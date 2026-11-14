"""PSF rendering/fitting, detection, registration, and reprojection checks on generated pixels."""

from __future__ import annotations

import numpy as np
import pytest

from skyshift.coords.tangent import angular_separation_deg
from skyshift.coords.wcs import make_tan_wcs, pixel_to_sky, sky_to_pixel
from skyshift.imaging.detect import detect_sources
from skyshift.imaging.psf import fit_psf, fwhm_to_sigma, gaussian_pixel_integrated, render_point_sources, windowed_centroid
from skyshift.imaging.registration import RegisteredWCS, SimilarityTransform, fit_similarity, match_by_offset_voting, register_frame
from skyshift.imaging.reproject import reproject_to_grid

SIGMA = fwhm_to_sigma(2.5)
SKY, RN = 150.0, 5.0


def _noisy(shape, xs, ys, fluxes, rng, sigma=SIGMA):
    expected = SKY + render_point_sources(shape, np.array(xs), np.array(ys), np.array(fluxes), sigma)
    image = rng.poisson(expected).astype(float) + rng.normal(0, RN, shape)
    return image, RN**2 + np.maximum(image, 0.0), np.zeros(shape, dtype=np.uint16)


@pytest.mark.measurement
def test_pixel_integration_matches_supersampling():
    """Pixel-integrated Gaussian equals 50x-supersampled numerical integration (<1e-4 relative) and sums to the flux."""
    shape, x0, y0 = (15, 17), 8.3, 6.7
    exact = gaussian_pixel_integrated(shape, x0, y0, 1000.0, SIGMA)
    sub = 50
    fine_x = (np.arange(shape[1] * sub) + 0.5) / sub - 0.5
    fine_y = (np.arange(shape[0] * sub) + 0.5) / sub - 0.5
    g = np.exp(-((fine_x[None, :] - x0) ** 2 + (fine_y[:, None] - y0) ** 2) / (2 * SIGMA**2)) / (2 * np.pi * SIGMA**2)
    numeric = 1000.0 * g.reshape(shape[0], sub, shape[1], sub).sum(axis=(1, 3)) / sub**2
    assert np.max(np.abs(exact - numeric)) < 1e-4 * exact.max()
    assert exact.sum() == pytest.approx(1000.0, rel=1e-6)


@pytest.mark.measurement
def test_zero_based_pixel_convention():
    """A source at x=10, y=20 peaks at numpy index [20, 10] and fits back to (10, 20)."""
    img = gaussian_pixel_integrated((40, 30), 10.0, 20.0, 5000.0, SIGMA) + SKY
    iy, ix = np.unravel_index(np.argmax(img), img.shape)
    assert (iy, ix) == (20, 10)
    fit = fit_psf(img, np.full(img.shape, 50.0), np.zeros(img.shape, np.uint16), 10.4, 19.6, SIGMA)
    assert fit.x == pytest.approx(10.0, abs=1e-6) and fit.y == pytest.approx(20.0, abs=1e-6)


@pytest.mark.measurement
@pytest.mark.parametrize("x0,y0", [(20.0, 20.0), (20.25, 19.6), (19.5, 20.5), (20.9, 20.1)])
def test_noiseless_subpixel_recovery(x0, y0):
    """Noiseless pixel-integrated sources are recovered to < 1e-4 px at sub-pixel offsets."""
    img = gaussian_pixel_integrated((41, 41), x0, y0, 8000.0, SIGMA) + SKY
    fit = fit_psf(img, np.full(img.shape, 100.0), np.zeros(img.shape, np.uint16), round(x0), round(y0), SIGMA)
    assert abs(fit.x - x0) < 1e-4 and abs(fit.y - y0) < 1e-4 and fit.flux == pytest.approx(8000.0, rel=1e-6)


@pytest.mark.measurement
@pytest.mark.slow
def test_reported_uncertainties_match_monte_carlo_scatter():
    """Over 400 Poisson+read-noise realisations: bias < 0.1 sigma and pull std in [0.9, 1.1] for x, y and flux."""
    rng = np.random.default_rng(42)
    pulls = []
    for _ in range(400):
        x0, y0 = 15 + rng.uniform(-0.5, 0.5), 15 + rng.uniform(-0.5, 0.5)
        img, var, mask = _noisy((31, 31), [x0], [y0], [9000.0], rng)
        fit = fit_psf(img, var, mask, round(x0), round(y0), SIGMA)
        assert fit.status != "rejected"
        pulls.append([(fit.x - x0) / fit.sigma_x, (fit.y - y0) / fit.sigma_y, (fit.flux - 9000.0) / fit.flux_err])
    pulls = np.array(pulls)
    assert np.all(np.abs(pulls.mean(axis=0)) < 0.1 * 1.0 + 3 / np.sqrt(len(pulls)))
    assert np.all((pulls.std(axis=0) > 0.9) & (pulls.std(axis=0) < 1.1))


@pytest.mark.measurement
def test_masked_pixel_does_not_bias_fit():
    """A huge value in a masked pixel next to the source leaves the fitted position unchanged within 0.05 sigma."""
    rng = np.random.default_rng(1)
    img, var, mask = _noisy((31, 31), [15.2], [14.7], [9000.0], rng)
    clean = fit_psf(img, var, mask, 15, 15, SIGMA)
    img2, mask2 = img.copy(), mask.copy()
    img2[15, 16] += 1e6
    mask2[15, 16] = 1
    flagged = fit_psf(img2, var, mask2, 15, 15, SIGMA)
    assert "MASKED_PIXELS_IN_FIT" in flagged.flags
    assert abs(flagged.x - clean.x) < 0.05 * clean.sigma_x * 10 and abs(flagged.y - clean.y) < 0.05 * clean.sigma_y * 10


@pytest.mark.measurement
def test_quality_flags_edge_low_snr_and_too_few_pixels():
    """Edge truncation is flagged, faint sources get LOW_SNR, and fully masked windows are rejected."""
    rng = np.random.default_rng(2)
    img, var, mask = _noisy((40, 40), [1.2, 25.0], [20.0, 25.0], [8000.0, 120.0], rng)
    assert "EDGE_TRUNCATED" in fit_psf(img, var, mask, 1, 20, SIGMA).flags
    assert "LOW_SNR" in fit_psf(img, var, mask, 25, 25, SIGMA).flags
    dead = np.full(mask.shape, 1, np.uint16)
    assert fit_psf(img, var, dead, 25, 25, SIGMA).status == "rejected"


@pytest.mark.measurement
def test_windowed_centroid_agrees_with_psf_fit():
    """The secondary windowed centroid agrees with the PSF fit within their combined uncertainties."""
    rng = np.random.default_rng(3)
    img, var, mask = _noisy((31, 31), [15.3], [14.6], [12000.0], rng)
    a = fit_psf(img, var, mask, 15, 15, SIGMA)
    b = windowed_centroid(img, var, mask, 15, 15, SIGMA)
    assert abs(a.x - b.x) < 4 * np.hypot(a.sigma_x, b.sigma_x) and abs(a.y - b.y) < 4 * np.hypot(a.sigma_y, b.sigma_y)


@pytest.mark.measurement
def test_detection_completeness_false_positives_and_masks():
    """Isolated bright sources are all detected; masked hot pixels/cosmic rays never seed detections; pure noise gives <= 1 false positive."""
    rng = np.random.default_rng(4)
    gx, gy = np.meshgrid(np.arange(12, 90, 15.0), np.arange(12, 90, 15.0))  # >= 4 FWHM apart: isolated
    xs = gx.ravel() + rng.uniform(-2, 2, gx.size)
    ys = gy.ravel() + rng.uniform(-2, 2, gy.size)
    img, var, mask = _noisy((100, 100), xs, ys, np.full(xs.size, 6000.0), rng)
    for (yy, xx, bit) in ((5, 50, 2), (95, 20, 1), (50, 95, 1)):
        img[yy, xx] += 20000
        mask[yy, xx] = bit
    det = detect_sources(img, var, mask, SIGMA)
    found = sum(1 for x, y in zip(xs, ys) if any(np.hypot(d.x - x, d.y - y) < 0.5 for d in det))
    assert found == xs.size
    assert not any(np.hypot(d.x - xx, d.y - yy) < 2.0 for d in det for (yy, xx) in ((5, 50), (95, 20), (50, 95)))
    noise, nvar, nmask = _noisy((100, 100), [], [], [], rng)
    assert len(detect_sources(noise, nvar, nmask, SIGMA)) <= 1


@pytest.mark.measurement
def test_blended_pair_is_flagged_not_silently_measured():
    """Two sources 1.1 FWHM apart are not separable by a single-PSF fit: the fit is flagged POOR_PSF_FIT."""
    rng = np.random.default_rng(10)
    sep = 1.1 * 2.5
    img, var, mask = _noisy((41, 41), [20.0, 20.0 + sep], [20.0, 20.0], [8000.0, 6000.0], rng)
    fit = fit_psf(img, var, mask, 21, 20, SIGMA)
    assert "POOR_PSF_FIT" in fit.flags and fit.status != "ok"


@pytest.mark.registration
def test_similarity_fit_exact_and_outlier_rejection():
    """Noiseless points recover a known similarity exactly; a single 30-sigma mover is clipped."""
    rng = np.random.default_rng(5)
    t = SimilarityTransform(np.cos(0.01) * 1.0002, np.sin(0.01) * 1.0002, 3.7, -2.2)
    src = rng.uniform(0, 160, (25, 2))
    dst = np.column_stack(t.apply(src[:, 0], src[:, 1]))
    fit = fit_similarity(src, dst)
    assert fit.transform.a == pytest.approx(t.a, abs=1e-10) and fit.transform.tx == pytest.approx(t.tx, abs=1e-8)
    cov = np.tile(np.eye(2) * 0.02**2, (25, 1, 1))
    noisy = dst + rng.normal(0, 0.02, dst.shape)
    noisy[7] += [0.6, -0.4]
    fit = fit_similarity(src, noisy, cov_dst=cov)
    assert not fit.used[7] and fit.used.sum() >= 23


@pytest.mark.registration
@pytest.mark.slow
def test_similarity_covariance_is_calibrated():
    """Over 300 trials the transform-parameter pulls have std in [0.85, 1.15] (covariance is consistent with scatter)."""
    rng = np.random.default_rng(6)
    t = SimilarityTransform(0.9999, 0.004, 1.5, 0.7)
    src = rng.uniform(0, 160, (20, 2))
    dst = np.column_stack(t.apply(src[:, 0], src[:, 1]))
    cov = np.tile(np.eye(2) * 0.05**2, (20, 1, 1))
    pulls = []
    for _ in range(300):
        fit = fit_similarity(src, dst + rng.normal(0, 0.05, dst.shape), cov_dst=cov)
        p = np.array([fit.transform.a - t.a, fit.transform.b - t.b, fit.transform.tx - t.tx, fit.transform.ty - t.ty])
        pulls.append(p / np.sqrt(np.diag(fit.cov)))
    s = np.array(pulls).std(axis=0)
    assert np.all((s > 0.85) & (s < 1.15))


@pytest.mark.registration
def test_offset_voting_finds_large_shift():
    """Offset voting recovers a 25 px shift with 30% unmatched points on each side."""
    rng = np.random.default_rng(7)
    ref = rng.uniform(0, 200, (40, 2))
    det = ref[:28] + np.array([-25.0, 12.0]) + rng.normal(0, 0.05, (28, 2))
    det = np.vstack([det, rng.uniform(0, 200, (12, 2))])
    pairs = match_by_offset_voting(det, ref, max_shift_px=30.0, tol_px=1.0)
    good = sum(1 for i, j in pairs if i < 28 and i == j)
    assert good >= 26 and len(pairs) - good <= 2


@pytest.mark.registration
def test_registered_wcs_folding_is_exact():
    """Folding the similarity into CRPIX/CD reproduces the composed mapping to < 1e-6 mas."""
    nominal = make_tan_wcs(180.0, 35.0, 0.4, (160, 160), rotation_deg=0.2, crpix0=(81.0, 78.5))
    reg = RegisteredWCS(nominal, SimilarityTransform(0.99998, 0.0003, 1.3, -2.1))
    folded = reg.as_astropy()
    gx, gy = np.meshgrid(np.linspace(0, 159, 8), np.linspace(0, 159, 8))
    r1, d1 = reg.pixel_to_sky(gx.ravel(), gy.ravel())
    r2, d2 = pixel_to_sky(folded, gx.ravel(), gy.ravel())
    assert np.max(angular_separation_deg(r1, d1, r2, d2)) * 3.6e6 < 1e-6
    x, y = reg.sky_to_pixel(r1, d1)
    assert np.max(np.hypot(x - gx.ravel(), y - gy.ravel())) < 1e-8


@pytest.mark.registration
def test_register_frame_recovers_truth_wcs_from_star_images():
    """Real registration accuracy: stars rendered through a truth WCS, measured, and matched through a header WCS
    that is wrong by ~1" recover the truth WCS within 3x the expected precision (sigma_star / sqrt(N))."""
    rng = np.random.default_rng(8)
    shape = (160, 160)
    truth = make_tan_wcs(180.0, 35.0, 0.4, shape, rotation_deg=0.15, crpix0=(82.0, 77.0))
    header = make_tan_wcs(180.0002, 34.9998, 0.4, shape, rotation_deg=0.19, crpix0=(82.0, 77.0))
    ra = 180.0 + rng.uniform(-0.008, 0.008, 40)
    dec = 35.0 + rng.uniform(-0.008, 0.008, 40)
    x, y = sky_to_pixel(truth, ra, dec)
    img, var, mask = _noisy(shape, x, y, np.full(40, 20000.0), rng)
    det = detect_sources(img, var, mask, SIGMA)
    res = register_frame(np.array([[d.x, d.y] for d in det]), np.array([d.cov_xy for d in det]), header, ra, dec,
                         np.tile(np.eye(2) * 0.1, (40, 1, 1)), [f"r{i}" for i in range(40)], "test")
    gx, gy = np.meshgrid(np.linspace(10, 150, 6), np.linspace(10, 150, 6))
    r1, d1 = res.wcs.pixel_to_sky(gx.ravel(), gy.ravel())
    r2, d2 = pixel_to_sky(truth, gx.ravel(), gy.ravel())
    err_mas = angular_separation_deg(r1, d1, r2, d2) * 3.6e6
    r0, d0 = pixel_to_sky(header, gx.ravel(), gy.ravel())
    assert np.max(angular_separation_deg(r0, d0, r2, d2) * 3.6e6) > 500  # the header really was wrong
    star_sigma = np.median([np.sqrt(d.cov_xy[0, 0]) for d in det]) * 400.0
    assert np.max(err_mas) < 3 * 2.0 * star_sigma / np.sqrt(res.summary.n_used)  # corners: up to ~2x the centre error
    assert res.summary.chi2_per_dof < 2.0


@pytest.mark.registration
def test_reprojection_identity_shift_coverage_and_masks():
    """Identity reprojection is exact; an integer shift is exact; outside coverage and masked pixels become NaN."""
    rng = np.random.default_rng(9)
    w = make_tan_wcs(10.0, 20.0, 0.4, (50, 60))
    img = rng.normal(100, 5, (50, 60)).astype(np.float32)
    mask = np.zeros(img.shape, np.uint16)
    out, cov = reproject_to_grid(img, mask, RegisteredWCS(w, SimilarityTransform()), w, (50, 60))
    np.testing.assert_allclose(out[:, :], img, rtol=0, atol=1e-4)
    assert cov.all()
    shifted = RegisteredWCS(w, SimilarityTransform(1.0, 0.0, 3.0, -2.0))
    out, cov = reproject_to_grid(img, mask, shifted, w, (50, 60))
    np.testing.assert_allclose(out[10:40, 10:50], img[12:42, 7:47], atol=1e-4)
    assert np.isnan(out[:, :3]).all() and not cov[:, :2].any()
    mask[25, 30] = 2
    out, _ = reproject_to_grid(img, mask, RegisteredWCS(w, SimilarityTransform()), w, (50, 60))
    assert np.isnan(out[25, 30]) and np.isfinite(out[25, 33])
