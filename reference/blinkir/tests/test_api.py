from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["channels"] == 102


def test_presets():
    res = client.get("/api/presets")
    assert res.status_code == 200
    targets = res.json()["targets"]
    assert len(targets) == 5
    ids = {t["id"] for t in targets}
    assert "WISE_0855" in ids
    assert "Barnards_Star" in ids


def test_wise_0855_cutout_and_spectrum():
    res = client.get("/api/sky-cutout?query=WISE_0855")
    assert res.status_code == 200
    data = res.json()
    assert len(data["epoch1_image"]) == 64
    assert len(data["epoch2_image"]) == 64
    assert len(data["difference_image"]) == 64
    assert len(data["spectrum_102"]) == 102
    assert data["flag_status"] == "CLEAN"


def test_export_discovery_card():
    payload = {
        "target_name": "WISE 0855",
        "ra": 133.795129,
        "dec": -7.245147,
        "fov_deg": 0.04,
        "measured_shift_arcsec": 4.06,
        "proper_motion_arcsec_yr": 8.13,
        "flag_status": "CLEAN",
    }
    res = client.post("/api/export-candidate", json=payload)
    assert res.status_code == 200
    assert res.json()["schema"].startswith("SkyShift-NASA-SpaceApps-2026")

