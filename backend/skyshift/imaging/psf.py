"""Pixel-integrated Gaussian PSF: rendering, fitting, and a windowed centroid.

Pixel convention: 0-based, integer values at pixel centres; pixel i spans
[i - 0.5, i + 0.5]. The model value of pixel (ix, iy) is the exact integral of
a circular Gaussian over that pixel (erf differences), so the model already
contains the pixel response and must not be integrated again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares
from scipy.special import ndtr

PSF_METHOD_VERSION = "1.0.0"
POOR_FIT_CHI2_RED = 2.0  # ~5 sigma above 1 for a ~49-pixel window
SQRT_8LN2 = 2.0 * math.sqrt(2.0 * math.log(2.0))
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


def fwhm_to_sigma(fwhm: float) -> float:
    return fwhm / SQRT_8LN2


def _pixel_fractions(n: int, centre: float, sigma: float, start: int = 0) -> np.ndarray:
    """Fraction of a unit 1-D Gaussian falling in pixels start..start+n-1."""
    edges = (np.arange(start, start + n + 1, dtype=float) - 0.5 - centre) / sigma
    return np.diff(ndtr(edges))


def _pixel_fraction_derivatives(n: int, centre: float, sigma: float, start: int = 0) -> np.ndarray:
    """d(fraction)/d(centre) for each pixel."""
    edges = (np.arange(start, start + n + 1, dtype=float) - 0.5 - centre) / sigma
    pdf = _INV_SQRT_2PI * np.exp(-0.5 * edges**2)
    return -(pdf[1:] - pdf[:-1]) / sigma


def gaussian_pixel_integrated(shape: tuple[int, int], x0: float, y0: float, flux: float, sigma_px: float) -> np.ndarray:
    """Image (ny, nx) of a pixel-integrated circular Gaussian with total flux `flux`."""
    ny, nx = shape
    return flux * np.outer(_pixel_fractions(ny, y0, sigma_px), _pixel_fractions(nx, x0, sigma_px))


def render_point_sources(
    shape: tuple[int, int],
    xs: np.ndarray,
    ys: np.ndarray,
    fluxes: np.ndarray,
    sigma_px: float,
    stamp_radius_px: int | None = None,
) -> np.ndarray:
    """Sum of pixel-integrated Gaussians, each evaluated on a stamp (truncation < 1e-8 of flux)."""
    ny, nx = shape
    image = np.zeros(shape, dtype=float)
    radius = stamp_radius_px if stamp_radius_px is not None else int(math.ceil(6.0 * sigma_px)) + 2
    for x0, y0, flux in zip(np.atleast_1d(xs), np.atleast_1d(ys), np.atleast_1d(fluxes), strict=True):
        ix0, iy0 = int(round(x0)) - radius, int(round(y0)) - radius
        ix1, iy1 = ix0 + 2 * radius + 1, iy0 + 2 * radius + 1
        cx0, cy0, cx1, cy1 = max(ix0, 0), max(iy0, 0), min(ix1, nx), min(iy1, ny)
        if cx0 >= cx1 or cy0 >= cy1:
            continue
        fx = _pixel_fractions(cx1 - cx0, x0, sigma_px, start=cx0)
        fy = _pixel_fractions(cy1 - cy0, y0, sigma_px, start=cy0)
        image[cy0:cy1, cx0:cx1] += flux * np.outer(fy, fx)
    return image


@dataclass
class PSFFit:
    method: str
    x: float
    y: float
    flux: float
    background: float
    cov_xy: np.ndarray  # 2x2, px^2
    flux_err: float
    snr: float
    chi2_red: float | None
    n_pixels: int
    converged: bool
    status: str  # 'ok' | 'warning' | 'rejected'
    flags: list[str] = field(default_factory=list)
    message: str = ""
    cov: np.ndarray | None = None  # full parameter covariance (x, y, flux, background)

    @property
    def sigma_x(self) -> float:
        return float(math.sqrt(self.cov_xy[0, 0]))

    @property
    def sigma_y(self) -> float:
        return float(math.sqrt(self.cov_xy[1, 1]))


def _rejected(x0: float, y0: float, flags: list[str], message: str, n: int = 0, method: str = "psf_gaussian_fit") -> PSFFit:
    return PSFFit(method=method, x=x0, y=y0, flux=float("nan"), background=float("nan"), cov_xy=np.full((2, 2), np.nan),
                  flux_err=float("nan"), snr=float("nan"), chi2_red=None, n_pixels=n, converged=False, status="rejected",
                  flags=flags, message=message)


def _window(shape: tuple[int, int], x0: float, y0: float, radius: int) -> tuple[int, int, int, int, bool]:
    ny, nx = shape
    ix, iy = int(round(x0)), int(round(y0))
    x_lo, x_hi, y_lo, y_hi = ix - radius, ix + radius + 1, iy - radius, iy + radius + 1
    truncated = x_lo < 0 or y_lo < 0 or x_hi > nx or y_hi > ny
    return max(x_lo, 0), min(x_hi, nx), max(y_lo, 0), min(y_hi, ny), truncated


def fit_psf(
    image: np.ndarray,
    variance: np.ndarray,
    mask: np.ndarray,
    x0: float,
    y0: float,
    sigma_px: float,
    fit_radius_px: int | None = None,
    bad_bits: int = 0xFFFF,
    max_shift_px: float = 2.0,
    low_snr: float = 5.0,
) -> PSFFit:
    """Weighted least-squares fit of (x, y, flux, background) on unmasked pixels.

    Weights are 1/variance from the variance plane. The covariance is
    (J^T W J)^-1 at the solution and is not rescaled by chi2 (chi2_red is
    reported as a quality indicator instead).
    """
    radius = fit_radius_px if fit_radius_px is not None else max(3, int(math.ceil(3.0 * sigma_px)))
    xl, xh, yl, yh, truncated = _window(image.shape, x0, y0, radius)
    flags: list[str] = []
    if truncated:
        flags.append("EDGE_TRUNCATED")
    if xl >= xh or yl >= yh:
        return _rejected(x0, y0, ["OUTSIDE_IMAGE"], "Fit window lies outside the image.")
    sub = image[yl:yh, xl:xh].astype(float)
    var = variance[yl:yh, xl:xh].astype(float)
    msk = mask[yl:yh, xl:xh]
    good = ((msk & bad_bits) == 0) & np.isfinite(sub) & np.isfinite(var) & (var > 0)
    if np.any((msk & bad_bits) != 0):
        flags.append("MASKED_PIXELS_IN_FIT")
    n = int(good.sum())
    if n < 12:
        return _rejected(x0, y0, [*flags, "TOO_FEW_PIXELS"], f"Only {n} usable pixels in the fit window.", n)
    yy, xx = np.nonzero(good)
    data = sub[good]
    w = 1.0 / np.sqrt(var[good])
    ny_w, nx_w = sub.shape

    ring = good.copy()
    ring[1:-1, 1:-1] = False
    bg0 = float(np.median(sub[ring])) if ring.any() else float(np.median(data))
    flux0 = max(float(np.sum(data - bg0)), 10.0 * float(np.sqrt(np.median(var[good]))))

    def model(p: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        fx = _pixel_fractions(nx_w, p[0], sigma_px, start=xl)
        fy = _pixel_fractions(ny_w, p[1], sigma_px, start=yl)
        return fx, fy, p[2] * fy[yy] * fx[xx] + p[3]

    def residual(p: np.ndarray) -> np.ndarray:
        return (model(p)[2] - data) * w

    def jacobian(p: np.ndarray) -> np.ndarray:
        fx, fy, _ = model(p)
        dfx = _pixel_fraction_derivatives(nx_w, p[0], sigma_px, start=xl)
        dfy = _pixel_fraction_derivatives(ny_w, p[1], sigma_px, start=yl)
        jac = np.empty((n, 4))
        jac[:, 0] = p[2] * fy[yy] * dfx[xx]
        jac[:, 1] = p[2] * dfy[yy] * fx[xx]
        jac[:, 2] = fy[yy] * fx[xx]
        jac[:, 3] = 1.0
        return jac * w[:, None]

    p0 = np.array([x0, y0, flux0, bg0])
    try:
        res = least_squares(residual, p0, jac=jacobian, method="lm", x_scale="jac", max_nfev=200)
    except (ValueError, np.linalg.LinAlgError) as exc:
        return _rejected(x0, y0, [*flags, "NOT_CONVERGED"], f"Least squares failed: {exc}", n)
    jac = jacobian(res.x)
    try:
        cov = np.linalg.inv(jac.T @ jac)
    except np.linalg.LinAlgError:
        return _rejected(x0, y0, [*flags, "SINGULAR_COVARIANCE"], "Singular normal matrix.", n)
    if not np.all(np.isfinite(cov)) or np.any(np.diag(cov) <= 0):
        return _rejected(x0, y0, [*flags, "SINGULAR_COVARIANCE"], "Non-finite covariance.", n)
    x, y, flux, bg = (float(v) for v in res.x)
    flux_err = float(math.sqrt(cov[2, 2]))
    snr = flux / flux_err if flux_err > 0 else float("nan")
    chi2_red = float(np.sum(res.fun**2) / (n - 4))
    converged = bool(res.success)
    status = "ok"
    message = ""
    if not converged:
        flags.append("NOT_CONVERGED")
        status = "rejected"
        message = res.message
    if math.hypot(x - x0, y - y0) > max_shift_px:
        flags.append("LARGE_SHIFT")
        status = "rejected"
        message = f"Fit moved {math.hypot(x - x0, y - y0):.2f} px from the initial position (> {max_shift_px} px)."
    if not (xl - 0.5 <= x <= xh - 0.5 and yl - 0.5 <= y <= yh - 0.5):
        flags.append("OUTSIDE_WINDOW")
        status = "rejected"
    if chi2_red > POOR_FIT_CHI2_RED:
        flags.append("POOR_PSF_FIT")  # residual structure: possible blend or PSF mismatch
    if flux <= 0:
        flags.append("NON_POSITIVE_FLUX")
        status = "rejected"
    elif snr < low_snr:
        flags.append("LOW_SNR")
    if status == "ok" and flags:
        status = "warning"
    return PSFFit(method="psf_gaussian_fit", x=x, y=y, flux=flux, background=bg, cov_xy=cov[:2, :2].copy(), flux_err=flux_err,
                  snr=float(snr), chi2_red=chi2_red, n_pixels=n, converged=converged, status=status, flags=flags,
                  message=message, cov=cov)


def windowed_centroid(
    image: np.ndarray,
    variance: np.ndarray,
    mask: np.ndarray,
    x0: float,
    y0: float,
    sigma_px: float,
    background: float | None = None,
    bad_bits: int = 0xFFFF,
    n_iter: int = 20,
) -> PSFFit:
    """Gaussian-windowed centroid (XWIN-like) with propagated uncertainty.

    Secondary method: x_{k+1} = x_k + 2 sum(w I (x - x_k)) / sum(w I), window
    sigma = PSF sigma. Uncertainty: 4 sum(w^2 var (x - x)^2) / (sum w I)^2.
    """
    radius = max(3, int(math.ceil(4.0 * sigma_px)))
    xl, xh, yl, yh, truncated = _window(image.shape, x0, y0, radius)
    flags = ["EDGE_TRUNCATED"] if truncated else []
    sub = image[yl:yh, xl:xh].astype(float)
    var = variance[yl:yh, xl:xh].astype(float)
    good = ((mask[yl:yh, xl:xh] & bad_bits) == 0) & np.isfinite(sub) & (var > 0)
    if np.any(~good):
        flags.append("MASKED_PIXELS_IN_FIT")
    if good.sum() < 12:
        return _rejected(x0, y0, [*flags, "TOO_FEW_PIXELS"], "Too few usable pixels.", int(good.sum()), "windowed_centroid")
    yy, xx = np.mgrid[yl:yh, xl:xh]
    if background is None:
        ring = good.copy()
        ring[1:-1, 1:-1] = False
        background = float(np.median(sub[ring])) if ring.any() else 0.0
    signal = np.where(good, sub - background, 0.0)
    x, y = float(x0), float(y0)
    converged = False
    for _ in range(n_iter):
        wgt = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma_px**2)) * good
        norm = float(np.sum(wgt * signal))
        if norm <= 0:
            return _rejected(x0, y0, [*flags, "NON_POSITIVE_FLUX"], "Windowed flux is not positive.", int(good.sum()), "windowed_centroid")
        dx = 2.0 * float(np.sum(wgt * signal * (xx - x))) / norm
        dy = 2.0 * float(np.sum(wgt * signal * (yy - y))) / norm
        x, y = x + dx, y + dy
        if math.hypot(dx, dy) < 1e-6:
            converged = True
            break
    wgt = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma_px**2)) * good
    norm = float(np.sum(wgt * signal))
    vx = 4.0 * float(np.sum(wgt**2 * np.where(good, var, 0.0) * (xx - x) ** 2)) / norm**2
    vy = 4.0 * float(np.sum(wgt**2 * np.where(good, var, 0.0) * (yy - y) ** 2)) / norm**2
    flux = float(np.sum(signal))
    flux_err = float(math.sqrt(np.sum(np.where(good, var, 0.0))))
    status = "ok" if converged and not flags else ("warning" if converged else "rejected")
    if not converged:
        flags.append("NOT_CONVERGED")
    return PSFFit(method="windowed_centroid", x=x, y=y, flux=flux, background=background, cov_xy=np.diag([vx, vy]),
                  flux_err=flux_err, snr=flux / flux_err if flux_err > 0 else float("nan"), chi2_red=None,
                  n_pixels=int(good.sum()), converged=converged, status=status, flags=flags)
