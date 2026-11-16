"""Gaia DR3 reference catalogue (ESA Gaia archive TAP): explicit ADQL on gaiadr3.gaia_source,
recorded per field, epoch-propagated predictions for SPHEREx exposures.

Live access happens only in `python -m skyshift.providers.gaia_dr3.fetch` (explicit
command). The API serves predictions from the committed response + manifest under
fixtures/gaia_dr3/<field>/ and never queries the archive during a browser action.
Catalogue values are origin 'catalog'; positions at an exposure epoch are origin
'model_prediction'. A Gaia non-detection is never evidence of a new object.
"""

from __future__ import annotations

import hashlib
import json
import threading

from skyshift.contracts import Epoch, ProviderCapability, ProviderStatus, SkyPosition
from skyshift.providers.archive_common import live_status
from skyshift.providers.base import ProviderUnavailable
from skyshift.providers.gaia_dr3 import reference as ref
from skyshift.providers.gaia_dr3.catalog import GaiaCatalog, parse_gaia_votable, schema_checks, source_id_string
from skyshift.providers.gaia_dr3.paths import manifest_path, response_path
from skyshift.providers.gaia_dr3.rows import build_cone_query, gaia_row_to_catalog_source

GAIA_TABLE = ref.GAIA_TABLE
GAIA_RELEASE = ref.GAIA_RELEASE

# Live tests whose recorded result (validation/report.json) sets the live capability status.
LIVE_TESTS = {
    "query": "test_live_gaia_field_query_matches_recorded",
    "epoch_prop": "test_live_gaia_archive_propagation_agrees",
}


def _cap(name: str, status: str, detail: str, checked: str | None = None) -> ProviderCapability:
    return ProviderCapability(name=name, status=status, detail=detail, checked_utc=checked)  # type: ignore[arg-type]


class RecordedField:
    """One field's recorded Gaia DR3 response, verified against its manifest."""

    def __init__(self, field_id: str, manifest: dict, catalog: GaiaCatalog):
        self.field_id = field_id
        self.manifest = manifest
        self.catalog = catalog

    @property
    def retrieved_utc(self) -> str:
        return self.manifest["retrieved_utc"]


_lock = threading.Lock()
_cache: dict[tuple[str, float, float], RecordedField] = {}


def recorded_fields() -> list[str]:
    from skyshift.providers.gaia_dr3.paths import FIXTURE_ROOT

    if not FIXTURE_ROOT.exists():
        return []
    return sorted(p.parent.name for p in FIXTURE_ROOT.glob("*/manifest.json"))


def load_recorded_field(field_id: str) -> RecordedField:
    """Read and verify the committed response (sha256 vs manifest, schema/provenance checks); raises ProviderUnavailable."""
    mpath, rpath = manifest_path(field_id), response_path(field_id)
    if not mpath.exists() or not rpath.exists():
        raise ProviderUnavailable("gaia_dr3", "load_recorded_field",
                                  f"no recorded Gaia DR3 response for {field_id}; run: cd backend && uv run python -m skyshift.providers.gaia_dr3.fetch --field {field_id}")
    key = (field_id, mpath.stat().st_mtime, rpath.stat().st_mtime)
    with _lock:
        if key in _cache:
            return _cache[key]
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            expected_gz, expected_raw = manifest["field_query"]["response_sha256_gz"], manifest["field_query"]["response_sha256"]
            expected_rows = manifest["count_query"]["n_rows"]
            service = (manifest.get("service") or {}).get("id", "esa")
        except (OSError, ValueError, KeyError, TypeError) as exc:  # a broken manifest is not a recorded response
            raise ProviderUnavailable("gaia_dr3", "load_recorded_field", f"manifest for {field_id} unreadable ({type(exc).__name__}: {exc})") from None
        if service not in ref.SERVICES:
            raise ProviderUnavailable("gaia_dr3", "load_recorded_field", f"recorded response for {field_id} names an unknown service {service!r}")
        if not ref.SERVICES[service].archive_of_record:
            ver = (manifest.get("service") or {}).get("verification") or {}
            if ver.get("status") != "pass":
                raise ProviderUnavailable("gaia_dr3", "load_recorded_field", f"recorded response for {field_id} comes from {service!r} without a passing verification")
            if ver.get("reference_field") != field_id:  # the reference record itself is ESA's; check its identity against what is committed now
                try:
                    ref_m = json.loads(manifest_path(ver["reference_field"]).read_text(encoding="utf-8"))
                except (OSError, ValueError, KeyError) as exc:
                    raise ProviderUnavailable("gaia_dr3", "load_recorded_field", f"verification reference for {field_id} unreadable ({exc})") from None
                if ref_m["field_query"]["response_sha256_gz"] != ver.get("reference_response_sha256_gz"):
                    raise ProviderUnavailable("gaia_dr3", "load_recorded_field",
                                              f"{field_id} was verified against a different ESA reference response than the one committed now")
        gz = rpath.read_bytes()
        if hashlib.sha256(gz).hexdigest() != expected_gz:
            raise ProviderUnavailable("gaia_dr3", "load_recorded_field", f"recorded response for {field_id} does not match its manifest sha256")
        try:
            cat = parse_gaia_votable(gz)
        except Exception as exc:  # noqa: BLE001 - hash matched but the bytes do not parse: never serve partial data
            raise ProviderUnavailable("gaia_dr3", "load_recorded_field", f"recorded response for {field_id} does not parse ({type(exc).__name__})") from None
        cat.sha256 = expected_raw
        failed = [c for c in schema_checks(cat, expected_rows=expected_rows, service=service) if c.status == "fail"]
        if failed:
            raise ProviderUnavailable("gaia_dr3", "load_recorded_field", "recorded response fails checks: " + "; ".join(c.id for c in failed))
        rec = RecordedField(field_id, manifest, cat)
        _cache.clear()
        _cache[key] = rec
        return rec


class GaiaDR3Provider:
    id = "gaia_dr3"

    def status(self) -> ProviderStatus:
        live = {k: live_status(v) for k, v in LIVE_TESTS.items()}
        fields, last_ok = [], []
        for f in recorded_fields():
            try:
                m = json.loads(manifest_path(f).read_text(encoding="utf-8"))
                svc = m.get("service") or {"id": "esa", "name": ref.SERVICES["esa"].name}
                via = "" if svc["id"] == "esa" else (f" via {svc['name']} (partner data centre; verification {(svc.get('verification') or {}).get('status')}, "
                                                    f"cross-check {(svc.get('crosscheck') or {}).get('status')})")
                fields.append(f"{f}: {m['field_query']['n_rows']} sources recorded {m['retrieved_utc']}{via} (radius {m['geometry']['radius_deg']:.4f} deg)")
                rec = m["field_query"].get("record") or {}
                if svc["id"] == "esa":  # the live checks test the ESA archive: only its own retrievals are its last success
                    last_ok.append(f"{f} {m['retrieved_utc']} (HTTP {rec.get('status', '?')}, job {m['field_query'].get('job_id', '?')}, {m['field_query']['n_rows']} rows)")
            except (OSError, KeyError, ValueError) as exc:  # a broken manifest must not look recorded
                fields.append(f"{f}: manifest unreadable ({exc})")
        if last_ok:
            # An unreachable archive leaves the live checks without a result; the last successful retrieval is stated, never relabelled as a pass.
            suffix = " Last successful retrieval from the ESA archive (recorded, not a live check): " + "; ".join(last_ok) + "."
            live = {k: (s, t, d.rstrip(".") + "." + suffix) if s in ("unavailable", "failed", "not_run") else (s, t, d) for k, (s, t, d) in live.items()}
        return ProviderStatus(
            id="gaia_dr3",
            name="Gaia DR3 reference catalog (ESA)",
            role="catalog",
            status="implemented",
            release_policy=f"Pinned: {GAIA_RELEASE}, table {GAIA_TABLE} named explicitly in every ADQL query (never a changing default; not EDR3). "
                           "The archive's RELEASE parameter is checked in every response.",
            access_route=f"ESA Gaia archive TAP sync ({ref.TAP_SYNC_URL}, archive of record) with explicit ADQL, only through "
                         "`python -m skyshift.providers.gaia_dr3.fetch`; the API reads the committed response + manifest. When ESA is unreachable, a Gaia "
                         "partner data centre (ARI Heidelberg, AIP Potsdam; `--service`) is used only after it reproduces an ESA-recorded response exactly "
                         "(every row, value and NULL), optionally cross-checked against the other partner (`--crosscheck`).",
            capabilities=[
                _cap("Field query (ADQL on gaiadr3.gaia_source; footprint + proper-motion + neighbour margin)", live["query"][0], live["query"][2], live["query"][1]),
                _cap("Archive-side propagation cross-check (EPOCH_PROP)", live["epoch_prop"][0], live["epoch_prop"][2], live["epoch_prop"][1]),
                _cap("Schema / provenance checks (units, datatypes, RELEASE, COOSYS J2016.0, COUNT cross-check)", "implemented", "Run on every recorded and live response."),
                _cap("Epoch propagation (rigorous uniform space motion, 6x6 covariance) + observer parallax", "implemented",
                     "skyshift.science.epoch_propagation; checked against astropy/ERFA and the archive's own propagation."),
                _cap("Epoch-dependent overlay on SPHEREx frames (model predictions)", "implemented", "See the SPHEREx dataset capability 'catalog_overlay'."),
                _cap("Cross-matching with ambiguity handling (synthetic training data)", "implemented", "skyshift.science.catalog.associate."),
            ],
            references=ref.REFERENCES,
            notes=[ref.ACKNOWLEDGEMENT, "Gaia returns catalog records, not image frames. A Gaia non-detection is not evidence of a new object."] + fields,
            last_reviewed_utc=ref.DOC_REVIEW_UTC,
        )

    def query_region(self, center: SkyPosition, radius_deg: float, observation_epochs: list[Epoch]) -> list:
        raise ProviderUnavailable("gaia_dr3", "query_region",
                                  "the API never queries Gaia; use the recorded field responses (python -m skyshift.providers.gaia_dr3.fetch)")


__all__ = [
    "GAIA_RELEASE", "GAIA_TABLE", "GaiaDR3Provider", "LIVE_TESTS", "RecordedField", "build_cone_query",
    "gaia_row_to_catalog_source", "live_status", "load_recorded_field", "recorded_fields", "source_id_string",
]
