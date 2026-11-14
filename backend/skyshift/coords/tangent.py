"""Gnomonic (tangent-plane) projection and angle helpers.

Conventions: xi points east (+RA direction), eta points north (+Dec).
Offsets are standard coordinates in radians unless a function says mas.
For small offsets, xi ~= dRA * cos(Dec0), eta ~= dDec.
"""

from __future__ import annotations

import numpy as np

MAS_PER_RAD = 180.0 / np.pi * 3600.0 * 1000.0
ARCSEC_PER_RAD = 180.0 / np.pi * 3600.0


def wrap_ra_deg(ra_deg: float | np.ndarray) -> float | np.ndarray:
    """Wrap right ascension into [0, 360)."""
    ra = np.mod(np.asarray(ra_deg, dtype=float), 360.0)
    ra = np.where(ra >= 360.0, ra - 360.0, ra)  # guards mod returning 360.0 for tiny negatives
    ra = ra + 0.0  # normalise -0.0
    return float(ra) if np.ndim(ra) == 0 else ra


def validate_dec_deg(dec_deg: float | np.ndarray) -> None:
    dec = np.asarray(dec_deg, dtype=float)
    if not np.all(np.isfinite(dec)) or np.any(np.abs(dec) > 90.0):
        raise ValueError("Declination must be finite and within [-90, 90] degrees")


def sky_to_tangent(
    ra_deg: float | np.ndarray, dec_deg: float | np.ndarray, ra0_deg: float, dec0_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """Project (ra, dec) onto the tangent plane at (ra0, dec0). Returns (xi, eta) in radians.

    Raises ValueError for points 90 degrees or more from the tangent point,
    where the gnomonic projection is undefined.
    """
    validate_dec_deg(dec_deg)
    validate_dec_deg(dec0_deg)
    a = np.radians(np.asarray(ra_deg, dtype=float) - ra0_deg)
    d = np.radians(np.asarray(dec_deg, dtype=float))
    d0 = np.radians(dec0_deg)
    cos_c = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a)
    if np.any(cos_c <= 1e-12):
        raise ValueError("Point is 90 degrees or more from the tangent point; gnomonic projection undefined")
    xi = np.cos(d) * np.sin(a) / cos_c
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a)) / cos_c
    return xi, eta


def tangent_to_sky(
    xi: float | np.ndarray, eta: float | np.ndarray, ra0_deg: float, dec0_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse gnomonic projection. Returns (ra_deg in [0, 360), dec_deg)."""
    validate_dec_deg(dec0_deg)
    xi = np.asarray(xi, dtype=float)
    eta = np.asarray(eta, dtype=float)
    d0 = np.radians(dec0_deg)
    denom = np.cos(d0) - eta * np.sin(d0)
    dec = np.arctan2(np.sin(d0) + eta * np.cos(d0), np.hypot(xi, denom))
    ra = np.radians(ra0_deg) + np.arctan2(xi, denom)
    return wrap_ra_deg(np.degrees(ra)), np.degrees(dec)


def offsets_mas(
    ra_deg: float | np.ndarray, dec_deg: float | np.ndarray, ra0_deg: float, dec0_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """(east, north) tangent-plane offsets in milliarcseconds."""
    xi, eta = sky_to_tangent(ra_deg, dec_deg, ra0_deg, dec0_deg)
    return xi * MAS_PER_RAD, eta * MAS_PER_RAD


def apply_offsets_mas(
    east_mas: float | np.ndarray, north_mas: float | np.ndarray, ra0_deg: float, dec0_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    return tangent_to_sky(np.asarray(east_mas) / MAS_PER_RAD, np.asarray(north_mas) / MAS_PER_RAD, ra0_deg, dec0_deg)


def angular_separation_deg(
    ra1_deg: float | np.ndarray, dec1_deg: float | np.ndarray, ra2_deg: float | np.ndarray, dec2_deg: float | np.ndarray
) -> np.ndarray:
    """Great-circle separation (Vincenty formula; accurate at all separations)."""
    l1, b1, l2, b2 = (np.radians(np.asarray(v, dtype=float)) for v in (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    dl = l2 - l1
    num = np.hypot(np.cos(b2) * np.sin(dl), np.cos(b1) * np.sin(b2) - np.sin(b1) * np.cos(b2) * np.cos(dl))
    den = np.sin(b1) * np.sin(b2) + np.cos(b1) * np.cos(b2) * np.cos(dl)
    return np.degrees(np.arctan2(num, den))
