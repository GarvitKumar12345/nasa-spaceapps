"""Documented Gaia DR3 facts used by the provider, with their sources.

Read from the primary documents in REFERENCES (documentation review 2026-11-14).
Values the archive states about its own response (column units, datatypes, the
RELEASE parameter, the COOSYS epoch, QUERY_STATUS) are read from each response
and checked against these documented values; they are never assumed from here.
"""

from __future__ import annotations

from dataclasses import dataclass

from skyshift.contracts import Reference

DOC_REVIEW_UTC = "2026-11-14T00:00:00Z"

TAP_BASE = "https://gea.esac.esa.int/tap-server/tap"
TAP_SYNC_URL = f"{TAP_BASE}/sync"
ALLOWED_PREFIXES: tuple[str, ...] = ("https://gea.esac.esa.int/tap-server/",)
USER_AGENT = "SkyShift/0.1 (local research build; bounded Gaia DR3 client)"

GAIA_TABLE = "gaiadr3.gaia_source"
GAIA_RELEASE = "Gaia DR3"
# gaia_source data model: ref_epoch is the reference epoch in Julian years; for DR3 it is 2016.0 for every
# source and, like all Gaia times, refers to TCB (Gaia DR3 documentation, astrometric data / data model).
REFERENCE_EPOCH_JYEAR = 2016.0
REFERENCE_EPOCH_SCALE = "tcb"
COOSYS_EPOCH = "J2016.0"

# astrometric_params_solved: 3 = 2-parameter (position only), 31 = 5-parameter, 95 = 6-parameter
# (5 + pseudocolour). For 2-parameter solutions parallax and proper motion are NULL.
SOLUTION_BY_PARAMS = {3: "2-parameter", 31: "5-parameter", 95: "6-parameter"}

# Renormalised unit weight error: values well above 1 indicate a poor single-star fit (e.g. unresolved
# binaries). 1.4 is the threshold recommended by Lindegren (2018, GAIA-C3-TN-LU-LL-124) and used widely for DR3.
RUWE_THRESHOLD = 1.4

# Largest known stellar proper motion: Barnard's Star, |mu| = 10.39 arcsec/yr in Gaia DR3 (and the maximum
# of `pm` in this field's response). Rounded up, it bounds the motion of any catalogued star since J2016.0.
MAX_STELLAR_PROPER_MOTION_ARCSEC_YR = 10.5

# Astronomical unit expressed in km yr / s: A = 1 au / (1 Julian year) in km/s^-1 units, used in mu_r = v_r * parallax / A
# (ESA 1997, Vol. 1, Sect. 1.5.5; Gaia DR3 documentation, astrometric parameter transformations).
A_KM_YR_PER_S = 4.740470463533348  # = 149597870.7 km / (365.25 * 86400 s)


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    unit: str | None  # astropy unit string; None = dimensionless/none declared
    datatypes: tuple[str, ...]  # VOTable datatypes accepted for this column
    role: str  # astrometry | quality | photometry | radial_velocity | identity


def _c(name: str, unit: str | None, datatypes: tuple[str, ...], role: str) -> ColumnSpec:
    return ColumnSpec(name, unit, datatypes, role)


# Columns requested from gaiadr3.gaia_source, with the units and datatypes documented in the DR3 data model.
FIELD_COLUMNS: tuple[ColumnSpec, ...] = (
    _c("source_id", None, ("long",), "identity"),
    _c("ref_epoch", "yr", ("double",), "astrometry"),
    _c("ra", "deg", ("double",), "astrometry"),
    _c("ra_error", "mas", ("float", "double"), "astrometry"),
    _c("dec", "deg", ("double",), "astrometry"),
    _c("dec_error", "mas", ("float", "double"), "astrometry"),
    _c("parallax", "mas", ("double",), "astrometry"),
    _c("parallax_error", "mas", ("float", "double"), "astrometry"),
    _c("pmra", "mas / yr", ("double",), "astrometry"),
    _c("pmra_error", "mas / yr", ("float", "double"), "astrometry"),
    _c("pmdec", "mas / yr", ("double",), "astrometry"),
    _c("pmdec_error", "mas / yr", ("float", "double"), "astrometry"),
    _c("ra_dec_corr", None, ("float", "double"), "astrometry"),
    _c("ra_parallax_corr", None, ("float", "double"), "astrometry"),
    _c("ra_pmra_corr", None, ("float", "double"), "astrometry"),
    _c("ra_pmdec_corr", None, ("float", "double"), "astrometry"),
    _c("dec_parallax_corr", None, ("float", "double"), "astrometry"),
    _c("dec_pmra_corr", None, ("float", "double"), "astrometry"),
    _c("dec_pmdec_corr", None, ("float", "double"), "astrometry"),
    _c("parallax_pmra_corr", None, ("float", "double"), "astrometry"),
    _c("parallax_pmdec_corr", None, ("float", "double"), "astrometry"),
    _c("pmra_pmdec_corr", None, ("float", "double"), "astrometry"),
    _c("astrometric_params_solved", None, ("short", "int", "unsignedByte"), "astrometry"),
    _c("nu_eff_used_in_astrometry", "1 / um", ("float", "double"), "astrometry"),
    _c("pseudocolour", "1 / um", ("float", "double"), "astrometry"),
    _c("visibility_periods_used", None, ("short", "int"), "quality"),
    _c("ruwe", None, ("float", "double"), "quality"),
    _c("astrometric_excess_noise", "mas", ("float", "double"), "quality"),
    _c("astrometric_excess_noise_sig", None, ("float", "double"), "quality"),
    _c("ipd_frac_multi_peak", None, ("short", "int", "unsignedByte"), "quality"),
    _c("ipd_gof_harmonic_amplitude", None, ("float", "double"), "quality"),
    _c("duplicated_source", None, ("boolean",), "quality"),
    _c("non_single_star", None, ("short", "int", "unsignedByte"), "quality"),
    _c("phot_g_mean_mag", "mag", ("float", "double"), "photometry"),
    _c("phot_bp_mean_mag", "mag", ("float", "double"), "photometry"),
    _c("phot_rp_mean_mag", "mag", ("float", "double"), "photometry"),
    _c("bp_rp", "mag", ("float", "double"), "photometry"),
    _c("phot_variable_flag", None, ("char", "unicodeChar"), "photometry"),
    _c("radial_velocity", "km / s", ("float", "double"), "radial_velocity"),
    _c("radial_velocity_error", "km / s", ("float", "double"), "radial_velocity"),
    _c("grvs_mag", "mag", ("float", "double"), "radial_velocity"),
    _c("rv_template_teff", "K", ("float", "double"), "radial_velocity"),
)
COLUMN_NAMES: tuple[str, ...] = tuple(c.name for c in FIELD_COLUMNS)

CORRELATION_COLUMNS: tuple[str, ...] = (
    "ra_dec_corr", "ra_parallax_corr", "ra_pmra_corr", "ra_pmdec_corr", "dec_parallax_corr",
    "dec_pmra_corr", "dec_pmdec_corr", "parallax_pmra_corr", "parallax_pmdec_corr", "pmra_pmdec_corr",
)

ACKNOWLEDGEMENT = (
    "This work has made use of data from the European Space Agency (ESA) mission Gaia (https://www.cosmos.esa.int/gaia), "
    "processed by the Gaia Data Processing and Analysis Consortium (DPAC, https://www.cosmos.esa.int/web/gaia/dpac/consortium). "
    "Funding for the DPAC has been provided by national institutions, in particular the institutions participating in the "
    "Gaia Multilateral Agreement."
)
CITATIONS: tuple[str, ...] = (
    "Gaia Collaboration, Vallenari, A., et al. 2023, A&A 674, A1 (Gaia Data Release 3: summary of the content and survey properties)",
    "Gaia Collaboration, Prusti, T., et al. 2016, A&A 595, A1 (The Gaia mission)",
)

REFERENCES = [
    Reference(title="Gaia DR3 data model: gaiadr3.gaia_source", url="https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html"),
    Reference(title="Gaia DR3 documentation (ESA)", url="https://gea.esac.esa.int/archive/documentation/GDR3/"),
    Reference(title="ESA Gaia archive help (TAP, ADQL)", url="https://www.cosmos.esa.int/web/gaia-users/archive"),
    Reference(title="Astroquery Gaia TAP documentation", url="https://astroquery.readthedocs.io/en/latest/gaia/gaia.html"),
    Reference(title="Astropy coordinates: apply_space_motion", url="https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html"),
    Reference(title="Gaia credits and citation", url="https://www.cosmos.esa.int/web/gaia-users/credits"),
    Reference(title="Gaia DR3 known issues", url="https://www.cosmos.esa.int/web/gaia/dr3-known-issues"),
]
