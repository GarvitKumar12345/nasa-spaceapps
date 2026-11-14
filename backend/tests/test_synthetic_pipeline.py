"""Synthetic generator and end-to-end investigation checks (truth used only for validation)."""

from __future__ import annotations

import numpy as np
import pytest

from skyshift.contracts import FitRequest
from skyshift.coords.observer import observer_barycentric_au
from skyshift.coords.tangent import offsets_mas
from skyshift.coords.time import jyear_to_mjd_tdb
from skyshift.pipeline.investigation import Investigation
from skyshift.providers.registry import synthetic_provider
from skyshift.science.astrometry import fit_astrometry, parallax_factors
from skyshift.synthetic.generator import generate
from skyshift.synthetic.scenario import default_scenario


@pytest.fixture(scope="module")
def bundle():
    return synthetic_provider().load_dataset("syn-nb-01")


@pytest.mark.contracts
def test_generation_is_deterministic(bundle):
    """Same seed -> identical arrays and Dataset JSON; a different seed changes the pixels."""
    again = generate(default_scenario(), bundle.dataset.seed)
    assert again.dataset.model_dump_json() == bundle.dataset.model_dump_json()
    for fid, arr in bundle.arrays.items():
        assert np.array_equal(arr.image, again.arrays[fid].image) and np.array_equal(arr.mask, again.arrays[fid].mask)
    other = generate(default_scenario(), bundle.dataset.seed + 1)
    assert not np.array_equal(other.arrays[next(iter(other.arrays))].image, bundle.arrays[next(iter(bundle.arrays))].image)


@pytest.mark.contracts
def test_schedule_ids_statuses_and_timing(bundle):
    """22 band-visits; missing/failed observations keep their reasons and have no frames; mid = start + 90 s; G2 starts 240 s later."""
    obs = {o.id: o for o in bundle.dataset.observations}
    assert len(obs) == 22 and len(bundle.dataset.frames) == 18
    assert obs["syn-nb-01:v04:G1"].status == "missing" and obs["syn-nb-01:v06:G2"].status == "missing"
    assert obs["syn-nb-01:v10:G1"].status == "failed" and not obs["syn-nb-01:v10:G2"].frame_ids
    for o in obs.values():
        assert (o.timing.mid.mjd_tdb - o.timing.start.mjd_tdb) * 86400 == pytest.approx(90.0, abs=1e-5)
        assert (o.status == "available") == bool(o.frame_ids)
    g1, g2 = obs["syn-nb-01:v01:G1"], obs["syn-nb-01:v01:G2"]
    assert (g2.timing.start.mjd_tdb - g1.timing.start.mjd_tdb) * 86400 == pytest.approx(240.0, abs=1e-5)


@pytest.mark.contracts
def test_dataset_contains_no_truth_and_declares_origin(bundle):
    """The Dataset served to the UI carries no simulation-truth values or origins; frames are 'simulated' electrons with sky included."""
    text = bundle.dataset.model_dump_json()
    assert "simulation_truth" not in text and "truth:" not in text
    frame = bundle.dataset.frames[0]
    assert frame.provenance.origin == "simulated" and frame.unit == "electron" and frame.background.included_in_image
    assert not frame.display_only and frame.psf.includes_pixel_response


@pytest.mark.contracts
def test_variance_from_data_and_masks(bundle):
    """Variance = read_noise^2 + max(image, 0) from the noisy data; hot pixels flagged identically in every frame."""
    hot_sets = []
    for arr in bundle.arrays.values():
        np.testing.assert_allclose(arr.variance, 25.0 + np.maximum(arr.image, 0), rtol=1e-6)
        hot_sets.append(set(zip(*np.nonzero(arr.mask & 1))))
    assert all(h == hot_sets[0] for h in hot_sets) and len(hot_sets[0]) == 12


@pytest.mark.catalog
def test_simulated_catalog_conventions(bundle):
    """Simulated catalog: J2016.0 TCB epoch, origin 'simulated', C1 5-parameter, V1 2-parameter, some negative parallaxes."""
    cat = bundle.catalog
    assert all(s.reference_epoch.scale == "tcb" and s.reference_epoch.value == 2016.0 and s.origin == "simulated" for s in cat)
    assert any(s.astrometric_solution == "2-parameter" and s.parallax_mas is None for s in cat)
    assert any((s.parallax_mas or 0) > 100 for s in cat)
    assert any((s.parallax_mas or 0) < 0 for s in cat)
    assert all(s.radial_velocity_km_s is None for s in cat)


@pytest.mark.pipeline
def test_truth_motion_matches_hand_written_estimate(bundle):
    """C1 truth displacement between two epochs equals pm*dt + parallax-factor change (written here independently) within 1 mas."""
    sc = default_scenario().candidate
    pos = {p.frame_id: p for p in bundle.truth.positions if p.truth_id == "truth:C1"}
    a, b = "syn-nb-01:v01:G1:native", "syn-nb-01:v11:G1:native"
    obs = {o.frame_ids[0]: o for o in bundle.dataset.observations if o.frame_ids}
    ta, tb = obs[a].timing.mid.mjd_tdb, obs[b].timing.mid.mjd_tdb
    e, n = offsets_mas(pos[b].ra_deg, pos[b].dec_deg, pos[a].ra_deg, pos[a].dec_deg)
    fa = parallax_factors(pos[a].ra_deg, pos[a].dec_deg, observer_barycentric_au(np.array([ta])))
    fb = parallax_factors(pos[a].ra_deg, pos[a].dec_deg, observer_barycentric_au(np.array([tb])))
    dt = (tb - ta) / 365.25
    assert float(e) == pytest.approx(sc.pmra_mas_yr * dt + sc.parallax_mas * (fb[0][0] - fa[0][0]), abs=1.0)
    assert float(n) == pytest.approx(sc.pmdec_mas_yr * dt + sc.parallax_mas * (fb[1][0] - fa[1][0]), abs=1.0)


@pytest.mark.registration
def test_registration_recovers_truth_wcs_in_every_frame(investigation):
    """Real registration accuracy per frame: registered-vs-truth WCS error at grid points is within 4.5 sigma of the
    registration's own propagated covariance, while the headers were wrong by > 0.5"."""
    from skyshift.coords.tangent import offsets_mas as off
    from skyshift.coords.wcs import description_to_wcs, pixel_to_sky
    from skyshift.imaging.registration import registration_cov_mas

    gx, gy = np.meshgrid(np.linspace(5, 154, 5), np.linspace(5, 154, 5))
    worst_header, worst_norm = 0.0, 0.0
    for ft in investigation.bundle.truth.frames:
        st = investigation.frames[ft.frame_id]
        assert st.registration.summary.quality.status in ("ok", "warning")
        tw = description_to_wcs(ft.true_wcs)
        for x, y in zip(gx.ravel(), gy.ravel()):
            r1, d1 = st.registration.wcs.pixel_to_sky(np.array(x), np.array(y))
            r2, d2 = pixel_to_sky(tw, x, y)
            e, n = off(float(r1), float(d1), float(r2), float(d2))
            d = np.array([float(e), float(n)])
            worst_norm = max(worst_norm, float(np.sqrt(d @ np.linalg.solve(registration_cov_mas(st.registration, x, y), d))))
        r0, d0 = pixel_to_sky(description_to_wcs(st.product.wcs), gx.ravel(), gy.ravel())
        r2, d2 = pixel_to_sky(tw, gx.ravel(), gy.ravel())
        from skyshift.coords.tangent import angular_separation_deg

        worst_header = max(worst_header, float(np.max(angular_separation_deg(r0, d0, r2, d2)) * 3.6e6))
    assert worst_norm < 4.5
    assert worst_header > 500


@pytest.mark.pipeline
def test_moving_source_measured_from_pixels_matches_truth(investigation, c1_id):
    """C1 is tracked in all 18 frames; image-measured positions vs truth have pulls with |mean| < 0.5 and std in [0.7, 1.4]."""
    ms = investigation.measure(c1_id).measurements
    measured = [m for m in ms if m.status == "measured"]
    assert len(measured) == 18 and sum(m.status == "missing_frame" for m in ms) == 4
    truth = {p.frame_id: p for p in investigation.bundle.truth.positions if p.truth_id == "truth:C1"}
    pulls = []
    for m in measured:
        e, n = offsets_mas(m.ra_deg, m.dec_deg, truth[m.frame_id].ra_deg, truth[m.frame_id].dec_deg)
        pulls += [float(e) / m.sigma_ra_cosdec_mas, float(n) / m.sigma_dec_mas]
    pulls = np.array(pulls)
    assert abs(pulls.mean()) < 0.5 and 0.7 < pulls.std(ddof=1) < 1.4


@pytest.mark.pipeline
def test_stationary_isolated_star_pulls_are_unit_normal(investigation):
    """Isolated stationary stars (no truth neighbour within 3"): position pulls vs truth have std in [0.8, 1.25] — uncertainties are calibrated."""
    from skyshift.coords.tangent import angular_separation_deg

    tr = investigation.bundle.truth.sources
    tra = np.array([t.ra_deg for t in tr])
    tdec = np.array([t.dec_deg for t in tr])
    pulls = []
    for s in investigation.sources:
        sep = angular_separation_deg(s.position.ra_deg, s.position.dec_deg, tra, tdec) * 3600
        j = int(np.argmin(sep))
        if sep[j] > 0.3 or tr[j].kind != "stationary_star" or np.sort(angular_separation_deg(tr[j].ra_deg, tr[j].dec_deg, tra, tdec) * 3600)[1] < 3.0:
            continue
        for m in investigation.measure(s.id).measurements:
            if m.status == "measured":
                e, n = offsets_mas(m.ra_deg, m.dec_deg, tr[j].ra_deg, tr[j].dec_deg)
                pulls += [float(e) / m.sigma_ra_cosdec_mas, float(n) / m.sigma_dec_mas]
    pulls = np.array(pulls)
    assert len(pulls) > 150 and abs(pulls.mean()) < 0.3 and 0.8 < pulls.std() < 1.25


@pytest.mark.pipeline
def test_full_fit_recovers_injected_motion_and_parallax(investigation, c1_id):
    """Fit of image-derived positions recovers the injected pm and parallax within 3 sigma with an acceptable chi2 (p > 0.001)."""
    ms = investigation.measure(c1_id).measurements
    fit = fit_astrometry(FitRequest(dataset_id="syn-nb-01", source_id=c1_id, model="proper_motion_parallax", measurements=ms,
                                    reference_epoch_mjd_tdb=float(jyear_to_mjd_tdb(2026.0))))
    p = {q.name: q for q in fit.parameters}
    truth = {"pmra": 640.0, "pmdec": -1110.0, "parallax": 165.0}
    for name, value in truth.items():
        assert abs(p[name].value - value) < 3 * p[name].uncertainty, name
    assert fit.identifiability.status == "constrained" and fit.p_value > 1e-3
    assert next(d for d in fit.derived if d.name == "distance").status == "derived"


@pytest.mark.pipeline
def test_change_indicators_flag_motion_and_variability(investigation, c1_id, v1_id):
    """Derived indicators: C1 displacement significant, V1 flux variation significant, most stationary stars not flagged."""
    ind = {s.id: {c.kind: c for c in s.change_indicators} for s in investigation.sources}
    assert ind[c1_id]["displacement"].significant and not ind[c1_id]["flux_variation"].significant
    assert ind[v1_id]["flux_variation"].significant and not ind[v1_id]["displacement"].significant
    flagged = sum(1 for k, v in ind.items() if k not in (c1_id, v1_id) and v["displacement"].significant)
    assert flagged <= 0.1 * len(ind)


@pytest.mark.catalog
def test_moving_source_matches_its_catalog_entry_after_propagation(investigation, c1_id):
    """C1 matches its simulated-catalog counterpart at every epoch once catalog astrometry is propagated from J2016.0."""
    assoc = investigation.associations(c1_id)
    assert len(assoc) == 18 and all(a.status == "matched" for a in assoc)
    assert len({a.candidates[0].catalog_source_id for a in assoc}) == 1


@pytest.mark.catalog
def test_close_pair_is_kept_ambiguous_in_wide_psf_band(investigation):
    """The 1.1" close pair is never reported as a clean unique match in G2 (PSF 1.4"): the blend stays 'ambiguous'."""
    from skyshift.coords.tangent import angular_separation_deg

    truth = next(t for t in investigation.bundle.truth.sources if t.truth_id == "truth:pair:a")
    src = min(investigation.sources, key=lambda s: float(angular_separation_deg(s.position.ra_deg, s.position.dec_deg, truth.ra_deg, truth.dec_deg)))
    g2 = [a for a in investigation.associations(src.id) if ":G2:" in (a.measurement_id or "")]
    assert g2 and all(a.status == "ambiguous" for a in g2)


@pytest.mark.pipeline
def test_measurements_never_read_truth(bundle):
    """The pipeline gives identical measurements when the truth is removed from the bundle."""
    stripped = bundle.__class__(dataset=bundle.dataset, arrays=bundle.arrays, catalog=bundle.catalog, catalog_name=bundle.catalog_name, truth=None)
    inv = Investigation(stripped)
    ref = Investigation(bundle)
    a = inv.measure("S003").measurements
    b = ref.measure("S003").measurements
    assert [m.model_dump() for m in a] == [m.model_dump() for m in b]


@pytest.mark.pipeline
def test_difference_requires_same_band_and_registration(investigation):
    """Difference previews are allowed only for registered, same-band frames; G1 vs G2 is refused with a reason."""
    ok, arr = investigation.difference("syn-nb-01:v01:G1:registered", "syn-nb-01:v11:G1:registered")
    assert ok.compatible and arr is not None and arr.shape == (176, 176)
    bad, none = investigation.difference("syn-nb-01:v01:G1:registered", "syn-nb-01:v01:G2:registered")
    assert not bad.compatible and none is None and "wavelength" in bad.reasons[0]
