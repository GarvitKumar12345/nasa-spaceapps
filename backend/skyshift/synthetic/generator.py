"""Deterministic generator for the synthetic training investigation SYN-NB-01.

Produces original arrays (image, variance, mask), the Dataset contract, a
simulated reference catalog, and the simulation truth (kept separate). Truth
positions use astropy directly (space motion + builtin Earth ephemeris), not
skyshift.science, so recovery tests compare independent implementations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import astropy.units as u
import numpy as np
from astropy.coordinates import BarycentricMeanEcliptic, SkyCoord, get_body_barycentric, solar_system_ephemeris
from astropy.time import Time

from skyshift._astropy_config import SOLAR_SYSTEM_EPHEMERIS
from skyshift.contracts import (
    BackgroundInfo,
    Band,
    CatalogSource,
    Coverage,
    Dataset,
    FieldDescription,
    FrameProduct,
    FrameTruth,
    InstrumentDescription,
    MaskBit,
    Observation,
    ObservationTiming,
    ObserverModel,
    Provenance,
    PSFReference,
    Quality,
    SimulationTruth,
    SkyPosition,
    TruthPosition,
    TruthSource,
    WavelengthInfo,
)
from skyshift.coords.observer import GEOCENTER_BUILTIN
from skyshift.coords.tangent import apply_offsets_mas, offsets_mas
from skyshift.coords.time import add_seconds, epoch_from_isot_utc, epoch_from_jyear
from skyshift.coords.wcs import footprint_icrs, make_tan_wcs, sky_to_pixel, wcs_to_description
from skyshift.imaging.psf import fwhm_to_sigma, render_point_sources
from skyshift.providers.base import DatasetBundle, FrameArrays
from skyshift.synthetic.scenario import Scenario, scenario_parameters
from skyshift.versions import software_versions

GENERATOR = "skyshift.synthetic.generator"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261114

MASK_HOT, MASK_CR, MASK_SAT, MASK_NOCOV = 1, 2, 4, 8
MASK_BITS = [
    MaskBit(bit=MASK_HOT, name="HOT_PIXEL", description="Detector hot pixel (fixed position, flagged by the simulated pipeline)."),
    MaskBit(bit=MASK_CR, name="COSMIC_RAY", description="Cosmic-ray hit flagged by the simulated pipeline."),
    MaskBit(bit=MASK_SAT, name="SATURATED", description="Pixel at or above full well (value clipped)."),
    MaskBit(bit=MASK_NOCOV, name="NO_COVERAGE", description="No input coverage (registered products only)."),
]

SYNTHETIC_OBSERVER = ObserverModel(
    kind="geocenter",
    ephemeris=GEOCENTER_BUILTIN.ephemeris,
    approximation_note=(
        "Synthetic declaration: the generic imager observes from the geocentre exactly, and the same observer is used "
        "for truth and fit, so no observer-approximation error exists in this dataset. A real low-Earth-orbit "
        "spacecraft differs by its orbit radius (see coords.observer.geocenter_suitability)."
    ),
    max_position_error_km=GEOCENTER_BUILTIN.max_position_error_km,
)

LIMITATIONS = [
    "Simulated data: every pixel, star, and catalog value is generated; no real sky is shown.",
    "Toy instrument (0.40\"/px, Gaussian PSF, Poisson + read noise, constant sky): not a SPHEREx sensitivity, PSF, or wavelength model.",
    "The PSF used for fitting is the exact rendering model; real PSFs differ and add model error.",
    "Geometric directions only: aberration, light deflection, and light-time are not simulated.",
    "Variance plane is estimated from the noisy data (read noise^2 + max(image, 0)), as a pipeline would.",
    "Background stars are exactly stationary in the truth; the simulated catalog adds Gaia-like noise (incl. negative parallaxes).",
    "One scheduled visit has no G1 frame, one no G2 frame, and one visit failed in both bands; these stay missing.",
]


@dataclass
class _TruthStar:
    truth_id: str
    kind: str
    ra: float
    dec: float
    flux: dict[str, float]
    parallax: float = 0.0
    pmra: float = 0.0
    pmdec: float = 0.0
    rv: float = 0.0
    variability: dict[str, float] | None = None


def _rng(seed: int, *key: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed, *key]))


def _moving_coord(star: _TruthStar, scenario: Scenario) -> SkyCoord:
    return SkyCoord(
        ra=star.ra * u.deg,
        dec=star.dec * u.deg,
        distance=(1000.0 / star.parallax) * u.pc,
        pm_ra_cosdec=star.pmra * u.mas / u.yr,
        pm_dec=star.pmdec * u.mas / u.yr,
        radial_velocity=star.rv * u.km / u.s,
        obstime=Time(scenario.truth_epoch_jyear_tdb, format="jyear", scale="tdb"),
        frame="icrs",
    )


def _apparent_geocentric(star: _TruthStar, scenario: Scenario, mjd_tdb: float) -> tuple[float, float]:
    """Geometric geocentric direction of a moving truth star at an epoch (independent of skyshift.science)."""
    t = Time(mjd_tdb, format="mjd", scale="tdb")
    moved = _moving_coord(star, scenario).apply_space_motion(new_obstime=t)
    with solar_system_ephemeris.set(SOLAR_SYSTEM_EPHEMERIS):
        earth = get_body_barycentric("earth", t)
    vec = moved.cartesian.xyz.to_value(u.au) - earth.xyz.to_value(u.au)
    ra = math.degrees(math.atan2(vec[1], vec[0])) % 360.0
    dec = math.degrees(math.atan2(vec[2], math.hypot(vec[0], vec[1])))
    return ra, dec


def _flux_at(star: _TruthStar, band: str, mjd_tdb: float) -> float:
    base = star.flux[band]
    v = star.variability
    if not v:
        return base
    phase = (mjd_tdb - v["phase_mjd_tdb"]) / v["period_days"] + v["phase"]
    return base * (1.0 + v["amplitude"] * math.sin(2.0 * math.pi * phase))


def _truth_stars(scenario: Scenario, seed: int) -> list[_TruthStar]:
    rng = _rng(seed, 1)
    ra0, dec0 = scenario.center_ra_deg, scenario.center_dec_deg
    half = scenario.box_arcsec / 2.0
    stars: list[_TruthStar] = []
    east = rng.uniform(-half, half, scenario.n_background) * 1000.0
    north = rng.uniform(-half, half, scenario.n_background) * 1000.0
    g1 = np.minimum(scenario.flux_min_e * rng.uniform(0.0, 1.0, scenario.n_background) ** (-1.0 / scenario.flux_index), scenario.flux_cap_e)
    lo, hi = scenario.color_ratio_range
    ratio = np.exp(rng.uniform(math.log(lo), math.log(hi), scenario.n_background))
    ras, decs = apply_offsets_mas(east, north, ra0, dec0)
    for i in range(scenario.n_background):
        stars.append(_TruthStar(f"truth:star:{i + 1:03d}", "stationary_star", float(ras[i]), float(decs[i]), {"G1": float(g1[i]), "G2": float(g1[i] * ratio[i])}))
    p = scenario.pair
    pa = math.radians(p.position_angle_deg)
    for k, (de, dn) in enumerate([(0.0, 0.0), (p.separation_arcsec * math.sin(pa), p.separation_arcsec * math.cos(pa))]):
        ra, dec = apply_offsets_mas((p.east_arcsec + de) * 1000.0, (p.north_arcsec + dn) * 1000.0, ra0, dec0)
        f = p.flux_g1[k]
        stars.append(_TruthStar(f"truth:pair:{'ab'[k]}", "stationary_star", float(ra), float(dec), {"G1": f, "G2": f * 1.1}))
    c = scenario.candidate
    ra, dec = apply_offsets_mas(c.east_arcsec * 1000.0, c.north_arcsec * 1000.0, ra0, dec0)
    stars.append(_TruthStar(f"truth:{c.id}", "moving_nearby_source", float(ra), float(dec), dict(c.flux), c.parallax_mas, c.pmra_mas_yr, c.pmdec_mas_yr, c.radial_velocity_km_s))
    v = scenario.variable
    ra, dec = apply_offsets_mas(v.east_arcsec * 1000.0, v.north_arcsec * 1000.0, ra0, dec0)
    stars.append(
        _TruthStar(f"truth:{v.id}", "variable_star", float(ra), float(dec), dict(v.flux_mean),
                   variability={"amplitude": v.amplitude, "period_days": v.period_days, "phase": v.phase, "phase_mjd_tdb": v.phase_mjd_tdb})
    )
    return stars


def _err_scale(flux: float, lo: float, hi: float, scenario: Scenario) -> float:
    frac = math.log(scenario.flux_cap_e / flux) / math.log(scenario.flux_cap_e / scenario.catalog_limit_g1_e)
    frac = min(max(frac, 0.0), 1.0)
    return lo * (hi / lo) ** frac


def _simulated_catalog(stars: list[_TruthStar], scenario: Scenario, seed: int) -> list[CatalogSource]:
    rng = _rng(seed, 2)
    epoch = epoch_from_jyear(scenario.catalog_epoch_jyear_tcb, "tcb")
    out: list[CatalogSource] = []
    prov = Provenance(origin="simulated", provider="synthetic", dataset_id=scenario.dataset_id, release=scenario.catalog_release,
                      method=f"{GENERATOR}._simulated_catalog", method_version=GENERATOR_VERSION,
                      notes=["Simulated Gaia-like catalog values: truth propagated to J2016.0 plus Gaussian noise. Not Gaia data."])
    n = 0
    for s in stars:
        if s.kind == "stationary_star" and s.flux["G1"] < scenario.catalog_limit_g1_e:
            continue
        n += 1
        if s.kind == "moving_nearby_source":
            t = Time(scenario.catalog_epoch_jyear_tcb, format="jyear", scale="tcb")
            moved = _moving_coord(s, scenario).apply_space_motion(new_obstime=t)
            ra_t, dec_t = float(moved.ra.deg), float(moved.dec.deg)
            s_pos, s_plx, s_pm = 0.3, 0.4, 0.4
        else:
            ra_t, dec_t = s.ra, s.dec
            s_pos = _err_scale(s.flux["G1"], 0.05, 1.0, scenario)
            s_plx = _err_scale(s.flux["G1"], 0.06, 1.2, scenario)
            s_pm = _err_scale(s.flux["G1"], 0.05, 1.2, scenario)
        two_param = s.kind == "variable_star"
        if two_param:
            s_pos = 1.5
        de, dn = rng.normal(0.0, s_pos, 2)
        ra_c, dec_c = apply_offsets_mas(de, dn, ra_t, dec_t)
        mag = -2.5 * math.log10(s.flux["G1"] / 1.0e5) + 15.0
        common = dict(
            id=f"simcat:{n:04d}",
            catalog=scenario.catalog_name,
            catalog_release=scenario.catalog_release,
            origin="simulated",
            reference_epoch=epoch,
            ra_deg=float(ra_c),
            dec_deg=float(dec_c),
            ra_error_mas=s_pos,
            dec_error_mas=s_pos,
            quality_indicators={"ruwe": float(round(rng.normal(1.0, 0.05), 3))},
            photometry={"sim_mag_g1": round(mag, 3)},
            uncertainty_status="catalog_reported",
            provenance=prov,
            quality=Quality(status="ok"),
        )
        if two_param:
            out.append(CatalogSource(**common, astrometric_solution="2-parameter", astrometric_params_solved=3))
        else:
            out.append(
                CatalogSource(
                    **common,
                    parallax_mas=float(s.parallax + rng.normal(0.0, s_plx)),
                    parallax_error_mas=s_plx,
                    pmra_mas_yr=float(s.pmra + rng.normal(0.0, s_pm)),
                    pmra_error_mas_yr=s_pm,
                    pmdec_mas_yr=float(s.pmdec + rng.normal(0.0, s_pm)),
                    pmdec_error_mas_yr=s_pm,
                    astrometric_solution="5-parameter",
                    astrometric_params_solved=31,
                )
            )
    return out


def generate(scenario: Scenario, seed: int = DEFAULT_SEED) -> DatasetBundle:
    """Generate the full synthetic dataset deterministically from `seed`."""
    ds = scenario.dataset_id
    ra0, dec0 = scenario.center_ra_deg, scenario.center_dec_deg
    stars = _truth_stars(scenario, seed)
    catalog = _simulated_catalog(stars, scenario, seed)
    in_catalog = {s.truth_id for s in stars if s.kind != "stationary_star" or s.flux["G1"] >= scenario.catalog_limit_g1_e}
    shape = scenario.detector_shape
    ny, nx = shape
    rng_hot = _rng(seed, 3)
    hot_y = rng_hot.integers(4, ny - 4, scenario.n_hot_pixels)
    hot_x = rng_hot.integers(4, nx - 4, scenario.n_hot_pixels)
    prov_common = dict(provider="synthetic", dataset_id=ds, release=scenario.release, method=f"{GENERATOR}.generate", method_version=GENERATOR_VERSION)
    software = software_versions()

    bands = [
        Band(id=b.id, label=b.label, center_um=b.center_um, width_um=b.width_um, wavelength_model="fixed_filter",
             notes=["Synthetic fixed filter; wavelength does not depend on detector position (unlike SPHEREx)."])
        for b in scenario.bands
    ]
    psf_by_band = {
        b.id: PSFReference(model="gaussian_pixel_integrated", fwhm_arcsec=b.fwhm_arcsec, includes_pixel_response=True,
                           source="declared synthetic instrument (circular Gaussian integrated over each pixel)")
        for b in scenario.bands
    }

    observations: list[Observation] = []
    frames: list[FrameProduct] = []
    arrays: dict[str, FrameArrays] = {}
    frame_truths: list[FrameTruth] = []
    positions: list[TruthPosition] = []
    frame_index = 0
    for visit in scenario.visits:
        g1_start = epoch_from_isot_utc(visit.start_utc)
        for band in scenario.bands:
            status, reason = visit.status[band.id]
            start = g1_start if band.id == "G1" else add_seconds(g1_start, scenario.g2_offset_s)
            mid = add_seconds(start, scenario.exposure_s / 2.0)
            obs_id = f"{ds}:{visit.id}:{band.id}"
            timing = ObservationTiming(
                start=start,
                mid=mid,
                exposure_s=scenario.exposure_s,
                mid_derivation="start + exposure/2 (synthetic schedule; times are UTC, converted to TDB with astropy)",
                raw={"DATE-OBS": str(start.value), "TIMESYS": "UTC", "EXPTIME": scenario.exposure_s},
            )
            native_id = f"{obs_id}:native"
            quality = Quality(status="ok") if status == "available" else Quality(status="unavailable", flags=[status.upper()], messages=[reason or ""])
            frame_ids: list[str] = []
            if status == "available":
                frame_index += 1
                rng = _rng(seed, 100 + frame_index)
                dx, dy = rng.uniform(-scenario.pointing_offset_px, scenario.pointing_offset_px, 2)
                rot = float(rng.uniform(-scenario.rotation_deg, scenario.rotation_deg))
                crpix0 = ((nx - 1) / 2.0 + dx, (ny - 1) / 2.0 + dy)
                true_wcs = make_tan_wcs(ra0, dec0, scenario.pixel_scale_arcsec, shape, rotation_deg=rot, crpix0=crpix0)
                he, hn = rng.normal(0.0, scenario.header_error_arcsec, 2)
                hrot = float(rng.normal(0.0, scenario.header_rotation_error_deg))
                hra, hdec = apply_offsets_mas(he * 1000.0, hn * 1000.0, ra0, dec0)
                nominal = make_tan_wcs(float(hra), float(hdec), scenario.pixel_scale_arcsec, shape, rotation_deg=rot + hrot, crpix0=crpix0)

                xs, ys, fl = [], [], []
                for s in stars:
                    if s.kind == "moving_nearby_source":
                        ra, dec = _apparent_geocentric(s, scenario, mid.mjd_tdb)
                    else:
                        ra, dec = s.ra, s.dec
                    flux = _flux_at(s, band.id, mid.mjd_tdb)
                    px, py = sky_to_pixel(true_wcs, ra, dec)
                    xs.append(float(px))
                    ys.append(float(py))
                    fl.append(flux)
                    if s.kind != "stationary_star":
                        positions.append(TruthPosition(frame_id=native_id, truth_id=s.truth_id, x_px=float(px), y_px=float(py), ra_deg=ra, dec_deg=dec, flux=flux))
                sigma = fwhm_to_sigma(band.fwhm_arcsec / scenario.pixel_scale_arcsec)
                expected = band.sky_e + render_point_sources(shape, np.array(xs), np.array(ys), np.array(fl), sigma)
                image = rng.poisson(expected).astype(float) + rng.normal(0.0, scenario.read_noise_e, shape)
                mask = np.zeros(shape, dtype=np.uint16)
                image[hot_y, hot_x] += rng.uniform(*scenario.hot_pixel_excess_e, scenario.n_hot_pixels)
                mask[hot_y, hot_x] |= MASK_HOT
                for _ in range(int(rng.poisson(scenario.cosmic_ray_rate))):
                    cy, cx = int(rng.integers(0, ny)), int(rng.integers(0, nx))
                    step = [(0, 1), (1, 0), (1, 1), (1, -1)][int(rng.integers(0, 4))]
                    for k in range(int(rng.integers(1, 4))):
                        yy, xx = cy + k * step[0], cx + k * step[1]
                        if 0 <= yy < ny and 0 <= xx < nx:
                            image[yy, xx] += rng.uniform(*scenario.cosmic_ray_e)
                            mask[yy, xx] |= MASK_CR
                sat = image >= scenario.full_well_e
                image[sat] = scenario.full_well_e
                mask[sat] |= MASK_SAT
                image32 = image.astype(np.float32)
                variance = (scenario.read_noise_e**2 + np.maximum(image32, 0.0)).astype(np.float32)
                arrays[native_id] = FrameArrays(image=image32, variance=variance, mask=mask)
                frame_ids = [native_id]
                frames.append(
                    FrameProduct(
                        id=native_id,
                        observation_id=obs_id,
                        dataset_id=ds,
                        kind="native",
                        shape=shape,
                        unit="electron",
                        unit_kind="counts",
                        variance_unit="electron2",
                        planes=["image", "variance", "mask"],
                        mask_bits=MASK_BITS,
                        wcs=wcs_to_description(nominal, shape, "native_header"),
                        coverage=Coverage(valid_fraction=float(np.mean(mask == 0)), nan_marks_no_coverage=False, footprint_icrs=footprint_icrs(nominal, shape)),
                        band_id=band.id,
                        wavelength=WavelengthInfo(band_id=band.id, center_um=band.center_um, width_um=band.width_um, determination="band_definition", position_dependent=False,
                                                  notes=["Fixed synthetic filter: the same wavelength applies at every pixel."]),
                        psf=psf_by_band[band.id],
                        background=BackgroundInfo(included_in_image=True, model_available=False, model_kind="constant sky (simulated)", subtracted_by_skyshift=False,
                                                  notes=["Sky is included in the image; PSF fitting fits a local constant background (no separate subtraction)."]),
                        display_only=False,
                        provenance=Provenance(origin="simulated", **prov_common, software=software,
                                              notes=[f"seed {seed}; frame noise stream {frame_index}; header WCS deliberately perturbed (simulation truth kept separately)"]),
                        quality=Quality(status="ok", messages=[f"{int(np.sum((mask & MASK_HOT) != 0))} hot pixels and {int(np.sum((mask & MASK_CR) != 0))} cosmic-ray pixels flagged."]),
                    )
                )
                frame_truths.append(
                    FrameTruth(frame_id=native_id, true_wcs=wcs_to_description(true_wcs, shape, "simulation_truth"), pointing_offset_px=(float(dx), float(dy)),
                               rotation_deg=rot, header_error_arcsec=(float(he), float(hn)), header_rotation_error_deg=hrot)
                )
            observations.append(
                Observation(
                    id=obs_id,
                    dataset_id=ds,
                    provider="synthetic",
                    instrument="SkyShift generic training imager (GTI-1)",
                    detector="GTI-1 detector (synthetic)",
                    band_id=band.id,
                    status=status,  # type: ignore[arg-type]
                    status_reason=reason,
                    timing=timing,
                    pointing=SkyPosition(ra_deg=ra0, dec_deg=dec0),
                    observer=SYNTHETIC_OBSERVER,
                    frame_ids=frame_ids,
                    provenance=Provenance(origin="simulated", **prov_common),
                    quality=quality,
                )
            )

    ecl = SkyCoord(ra=ra0 * u.deg, dec=dec0 * u.deg, frame="icrs").transform_to(BarycentricMeanEcliptic())
    common_grid = make_tan_wcs(ra0, dec0, scenario.pixel_scale_arcsec, scenario.grid_shape)
    ref_frame = f"{ds}:{scenario.reference_visit}:{scenario.reference_band}:native"
    dataset = Dataset(
        id=ds,
        title=scenario.title,
        provider="synthetic",
        origin="simulated",
        release=scenario.release,
        description=(
            "Deterministic synthetic training field: stationary background stars, one nearby source with proper motion "
            "and annual parallax, one variable star, and a close pair, observed at irregular epochs in two synthetic bands."
        ),
        field=FieldDescription(center=SkyPosition(ra_deg=ra0, dec_deg=dec0), fov_arcsec=scenario.grid_shape[1] * scenario.pixel_scale_arcsec,
                               ecliptic_lat_deg=float(ecl.lat.deg)),
        instrument=InstrumentDescription(
            name="SkyShift generic training imager (GTI-1)",
            kind="generic_synthetic",
            pixel_scale_arcsec=scenario.pixel_scale_arcsec,
            detector_shape=shape,
            gain_e_per_adu=scenario.gain_e_per_adu,
            read_noise_e=scenario.read_noise_e,
            full_well_e=scenario.full_well_e,
            psf_by_band=psf_by_band,
            notes=list(scenario.notes),
        ),
        bands=bands,
        observations=observations,
        frames=frames,
        common_grid=wcs_to_description(common_grid, scenario.grid_shape, "common_grid"),
        reference_frame_ids={b.id: ref_frame for b in scenario.bands},
        seed=seed,
        generator=GENERATOR,
        generator_version=GENERATOR_VERSION,
        scenario_parameters=scenario_parameters(scenario),
        limitations=LIMITATIONS,
        provenance=Provenance(origin="simulated", **prov_common, software=software, notes=[f"seed {seed}"]),
        quality=Quality(status="ok"),
    )
    truth = SimulationTruth(
        dataset_id=ds,
        seed=seed,
        generator=GENERATOR,
        generator_version=GENERATOR_VERSION,
        scenario_parameters=scenario_parameters(scenario),
        sources=[
            TruthSource(
                truth_id=s.truth_id,
                kind=s.kind,  # type: ignore[arg-type]
                ra_deg=s.ra,
                dec_deg=s.dec,
                reference_epoch=epoch_from_jyear(scenario.truth_epoch_jyear_tdb, "tdb"),
                parallax_mas=s.parallax,
                pmra_mas_yr=s.pmra,
                pmdec_mas_yr=s.pmdec,
                radial_velocity_km_s=s.rv,
                flux_by_band=s.flux,
                variability=s.variability,
                in_simulated_catalog=s.truth_id in in_catalog,
            )
            for s in stars
        ],
        frames=frame_truths,
        positions=positions,
    )
    return DatasetBundle(dataset=dataset, arrays=arrays, catalog=catalog, catalog_name=scenario.catalog_name, truth=truth)


def truth_offsets_mas(truth: SimulationTruth, truth_id: str, ra0: float, dec0: float) -> list[tuple[str, float, float]]:
    """(frame_id, east_mas, north_mas) of a truth source about (ra0, dec0) — validation helper only."""
    out = []
    for p in truth.positions:
        if p.truth_id == truth_id:
            e, n = offsets_mas(p.ra_deg, p.dec_deg, ra0, dec0)
            out.append((p.frame_id, float(e), float(n)))
    return out

