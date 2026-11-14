"""Astropy runtime configuration for reproducible, offline operation.

SkyShift never downloads IERS tables at runtime. UTC<->TT<->TDB conversions use
ERFA plus the leap-second table bundled with astropy-iers-data; UT1 (Earth
rotation) is not needed by any SkyShift computation. The solar-system
ephemeris is astropy's 'builtin' (ERFA epv00), which needs no download.
"""

from astropy.utils import iers

iers.conf.auto_download = False
iers.conf.auto_max_age = None

SOLAR_SYSTEM_EPHEMERIS = "builtin"
