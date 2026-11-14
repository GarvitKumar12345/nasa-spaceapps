"""Documented SPHEREx facts used by the provider, with their sources.

Everything here was read from the primary documents listed in REFERENCES on
2026-11-14 (documentation review, not a live test). Values that a file states
about itself (flag bit definitions, units, WCS keywords, ePSF sampling) are
read from that file and checked against these documented values; they are
never taken from this module when the file provides them.
"""

from __future__ import annotations

from dataclasses import dataclass

from skyshift.contracts import Reference

DOC_REVIEW_UTC = "2026-11-14T00:00:00Z"
EXPLANATORY_SUPPLEMENT = "SPHEREx Explanatory Supplement SSDC-DP-017 v2.1 (2026-11-10)"

REFERENCES = [
    Reference(title="SPHEREx archive access documentation (collections, SIA2, cutouts)", url="https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/"),
    Reference(title="SPHEREx data-product documentation (Spectral Image MEF layout)", url="https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/"),
    Reference(title="IRSA tutorial: SPHEREx spectral image introduction (SIA, extensions, flags, spectral WCS)", url="https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/"),
    Reference(title="IRSA tutorial: SPHEREx spectral image cutouts (TAP + cutout URLs)", url="https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/"),
    Reference(title="IRSA tutorial: SPHEREx PSF models (ePSF format by VERSION)", url="https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/"),
    Reference(title="IRSA IBE cutout service parameters", url="https://irsa.ipac.caltech.edu/ibe/cutouts.html"),
    Reference(title=EXPLANATORY_SUPPLEMENT, url="https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf"),
    Reference(title="IRSA SPHEREx Spectrophotometry Tool help (flag handling)", url="https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html"),
]


@dataclass(frozen=True)
class Collection:
    id: str
    release: str
    survey: str
    pipeline: str
    description: str


# Searchable Spectral Image collections (data-access documentation, SIA2 COLLECTION values).
# DR1 = R7 reprocessing of surveys 1-2 (Year 1); QR3 = R7 processing of surveys 3-4 (ES v2.1 Sect. 2.1).
COLLECTIONS: dict[str, Collection] = {
    "spherex_dr1": Collection("spherex_dr1", "DR1", "wide", "R7 (VERSION >= 7.0)", "DR1 Spectral Image MEFs, Wide Survey"),
    "spherex_dr1_deep": Collection("spherex_dr1_deep", "DR1", "deep", "R7 (VERSION >= 7.0)", "DR1 Spectral Image MEFs, Deep Survey"),
    "spherex_qr3": Collection("spherex_qr3", "QR3", "wide", "R7 (VERSION >= 7.0)", "QR3 Spectral Image MEFs, Wide Survey"),
    "spherex_qr3_deep": Collection("spherex_qr3_deep", "QR3", "deep", "R7 (VERSION >= 7.0)", "QR3 Spectral Image MEFs, Deep Survey"),
}
UNSUPPORTED_COLLECTIONS: dict[str, str] = {
    "spherex_qr2": "QR2 is superseded by DR1/QR3, no longer searchable via SIA2 (download-only until February 2027) and stores the legacy PSF cube; not supported.",
    "spherex_qr": "QR1 is superseded and must not be combined with later releases; not supported.",
    "spherex_dr1_cube": "All-Sky Cube products are not Spectral Images; not supported by this provider.",
}

# Spectral Image MEF extensions for pipeline R7 (DR1/QR3), read by EXTNAME, never by position.
EXPECTED_EXTENSIONS_R7: tuple[str, ...] = ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "EPSF", "WCS-WAVE")
# Pre-R7 (QR1/QR2) files carry a 'PSF' image cube instead of the 'EPSF' table.
LEGACY_PSF_EXTENSION = "PSF"
R7_MIN_VERSION = (7, 0)

# Units as documented (IMAGE/ZODI: MJy/sr, VARIANCE: (MJy/sr)^2, FLAGS dimensionless).
IMAGE_UNIT = "MJy / sr"
VARIANCE_UNIT = "MJy2 / sr2"

# ES v2.1 Table 16: Level 2 image pixel flags (bit -> name). Bit 29 exists in the table but is
# not defined in every file header; files are checked against this table, not the reverse.
DOCUMENTED_FLAGS: dict[int, str] = {
    0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC", 7: "DICHROIC", 9: "MISSING_DATA",
    10: "HOT", 11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS", 15: "NONLINEAR", 17: "PERSIST",
    19: "OUTLIER", 20: "CROSSTALK", 21: "SOURCE", 22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT",
    25: "STREAK", 26: "BLOOM", 27: "SNOWBALL", 28: "HALO", 29: "SATELLITE_HALO",
}
# ES v2.1 Sect. 3.3, "Flags for masking pixels for photometry calculations".
PHOTOMETRY_MASK_FLAGS: tuple[str, ...] = (
    "SUR_ERROR", "NONFUNC", "MISSING_DATA", "HOT", "COLD", "NONLINEAR", "PERSIST", "BLOOM", "SNOWBALL", "HALO", "SATELLITE_HALO",
)
# ES v2.1 Sect. 3.3: flags that raise the L3 CONTAINS_BAD_PIXEL warning (minus the photometry-mask set above).
CAUTION_FLAGS: tuple[str, ...] = ("TRANSIENT", "OVERFLOW", "DICHROIC", "CROSSTALK", "GHOST", "GHOST_FPA", "GHOST_EXT", "STREAK")
# ES v2.1 Table 16: FULLSAMPLE is "purely informational"; SOURCE marks a known source (informational per the IRSA tool help).
INFORMATIONAL_FLAGS: tuple[str, ...] = ("SOURCE", "FULLSAMPLE")
# Radius used by the L3 photometry for its CONTAINS_BAD_PIXEL summary (ES v2.1 Sect. 3.3).
FLAG_SUMMARY_RADIUS_PX = 2.5


def flag_class(name: str) -> str:
    """'photometry_mask' | 'caution' | 'informational' | 'other' (documented but not in any list, e.g. PHANMISS, OUTLIER)."""
    if name in PHOTOMETRY_MASK_FLAGS:
        return "photometry_mask"
    if name in CAUTION_FLAGS:
        return "caution"
    if name in INFORMATIONAL_FLAGS:
        return "informational"
    return "other"


# Data-product documentation band table (micrometres). SIA energy_bandpassname 'SPHEREx-Dn' and
# em_min/em_max tie band n to detector n; the per-file WCS-WAVE values are checked against SIA em_min/em_max.
DOCUMENTED_BAND_RANGES_UM: dict[int, tuple[float, float]] = {
    1: (0.75, 1.09), 2: (1.10, 1.62), 3: (1.63, 2.41), 4: (2.42, 3.82), 5: (3.83, 4.41), 6: (4.42, 5.00),
}
DETECTOR_SHAPE = (2040, 2040)
NOMINAL_PIXEL_SCALE_ARCSEC = 6.15  # ES v2.1 Sect. 4.2.2 ("1 px ~ 6.15 arcsec")

# ES v2.1 Sect. 3.2.8: FINAST 0 = good astrometry, 1 = partial (corner offsets of a couple of pixels),
# >1 = poor (images should not be used). Archive inclusion requires FINAST = 0 and L2DQA = PASS (Sect. 3.2.12).
FINAST_GOOD = 0
# ES v2.1 Sect. 4.2.2: re-extracted bright stars vs Gaia/2MASS give RMS < 0.3 arcsec (detector 3 shown).
DOCUMENTED_ASTROMETRIC_RMS_ARCSEC = 0.3

# ES v2.1 Sect. 4.2.3: ePSF per zone, 5x oversampled, 33x33 samples, unit total flux, includes the
# detector-pixel response (not deconvolved). Zones: 21x21 (detectors 1,2,4,5,6) or 11x41 (detector 3).
EPSF_COLUMNS: tuple[str, ...] = ("XCENTER", "YCENTER", "CWAVE", "CBAND", "EPSF")
EPSF_ZONES = {1: 441, 2: 441, 3: 451, 4: 441, 5: 441, 6: 441}

# WCS-WAVE is a bilinear lookup table (~1 nm), suitable for visualization only; science needs the
# Spectral WCS calibration product (CWAVE/CBAND images). Data-product docs; ES v2.1 Sect. 4.3.1.
WCS_WAVE_ACCURACY_UM = 0.001
WAVELENGTH_VISUALIZATION_NOTE = (
    "Local wavelength from the file's WCS-WAVE lookup table (bilinear, ~1 nm): documented as suitable for "
    "visualization only. Quantitative work needs the Spectral WCS calibration product (CWAVE/CBAND), which "
    "SkyShift does not retrieve in this build."
)
