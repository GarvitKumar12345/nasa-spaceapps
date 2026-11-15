"""SPHEREx effective-PSF evaluation and position fitting (skyshift.imaging.epsf).

Offline, on the committed real DR1 cutout fixture (IMAGE/VARIANCE/FLAGS as delivered; EPSF table
trimmed to the zones under the cutout, labelled SKYTRIM). References that do not use the code under
test: the stored ePSF samples themselves (exact on the 5x lattice), the documented normalisation,
the IRSA tutorial's zone-selection rule, and injection into the real pixels with a loop written here.
"""

from __future__ import annotations

import numpy as np
import pytest

from skyshift.imaging.epsf import EPSFLibrary, EPSFModel, fit_position
from skyshift.providers.spherex.fitsfile import read_spectral_image
from skyshift.providers.spherex.paths import FIXTURE_ROOT

FIXTURE = FIXTURE_ROOT / "spherex-dr1-barnard" / "fixture_cutout_D1_trimmed_epsf.fits"


@pytest.fixture(scope="module")
def img():
    return read_spectral_image(FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def lib(img) -> EPSFLibrary:
    assert img.epsf_library is not None
    return img.epsf_library


@pytest.mark.measurement
def test_normalisation_matches_the_documentation(lib):
    """[measurement] Each 33x33 zone sums to 1 over the 5x grid ('normalized to its integral'); native-spacing samples x 25 sum to ~1 (A&K flux fractions)."""
    chk = lib.native_sum_check()
    assert chk["oversampled_sum_min"] == pytest.approx(1.0, abs=1e-9) and chk["oversampled_sum_max"] == pytest.approx(1.0, abs=1e-9)
    assert 0.97 < chk["native_sum_scaled_min"] and chk["native_sum_scaled_max"] < 1.04
    assert lib.oversampling == (5, 5) and lib.arrays.shape[1:] == (33, 33)
    for k in range(len(lib.zones)):
        a = lib.arrays[k]
        assert np.unravel_index(np.argmax(a), a.shape) in {(16, 16), (16, 17), (17, 16), (15, 16), (16, 15)}  # peak at the reference index


@pytest.mark.measurement
def test_interpolating_model_equals_the_stored_samples_on_the_lattice(lib):
    """[measurement] At offsets that are multiples of 1/5 px the model returns exactly 25 x the stored sample (axis order and centre convention)."""
    m = lib.model(0)
    k = np.arange(-16, 17)
    dx, dy = np.meshgrid(k / 5.0, k / 5.0)
    vals = m.evaluate(dx, dy)
    assert np.allclose(vals, 25.0 * lib.arrays[0], rtol=0, atol=1e-12)
    assert m.evaluate(np.array([3.3]), np.array([0.0]))[0] == 0.0  # outside the sampled support


@pytest.mark.measurement
def test_noiseless_lattice_renders_are_recovered(lib):
    """[measurement] Stars rendered from the stored samples alone (no interpolation) at 25 sub-pixel phases are fitted back to < 1e-3 px."""
    m = lib.model(1)
    shape = (21, 21)
    var = np.full(shape, 1e-4)
    bad = np.zeros(shape, dtype=bool)
    worst = 0.0
    for fx in range(5):
        for fy in range(5):
            x0, y0 = 10.0 + fx / 5.0, 10.0 + fy / 5.0
            image = m.sample_exact(shape, x0, y0, 100.0) + 2.0
            fit = fit_position(image, var, bad, m, x0 + 0.3, y0 - 0.25)
            assert fit.status == "ok"
            worst = max(worst, abs(fit.x - x0), abs(fit.y - y0))
            assert fit.flux == pytest.approx(100.0, rel=2e-3)
    assert worst < 1e-3


@pytest.mark.measurement
def test_zone_lookup_follows_the_detector_coordinate_convention(img, lib):
    """[measurement] Zones are chosen from detector pixels (cutout + 1 - CRPIX1A); every cutout pixel lies in a kept zone, which is also the nearest centre (IRSA tutorial rule)."""
    ox, oy = img.detector_offset()
    assert ox == pytest.approx(1.0 - float(img.image_header["CRPIX1A"])) and oy == pytest.approx(1.0 - float(img.image_header["CRPIX2A"]))
    ny, nx = img.shape
    centres = np.array([[z.x_center, z.y_center] for z in lib.zones])
    for y in range(0, ny, 4):
        for x in range(0, nx, 4):
            dx, dy = x + ox, y + oy
            k = lib.zone_index(dx, dy)
            assert lib.zone_contains(k, dx, dy)
            assert k == int(np.argmin(np.hypot(centres[:, 0] - dx, centres[:, 1] - dy)))


def _fit_bad(img) -> np.ndarray:
    masks = {d.name: d.mask_value for d in img.flag_defs}
    excluded = sum(v for n, v in masks.items() if n not in ("SOURCE", "FULLSAMPLE"))
    return (img.flags.astype(np.int64) & excluded) != 0


@pytest.mark.measurement
def test_injection_into_real_pixels_is_unbiased_with_calibrated_errors(img, lib):
    """[measurement] 60 ePSF stars (S/N ~ 40) injected into the real cutout are recovered with |bias| < 3 SE + 0.005 px and robust pulls <= 1.5."""
    rng = np.random.default_rng(2026)
    image0, var = img.image.astype(float), img.variance.astype(float)
    bad = _fit_bad(img)
    masks = {d.name: d.mask_value for d in img.flag_defs}
    sat = (img.flags.astype(np.int64) & (masks["OVERFLOW"] | masks["SUR_ERROR"] | masks["BLOOM"])) != 0
    sy, sx = np.nonzero(sat)
    ny, nx = img.shape
    ox, oy = img.detector_offset()
    sig = float(np.nanmedian(np.sqrt(var[var > 0])))
    dxs, dys, pxs, pys = [], [], [], []
    while len(dxs) < 60:
        x0, y0 = rng.uniform(4, nx - 5), rng.uniform(4, ny - 5)
        ix, iy = int(round(x0)), int(round(y0))
        if np.any(bad[iy - 3 : iy + 4, ix - 3 : ix + 4]) or (len(sx) and np.min(np.hypot(sx - x0, sy - y0)) < 10):
            continue
        m = lib.model(lib.zone_index(x0 + ox, y0 + oy))
        image = image0 + m.render(image0.shape, x0, y0, 40.0 * sig * np.sqrt(3.6))
        fit = fit_position(image, var, bad, m, x0 + rng.normal(0, 0.3), y0 + rng.normal(0, 0.3))
        if fit.status != "ok":
            continue
        dxs.append(fit.x - x0)
        dys.append(fit.y - y0)
        pxs.append((fit.x - x0) / fit.sigma_x)
        pys.append((fit.y - y0) / fit.sigma_y)
    for d, p in ((np.array(dxs), np.array(pxs)), (np.array(dys), np.array(pys))):
        se = d.std(ddof=1) / np.sqrt(len(d))
        assert abs(d.mean()) < 3 * se + 0.005
        assert 1.4826 * np.median(np.abs(p - np.median(p))) <= 1.5


@pytest.mark.measurement
def test_edges_flags_and_runaway_fits_are_never_measurements(img, lib):
    """[measurement] A window over the edge, a mostly flagged window and a solution beyond the 2 px search box are reported as such, not as positions."""
    m = lib.model(0)
    image, var = img.image.astype(float), img.variance.astype(float)
    bad = np.zeros(img.shape, dtype=bool)
    assert fit_position(image, var, bad, m, 1.0, 20.0).status == "edge"
    bad2 = bad.copy()
    bad2[17:24, 17:24] = True
    bad2[20, 20] = False
    assert fit_position(image, var, bad2, m, 20.0, 20.0).status == "too_few_pixels"
    # A bright star 2.6 px from the starting point sits at the window edge: the fit either leaves the search box or
    # settles on the wing with a huge chi2 and an inflated sigma, which the alignment rejects (sigma > 0.25 px).
    from skyshift.science.alignment import AlignmentConfig

    shape = (31, 31)
    star = EPSFModel(lib.arrays[0], (5, 5)).render(shape, 15.0, 15.0, 1000.0) + 1.0
    fit = fit_position(star, np.full(shape, 1e-2), np.zeros(shape, dtype=bool), m, 15.0 + 2.6, 15.0, max_shift_px=2.0)
    assert fit.status != "ok" or (max(fit.sigma_x, fit.sigma_y) > AlignmentConfig().max_sigma_px and fit.chi2_red > 100)
