"""Declared parameters of the synthetic training investigation SYN-NB-01.

Every number here is a simulation declaration (docs/architecture.md section 3),
not a property of any real instrument or sky field. The toy instrument is not a
SPHEREx sensitivity, PSF, or wavelength model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BandSpec:
    id: str
    label: str
    center_um: float
    width_um: float
    fwhm_arcsec: float
    sky_e: float  # sky background, electrons per pixel per exposure


@dataclass(frozen=True)
class VisitSpec:
    id: str
    start_utc: str  # G1 exposure start; G2 starts g2_offset_s later
    status: dict[str, tuple[str, str | None]]  # band -> (status, reason)


@dataclass(frozen=True)
class MovingSourceSpec:
    id: str
    east_arcsec: float  # offset from field centre at the truth epoch
    north_arcsec: float
    parallax_mas: float
    pmra_mas_yr: float
    pmdec_mas_yr: float
    radial_velocity_km_s: float
    flux: dict[str, float]


@dataclass(frozen=True)
class VariableSourceSpec:
    id: str
    east_arcsec: float
    north_arcsec: float
    flux_mean: dict[str, float]
    amplitude: float  # fractional
    period_days: float
    phase: float  # fraction of period at phase_mjd_tdb
    phase_mjd_tdb: float


@dataclass(frozen=True)
class PairSpec:
    east_arcsec: float
    north_arcsec: float
    separation_arcsec: float
    position_angle_deg: float
    flux_g1: tuple[float, float]


_OK: tuple[str, None] = ("available", None)
_MISSING = ("missing", "Scheduled observation; no frame delivered (simulated).")
_FAILED = ("failed", "Frame failed quality gate: simulated tracking loss.")


@dataclass(frozen=True)
class Scenario:
    dataset_id: str = "syn-nb-01"
    title: str = "Training field 01 — nearby-source motion (synthetic)"
    release: str = "synthetic-v1"
    center_ra_deg: float = 180.0
    center_dec_deg: float = 35.0
    pixel_scale_arcsec: float = 0.40
    detector_shape: tuple[int, int] = (160, 160)
    grid_shape: tuple[int, int] = (176, 176)
    gain_e_per_adu: float = 1.0
    read_noise_e: float = 5.0
    full_well_e: float = 150_000.0
    exposure_s: float = 180.0
    g2_offset_s: float = 240.0
    bands: tuple[BandSpec, ...] = (
        BandSpec("G1", "G1 (synthetic) 1.25 µm", 1.25, 0.30, 1.00, 150.0),
        BandSpec("G2", "G2 (synthetic) 2.15 µm", 2.15, 0.40, 1.40, 260.0),
    )
    visits: tuple[VisitSpec, ...] = (
        VisitSpec("v01", "2025-01-08T03:10:00", {"G1": _OK, "G2": _OK}),
        VisitSpec("v02", "2025-03-19T22:40:00", {"G1": _OK, "G2": _OK}),
        VisitSpec("v03", "2025-05-27T20:05:00", {"G1": _OK, "G2": _OK}),
        VisitSpec("v04", "2025-07-10T18:30:00", {"G1": _MISSING, "G2": _OK}),
        VisitSpec("v05", "2025-12-16T05:20:00", {"G1": _OK, "G2": _OK}),
        VisitSpec("v06", "2026-02-03T01:45:00", {"G1": _OK, "G2": _MISSING}),
        VisitSpec("v07", "2026-04-22T21:15:00", {"G1": _OK, "G2": _OK}),
        VisitSpec("v08", "2026-06-30T19:00:00", {"G1": _OK, "G2": _OK}),
        VisitSpec("v09", "2026-12-09T04:35:00", {"G1": _OK, "G2": _OK}),
        VisitSpec("v10", "2027-03-02T23:50:00", {"G1": _FAILED, "G2": _FAILED}),
        VisitSpec("v11", "2027-05-14T20:25:00", {"G1": _OK, "G2": _OK}),
    )
    reference_visit: str = "v01"
    reference_band: str = "G1"
    truth_epoch_jyear_tdb: float = 2026.0
    catalog_epoch_jyear_tcb: float = 2016.0
    n_background: int = 64
    box_arcsec: float = 78.0
    flux_min_e: float = 400.0
    flux_index: float = 1.1
    flux_cap_e: float = 120_000.0
    color_ratio_range: tuple[float, float] = (0.7, 1.6)
    pair: PairSpec = PairSpec(-18.0, -14.0, 1.10, 60.0, (6000.0, 4000.0))
    candidate: MovingSourceSpec = MovingSourceSpec("C1", 6.0, -4.0, 165.0, 640.0, -1110.0, 0.0, {"G1": 9000.0, "G2": 26000.0})
    variable: VariableSourceSpec = VariableSourceSpec("V1", -12.0, 9.0, {"G1": 15000.0, "G2": 18000.0}, 0.30, 23.7, 0.2, 60676.0)
    pointing_offset_px: float = 5.0  # uniform half-range per axis
    rotation_deg: float = 0.3  # uniform half-range
    header_error_arcsec: float = 0.6  # Gaussian sigma per axis
    header_rotation_error_deg: float = 0.03  # Gaussian sigma
    n_hot_pixels: int = 12
    hot_pixel_excess_e: tuple[float, float] = (3000.0, 8000.0)
    cosmic_ray_rate: float = 2.0
    cosmic_ray_e: tuple[float, float] = (2000.0, 20000.0)
    catalog_limit_g1_e: float = 900.0
    catalog_name: str = "SkyShift simulated reference catalog (Gaia-like format)"
    catalog_release: str = "simcat-v1"
    notes: tuple[str, ...] = field(
        default=(
            "Toy instrument: pixel scale, PSF, noise, and bands are illustrative; not a SPHEREx sensitivity, PSF, or wavelength model.",
            "Geometric directions: no aberration, light deflection, or light-time.",
        )
    )

    def band(self, band_id: str) -> BandSpec:
        for b in self.bands:
            if b.id == band_id:
                return b
        raise KeyError(band_id)


def default_scenario() -> Scenario:
    return Scenario()


def scenario_parameters(scenario: Scenario) -> dict[str, Any]:
    """JSON-safe dictionary of the scenario (tuples become lists)."""

    def clean(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k): clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        return v

    return clean(asdict(scenario))
