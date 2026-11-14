"""Astrometric model and fit checks (independent methods, Monte-Carlo calibration)."""

from __future__ import annotations

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from astropy.time import Time

from skyshift.contracts import FitRequest, Provenance, Quality, SourceMeasurement
from skyshift.coords.observer import CIRCULAR_1AU, GEOCENTER_BUILTIN, observer_barycentric_au
from skyshift.coords.tangent import apply_offsets_mas, offsets_mas
from skyshift.coords.time import epoch_from_isot_utc, epoch_from_mjd_tdb, jyear_to_mjd_tdb
from skyshift.science.astrometry import fit_astrometry, linear_offsets, parallax_factors, rigorous_offsets

pytestmark = pytest.mark.math

RA0, DEC0 = 180.0017, 34.9989
REF = float(jyear_to_mjd_tdb(2026.0))
SEASONAL = [
    "2025-01-08T03:11:30", "2025-03-19T22:41:30", "2025-05-27T20:06:30", "2025-12-16T05:21:30", "2026-02-03T01:46:30",
    "2026-04-22T21:16:30", "2026-06-30T19:01:30", "2026-12-09T04:36:30", "2027-05-14T20:26:30",
]


def _measurements(isos_or_mjd, east, north, sigma, ra0=RA0, dec0=DEC0, corr=0.0):
    out = []
    for i, t in enumerate(isos_or_mjd):
        ep = epoch_from_isot_utc(t) if isinstance(t, str) else epoch_from_mjd_tdb(float(t))
        ra, dec = apply_offsets_mas(east[i], north[i], ra0, dec0)
        out.append(SourceMeasurement(
            id=f"m{i:02d}", source_id="S1", dataset_id="d", frame_id=f"f{i}", observation_id=f"o{i}", band_id="G1", epoch=ep,
            method="psf_gaussian_fit", method_version="test", status="measured", ra_deg=float(ra), dec_deg=float(dec),
            sigma_ra_cosdec_mas=sigma, sigma_dec_mas=sigma, corr_ra_dec=corr, uncertainty_status="estimated",
            quality=Quality(status="ok"), provenance=Provenance(origin="derived_measurement", provider="skyshift"),
        ))
    return out


def _truth_track(mjd, plx=165.0, pmra=640.0, pmdec=-1110.0):
    return rigorous_offsets(RA0, DEC0, plx, pmra, pmdec, 0.0, REF, mjd, observer_barycentric_au(mjd), RA0, DEC0)


def _mjd(isos):
    return np.array([epoch_from_isot_utc(t).mjd_tdb for t in isos])


def test_zero_motion_limits():
    """Zero proper motion and parallax give zero offsets in both the linear and rigorous (vector) models."""
    mjd = _mjd(SEASONAL)
    f_ra, f_dec = parallax_factors(RA0, DEC0, observer_barycentric_au(mjd))
    e, n = linear_offsets([0, 0, 0, 0, 0], (mjd - REF) / 365.25, f_ra, f_dec, "proper_motion_parallax")
    assert np.all(e == 0) and np.all(n == 0)
    # Rigorous model needs a finite distance; ERFA overrides parallaxes below ~0.5 microarcsec,
    # so use 1 microarcsec (1 Gpc-like) and expect displacements at that level only.
    e, n = rigorous_offsets(RA0, DEC0, 1e-3, 0.0, 0.0, 0.0, REF, mjd, observer_barycentric_au(mjd))
    assert np.max(np.abs(e)) < 1.1e-3 and np.max(np.abs(n)) < 1.1e-3


@pytest.mark.parametrize("dec", [60.0, 85.0])
def test_ra_cosine_convention_matches_astropy(dec):
    """pmra = dRA/dt cos(Dec): the coordinate-RA rate is pmra/cos(Dec), as in astropy apply_space_motion."""
    c = SkyCoord(ra=10 * u.deg, dec=dec * u.deg, distance=100 * u.pc, pm_ra_cosdec=100 * u.mas / u.yr, pm_dec=0 * u.mas / u.yr,
                 radial_velocity=0 * u.km / u.s, obstime=Time(2026.0, format="jyear", scale="tdb"))
    c1 = c.apply_space_motion(new_obstime=Time(2027.0, format="jyear", scale="tdb"))
    dra_coord_mas = (c1.ra - c.ra).to_value(u.mas)
    assert dra_coord_mas == pytest.approx(100.0 / np.cos(np.radians(dec)), rel=1e-4)
    east, _ = rigorous_offsets(10.0, dec, 10.0, 100.0, 0.0, 0.0, REF, np.array([REF + 365.25]), np.zeros((1, 3)))
    assert float(east[0]) == pytest.approx(100.0, rel=1e-6)  # tangent-plane east offset is pmra * dt


def test_linear_model_agrees_with_rigorous_vector_geometry():
    """Linear parallax-factor model vs independent vector propagation (6 pc, 1.28"/yr, 3 yr): agreement < 0.05 mas."""
    mjd = jyear_to_mjd_tdb(np.linspace(2024.5, 2027.5, 60))
    e_r, n_r = _truth_track(mjd)
    f_ra, f_dec = parallax_factors(RA0, DEC0, observer_barycentric_au(mjd))
    e_l, n_l = linear_offsets([0, 0, 640.0, -1110.0, 165.0], (mjd - REF) / 365.25, f_ra, f_dec, "proper_motion_parallax")
    assert np.max(np.hypot(e_r - e_l, n_r - n_l)) < 0.05


def test_parallax_ellipse_geometry_with_circular_observer():
    """Circular 1 AU observer: an ecliptic-pole source traces a circle of radius = parallax; an ecliptic-plane source a line."""
    mjd = jyear_to_mjd_tdb(np.linspace(2025.0, 2026.0, 400))
    obs = observer_barycentric_au(mjd, CIRCULAR_1AU)
    pole = SkyCoord(lon=0 * u.deg, lat=90 * u.deg, frame="barycentricmeanecliptic").icrs
    fr, fd = parallax_factors(pole.ra.deg, pole.dec.deg, obs)
    r = 100.0 * np.hypot(fr, fd)
    assert np.allclose(r, 100.0, rtol=2e-3)
    plane = SkyCoord(lon=40 * u.deg, lat=0 * u.deg, frame="barycentricmeanecliptic")
    fr, fd = parallax_factors(plane.icrs.ra.deg, plane.icrs.dec.deg, obs)
    lat_dir = SkyCoord(lon=40 * u.deg, lat=0.01 * u.deg, frame="barycentricmeanecliptic").icrs
    e_dir, n_dir = offsets_mas(lat_dir.ra.deg, lat_dir.dec.deg, plane.icrs.ra.deg, plane.icrs.dec.deg)
    unit = np.array([float(e_dir), float(n_dir)]) / np.hypot(float(e_dir), float(n_dir))
    along_latitude = 100.0 * (fr * unit[0] + fd * unit[1])
    assert np.max(np.abs(along_latitude)) < 0.5  # ~0 for an ecliptic source (obliquity rounding only)
    assert 100.0 * np.max(np.hypot(fr, fd)) == pytest.approx(100.0, rel=2e-3)


def test_parallax_amplitude_scales_as_inverse_distance():
    """Doubling the distance halves the parallactic excursion (vector method, no proper motion)."""
    mjd = jyear_to_mjd_tdb(np.linspace(2025.0, 2026.0, 100))
    obs = observer_barycentric_au(mjd)
    e1, n1 = rigorous_offsets(RA0, DEC0, 200.0, 0.0, 0.0, 0.0, REF, mjd, obs)
    e2, n2 = rigorous_offsets(RA0, DEC0, 100.0, 0.0, 0.0, 0.0, REF, mjd, obs)
    assert np.ptp(np.hypot(e1, n1)) > 0
    assert np.ptp(e2) == pytest.approx(0.5 * np.ptp(e1), rel=1e-3)


def test_fit_recovers_injected_motion_from_independent_model():
    """Noisy positions from the rigorous model: fitted pm and parallax within 3 sigma; static/pm-only models rejected."""
    mjd = _mjd(SEASONAL)
    e, n = _truth_track(mjd)
    rng = np.random.default_rng(11)
    ms = _measurements(SEASONAL, e + rng.normal(0, 7, e.size), n + rng.normal(0, 7, n.size), 7.0)
    fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=ms, reference_epoch_mjd_tdb=REF))
    p = {q.name: q for q in fit.parameters}
    for name, truth in (("pmra", 640.0), ("pmdec", -1110.0), ("parallax", 165.0)):
        assert abs(p[name].value - truth) < 3 * p[name].uncertainty, name
    assert fit.identifiability.status == "constrained" and fit.status == "ok"
    chi = {c.model: c.chi2 for c in fit.comparisons}
    assert chi["static"] > chi["proper_motion"] > chi["proper_motion_parallax"]
    assert fit.prediction is not None
    total = np.array(fit.prediction.ra_cosdec_offset_mas)
    parts = np.array(fit.prediction.components["proper_motion"].ra_cosdec_offset_mas) + np.array(fit.prediction.components["parallax"].ra_cosdec_offset_mas)
    np.testing.assert_allclose(parts, total, atol=1e-9)


@pytest.mark.slow
def test_fit_uncertainties_are_calibrated_monte_carlo():
    """Over 200 noise realisations the parameter pulls have std in [0.85, 1.15] and mean chi2 ~ dof."""
    mjd = _mjd(SEASONAL)
    e, n = _truth_track(mjd)
    rng = np.random.default_rng(5)
    pulls, chi2 = [], []
    for _ in range(200):
        ms = _measurements(SEASONAL, e + rng.normal(0, 7, e.size), n + rng.normal(0, 7, n.size), 7.0)
        fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=ms, reference_epoch_mjd_tdb=REF), n_curve=10)
        p = {q.name: q for q in fit.parameters}
        pulls.append([(p["pmra"].value - 640) / p["pmra"].uncertainty, (p["pmdec"].value + 1110) / p["pmdec"].uncertainty, (p["parallax"].value - 165) / p["parallax"].uncertainty])
        chi2.append(fit.chi2)
    pulls = np.array(pulls)
    assert np.all((pulls.std(axis=0) > 0.85) & (pulls.std(axis=0) < 1.15))
    assert np.all(np.abs(pulls.mean(axis=0)) < 0.25)
    assert np.mean(chi2) == pytest.approx(2 * len(SEASONAL) - 5, rel=0.15)


def test_identifiability_insufficient_and_underconstrained_cases():
    """2 epochs -> insufficient data; 3 epochs in 2 months -> parallax not constrained; 1.000-yr spacing -> degenerate."""
    two = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax",
                                    measurements=_measurements(SEASONAL[:2], [0, 1], [0, 1], 5.0)))
    assert two.identifiability.status == "insufficient_data" and two.status == "pending"
    assert all(p.value is None for p in two.parameters)
    short = [60800.0, 60820.0, 60840.0, 60860.0]
    fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=_measurements(short, [0, 1, 2, 3], [0, 1, 2, 3], 5.0)))
    assert fit.identifiability.status == "underconstrained"
    assert {p.name: p.status for p in fit.parameters}["parallax"] == "not_constrained"
    assert next(d for d in fit.derived if d.name == "distance").status == "not_derived"
    yearly = [59700.0 + 365.25 * k for k in range(5)]  # 2022-2026: inside the leap-second table
    fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=_measurements(yearly, [0, 1, 2, 3, 4], [0, 1, 2, 3, 4], 5.0)))
    assert fit.identifiability.status == "underconstrained"


def test_distance_only_from_significant_positive_parallax():
    """Distance is derived only for parallax/sigma >= 10; negative or weak parallax never becomes a distance."""
    mjd = _mjd(SEASONAL)
    for plx, sigma, expected in ((165.0, 7.0, "derived"), (12.0, 7.0, "not_derived")):
        e, n = rigorous_offsets(RA0, DEC0, plx, 50.0, 30.0, 0.0, REF, mjd, observer_barycentric_au(mjd))
        fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=_measurements(SEASONAL, e, n, sigma)))
        assert next(d for d in fit.derived if d.name == "distance").status == expected
    f_ra, f_dec = parallax_factors(RA0, DEC0, observer_barycentric_au(mjd))
    e, n = linear_offsets([0, 0, 50.0, 30.0, -30.0], (mjd - REF) / 365.25, f_ra, f_dec, "proper_motion_parallax")
    fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=_measurements(SEASONAL, e, n, 2.0)))
    d = next(d for d in fit.derived if d.name == "distance")
    assert d.status == "not_derived" and d.value is None and "not positive" in d.reason


def test_exclusions_and_input_hash():
    """Excluded measurements are not fitted but get residuals; any input change changes the hash; repeat fits are identical."""
    mjd = _mjd(SEASONAL)
    e, n = _truth_track(mjd)
    ms = _measurements(SEASONAL, e, n, 7.0)
    base = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=ms))
    again = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=ms))
    excl = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=ms, excluded_measurement_ids=["m03"]))
    moved = [m.model_copy(update={"ra_deg": m.ra_deg + 1e-9}) if m.id == "m05" else m for m in ms]
    shifted = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=moved))
    other_model = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion", measurements=ms))
    assert base.input_hash == again.input_hash
    assert len({base.input_hash, excl.input_hash, shifted.input_hash, other_model.input_hash}) == 4
    assert "m03" not in excl.inputs.measurement_ids and any(r.measurement_id == "m03" and not r.included for r in excl.residuals)


def test_unusable_measurements_are_reported_not_used():
    """Pending or position-less measurements are skipped with a warning, never silently fitted."""
    mjd = _mjd(SEASONAL)
    e, n = _truth_track(mjd)
    ms = _measurements(SEASONAL, e, n, 7.0)
    ms[2] = ms[2].model_copy(update={"status": "pending"})
    fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=ms))
    assert "m02" not in fit.inputs.measurement_ids and any("m02" in w for w in fit.warnings)
    with pytest.raises(ValueError):
        fit_astrometry(FitRequest(dataset_id="other", source_id="S1", model="static", measurements=ms))


def test_geocenter_model_is_used_by_default():
    """The fit records the observer it used (geocentre, builtin ephemeris)."""
    mjd = _mjd(SEASONAL)
    e, n = _truth_track(mjd)
    fit = fit_astrometry(FitRequest(dataset_id="d", source_id="S1", model="proper_motion_parallax", measurements=_measurements(SEASONAL, e, n, 7.0)))
    assert fit.inputs.observer == GEOCENTER_BUILTIN
