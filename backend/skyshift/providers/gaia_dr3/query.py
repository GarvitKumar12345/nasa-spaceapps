"""Explicit ADQL for gaiadr3.gaia_source and the justification of the search region.

The search circle must contain every catalogued star that lies inside any
SPHEREx cutout at its exposure epoch, plus the neighbours that can contribute
flux to pixels inside a cutout. Gaia positions refer to J2016.0, so the circle
is the union of the cutout footprints (largest corner distance from the field
centre, measured with each cutout's archive WCS) widened by

  * a proper-motion margin: mu_max * dt_max, where mu_max bounds every stellar
    proper motion (Barnard's Star, 10.39"/yr, the largest known, rounded up to
    10.5"/yr) and dt_max is the longest interval between J2016.0 and an
    exposure mid-time; and
  * a neighbour margin: sources up to `neighbour_margin_px` SPHEREx pixels
    outside a footprint can still put flux into its edge pixels (the ePSF
    support is +/-3.2 px) or fail an isolation test.

The tiny radius of the SPHEREx SIA discovery query (0.0003 deg, a point-in-
image test) is unrelated and never used here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from skyshift.providers.gaia_dr3 import reference as ref

MAX_SEARCH_RADIUS_DEG = 0.5
# ESA Gaia archive: anonymous TAP queries return at most 50 000 rows (archive quotas page and the TAP
# capabilities outputLimit). MAXREC is sent explicitly; truncation is reported by a QUERY_STATUS=OVERFLOW
# INFO that follows the table, which catalog.parse_gaia_votable checks (CSV output would truncate silently).
MAXREC = 50_000


@dataclass(frozen=True)
class SearchGeometry:
    center_ra_deg: float
    center_dec_deg: float
    footprint_radius_deg: float
    dt_max_yr: float
    max_proper_motion_arcsec_yr: float
    proper_motion_margin_deg: float
    neighbour_margin_px: float
    pixel_scale_arcsec: float
    neighbour_margin_deg: float
    radius_deg: float

    def as_dict(self) -> dict:
        return asdict(self)

    def derivation(self) -> str:
        return (
            f"radius = footprint {self.footprint_radius_deg * 3600:.1f}\" + proper-motion margin "
            f"{self.max_proper_motion_arcsec_yr:g}\"/yr x {self.dt_max_yr:.3f} yr = {self.proper_motion_margin_deg * 3600:.1f}\" "
            f"+ neighbour margin {self.neighbour_margin_px:g} px x {self.pixel_scale_arcsec:.2f}\"/px = {self.neighbour_margin_deg * 3600:.1f}\" "
            f"-> {self.radius_deg:.7f} deg ({self.radius_deg * 3600:.1f}\")"
        )


def search_geometry(
    center_ra_deg: float,
    center_dec_deg: float,
    footprint_radius_deg: float,
    dt_max_yr: float,
    *,
    max_proper_motion_arcsec_yr: float = ref.MAX_STELLAR_PROPER_MOTION_ARCSEC_YR,
    neighbour_margin_px: float = 6.0,
    pixel_scale_arcsec: float = 6.2,
) -> SearchGeometry:
    if not (0.0 < footprint_radius_deg < 0.4):
        raise ValueError("footprint_radius_deg must be in (0, 0.4) for a bounded cutout field")
    if not (0.0 <= dt_max_yr < 100.0):
        raise ValueError("dt_max_yr must be in [0, 100)")
    if max_proper_motion_arcsec_yr < ref.MAX_STELLAR_PROPER_MOTION_ARCSEC_YR:
        raise ValueError(f"max proper motion below the largest known stellar proper motion ({ref.MAX_STELLAR_PROPER_MOTION_ARCSEC_YR}\"/yr)")
    pm_margin = max_proper_motion_arcsec_yr * dt_max_yr / 3600.0
    nb_margin = neighbour_margin_px * pixel_scale_arcsec / 3600.0
    radius = footprint_radius_deg + pm_margin + nb_margin
    # Round up to the 7th decimal used in the ADQL text, so the stated radius is never smaller than the derived one.
    radius = math.ceil(radius * 1e7) / 1e7
    if radius > MAX_SEARCH_RADIUS_DEG:
        raise ValueError(f"search radius {radius:.4f} deg exceeds the {MAX_SEARCH_RADIUS_DEG} deg bound")
    return SearchGeometry(
        center_ra_deg=center_ra_deg % 360.0,
        center_dec_deg=center_dec_deg,
        footprint_radius_deg=footprint_radius_deg,
        dt_max_yr=dt_max_yr,
        max_proper_motion_arcsec_yr=max_proper_motion_arcsec_yr,
        proper_motion_margin_deg=pm_margin,
        neighbour_margin_px=neighbour_margin_px,
        pixel_scale_arcsec=pixel_scale_arcsec,
        neighbour_margin_deg=nb_margin,
        radius_deg=radius,
    )


def _circle(geom: SearchGeometry) -> str:
    return f"1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {geom.center_ra_deg:.7f}, {geom.center_dec_deg:.7f}, {geom.radius_deg:.7f}))"


def build_field_query(geom: SearchGeometry, columns: tuple[str, ...] = ref.COLUMN_NAMES) -> str:
    """All gaiadr3.gaia_source rows in the search circle (no magnitude cut: faint neighbours matter), ordered by source_id."""
    if "source_id" not in columns or "ref_epoch" not in columns:
        raise ValueError("source_id and ref_epoch must be selected")
    return f"SELECT {', '.join(columns)} FROM {ref.GAIA_TABLE} WHERE {_circle(geom)} ORDER BY source_id"


def build_count_query(geom: SearchGeometry) -> str:
    """Row count of the same circle: a truncation check independent of the main response."""
    return f"SELECT COUNT(*) AS n_rows FROM {ref.GAIA_TABLE} WHERE {_circle(geom)}"


def tap_sync_fields(query: str, fmt: str = "votable") -> dict[str, str]:
    """Form fields of one TAP sync request (IVOA TAP 1.1: REQUEST/LANG/FORMAT/QUERY, explicit MAXREC)."""
    return {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": fmt, "MAXREC": str(MAXREC), "QUERY": query}


__all__ = ["MAXREC", "SearchGeometry", "build_count_query", "build_field_query", "search_geometry", "tap_sync_fields"]
