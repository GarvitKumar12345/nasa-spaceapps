"""Alignment diagnostics: Gaia DR3 predictions vs ePSF positions on SPHEREx frames.

Offline: statistics and decision rules against direct formulas and synthetic inputs with known
answers; reference selection on a constructed frame (real ePSF, synthetic pixels and flags); one
real frame from the committed fixture cutout with the recorded Gaia response. With the local
cutout cache: the full 17-frame report and the API routes.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import stats

from skyshift.coords.observer import observer_barycentric_au
from skyshift.coords.time import make_epoch
from skyshift.coords.wcs import make_tan_wcs
from skyshift.providers.gaia_dr3 import load_recorded_field
from skyshift.providers.spherex.fitsfile import read_spectral_image
from skyshift.providers.spherex.paths import FIXTURE_ROOT
from skyshift.science.alignment import (
    AlignmentConfig,
    CatalogInputs,
    FrameInputs,
    convention_test,
    diagnose_frame,
    evaluate_translation,
    extra_scatter,
    residual_statistics,
    saturated_sources,
)
from skyshift.science.epoch_propagation import AstrometricArrays, predict_observed

FIELD = "spherex-dr1-barnard"
BARNARD = "4472832130942575872"
FIXTURE = FIXTURE_ROOT / FIELD / "fixture_cutout_D1_trimmed_epsf.fits"
MASKS = {"TRANSIENT": 1 << 0, "OVERFLOW": 1 << 1, "SUR_ERROR": 1 << 2, "NONFUNC": 1 << 6, "SOURCE": 1 << 21, "BLOOM": 1 << 26}


# ---------------------------------------------------------------- statistics and decisions


@pytest.mark.registration
def test_residual_statistics_match_direct_formulas():
    """[registration] Means, SEs, RMS, robust sigma, weighted means and the extra-scatter root agree with direct numpy computations."""
    rng = np.random.default_rng(3)
    e, n = rng.normal(0.1, 0.2, 12), rng.normal(-0.05, 0.25, 12)
    se, sn = rng.uniform(0.05, 0.15, 12), rng.uniform(0.05, 0.15, 12)
    s = residual_statistics(e, n, se, sn)
    assert s["mean_east_arcsec"] == pytest.approx(e.mean()) and s["se_north_arcsec"] == pytest.approx(n.std(ddof=1) / math.sqrt(12))
    assert s["rms_total_arcsec"] == pytest.approx(math.sqrt(np.mean(e**2 + n**2)))
    assert s["robust_sigma_east_arcsec"] == pytest.approx(1.4826 * np.median(np.abs(e - np.median(e))))
    sx = s["extra_scatter_arcsec"]
    w = 1 / (se**2 + sx**2)
    assert s["wmean_east_arcsec"] == pytest.approx(np.sum(w * e) / np.sum(w))
    assert extra_scatter(np.zeros(4), np.ones(4), 4) == 0.0  # formal errors already explain zero residuals


@pytest.mark.registration
def test_scatter_statistics_are_calibrated_for_unequal_errors():
    """[registration] Null Monte Carlo with very unequal per-star sigmas: E[chi2_mean] = 2(k-1), P(extra scatter > 0) = P(chi2 > dof); an injected extra scatter is recovered."""
    rng = np.random.default_rng(17)
    k = 9
    se = np.array([0.04, 0.05, 0.08, 0.12, 0.2, 0.3, 0.45, 0.6, 0.7])  # the spread seen in real frames (")
    sn = se[::-1].copy()
    chi2, positive = [], 0
    for _ in range(2000):
        e, n = 0.1 + rng.normal(0, se), -0.2 + rng.normal(0, sn)  # a common offset, no extra scatter
        s = residual_statistics(e, n, se, sn)
        chi2.append(s["chi2_mean"])
        positive += s["extra_scatter_arcsec"] > 0
    dof = 2 * (k - 1)
    assert np.mean(chi2) == pytest.approx(dof, abs=5 * math.sqrt(2 * dof / 2000))
    assert positive / 2000 == pytest.approx(stats.chi2.sf(dof, dof), abs=5 * math.sqrt(0.25 / 2000))
    # with a true extra scatter of 0.15" the estimate is centred near it (the estimator is consistent, not exact for k = 9)
    est = [residual_statistics(rng.normal(0, np.hypot(se, 0.15)), rng.normal(0, np.hypot(sn, 0.15)), se, sn)["extra_scatter_arcsec"] for _ in range(1000)]
    assert 0.09 < float(np.median(est)) < 0.2


@pytest.mark.registration
def test_translation_is_justified_only_when_significant_and_held_out_residuals_improve():
    """[registration] A 0.5" offset (10 stars, sigma 0.1") is justified with a held-out RMS gain; no offset is not justified; 4 stars are not evaluated."""
    rng = np.random.default_rng(11)
    se = np.full(10, 0.1)
    e, n = 0.5 + rng.normal(0, 0.1, 10), -0.3 + rng.normal(0, 0.1, 10)
    t = evaluate_translation(e, n, se, se)
    assert t["evaluated"] and t["justified"] and t["heldout_rms_corrected_arcsec"] < 0.5 * t["heldout_rms_uncorrected_arcsec"]
    assert t["offset_east_arcsec"] == pytest.approx(0.5, abs=0.1) and t["p_value"] < 1e-6
    e0, n0 = rng.normal(0, 0.1, 10), rng.normal(0, 0.1, 10)
    t0 = evaluate_translation(e0, n0, se, se)
    assert t0["evaluated"] and not t0["justified"] and t0["p_value"] >= 0.0027
    t4 = evaluate_translation(e[:4], n[:4], se[:4], se[:4])
    assert not t4["evaluated"] and not t4["justified"] and "not evaluated" in t4["decision"]


@pytest.mark.registration
def test_shared_error_does_not_average_down_with_the_number_of_references():
    """[registration] A 0.15" offset measured with 10 or 160 stars of sigma 0.1": the random part of the offset
    error falls as 1/sqrt(N) but the total never drops below the shared 0.1" term, so more stars cannot make an
    offset that is within the shared error significant; without the shared term the 160-star offset would be."""
    rng = np.random.default_rng(23)
    res = {}
    for n_star in (10, 160):
        se = np.full(n_star, 0.1)
        e, n = 0.15 + rng.normal(0, 0.1, n_star), rng.normal(0, 0.1, n_star)
        res[n_star] = (evaluate_translation(e, n, se, se, shared_sigma_arcsec=0.1), evaluate_translation(e, n, se, se))
    t10, t160 = res[10][0], res[160][0]
    # random part ~ sqrt((0.1^2 + extra^2) / N): times sqrt(N) it is ~0.1" for both N (extra scatter ~0 here)
    for n_star, t in ((10, t10), (160, t160)):
        assert 0.1 <= t["sigma_random_east_arcsec"] * math.sqrt(n_star) < 0.12
    for t in (t10, t160):
        assert t["sigma_east_arcsec"] == pytest.approx(math.hypot(t["sigma_random_east_arcsec"], 0.1)) and t["sigma_east_arcsec"] >= 0.1
        assert t["p_value"] >= t["p_value_random_only"]
    assert not t160["justified"] and t160["p_value"] > 0.0027
    assert res[160][1]["justified"] and res[160][1]["p_value"] < 1e-6  # the same data, random errors only


@pytest.mark.registration
def test_windowed_centroid_is_exact_for_a_symmetric_source_and_moves_toward_the_light_centroid():
    """[registration] The XWIN-type iteration converges to the centre of a well-sampled symmetric (Gaussian) stamp,
    and for a stamp with a 10 % satellite at +1 px it lands between the core (0) and the light centroid (+0.1 px).
    (On undersampled stamps it carries a pixel-phase bias - which is why it defines a different 'position'.)"""
    from skyshift.science.alignment import windowed_centroid

    yy, xx = np.mgrid[0:41, 0:41]
    g = lambda x0, y0: np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * 2.0**2))  # noqa: E731
    x, y = windowed_centroid(g(20.23, 19.81), 20.0, 20.0, 2.5)
    assert abs(x - 20.23) < 1e-5 and abs(y - 19.81) < 1e-5
    x, _ = windowed_centroid(0.9 * g(20.0, 20.0) + 0.1 * g(21.0, 20.0), 20.0, 20.0, 2.5)
    assert 0.0 < x - 20.0 < 0.1


@pytest.mark.registration
def test_convention_test_distinguishes_catalogue_and_apparent_frames():
    """[registration] Offsets ~0.1" with aberrations ~9" -> catalogue frame; offsets equal to the aberration -> apparent; tiny aberrations -> undetermined."""
    rng = np.random.default_rng(5)
    ab = [(8.0 + rng.normal(), 4.0 + rng.normal()) for _ in range(8)]
    small = [(rng.normal(0, 0.1), rng.normal(0, 0.1), 0.05, 0.05) for _ in range(8)]
    assert convention_test(small, ab)["decision"].startswith("catalogue frame")
    shifted = [(a[0] + o[0], a[1] + o[1], o[2], o[3]) for a, o in zip(ab, small)]
    assert convention_test(shifted, ab)["decision"].startswith("apparent frame")
    assert convention_test(small, [(0.05, 0.05)] * 8)["decision"] == "undetermined"
    assert convention_test([], [])["n_frames"] == 0


# ---------------------------------------------------------------- constructed frame


@pytest.fixture(scope="module")
def fixture_img():
    return read_spectral_image(FIXTURE.read_bytes())


def _constructed(fixture_img):
    """A 60x60 frame with real ePSF stars, Gaussian noise, synthetic flags and a TAN WCS; catalogue = true positions."""
    rng = np.random.default_rng(42)
    shape = (60, 60)
    w = make_tan_wcs(150.0, 20.0, 6.15, shape)
    lib = fixture_img.epsf_library
    stars = {  # name: (x, y, flux, G, RP, aps, ruwe)
        "A_saturated": (30.0, 30.0, 8000.0, 8.0, 7.0, 31, 1.0),
        "B_near_sat": (35.2, 30.4, 80.0, 13.8, 13.1, 31, 1.0),
        "C_clean": (12.3, 12.6, 80.0, 13.5, 12.9, 31, 1.0),
        "D_clean": (47.7, 13.2, 80.0, 13.6, 13.0, 95, 1.1),
        "E_clean": (13.1, 46.8, 80.0, 13.7, 13.1, 31, 0.9),
        "F_pair_a": (46.4, 46.2, 70.0, 14.0, 13.4, 31, 1.0),
        "F_pair_b": (47.6, 46.9, 40.0, 14.6, 14.0, 31, 1.0),
        "G_edge": (1.4, 30.2, 80.0, 13.9, 13.3, 31, 1.0),
        "H_flag_core": (30.3, 51.1, 80.0, 13.9, 13.3, 31, 1.0),
        "I_ruwe": (20.6, 40.2, 80.0, 13.9, 13.3, 31, 2.1),
        "J_two_param": (40.2, 52.4, 80.0, 13.9, 13.3, 3, np.nan),
        "K_faint": (52.5, 30.5, 0.5, 19.5, 18.9, 31, 1.0),
        "L_low_snr": (8.4, 30.3, 0.4, 18.3, 17.6, 31, 1.0),
    }
    img = np.full(shape, 10.0)
    for x, y, f, *_ in stars.values():
        img += lib.model(0).render(shape, x, y, f)
    img += rng.normal(0, 0.1, shape)
    var = np.full(shape, 0.01)
    flags = np.zeros(shape, dtype=np.uint32)
    flags[29:32, 29:32] |= MASKS["OVERFLOW"] | MASKS["SUR_ERROR"]
    flags[27:34, 27:34] |= MASKS["BLOOM"]
    flags[51, 30] |= MASKS["TRANSIENT"]
    flags[5:8, 52:55] |= MASKS["SUR_ERROR"]  # SUR_ERROR alone: a data-handling flag, not saturation
    flags |= MASKS["SOURCE"]  # informational everywhere, as in the real crowded frames

    def s2p(ra, dec):
        xy = w.all_world2pix(np.column_stack([np.atleast_1d(ra), np.atleast_1d(dec)]), 0)
        return xy[:, 0], xy[:, 1]

    def p2s(x, y):
        rd = w.all_pix2world(np.column_stack([np.atleast_1d(x), np.atleast_1d(y)]), 0)
        return rd[:, 0], rd[:, 1]

    names = list(stars)
    xs = np.array([stars[k][0] for k in names])
    ys = np.array([stars[k][1] for k in names])
    ra, dec = p2s(xs, ys)
    col = lambda j: np.array([stars[k][j] for k in names], dtype=float)  # noqa: E731
    z0 = lib.zones[0]  # place the whole frame inside zone 0 (the zone used to render the stars), ~97 px wide
    frame = FrameInputs(frame_id="constructed", image=img, variance=var, flags=flags, flag_masks=MASKS, sky_to_pixel=s2p, pixel_to_sky=p2s,
                        pixel_scale_arcsec=6.15, detector_offset=(z0.x_center - 30.0, z0.y_center - 30.0), epsf=lib)
    cat = CatalogInputs(source_id=names, ra_deg=ra, dec_deg=dec, sigma_east_mas=np.full(len(names), 0.1), sigma_north_mas=np.full(len(names), 0.1),
                        g_mag=col(3), rp_mag=col(4), params_solved=col(5), ruwe=col(6), duplicated=np.zeros(len(names), dtype=bool),
                        ipd_multi_peak=np.zeros(len(names)), non_single_star=np.zeros(len(names)))
    return frame, cat, names


@pytest.mark.registration
def test_reference_selection_reasons_on_a_constructed_frame(fixture_img):
    """[registration] Saturated star, its neighbour within 8 px, a 2-px pair, a flagged core, an edge star, high RUWE, 2-parameter, faint and low-S/N stars get their reasons; clean stars are used with residuals within 5 sigma."""
    frame, cat, names = _constructed(fixture_img)
    diag = diagnose_frame(frame, cat, AlignmentConfig())
    by = {names[r.index]: r for r in diag.results}
    expect = {"A_saturated": "saturated", "B_near_sat": "near_saturated_source", "F_pair_a": "neighbour_within_2px", "F_pair_b": "neighbour_within_2px",
              "G_edge": "outside_frame", "H_flag_core": "flagged_core", "I_ruwe": "ruwe_high", "J_two_param": "no_proper_motion", "K_faint": "too_faint",
              "L_low_snr": "low_snr"}
    for name, reason in expect.items():
        assert by[name].status == "rejected" and by[name].reason == reason, (name, by[name].reason)
    for name in ("C_clean", "D_clean", "E_clean"):
        r = by[name]
        assert r.status == "used", (name, r.reason, r.detail)
        assert abs(r.d_east_arcsec) < 5 * r.s_east_arcsec and abs(r.d_north_arcsec) < 5 * r.s_north_arcsec
    assert [names[i] for i in diag.saturated] == ["A_saturated"]


@pytest.mark.registration
def test_saturated_regions_come_from_overflow_and_the_brightest_gaia_source(fixture_img):
    """[registration] Each OVERFLOW group is assigned to the brightest Gaia source in reach; SUR_ERROR-only pixels and faint stars inside the core create no saturated sources."""
    frame, cat, names = _constructed(fixture_img)
    px, py = frame.sky_to_pixel(cat.ra_deg, cat.dec_deg)
    idx, centres = saturated_sources(frame.flags.astype(np.int64), MASKS, px, py, cat.g_mag, np.ones(len(names), dtype=bool))
    assert [names[i] for i in idx] == ["A_saturated"] and centres.shape == (1, 2)
    flags = frame.flags.astype(np.int64) & ~MASKS["OVERFLOW"]
    assert saturated_sources(flags, MASKS, px, py, cat.g_mag, np.ones(len(names), dtype=bool))[0] == []


# ---------------------------------------------------------------- one real frame, offline (committed fixtures)


@pytest.mark.registration
def test_real_fixture_frame_against_recorded_gaia(fixture_img):
    """[registration] Recorded data, no cache: in the real D1 cutout Barnard's Star is saturated and excluded, >= 5 references are used, the mean residual is < 0.3" and RMS < 0.5" (no ~7" aberration offset)."""
    rec = load_recorded_field(FIELD)
    ref_epoch = make_epoch(2016.0, "jyear", "tcb")
    astro = AstrometricArrays.from_columns(rec.catalog.columns, ref_epoch.mjd_tdb)
    mid = make_epoch(str(fixture_img.image_header["DATE-AVG"]).strip(), "isot", "utc")
    pred = predict_observed(astro, mid.mjd_tdb, observer_barycentric_au(np.array([mid.mjd_tdb]))[0])
    w = fixture_img.wcs

    def s2p(ra, dec):
        xy = w.all_world2pix(np.column_stack([np.atleast_1d(ra), np.atleast_1d(dec)]), 0, tolerance=1e-9, maxiter=60, quiet=True)
        return xy[:, 0], xy[:, 1]

    def p2s(x, y):
        rd = w.all_pix2world(np.column_stack([np.atleast_1d(x), np.atleast_1d(y)]), 0)
        return rd[:, 0], rd[:, 1]

    c = rec.catalog.columns
    frame = FrameInputs("fixture", fixture_img.image, fixture_img.variance, fixture_img.flags, {d.name: d.mask_value for d in fixture_img.flag_defs},
                        s2p, p2s, 6.15, fixture_img.detector_offset(), fixture_img.epsf_library)
    cat = CatalogInputs(rec.catalog.source_id, pred.ra_deg, pred.dec_deg, pred.sigma_ra_cosdec_mas, pred.sigma_dec_mas, c["phot_g_mean_mag"], c["phot_rp_mean_mag"],
                        c["astrometric_params_solved"], c["ruwe"], np.asarray(c["duplicated_source"], dtype=bool), c["ipd_frac_multi_peak"], c["non_single_star"])
    diag = diagnose_frame(frame, cat, AlignmentConfig())
    assert BARNARD in [rec.catalog.source_id[i] for i in diag.saturated]
    used = diag.used
    assert len(used) >= 5
    e = np.array([r.d_east_arcsec for r in used])
    n = np.array([r.d_north_arcsec for r in used])
    assert abs(e.mean()) < 0.3 and abs(n.mean()) < 0.3 and math.sqrt(np.mean(e**2 + n**2)) < 0.5
    near = [r for r in diag.results if r.dist_saturated_px is not None and r.dist_saturated_px < 8.0 and r.status == "used"]
    assert near == []


# ---------------------------------------------------------------- full field (local cache) and API


@pytest.fixture(scope="module")
def gaia_session(spherex_bundle):
    from skyshift.pipeline.observed_gaia import observed_gaia

    return observed_gaia(spherex_bundle, load_recorded_field(FIELD))


@pytest.mark.registration
def test_field_report_on_all_real_frames(gaia_session):
    """[registration] 17 frames: counts add up, >= 10 frames usable, convention = catalogue frame, pooled RMS < 2 x the documented 0.3", Barnard's Star saturated in every frame."""
    rep = gaia_session.report()
    # full aberration is rejected by the data, but the pipeline's parallax/deflection/centroid conventions are only bounded
    assert rep.status == "available" and rep.convention.status == "partially_resolved" and len(rep.frames) == 17
    statuses = {a.aspect.split(" (")[0]: a.status for a in rep.convention.aspects}
    assert any(s == "documented_and_tested" for s in statuses.values()) and any(s.endswith("_bounded") for s in statuses.values())
    assert rep.convention_test.decision.startswith("catalogue frame") and rep.convention_test.max_frame_offset_arcsec < 1.0
    assert rep.n_frames_ok >= 10 and rep.n_frames_ok + rep.n_frames_insufficient + rep.n_frames_not_validated == 17
    for f in rep.frames:
        assert f.n_candidates + f.n_fainter_than_limit == f.n_in_frame and f.n_used + f.n_rejected == f.n_candidates
        assert sum(f.rejected_by_reason.values()) == f.n_rejected and BARNARD in f.saturated_source_ids
        assert (f.status == "ok") == (f.n_used >= 5 and f.estimator.passed)
        t = f.translation
        if t.evaluated:
            assert t.justified == (t.p_value < 0.0027 and t.heldout_rms_corrected_arcsec < t.heldout_rms_uncorrected_arcsec)
        for r in f.residuals:
            if r.status == "used":
                assert r.sigma_east_arcsec > 0 and r.snr >= 10 and max(r.sigma_x_px, r.sigma_y_px) <= 0.25
            assert r.source_id != BARNARD or r.reason == "saturated"
    p = rep.pooled
    assert p.n >= 50 and p.rms_east_arcsec < 0.6 and p.rms_north_arcsec < 0.6 and abs(p.mean_east_arcsec) < 0.1 and abs(p.mean_north_arcsec) < 0.1
    assert p.rms_total_arcsec == pytest.approx(math.hypot(p.rms_east_arcsec, p.rms_north_arcsec))  # 2-D RMS, not a per-axis value


@pytest.mark.registration
def test_report_budget_separates_random_and_shared_errors_and_records_its_cache_provenance(gaia_session):
    """[registration] Every ok frame carries a shared term that enters its translation sigma without 1/sqrt(N); the
    budget lists random, unexplained and shared kinds; the cache record names its key, inputs and computation time."""
    rep = gaia_session.report()
    kinds = {u.kind for u in rep.uncertainty_budget}
    assert kinds == {"random_per_star", "unexplained_per_star", "shared_per_frame", "shared_all_frames"}
    for f in rep.frames:
        if f.status != "ok":
            continue
        sh, t = f.shared, f.translation
        assert sh is not None and sh.total_arcsec >= sh.convention_arcsec > 0
        assert (sh.psf_mismatch_arcsec is None) == bool(sh.missing_terms)
        if t.evaluated:
            assert t.sigma_shared_arcsec == pytest.approx(sh.total_arcsec)
            assert t.sigma_east_arcsec == pytest.approx(math.hypot(t.sigma_random_east_arcsec, sh.total_arcsec))
            assert t.p_value == pytest.approx(stats.chi2.sf(t.chi2, 2)) and t.p_value_random_only == pytest.approx(stats.chi2.sf(t.chi2_random_only, 2))
    assert rep.reassessment and "do not shrink with N" in rep.reassessment
    c = rep.cache
    assert c is not None and c.key == gaia_session.cache_key() and c.computed_utc.endswith("Z")
    assert c.inputs["gaia_retrieved_utc"] == gaia_session.recorded.manifest["retrieved_utc"] and int(c.inputs["n_frames"]) == 17


@pytest.mark.api
def test_api_serves_gaia_predictions_with_string_ids_and_keeps_analyses_unavailable(spherex_bundle, gaia_session):
    """[api] Overlay/detail JSON: string source IDs, model_prediction vs derived_measurement origins; alignment report served; differences, fits and target measurements stay 409."""
    from skyshift.api.app import app

    assert gaia_session.report() is not None  # computed (and disk-cached) once for the module
    c = TestClient(app)
    frame = next(f for f in spherex_bundle.dataset.frames if f.kind == "archive_wcs_reprojection")
    ov = c.get(f"/api/datasets/{FIELD}/gaia/overlay", params={"frame_id": frame.id})
    assert ov.status_code == 200
    body = ov.json()
    assert body["convention"]["status"] == "partially_resolved" and body["convention"]["aspects"] and body["epoch"]["iso_utc"]
    assert all(isinstance(p["source_id"], str) and p["origin"] == "model_prediction" for p in body["predictions"])
    raw = ov.text
    assert f'"source_id":"{BARNARD}"' in raw.replace(" ", "")  # serialised as a string, never a JSON number
    d = c.get(f"/api/datasets/{FIELD}/gaia/sources/{BARNARD}", params={"frame_id": frame.id}).json()
    assert d["source"]["source_id"] == BARNARD and d["source"]["origin"] == "catalog" and d["propagated"]["origin"] == "model_prediction"
    assert d["measurement"]["origin"] == "derived_measurement" and d["measurement"]["reason"] == "saturated"
    assert "SATURATED_IN_FRAME" in d["prediction"]["flags"] and d["propagated"]["radial_velocity_assumed"] is False
    assert c.get(f"/api/datasets/{FIELD}/gaia/sources/4.47e18", params={"frame_id": frame.id}).status_code == 422
    rep = c.get(f"/api/datasets/{FIELD}/alignment")
    assert rep.status_code == 200 and rep.json()["status"] == "available"
    native = frame.id.replace(":display", ":native")
    for path, method, payload in (
        (f"/api/datasets/{FIELD}/difference/info?a={native}&b={native}", "get", None),
        (f"/api/datasets/{FIELD}/sources", "get", None),
        (f"/api/datasets/{FIELD}/catalog?frame_id={frame.id}", "get", None),
        ("/api/fits/astrometric", "post", {"dataset_id": FIELD, "source_id": "S001", "model": "proper_motion"}),
    ):
        r = c.post(path, json=payload) if method == "post" else c.get(path)
        assert r.status_code in (409, 422), path
        if r.status_code == 409:
            assert r.json()["detail"]["code"] == "not_available"
    assert c.get("/api/datasets/syn-nb-01/gaia/overlay", params={"frame_id": "x"}).status_code == 409
    text = json.dumps(body).lower() + rep.text.lower()
    for word in ("discovered", "new object detected", "new source", "transient candidate"):
        assert word not in text
    assert "not evidence of a new or vanished object" in text


@pytest.mark.api
def test_cached_alignment_report_is_served_only_under_its_own_key_and_keeps_its_provenance(spherex_bundle, gaia_session, tmp_path):
    """[api] Disk cache: absent -> nothing (and the convention says 'not computed yet', not 'no frames'); garbage ->
    deleted; another key -> never served; the right key -> the same report with served_from_cache and the
    original computation time and inputs."""
    from skyshift.pipeline.observed_gaia import ObservedGaia

    rep = gaia_session.report()
    fresh = ObservedGaia(spherex_bundle, load_recorded_field(FIELD))
    path = tmp_path / "report.json"
    fresh._cache_path = lambda: path  # type: ignore[method-assign]
    assert fresh.cached_report() is None
    conv = fresh.convention()
    assert conv.status == "approximate" and any("not computed yet" in e for e in conv.evidence)
    path.write_text("{not json", encoding="utf-8")
    assert fresh.cached_report() is None and not path.exists()
    other = rep.model_copy(update={"cache": rep.cache.model_copy(update={"key": "0" * 24, "served_from_cache": False})})
    path.write_text(other.model_dump_json(), encoding="utf-8")
    assert fresh.cached_report() is None and path.exists()
    path.write_text(rep.model_copy(update={"cache": rep.cache.model_copy(update={"served_from_cache": False})}).model_dump_json(), encoding="utf-8")
    got = fresh.cached_report()
    assert got is not None and got.cache.served_from_cache is True
    assert got.cache.key == rep.cache.key and got.cache.computed_utc == rep.cache.computed_utc and got.cache.inputs == rep.cache.inputs
    assert got.provenance == rep.provenance and got.pooled == rep.pooled and len(got.frames) == len(rep.frames)
    assert fresh.convention().status == "partially_resolved"  # the overlay now uses the cached convention test


@pytest.mark.api
def test_gaia_failures_answer_503_or_409_and_never_substitute(spherex_bundle, monkeypatch):
    """[api] A recorded Gaia response that fails its checks -> 503 provider_unavailable on overlay, detail and alignment
    (no predictions, no frames in the body); a dataset whose capability is unavailable -> 409 not_available."""
    import skyshift.api.app as appmod
    from skyshift.providers.base import ProviderUnavailable

    def broken(field_id: str):  # noqa: ANN202
        raise ProviderUnavailable("gaia_dr3", "load_recorded_field", f"recorded response for {field_id} does not match its manifest sha256")

    c = TestClient(appmod.app)
    frame = next(f for f in spherex_bundle.dataset.frames if f.kind == "archive_wcs_reprojection")
    monkeypatch.setattr(appmod, "load_recorded_field", broken)
    for path, params in ((f"/api/datasets/{FIELD}/gaia/overlay", {"frame_id": frame.id}), (f"/api/datasets/{FIELD}/gaia/sources/{BARNARD}", {"frame_id": frame.id}),
                         (f"/api/datasets/{FIELD}/alignment", None)):
        r = c.get(path, params=params)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "provider_unavailable", path
        assert "predictions" not in r.text and "frames" not in r.json()
    monkeypatch.undo()
    from skyshift.api.app import ObservedSession
    from skyshift.contracts import AnalysisCapability

    monkeypatch.setattr(ObservedSession, "capability", lambda self, cid: AnalysisCapability(id=cid, status="unavailable", reason="test: no recorded response", requirements=[]))
    for path in (f"/api/datasets/{FIELD}/gaia/overlay?frame_id={frame.id}", f"/api/datasets/{FIELD}/alignment"):
        r = c.get(path)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_available" and r.json()["detail"]["message"] == "test: no recorded response"


@pytest.mark.registration
def test_translation_decisions_are_consistent_with_chi2(gaia_session):
    """[registration] For every evaluated frame: chi2 = (offset / total sigma)^2 summed over both axes, the decision
    follows from p < 0.0027 and the held-out test, and the offset is the weighted mean of the residuals."""
    n_eval = 0
    for f in gaia_session.report().frames:
        t = f.translation
        if not t.evaluated:
            continue
        n_eval += 1
        assert t.chi2 == pytest.approx((t.offset_east_arcsec / t.sigma_east_arcsec) ** 2 + (t.offset_north_arcsec / t.sigma_north_arcsec) ** 2, rel=1e-6)
        assert t.justified == (t.p_value < 0.0027 and t.heldout_rms_corrected_arcsec < t.heldout_rms_uncorrected_arcsec)
        assert t.offset_east_arcsec == pytest.approx(f.statistics.wmean_east_arcsec, abs=1e-9)
    assert n_eval >= 10
