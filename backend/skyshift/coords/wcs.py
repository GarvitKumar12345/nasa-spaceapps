"""WCS helpers on top of astropy.wcs.

Pixel convention everywhere in SkyShift: 0-based, integer values at pixel
centres, numpy array index [iy, ix] <-> pixel (x=ix, y=iy). Astropy calls use
origin=0. FITS headers (WCSDescription.header) keep FITS 1-based CRPIX.
Pixel edges of an (ny, nx) array span x in [-0.5, nx-0.5], y in [-0.5, ny-0.5].
"""

from __future__ import annotations

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from skyshift.contracts import WCSDescription
from skyshift.coords.tangent import MAS_PER_RAD, offsets_mas, wrap_ra_deg

WCS_KIND = ("native_header", "registered", "common_grid", "simulation_truth")


def make_tan_wcs(
    center_ra_deg: float,
    center_dec_deg: float,
    pixel_scale_arcsec: float,
    shape: tuple[int, int],
    rotation_deg: float = 0.0,
    crpix0: tuple[float, float] | None = None,
) -> WCS:
    """TAN WCS with north up / east left at rotation 0.

    `rotation_deg` is the position angle of the image +y axis, measured from
    north through east. `crpix0` is the 0-based pixel at the reference point
    (default: array centre). CD = s * [[-cos t, sin t], [sin t, cos t]].
    """
    if pixel_scale_arcsec <= 0:
        raise ValueError("pixel_scale_arcsec must be positive")
    ny, nx = shape
    if crpix0 is None:
        crpix0 = ((nx - 1) / 2.0, (ny - 1) / 2.0)
    s = pixel_scale_arcsec / 3600.0
    t = np.radians(rotation_deg)
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.cunit = ["deg", "deg"]
    w.wcs.crval = [float(wrap_ra_deg(center_ra_deg)), float(center_dec_deg)]
    w.wcs.crpix = [crpix0[0] + 1.0, crpix0[1] + 1.0]  # FITS is 1-based
    w.wcs.cd = np.array([[-s * np.cos(t), s * np.sin(t)], [s * np.sin(t), s * np.cos(t)]])
    w.wcs.radesys = "ICRS"
    w.pixel_shape = (nx, ny)
    w.wcs.set()
    return w


def has_sip(w: WCS) -> bool:
    return w.sip is not None


def wcs_to_description(w: WCS, shape: tuple[int, int], kind: str) -> WCSDescription:
    """Serialise a celestial WCS to explicit FITS keywords (CD-matrix form for linear part)."""
    if kind not in WCS_KIND:
        raise ValueError(f"unknown WCS kind {kind!r}")
    ny, nx = shape
    cd = np.asarray(w.pixel_scale_matrix, dtype=float)  # CD-equivalent (deg/px) regardless of PC/CDELT form
    header: dict[str, float | int | str] = {
        "NAXIS": 2,
        "NAXIS1": int(nx),
        "NAXIS2": int(ny),
        "CTYPE1": str(w.wcs.ctype[0]),
        "CTYPE2": str(w.wcs.ctype[1]),
        "CUNIT1": "deg",
        "CUNIT2": "deg",
        "CRVAL1": float(w.wcs.crval[0]),
        "CRVAL2": float(w.wcs.crval[1]),
        "CRPIX1": float(w.wcs.crpix[0]),
        "CRPIX2": float(w.wcs.crpix[1]),
        "CD1_1": float(cd[0, 0]),
        "CD1_2": float(cd[0, 1]),
        "CD2_1": float(cd[1, 0]),
        "CD2_2": float(cd[1, 1]),
        "RADESYS": str(w.wcs.radesys or "ICRS"),
    }
    distortion = "none"
    if has_sip(w):
        distortion = "sip"
        sip_hdr = w.to_header(relax=True)
        for key, value in sip_hdr.items():
            if key.startswith(("A_", "B_", "AP_", "BP_")):
                header[key] = float(value) if isinstance(value, float) else value
    return WCSDescription(kind=kind, header=header, shape=(int(ny), int(nx)), distortion=distortion)


def description_to_wcs(desc: WCSDescription) -> WCS:
    hdr = fits.Header()
    for key, value in desc.header.items():
        hdr[key] = value
    w = WCS(hdr)
    ny, nx = desc.shape
    w.pixel_shape = (nx, ny)
    return w


def pixel_to_sky(w: WCS, x: float | np.ndarray, y: float | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """0-based pixel -> (ra_deg in [0,360), dec_deg), including any SIP distortion."""
    ra, dec = w.all_pix2world(np.asarray(x, dtype=float), np.asarray(y, dtype=float), 0)
    return wrap_ra_deg(ra), np.asarray(dec)


def sky_to_pixel(w: WCS, ra_deg: float | np.ndarray, dec_deg: float | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(ra, dec) -> 0-based pixel, including any SIP distortion."""
    x, y = w.all_world2pix(np.asarray(ra_deg, dtype=float), np.asarray(dec_deg, dtype=float), 0)
    return np.asarray(x), np.asarray(y)


def local_jacobian_mas_per_px(w: WCS, x: float, y: float, step_px: float = 0.5) -> np.ndarray:
    """2x2 matrix J with [d_east_mas, d_north_mas]^T = J @ [dx, dy]^T at pixel (x, y).

    Central finite differences through the full WCS (valid with distortion).
    """
    ra0, dec0 = pixel_to_sky(w, x, y)
    pts_x = np.array([x + step_px, x - step_px, x, x])
    pts_y = np.array([y, y, y + step_px, y - step_px])
    ra, dec = pixel_to_sky(w, pts_x, pts_y)
    east, north = offsets_mas(ra, dec, float(ra0), float(dec0))
    jac = np.empty((2, 2))
    jac[0, 0] = (east[0] - east[1]) / (2 * step_px)
    jac[1, 0] = (north[0] - north[1]) / (2 * step_px)
    jac[0, 1] = (east[2] - east[3]) / (2 * step_px)
    jac[1, 1] = (north[2] - north[3]) / (2 * step_px)
    return jac


def pixel_scale_arcsec(w: WCS) -> float:
    """Geometric-mean pixel scale of the linear part (arcsec/px)."""
    return float(np.sqrt(abs(np.linalg.det(np.asarray(w.pixel_scale_matrix)))) * 3600.0)


def footprint_icrs(w: WCS, shape: tuple[int, int]) -> list[tuple[float, float]]:
    """Sky positions of the four outer pixel-edge corners, counter-clockwise in pixel space."""
    ny, nx = shape
    xs = np.array([-0.5, nx - 0.5, nx - 0.5, -0.5])
    ys = np.array([-0.5, -0.5, ny - 0.5, ny - 0.5])
    ra, dec = pixel_to_sky(w, xs, ys)
    return [(float(r), float(d)) for r, d in zip(ra, dec, strict=True)]


def mas_to_px(value_mas: float, w: WCS) -> float:
    return value_mas / (pixel_scale_arcsec(w) * 1000.0)


__all__ = [
    "MAS_PER_RAD",
    "make_tan_wcs",
    "wcs_to_description",
    "description_to_wcs",
    "pixel_to_sky",
    "sky_to_pixel",
    "local_jacobian_mas_per_px",
    "pixel_scale_arcsec",
    "footprint_icrs",
    "has_sip",
    "mas_to_px",
]
