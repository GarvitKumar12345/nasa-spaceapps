"""Point-source detection on original image arrays (matched filter + PSF refinement)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from astropy.stats import sigma_clipped_stats
from scipy.ndimage import gaussian_filter, maximum_filter

from skyshift.imaging.psf import PSFFit, fit_psf

DETECT_METHOD_VERSION = "1.0.0"


@dataclass
class Detection:
    x: float
    y: float
    cov_xy: np.ndarray
    flux: float
    flux_err: float
    snr: float
    background: float
    peak_snr: float
    psf_status: str
    flags: list[str] = field(default_factory=list)
    fit: PSFFit | None = None


def background_stats(image: np.ndarray, mask: np.ndarray, bad_bits: int = 0xFFFF) -> tuple[float, float, float]:
    """Sigma-clipped (mean, median, std) of unmasked finite pixels."""
    good = ((mask & bad_bits) == 0) & np.isfinite(image)
    mean, median, std = sigma_clipped_stats(image[good], sigma=3.0, maxiters=10)
    return float(mean), float(median), float(std)


def detect_sources(
    image: np.ndarray,
    variance: np.ndarray,
    mask: np.ndarray,
    sigma_px: float,
    threshold: float = 5.0,
    min_sep_px: float = 2.0,
    edge_px: int = 3,
    bad_bits: int = 0xFFFF,
    refine: bool = True,
) -> list[Detection]:
    """Detect point sources; masked pixels never seed or bias a detection.

    The background-subtracted image (masked pixels set to 0) is smoothed with
    the PSF Gaussian (matched filter); peaks above `threshold` times the
    sigma-clipped noise of the filtered map are refined with `fit_psf`.
    Rejected fits are dropped; duplicates converging within `min_sep_px`
    keep the brighter one. Sorted by decreasing flux.
    """
    good = ((mask & bad_bits) == 0) & np.isfinite(image)
    _, median, _ = background_stats(image, mask, bad_bits)
    work = np.where(good, image - median, 0.0)
    filtered = gaussian_filter(work, sigma_px, mode="constant", cval=0.0)
    _, f_med, f_std = sigma_clipped_stats(filtered[good], sigma=3.0, maxiters=10)
    size = 2 * int(np.ceil(min_sep_px)) + 1
    peaks = (filtered == maximum_filter(filtered, size=size, mode="constant", cval=-np.inf)) & good
    peaks &= (filtered - f_med) > threshold * f_std
    ny, nx = image.shape
    peaks[:edge_px, :] = peaks[-edge_px:, :] = False
    peaks[:, :edge_px] = peaks[:, -edge_px:] = False
    iy, ix = np.nonzero(peaks)
    order = np.argsort(-filtered[iy, ix])
    detections: list[Detection] = []
    for k in order:
        x0, y0 = float(ix[k]), float(iy[k])
        peak_snr = float((filtered[iy[k], ix[k]] - f_med) / f_std)
        if not refine:
            detections.append(Detection(x0, y0, np.full((2, 2), np.nan), float("nan"), float("nan"), float("nan"), median, peak_snr, "not_fit"))
            continue
        fit = fit_psf(image, variance, mask, x0, y0, sigma_px, bad_bits=bad_bits)
        if fit.status == "rejected":
            continue
        detections.append(
            Detection(fit.x, fit.y, fit.cov_xy, fit.flux, fit.flux_err, fit.snr, fit.background, peak_snr, fit.status, list(fit.flags), fit)
        )
    detections.sort(key=lambda d: -d.flux if np.isfinite(d.flux) else 0.0)
    kept: list[Detection] = []
    for det in detections:
        if all(np.hypot(det.x - k.x, det.y - k.y) >= min_sep_px for k in kept):
            kept.append(det)
    return kept
