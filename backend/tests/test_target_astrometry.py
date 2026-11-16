"""Target astrometry (skyshift.science.target_astrometry): the measurement cannot be pulled by the prediction, the error
budget maps pixel terms to the sky correctly, and the recorded van Maanen 2 results keep measurements and predictions
apart. The injected star is rendered by photutils from a real SPHEREx zone ePSF (an implementation independent of the
fitter's evaluation)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from skyshift.science import target_astrometry as ta
from skyshift.science.alignment import FrameInputs

VM2 = "spherex-dr1-vanmaanen2"


@pytest.fixture(scope="module")
def lib():
    from astropy.io import fits

    from skyshift.imaging.epsf import EPSFLibrary
    from skyshift.providers.spherex.paths import FIXTURE_ROOT

    return EPSFLibrary.from_hdu(fits.open(FIXTURE_ROOT / "spherex-dr1-barnard" / "fixture_cutout_D1_trimmed_epsf.fits")["EPSF"])


def _frame(lib, x0, y0, flux, sigma, rng, extra=None):  # noqa: ANN001, ANN202
    """A constructed frame (not archive data): photutils rendering of zone 0 at (x0, y0) plus white noise."""
    pytest.importorskip("photutils")
    from photutils.psf import ImagePSF

    ox, oy = lib.oversampling
    ip = ImagePSF(data=lib.arrays[0] * ox * oy, oversampling=(oy, ox))
    yy, xx = np.mgrid[0:41, 0:41]
    img = ip.evaluate(xx, yy, flux=flux, x_0=x0, y_0=y0) + 20.0
    for ex, ey, ef in extra or []:
        img = img + ip.evaluate(xx, yy, flux=ef, x_0=ex, y_0=ey)
    img = img + rng.normal(0, sigma, img.shape)
    z = lib.zones[0]
    off = (z.x_center - 20.0, z.y_center - 20.0)  # puts the cutout at the zone centre: zone lookups return zone 0
    return FrameInputs(frame_id="constructed", image=img, variance=np.full(img.shape, sigma**2), flags=np.zeros(img.shape, np.uint32),
                       flag_masks={"OVERFLOW": 2, "SOURCE": 1 << 21}, sky_to_pixel=None, pixel_to_sky=None, pixel_scale_arcsec=6.15,
                       detector_offset=off, epsf=lib)


@pytest.mark.measurement
def test_measured_position_is_not_pulled_by_a_wrong_prediction(lib):
    """[measurement] A star at a known position is recovered within its errors whether the prediction is right or off by
    1.4 px: the fit starts from the brightest pixel near the prediction and must give the same answer from offset starts."""
    rng = np.random.default_rng(12)
    x0, y0 = 20.31, 19.62
    good, off = [], []
    for _ in range(25):
        fr = _frame(lib, x0, y0, 3000.0, 2.0, rng)
        a = ta.fit_target(fr, x0, y0, [])
        b = ta.fit_target(fr, x0 + 1.0, y0 - 1.0, [])  # a prediction 1.4 px away
        assert a.status == b.status == "ok" and a.start_spread_px <= 2e-3
        assert math.hypot(a.x - b.x, a.y - b.y) < 1e-6  # identical measurement: the prediction only chose the search region
        good.append(((a.x - x0) / a.sigma_x, (a.y - y0) / a.sigma_y))
    pulls = np.array(good)
    assert np.all(np.abs(pulls.mean(axis=0)) < 4 / math.sqrt(25)) and np.all(pulls.std(axis=0) < 1.5)
    far = ta.fit_target(_frame(lib, x0, y0, 3000.0, 2.0, rng), x0 + 4.0, y0, [])  # nothing within 2 px of the prediction
    assert far.status == "rejected" or math.hypot(far.x - x0, far.y - y0) > 1.0


@pytest.mark.measurement
@pytest.mark.parametrize("dx,dy,ratio", [(2.5, 0.0, 0.2), (0.0, -3.0, 0.5), (1.8, 1.8, 0.1)])
def test_neighbour_shift_simulation_predicts_the_shift_of_an_injected_neighbour(lib, dx, dy, ratio):
    """[measurement] The shift simulated for a catalogued neighbour (pipeline ePSF rendering) equals the shift measured when
    that neighbour is actually injected (photutils rendering) - in both axes, whatever its sign: real ePSFs are
    asymmetric and the sign changes with separation (estimator review), so only the agreement is a physical expectation."""
    rng = np.random.default_rng(3)
    x0, y0 = 20.2, 20.1
    base = ta.fit_target(_frame(lib, x0, y0, 3000.0, 0.01, rng), x0, y0, [{"dx": dx, "dy": dy, "ratio": ratio}])
    with_nb = ta.fit_target(_frame(lib, x0, y0, 3000.0, 0.01, rng, extra=[(x0 + dx, y0 + dy, 3000.0 * ratio)]), x0, y0, [])
    assert base.neighbour_shift_px is not None and math.hypot(*base.neighbour_shift_px) > 0.002  # the case is sensitive
    injected = (with_nb.x - x0, with_nb.y - y0)
    assert injected[0] == pytest.approx(base.neighbour_shift_px[0], abs=0.002) and injected[1] == pytest.approx(base.neighbour_shift_px[1], abs=0.002)


@pytest.mark.registration
def test_epoch_budget_maps_pixel_terms_to_the_sky_in_quadrature():
    """[registration] With a 90-degree-rotated detector (x -> north, y -> east) the per-axis terms swap axes; independent
    per-axis sigmas add in quadrature; the random/systematic split recombines to the total."""
    J = np.array([[0.0, 6.0], [6.0, 0.0]])  # east = 6"/px * dy, north = 6"/px * dx
    fit = ta.TargetFit("ok", "measured", x=0.0, y=0.0, sigma_x=0.01, sigma_y=0.02, corr_xy=0.0, zone_swap_shift_px=(0.004, 0.0),
                       neighbour_shift_px=(0.0, 0.003))
    b = ta.epoch_budget(fit, (0.05, 0.04), 0.03, (0.002, 0.006), J)
    t = b["terms_arcsec"]
    assert t["fit"] == pytest.approx([0.12, 0.06]) and t["psf_target"] == pytest.approx([0.0, 0.012]) and t["neighbours"] == pytest.approx([0.018, 0.0])
    assert t["convention_differential"] == pytest.approx([0.036, 0.012])
    for i in (0, 1):
        assert b["total_arcsec"][i] == pytest.approx(math.sqrt(sum(v[i] ** 2 for v in t.values())))
        assert math.hypot(b["random_arcsec"][i], b["systematic_arcsec"][i]) == pytest.approx(b["total_arcsec"][i])


@pytest.mark.registration
def test_displacement_projection_against_direct_geometry():
    """[registration] A displacement 1.2 x the prediction plus a perpendicular 0.1" gives along-ratio 1.2 and
    perpendicular 0.1"; the 2-D chi2 equals the sum of squared pulls."""
    pred = np.array([0.6, -1.4])
    u = pred / np.linalg.norm(pred)
    meas = 1.2 * pred + 0.1 * np.array([-u[1], u[0]])
    k, sk, perp, sp = ta.along_ratio(meas, pred, np.array([0.1, 0.1]))
    assert k == pytest.approx(1.2) and perp == pytest.approx(0.1) and sk == pytest.approx(0.1 / np.linalg.norm(pred)) and sp == pytest.approx(0.1)
    c, p = ta.chi2_2d(np.array([0.3, -0.4]), np.array([0.1, 0.2]))
    assert c == pytest.approx(9 + 4) and p == pytest.approx(math.exp(-13 / 2))


@pytest.mark.archive
def test_recorded_van_maanen_2_results_keep_measurements_apart_from_predictions():
    """[archive] validation/vanmaanen2_motion.json (if produced): measured positions are fits, never the predictions; D6 is
    excluded by the stage-1 S/N rule; only D1-D3 pairs are primary; a significance is stated only if the
    zero-displacement tests support the budget."""
    from skyshift.validation.report import REPO_ROOT

    path = REPO_ROOT / "validation" / "vanmaanen2_motion.json"
    if not path.exists():
        pytest.skip("van Maanen 2 motion results not produced (needs the cutout cache and the Gaia DR3 record)")
    res = json.loads(path.read_text(encoding="utf-8"))
    for r in res["frames"]:
        assert r["predicted"]["origin"] == "model_prediction"
        if r["status"] == "measured":
            assert r["measured"]["origin"] == "derived_measurement"
            assert (r["measured"]["x_px"], r["measured"]["y_px"]) != (r["predicted"]["x_px"], r["predicted"]["y_px"])
        if r["detector"] == 6:
            assert r["status"] == "rejected" and "stage-1" in r["reason"]
    assert {p["detectors"][0] for p in res["pairs"] if p.get("role") == "primary"} <= {1, 2, 3}
    for p in res["pairs"]:
        if "measured_arcsec" in p:
            assert p["measured_arcsec"] != p["predicted_arcsec"]
    d = res["decision"]
    assert d["motion_detected"] is False or d["budget_supported_by_zero_displacement_tests"] is True
    assert res["gaia_record"]["verification"] in ("pass", None) and res["target"]["source_id"].isdigit()


@pytest.mark.api
def test_target_motion_endpoint_serves_the_recorded_study_with_origins_and_staleness(monkeypatch):
    """[api] /target-motion serves the recorded stage-2 study as recorded: fixed origins, measured never equal to predicted,
    D6 not measured, the conclusion as recorded, stale when the code/data hash differs; 409 for fields without a study and
    for simulated data. Generic target measurement stays 409."""
    from fastapi.testclient import TestClient

    import skyshift.validation.report as rep_mod
    from skyshift.api.app import app
    from skyshift.pipeline.target_motion import study_path

    if not study_path(VM2).exists():
        pytest.skip("no recorded stage-2 study")
    raw = json.loads(study_path(VM2).read_text(encoding="utf-8"))
    c = TestClient(app)
    monkeypatch.setattr(rep_mod, "source_hash", lambda root=None: raw["source_hash"])
    s = c.get(f"/api/datasets/{VM2}/target-motion").json()
    assert s["stale"] is False and s["recovered"] == raw["conclusion"]["recovered"] and s["gaia_source_id"] == raw["target"]["source_id"]
    assert s["measured_origin"] == "derived_measurement" and s["predicted_origin"] == "model_prediction"
    for p in s["pairs"]:
        if p["measured_arcsec"] is not None:
            assert p["measured_arcsec"] != p["predicted_arcsec"] and p["status"] in ("pass", "fail", "inconclusive")
        if p["detector"] == 6:
            assert p["status"] == "not measured" and p["role"] == "excluded"
    assert "not a blind analysis" in s["plan_disclosure"] and s["limitations"]
    monkeypatch.setattr(rep_mod, "source_hash", lambda root=None: "different")
    assert c.get(f"/api/datasets/{VM2}/target-motion").json()["stale"] is True
    for ds in ("spherex-dr1-barnard", "syn-nb-01"):
        r = c.get(f"/api/datasets/{ds}/target-motion")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_available"
    assert c.get(f"/api/datasets/{VM2}/sources").status_code == 409
