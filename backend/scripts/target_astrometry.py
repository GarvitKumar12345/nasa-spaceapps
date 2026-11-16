"""Measured motion of a known target in SPHEREx frames: a validation study (skyshift.science.target_astrometry).

Steps for the field's study target (default: van Maanen 2 in spherex-dr1-vanmaanen2):
  1. Identify the target in the recorded Gaia DR3 response by propagation: the source predicted within 2" of the
     literature-propagated position at every exposure epoch, with |mu| > 1"/yr. Catalogue-epoch coordinates are
     never matched directly (a 3"/yr star moves ~30" between J2016.0 and 2025.5).
  2. Alignment diagnostics of the field with the target excluded from the references (ObservedGaia report).
  3. Per frame: the Gaia prediction (model_prediction), the stage-1 usability (validation/<field>_stage1.json), the
     ePSF position (derived_measurement), the frame tie from the reference stars, and the per-epoch error budget.
  4. Pairs of one compatibility group spanning both seasons: measured vs predicted displacement.
  5. Zero-displacement tests of the error budget: the same instant on two detectors; one detector two minutes apart.
  6. Decisions by the predefined rules in TargetConfig; D1-D3 primary, D4-D5 secondary, D6 excluded (stage-1 S/N).
Writes validation/<target>_motion.json, validation/<target>_motion_table.csv and validation/plots/<target>_*.png.

Run: cd backend && uv run python scripts/target_astrometry.py [--field spherex-dr1-vanmaanen2]
"""

from __future__ import annotations

import argparse
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

from astropy.time import Time  # noqa: E402

from skyshift.coords.tangent import offsets_mas  # noqa: E402
from skyshift.pipeline.observed_gaia import observed_gaia  # noqa: E402
from skyshift.providers.gaia_dr3 import load_recorded_field  # noqa: E402
from skyshift.providers.spherex import SpherexProvider  # noqa: E402
from skyshift.providers.spherex.fields import PRESETS  # noqa: E402
from skyshift.science import target_astrometry as ta  # noqa: E402
from skyshift.validation.report import source_hash  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def literature_radec(t, jyear: float) -> tuple[float, float]:  # noqa: ANN001 - StudyTarget
    dtyr = jyear - 2000.0
    dec = t.dec_j2000_deg + t.pmdec_arcsec_yr * dtyr / 3600.0
    return (t.ra_j2000_deg + t.pmra_arcsec_yr * dtyr / 3600.0 / math.cos(math.radians(dec))) % 360.0, dec


def identify_target(og, target) -> tuple[str, dict]:  # noqa: ANN001
    """Gaia DR3 source of the target, found by propagation to every exposure epoch (not by catalogue-epoch position)."""
    cols = og.catalog.columns
    pm = np.hypot(np.nan_to_num(cols["pmra"]), np.nan_to_num(cols["pmdec"])) / 1000.0
    hits: dict[str, list[float]] = {}
    for nid in og.obs_by_native:
        pred = og.prediction(nid)
        mid = og.epoch_of(nid)
        ra_l, dec_l = literature_radec(target, float(Time(mid.mjd_tdb, format="mjd", scale="tdb").jyear))
        e, n = offsets_mas(pred.ra_deg, pred.dec_deg, ra_l, dec_l)
        sep = np.hypot(e, n) / 1000.0
        for i in np.flatnonzero((sep < 2.0) & (pm > 1.0)):
            hits.setdefault(og.catalog.source_id[int(i)], []).append(float(sep[i]))
    n_frames = len(og.obs_by_native)
    complete = {k: v for k, v in hits.items() if len(v) == n_frames}
    if len(complete) != 1:
        raise RuntimeError(f"target identification is not unique: {hits}")
    sid = next(iter(complete))
    i = og.catalog.index[sid]
    row = {k: og.catalog.value(k, i) for k in ("ra", "dec", "parallax", "parallax_error", "pmra", "pmra_error", "pmdec", "pmdec_error", "ruwe",
                                               "astrometric_params_solved", "phot_g_mean_mag", "phot_rp_mean_mag", "radial_velocity")}
    catalogue_epoch_sep = float(np.hypot(*offsets_mas(row["ra"], row["dec"], *literature_radec(target, 2016.0))) / 1000.0)
    return sid, {"source_id": sid, "gaia_dr3": row, "max_predicted_separation_from_literature_arcsec": max(complete[sid]),
                 "n_frames_matched": n_frames, "literature_vs_gaia_at_J2016_arcsec": catalogue_epoch_sep,
                 "rule": "unique source predicted within 2\" of the literature-propagated position at every exposure epoch, |mu| > 1\"/yr"}


def neighbours_of(og, nid: str, i_t: int, cfg: ta.TargetConfig) -> list[dict]:  # noqa: ANN001
    pred = og.prediction(nid)
    fi = og._frame_inputs(nid)
    px, py = fi.sky_to_pixel(pred.ra_deg, pred.dec_deg)
    rp, g = np.asarray(og.catalog.columns["phot_rp_mean_mag"], float), np.asarray(og.catalog.columns["phot_g_mean_mag"], float)
    d = np.hypot(px - px[i_t], py - py[i_t])
    out = []
    for j in np.flatnonzero((d < cfg.neighbour_radius_px) & (np.arange(len(d)) != i_t)):
        if np.isfinite(rp[j]) and np.isfinite(rp[i_t]):
            ratio, band = 10 ** (-0.4 * (rp[j] - rp[i_t])), "RP"
        elif np.isfinite(g[j]) and np.isfinite(g[i_t]):
            ratio, band = 10 ** (-0.4 * (g[j] - g[i_t])), "G"
        else:
            continue
        out.append({"source_id": og.catalog.source_id[int(j)], "dx": float(px[j] - px[i_t]), "dy": float(py[j] - py[i_t]), "ratio": float(ratio), "band": band})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--field", default="spherex-dr1-vanmaanen2")
    args = ap.parse_args()
    preset = PRESETS[args.field]
    target = preset.study_target
    if target is None:
        print(f"{args.field} has no study target", file=sys.stderr)
        return 2
    cfg = ta.TargetConfig()
    bundle = SpherexProvider().load_dataset(args.field)
    recorded = load_recorded_field(args.field)  # raises ProviderUnavailable if no verified Gaia DR3 record exists
    og = observed_gaia(bundle, recorded)
    sid, ident = identify_target(og, target)
    if og.cfg.excluded_source_ids != (sid,):
        raise RuntimeError(f"the field's alignment configuration must exclude the target {sid} from its references (got {og.cfg.excluded_source_ids})")
    rep = og.report()
    i_t = og.catalog.index[sid]
    slug = args.field.replace("spherex-dr1-", "")
    stage1 = json.loads((REPO / "validation" / f"{slug}_stage1.json").read_text(encoding="utf-8"))
    usable1 = {f["frame_id"]: f for f in stage1["frames"]}
    frames_by_id = {f.frame_id: f for f in rep.frames}
    rows: list[dict] = []
    for nid in sorted(og.obs_by_native, key=lambda k: (og.images[k].detector, og.epoch_of(k).mjd_tdb)):
        img = og.images[nid]
        obs = og.obs_by_native[nid]
        fa = frames_by_id[nid]
        pred = og.prediction(nid)
        fi = og._frame_inputs(nid)
        xp, yp = fi.sky_to_pixel(np.array([pred.ra_deg[i_t]]), np.array([pred.dec_deg[i_t]]))
        s1 = usable1.get(nid, {})
        row = {"frame_id": nid, "observation_id": obs.id, "obs_id": img.obs_id, "detector": int(img.detector), "band_id": obs.band_id,
               "mid_utc": obs.timing.mid.iso_utc, "season": s1.get("season"),
               "lambda_um": obs.archive.local_wavelength_um if obs.archive else None, "bandwidth_um": obs.archive.local_bandwidth_um if obs.archive else None,
               "stage1_diagnostic_snr": s1.get("diagnostic_snr_3x3"), "stage1_usable": bool(s1.get("usable")),
               "predicted": {"ra_deg": float(pred.ra_deg[i_t]), "dec_deg": float(pred.dec_deg[i_t]), "x_px": float(xp[0]), "y_px": float(yp[0]),
                             "sigma_east_mas": float(pred.sigma_ra_cosdec_mas[i_t]), "sigma_north_mas": float(pred.sigma_dec_mas[i_t]), "origin": "model_prediction"},
               "frame_status": fa.status, "n_references": fa.n_used,
               "provenance": {"spherex_file": obs.archive.file_name if obs.archive else None, "spherex_sha256": obs.archive.sha256 if obs.archive else None,
                              "gaia_endpoint": recorded.manifest["endpoint"], "gaia_retrieved_utc": recorded.manifest["retrieved_utc"],
                              "gaia_response_sha256_gz": recorded.manifest["field_query"]["response_sha256_gz"]}}
        if int(img.detector) == 6 or not row["stage1_usable"]:
            row.update(status="rejected", reason=f"stage-1 criteria not met ({s1.get('reason', 'no stage-1 record')})")
            rows.append(row)
            continue
        nbs = neighbours_of(og, nid, i_t, cfg)
        fit = ta.fit_target(fi, float(xp[0]), float(yp[0]), nbs, cfg)
        row["fit"] = {k: v for k, v in asdict(fit).items() if k != "neighbours"}
        row["neighbours"] = nbs
        if fit.status != "ok":
            row.update(status="rejected", reason=fit.reason)
            rows.append(row)
            continue
        ra_m, dec_m = fi.pixel_to_sky(np.array([fit.x]), np.array([fit.y]))
        e, n = offsets_mas(float(ra_m[0]), float(dec_m[0]), float(pred.ra_deg[i_t]), float(pred.dec_deg[i_t]))
        row["measured"] = {"x_px": fit.x, "y_px": fit.y, "sigma_x_px": fit.sigma_x, "sigma_y_px": fit.sigma_y, "ra_deg": float(ra_m[0]), "dec_deg": float(dec_m[0]),
                           "chi2_red": fit.chi2_red, "snr": fit.snr, "origin": "derived_measurement"}
        row["residual_vs_prediction_arcsec"] = [float(e) / 1000.0, float(n) / 1000.0]
        t = fa.translation
        if fa.status != "ok" or not t.evaluated:
            row.update(status="rejected", reason=f"frame tie unavailable ({fa.status}; {fa.n_used} references)")
            rows.append(row)
            continue
        diag, _ = og.diagnosis(nid)
        ref_zones = [r.zone for r in diag.used if r.zone is not None]
        conv = ta.convention_differential_px(fi, fit.zone, ref_zones)
        J = og._sky_jacobian(nid)
        budget = ta.epoch_budget(fit, (t.sigma_random_east_arcsec, t.sigma_random_north_arcsec), float(fa.statistics.extra_scatter_arcsec or 0.0), conv, J)
        row["frame_offset_arcsec"] = [t.offset_east_arcsec, t.offset_north_arcsec]
        row["frame_offset_sigma_random_arcsec"] = [t.sigma_random_east_arcsec, t.sigma_random_north_arcsec]
        row["tied_residual_arcsec"] = [row["residual_vs_prediction_arcsec"][0] - t.offset_east_arcsec, row["residual_vs_prediction_arcsec"][1] - t.offset_north_arcsec]
        row["budget"] = budget
        row.update(status="measured", reason="measured")
        rows.append(row)
    by_id = {r["frame_id"]: r for r in rows}

    def pair_result(a: dict, b: dict, label: str, kind: str) -> dict:
        ea, eb = np.array(a["tied_residual_arcsec"]), np.array(b["tied_residual_arcsec"])
        sa, sb = np.array(a["budget"]["total_arcsec"]), np.array(b["budget"]["total_arcsec"])
        ra_, rb_ = np.array(a["budget"]["random_arcsec"]), np.array(b["budget"]["random_arcsec"])
        pe, pn = offsets_mas(b["predicted"]["ra_deg"], b["predicted"]["dec_deg"], a["predicted"]["ra_deg"], a["predicted"]["dec_deg"])
        pred_d = np.array([float(pe), float(pn)]) / 1000.0
        dres, sig = ta.displacement(ea, eb, sa, sb)
        # measured displacement from the two measured positions only, minus the change of the frames' reference offsets
        me, mn = offsets_mas(b["measured"]["ra_deg"], b["measured"]["dec_deg"], a["measured"]["ra_deg"], a["measured"]["dec_deg"])
        raw_d = np.array([float(me), float(mn)]) / 1000.0
        meas_d = raw_d - (np.array(b["frame_offset_arcsec"]) - np.array(a["frame_offset_arcsec"]))
        if np.max(np.abs(meas_d - (pred_d + dres))) > 1e-4:  # the two ways of writing it agree (small-angle algebra)
            raise RuntimeError(f"displacement bookkeeping inconsistent for {label}: {meas_d} vs {pred_d + dres}")
        _, sig_rand = ta.displacement(ea, eb, ra_, rb_)
        c0, p0 = ta.chi2_2d(meas_d, sig)
        cp, pp = ta.chi2_2d(dres, sig)
        out = {"label": label, "kind": kind, "from": a["frame_id"], "to": b["frame_id"], "from_utc": a["mid_utc"], "to_utc": b["mid_utc"],
               "interval_days": (Time(b["mid_utc"]).mjd - Time(a["mid_utc"]).mjd), "detectors": [a["detector"], b["detector"]],
               "predicted_arcsec": pred_d.tolist(), "measured_arcsec": meas_d.tolist(), "measured_uncorrected_archive_wcs_arcsec": raw_d.tolist(),
               "measured_minus_predicted_arcsec": dres.tolist(),
               "sigma_total_arcsec": sig.tolist(), "sigma_random_arcsec": sig_rand.tolist(),
               "chi2_vs_zero": c0, "p_vs_zero": p0, "chi2_vs_prediction": cp, "p_vs_prediction": pp,
               "predicted_length_arcsec": float(np.linalg.norm(pred_d)), "measured_length_arcsec": float(np.linalg.norm(meas_d))}
        if np.linalg.norm(pred_d) > 0.1:
            k, sk, perp, sperp = ta.along_ratio(meas_d, pred_d, sig)
            out.update(along_ratio=k, along_ratio_sigma=sk, perpendicular_arcsec=perp, perpendicular_sigma_arcsec=sperp)
        return out

    # motion pairs: one compatibility group spanning both seasons
    pairs = []
    for band in sorted({r["band_id"] for r in rows if r["band_id"]}):
        members = sorted((r for r in rows if r["band_id"] == band), key=lambda r: r["mid_utc"])
        if len(members) != 2 or members[0]["season"] == members[1]["season"]:
            continue
        det = members[0]["detector"]
        role = "primary" if det in cfg.primary_detectors else "secondary" if det in cfg.secondary_detectors else "excluded"
        if all(m["status"] == "measured" for m in members):
            pairs.append({**pair_result(members[0], members[1], band, "motion"), "role": role})
        else:
            pairs.append({"label": band, "kind": "motion", "role": "excluded" if role == "excluded" else role, "detectors": [det, det],
                          "status": "not measured", "reason": "; ".join(f"{m['frame_id']}: {m['reason']}" for m in members if m["status"] != "measured")})
    # zero-displacement pairs (tests of the error budget)
    nulls = []
    measured = [r for r in rows if r["status"] == "measured"]
    for a in measured:
        for b in measured:
            if a["frame_id"] >= b["frame_id"]:
                continue
            same_instant = a["obs_id"] == b["obs_id"] and a["detector"] != b["detector"]
            minutes = abs(Time(a["mid_utc"]).mjd - Time(b["mid_utc"]).mjd) * 1440.0
            same_detector_minutes = a["detector"] == b["detector"] and minutes < 10.0
            if same_instant or same_detector_minutes:
                kind = "same exposure, two detectors" if same_instant else f"same detector, {minutes:.1f} min apart"
                nulls.append(pair_result(a, b, f"{a['obs_id']} D{a['detector']} vs D{b['detector']}" if same_instant else f"D{a['detector']} {minutes:.1f} min", kind))
    null_chi2 = float(sum(p["chi2_vs_prediction"] for p in nulls))
    null_dof = 2 * len(nulls)
    from scipy import stats

    null_p = float(stats.chi2.sf(null_chi2, null_dof)) if null_dof else None
    budget_supported = bool(null_dof and null_p is not None and null_p >= cfg.null_test_p)
    # primary combination: independent exposures (D1-D3 pairs use different exposures)
    prim = [p for p in pairs if p.get("role") == "primary" and "along_ratio" in p]
    combo = None
    if prim:
        w = np.array([1.0 / p["along_ratio_sigma"] ** 2 for p in prim])
        k = float(np.sum(w * np.array([p["along_ratio"] for p in prim])) / np.sum(w))
        sk = float(1.0 / math.sqrt(np.sum(w)))
        chi2_pred = float(sum(p["chi2_vs_prediction"] for p in prim))
        chi2_zero = float(sum(p["chi2_vs_zero"] for p in prim))
        combo = {"pairs": [p["label"] for p in prim], "along_ratio": k, "along_ratio_sigma": sk,
                 "chi2_vs_prediction": chi2_pred, "dof": 2 * len(prim), "p_vs_prediction": float(stats.chi2.sf(chi2_pred, 2 * len(prim))),
                 "chi2_vs_zero": chi2_zero, "p_vs_zero": float(stats.chi2.sf(chi2_zero, 2 * len(prim)))}
    decision = {
        "budget_supported_by_zero_displacement_tests": budget_supported,
        "null_chi2": null_chi2, "null_dof": null_dof, "null_p": null_p, "null_scale_factor": math.sqrt(null_chi2 / null_dof) if null_dof else None,
        "motion_detected": bool(budget_supported and combo and combo["p_vs_zero"] < cfg.detection_p),
        "consistent_with_prediction": bool(combo and combo["p_vs_prediction"] >= cfg.consistency_p) if combo else None,
        "rules": {"detection": f"primary pairs combined, p vs zero < {cfg.detection_p:.2g} (5 sigma), only if the zero-displacement tests support the budget (p >= {cfg.null_test_p})",
                  "consistency": f"primary pairs combined, p vs prediction >= {cfg.consistency_p}", "primary": "D1-D3 pairs; D4-D5 secondary; D6 excluded (stage-1 S/N)"},
    }
    if not budget_supported:
        decision["statement"] = "Zero-displacement tests do not support the error budget: no significance is quoted; measured displacements are reported with the budget as is."
    result = {"field": args.field, "target": {"name": target.name, **ident}, "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
              "source_hash": source_hash(), "method_version": ta.TARGET_ASTROMETRY_VERSION, "config": asdict(cfg),
              "gaia_record": {"endpoint": recorded.manifest["endpoint"], "service": recorded.manifest.get("service", {}).get("name"),
                              "retrieved_utc": recorded.manifest["retrieved_utc"], "n_rows": recorded.manifest["field_query"]["n_rows"],
                              "verification": (recorded.manifest.get("service") or {}).get("verification", {}).get("status"),
                              "crosscheck": ((recorded.manifest.get("service") or {}).get("crosscheck") or {}).get("status")},
              "alignment": {"status": rep.status, "n_frames_ok": rep.n_frames_ok, "convention_test": rep.convention_test.decision,
                            "pooled_rms_east_north_2d_arcsec": [rep.pooled.rms_east_arcsec, rep.pooled.rms_north_arcsec, rep.pooled.rms_total_arcsec] if rep.pooled and rep.pooled.n else None,
                            "frames": [{"frame_id": f.frame_id, "detector": f.detector, "status": f.status, "n_used": f.n_used,
                                        "offset_arcsec": [f.translation.offset_east_arcsec, f.translation.offset_north_arcsec] if f.translation.evaluated else None,
                                        "p_total": f.translation.p_value if f.translation.evaluated else None, "estimator_passed": bool(f.estimator and f.estimator.passed)}
                                       for f in rep.frames]},
              "frames": rows, "pairs": pairs, "zero_displacement_tests": nulls, "primary_combination": combo, "decision": decision,
              "sensitivity_post_hoc": sensitivity(rows, og, rep, cfg, i_t)}
    out_json = REPO / "validation" / f"{slug}_motion.json"
    out_json.write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    write_table(rows, REPO / "validation" / f"{slug}_motion_table.csv")
    try:
        from plots_target import make_plots  # noqa: PLC0415 - optional (matplotlib is a dev dependency)

        make_plots(result, og, REPO / "validation" / "plots", slug)
    except ImportError as exc:
        print(f"plots skipped: {exc}", file=sys.stderr)
    summarize(result)
    print(f"wrote {out_json.relative_to(REPO)}")
    return 0


def sensitivity(rows: list[dict], og, rep, cfg: ta.TargetConfig, i_t: int) -> dict:  # noqa: ANN001
    """POST HOC analyses, defined after the primary run (they never change the primary rows, pairs or decision).

    (a) Frames rejected by the start criterion: the same starts inside the primary fit's window, separating start
        dependence from the choice of fit window (fit_position centres its window on the rounded start).
    (b) Untied positions (archive WCS, no reference-star tie) for every frame with a converged fit, so that the
        same-instant pairs (D1/D4, D2/D5) and the two-minute D1 pair exist as zero-displacement tests. Per-epoch
        budget: fit sigma, the field's frame-offset RMS (archive-WCS error, conservative: includes its own noise), the
        pooled extra scatter, the target zone's full centroid-convention term (not cancelled without a tie), the
        target's PSF and neighbour terms, and the RMS shift over the fit windows the offset starts select."""
    from scipy import stats

    ok_frames = [f for f in rep.frames if f.status == "ok" and f.translation.evaluated]
    offs = np.array([[f.translation.offset_east_arcsec, f.translation.offset_north_arcsec] for f in ok_frames])
    wcs_rms = np.sqrt(np.mean(offs**2, axis=0)) if len(offs) else np.array([np.nan, np.nan])
    extra = float(rep.pooled.extra_scatter_arcsec or 0.0) if rep.pooled else 0.0
    window = []
    untied: dict[str, dict] = {}
    for r in rows:
        fit = r.get("fit")
        if not fit or fit.get("x") is None or r["detector"] == 6 or not r["stage1_usable"]:
            continue
        if fit["status"] != "ok" and "starting point" in r["reason"]:
            window.append({"frame_id": r["frame_id"], "start_spread_px": fit["start_spread_px"], "start_spread_fixed_window_px": fit["start_spread_fixed_window_px"],
                           "window_choice_rms_px": fit["window_choice_rms_px"], "sigma_px": [fit["sigma_x"], fit["sigma_y"]]})
        if fit["status"] != "ok" and "starting point" not in r["reason"]:
            continue
        fi = og._frame_inputs(r["frame_id"])
        ra_m, dec_m = fi.pixel_to_sky(np.array([fit["x"]]), np.array([fit["y"]]))
        e, n = offsets_mas(float(ra_m[0]), float(dec_m[0]), r["predicted"]["ra_deg"], r["predicted"]["dec_deg"])
        J = og._sky_jacobian(r["frame_id"])
        tf = ta.TargetFit(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in fit.items()})
        conv = ta.convention_differential_px(fi, fit["zone"], [])  # the target zone's own convention size (no tie to cancel it)
        b = ta.epoch_budget(tf, tuple(wcs_rms), extra, conv, J)
        wc = np.asarray(fit["window_choice_rms_px"] or (0.0, 0.0))
        wsky = np.sqrt((J**2) @ (wc**2))
        tot = [math.hypot(b["total_arcsec"][i], float(wsky[i])) for i in (0, 1)]
        untied[r["frame_id"]] = {**r, "measured": {"ra_deg": float(ra_m[0]), "dec_deg": float(dec_m[0]), "x_px": fit["x"], "y_px": fit["y"]},
                                 "residual_vs_prediction_arcsec": [float(e) / 1000.0, float(n) / 1000.0], "budget": {**b, "total_arcsec": tot},
                                 "window_choice_arcsec": wsky.tolist(), "frame_wcs_term_arcsec": wcs_rms.tolist()}

    def upair(a: dict, c: dict, label: str, kind: str) -> dict:
        pe, pn = offsets_mas(c["predicted"]["ra_deg"], c["predicted"]["dec_deg"], a["predicted"]["ra_deg"], a["predicted"]["dec_deg"])
        me, mn = offsets_mas(c["measured"]["ra_deg"], c["measured"]["dec_deg"], a["measured"]["ra_deg"], a["measured"]["dec_deg"])
        pred, meas = np.array([pe, pn]) / 1000.0, np.array([me, mn]) / 1000.0
        sig = np.hypot(np.array(a["budget"]["total_arcsec"]), np.array(c["budget"]["total_arcsec"]))
        c0, p0 = ta.chi2_2d(meas, sig)
        cp, pp = ta.chi2_2d(meas - pred, sig)
        out = {"label": label, "kind": kind, "detectors": [a["detector"], c["detector"]], "from_utc": a["mid_utc"], "to_utc": c["mid_utc"],
               "predicted_arcsec": pred.tolist(), "measured_arcsec": meas.tolist(), "sigma_total_arcsec": sig.tolist(),
               "chi2_vs_zero": c0, "p_vs_zero": p0, "chi2_vs_prediction": cp, "p_vs_prediction": pp}
        if np.linalg.norm(pred) > 0.1:
            k, sk, perp, sperp = ta.along_ratio(meas, pred, sig)
            out.update(along_ratio=k, along_ratio_sigma=sk, perpendicular_arcsec=perp, perpendicular_sigma_arcsec=sperp)
        return out

    rows_u = sorted(untied.values(), key=lambda r: (r["detector"], r["mid_utc"]))
    nulls, pairs = [], []
    for a in rows_u:
        for c in rows_u:
            if a["frame_id"] >= c["frame_id"]:
                continue
            minutes = abs(Time(a["mid_utc"]).mjd - Time(c["mid_utc"]).mjd) * 1440.0
            if a["obs_id"] == c["obs_id"] and a["detector"] != c["detector"]:
                nulls.append(upair(a, c, f"{a['obs_id']} D{a['detector']} vs D{c['detector']}", "same exposure, two detectors"))
            elif a["detector"] == c["detector"] and minutes < 10.0:
                nulls.append(upair(a, c, f"D{a['detector']} {minutes:.1f} min apart", "same detector, minutes apart"))
    for band in sorted({r["band_id"] for r in rows_u}):
        m = sorted((r for r in rows_u if r["band_id"] == band), key=lambda r: r["mid_utc"])
        if len(m) == 2 and m[0]["season"] != m[1]["season"]:
            pairs.append({**upair(m[0], m[1], band, "motion (untied)"), "role": "primary" if m[0]["detector"] in cfg.primary_detectors else "secondary"})
    nchi = float(sum(p["chi2_vs_prediction"] for p in nulls))
    ndof = 2 * len(nulls)
    prim = [p for p in pairs if p["role"] == "primary" and "along_ratio" in p]
    combo = None
    if prim:
        w = np.array([1 / p["along_ratio_sigma"] ** 2 for p in prim])
        k = float(np.sum(w * np.array([p["along_ratio"] for p in prim])) / np.sum(w))
        combo = {"pairs": [p["label"] for p in prim], "along_ratio": k, "along_ratio_sigma": float(1 / math.sqrt(np.sum(w))),
                 "chi2_vs_zero": float(sum(p["chi2_vs_zero"] for p in prim)), "chi2_vs_prediction": float(sum(p["chi2_vs_prediction"] for p in prim)),
                 "dof": 2 * len(prim)}
        combo["p_vs_zero"] = float(stats.chi2.sf(combo["chi2_vs_zero"], combo["dof"]))
        combo["p_vs_prediction"] = float(stats.chi2.sf(combo["chi2_vs_prediction"], combo["dof"]))
    return {"post_hoc": True, "note": " ".join(sensitivity.__doc__.split()),
            "start_window_diagnosis": window,
            "untied": {"frame_wcs_term_arcsec": wcs_rms.tolist(), "extra_scatter_arcsec": extra,
                       "frames": [{"frame_id": r["frame_id"], "detector": r["detector"], "mid_utc": r["mid_utc"], "residual_vs_prediction_arcsec": r["residual_vs_prediction_arcsec"],
                                   "sigma_total_arcsec": r["budget"]["total_arcsec"], "terms_arcsec": r["budget"]["terms_arcsec"], "window_choice_arcsec": r["window_choice_arcsec"]}
                                  for r in rows_u],
                       "zero_displacement_tests": nulls, "null_chi2": nchi, "null_dof": ndof,
                       "null_p": float(stats.chi2.sf(nchi, ndof)) if ndof else None, "pairs": pairs, "primary_combination": combo}}


def write_table(rows: list[dict], path: Path) -> None:
    cols = ["observation_id", "frame_id", "detector", "band_id", "mid_utc", "season", "lambda_um", "stage1_diagnostic_snr", "status", "reason",
            "pred_ra_deg", "pred_dec_deg", "pred_x_px", "pred_y_px", "meas_x_px", "meas_y_px", "sigma_x_px", "sigma_y_px", "meas_ra_deg", "meas_dec_deg",
            "chi2_red", "resid_east_arcsec", "resid_north_arcsec", "frame_offset_east_arcsec", "frame_offset_north_arcsec", "n_references",
            "tied_resid_east_arcsec", "tied_resid_north_arcsec", "sigma_total_east_arcsec", "sigma_total_north_arcsec", "gaia_endpoint", "gaia_retrieved_utc"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["# origin: pred_* = model_prediction (Gaia DR3 propagated to the exposure, geocentric parallax); meas_* = derived_measurement (ePSF fit, native pixels)"])
        w.writerow(cols)
        for r in rows:
            m, p = r.get("measured") or {}, r["predicted"]
            g = lambda d, k, i=None: (d.get(k)[i] if i is not None and d.get(k) else d.get(k)) if d else None  # noqa: E731
            w.writerow([r["observation_id"], r["frame_id"], r["detector"], r["band_id"], r["mid_utc"], r["season"], r["lambda_um"], r["stage1_diagnostic_snr"],
                        r["status"], r["reason"], p["ra_deg"], p["dec_deg"], p["x_px"], p["y_px"], m.get("x_px"), m.get("y_px"), m.get("sigma_x_px"), m.get("sigma_y_px"),
                        m.get("ra_deg"), m.get("dec_deg"), m.get("chi2_red"), g(r, "residual_vs_prediction_arcsec", 0), g(r, "residual_vs_prediction_arcsec", 1),
                        g(r, "frame_offset_arcsec", 0), g(r, "frame_offset_arcsec", 1), r["n_references"], g(r, "tied_residual_arcsec", 0), g(r, "tied_residual_arcsec", 1),
                        (r.get("budget") or {}).get("total_arcsec", [None, None])[0], (r.get("budget") or {}).get("total_arcsec", [None, None])[1],
                        r["provenance"]["gaia_endpoint"], r["provenance"]["gaia_retrieved_utc"]])


def summarize(res: dict) -> None:
    t = res["target"]
    print(f"target {t['name']} = Gaia DR3 {t['source_id']} (pm {t['gaia_dr3']['pmra']:.1f}, {t['gaia_dr3']['pmdec']:.1f} mas/yr; plx {t['gaia_dr3']['parallax']:.2f} mas; "
          f"RUWE {t['gaia_dr3']['ruwe']:.2f})")
    for r in res["frames"]:
        if r["status"] == "measured":
            b = r["budget"]["total_arcsec"]
            print(f"  D{r['detector']} {r['mid_utc'][:16]} {r['band_id']:>10}: tied residual ({r['tied_residual_arcsec'][0]:+.3f}, {r['tied_residual_arcsec'][1]:+.3f}) "
                  f"± ({b[0]:.3f}, {b[1]:.3f})\"  fit sigma ({r['measured']['sigma_x_px']:.3f}, {r['measured']['sigma_y_px']:.3f}) px chi2 {r['measured']['chi2_red']:.1f} "
                  f"refs {r['n_references']}")
        else:
            print(f"  D{r['detector']} {r['mid_utc'][:16]} {r['band_id']:>10}: {r['status']} - {r['reason']}")
    for p in res["pairs"]:
        if "measured_arcsec" in p:
            print(f"  pair {p['label']} [{p['role']}] {p['interval_days']:.0f} d: predicted ({p['predicted_arcsec'][0]:+.3f}, {p['predicted_arcsec'][1]:+.3f}) "
                  f"measured ({p['measured_arcsec'][0]:+.3f}, {p['measured_arcsec'][1]:+.3f}) ± ({p['sigma_total_arcsec'][0]:.3f}, {p['sigma_total_arcsec'][1]:.3f})\"; "
                  f"along ratio {p.get('along_ratio', float('nan')):.3f} ± {p.get('along_ratio_sigma', float('nan')):.3f}; p(vs pred) {p['p_vs_prediction']:.3g}")
        else:
            print(f"  pair {p['label']} [{p['role']}]: {p['status']} - {p['reason']}")
    for p in res["zero_displacement_tests"]:
        print(f"  null {p['label']} ({p['kind']}): measured-predicted ({p['measured_minus_predicted_arcsec'][0]:+.3f}, {p['measured_minus_predicted_arcsec'][1]:+.3f}) "
              f"± ({p['sigma_total_arcsec'][0]:.3f}, {p['sigma_total_arcsec'][1]:.3f})\"; chi2 {p['chi2_vs_prediction']:.2f}")
    print("  primary combination:", json.dumps(res["primary_combination"]))
    print("  decision:", json.dumps(res["decision"]))
    s = res["sensitivity_post_hoc"]
    print("POST HOC sensitivity (does not change the decision):")
    for w in s["start_window_diagnosis"]:
        print(f"  {w['frame_id'].split(':')[1]} D: start spread {w['start_spread_px']:.4f} px with re-centred windows, {w['start_spread_fixed_window_px']:.2e} px in one window; "
              f"window-choice RMS {w['window_choice_rms_px']} px vs sigma {w['sigma_px']}")
    u = s["untied"]
    print(f"  untied: frame-WCS term {u['frame_wcs_term_arcsec']}, extra scatter {u['extra_scatter_arcsec']:.3f}\"")
    for p in u["zero_displacement_tests"]:
        print(f"  null {p['label']}: measured-predicted ({p['measured_arcsec'][0]-p['predicted_arcsec'][0]:+.3f}, {p['measured_arcsec'][1]-p['predicted_arcsec'][1]:+.3f}) "
              f"± ({p['sigma_total_arcsec'][0]:.3f}, {p['sigma_total_arcsec'][1]:.3f})\"; chi2 {p['chi2_vs_prediction']:.2f}")
    print(f"  null chi2 {u['null_chi2']:.2f} / {u['null_dof']} dof, p {u['null_p']}")
    for p in u["pairs"]:
        print(f"  untied pair {p['label']} [{p['role']}]: predicted ({p['predicted_arcsec'][0]:+.3f}, {p['predicted_arcsec'][1]:+.3f}) measured ({p['measured_arcsec'][0]:+.3f}, "
              f"{p['measured_arcsec'][1]:+.3f}) ± ({p['sigma_total_arcsec'][0]:.3f}, {p['sigma_total_arcsec'][1]:.3f}); ratio {p.get('along_ratio', float('nan')):.3f} ± "
              f"{p.get('along_ratio_sigma', float('nan')):.3f}; p(vs pred) {p['p_vs_prediction']:.3g}")
    print("  untied primary combination:", json.dumps(u["primary_combination"]))


if __name__ == "__main__":
    raise SystemExit(main())
