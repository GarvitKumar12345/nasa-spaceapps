"""Gaia DR3 provider checks.

Offline tests use the TAP responses recorded by `python -m skyshift.providers.gaia_dr3.fetch`
(fixtures/gaia_dr3/spherex-dr1-barnard/): the field query, an independent COUNT(*), the archive's
own propagation of a pinned subset (ESDC_EPOCH_PROP / ESDC_EPOCH_PROP_ERROR) and a MAXREC=5
truncation probe. Live tests (-m live) re-run the same requests against the ESA Gaia archive:
schema, provenance and pinned values must match exactly; a different row count is recorded as a
note in the validation report, not as a failure.
"""

from __future__ import annotations

import copy
import json
import math

import astropy.units as u
import numpy as np
import pytest
from astropy.time import Time

from skyshift.coords.tangent import angular_separation_deg
from skyshift.providers.gaia_dr3 import load_recorded_field, source_id_string
from skyshift.providers.gaia_dr3 import reference as ref
from skyshift.providers.gaia_dr3.catalog import parse_gaia_votable, schema_checks
from skyshift.providers.gaia_dr3.fetch import build_epoch_prop_query, gaia_client
from skyshift.providers.gaia_dr3.paths import OVERFLOW_PROBE_NAME, field_dir, manifest_path
from skyshift.providers.gaia_dr3.query import MAXREC, SearchGeometry, build_count_query, build_field_query, search_geometry
from skyshift.providers.gaia_dr3.rows import gaia_row_to_catalog_source
from skyshift.providers.spherex.fields import PRESETS

FIELD = "spherex-dr1-barnard"
BARNARD = "4472832130942575872"  # Gaia DR3 source_id of Barnard's Star (GJ 699), as published


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(manifest_path(FIELD).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recorded():
    return load_recorded_field(FIELD)


def _geometry(manifest: dict) -> SearchGeometry:
    return SearchGeometry(**{k: v for k, v in manifest["geometry"].items() if k != "derivation"})


# ---------------------------------------------------------------- query and search region


@pytest.mark.archive
def test_recorded_query_is_explicit_and_reproducible(manifest):
    """[archive] The recorded ADQL names gaiadr3.gaia_source with explicit columns, ORDER BY source_id and MAXREC, and equals the builder's output."""
    geom = _geometry(manifest)
    adql = manifest["field_query"]["adql"]
    assert build_field_query(geom) == adql and build_count_query(geom) == manifest["count_query"]["adql"]
    assert f"FROM {ref.GAIA_TABLE} WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', " in adql and adql.endswith("ORDER BY source_id")
    assert adql.startswith("SELECT " + ", ".join(ref.COLUMN_NAMES) + " FROM")
    form = manifest["field_query"]["form"]
    assert form == {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable", "MAXREC": str(MAXREC), "QUERY": adql}
    assert manifest["release"] == ref.GAIA_RELEASE and manifest["endpoint"] == ref.TAP_SYNC_URL
    assert "phot_g_mean_mag <" not in adql  # no magnitude cut: faint neighbours are needed for isolation tests


@pytest.mark.archive
def test_search_radius_covers_the_footprints_with_justified_margins(manifest, recorded):
    """[archive] Radius = largest cutout-corner distance + 10.5"/yr x dt_max + 6 px, re-derived independently; it is not the SIA point-in-image radius."""
    geom = _geometry(manifest)
    preset = PRESETS[FIELD]
    corners = np.array([c for f in manifest["footprints"] for c in f["corners_icrs_deg"]])
    sep = angular_separation_deg(corners[:, 0], corners[:, 1], preset.ra_deg, preset.dec_deg)
    assert float(sep.max()) == pytest.approx(geom.footprint_radius_deg, abs=1e-9)
    # dt from J2016.0 (TCB) to each exposure mid-time (UTC), independently with astropy (Julian years of 365.25 d)
    t0 = Time(ref.REFERENCE_EPOCH_JYEAR, format="jyear", scale="tcb")
    dts = [float(((Time(f["mid_utc"], scale="utc") - t0).to(u.day) / (365.25 * u.day)).value) for f in manifest["footprints"]]
    assert max(dts) == pytest.approx(geom.dt_max_yr, abs=2e-9)
    # the proper-motion margin bounds the fastest star actually in the response (Barnard's Star, 10.39"/yr)
    pm = np.hypot(np.nan_to_num(recorded.catalog.columns["pmra"]), np.nan_to_num(recorded.catalog.columns["pmdec"])) / 1000.0
    assert recorded.catalog.source_id[int(np.argmax(pm))] == BARNARD and pm.max() < geom.max_proper_motion_arcsec_yr
    expected = geom.footprint_radius_deg + geom.max_proper_motion_arcsec_yr * geom.dt_max_yr / 3600 + geom.neighbour_margin_px * geom.pixel_scale_arcsec / 3600
    assert geom.radius_deg >= expected and geom.radius_deg - expected < 1e-7
    assert geom.radius_deg > 300 * preset.search_radius_deg  # never the 0.0003 deg SIA discovery radius
    rebuilt = search_geometry(preset.ra_deg, preset.dec_deg, geom.footprint_radius_deg, geom.dt_max_yr)
    assert rebuilt == geom
    with pytest.raises(ValueError):
        search_geometry(preset.ra_deg, preset.dec_deg, geom.footprint_radius_deg, geom.dt_max_yr, max_proper_motion_arcsec_yr=5.0)


# ---------------------------------------------------------------- recorded response


@pytest.mark.archive
def test_recorded_response_passes_schema_and_provenance_checks(recorded, manifest):
    """[archive] Units, datatypes, RELEASE, COOSYS J2016.0, QUERY_STATUS, ref_epoch, solution codes and the independent COUNT(*) all pass on the committed response."""
    checks = schema_checks(recorded.catalog, expected_rows=manifest["count_query"]["n_rows"])
    assert {c.id for c in checks} == {"columns", "units", "datatypes", "release", "table", "coosys", "query_status", "ref_epoch", "source_ids", "solution_types", "row_count"}
    assert [c.id for c in checks if c.status != "pass"] == []
    assert len(recorded.catalog) == manifest["count_query"]["n_rows"] == manifest["field_query"]["n_rows"]
    assert [c["status"] for c in manifest["checks"]] == ["pass"] * len(manifest["checks"])
    aps = recorded.catalog.columns["astrometric_params_solved"]
    assert set(np.unique(aps).astype(int)) == {3, 31, 95}


@pytest.mark.archive
def test_checks_detect_schema_provenance_and_truncation_problems(recorded):
    """[archive] A changed unit, a different RELEASE, a missing column or a count mismatch fail their checks; the recorded MAXREC=5 probe is detected as OVERFLOW."""
    probe = parse_gaia_votable((field_dir(FIELD) / OVERFLOW_PROBE_NAME).read_bytes())
    assert len(probe) == 5 and probe.infos["QUERY_STATUS"] == "OVERFLOW"
    assert probe.infos["QUERY_STATUS_ALL"].split(",")[0] == "OK"  # the leading INFO says OK: only the trailing one reveals truncation
    assert {c.id: c.status for c in schema_checks(probe)}["query_status"] == "fail"
    cat = copy.deepcopy(recorded.catalog)
    next(f for f in cat.fields if f.name == "pmra").unit = "mas"
    cat.params["RELEASE"] = "Gaia EDR3"
    cat.fields = [f for f in cat.fields if f.name != "ruwe"]
    status = {c.id: c.status for c in schema_checks(cat, expected_rows=len(cat) + 1)}
    assert status["units"] == "fail" and status["release"] == "fail" and status["columns"] == "fail" and status["row_count"] == "fail"


@pytest.mark.contracts
def test_source_ids_stay_exact_decimal_strings(recorded):
    """[contracts] Gaia source_ids (all > 2^53 here) are exact strings in the parser, CatalogSource and JSON; a float would corrupt them and is refused."""
    ids = recorded.catalog.source_id
    assert all(isinstance(s, str) and s.isdigit() for s in ids) and BARNARD in recorded.catalog.index
    assert all(int(s) > 2**53 for s in ids)
    corrupted = [s for s in ids if str(int(float(s))) != s]
    # what a JavaScript number / float64 round trip would do (float64 spacing is 1024 at ~4.5e18)
    assert len(corrupted) > 0.5 * len(ids) and BARNARD in corrupted and str(int(float(BARNARD))) == "4472832130942575616"
    with pytest.raises(TypeError):
        source_id_string(float(BARNARD))
    with pytest.raises(ValueError):
        source_id_string("4472832130942575872.0")
    src = gaia_row_to_catalog_source(recorded.catalog.row(recorded.catalog.index[BARNARD]))
    assert src.source_id == BARNARD and src.id == f"gaiadr3:{BARNARD}"
    data = json.loads(src.model_dump_json())
    assert isinstance(data["source_id"], str) and data["source_id"] == BARNARD


@pytest.mark.archive
def test_pinned_rows_equal_the_committed_response(recorded, manifest):
    """[archive] Every pinned row recorded in the manifest (fastest star, bright clean stars, one 2-parameter source) equals the committed response."""
    pinned = manifest["pinned_sources"]
    assert pinned[0]["source_id"] == BARNARD and any(p["astrometric_params_solved"] == 3 for p in pinned)
    for row in pinned:
        live = recorded.catalog.row(recorded.catalog.index[row["source_id"]])
        assert set(live) == set(row)
        for k, v in row.items():
            assert live[k] == v, (row["source_id"], k)


@pytest.mark.catalog
def test_barnards_star_row_and_documented_conventions(recorded):
    """[catalog] Barnard's Star keeps its published DR3 values and the J2016.0 TCB epoch; 2-parameter rows have NULL parallax/pm and become unpropagatable sources."""
    row = recorded.catalog.row(recorded.catalog.index[BARNARD])
    assert row["ref_epoch"] == 2016.0 and row["astrometric_params_solved"] == 31
    assert math.hypot(row["pmra"], row["pmdec"]) == pytest.approx(10393.35, abs=0.05)
    assert row["parallax"] == pytest.approx(546.976, abs=0.001) and row["radial_velocity"] == pytest.approx(-110.468, abs=0.001)
    src = gaia_row_to_catalog_source(row)
    assert (src.reference_epoch.value, src.reference_epoch.format, src.reference_epoch.scale) == (2016.0, "jyear", "tcb")
    two = next(i for i, v in enumerate(recorded.catalog.columns["astrometric_params_solved"]) if v == 3)
    s2 = gaia_row_to_catalog_source(recorded.catalog.row(two))
    assert s2.astrometric_solution == "2-parameter" and s2.pmra_mas_yr is None and "NO_PROPER_MOTION" in s2.quality.flags


@pytest.mark.archive
def test_epoch_prop_check_query_is_recorded(manifest):
    """[archive] The archive-side propagation query covers every exposure epoch (TCB Julian years) for the pinned sources and is labelled a check only."""
    ep = manifest["epoch_prop"]
    assert ep["status"] == "recorded" and ep["adql"] == build_epoch_prop_query([p["source_id"] for p in manifest["pinned_sources"]], ep["target_epochs_jyear_tcb"])
    mids = sorted({round(float(Time(f["mid_utc"], scale="utc").tcb.jyear), 8) for f in manifest["footprints"]})
    assert ep["target_epochs_jyear_tcb"] == pytest.approx(mids, abs=1e-8)
    assert "never used for predictions" in ep["note"]


@pytest.mark.contracts
def test_live_status_separates_unreachable_services_from_failed_checks(monkeypatch):
    """[contracts] A live test that never reached the archive maps to 'unavailable'; a real check failure stays 'failed'; a pass with a count note is 'tested'."""
    from skyshift.contracts import TestResult, ValidationReport
    from skyshift.providers import archive_common

    def report_with(status: str, message: str | None, notes: list[str] | None = None) -> ValidationReport:
        r = TestResult(id="tests/test_gaia_dr3.py::test_live_x", name="x", suite="pytest", category="live", status=status, message=message, notes=notes or [])
        return ValidationReport(generated_utc="2026-11-15T00:00:00Z", source_hash="h", results=[r], available=True)

    import skyshift.validation.report as rep_mod

    timeout = ("E   skyshift.providers.spherex.http.ArchiveRequestFailed: URLError: <urlopen error [WinError 10060] A connection attempt failed> "
               "(https://gea.esac.esa.int/tap-server/tap/sync, attempts=6)")
    monkeypatch.setattr(rep_mod, "load_report", lambda: report_with("failed", timeout))
    status, _, detail = archive_common.live_status("test_live_x")
    assert status == "unavailable" and "could not reach the service" in detail
    monkeypatch.setattr(rep_mod, "load_report", lambda: report_with("failed", "E   AssertionError: pinned source 123 missing"))
    assert archive_common.live_status("test_live_x")[0] == "failed"
    monkeypatch.setattr(rep_mod, "load_report", lambda: report_with("failed", "ArchiveRequestFailed: HTTP 400 Bad Request (…)"))
    assert archive_common.live_status("test_live_x")[0] == "failed"  # the service answered and refused the request
    monkeypatch.setattr(rep_mod, "load_report", lambda: report_with("passed", None, ["Gaia row count changed: 3181 live vs 3180 recorded"]))
    status, _, detail = archive_common.live_status("test_live_x")
    assert status == "tested" and "row count changed" in detail


@pytest.mark.archive
def test_partner_service_records_need_an_exact_verification_against_the_esa_record(recorded, tmp_path, monkeypatch):
    """[archive] The identity comparison catches one changed value, a changed NULL pattern and a missing row; the schema
    checks stay strict for ESA (no RELEASE -> fail) while a partner service's missing RELEASE/COOSYS are stated warnings;
    a partner-service record loads only with a passing verification against the ESA reference committed now."""
    import copy
    import shutil

    import skyshift.providers.gaia_dr3 as gaia
    from skyshift.providers.gaia_dr3.catalog import GaiaCatalog, schema_checks
    from skyshift.providers.gaia_dr3.fetch import compare_catalogs
    from skyshift.providers.base import ProviderUnavailable

    cat = recorded.catalog
    assert compare_catalogs(cat, cat)["identical"]
    cols = {k: v.copy() for k, v in cat.columns.items()}
    null = {k: v.copy() for k, v in cat.null.items()}
    cols["pmra"][5] += 1e-9
    assert not compare_catalogs(cat, GaiaCatalog(list(cat.source_id), cols, null, cat.fields, cat.infos, cat.params, cat.coosys))["columns"]["pmra"]["identical"]
    null2 = {k: v.copy() for k, v in cat.null.items()}
    null2["radial_velocity"][0] = not null2["radial_velocity"][0]
    assert not compare_catalogs(cat, GaiaCatalog(list(cat.source_id), {k: v.copy() for k, v in cat.columns.items()}, null2, cat.fields, cat.infos, cat.params, cat.coosys))["identical"]
    short = GaiaCatalog(cat.source_id[1:], {k: v[1:] for k, v in cat.columns.items()}, {k: v[1:] for k, v in cat.null.items()}, cat.fields, cat.infos, cat.params, cat.coosys)
    assert not compare_catalogs(cat, short)["identical"]
    bare = GaiaCatalog(list(cat.source_id), cat.columns, cat.null, cat.fields, cat.infos, {}, [])
    by = lambda checks: {c.id: c.status for c in checks}  # noqa: E731
    assert by(schema_checks(bare, service="esa"))["release"] == "fail" and by(schema_checks(bare, service="esa"))["coosys"] == "fail"
    assert by(schema_checks(bare, service="ari"))["release"] == "warn" and by(schema_checks(bare, service="ari"))["coosys"] == "warn"
    # a partner record: refused without a passing verification, or when verified against another ESA reference
    field = tmp_path / "f"
    field.mkdir()
    shutil.copy(gaia.response_path("spherex-dr1-barnard"), field / "r.vot.gz")
    m = copy.deepcopy(recorded.manifest)
    m["service"] = {"id": "ari", "verification": {"status": "fail", "reference_field": "spherex-dr1-barnard"}}
    (field / "m.json").write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(gaia, "manifest_path", lambda f: field / "m.json" if f == "x-field" else gaia.paths.manifest_path(f))
    monkeypatch.setattr(gaia, "response_path", lambda f: field / "r.vot.gz" if f == "x-field" else gaia.paths.response_path(f))
    with pytest.raises(ProviderUnavailable, match="without a passing verification"):
        gaia.load_recorded_field("x-field")
    m["service"]["verification"] = {"status": "pass", "reference_field": "spherex-dr1-barnard", "reference_response_sha256_gz": "0" * 64}
    (field / "m.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ProviderUnavailable, match="different ESA reference"):
        gaia.load_recorded_field("x-field")


@pytest.mark.archive
def test_vanmaanen2_record_came_from_a_verified_partner_service_with_an_identical_crosscheck():
    """[archive] The committed van Maanen 2 record: ARI reproduced the ESA-recorded reference response exactly, AIP returned an
    identical field response, the row count equals the independent COUNT, and the loader accepts it as Gaia DR3."""
    from skyshift.providers.gaia_dr3 import load_recorded_field

    rec = load_recorded_field("spherex-dr1-vanmaanen2")
    s = rec.manifest["service"]
    assert s["id"] == "ari" and not s["archive_of_record"] and s["verification"]["status"] == "pass"
    assert s["verification"]["comparison"]["identical"] and s["verification"]["comparison"]["n_rows_other"] == 3180
    assert s["crosscheck"]["status"] == "pass" and s["crosscheck"]["comparison"]["identical"]
    assert rec.manifest["field_query"]["n_rows"] == rec.manifest["count_query"]["n_rows"] == len(rec.catalog)
    assert "2552928187080872832" in rec.catalog.index  # van Maanen 2 (identified by propagation in scripts/target_astrometry.py)


@pytest.mark.contracts
def test_unreachable_live_checks_keep_their_status_and_state_the_last_successful_retrieval(monkeypatch, manifest):
    """[contracts] With the ESA archive unreachable in the latest run, both live Gaia capabilities read 'unavailable'
    (never 'tested') and name the last successful retrieval recorded in the manifest (time, HTTP status, job id)."""
    from skyshift.contracts import TestResult, ValidationReport
    from skyshift.providers.gaia_dr3 import LIVE_TESTS, GaiaDR3Provider

    import skyshift.validation.report as rep_mod

    msg = "E   ArchiveRequestFailed: URLError: <urlopen error [WinError 10060] A connection attempt failed> (attempts=6)"
    results = [TestResult(id=f"tests/test_gaia_dr3.py::{t}", name=t, suite="pytest", category="live", status="failed", message=msg) for t in LIVE_TESTS.values()]
    monkeypatch.setattr(rep_mod, "load_report", lambda: ValidationReport(generated_utc="2026-11-15T21:00:00Z", source_hash="h", results=results, available=True))
    caps = GaiaDR3Provider().status().capabilities[:2]
    for c in caps:
        assert c.status == "unavailable" and c.checked_utc == "2026-11-15T21:00:00Z"
        assert "Last successful retrieval" in c.detail and manifest["retrieved_utc"] in c.detail and manifest["field_query"]["job_id"] in c.detail


# ---------------------------------------------------------------- live (ESA Gaia archive)


@pytest.mark.live
def test_live_gaia_field_query_matches_recorded(manifest, record_property):
    """[live] Gaia DR3: the recorded ADQL re-run on the ESA archive passes schema/provenance checks and returns the pinned rows unchanged; a changed row count is a note."""
    body, rec = gaia_client().post_form(ref.TAP_SYNC_URL, manifest["field_query"]["form"], max_bytes=30_000_000)
    cat = parse_gaia_votable(body)
    failed = [f"{c.id}: {c.detail}" for c in schema_checks(cat) if c.status == "fail"]
    assert rec.status == 200 and failed == []
    for row in manifest["pinned_sources"]:
        assert row["source_id"] in cat.index, f"pinned source {row['source_id']} missing"
        live = cat.row(cat.index[row["source_id"]])
        assert {k: live[k] for k in row} == row
    n0 = manifest["field_query"]["n_rows"]
    if len(cat) != n0:
        record_property("note", f"Gaia row count changed: {len(cat)} live vs {n0} recorded for the same ADQL (DR3 is frozen); schema, provenance "
                                "and pinned values unchanged. Reported, not a failure.")
    else:
        same = rec.sha256 == manifest["field_query"]["response_sha256"]
        record_property("note", f"Gaia row count unchanged ({n0} rows); response bytes {'identical' if same else 'differ (job id / metadata only)'}.")


@pytest.mark.live
def test_live_gaia_archive_propagation_agrees(manifest, record_property):
    """[live] Gaia DR3: the archive's ESDC_EPOCH_PROP for the pinned sources, re-run live, equals the recorded values to 1e-9 mas."""
    body, rec = gaia_client().post_form(ref.TAP_SYNC_URL, {**manifest["field_query"]["form"], "QUERY": manifest["epoch_prop"]["adql"]}, max_bytes=5_000_000)
    from skyshift.providers.gaia_dr3.paths import epoch_prop_path

    live = parse_gaia_votable(body)
    old = parse_gaia_votable(epoch_prop_path(FIELD).read_bytes())
    assert rec.status == 200 and live.source_id == old.source_id and set(live.columns) == set(old.columns)
    for name in old.columns:
        assert np.allclose(np.asarray(old.columns[name], dtype=float), np.asarray(live.columns[name], dtype=float), rtol=0, atol=1e-9, equal_nan=True), name
    record_property("note", f"{len(live)} pinned sources x {len(manifest['epoch_prop']['target_epochs_jyear_tcb'])} epochs re-propagated by the archive.")
