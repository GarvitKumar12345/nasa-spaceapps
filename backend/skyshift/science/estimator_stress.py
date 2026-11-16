"""Controlled stress tests of the ePSF position estimator with an independent renderer.

The renderer here does not use skyshift.imaging.epsf: an analytic PSF (elliptical Moffat, optionally
with a displaced satellite component that breaks the symmetry) is integrated over each native pixel
by sub-pixel midpoint summation - no oversampled grid, no spline. The fitting model is an ePSF built
from an analytic PSF on the 5x oversampled grid following the Anderson & King definition (value =
flux in a native pixel centred at that offset), stored with the SPHEREx normalisation (sum 1 over the
oversampled grid), or a deliberately different PSF to measure mismatch biases.

Every case reports the position bias (mean recovered - true, px), its standard error, the RMS, the
robust pull width and the median chi2_red, over a regular grid of sub-pixel phases.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from skyshift.imaging.epsf import EPSFModel, fit_position

PSF = Callable[[np.ndarray, np.ndarray], np.ndarray]


def moffat(fwhm: float = 1.15, beta: float = 3.0, q: float = 1.0, theta_deg: float = 0.0,
           sat_frac: float = 0.0, sat_dx: float = 0.0, sat_dy: float = 0.0) -> PSF:
    """Unit-flux elliptical Moffat (axis ratio q, position angle theta), plus an optional satellite copy
    carrying `sat_frac` of the flux displaced by (sat_dx, sat_dy) px. The profile is centred on its core,
    so a satellite moves the light centroid by sat_frac * (sat_dx, sat_dy) / 1 (total flux stays 1)."""
    alpha = fwhm / (2.0 * math.sqrt(2.0 ** (1.0 / beta) - 1.0))
    norm = (beta - 1.0) / (math.pi * alpha * alpha * q)
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))

    def core(dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
        u = c * dx + s * dy
        v = -s * dx + c * dy
        return norm * (1.0 + (u * u + (v / q) ** 2) / (alpha * alpha)) ** (-beta)

    def f(dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
        out = (1.0 - sat_frac) * core(dx, dy)
        if sat_frac:
            out = out + sat_frac * core(dx - sat_dx, dy - sat_dy)
        return out

    return f


def _sub_offsets(sub: int) -> np.ndarray:
    return (np.arange(sub) + 0.5) / sub - 0.5


def pixel_integrated(psf: PSF, shape: tuple[int, int], x0: float, y0: float, flux: float, sub: int = 9) -> np.ndarray:
    """Image of a point source: the PSF integrated over every native pixel (midpoint rule, sub x sub)."""
    ny, nx = shape
    o = _sub_offsets(sub)
    yy, xx = np.mgrid[0:ny, 0:nx]
    acc = np.zeros(shape)
    for oy in o:
        for ox in o:
            acc += psf(xx + ox - x0, yy + oy - y0)
    return flux * acc / (sub * sub)


def epsf_from_psf(psf: PSF, oversampling: int = 5, half: int = 16, sub: int = 9) -> np.ndarray:
    """A&K ePSF samples on the oversampled grid ((2*half+1)^2), normalised like SPHEREx (sum 1)."""
    k = (np.arange(2 * half + 1) - half) / oversampling
    gx, gy = np.meshgrid(k, k)
    o = _sub_offsets(sub)
    acc = np.zeros_like(gx)
    for oy in o:
        for ox in o:
            acc += psf(gx + ox, gy + oy)
    vals = acc / (sub * sub)  # flux fraction in a native pixel centred at each grid offset
    return vals / (oversampling * oversampling)


@dataclass
class Case:
    name: str
    render: PSF
    flux: float = 1000.0
    noise_sigma: float = 0.0
    background: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None
    n_masked: int = 0
    neighbour: tuple[float, float, float] | None = None  # (dx, dy, flux ratio) of a second source
    n_grid: int = 8
    realizations: int = 1


def run_case(case: Case, model: EPSFModel, seed: int = 0, half_window: int = 3) -> dict:
    """Fit `case` with `model` over an n_grid x n_grid grid of sub-pixel phases (x realizations)."""
    rng = np.random.default_rng(seed)
    shape = (21, 21)
    phases = (np.arange(case.n_grid) + 0.5) / case.n_grid - 0.5
    dx, dy, px, py, chi = [], [], [], [], []
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    for _ in range(case.realizations):
        for fx in phases:
            for fy in phases:
                x0, y0 = 10.0 + fx, 10.0 + fy
                img = pixel_integrated(case.render, shape, x0, y0, case.flux)
                if case.neighbour is not None:
                    ndx, ndy, ratio = case.neighbour
                    img = img + pixel_integrated(case.render, shape, x0 + ndx, y0 + ndy, case.flux * ratio)
                bg = case.background(xx - x0, yy - y0) if case.background is not None else np.zeros(shape)
                img = img + bg + 5.0
                var = np.full(shape, max(case.noise_sigma, 1e-3) ** 2)
                if case.noise_sigma > 0:
                    img = img + rng.normal(0.0, case.noise_sigma, shape)
                bad = np.zeros(shape, dtype=bool)
                if case.n_masked:
                    ring = [(iy, ix) for iy in range(7, 14) for ix in range(7, 14) if max(abs(iy - 10), abs(ix - 10)) >= 2]
                    for j in rng.choice(len(ring), size=case.n_masked, replace=False):
                        bad[ring[j]] = True
                start = (x0 + rng.normal(0, 0.2), y0 + rng.normal(0, 0.2))
                f = fit_position(img, var, bad, model, start[0], start[1], half_window=half_window)
                if f.status != "ok":
                    continue
                dx.append(f.x - x0)
                dy.append(f.y - y0)
                px.append((f.x - x0) / f.sigma_x if f.sigma_x else np.nan)
                py.append((f.y - y0) / f.sigma_y if f.sigma_y else np.nan)
                chi.append(f.chi2_red if f.chi2_red is not None else np.nan)
    dx, dy = np.array(dx), np.array(dy)
    n = len(dx)

    def rpull(p: list[float]) -> float:
        a = np.asarray(p, dtype=float)
        a = a[np.isfinite(a)]
        return float(1.4826 * np.median(np.abs(a - np.median(a)))) if a.size else float("nan")

    return {
        "case": case.name, "n": n, "n_failed": case.n_grid * case.n_grid * case.realizations - n,
        "bias_x_px": float(dx.mean()) if n else None, "bias_y_px": float(dy.mean()) if n else None,
        "se_x_px": float(dx.std(ddof=1) / math.sqrt(n)) if n > 1 else None, "se_y_px": float(dy.std(ddof=1) / math.sqrt(n)) if n > 1 else None,
        "rms_x_px": float(np.sqrt(np.mean(dx**2))) if n else None, "rms_y_px": float(np.sqrt(np.mean(dy**2))) if n else None,
        "max_abs_px": float(np.max(np.hypot(dx, dy))) if n else None,
        "robust_pull_x": rpull(px) if case.noise_sigma > 0 else None, "robust_pull_y": rpull(py) if case.noise_sigma > 0 else None,
        "chi2_red_median": float(np.nanmedian(chi)) if chi else None,
    }


def default_matrix(fwhm: float = 1.15, beta: float = 3.0) -> tuple[EPSFModel, list[Case]]:
    """The nominal model and the controlled variations used in the review (FWHM ~ SPHEREx SWIR ePSFs)."""
    nominal = moffat(fwhm, beta)
    model = EPSFModel(epsf_from_psf(nominal), (5, 5))
    peak = float(pixel_integrated(nominal, (21, 21), 10.0, 10.0, 1000.0).max())
    sig50 = 1000.0 / (50.0 * math.sqrt(3.6))  # pixel noise giving S/N ~ 50 for N_eff ~ 3.6
    cases = [
        Case("matched, noiseless", nominal),
        Case("matched, S/N~10", nominal, noise_sigma=sig50 * 5, realizations=4),
        Case("matched, S/N~20", nominal, noise_sigma=sig50 * 2.5, realizations=4),
        Case("matched, S/N~50", nominal, noise_sigma=sig50, realizations=4),
        Case("matched, S/N~200", nominal, noise_sigma=sig50 / 4, realizations=4),
        Case("PSF 10% broader", moffat(fwhm * 1.1, beta)),
        Case("PSF 10% narrower", moffat(fwhm * 0.9, beta)),
        Case("PSF elongated q=0.85 (PA 30 deg)", moffat(fwhm, beta, q=0.85, theta_deg=30.0)),
        Case("PSF wings beta=2.5", moffat(fwhm, 2.5)),
        Case("asymmetric: 5% satellite at +0.5 px (x)", moffat(fwhm, beta, sat_frac=0.05, sat_dx=0.5)),
        Case("asymmetric: 10% satellite at +0.3 px (y)", moffat(fwhm, beta, sat_frac=0.10, sat_dy=0.3)),
        Case("background gradient 2% of peak per px", nominal, background=lambda x, y: 0.02 * peak * (x + 0.5 * y)),
        Case("background curvature 1% of peak at r=3 px", nominal, background=lambda x, y: 0.01 * peak * (x * x + y * y) / 9.0),
        Case("1 masked pixel (not core)", nominal, n_masked=1),
        Case("3 masked pixels (not core)", nominal, n_masked=3),
        Case("neighbour 10% at 2.0 px", nominal, neighbour=(2.0, 0.0, 0.10)),
        Case("neighbour 10% at 3.0 px", nominal, neighbour=(3.0, 0.0, 0.10)),
        Case("neighbour 5% at 2.0 px", nominal, neighbour=(2.0, 0.0, 0.05)),
        Case("neighbour 30% at 3.5 px", nominal, neighbour=(3.5, 0.0, 0.30)),
    ]
    return model, cases


__all__ = ["Case", "default_matrix", "epsf_from_psf", "moffat", "pixel_integrated", "run_case"]
