"""Reprojection of native frames onto the common sky grid (display products only).

Bilinear interpolation correlates neighbouring output pixels and smooths the
noise, so reprojected arrays are display-only: measurements always use the
native arrays. Masked input pixels become NaN before interpolation, so any
output pixel that depends on them stays missing.
"""

from __future__ import annotations

import numpy as np
from astropy.wcs import WCS
from scipy.ndimage import map_coordinates

from skyshift.coords.wcs import pixel_to_sky
from skyshift.imaging.registration import RegisteredWCS

COVARIANCE_NOTE = (
    "Bilinear reprojection onto the common grid correlates neighbouring pixels and reduces the apparent "
    "pixel-to-pixel noise; use this product for display and difference previews only."
)


def reproject_to_grid(
    image: np.ndarray,
    mask: np.ndarray,
    registered: RegisteredWCS,
    out_wcs: WCS,
    out_shape: tuple[int, int],
    order: int = 1,
    bad_bits: int = 0xFFFF,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (image on the output grid as float32 with NaN where missing, geometric coverage bool)."""
    ny, nx = out_shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    ra, dec = pixel_to_sky(out_wcs, xx.ravel().astype(float), yy.ravel().astype(float))
    xi, yi = registered.sky_to_pixel(ra, dec)
    in_ny, in_nx = image.shape
    coverage = (xi >= -0.5) & (xi <= in_nx - 0.5) & (yi >= -0.5) & (yi <= in_ny - 0.5)
    src = np.asarray(image, dtype=float).copy()
    src[(mask & bad_bits) != 0] = np.nan
    # Points inside an edge pixel's footprint (within half a pixel of the outermost
    # centres) take the edge value; clamping also removes round-off excursions
    # (~1e-10 px) that would otherwise pull NaN from outside the array.
    xc = np.clip(xi, 0.0, in_nx - 1.0)
    yc = np.clip(yi, 0.0, in_ny - 1.0)
    out = map_coordinates(src, [yc, xc], order=order, mode="nearest", prefilter=False)
    out[~coverage] = np.nan
    return out.reshape(out_shape).astype(np.float32), coverage.reshape(out_shape)


def difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """b - a with NaN wherever either input is missing."""
    return (np.asarray(b, dtype=np.float32) - np.asarray(a, dtype=np.float32)).astype(np.float32)
