"""Epoch propagation of Gaia DR3 astrometry (skyshift.science.epoch_propagation).

Independent references: the Gaia archive's own ESDC_EPOCH_PROP / ESDC_EPOCH_PROP_ERROR results
recorded for pinned sources at every exposure epoch, astropy/ERFA apply_space_motion (a different
algorithm that includes light time), a Monte Carlo propagation of the covariance, closed-form
tangent-plane motion, and astropy's TCB/TDB conversion.
"""

from __future__ import annotations

import json
import warnings

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import Distance, SkyCoord
from astropy.time import Time

from skyshift.coords.observer import observer_barycentric_au
from skyshift.coords.tangent import apply_offsets_mas, offsets_mas
from skyshift.coords.time import make_epoch
from skyshift.providers.gaia_dr3 import load_recorded_field
from skyshift.providers.gaia_dr3.catalog import parse_gaia_votable
from skyshift.providers.gaia_dr3.paths import epoch_prop_path, manifest_path
from skyshift.science.astrometry import parallax_factors
from skyshift.science.epoch_propagation import (
    JULIAN_YEAR_DAYS,
    AstrometricArrays,
    initial_covariance,
    observer_parallax_offsets,
    predict_observed,
    propagate,
    propagate_core,
)

FIELD = "spherex-dr1-barnard"
BARNARD = "4472832130942575872"
L_B = 1.550519768e-8  # IAU 2006 B3: d(TCB)/d(TDB) - 1


@pytest.fixture(scope="module")
def field():
    rec = load_recorded_field(FIELD)
    ref = make_epoch(2016.0, "jyear", "tcb")
    return rec, AstrometricArrays.from_columns(rec.catalog.columns, ref.mjd_tdb), ref


@pytest.fixture(scope="module")
def archive_prop():
    m = json.loads(manifest_path(FIELD).read_text(encoding="utf-8"))
    return parse_gaia_votable(epoch_prop_path(FIELD).read_bytes()), m["epoch_prop"]["target_epochs_jyear_tcb"]


def _subset(field, ids):
    rec, astro, ref = field
    idx = np.array([rec.catalog.index[s] for s in ids])
    return astro.subset(idx), idx


@pytest.mark.catalog
def test_positions_match_the_archive_propagation(field, archive_prop):
    """[catalog] Propagated parameters equal the archive's ESDC_EPOCH_PROP at every exposure epoch: positions < 1e-3 mas, parallax/pm < 1e-6 mas(/yr), mu_r < 1e-3."""
    rec, astro, ref = field
    ap, epochs = archive_prop
    sub, _ = _subset(field, ap.source_id)
    for k, t1 in enumerate(epochs):
        # use the archive's own time argument (Julian years on the TCB axis) so that only the algorithms are compared
        res = propagate(sub, ref.mjd_tdb + (t1 - 2016.0) * JULIAN_YEAR_DAYS, unknown_rv_sigma_km_s=0.0)
        arr = np.asarray(ap.columns[f"p{k}"], dtype=float)
        for i, sid in enumerate(ap.source_id):
            de, dn = offsets_mas(res.ra_deg[i], res.dec_deg[i], arr[i, 0], arr[i, 1])
            assert abs(float(de)) < 1e-3 and abs(float(dn)) < 1e-3, (sid, t1, float(de), float(dn))
            if res.propagated[i]:
                assert res.parallax_mas[i] == pytest.approx(arr[i, 2], abs=1e-6)
                assert res.pmra_mas_yr[i] == pytest.approx(arr[i, 3], abs=1e-6) and res.pmdec_mas_yr[i] == pytest.approx(arr[i, 4], abs=1e-6)
                assert res.mu_r_mas_yr[i] == pytest.approx(arr[i, 5], abs=1e-3, rel=1e-9)


@pytest.mark.catalog
def test_uncertainties_and_correlations_match_the_archive(field, archive_prop):
    """[catalog] The 6x6 propagated covariance reproduces ESDC_EPOCH_PROP_ERROR (Michalik et al. 2014 mu_r terms): sigmas within 1e-3 relative, correlations within 1e-3."""
    ap, epochs = archive_prop
    _, astro, ref = field
    sub, _ = _subset(field, ap.source_id)
    pairs = [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (2, 1), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2), (5, 2), (4, 3), (5, 3), (5, 4)]
    for k, t1 in enumerate(epochs):
        res = propagate(sub, ref.mjd_tdb + (t1 - 2016.0) * JULIAN_YEAR_DAYS, unknown_rv_sigma_km_s=0.0)  # archive: NULL rv error -> 0
        err = np.asarray(ap.columns[f"e{k}"], dtype=float)
        for i in range(len(ap.source_id)):
            c = res.cov6[i]
            n_par = 6 if res.propagated[i] else 2
            sig = np.sqrt(np.diag(c))[:n_par]
            assert np.allclose(sig, err[i, :n_par], rtol=1e-3, atol=1e-9), (ap.source_id[i], sig, err[i, :6])
            if res.propagated[i]:
                for (a, b), rho in zip(pairs, err[i, 6:]):
                    s = np.sqrt(c[a, a] * c[b, b])
                    if s > 0:
                        assert c[a, b] / s == pytest.approx(rho, abs=1e-3), (ap.source_id[i], a, b)


@pytest.mark.catalog
def test_agrees_with_erfa_space_motion_within_the_light_time_bound(field):
    """[catalog] astropy/ERFA apply_space_motion (includes light time) agrees: < 0.05 mas for Barnard's Star, < 1e-4 mas for other stars with significant positive parallax."""
    rec, astro, ref = field
    c = rec.catalog.columns
    ok = np.isfinite(c["parallax"]) & (c["parallax"] > 0.5) & (c["parallax"] / c["parallax_error"] > 10)
    idx = np.flatnonzero(ok)[:40]
    i_b = rec.catalog.index[BARNARD]
    idx = np.unique(np.append(idx, i_b))
    target = Time("2026-03-11T13:34:41", scale="utc")
    res = propagate(astro.subset(idx), target.tdb.mjd)
    rv = np.where(np.isfinite(c["radial_velocity"][idx]), c["radial_velocity"][idx], 0.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sc = SkyCoord(ra=c["ra"][idx] * u.deg, dec=c["dec"][idx] * u.deg, distance=Distance(parallax=c["parallax"][idx] * u.mas),
                      pm_ra_cosdec=c["pmra"][idx] * u.mas / u.yr, pm_dec=c["pmdec"][idx] * u.mas / u.yr, radial_velocity=rv * u.km / u.s,
                      obstime=Time(2016.0, format="jyear", scale="tcb")).apply_space_motion(new_obstime=target)
    for k, i in enumerate(idx):
        e, n = offsets_mas(sc.ra.deg[k], sc.dec.deg[k], res.ra_deg[k], res.dec_deg[k])
        d = float(np.hypot(e, n))
        assert d < (0.05 if i == i_b else 1e-4), (rec.catalog.source_id[i], d)


@pytest.mark.catalog
def test_covariance_matches_a_monte_carlo_propagation(field):
    """[catalog] The Jacobian position covariance equals a 20 000-draw Monte Carlo through the exact model within 5 % (sampling error ~1 %)."""
    rec, astro, ref = field
    rng = np.random.default_rng(7)
    c = rec.catalog.columns
    six = int(np.flatnonzero((c["astrometric_params_solved"] == 95) & (c["phot_g_mean_mag"] > 19))[0])
    for i in (rec.catalog.index[BARNARD], six):
        sub = astro.subset(np.array([i]))
        tgt = ref.mjd_tdb + 10.3 * JULIAN_YEAR_DAYS
        res = propagate(sub, tgt)
        rv_used = res.rv_used_km_s
        sig_rv = np.where(np.isfinite(sub.sigma_rv_km_s), sub.sigma_rv_km_s, 100.0) if np.isfinite(sub.rv_km_s[0]) else np.array([100.0])
        c0 = initial_covariance(sub, rv_used, sig_rv)[0]
        x0 = np.array([0.0, 0.0, sub.parallax_mas[0], sub.pmra_mas_yr[0], sub.pmdec_mas_yr[0], rv_used[0] * sub.parallax_mas[0] / 4.740470463533348])
        draws = rng.multivariate_normal(x0, c0, size=20000)
        ra_in, dec_in = apply_offsets_mas(draws[:, 0], draws[:, 1], sub.ra_deg[0], sub.dec_deg[0])
        out = propagate_core(ra_in, dec_in, draws[:, 2], draws[:, 3], draws[:, 4], draws[:, 5], np.full(len(draws), 10.3))
        e, n = offsets_mas(out[0], out[1], res.ra_deg[0], res.dec_deg[0])
        mc = np.cov(np.vstack([e, n]))
        an = res.cov6[0, :2, :2]
        assert np.sqrt(mc[0, 0]) == pytest.approx(np.sqrt(an[0, 0]), rel=0.05)
        assert np.sqrt(mc[1, 1]) == pytest.approx(np.sqrt(an[1, 1]), rel=0.05)
        rho_mc = mc[0, 1] / np.sqrt(mc[0, 0] * mc[1, 1])
        assert rho_mc == pytest.approx(an[0, 1] / np.sqrt(an[0, 0] * an[1, 1]), abs=0.03)


def _single(ra, dec, plx, pmra, pmdec, rv=np.nan):
    n = 1
    return AstrometricArrays(np.array([ra]), np.array([dec]), np.array([plx]), np.array([pmra]), np.array([pmdec]), np.array([rv]),
                             np.full((n, 5), 0.1), np.repeat(np.eye(5)[None], n, axis=0), np.array([np.nan]), make_epoch(2016.0, "jyear", "tcb").mjd_tdb)


@pytest.mark.catalog
def test_zero_radial_velocity_is_linear_tangent_plane_motion_and_pmra_includes_cos_dec():
    """[catalog] With v_r = 0 the result is the gnomonic deprojection of (pmra t, pmdec t); at Dec 80 deg pmra = 1000 mas/yr moves 1000 mas of arc per year."""
    a = _single(30.0, 80.0, 1.0, 1000.0, 0.0)
    t = 10.0
    res = propagate(a, a.ref_epoch_mjd_tdb + t * JULIAN_YEAR_DAYS)
    ra_c, dec_c = apply_offsets_mas(1000.0 * t, 0.0, 30.0, 80.0)
    e, n = offsets_mas(res.ra_deg[0], res.dec_deg[0], float(ra_c), float(dec_c))
    assert abs(float(e)) < 1e-6 and abs(float(n)) < 1e-6
    sep_mas = float(SkyCoord(30.0 * u.deg, 80.0 * u.deg).separation(SkyCoord(res.ra_deg[0] * u.deg, res.dec_deg[0] * u.deg)).to_value(u.mas))
    assert sep_mas == pytest.approx(np.degrees(np.arctan(1000.0 * t / 206264806.247)) * 3.6e6, rel=1e-9)
    d_ra_mas = (res.ra_deg[0] - 30.0) * 3.6e6
    assert d_ra_mas * np.cos(np.radians(80.0)) == pytest.approx(1000.0 * t, rel=1e-4)  # RA itself changes by ~5.76x more


@pytest.mark.catalog
def test_reference_epoch_is_tcb():
    """[catalog] J2016.0 is a TCB epoch: as TDB it is ~19.1 s earlier than J2016.0 TDB (astropy), and that offset is kept."""
    tcb = make_epoch(2016.0, "jyear", "tcb")
    assert tcb.mjd_tdb == pytest.approx(Time(2016.0, format="jyear", scale="tcb").tdb.mjd, abs=1e-12)
    dt_s = (Time(2016.0, format="jyear", scale="tdb").mjd - tcb.mjd_tdb) * 86400.0
    expected = L_B * (Time(2016.0, format="jyear", scale="tdb").jd - 2443144.5003725) * 86400.0 - 6.55e-5
    assert dt_s == pytest.approx(expected, abs=0.01) and 19.0 < dt_s < 19.2


@pytest.mark.catalog
def test_missing_motion_radial_velocity_and_weak_parallax_are_explicit(field):
    """[catalog] 2-parameter sources keep their J2016.0 position (flagged), v_r=0 sources carry a perspective bound, negative parallaxes stay finite and are never inverted."""
    rec, astro, ref = field
    c = rec.catalog.columns
    res = propagate(astro, ref.mjd_tdb + 10.0 * JULIAN_YEAR_DAYS)
    two = c["astrometric_params_solved"] == 3
    assert not res.propagated[two].any() and res.propagated[~two].all()
    assert np.allclose(res.ra_deg[two], c["ra"][two]) and np.allclose(res.dec_deg[two], c["dec"][two])
    assert np.all(np.isnan(res.pmra_mas_yr[two]))
    no_rv = ~two & ~np.isfinite(c["radial_velocity"])
    assert res.rv_assumed[no_rv].all() and np.all(res.perspective_bound_mas[no_rv] >= 0)
    assert np.all(res.perspective_bound_mas[np.isfinite(c["radial_velocity"])] == 0)
    neg = ~two & (c["parallax"] < 0)
    assert neg.sum() > 10 and np.all(np.isfinite(res.ra_deg[neg])) and np.all(res.parallax_mas[neg] < 0)
    # uncertainties grow with time for moving sources (and do not for 2-parameter ones)
    s0 = np.sqrt(astro.sigma5[~two, 0] ** 2)
    assert np.all(res.sigma_ra_cosdec_mas[~two] > s0)


@pytest.mark.catalog
def test_observer_parallax_is_applied_exactly_once():
    """[catalog] predict_observed = barycentric propagation + one parallax displacement equal to parallax x the existing parallax factors; no aberration term."""
    a = _single(269.44850252543836, 4.739420051112412, 546.975939730948, -801.5509783684709, 10362.394206546573, -110.46822)
    mjd = Time("2026-03-11T13:34:41", scale="utc").tdb.mjd
    b = observer_barycentric_au(np.array([mjd]))[0]
    bary = propagate(a, mjd)
    obs = predict_observed(a, mjd, b)
    e, n = offsets_mas(obs.ra_deg[0], obs.dec_deg[0], bary.ra_deg[0], bary.dec_deg[0])
    fr, fd = parallax_factors(bary.ra_deg[0], bary.dec_deg[0], b)
    plx = bary.parallax_mas[0]
    assert float(e) == pytest.approx(plx * float(fr[0]), abs=2e-6) and float(n) == pytest.approx(plx * float(fd[0]), abs=2e-6)
    oe, on = observer_parallax_offsets(bary.ra_deg, bary.dec_deg, bary.parallax_mas, b)
    assert np.hypot(oe[0], on[0]) <= plx * np.linalg.norm(b) * (1 + 1e-12)  # one application, never doubled
    assert np.hypot(float(e), float(n)) == pytest.approx(float(np.hypot(oe[0], on[0])), rel=1e-6)
