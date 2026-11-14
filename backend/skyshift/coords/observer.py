"""Observer positions for astrometric models (barycentric, ICRS-aligned, AU).

The parallax term of every SkyShift astrometric model needs the observer's
barycentric position at each epoch. Supported observer models
(`ObserverModel.kind`):

* ``geocenter``: Earth barycentric position from astropy's ``builtin``
  ephemeris (ERFA epv00). This is the session-1 observer for both the
  synthetic truth and the fit.
* ``solar_system_barycenter``: the origin (no observer parallax).
* ``circular_1au_approximation``: a teaching approximation; a circle of 1 AU
  in the ecliptic plane, rotated into the equatorial frame.
* ``spacecraft_ephemeris``: not implemented in this build (raises).

Times are MJD in TDB. Positions are returned as an (N, 3) array in AU.
"""

from __future__ import annotations

import astropy.units as u
import numpy as np
import numpy.typing as npt
from astropy.coordinates import get_body_barycentric, solar_system_ephemeris
from astropy.time import Time

from skyshift._astropy_config import SOLAR_SYSTEM_EPHEMERIS
from skyshift.contracts import ObserverModel
from skyshift.coords.time import JULIAN_YEAR_DAYS, MJD_J2000

AU_KM = 149_597_870.7
"""Astronomical unit in km (IAU 2012 Resolution B2, exact)."""

EPV00_MAX_BARYCENTRIC_ERROR_KM = 13.4
"""Maximum barycentric Earth position error of ERFA/SOFA epv00 against JPL DE405
over 1900-2100, as stated in the SOFA epv00 documentation (note 4)."""

MEAN_OBLIQUITY_J2000_DEG = 23.4392911
"""Mean obliquity of the ecliptic at J2000.0 (84381.448 arcsec, IAU 1976/1980),
used only by the circular teaching approximation."""

EARTH_MEAN_LONGITUDE_J2000_DEG = 100.46646
"""Heliocentric mean ecliptic longitude of the Earth at J2000.0 TDB: the Sun's
geometric mean longitude 280.46646 deg (Meeus, Astronomical Algorithms, eq. 25.2)
minus 180 deg. Phase origin of the circular approximation in ICRS."""

CIRCULAR_MAX_ERROR_AU = 0.05
"""Declared bound on |circular approximation - true Earth position| for 1970-2030:
2e (radial + equation-of-centre terms, e = 0.0167) + 0.0102 AU (Sun-barycentre
offset) + 0.0033 AU (Julian-year vs sidereal-year phase drift over 30 yr),
rounded up. Checked against the builtin ephemeris in tests/test_observer.py."""

GEOCENTER_BUILTIN = ObserverModel(
    kind="geocenter",
    ephemeris="astropy builtin (ERFA epv00)",
    approximation_note=(
        "Observer at the geocentre; Earth barycentric position from ERFA epv00 "
        f"(max {EPV00_MAX_BARYCENTRIC_ERROR_KM} km vs JPL DE405, 1900-2100). "
        "A spacecraft observer differs by its orbit radius (see geocenter_suitability)."
    ),
    max_position_error_km=EPV00_MAX_BARYCENTRIC_ERROR_KM,
)

SOLAR_SYSTEM_BARYCENTER = ObserverModel(
    kind="solar_system_barycenter",
    ephemeris=None,
    approximation_note="Observer at the solar-system barycentre: no observer parallax (barycentric directions).",
    max_position_error_km=None,
)

CIRCULAR_1AU = ObserverModel(
    kind="circular_1au_approximation",
    ephemeris=None,
    approximation_note=(
        "Teaching approximation: circular 1 AU orbit in the ecliptic plane, period 1 Julian year, "
        f"phase = Earth mean longitude {EARTH_MEAN_LONGITUDE_J2000_DEG} deg at J2000.0 TDB, "
        f"mean obliquity {MEAN_OBLIQUITY_J2000_DEG} deg; frame bias and eccentricity neglected."
    ),
    max_position_error_km=CIRCULAR_MAX_ERROR_AU * AU_KM,
)

SPHEREX_LIKE_ORBIT_RADIUS_KM = 7100.0
"""Upper bound on the geocentric distance of a ~700 km altitude low Earth orbit
(Earth equatorial radius 6378 km + ~700 km), e.g. SPHEREx-like."""


def _as_mjd_array(mjd_tdb: npt.ArrayLike) -> np.ndarray:
    t = np.atleast_1d(np.asarray(mjd_tdb, dtype=float))
    if t.ndim != 1:
        raise ValueError("mjd_tdb must be a scalar or a 1-D array")
    if not np.all(np.isfinite(t)):
        raise ValueError("mjd_tdb must be finite")
    return t


def circular_observer_ecliptic_au(t_yr: npt.ArrayLike, phase0_rad: float = 0.0) -> np.ndarray:
    """Teaching observer on a circular 1 AU orbit, ecliptic frame, shape (N, 3) in AU.

    Frame: x toward the reference direction (the vernal equinox when mapped to
    ICRS), z toward the ecliptic north pole. Motion is prograde (counter-clockwise
    seen from +z) with a period of exactly 1 yr: longitude(t) = phase0 + 2*pi*t.
    """
    t = np.atleast_1d(np.asarray(t_yr, dtype=float))
    phase = phase0_rad + 2.0 * np.pi * t
    return np.column_stack([np.cos(phase), np.sin(phase), np.zeros_like(phase)])


def ecliptic_to_equatorial(xyz_ecliptic: npt.ArrayLike, obliquity_deg: float = MEAN_OBLIQUITY_J2000_DEG) -> np.ndarray:
    """Rotate (N, 3) ecliptic Cartesian vectors into the equatorial frame (rotation about x by the obliquity)."""
    v = np.atleast_2d(np.asarray(xyz_ecliptic, dtype=float))
    eps = np.radians(obliquity_deg)
    c, s = np.cos(eps), np.sin(eps)
    return np.column_stack([v[:, 0], c * v[:, 1] - s * v[:, 2], s * v[:, 1] + c * v[:, 2]])


def observer_barycentric_au(mjd_tdb: npt.ArrayLike, model: ObserverModel = GEOCENTER_BUILTIN) -> np.ndarray:
    """Barycentric observer position (ICRS-aligned Cartesian, AU) at MJD(TDB) epochs, shape (N, 3).

    Raises NotImplementedError for ``spacecraft_ephemeris`` and ValueError for
    a geocentre model that names an ephemeris other than the builtin one.
    """
    t = _as_mjd_array(mjd_tdb)
    if model.kind == "geocenter":
        if model.ephemeris != GEOCENTER_BUILTIN.ephemeris:
            raise ValueError(
                f"geocenter observer requires ephemeris {GEOCENTER_BUILTIN.ephemeris!r}; got {model.ephemeris!r}"
            )
        with solar_system_ephemeris.set(SOLAR_SYSTEM_EPHEMERIS):
            pos = get_body_barycentric("earth", Time(t, format="mjd", scale="tdb"))
        return np.ascontiguousarray(pos.xyz.to_value(u.au).T)
    if model.kind == "solar_system_barycenter":
        return np.zeros((t.size, 3))
    if model.kind == "circular_1au_approximation":
        t_yr = (t - MJD_J2000) / JULIAN_YEAR_DAYS
        ecliptic = circular_observer_ecliptic_au(t_yr, np.radians(EARTH_MEAN_LONGITUDE_J2000_DEG))
        return ecliptic_to_equatorial(ecliptic)
    if model.kind == "spacecraft_ephemeris":
        raise NotImplementedError(
            "spacecraft_ephemeris observer is not implemented in this build: no spacecraft orbit "
            "ephemeris (e.g. SPHEREx) is integrated yet. Use the geocentre model and quantify the "
            "approximation with geocenter_suitability()."
        )
    raise ValueError(f"unknown observer kind {model.kind!r}")


def geocenter_suitability(spacecraft_orbit_radius_km: float, parallax_mas: float) -> dict[str, float | str]:
    """Quantify the geocentre approximation for a spacecraft observer.

    Replacing an observer at distance r from the geocentre by the geocentre
    changes the parallactic displacement of a source with parallax p by at most
    p * r / 1 AU (the observer-position term only; aberration and light-time
    are separate effects not covered by this bound). Uses |parallax_mas|.
    """
    if not np.isfinite(spacecraft_orbit_radius_km) or spacecraft_orbit_radius_km < 0:
        raise ValueError("spacecraft_orbit_radius_km must be finite and >= 0")
    if not np.isfinite(parallax_mas):
        raise ValueError("parallax_mas must be finite")
    fraction = spacecraft_orbit_radius_km / AU_KM
    plx = abs(float(parallax_mas))
    max_error = plx * fraction
    statement = (
        f"Treating an observer up to {spacecraft_orbit_radius_km:,.0f} km from the Earth's centre as the geocentre "
        f"changes the parallactic displacement of a source with parallax {plx:.4g} mas by at most "
        f"{max_error:.3g} mas (r / 1 AU = {fraction:.3g} of the parallax). This bound covers the observer-position "
        "term only; aberration and light-time are separate effects."
    )
    return {
        "observer_model": "geocenter",
        "spacecraft_orbit_radius_km": float(spacecraft_orbit_radius_km),
        "parallax_mas": plx,
        "fraction_of_parallax": fraction,
        "max_parallax_error_mas": max_error,
        "statement": statement,
    }


__all__ = [
    "AU_KM",
    "CIRCULAR_1AU",
    "CIRCULAR_MAX_ERROR_AU",
    "EARTH_MEAN_LONGITUDE_J2000_DEG",
    "GEOCENTER_BUILTIN",
    "MEAN_OBLIQUITY_J2000_DEG",
    "SOLAR_SYSTEM_BARYCENTER",
    "SPHEREX_LIKE_ORBIT_RADIUS_KM",
    "circular_observer_ecliptic_au",
    "ecliptic_to_equatorial",
    "geocenter_suitability",
    "observer_barycentric_au",
]
