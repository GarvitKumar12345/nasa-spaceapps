"""Local SPHEREx wavelength at a sky position, and wavelength-compatibility groups.

SPHEREx wavelength varies across each detector (linear variable filters), so the
wavelength of an observation is evaluated at the query position's pixel, not taken
from the detector number. Two evaluations of the same documented WCS-WAVE lookup
are provided: astropy's FITS '-TAB' implementation (as in the IRSA tutorials) and
an independent bilinear implementation of the data-product description; tests
require them to agree. Both are visualization-grade (~1 nm, documented).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

_SIP_KEY = re.compile(r"^(A|B|AP|BP)_(\d+_\d+|ORDER|DMAX)$")

# A pair of observations is wavelength-compatible for side-by-side/blink display when they come
# from the same detector and their local central wavelengths differ by at most this fraction of the
# smaller local bandwidth (>= 75 % passband overlap for top-hat passbands of equal width).
DEFAULT_MAX_DELTA_FRACTION = 0.25


def spectral_header(image_header: fits.Header) -> fits.Header:
    """IMAGE header without SIP keywords: SIP describes optical distortion and must not be applied
    to the lettered spectral WCS (the IRSA tutorial sets `sip = None` for the same reason)."""
    h = image_header.copy()
    for key in list(h.keys()):
        if _SIP_KEY.match(key):
            del h[key]
    return h


def spectral_wcs(image_header: fits.Header, hdul: fits.HDUList) -> WCS:
    if str(image_header.get("CTYPE1W", "")).strip() != "WAVE-TAB" or str(image_header.get("PS1_0W", "")).strip() != "WCS-WAVE":
        raise ValueError("IMAGE header lacks the documented WAVE-TAB spectral WCS (key 'W')")
    w = WCS(spectral_header(image_header), fobj=hdul, key="W")
    w.sip = None
    return w


def wavelength_astropy(image_header: fits.Header, hdul: fits.HDUList, x0: float, y0: float) -> tuple[float, float]:
    """(central wavelength, bandwidth) in micrometres at 0-based pixel (x0, y0) via astropy -TAB."""
    lam, bw = spectral_wcs(image_header, hdul).pixel_to_world_values(float(x0), float(y0))
    return float(lam), float(bw)


@dataclass(frozen=True)
class WaveTable:
    x: np.ndarray  # index vector for pixel axis 1 (raw FITS coordinates)
    y: np.ndarray  # index vector for pixel axis 2
    values: np.ndarray  # (ny, nx, 2): [..., 0] wavelength, [..., 1] bandwidth (um)

    @classmethod
    def from_hdu(cls, hdu: fits.BinTableHDU) -> WaveTable:
        row = hdu.data[0]
        x = np.asarray(row["X"], dtype=float).ravel()
        y = np.asarray(row["Y"], dtype=float).ravel()
        values = np.asarray(row["VALUES"], dtype=float)
        if values.shape != (y.size, x.size, 2):
            raise ValueError(f"WCS-WAVE VALUES shape {values.shape} does not match X/Y ({y.size}, {x.size}, 2)")
        if not (np.all(np.diff(x) > 0) and np.all(np.diff(y) > 0)):
            raise ValueError("WCS-WAVE index vectors must be strictly increasing")
        return cls(x, y, values)


def lookup_coordinates(image_header: fits.Header, x0: float, y0: float) -> tuple[float, float]:
    """Table coordinates psi = CDELT*(p - CRPIX) + CRVAL with p the 1-based FITS pixel (FITS Paper III, -TAB)."""
    if any(k in image_header for k in ("PC1_2W", "PC2_1W", "CD1_1W")):
        raise ValueError("rotated spectral WCS lookups are not supported by the independent evaluator")
    px, py = x0 + 1.0, y0 + 1.0
    psx = float(image_header.get("CDELT1W", 1.0)) * (px - float(image_header["CRPIX1W"])) + float(image_header.get("CRVAL1W", 0.0))
    psy = float(image_header.get("CDELT2W", 1.0)) * (py - float(image_header["CRPIX2W"])) + float(image_header.get("CRVAL2W", 0.0))
    return psx, psy


def wavelength_bilinear(image_header: fits.Header, table: WaveTable, x0: float, y0: float) -> tuple[float, float]:
    """Independent evaluation: locate psi in the X/Y control points and interpolate the four nearest
    VALUES bilinearly (data-product documentation). NaN outside the control-point grid."""
    psx, psy = lookup_coordinates(image_header, x0, y0)
    if not (table.x[0] <= psx <= table.x[-1] and table.y[0] <= psy <= table.y[-1]):
        return float("nan"), float("nan")
    i = min(int(np.searchsorted(table.x, psx, side="right")) - 1, table.x.size - 2)
    j = min(int(np.searchsorted(table.y, psy, side="right")) - 1, table.y.size - 2)
    fx = (psx - table.x[i]) / (table.x[i + 1] - table.x[i])
    fy = (psy - table.y[j]) / (table.y[j + 1] - table.y[j])
    v = table.values
    out = (1 - fx) * (1 - fy) * v[j, i] + fx * (1 - fy) * v[j, i + 1] + (1 - fx) * fy * v[j + 1, i] + fx * fy * v[j + 1, i + 1]
    return float(out[0]), float(out[1])


# ------------------------------------------------------------------ compatibility


@dataclass(frozen=True)
class WavelengthSample:
    key: str  # observation key, e.g. '2025W34_1A_0012_3:D1'
    detector: int
    lambda_um: float
    bandwidth_um: float
    t_mjd: float


def pair_compatible(a: WavelengthSample, b: WavelengthSample, max_delta_fraction: float = DEFAULT_MAX_DELTA_FRACTION) -> bool:
    """Same detector AND |dlambda| <= f * min(bandwidth). Detector equality alone is never sufficient."""
    return a.detector == b.detector and abs(a.lambda_um - b.lambda_um) <= max_delta_fraction * min(a.bandwidth_um, b.bandwidth_um)


def _window_ok(w: list[WavelengthSample], f: float) -> bool:
    return (w[-1].lambda_um - w[0].lambda_um) <= f * min(s.bandwidth_um for s in w)


def compatibility_groups(samples: list[WavelengthSample], max_delta_fraction: float = DEFAULT_MAX_DELTA_FRACTION) -> list[list[WavelengthSample]]:
    """Partition samples into groups in which every pair is compatible.

    Per detector, samples are sorted by wavelength; the largest contiguous window whose
    wavelength range is within f * (smallest bandwidth in the window) is taken first
    (ties: longer time baseline, then smaller spread, then shorter wavelength), and the
    process repeats on the remainder. Deterministic; singletons are returned as groups of one.
    """
    if not 0 < max_delta_fraction <= 1:
        raise ValueError("max_delta_fraction must be in (0, 1]")
    bad = [s.key for s in samples if not (np.isfinite(s.lambda_um) and np.isfinite(s.bandwidth_um) and s.bandwidth_um > 0)]
    if bad:
        raise ValueError(f"samples without a finite local wavelength/bandwidth: {bad}")
    groups: list[list[WavelengthSample]] = []
    for det in sorted({s.detector for s in samples}):
        pool = sorted((s for s in samples if s.detector == det), key=lambda s: (s.lambda_um, s.key))
        while pool:
            best: tuple | None = None
            for a in range(len(pool)):
                b = a
                while b + 1 < len(pool) and _window_ok(pool[a : b + 2], max_delta_fraction):
                    b += 1
                w = pool[a : b + 1]
                times = [s.t_mjd for s in w]
                score = (len(w), max(times) - min(times), -(w[-1].lambda_um - w[0].lambda_um), -w[0].lambda_um)
                if best is None or score > best[0]:
                    best = (score, a, b)
            assert best is not None
            _, a, b = best
            groups.append(pool[a : b + 1])
            pool = pool[:a] + pool[b + 1 :]
    return groups
