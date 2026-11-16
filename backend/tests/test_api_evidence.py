"""HTTP API, evidence-record, and provider-boundary checks."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from skyshift.api.app import app
from skyshift.contracts import EvidenceRecord, ProviderStatus
from skyshift.providers.base import ProviderUnavailable
from skyshift.providers.extensions import NeossatProvider, WiseProvider
from skyshift.providers.gaia_dr3 import GAIA_TABLE, GaiaDR3Provider, build_cone_query, gaia_row_to_catalog_source
from skyshift.providers.registry import provider_statuses
from skyshift.providers.spherex import SpherexProvider, check_extension_names


@pytest.fixture(scope="module")
def client(investigation):  # investigation fixture warms the cache
    return TestClient(app)


@pytest.fixture(scope="module")
def record(client, c1_id) -> dict:
    """An evidence record built only from API responses (as the browser does)."""
    ds = client.get("/api/datasets/syn-nb-01").json()
    ms = client.get(f"/api/datasets/syn-nb-01/sources/{c1_id}/measurements").json()["measurements"]
    fit = client.post("/api/fits/astrometric", json={"dataset_id": "syn-nb-01", "source_id": c1_id, "model": "proper_motion_parallax", "measurements": ms}).json()
    src = next(s for s in client.get("/api/datasets/syn-nb-01/sources").json() if s["id"] == c1_id)
    return {
        "schema_version": "skyshift.evidence/1", "contracts_version": "skyshift.contracts/1", "id": "8d1b7a54-1111-4c2e-9f00-0000000000aa",
        "created_utc": "2026-11-14T10:00:00Z", "updated_utc": "2026-11-14T10:00:00Z", "title": f"{c1_id} candidate", "record_label": "synthetic training record",
        "dataset": {"dataset_id": "syn-nb-01", "provider": "synthetic", "origin": "simulated", "release": ds["release"], "generator": ds["generator"],
                    "generator_version": ds["generator_version"], "seed": ds["seed"], "scenario_parameters": None},
        "source": {"source_id": c1_id, "label": c1_id, "reference_position": src["position"], "origin": "derived_measurement", "catalog_associations": []},
        "selection": {"band_ids": ["G1", "G2"], "frame_ids": [], "observation_ids": [], "epochs": [],
                      "view": {"mode": "analyze", "band_id": "G1", "frame_id": None, "compare_frame_id": None, "center_x_px": None, "center_y_px": None, "zoom": None, "fov_arcsec": None, "stretch": {}}},
        "measurements": ms, "included_measurement_ids": [m["id"] for m in ms if m["status"] == "measured"], "fit": fit, "fit_status": "current",
        "assumptions": [], "quality_flags": [], "notes": "",
        "simulation": {"seed": ds["seed"], "generator": ds["generator"], "generator_version": ds["generator_version"], "truth": None},
        "provenance": {"origin": "derived_measurement", "provider": "skyshift", "dataset_id": "syn-nb-01", "release": None, "processing_version": None,
                       "source_url": None, "retrieved_utc": None, "method": "test", "method_version": "0", "parents": [], "software": [], "notes": []},
    }


@pytest.mark.api
def test_core_routes_return_contracts(client):
    """Health, providers, datasets, dataset and sources respond with contract-shaped JSON."""
    assert client.get("/api/health").json()["contracts_version"] == "skyshift.contracts/1.1"
    assert [p["id"] for p in client.get("/api/providers").json()] == ["synthetic", "spherex", "gaia_dr3", "wise", "neossat"]
    listed = client.get("/api/datasets").json()
    assert listed[0]["id"] == "syn-nb-01" and listed[0]["origin"] == "simulated"  # synthetic training data stays the default
    assert all(d["origin"] == "observed" and d["provider"] == "spherex" for d in listed[1:])
    ds = client.get("/api/datasets/syn-nb-01").json()
    kinds = {f["kind"] for f in ds["frames"]}
    assert kinds == {"native", "registered"} and all(f["display_only"] for f in ds["frames"] if f["kind"] == "registered")
    assert len(client.get("/api/datasets/syn-nb-01/sources").json()) > 20


@pytest.mark.api
def test_pixel_planes_binary_format(client):
    """Pixel planes: shape/dtype headers match the payload; registered images use NaN outside coverage; masks are uint16."""
    r = client.get("/api/datasets/syn-nb-01/frames/syn-nb-01:v01:G1:registered/pixels?plane=image")
    ny, nx = map(int, r.headers["x-skyshift-shape"].split(","))
    data = np.frombuffer(r.content, "<f4")
    assert data.size == ny * nx and r.headers["x-skyshift-display-only"] == "true" and np.isnan(data).any()
    r = client.get("/api/datasets/syn-nb-01/frames/syn-nb-01:v01:G1:native/pixels?plane=mask")
    assert r.headers["x-skyshift-dtype"] == "uint16" and len(r.content) == 160 * 160 * 2
    assert client.get("/api/datasets/syn-nb-01/frames/syn-nb-01:v01:G1:registered/pixels?plane=variance").status_code == 422


@pytest.mark.api
def test_error_responses(client):
    """Unknown ids -> 404 not_found; incompatible difference -> 409; archive stubs -> 503 (never synthetic data)."""
    assert client.get("/api/datasets/nope").json()["detail"]["code"] == "not_found"
    assert client.get("/api/datasets/syn-nb-01/sources/S999/measurements").status_code == 404
    r = client.get("/api/datasets/syn-nb-01/difference/pixels?a=syn-nb-01:v01:G1:registered&b=syn-nb-01:v01:G2:registered")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "incompatible_frames"
    with pytest.raises(ProviderUnavailable):
        SpherexProvider().load_dataset("anything")


@pytest.mark.api
def test_resolve_coordinates_source_ids_and_names(client):
    """Decimal and sexagesimal coordinates parse; source ids resolve; target names are honestly unresolved."""
    get = lambda q: client.get("/api/resolve", params={"q": q, "dataset_id": "syn-nb-01"}).json()  # noqa: E731
    a, b = get("180 35"), get("12:00:00 +35:00:00")
    assert a["kind"] == b["kind"] == "coordinates" and math.isclose(a["position"]["ra_deg"], b["position"]["ra_deg"], abs_tol=1e-9)
    assert a["in_dataset_field"] is True and get("10 10")["in_dataset_field"] is False
    assert get("S003")["kind"] == "source_id"
    assert get("Barnard's Star")["kind"] == "unresolved"


@pytest.mark.api
def test_truth_is_separate_endpoint(client):
    """Simulation truth is served only by /truth, labelled simulation_truth."""
    t = client.get("/api/datasets/syn-nb-01/truth").json()
    assert t["origin"] == "simulation_truth" and "not measurements" in t["warning"]


@pytest.mark.contracts
def test_evidence_validate_reproduce_and_stale_detection(client, record):
    """A record built from API output validates as current, reproduces from its seed, and goes stale when inputs change."""
    v = client.post("/api/evidence/validate", json=record).json()
    assert v["valid"] and v["recomputed_fit_status"] == "current" and v["fit_input_hash_matches"]
    rep = client.post("/api/evidence/reproduce", json=record).json()
    assert rep["status"] == "reproduced" and all(c["passed"] for c in rep["checks"]) and len(rep["checks"]) > 50
    tampered = copy.deepcopy(record)
    tampered["measurements"][0]["ra_deg"] += 1e-7
    assert client.post("/api/evidence/validate", json=tampered).json()["recomputed_fit_status"] == "stale"
    fewer = copy.deepcopy(record)
    fewer["included_measurement_ids"] = fewer["included_measurement_ids"][1:]
    assert client.post("/api/evidence/validate", json=fewer).json()["recomputed_fit_status"] == "stale"


@pytest.mark.contracts
def test_evidence_round_trip_preserves_everything(record):
    """JSON export -> import round trip is lossless (origins, units, uncertainties, assumptions, provenance)."""
    parsed = EvidenceRecord.model_validate(record)
    again = EvidenceRecord.model_validate_json(parsed.model_dump_json())
    assert again == parsed
    assert all(m.origin == "derived_measurement" for m in again.measurements)


@pytest.mark.contracts
def test_evidence_rejects_bad_records(client, record):
    """Unsupported schema, wrong label for the origin, and dangling included ids are rejected with reasons."""
    assert not client.post("/api/evidence/validate", json={"schema_version": "x"}).json()["valid"]
    wrong = copy.deepcopy(record)
    wrong["record_label"] = "candidate for review"
    out = client.post("/api/evidence/validate", json=wrong).json()
    assert not out["valid"] and any("synthetic training record" in e for e in out["errors"])
    dangling = copy.deepcopy(record)
    dangling["included_measurement_ids"].append("nope")
    assert not client.post("/api/evidence/validate", json=dangling).json()["valid"]
    assert client.post("/api/evidence/reproduce", json={"schema_version": "x"}).status_code == 422


@pytest.mark.contracts
def test_evidence_csv_keeps_origin_units_and_rows(client, record):
    """CSV export: header comments state the label, origin and units; one row per measurement with origin and included flag."""
    text = client.post("/api/evidence/csv", json=record).text
    lines = text.splitlines()
    comments = [ln for ln in lines if ln.startswith("#")]
    rows = [ln for ln in lines if not ln.startswith("#")]
    assert any("synthetic training record" in c for c in comments) and any("units:" in c for c in comments)
    assert rows[0].startswith("record_id,") and len(rows) - 1 == len(record["measurements"])
    assert all(",derived_measurement," in r for r in rows[1:])


@pytest.mark.contracts
def test_provider_statuses_are_honest():
    """All five providers listed; 'tested' appears only for SPHEREx/Gaia live checks recorded in the report; WISE/NEOSSat are documented, not run."""
    statuses = [ProviderStatus.model_validate(s.model_dump()) for s in provider_statuses()]
    assert [s.id for s in statuses] == ["synthetic", "spherex", "gaia_dr3", "wise", "neossat"]
    assert all(s.status != "tested" for s in statuses)
    for s in statuses:
        for c in s.capabilities:
            if c.status == "tested":
                assert s.id in ("spherex", "gaia_dr3") and c.checked_utc and "live test" in c.detail
    assert statuses[1].status == "implemented" and statuses[2].status == "implemented"
    for s in statuses[3:]:
        assert s.status == "documented" and any(c.status == "not_run" for c in s.capabilities)
    for provider in (SpherexProvider(), WiseProvider(), NeossatProvider()):
        with pytest.raises(ProviderUnavailable):
            provider.load_dataset("x")
    with pytest.raises(ProviderUnavailable):
        GaiaDR3Provider().query_region(None, 0.01, [])  # type: ignore[arg-type]


@pytest.mark.contracts
def test_gaia_query_is_explicit_and_bounded():
    """The ADQL query names gaiadr3.gaia_source explicitly with TOP and refuses unbounded radii."""
    q = build_cone_query(180.0, 35.0, 0.02, 500)
    assert f"FROM {GAIA_TABLE}" in q and q.startswith("SELECT TOP 500") and "ref_epoch" in q
    with pytest.raises(ValueError):
        build_cone_query(180.0, 35.0, 5.0)


@pytest.mark.contracts
def test_gaia_row_mapping_on_hand_constructed_rows():
    """Hand-constructed rows (not a live response): 2/5/6-parameter solutions, NaN -> None, missing RV -> None, J2016.0 TCB kept."""
    base = {"source_id": 123, "ref_epoch": 2016.0, "ra": 180.0, "dec": 35.0, "ra_error": 0.1, "dec_error": 0.1, "parallax": 2.5,
            "parallax_error": 0.2, "pmra": 10.0, "pmra_error": 0.2, "pmdec": -5.0, "pmdec_error": 0.2, "ra_dec_corr": 0.1,
            "astrometric_params_solved": 31, "ruwe": 1.02, "phot_g_mean_mag": 15.0, "radial_velocity": float("nan")}
    five = gaia_row_to_catalog_source(base)
    assert five.astrometric_solution == "5-parameter" and five.radial_velocity_km_s is None and five.correlations == {"ra_dec_corr": 0.1}
    assert (five.reference_epoch.value, five.reference_epoch.format, five.reference_epoch.scale) == (2016.0, "jyear", "tcb")
    assert five.origin == "catalog" and five.catalog == GAIA_TABLE
    two = gaia_row_to_catalog_source({**base, "astrometric_params_solved": 3, "parallax": float("nan")})
    assert two.astrometric_solution == "2-parameter" and two.parallax_mas is None and two.pmra_mas_yr is None
    six = gaia_row_to_catalog_source({**base, "astrometric_params_solved": 95, "radial_velocity": 12.5})
    assert six.astrometric_solution == "6-parameter" and six.radial_velocity_km_s == 12.5


@pytest.mark.contracts
def test_spherex_extension_check():
    """Extensions are checked by name (case-insensitive) against the R7 (DR1/QR3) layout verified on real files (EPSF, not PSF)."""
    assert check_extension_names(["image", "FLAGS", "VARIANCE", "ZODI", "EPSF", "WCS-WAVE"]) == []
    assert check_extension_names(["IMAGE", "FLAGS"]) == ["VARIANCE", "ZODI", "EPSF", "WCS-WAVE"]


@pytest.mark.api
def test_validation_endpoint_reports_staleness_fields(client):
    """The validation endpoint always returns a current source hash and never fabricates results when no report exists."""
    v = client.get("/api/validation").json()
    assert v["current_source_hash"]
    if not v["available"]:
        assert v["results"] == [] and v["stale"] is None
