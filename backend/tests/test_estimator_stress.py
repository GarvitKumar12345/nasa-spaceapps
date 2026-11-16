"""The ePSF position estimator against an independent renderer and controlled PSF / scene variations.

The data are rendered without skyshift.imaging.epsf: an analytic PSF integrated over every native pixel
(skyshift.science.estimator_stress.pixel_integrated), or a real SPHEREx zone ePSF evaluated by photutils.
Expectations come from analytic properties (flux/centroid conservation, symmetry, first-order perturbation
theory, linearity of the background model, Fisher information), not from re-running the fitter's own model.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from skyshift.imaging.epsf import EPSFModel, fit_position
from skyshift.science import estimator_stress as es

FWHM, BETA = 1.15, 3.0  # undersampled, like the SPHEREx short-wavelength ePSFs (FWHM ~ 1.1 px)
SHAPE = (21, 21)


@pytest.fixture(scope="module")
def nominal():
    psf = es.moffat(FWHM, BETA)
    return psf, EPSFModel(es.epsf_from_psf(psf), (5, 5))


def _fit(img, model, x0, y0, var=None, bad=None, start=None):  # noqa: ANN001, ANN202
    """Fit from a start displaced 0.05 px away from the nearest pixel centre (mirrored with the phase, so that
    mirrored configurations stay mirrored and the window, centred on the nearest pixel, is the same)."""
    var = np.ones(img.shape) if var is None else var
    bad = np.zeros(img.shape, bool) if bad is None else bad
    if start is None:
        start = (x0 + 0.05 * np.sign(x0 - round(x0)), y0 + 0.05 * np.sign(y0 - round(y0)))
    return fit_position(img, var, bad, model, start[0], start[1])


def _support(shape, x0, y0, half_px):  # noqa: ANN001, ANN202
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    return (np.abs(xx - x0) <= half_px) & (np.abs(yy - y0) <= half_px)


@pytest.mark.measurement
def test_independent_renderer_conserves_flux_and_centroid_and_is_translation_covariant():
    """[measurement] Well sampled (FWHM 4 px, Gaussian-like wings): flux conserved, light centroid at the source,
    a satellite of fraction f at distance d moves it by f*d. Undersampled nominal PSF: a 1-px shift of the source
    shifts the image by exactly one pixel, a half-pixel phase gives a mirror-symmetric image, and the 9x9
    midpoint rule has converged (vs 27x27). (The pixel centroid of an undersampled image is not the source
    position - the pixel-phase bias - so it is not tested there.)"""
    yy, xx = np.mgrid[0:61, 0:61]
    wide = es.moffat(4.0, 10.0)
    img = es.pixel_integrated(wide, (61, 61), 30.37, 29.81, 1000.0)
    assert img.sum() == pytest.approx(1000.0, rel=1e-6)
    assert (img * xx).sum() / img.sum() == pytest.approx(30.37, abs=1e-5) and (img * yy).sum() / img.sum() == pytest.approx(29.81, abs=1e-5)
    sat = es.pixel_integrated(es.moffat(4.0, 10.0, sat_frac=0.1, sat_dx=0.3), (61, 61), 30.37, 29.81, 1000.0)
    assert (sat * xx).sum() / sat.sum() - 30.37 == pytest.approx(0.03, abs=1e-5)
    psf = es.moffat(FWHM, BETA)
    a = es.pixel_integrated(psf, (41, 41), 20.23, 19.64, 1.0)
    b = es.pixel_integrated(psf, (41, 41), 21.23, 19.64, 1.0)
    assert np.max(np.abs(b[:, 1:] - a[:, :-1])) < 1e-15
    half = es.pixel_integrated(psf, (41, 41), 20.5, 20.0, 1.0)
    assert np.max(np.abs(half[:, 1:21] - half[:, 40:20:-1])) < 1e-15  # column k <-> 41 - k (mirror about 20.5)
    fine = es.pixel_integrated(psf, (41, 41), 20.23, 19.64, 1.0, sub=27)
    assert np.max(np.abs(fine - a)) < 2e-3 * a.max()


@pytest.mark.measurement
def test_epsf_built_from_the_psf_reproduces_the_independent_rendering(nominal):
    """[measurement] A&K ePSF within its +-3.2 px support (33 samples / 5): on the 5x lattice the stored samples equal
    the pixel-integrated PSF (no interpolation); between lattice points the bicubic evaluation stays within 0.1 % of
    the peak. Outside the support the model is 0 (wing flux there is left to the fitted plane)."""
    psf, model = nominal
    on = es.pixel_integrated(psf, SHAPE, 10.2, 9.6, 1.0)
    sup = _support(SHAPE, 10.2, 9.6, 3.2 - 1e-9)
    assert np.max(np.abs(model.sample_exact(SHAPE, 10.2, 9.6, 1.0) - on)[sup]) < 1e-12
    for x0, y0 in ((10.0, 10.0), (10.27, 9.71), (10.43, 10.11)):
        direct = es.pixel_integrated(psf, SHAPE, x0, y0, 1.0)
        sup = _support(SHAPE, x0, y0, 3.2)
        assert np.max(np.abs(model.render(SHAPE, x0, y0, 1.0) - direct)[sup]) < 1e-3 * direct.max()
        assert np.max(direct[~sup]) < 3e-3 * direct.max()  # the truncated Moffat wing (<= 0.3 % of the peak per pixel)


def _crlb_xy(psf, x0, y0, flux, sigma, h=3):  # noqa: ANN001, ANN202
    """Cramer-Rao bound for (x, y) with flux and a plane background free, from finite differences of the
    independent renderer over the same (2h+1)^2 window the fitter uses (centred on the nearest pixel)."""
    ix, iy = int(round(x0)), int(round(y0))
    sl = (slice(iy - h, iy + h + 1), slice(ix - h, ix + h + 1))
    d = 1e-4
    dmx = (es.pixel_integrated(psf, SHAPE, x0 + d, y0, flux) - es.pixel_integrated(psf, SHAPE, x0 - d, y0, flux))[sl] / (2 * d)
    dmy = (es.pixel_integrated(psf, SHAPE, x0, y0 + d, flux) - es.pixel_integrated(psf, SHAPE, x0, y0 - d, flux))[sl] / (2 * d)
    shape_ = es.pixel_integrated(psf, SHAPE, x0, y0, 1.0)[sl]
    yy, xx = np.mgrid[-h : h + 1, -h : h + 1]
    J = np.column_stack([c.ravel() for c in (dmx, dmy, shape_, np.ones_like(shape_), xx.astype(float), yy.astype(float))])
    cov = np.linalg.inv(J.T @ J) * sigma**2
    return math.sqrt(cov[0, 0]), math.sqrt(cov[1, 1])


@pytest.mark.measurement
def test_matched_fit_is_unbiased_and_its_errors_match_an_independent_cramer_rao_bound(nominal):
    """[measurement] 400 noise realisations at a fixed sub-pixel phase (S/N ~ 50): mean error consistent with 0,
    scatter equal to the Cramer-Rao bound computed from the independent renderer (+-4 sigma of a std estimate),
    and the reported sigma equal to it within the sqrt(max(1, chi2_red)) inflation (<= +10 %)."""
    psf, model = nominal
    x0, y0, flux, sig = 10.21, 9.93, 1000.0, 10.5
    cx, cy = _crlb_xy(psf, x0, y0, flux, sig)
    rng = np.random.default_rng(7)
    clean = es.pixel_integrated(psf, SHAPE, x0, y0, flux) + 5.0
    var = np.full(SHAPE, sig**2)
    dx, dy, sx, sy = [], [], [], []
    for _ in range(400):
        f = _fit(clean + rng.normal(0, sig, SHAPE), model, x0, y0, var=var, start=(x0 + rng.normal(0, 0.05), y0 + rng.normal(0, 0.05)))
        assert f.status == "ok"
        dx.append(f.x - x0)
        dy.append(f.y - y0)
        sx.append(f.sigma_x)
        sy.append(f.sigma_y)
    dx, dy = np.array(dx), np.array(dy)
    n = len(dx)
    assert abs(dx.mean()) < 4 * dx.std() / math.sqrt(n) and abs(dy.mean()) < 4 * dy.std() / math.sqrt(n)
    tol = 4 / math.sqrt(2 * n)
    assert dx.std() / cx == pytest.approx(1.0, abs=tol) and dy.std() / cy == pytest.approx(1.0, abs=tol)
    assert 0.98 < np.mean(sx) / cx < 1.10 and 0.98 < np.mean(sy) / cy < 1.10


def _phase_errors(render_psf, model, phases, **kw):  # noqa: ANN001, ANN202
    out = []
    for fx, fy in phases:
        x0, y0 = 10.0 + fx, 10.0 + fy
        img = es.pixel_integrated(render_psf, SHAPE, x0, y0, 1000.0) + 5.0
        if kw.get("gradient"):
            yy, xx = np.mgrid[0 : SHAPE[0], 0 : SHAPE[1]]
            img = img + kw["gradient"][0] * (xx - x0) + kw["gradient"][1] * (yy - y0)
        f = _fit(img, model, x0, y0)
        assert f.status == "ok"
        out.append((f.x - x0, f.y - y0))
    return np.array(out)


@pytest.mark.measurement
def test_symmetric_psf_mismatch_gives_an_odd_phase_error_without_mean_bias(nominal):
    """[measurement] Fitting a 10 % broader (or narrower) symmetric PSF: the error is an odd function of the
    sub-pixel phase (err(-p) = -err(p), by symmetry), so it averages to zero over phase, but it is not zero:
    a PSF-shape error appears as a pixel-phase error of order 1e-2 px."""
    _, model = nominal
    ph = [(p, 0.0) for p in (0.1, 0.2, 0.3, 0.4)]
    for scale in (1.1, 0.9):
        wrong = es.moffat(FWHM * scale, BETA)
        pos = _phase_errors(wrong, model, ph)
        neg = _phase_errors(wrong, model, [(-p, 0.0) for p, _ in ph])
        assert np.max(np.abs(pos[:, 0] + neg[:, 0])) < 1e-5 and np.max(np.abs(pos[:, 1])) < 1e-5
        assert 3e-3 < np.max(np.abs(pos[:, 0])) < 0.05


@pytest.mark.measurement
def test_asymmetric_psf_shift_follows_first_order_theory(nominal):
    """[measurement] A satellite of flux fraction f at distance d shifts a symmetric-model fit by f*d to first
    order in d (the light-centroid shift); for finite d the shift is smaller (higher-order terms) but of the same sign."""
    _, model = nominal
    ph = [(p, q) for p in (-0.3, 0.05, 0.35) for q in (-0.2, 0.2)]  # mirror-symmetric across the satellite axis
    small = _phase_errors(es.moffat(FWHM, BETA, sat_frac=0.2, sat_dx=0.05), model, ph)
    assert small[:, 0].mean() == pytest.approx(0.2 * 0.05, rel=0.02) and abs(small[:, 1].mean()) < 1e-4
    for f, d in ((0.05, 0.5), (0.10, 0.3)):
        e = _phase_errors(es.moffat(FWHM, BETA, sat_frac=f, sat_dy=d), model, [(q, p) for p, q in ph])
        assert 0.75 * f * d < e[:, 1].mean() <= 1.01 * f * d and abs(e[:, 0].mean()) < 1e-4


@pytest.mark.measurement
def test_plane_background_absorbs_a_linear_gradient_exactly(nominal):
    """[measurement] The fit model includes a plane, so adding an exact plane to the data changes no position
    (the least-squares problem is the same after re-parametrising the plane) - also under PSF mismatch."""
    _, model = nominal
    ph = [(-0.37, 0.12), (0.08, -0.29), (0.41, 0.44)]
    for psf in (es.moffat(FWHM, BETA), es.moffat(FWHM * 1.1, BETA, q=0.85, theta_deg=30.0)):
        base = _phase_errors(psf, model, ph)
        grad = _phase_errors(psf, model, ph, gradient=(4.0, -2.5))
        assert np.max(np.abs(base - grad)) < 1e-6


@pytest.mark.measurement
def test_masking_pixels_never_reduces_the_formal_error_and_does_not_bias_a_matched_fit(nominal):
    """[measurement] Removing pixels removes information: the formal sigma can only grow; with the right PSF and
    no noise the position stays exact."""
    psf, model = nominal
    x0, y0 = 10.18, 9.77
    img = es.pixel_integrated(psf, SHAPE, x0, y0, 1000.0) + 5.0
    full = _fit(img, model, x0, y0)
    bad = np.zeros(SHAPE, bool)
    bad[8, 12] = bad[11, 8] = bad[12, 11] = True  # outside the 3x3 core, inside the 7x7 window
    masked = _fit(img, model, x0, y0, bad=bad)
    assert masked.n_masked == 3 and masked.sigma_x >= full.sigma_x and masked.sigma_y >= full.sigma_y
    assert math.hypot(masked.x - x0, masked.y - y0) < 2e-3


@pytest.mark.measurement
def test_neighbour_bias_is_linear_for_faint_neighbours_and_large_just_outside_the_isolation_radius(nominal):
    """[measurement] A faint neighbour perturbs the fit linearly in its flux (5 % vs 10 % at 2 px: ratio 2), and an
    equal-flux neighbour at 2.05 px - admitted by the 2 px / 10 % isolation rule - shifts the fit by > 0.1 px
    (documented limitation; the estimator review simulates the catalogued neighbours of every reference)."""
    psf, model = nominal
    ph = [(-0.3, 0.1), (0.0, -0.2), (0.25, 0.3)]

    def bias(sep: float, ratio: float) -> float:
        out = []
        for fx, fy in ph:
            x0, y0 = 10.0 + fx, 10.0 + fy
            img = es.pixel_integrated(psf, SHAPE, x0, y0, 1000.0) + es.pixel_integrated(psf, SHAPE, x0 + sep, y0, 1000.0 * ratio) + 5.0
            f = _fit(img, model, x0, y0)
            out.append(f.x - x0)
        return float(np.mean(out))

    b5, b10 = bias(2.0, 0.05), bias(2.0, 0.10)
    assert b5 > 0 and b10 / b5 == pytest.approx(2.0, rel=0.05)
    assert bias(2.05, 1.0) > 0.1


@pytest.mark.measurement
def test_real_spherex_epsf_rendered_by_photutils_is_recovered_exactly():
    """[measurement] A real SPHEREx zone ePSF (committed fixture) rendered with photutils ImagePSF (an independent
    implementation) is fitted back to < 1e-6 px; the two evaluations agree to rounding."""
    pytest.importorskip("photutils")
    from astropy.io import fits
    from photutils.psf import ImagePSF

    from skyshift.imaging.epsf import EPSFLibrary
    from skyshift.providers.spherex.paths import FIXTURE_ROOT

    lib = EPSFLibrary.from_hdu(fits.open(FIXTURE_ROOT / "spherex-dr1-barnard" / "fixture_cutout_D1_trimmed_epsf.fits")["EPSF"])
    ox, oy = lib.oversampling
    ip = ImagePSF(data=lib.arrays[0] * ox * oy, oversampling=(oy, ox))
    yy, xx = np.mgrid[0 : SHAPE[0], 0 : SHAPE[1]]
    for x0, y0 in ((10.31, 9.62), (9.55, 10.48)):
        img = ip.evaluate(xx, yy, flux=1000.0, x_0=x0, y_0=y0) + 5.0
        assert np.max(np.abs(img - 5.0 - lib.model(0).render(SHAPE, x0, y0, 1000.0))) < 1e-9 * img.max()
        f = _fit(img, lib.model(0), x0, y0)
        assert f.status == "ok" and math.hypot(f.x - x0, f.y - y0) < 1e-6
