"""Field presets for bounded SPHEREx investigations (chosen from actual archive coverage)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from skyshift.providers.spherex.wavelength import DEFAULT_MAX_DELTA_FRACTION


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
}
