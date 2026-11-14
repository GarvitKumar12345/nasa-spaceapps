"""Time-scale and observer-geometry checks against independent relations."""

from __future__ import annotations

import numpy as np
import pytest
from astropy.time import Time

from skyshift.contracts import ObserverModel
from skyshift.coords.observer import (
    AU_KM,
    CIRCULAR_1AU,
    CIRCULAR_MAX_ERROR_AU,
    GEOCENTER_BUILTIN,
    SOLAR_SYSTEM_BARYCENTER,
    geocenter_suitability,
    observer_barycentric_au,
)
from skyshift.coords.time import MJD_J2000, add_seconds, epoch_from_isot_utc, epoch_from_jyear, jyear_to_mjd_tdb, mjd_tdb_to_jyear

pytestmark = pytest.mark.math


def test_utc_to_tt_offset_uses_leap_seconds():
    """TT - UTC = 32.184 s + 37 leap seconds (in force since 2017) for a 2025 epoch."""
    t = Time("2025-06-01T00:00:00", scale="utc")
    label_diff_days = (t.tt.jd1 - t.jd1) + (t.tt.jd2 - t.jd2)  # two-part JD keeps sub-microsecond precision
    assert label_diff_days * 86400.0 == pytest.approx(69.184, abs=1e-6)


def test_tdb_minus_tt_is_bounded():
    """|TDB - TT| < 2 ms (periodic terms ~1.66 ms) across the synthetic schedule."""
    for iso in ("2025-01-08T03:11:30", "2025-07-10T18:31:30", "2026-12-09T04:36:30"):
        e = epoch_from_isot_utc(iso)
        assert abs(e.mjd_tdb - Time(iso, scale="utc").tt.mjd) * 86400.0 < 2e-3


def test_gaia_epoch_tcb_to_tdb_matches_iau_b3():
    """J2016.0 TCB -> TDB agrees with IAU 2006 Res. B3 (TDB = TCB - L_B(JD_TCB - T0)86400 s + TDB0) to < 1 ms; convention kept."""
    e = epoch_from_jyear(2016.0, "tcb")
    jd_tcb = 2451545.0 + 16 * 365.25
    l_b, t0, tdb0 = 1.550519768e-8, 2443144.5003725, -6.55e-5
    tdb_jd = jd_tcb - l_b * (jd_tcb - t0) + tdb0 / 86400.0
    assert e.mjd_tdb == pytest.approx(tdb_jd - 2400000.5, abs=1e-3 / 86400.0)
    assert (e.value, e.format, e.scale) == (2016.0, "jyear", "tcb")


def test_julian_year_conversions_and_add_seconds():
    """J2000.0 is MJD 51544.5 TDB; Julian years are 365.25 d; start + 90 s keeps the scale."""
    assert mjd_tdb_to_jyear(MJD_J2000) == 2000.0
    assert jyear_to_mjd_tdb(2026.0) == pytest.approx(MJD_J2000 + 26 * 365.25)
    start = epoch_from_isot_utc("2025-01-08T03:10:00")
    mid = add_seconds(start, 90.0)
    assert mid.scale == "utc" and (mid.mjd_tdb - start.mjd_tdb) * 86400.0 == pytest.approx(90.0, abs=1e-6)


def test_geocenter_distance_and_annual_period():
    """Builtin Earth barycentric distance stays within 0.97-1.03 AU and repeats after one sidereal year."""
    r = np.linalg.norm(observer_barycentric_au(jyear_to_mjd_tdb(np.linspace(2025.0, 2027.0, 200))), axis=1)
    assert r.min() > 0.97 and r.max() < 1.03
    p0 = observer_barycentric_au(np.array([61000.0]))[0]
    p1 = observer_barycentric_au(np.array([61000.0 + 365.25636]))[0]
    assert np.linalg.norm(p1 - p0) < 0.02  # residual dominated by the Sun's barycentric motion


def test_circular_approximation_within_declared_bound():
    """The circular 1 AU teaching observer stays within its declared bound of the builtin ephemeris (1990-2030)."""
    t = jyear_to_mjd_tdb(np.linspace(1990.0, 2030.0, 400))
    d = np.linalg.norm(observer_barycentric_au(t, CIRCULAR_1AU) - observer_barycentric_au(t, GEOCENTER_BUILTIN), axis=1)
    assert d.max() < CIRCULAR_MAX_ERROR_AU


def test_barycenter_and_unsupported_observers():
    """Barycentric observer gives no parallax; spacecraft ephemerides are refused rather than approximated silently."""
    assert np.all(observer_barycentric_au(np.array([60000.0, 61000.0]), SOLAR_SYSTEM_BARYCENTER) == 0)
    with pytest.raises(NotImplementedError):
        observer_barycentric_au(np.array([60000.0]), ObserverModel(kind="spacecraft_ephemeris"))


def test_geocenter_suitability_bound():
    """Geocentre approximation error = parallax * r / 1 AU (165 mas, 7100 km -> < 10 microarcsec)."""
    out = geocenter_suitability(7100.0, 165.0)
    assert out["max_parallax_error_mas"] == pytest.approx(165.0 * 7100.0 / AU_KM)
    assert out["max_parallax_error_mas"] < 0.01  # 10 microarcsec
