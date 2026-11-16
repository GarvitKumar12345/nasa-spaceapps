"""Stage 2: van Maanen 2's seasonal displacement from real SPHEREx pixels, with systematics tests and per-pair decisions.

Reuses the first pass (scripts/target_astrometry.py, results kept unchanged in validation/vanmaanen2_motion.json) and
adds, per STAGE2_PLAN below: the corrected start rule, analysis-choice systematics (background model, fit window,
ePSF interpolated between zones, neighbours modelled jointly), the D2 feature test, a tied-budget validation with
reference stars measured in both seasons, per-pair statistical/systematic uncertainties and pass/fail/inconclusive
statuses, robustness across analysis variants, fit/residual stamps and diagnostics plots.

Run: cd backend && uv run python scripts/target_motion_stage2.py
Writes validation/vanmaanen2_motion_stage2.json, validation/vanmaanen2_motion_stage2_pairs.csv, validation/plots/vanmaanen2_stage2_*.png
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import sys
import warnings
from dataclasses import asdict
from pathlib import Path

import numpy as np

warnings.simplefilter("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from astropy.time import Time  # noqa: E402
from scipy import stats  # noqa: E402

from skyshift.coords.tangent import offsets_mas  # noqa: E402
from skyshift.imaging.epsf import fit_position  # noqa: E402
from skyshift.pipeline.observed_gaia import observed_gaia  # noqa: E402
from skyshift.providers.gaia_dr3 import load_recorded_field  # noqa: E402
from skyshift.providers.spherex import SpherexProvider  # noqa: E402
from skyshift.providers.spherex.fields import PRESETS  # noqa: E402
from skyshift.science import target_astrometry as ta  # noqa: E402
from skyshift.science.alignment import excluded_mask  # noqa: E402
from skyshift.validation.report import source_hash  # noqa: E402
from target_astrometry import identify_target, neighbours_of  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIELD = "spherex-dr1-vanmaanen2"
STAGE2_PLAN = {
    "defined_utc": "2026-11-16T01:30Z",
    "disclosure": "Defined after the first pass (validation/vanmaanen2_motion.json), whose results were known: not a blind analysis. "
                  "The first-pass rules and results are kept unchanged for comparison.",
    "frames": "stage-1 usability unchanged (diagnostic S/N >= 30, unsaturated, clean core; D6 excluded); fit sigma <= 0.25 px",
    "start_rule": "start dependence tested inside one fixed fit window (<= 0.002 px); the RMS shift over the windows that offset starts "
                  "select is a systematic term (the first-pass rule conflated the two)",
    "systematics": "per epoch: first-pass terms + window choice + analysis choice (RMS shift over: constant background, 5x5 and 9x9 "
                   "windows, ePSF interpolated between zones, catalogued neighbours modelled jointly)",
    "approaches": "tied to reference stars (frames with >= 5 references) and untied (archive WCS; frame-WCS term = RMS of this field's "
                  "tied frame offsets)",
    "budget_validation": "tied: reference stars measured in both seasons on one detector (leave-one-out ties), chi2 of their epoch-to-epoch "
                         "changes after Gaia propagation; untied: the target's zero-displacement pairs (same exposure on two detectors; one "
                         "detector minutes apart). Each needs p >= 0.0027",
    "pair_status": "pass: consistent with the prediction (p >= 0.0027) and p(vs 0) < 5.7e-7 with a validated budget; inconclusive: "
                   "consistent but below that, or the budget not validated; fail: inconsistent with the prediction (p < 0.0027)",
    "conclusion": "recovered if, for at least one approach with a validated budget, the combined D1-D3 pairs give p(vs 0) < 5.7e-7 and "
                  "p(vs prediction) >= 0.0027, and the detection holds for every analysis variant",
    "not_done": "no proper-motion or parallax fit: two epochs per detector give one displacement",
}
P_DETECT = 2 * stats.norm.sf(5.0)
P_CONSISTENT = 0.0027
VARIANTS = ("background_constant", "window_5x5", "window_9x9", "epsf_interpolated", "neighbours_modelled")


def sigma_equiv(p: float) -> float:
    """Two-sided normal-equivalent significance of a p-value."""
    return float(stats.norm.isf(max(p, 1e-300) / 2.0))


def sky(J: np.ndarray, sx: float, sy: float) -> np.ndarray:
    return np.sqrt((J**2) @ np.array([sx**2, sy**2]))


def variants_for(fi, fit: ta.TargetFit, nbs: list[dict], det_xy: tuple[float, float]) -> dict:  # noqa: ANN001
    img, var = np.asarray(fi.image, float), np.asarray(fi.variance, float)
    bad = (fi.flags.astype(np.int64) & excluded_mask(fi.flag_masks)) != 0
    model = fi.epsf.model(fit.zone)
    sx, sy = int(fit.start_xy[0]), int(fit.start_xy[1])
    out: dict[str, dict] = {}

    def keep(name: str, x: float | None, y: float | None, note: str = "") -> None:
        out[name] = {"x": x, "y": y, "shift_px": [x - fit.x, y - fit.y] if x is not None else None, "note": note}

    g = fit_position(img, var, bad, model, sx, sy, background="constant")
    keep("background_constant", g.x if g.status == "ok" else None, g.y if g.status == "ok" else None)
    for h, name in ((2, "window_5x5"), (4, "window_9x9")):
        g = fit_position(img, var, bad, model, sx, sy, half_window=h)
        keep(name, g.x if g.status == "ok" else None, g.y if g.status == "ok" else None)
    imodel, weights = ta.interpolated_epsf(fi, *det_xy)
    g = fit_position(img, var, bad, imodel, sx, sy)
    keep("epsf_interpolated", g.x if g.status == "ok" else None, g.y if g.status == "ok" else None, f"zone weights {weights}")
    j = ta.fit_with_neighbours(fi, model, fit.x, fit.y, nbs, window_center=(sx, sy)) if nbs else {"x": fit.x, "y": fit.y}
    keep("neighbours_modelled", *((j["x"], j["y"]) if j else (None, None)), f"{len(nbs)} catalogued neighbour(s) modelled with free flux")
    if j:
        out["neighbours_modelled"]["joint_fit"] = {k: v for k, v in j.items() if k not in ("x", "y")}
    return out


def main() -> int:
    preset = PRESETS[FIELD]
    bundle = SpherexProvider().load_dataset(FIELD)
    recorded = load_recorded_field(FIELD)
    og = observed_gaia(bundle, recorded)
    sid, ident = identify_target(og, preset.study_target)
    assert sid == preset.study_target.gaia_dr3_source_id and og.cfg.excluded_source_ids == (sid,)
    rep = og.report()
    i_t = og.catalog.index[sid]
    stage1 = {f["frame_id"]: f for f in json.loads((REPO / "validation" / "vanmaanen2_stage1.json").read_text(encoding="utf-8"))["frames"]}
    fa_by = {f.frame_id: f for f in rep.frames}
    cfg = ta.TargetConfig()
    tied_frames = [f for f in rep.frames if f.status == "ok" and f.translation.evaluated]
    offs = np.array([[f.translation.offset_east_arcsec, f.translation.offset_north_arcsec] for f in tied_frames])
    wcs_rms = np.sqrt(np.mean(offs**2, axis=0))
    extra_pooled = float(rep.pooled.extra_scatter_arcsec or 0.0)
    cat_px_cache: dict[str, np.ndarray] = {}
    frames: list[dict] = []
    for nid in sorted(og.obs_by_native, key=lambda k: (og.images[k].detector, og.epoch_of(k).mjd_tdb)):
        img = og.images[nid]
        obs = og.obs_by_native[nid]
        fa = fa_by[nid]
        fi = og._frame_inputs(nid)
        pred = og.prediction(nid)
        px, py = fi.sky_to_pixel(pred.ra_deg, pred.dec_deg)
        cat_px_cache[nid] = np.column_stack([px, py])
        s1 = stage1.get(nid, {})
        row = {"frame_id": nid, "obs_id": img.obs_id, "detector": int(img.detector), "band_id": obs.band_id, "mid_utc": obs.timing.mid.iso_utc,
               "season": s1.get("season"), "lambda_um": obs.archive.local_wavelength_um if obs.archive else None,
               "stage1_snr": s1.get("diagnostic_snr_3x3"), "n_references": fa.n_used, "frame_status": fa.status,
               "predicted": {"ra_deg": float(pred.ra_deg[i_t]), "dec_deg": float(pred.dec_deg[i_t]), "x_px": float(px[i_t]), "y_px": float(py[i_t]), "origin": "model_prediction"},
               "spherex_file": obs.archive.file_name if obs.archive else None}
        if int(img.detector) == 6 or not s1.get("usable"):
            row.update(status="excluded", reason=f"stage-1 criteria not met ({s1.get('reason')})")
            frames.append(row)
            continue
        nbs = neighbours_of(og, nid, i_t, cfg)
        fit = ta.fit_target(fi, float(px[i_t]), float(py[i_t]), nbs, cfg)
        start_ok = fit.start_spread_fixed_window_px is not None and fit.start_spread_fixed_window_px <= cfg.start_tolerance_px
        sigma_ok = fit.sigma_x is not None and max(fit.sigma_x, fit.sigma_y) <= cfg.max_sigma_px
        if fit.x is None or not (start_ok and sigma_ok):
            row.update(status="rejected", reason=fit.reason if fit.x is None else ("start dependence inside a fixed window" if not start_ok else "position sigma above 0.25 px"))
            frames.append(row)
            continue
        det_xy = (fit.x + fi.detector_offset[0], fit.y + fi.detector_offset[1])
        var_res = variants_for(fi, fit, nbs, det_xy)
        shifts = np.array([v["shift_px"] for k, v in var_res.items() if k in VARIANTS and v["shift_px"] is not None])
        analysis_rms = np.sqrt(np.mean(shifts**2, axis=0)) if len(shifts) else np.zeros(2)
        features = ta.uncatalogued_features(fi, fit.x, fit.y, np.delete(cat_px_cache[nid], i_t, axis=0))
        feat_impact = None
        if features:
            imgv, varv = np.asarray(fi.image, float), np.asarray(fi.variance, float)
            badv = (fi.flags.astype(np.int64) & excluded_mask(fi.flag_masks)) != 0
            yy, xx = np.mgrid[0 : imgv.shape[0], 0 : imgv.shape[1]]
            fmask = np.zeros_like(badv)
            for ftr in features:
                fmask |= np.hypot(xx - ftr["x"], yy - ftr["y"]) <= 1.5
            sx_, sy_ = int(fit.start_xy[0]), int(fit.start_xy[1])
            a = fit_position(imgv, varv, badv, fi.epsf.model(fit.zone), sx_, sy_, half_window=5)
            b = fit_position(imgv, varv, badv | fmask, fi.epsf.model(fit.zone), sx_, sy_, half_window=5)
            if a.status == "ok" and b.status == "ok":
                feat_impact = {"window": "11x11 (the 7x7 fit window does not reach r >= 3.5 px features)", "shift_unmasked_minus_masked_px": [a.x - b.x, a.y - b.y],
                               "nominal_minus_masked_11x11_px": [fit.x - b.x, fit.y - b.y]}
        J = og._sky_jacobian(nid)
        ra_m, dec_m = fi.pixel_to_sky(np.array([fit.x]), np.array([fit.y]))
        e, n = offsets_mas(float(ra_m[0]), float(dec_m[0]), float(pred.ra_deg[i_t]), float(pred.dec_deg[i_t]))
        wc = sky(J, *(fit.window_choice_rms_px or (0.0, 0.0)))
        ac = sky(J, *analysis_rms)
        diag, _ = og.diagnosis(nid)
        ref_zones = [r.zone for r in diag.used if r.zone is not None]
        tied = fa.status == "ok" and fa.translation.evaluated
        budgets = {}
        if tied:
            t = fa.translation
            b = ta.epoch_budget(fit, (t.sigma_random_east_arcsec, t.sigma_random_north_arcsec), float(fa.statistics.extra_scatter_arcsec or 0.0),
                                ta.convention_differential_px(fi, fit.zone, ref_zones), J)
            budgets["tied"] = b
        b_u = ta.epoch_budget(fit, tuple(wcs_rms), extra_pooled, ta.convention_differential_px(fi, fit.zone, []), J)
        budgets["untied"] = b_u
        for b in budgets.values():
            b["terms_arcsec"]["window_choice"] = wc.tolist()
            b["terms_arcsec"]["analysis_choice"] = ac.tolist()
            b["systematic_arcsec"] = [math.hypot(b["systematic_arcsec"][i], wc[i], ac[i]) for i in (0, 1)]
            b["total_arcsec"] = [math.hypot(b["random_arcsec"][i], b["systematic_arcsec"][i]) for i in (0, 1)]
        resid = np.array([float(e), float(n)]) / 1000.0
        row.update(status="measured", reason="measured",
                   measured={"x_px": fit.x, "y_px": fit.y, "sigma_x_px": fit.sigma_x, "sigma_y_px": fit.sigma_y, "ra_deg": float(ra_m[0]), "dec_deg": float(dec_m[0]),
                             "chi2_red": fit.chi2_red, "snr": fit.snr, "origin": "derived_measurement"},
                   fit_metadata={"zone": fit.zone, "zone_center_detector_px": [fi.epsf.zones[fit.zone].x_center, fi.epsf.zones[fit.zone].y_center],
                                 "detector_px": list(det_xy), "window_center_px": list(fit.start_xy), "window": "7x7", "background": "plane",
                                 "start_spread_px": fit.start_spread_px, "start_spread_fixed_window_px": fit.start_spread_fixed_window_px,
                                 "window_choice_rms_px": fit.window_choice_rms_px, "zone_swap_shift_px": fit.zone_swap_shift_px,
                                 "neighbour_shift_px": fit.neighbour_shift_px, "n_masked": fit.n_masked, "pixel_convention": "0-based, integer = pixel centre, [iy, ix]",
                                 "epsf": "zone containing the star; A&K flux fractions = 25 x stored; bicubic spline (photutils ImagePSF-equivalent)"},
                   variants=var_res, analysis_choice_rms_px=analysis_rms.tolist(), uncatalogued_features=features, feature_impact=feat_impact,
                   neighbours=nbs, residual_untied_arcsec=resid.tolist(),
                   frame_offset_arcsec=[fa.translation.offset_east_arcsec, fa.translation.offset_north_arcsec] if tied else None,
                   residual_tied_arcsec=(resid - np.array([fa.translation.offset_east_arcsec, fa.translation.offset_north_arcsec])).tolist() if tied else None,
                   budgets=budgets, stamps=ta.fit_stamps(fi, fit), jacobian_arcsec_per_px=J.tolist())
        frames.append(row)
    by = {r["frame_id"]: r for r in frames}

    def pos(r: dict, approach: str, variant: str | None = None) -> tuple[float, float]:
        """Sky position of the target (measured, optionally a variant), tied positions shifted by the frame offset."""
        ra, dec = r["measured"]["ra_deg"], r["measured"]["dec_deg"]
        if variant:
            v = r["variants"][variant]
            if v["x"] is None:
                return ra, dec
            fi = og._frame_inputs(r["frame_id"])
            a, b = fi.pixel_to_sky(np.array([v["x"]]), np.array([v["y"]]))
            ra, dec = float(a[0]), float(b[0])
        return ra, dec

    def pair_stats(a: dict, c: dict, approach: str, label: str, variant: str | None = None) -> dict:
        pe, pn = offsets_mas(c["predicted"]["ra_deg"], c["predicted"]["dec_deg"], a["predicted"]["ra_deg"], a["predicted"]["dec_deg"])
        pred = np.array([pe, pn]) / 1000.0
        ra_c, de_c = pos(c, approach, variant)
        ra_a, de_a = pos(a, approach, variant)
        me, mn = offsets_mas(ra_c, de_c, ra_a, de_a)
        meas = np.array([me, mn]) / 1000.0
        if approach == "tied":
            meas = meas - (np.array(c["frame_offset_arcsec"]) - np.array(a["frame_offset_arcsec"]))
        ba, bc = a["budgets"][approach], c["budgets"][approach]
        s_stat = np.hypot(ba["random_arcsec"], bc["random_arcsec"])
        s_sys = np.hypot(ba["systematic_arcsec"], bc["systematic_arcsec"])
        s_tot = np.hypot(s_stat, s_sys)
        c0, p0 = ta.chi2_2d(meas, s_tot)
        cp, pp = ta.chi2_2d(meas - pred, s_tot)
        out = {"label": label, "approach": approach, "detector": a["detector"], "observation_ids": [a["obs_id"], c["obs_id"]], "epochs_utc": [a["mid_utc"], c["mid_utc"]],
               "interval_days": float(Time(c["mid_utc"]).mjd - Time(a["mid_utc"]).mjd), "predicted_arcsec": pred.tolist(), "measured_arcsec": meas.tolist(),
               "residual_arcsec": (meas - pred).tolist(), "sigma_stat_arcsec": s_stat.tolist(), "sigma_sys_arcsec": s_sys.tolist(), "sigma_total_arcsec": s_tot.tolist(),
               "predicted_length_arcsec": float(np.linalg.norm(pred)), "measured_length_arcsec": float(np.linalg.norm(meas)),
               "chi2_vs_zero": c0, "p_vs_zero": p0, "sigma_equiv_vs_zero": sigma_equiv(p0), "chi2_vs_prediction": cp, "p_vs_prediction": pp}
        if np.linalg.norm(pred) > 0.1:  # zero-displacement pairs have no predicted direction
            k, sk, perp, sperp = ta.along_ratio(meas, pred, s_tot)
            out.update(along_ratio=k, along_ratio_sigma=sk, perpendicular_arcsec=perp, perpendicular_sigma_arcsec=sperp)
        return out

    # budget validation, untied: the target's zero-displacement pairs
    meas = [r for r in frames if r["status"] == "measured"]
    nulls = []
    for a in meas:
        for c in meas:
            if a["frame_id"] >= c["frame_id"]:
                continue
            minutes = abs(Time(a["mid_utc"]).mjd - Time(c["mid_utc"]).mjd) * 1440.0
            if (a["obs_id"] == c["obs_id"] and a["detector"] != c["detector"]) or (a["detector"] == c["detector"] and minutes < 10.0):
                s = pair_stats(a, c, "untied", f"D{a['detector']}/D{c['detector']} {a['mid_utc'][:10]}")
                s["kind"] = "same exposure, two detectors" if a["obs_id"] == c["obs_id"] else f"same detector, {minutes:.1f} min apart (two exposures)"
                nulls.append(s)
    n_chi = float(sum(p["chi2_vs_prediction"] for p in nulls))
    n_dof = 2 * len(nulls)
    untied_valid = {"test": "target zero-displacement pairs", "n_pairs": len(nulls), "chi2": n_chi, "dof": n_dof,
                    "p": float(stats.chi2.sf(n_chi, n_dof)) if n_dof else None, "pairs": nulls}
    untied_valid["passed"] = bool(n_dof and untied_valid["p"] >= P_CONSISTENT)
    # budget validation, tied: reference stars measured in both seasons on one detector (leave-one-out ties)
    ref_rows, r_chi = [], 0.0
    bands = sorted({r["band_id"] for r in frames})
    for band in bands:
        m = sorted((fa_by[r["frame_id"]] for r in frames if r["band_id"] == band), key=lambda f: f.epoch.mjd_tdb)
        if len(m) != 2 or not all(f.status == "ok" and f.translation.evaluated for f in m):
            continue
        refs = [{r.source_id: r for r in f.residuals if r.status == "used"} for f in m]
        xs = [float(f.statistics.extra_scatter_arcsec or 0.0) for f in m]
        common = sorted(set(refs[0]) & set(refs[1]))

        def loo(k: int, s: str, axis: str) -> tuple[float, float]:
            vals = [(r, 1.0 / (getattr(r, f"sigma_{axis}_arcsec") ** 2 + xs[k] ** 2)) for sid_, r in refs[k].items() if sid_ != s]
            w = np.array([v[1] for v in vals])
            x = np.array([getattr(v[0], f"residual_{axis}_arcsec") for v in vals])
            return float(np.sum(w * x) / np.sum(w)), float(1.0 / math.sqrt(np.sum(w)))

        for s in common:
            d, sd = [], []
            for axis in ("east", "north"):
                t = []
                v = []
                for k in (0, 1):
                    off, soff = loo(k, s, axis)
                    r = refs[k][s]
                    t.append(getattr(r, f"residual_{axis}_arcsec") - off)
                    v.append(getattr(r, f"sigma_{axis}_arcsec") ** 2 + xs[k] ** 2 + soff**2)
                d.append(t[1] - t[0])
                sd.append(math.sqrt(sum(v)))
            r_chi += float(np.sum((np.array(d) / np.array(sd)) ** 2))
            ref_rows.append({"band": band, "source_id": s, "change_arcsec": d, "sigma_arcsec": sd})
    r_dof = 2 * len(ref_rows)
    tied_valid = {"test": "reference stars in both seasons on one detector (leave-one-out ties), changes after Gaia propagation",
                  "n_stars": len(ref_rows), "chi2": r_chi, "dof": r_dof, "p": float(stats.chi2.sf(r_chi, r_dof)) if r_dof else None, "stars": ref_rows}
    tied_valid["passed"] = bool(r_dof and tied_valid["p"] >= P_CONSISTENT)
    valid = {"tied": tied_valid, "untied": untied_valid}
    # motion pairs
    pairs = []
    for band in bands:
        m = sorted((r for r in frames if r["band_id"] == band), key=lambda r: r["mid_utc"])
        if len(m) != 2 or m[0]["season"] == m[1]["season"]:
            continue
        det = m[0]["detector"]
        role = "primary" if det in cfg.primary_detectors else "secondary" if det in cfg.secondary_detectors else "excluded"
        for approach in ("tied", "untied"):
            if not all(r["status"] == "measured" and approach in r["budgets"] for r in m):
                why = "; ".join(f"{r['frame_id'].split(':')[1]} D{r['detector']}: {r['reason'] if r['status'] != 'measured' else 'no frame tie (' + str(r['n_references']) + ' references)'}"
                               for r in m if r["status"] != "measured" or approach not in r["budgets"])
                pairs.append({"label": band, "approach": approach, "detector": det, "role": role, "status": "not measured", "reason": why})
                continue
            s = pair_stats(m[0], m[1], approach, band)
            s["role"] = role
            consistent = s["p_vs_prediction"] >= P_CONSISTENT
            detected = s["p_vs_zero"] < P_DETECT
            s["status"] = "fail" if not consistent else ("pass" if detected and valid[approach]["passed"] else "inconclusive")
            s["status_reason"] = ("inconsistent with the prediction" if not consistent else
                                  "consistent and detected at >= 5 sigma with a validated budget" if s["status"] == "pass" else
                                  f"consistent; {s['sigma_equiv_vs_zero']:.1f} sigma vs zero" + ("" if valid[approach]["passed"] else "; budget not validated"))
            s["variants"] = {v: pair_stats(m[0], m[1], approach, band, v) for v in VARIANTS}
            pairs.append(s)
    # POST HOC (defined after seeing the stage-2 fit residuals): the catalogued neighbour ~2.9 px away explains the target's chi2;
    # the same pairs with the neighbour-modelled joint fit as the estimator (its own covariance x sqrt(chi2) when > 1; the simulated
    # neighbour term dropped because the neighbour is now modelled; all other terms kept). Does not change the stage-2 conclusion.
    joint_frames = {}
    for r in meas:
        j = (r["variants"].get("neighbours_modelled") or {}).get("joint_fit")
        if not j or j.get("sigma_x") is None:
            continue
        J = np.array(r["jacobian_arcsec_per_px"])
        c = j["corr_xy"] * j["sigma_x"] * j["sigma_y"]
        cov = J @ np.array([[j["sigma_x"] ** 2, c], [c, j["sigma_y"] ** 2]]) @ J.T
        fi = og._frame_inputs(r["frame_id"])
        jx, jy = r["variants"]["neighbours_modelled"]["x"], r["variants"]["neighbours_modelled"]["y"]
        a_, b_ = fi.pixel_to_sky(np.array([jx]), np.array([jy]))
        jb = {}
        for ap, b in r["budgets"].items():
            t = {k: list(v) for k, v in b["terms_arcsec"].items()}
            t["fit"] = [math.sqrt(cov[0, 0]), math.sqrt(cov[1, 1])]
            t["neighbours"] = [0.0, 0.0]
            rnd = [math.hypot(t["fit"][i], t["frame_tie"][i], t["extra_scatter"][i]) for i in (0, 1)]
            sysk = [math.sqrt(sum(t[k][i] ** 2 for k in ("convention_differential", "psf_target", "window_choice", "analysis_choice"))) for i in (0, 1)]
            jb[ap] = {"terms_arcsec": t, "random_arcsec": rnd, "systematic_arcsec": sysk, "total_arcsec": [math.hypot(rnd[i], sysk[i]) for i in (0, 1)]}
        joint_frames[r["frame_id"]] = {**r, "measured": {**r["measured"], "x_px": jx, "y_px": jy, "ra_deg": float(a_[0]), "dec_deg": float(b_[0]),
                                                           "chi2_red": j["chi2_red"]}, "budgets": jb}
    post = {"post_hoc": True, "note": "Estimator: target + catalogued neighbour fitted jointly (neighbour flux free). Defined after the stage-2 residual images "
                                      "showed the unmodelled neighbour; reported for information, not used for the stage-2 conclusion.", "pairs": [], "combined": {}}
    for band in bands:
        m = sorted((joint_frames[r["frame_id"]] for r in frames if r["band_id"] == band and r["frame_id"] in joint_frames), key=lambda r: r["mid_utc"])
        if len(m) != 2 or m[0]["season"] == m[1]["season"]:
            continue
        for approach in ("tied", "untied"):
            if all(approach in r["budgets"] for r in m):
                s = pair_stats(m[0], m[1], approach, band)
                s["role"] = "primary" if m[0]["detector"] in cfg.primary_detectors else "secondary"
                post["pairs"].append(s)
    for approach in ("tied", "untied"):
        prim = [p for p in post["pairs"] if p["approach"] == approach and p["role"] == "primary"]
        if prim:
            c0 = float(sum(p["chi2_vs_zero"] for p in prim))
            cp = float(sum(p["chi2_vs_prediction"] for p in prim))
            w = np.array([1 / p["along_ratio_sigma"] ** 2 for p in prim])
            post["combined"][approach] = {"pairs": [p["label"] for p in prim], "along_ratio": float(np.sum(w * np.array([p["along_ratio"] for p in prim])) / np.sum(w)),
                                          "along_ratio_sigma": float(1 / math.sqrt(np.sum(w))), "dof": 2 * len(prim), "sigma_equiv_vs_zero": sigma_equiv(float(stats.chi2.sf(c0, 2 * len(prim)))),
                                          "p_vs_prediction": float(stats.chi2.sf(cp, 2 * len(prim)))}
    combos = {}
    for approach in ("tied", "untied"):
        prim = [p for p in pairs if p["approach"] == approach and p.get("role") == "primary" and "p_vs_zero" in p]
        if not prim:
            combos[approach] = {"pairs": [], "status": "no primary pair measured"}
            continue
        w = np.array([1 / p["along_ratio_sigma"] ** 2 for p in prim])
        c0 = float(sum(p["chi2_vs_zero"] for p in prim))
        cp = float(sum(p["chi2_vs_prediction"] for p in prim))
        dof = 2 * len(prim)
        robust = {}
        for v in VARIANTS:
            cv = float(sum(p["variants"][v]["chi2_vs_zero"] for p in prim))
            robust[v] = {"chi2_vs_zero": cv, "p_vs_zero": float(stats.chi2.sf(cv, dof)), "sigma_equiv": sigma_equiv(float(stats.chi2.sf(cv, dof)))}
        p0, pp = float(stats.chi2.sf(c0, dof)), float(stats.chi2.sf(cp, dof))
        combos[approach] = {"pairs": [p["label"] for p in prim], "along_ratio": float(np.sum(w * np.array([p["along_ratio"] for p in prim])) / np.sum(w)),
                            "along_ratio_sigma": float(1 / math.sqrt(np.sum(w))), "chi2_vs_zero": c0, "chi2_vs_prediction": cp, "dof": dof,
                            "p_vs_zero": p0, "sigma_equiv_vs_zero": sigma_equiv(p0), "p_vs_prediction": pp, "budget_validated": valid[approach]["passed"],
                            "robust_across_variants": all(r["p_vs_zero"] < P_DETECT for r in robust.values()), "variants": robust}
        combos[approach]["recovered"] = bool(valid[approach]["passed"] and p0 < P_DETECT and pp >= P_CONSISTENT and combos[approach]["robust_across_variants"])
    recovered = any(c.get("recovered") for c in combos.values())
    conclusion = {
        "recovered": recovered,
        "by_approach": {a: c.get("recovered") for a, c in combos.items()},
        "statement": ("SkyShift recovered van Maanen 2's seasonal displacement from SPHEREx pixels: " if recovered else
                      "The motion of van Maanen 2 is not recovered at the required significance: ")
                     + "; ".join(f"{a}: {c.get('along_ratio', float('nan')):.2f} ± {c.get('along_ratio_sigma', float('nan')):.2f} of the Gaia-predicted displacement, "
                                 f"{c.get('sigma_equiv_vs_zero', float('nan')):.1f} sigma vs zero, budget {'validated' if c.get('budget_validated') else 'NOT validated'}"
                                 for a, c in combos.items() if c.get("pairs")) + ".",
    }
    result = {"field": FIELD, "stage": 2, "plan": STAGE2_PLAN, "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "source_hash": source_hash(),
              "method_version": ta.TARGET_ASTROMETRY_VERSION, "config": asdict(cfg), "target": {"name": preset.study_target.name, **ident},
              "gaia_record": {"endpoint": recorded.manifest["endpoint"], "service": (recorded.manifest.get("service") or {}).get("name"),
                              "verification": ((recorded.manifest.get("service") or {}).get("verification") or {}).get("status"),
                              "crosscheck": ((recorded.manifest.get("service") or {}).get("crosscheck") or {}).get("status"),
                              "retrieved_utc": recorded.manifest["retrieved_utc"], "n_rows": recorded.manifest["field_query"]["n_rows"]},
              "alignment": {"n_frames_tied": len(tied_frames), "frame_wcs_rms_arcsec": wcs_rms.tolist(), "pooled_extra_scatter_arcsec": extra_pooled,
                            "pooled_rms_east_north_2d_arcsec": [rep.pooled.rms_east_arcsec, rep.pooled.rms_north_arcsec, rep.pooled.rms_total_arcsec]},
              "frames": frames, "budget_validation": valid, "pairs": pairs, "combined": combos, "conclusion": conclusion,
              "post_hoc_neighbour_modelled": post}
    out = REPO / "validation" / "vanmaanen2_motion_stage2.json"
    out.write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    with (REPO / "validation" / "vanmaanen2_motion_stage2_pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["# measured = derived_measurement (ePSF on native pixels); predicted = model_prediction (Gaia DR3 propagated, geocentric parallax)"])
        w.writerow(["pair", "approach", "role", "detector", "obs_id_season1", "obs_id_season2", "epoch1_utc", "epoch2_utc", "pred_east", "pred_north",
                    "meas_east", "meas_north", "sigma_stat_east", "sigma_stat_north", "sigma_sys_east", "sigma_sys_north", "resid_east", "resid_north",
                    "along_ratio", "along_ratio_sigma", "sigma_vs_zero", "p_vs_prediction", "status", "status_reason"])
        for p in pairs:
            if "p_vs_zero" not in p:
                w.writerow([p["label"], p["approach"], p["role"], p["detector"]] + [""] * 18 + [p["status"], p["reason"]])
                continue
            w.writerow([p["label"], p["approach"], p["role"], p["detector"], *p["observation_ids"], *p["epochs_utc"], *p["predicted_arcsec"], *p["measured_arcsec"],
                        *p["sigma_stat_arcsec"], *p["sigma_sys_arcsec"], *p["residual_arcsec"], p["along_ratio"], p["along_ratio_sigma"],
                        p["sigma_equiv_vs_zero"], p["p_vs_prediction"], p["status"], p["status_reason"]])
    try:
        from plots_target import make_stage2_plots

        make_stage2_plots(result, og, REPO / "validation" / "plots", "vanmaanen2_stage2")
    except ImportError as exc:
        print(f"plots skipped: {exc}", file=sys.stderr)
    for r in frames:
        if r["status"] == "measured":
            print(f"D{r['detector']} {r['mid_utc'][:10]}: analysis-choice RMS {np.round(r['analysis_choice_rms_px'], 4).tolist()} px; variants "
                  + ", ".join(f"{k} {np.round(v['shift_px'], 4).tolist() if v['shift_px'] else None}" for k, v in r["variants"].items())
                  + (f"; features {[(round(f['distance_px'], 1), round(f['peak_snr'], 1), f['flags']) for f in r['uncatalogued_features']]} impact {r['feature_impact']}" if r["uncatalogued_features"] else ""))
        else:
            print(f"D{r['detector']} {r['mid_utc'][:10]}: {r['status']} - {r['reason']}")
    print("budget validation:", json.dumps({k: {kk: v[kk] for kk in ("chi2", "dof", "p", "passed")} for k, v in valid.items()}))
    for p in pairs:
        if "p_vs_zero" in p:
            print(f"{p['label']:6s} {p['approach']:6s} {p['role']:9s}: pred ({p['predicted_arcsec'][0]:+.3f},{p['predicted_arcsec'][1]:+.3f}) meas ({p['measured_arcsec'][0]:+.3f},"
                  f"{p['measured_arcsec'][1]:+.3f}) stat ({p['sigma_stat_arcsec'][0]:.3f},{p['sigma_stat_arcsec'][1]:.3f}) sys ({p['sigma_sys_arcsec'][0]:.3f},{p['sigma_sys_arcsec'][1]:.3f}) "
                  f"ratio {p['along_ratio']:.2f}±{p['along_ratio_sigma']:.2f} {p['sigma_equiv_vs_zero']:.1f}σ p(pred) {p['p_vs_prediction']:.2f} -> {p['status']}")
        else:
            print(f"{p['label']:6s} {p['approach']:6s} {p['role']:9s}: {p['status']} - {p['reason']}")
    print("combined:", json.dumps({a: {k: c.get(k) for k in ("pairs", "along_ratio", "along_ratio_sigma", "sigma_equiv_vs_zero", "p_vs_prediction", "budget_validated", "robust_across_variants", "recovered")} for a, c in combos.items()}, default=float))
    print("conclusion:", conclusion["statement"])
    print("POST HOC neighbour-modelled estimator:")
    for p in post["pairs"]:
        print(f"  {p['label']:6s} {p['approach']:6s} {p['role']:9s}: meas ({p['measured_arcsec'][0]:+.3f},{p['measured_arcsec'][1]:+.3f}) stat ({p['sigma_stat_arcsec'][0]:.3f},"
              f"{p['sigma_stat_arcsec'][1]:.3f}) sys ({p['sigma_sys_arcsec'][0]:.3f},{p['sigma_sys_arcsec'][1]:.3f}) ratio {p['along_ratio']:.2f}±{p['along_ratio_sigma']:.2f} "
              f"{p['sigma_equiv_vs_zero']:.1f}σ p(pred) {p['p_vs_prediction']:.2f}")
    print("  combined:", json.dumps(post["combined"], default=float))
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
