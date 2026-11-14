"""Time handling with explicit time scales.

Recorded times keep their original value/format/scale in `Epoch`. All model
computations use TDB, either as MJD (`Epoch.mjd_tdb`) or as Julian years.
Catalog epochs (e.g. Gaia DR3 J2016.0, which is TCB) are converted with
astropy, never relabelled.
"""

from __future__ import annotations

from typing import Literal

import astropy.units as u
import numpy as np
from astropy.time import Time

from skyshift.contracts import Epoch, TimeScale

JULIAN_YEAR_DAYS = 365.25
MJD_J2000 = 51544.5  # J2000.0 = JD 2451545.0 (TT/TDB) -> MJD 51544.5

EpochFormat = Literal["isot", "mjd", "jd", "jyear"]


def to_time(value: float | str, fmt: EpochFormat, scale: TimeScale) -> Time:
    return Time(value, format=fmt, scale=scale)


def make_epoch(value: float | str, fmt: EpochFormat, scale: TimeScale) -> Epoch:
    """Build an Epoch, deriving mjd_tdb and a UTC display string with astropy."""
    t = to_time(value, fmt, scale)
    return Epoch(
        value=value,
        format=fmt,
        scale=scale,
        mjd_tdb=float(t.tdb.mjd),
        iso_utc=t.utc.isot,
    )


def epoch_from_isot_utc(isot: str) -> Epoch:
    return make_epoch(isot, "isot", "utc")


def epoch_from_jyear(jyear: float, scale: TimeScale = "tdb") -> Epoch:
    return make_epoch(float(jyear), "jyear", scale)


def epoch_from_mjd_tdb(mjd_tdb: float) -> Epoch:
    return make_epoch(float(mjd_tdb), "mjd", "tdb")


def epoch_to_time(epoch: Epoch) -> Time:
    return to_time(epoch.value, epoch.format, epoch.scale)


def add_seconds(epoch: Epoch, seconds: float) -> Epoch:
    """Shift an epoch by `seconds` (SI seconds), keeping its scale; result is ISO-T."""
    t = epoch_to_time(epoch) + seconds * u.s
    return make_epoch(t.isot, "isot", epoch.scale)


def mjd_tdb_to_jyear(mjd_tdb: float | np.ndarray) -> float | np.ndarray:
    """Julian epoch (TDB) from MJD(TDB): 2000.0 + (MJD - 51544.5) / 365.25."""
    return 2000.0 + (np.asarray(mjd_tdb, dtype=float) - MJD_J2000) / JULIAN_YEAR_DAYS


def jyear_to_mjd_tdb(jyear: float | np.ndarray) -> float | np.ndarray:
    return MJD_J2000 + (np.asarray(jyear, dtype=float) - 2000.0) * JULIAN_YEAR_DAYS


def years_between(mjd_tdb_from: float | np.ndarray, mjd_tdb_to: float | np.ndarray) -> float | np.ndarray:
    """Elapsed Julian years (TDB) from `mjd_tdb_from` to `mjd_tdb_to`."""
    return (np.asarray(mjd_tdb_to, dtype=float) - np.asarray(mjd_tdb_from, dtype=float)) / JULIAN_YEAR_DAYS
