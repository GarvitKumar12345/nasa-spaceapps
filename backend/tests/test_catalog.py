"""Catalog epoch propagation and cross-matching checks."""

from __future__ import annotations

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from astropy.time import Time

from skyshift.contracts import CatalogSource, Provenance, Quality
from skyshift.coords.observer import SOLAR_SYSTEM_BARYCENTER, observer_barycentric_au
from skyshift.coords.tangent import apply_offsets_mas, offsets_mas
from skyshift.coords.time import epoch_from_isot_utc, epoch_from_jyear
from skyshift.science.astrometry import parallax_factors
from skyshift.science.catalog import ImagePoint, associate, padded_search_radius_deg, propagate_catalog_source

pytestmark = pytest.mark.catalog

J2016 = epoch_from_jyear(2016.0, "tcb")
OBS = epoch_from_isot_utc("2026-04-22T21:16:30")


def _src(sid, ra, dec, plx=None, pmra=None, pmdec=None, sig=0.3, corr=None, solution="5-parameter", rv=None):
    full = plx is not None
    return CatalogSource(
        id=sid, catalog="test", catalog_release="t", origin="simulated", reference_epoch=J2016, ra_deg=ra, dec_deg=dec,
        ra_error_mas=sig, dec_error_mas=sig, parallax_mas=plx, parallax_error_mas=0.4 if full else None,
        pmra_mas_yr=pmra, pmra_error_mas_yr=0.4 if full else None, pmdec_mas_yr=pmdec, pmdec_error_mas_yr=0.4 if full else None,
        correlations=corr or {}, radial_velocity_km_s=rv, astrometric_solution=solution if full else "2-parameter",
        uncertainty_status="catalog_reported", provenance=Provenance(origin="simulated", provider="synthetic"), quality=Quality(status="ok"),
    )


def test_space_motion_propagation_matches_astropy():
    """Space-motion part (no observer parallax) equals astropy apply_space_motion to < 0.1 mas over ~10 yr."""
    s = _src("a", 180.0, 35.0, plx=165.0, pmra=640.0, pmdec=-1110.0)
    p = propagate_catalog_source(s, OBS, observer=SOLAR_SYSTEM_BARYCENTER, include_parallax=False)
    c = SkyCoord(ra=180 * u.deg, dec=35 * u.deg, distance=(1000 / 165) * u.pc, pm_ra_cosdec=640 * u.mas / u.yr, pm_dec=-1110 * u.mas / u.yr,
                 radial_velocity=0 * u.km / u.s, obstime=Time(J2016.mjd_tdb, format="mjd", scale="tdb"))
    m = c.apply_space_motion(new_obstime=Time(OBS.mjd_tdb, format="mjd", scale="tdb"))
    e, n = offsets_mas(p.ra_deg, p.dec_deg, m.ra.deg, m.dec.deg)
    assert np.hypot(float(e), float(n)) < 0.1
    assert p.includes_space_motion and not p.includes_observer_parallax


def test_observer_parallax_added_separately():
    """The observer-parallax term equals parallax x parallax factors at the observation epoch."""
    s = _src("a", 180.0, 35.0, plx=165.0, pmra=0.0, pmdec=0.0)
    without = propagate_catalog_source(s, OBS, include_parallax=False)
    with_plx = propagate_catalog_source(s, OBS, include_parallax=True)
    e, n = offsets_mas(with_plx.ra_deg, with_plx.dec_deg, without.ra_deg, without.dec_deg)
    fr, fd = parallax_factors(180.0, 35.0, observer_barycentric_au(np.array([OBS.mjd_tdb])))
    assert float(e) == pytest.approx(165.0 * fr[0], abs=1e-3) and float(n) == pytest.approx(165.0 * fd[0], abs=1e-3)


def test_covariance_propagation_matches_monte_carlo_with_correlation():
    """Propagated sigma (incl. ra_pmra_corr = 0.6) matches Monte-Carlo sampling of the catalog covariance to 5%."""
    s = _src("a", 10.0, -5.0, plx=10.0, pmra=5.0, pmdec=-3.0, sig=0.5, corr={"ra_pmra_corr": 0.6})
    p = propagate_catalog_source(s, OBS, include_parallax=True)
    rng = np.random.default_rng(2)
    cov = np.diag([0.5, 0.5, 0.4, 0.4, 0.4]) ** 2
    cov[0, 3] = cov[3, 0] = 0.6 * 0.5 * 0.4
    draws = rng.multivariate_normal(np.zeros(5), cov, 20000)
    dt = (OBS.mjd_tdb - J2016.mjd_tdb) / 365.25
    fr, fd = parallax_factors(10.0, -5.0, observer_barycentric_au(np.array([OBS.mjd_tdb])))
    east = draws[:, 0] + draws[:, 2] * fr[0] + draws[:, 3] * dt
    north = draws[:, 1] + draws[:, 2] * fd[0] + draws[:, 4] * dt
    assert p.sigma_ra_cosdec_mas == pytest.approx(east.std(), rel=0.05)
    assert p.sigma_dec_mas == pytest.approx(north.std(), rel=0.05)


def test_two_parameter_solution_not_propagated():
    """A 2-parameter solution keeps its catalog position and inflates the uncertainty by the stated allowance."""
    s = _src("b", 180.0, 35.0, sig=1.5)
    p = propagate_catalog_source(s, OBS, pm_allowance_mas_yr=20.0)
    assert not p.includes_space_motion and not p.includes_observer_parallax
    assert p.ra_deg == pytest.approx(180.0) and p.dec_deg == pytest.approx(35.0)
    dt = (OBS.mjd_tdb - J2016.mjd_tdb) / 365.25
    assert p.sigma_ra_cosdec_mas == pytest.approx(np.hypot(1.5, 20.0 * dt), rel=1e-9)
    assert any("2-parameter" in note for note in p.notes)


def test_association_statuses_and_no_invented_counterpart():
    """Unique counterpart -> matched; two within resolution -> ambiguous; none -> unmatched with a cautionary note."""
    a = _src("a", 180.0, 35.0, plx=0.1, pmra=0.0, pmdec=0.0)
    ra_b, dec_b = apply_offsets_mas(5000.0, 0.0, 180.0, 35.0)
    ra_c, dec_c = apply_offsets_mas(5400.0, 300.0, 180.0, 35.0)  # 0.5" from b: a blend at 1" resolution
    b = _src("b", float(ra_b), float(dec_b), plx=0.1, pmra=0.0, pmdec=0.0)
    c = _src("c", float(ra_c), float(dec_c), plx=0.1, pmra=0.0, pmdec=0.0)
    pa = propagate_catalog_source(a, OBS)
    pb = propagate_catalog_source(b, OBS)
    ra_far, dec_far = apply_offsets_mas(-15000.0, 9000.0, 180.0, 35.0)
    pts = [
        ImagePoint("p_a", "m_a", pa.ra_deg, pa.dec_deg, 8.0, 8.0),
        ImagePoint("p_b", "m_b", pb.ra_deg, pb.dec_deg, 8.0, 8.0),
        ImagePoint("p_far", "m_far", float(ra_far), float(dec_far), 8.0, 8.0),
    ]
    out = {x.image_source_id: x for x in associate(pts, [a, b, c], OBS, resolution_arcsec=1.0)}
    assert out["p_a"].status == "matched" and out["p_a"].candidates[0].catalog_source_id == "a"
    assert out["p_b"].status == "ambiguous"
    assert out["p_far"].status == "unmatched" and not out["p_far"].candidates
    assert "not by itself evidence of a new object" in out["p_far"].notes[0]


def test_epoch_propagation_is_required_for_high_proper_motion():
    """A 1.28"/yr source observed 10 yr after J2016.0 matches only after propagation (not with the raw catalog position)."""
    s = _src("fast", 180.0, 35.0, plx=165.0, pmra=640.0, pmdec=-1110.0)
    p = propagate_catalog_source(s, OBS)
    point = [ImagePoint("img", "m", p.ra_deg, p.dec_deg, 8.0, 8.0)]
    assert associate(point, [s], OBS, resolution_arcsec=1.0)[0].status == "matched"
    stale = s.model_copy(update={"pmra_mas_yr": 0.0, "pmdec_mas_yr": 0.0, "parallax_mas": 0.0})
    assert associate(point, [stale], OBS, resolution_arcsec=1.0)[0].status == "unmatched"


def test_padded_search_radius():
    """Search radius >= field radius + max_pm x |dt| so sources moving into the field are retrieved."""
    r = padded_search_radius_deg(0.01, J2016, [OBS], max_pm_arcsec_yr=5.0, margin_arcsec=0.0)
    dt = (OBS.mjd_tdb - J2016.mjd_tdb) / 365.25
    assert r == pytest.approx(0.01 + 5.0 * dt / 3600.0)
