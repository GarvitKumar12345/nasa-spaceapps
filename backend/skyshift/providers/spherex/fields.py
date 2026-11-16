"""Field presets for bounded SPHEREx investigations (chosen from actual archive coverage)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from skyshift.providers.spherex.wavelength import DEFAULT_MAX_DELTA_FRACTION


@dataclass(frozen=True)
class StudyTarget:
    """A named target of a motion study in a field. The literature astrometry only locates pixels; the Gaia DR3
    identity is established in the recorded field response by propagation to the exposure epochs (never by
    catalogue-epoch coordinates) and is then excluded from the field's reference stars."""

    name: str
    ra_j2000_deg: float
    dec_j2000_deg: float
    pmra_arcsec_yr: float
    pmdec_arcsec_yr: float
    parallax_mas: float
    astrometry_source: str
    gaia_dr3_source_id: str | None = None


@dataclass(frozen=True)
class FieldPreset:
    id: str  # dataset id
    title: str
    collection: str
    ra_deg: float
    dec_deg: float
    centre_note: str
    purpose: str
    search_radius_deg: float = 0.0003  # images containing the field centre (~1 arcsec)
    cutout_size_deg: float = 0.1
    max_cutouts: int = 24
    max_per_group: int = 4
    contrast_per_detector: int = 1
    max_delta_fraction: float = DEFAULT_MAX_DELTA_FRACTION
    min_edge_margin_px: float = 32.0  # cutout half-width + margin, so cutouts are not clipped
    display_grid_px: int = 64
    study_target: StudyTarget | None = None

    def as_dict(self) -> dict:
        return asdict(self)


PRESETS: dict[str, FieldPreset] = {
    "spherex-dr1-barnard": FieldPreset(
        id="spherex-dr1-barnard",
        title="SPHEREx DR1 · field around Barnard's Star (GJ 699)",
        collection="spherex_dr1",
        ra_deg=269.44628,
        dec_deg=4.76803,
        centre_note=(
            "Field centre = approximate position of Barnard's Star for 2025.9 (published astrometry propagated by hand), "
            "used only to centre the archive query and cutouts. SkyShift has not identified, matched or measured any "
            "source in these images; Gaia DR3 matching is a later step."
        ),
        purpose=(
            "First real-image viewer field: chosen because a live DR1 discovery query found 239 Spectral Images "
            "containing this position, in two observing seasons (Aug-Sep 2025, Mar-May 2026), on all six detectors, "
            "one processing version (v27) and no duplicate products."
        ),
    ),
    "spherex-dr1-vanmaanen2": FieldPreset(
        id="spherex-dr1-vanmaanen2",
        title="SPHEREx DR1 · field around van Maanen 2 (WD 0046+051)",
        collection="spherex_dr1",
        ra_deg=12.30010,
        dec_deg=5.36918,
        centre_note=(
            "Field centre = approximate position of van Maanen 2 for 2025.8 (literature J2000 position 00 49 09.90 +05 23 19.0 and proper "
            "motion (+1.23, -2.71)\"/yr propagated by hand), used only to centre the archive query and cutouts. SkyShift has not "
            "identified, matched or measured any source in these images; Gaia DR3 predictions need a recorded Gaia query for this field."
        ),
        purpose=(
            "Stage-1 verification field for a candidate known moving source (white dwarf, proper motion ~3\"/yr): a bounded DR1 SIA2 "
            "query on 2026-11-15 found 216 Spectral Images containing this position, in two observing seasons (2025-06/07 and "
            "2025-12/2026-01), on all six detectors. Data acquisition and checks only: no target measurement is enabled."
        ),
        study_target=StudyTarget(
            name="van Maanen 2 (WD 0046+051)", ra_j2000_deg=12.291242, dec_j2000_deg=5.388609, pmra_arcsec_yr=1.2313, pmdec_arcsec_yr=-2.7119,
            parallax_mas=231.7, astrometry_source="approximate literature values (J2000 position, proper motion, parallax); not a recorded catalogue query",
            # identified in the recorded Gaia DR3 field response (fixtures/gaia_dr3/spherex-dr1-vanmaanen2) by propagation to all 13
            # exposure epochs: unique source within 0.24" of the literature position, |mu| = 2.98"/yr (scripts/target_astrometry.py)
            gaia_dr3_source_id="2552928187080872832",
        ),
    ),
}
