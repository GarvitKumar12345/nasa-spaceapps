"""Estimator review: the ePSF position estimator on real SPHEREx reference stars and under controlled injections.

Writes validation/estimator_review.json (and prints a summary). Sections:

  documentation_parity   ePSF evaluation vs photutils ImagePSF; zone choice vs the IRSA tutorial rule (nearest
                         XCENTER/YCENTER); detector coordinates vs the tutorial formula 1 + x_cutout - CRPIX1A;
                         stored normalisation.
  pixel_integration      every used reference refitted with the ePSF integrated once more over a native pixel
                         (tests whether the stored ePSF already contains the pixel response).
  real_residuals         per-reference rows (detector, zone, detector position, sub-pixel phase, S/N, chi2,
                         residuals) and aggregates by detector, S/N, G, phase and zone position; pixel-phase
                         (S-curve) fits; chi2 growth law; stacked residual images.
  neighbours             Gaia neighbours of every used reference and the shift they induce in a simulated fit
                         rendered independently with photutils ImagePSF (no pipeline rendering code).
  sky_fixed_structure    high-pass pixels (Gaia stars masked) correlated between epochs of one compatibility group:
                         structure that VARIANCE does not describe and that is fixed on the sky (faint sources).
  zone_swap_injection    sources rendered with one zone's ePSF (photutils) and fitted with an adjacent zone's model.
  stress_matrix          analytic PSFs integrated over each pixel (independent renderer) fitted with an ePSF built
                         from the nominal PSF: PSF shape, phase, brightness, background, masks, neighbours.
  detectability          illustrative 5-sigma displacement thresholds from a reference-star error-budget model.
  detector_frame_offsets per-frame mean residuals in detector pixels (from the alignment report).

Nothing here changes a measurement: it describes the estimator. Needs the SPHEREx cutout cache and the
committed Gaia DR3 fixture; nothing is downloaded.

Run: cd backend && uv run python scripts/estimator_review.py [--quick]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
import warnings
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter

warnings.simplefilter("ignore")

from skyshift.imaging.epsf import EPSFModel, fit_position  # noqa: E402
from skyshift.pipeline.observed_gaia import observed_gaia  # noqa: E402
from skyshift.providers.gaia_dr3 import load_recorded_field  # noqa: E402
from skyshift.providers.spherex import SpherexProvider  # noqa: E402
from skyshift.science import estimator_stress as es  # noqa: E402
from skyshift.science.alignment import diagnose_frame, excluded_mask  # noqa: E402
from skyshift.validation.report import source_hash  # noqa: E402

FIELD = "spherex-dr1-barnard"
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "validation" / "estimator_review.json"


def _imagepsf(arr: np.ndarray, oversampling: tuple[int, int]):  # noqa: ANN202
    from photutils.psf import ImagePSF

    ox, oy = oversampling
    return ImagePSF(data=arr * float(ox * oy), oversampling=(oy, ox))  # photutils order (y, x)


def _rms(a: np.ndarray) -> float | None:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.sqrt(np.mean(a * a))) if a.size else None


def _robust(a: np.ndarray) -> float | None:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(1.4826 * np.median(np.abs(a - np.median(a)))) if a.size else None


def _wfit_scurve(phase: np.ndarray, res: np.ndarray, sig: np.ndarray) -> dict:
    """Weighted fit res = c + a sin(2 pi phase) + b cos(2 pi phase): the classic pixel-phase error."""
    A = np.column_stack([np.ones_like(phase), np.sin(2 * np.pi * phase), np.cos(2 * np.pi * phase)])
    w = 1.0 / sig
    coef, *_ = np.linalg.lstsq(A * w[:, None], res * w, rcond=None)
    cov = np.linalg.inv((A * w[:, None]).T @ (A * w[:, None]))
    chi2 = float(np.sum(((res - A @ coef) * w) ** 2))
    dof = len(res) - 3
    cov = cov * max(1.0, chi2 / dof)
    return {"n": int(len(res)), "const_px": float(coef[0]), "sin_amp_px": float(coef[1]), "sin_amp_sigma_px": float(math.sqrt(cov[1, 1])),
            "cos_amp_px": float(coef[2]), "cos_amp_sigma_px": float(math.sqrt(cov[2, 2]))}


def collect(og, rep) -> tuple[list[dict], dict, dict, list[dict]]:  # noqa: ANN001
    ok_frames = {f.frame_id for f in rep.frames if f.status == "ok"}
    cat = og.catalog.columns
    rows: list[dict] = []
    parity = {"photutils_max_abs_diff_rel_peak": 0.0, "zones_compared": 0, "zone_choice_checked": 0, "zone_choice_mismatch": 0,
              "detector_coord_max_abs_diff_px": 0.0, "oversampled_sum_range": [math.inf, -math.inf], "native_sum_scaled_range": [math.inf, -math.inf]}
    stacks: dict[int, list[np.ndarray]] = {d: [] for d in range(1, 7)}
    zswap: list[dict] = []
    for nid, img in og.images.items():
        fi = og._frame_inputs(nid)
        lib = fi.epsf
        ox_det, oy_det = fi.detector_offset
        # --- documentation parity on this file's (trimmed) EPSF table
        g = np.linspace(-3.4, 3.4, 23)
        X, Y = np.meshgrid(g + 0.137, g - 0.291)
        for zi in range(len(lib.zones)):
            ours = lib.model(zi).evaluate(X, Y)
            theirs = _imagepsf(lib.arrays[zi], lib.oversampling).evaluate(X, Y, flux=1.0, x_0=0.0, y_0=0.0)
            parity["photutils_max_abs_diff_rel_peak"] = max(parity["photutils_max_abs_diff_rel_peak"], float(np.max(np.abs(ours - theirs)) / np.max(ours)))
            parity["zones_compared"] += 1
        xs = np.array([z.x_center for z in lib.zones])
        ys = np.array([z.y_center for z in lib.zones])
        ny, nx = fi.image.shape
        for cx in np.arange(0, nx, 3.0):
            for cy in np.arange(0, ny, 3.0):
                dx, dy = cx + ox_det, cy + oy_det
                k = lib.zone_index(dx, dy)
                k2 = int(np.argmin(np.hypot(xs - dx, ys - dy)))
                parity["zone_choice_checked"] += 1
                parity["zone_choice_mismatch"] += int(k != k2)
        h = img.image_header
        if "CRPIX1A" in h and "CRPIX2A" in h:
            for cx, cy in ((0.0, 0.0), (nx - 1.0, ny - 1.0)):
                parity["detector_coord_max_abs_diff_px"] = max(parity["detector_coord_max_abs_diff_px"],
                                                               abs((1 + cx - h["CRPIX1A"]) - (cx + ox_det)), abs((1 + cy - h["CRPIX2A"]) - (cy + oy_det)))
        sc = lib.native_sum_check()
        parity["oversampled_sum_range"] = [min(parity["oversampled_sum_range"][0], sc["oversampled_sum_min"]), max(parity["oversampled_sum_range"][1], sc["oversampled_sum_max"])]
        parity["native_sum_scaled_range"] = [min(parity["native_sum_scaled_range"][0], sc["native_sum_scaled_min"]), max(parity["native_sum_scaled_range"][1], sc["native_sum_scaled_max"])]

        # --- real references of this frame
        pred = og.prediction(nid)
        ci = og._catalog_inputs(pred)
        diag = diagnose_frame(fi, ci, og.cfg)
        bad = (fi.flags.astype(np.int64) & excluded_mask(fi.flag_masks)) != 0
        image, var = np.asarray(fi.image, float), np.asarray(fi.variance, float)
        J = og._sky_jacobian(nid)
        Ji = np.linalg.inv(J)
        px_all, py_all = fi.sky_to_pixel(pred.ra_deg, pred.dec_deg)
        g_all, rp_all = np.asarray(cat["phot_g_mean_mag"], float), np.asarray(cat["phot_rp_mean_mag"], float)
        for r in diag.used:
            z = lib.zones[r.zone]
            m = lib.model(r.zone)
            integ = EPSFModel(uniform_filter(lib.arrays[r.zone], size=5, mode="constant"), lib.oversampling)
            f_int = fit_position(image, var, bad, integ, r.x_pred, r.y_pred, half_window=og.cfg.half_window)
            res_px = Ji @ np.array([r.d_east_arcsec, r.d_north_arcsec])
            sig_px = (r.sigma_x, r.sigma_y)
            i = r.index
            # Gaia neighbours within 4.5 px (any magnitude) at this epoch
            d = np.hypot(px_all - r.x_pred, py_all - r.y_pred)
            nb = np.flatnonzero((d < 4.5) & (np.arange(len(d)) != i))
            nbrs = []
            for j in nb:
                if np.isfinite(rp_all[j]) and np.isfinite(rp_all[i]):
                    ratio, band = 10 ** (-0.4 * (rp_all[j] - rp_all[i])), "RP"
                elif np.isfinite(g_all[j]) and np.isfinite(g_all[i]):
                    ratio, band = 10 ** (-0.4 * (g_all[j] - g_all[i])), "G"
                else:
                    continue
                nbrs.append({"dx": float(px_all[j] - r.x_pred), "dy": float(py_all[j] - r.y_pred), "ratio": float(ratio), "band": band})
            # stacked residual (flux-normalised, re-centred on the nearest pixel to the fit)
            ix, iy = int(round(r.x_pred)), int(round(r.y_pred))
            fit = fit_position(image, var, bad, m, r.x_pred, r.y_pred, half_window=og.cfg.half_window)
            if fit.status == "ok":
                yy, xx = np.mgrid[iy - 3 : iy + 4, ix - 3 : ix + 4]
                b0, bx, by = fit.background
                mod = fit.flux * m.evaluate(xx - fit.x, yy - fit.y) + b0 + bx * (xx - ix) + by * (yy - iy)
                res_img = (image[iy - 3 : iy + 4, ix - 3 : ix + 4] - mod) / fit.flux
                jx, jy = int(round(fit.x)) - ix, int(round(fit.y)) - iy
                stacks[img.detector].append(np.roll(np.roll(res_img, -jy, axis=0), -jx, axis=1))
                cxp, cyp = 3 + jx, 3 + jy
                mc = float(m.evaluate(np.array([ix - 3 + cxp - fit.x]), np.array([iy - 3 + cyp - fit.y]))[0])
                central_ratio = float((image[iy - 3 + cyp, ix - 3 + cxp] - (mod[cyp, cxp] - fit.flux * mc)) / fit.flux / mc) if mc > 0 else None
            else:
                central_ratio = None
            rows.append({
                "frame": nid, "observation": nid.split(":")[1], "ok_frame": nid in ok_frames, "detector": int(img.detector),
                "source_id": og.catalog.source_id[i], "g": float(g_all[i]), "rp": float(rp_all[i]) if np.isfinite(rp_all[i]) else None,
                "bp_rp": float(cat["bp_rp"][i]) if np.isfinite(cat["bp_rp"][i]) else None,
                "zone": [int(z.binx), int(z.biny)], "zone_offset": [float((r.x + ox_det - z.x_center) / z.x_width), float((r.y + oy_det - z.y_center) / z.y_width)],
                "x_det": float(r.x + ox_det), "y_det": float(r.y + oy_det), "phase_x": float(r.x - round(r.x)), "phase_y": float(r.y - round(r.y)),
                "snr": float(r.snr), "chi2_red": float(r.chi2_red), "chi2_red_integrated": float(f_int.chi2_red) if f_int.status == "ok" and f_int.chi2_red else None,
                "shift_integrated_px": [float(f_int.x - r.x), float(f_int.y - r.y)] if f_int.status == "ok" else None,
                "res_east": float(r.d_east_arcsec), "res_north": float(r.d_north_arcsec), "sig_east": float(r.s_east_arcsec), "sig_north": float(r.s_north_arcsec),
                "res_x_px": float(res_px[0]), "res_y_px": float(res_px[1]), "sig_x_px": float(sig_px[0]), "sig_y_px": float(sig_px[1]),
                "central_ratio": central_ratio, "neighbours": nbrs,
            })
            # independent-rendering zone swap: this zone rendered by photutils, fitted with each adjacent zone
            if nid in ok_frames:
                for k in lib.neighbours(r.zone):
                    zswap.append({"frame": nid, "detector": int(img.detector), "zone": r.zone, "other": k, "arr_a": r.zone, "lib": lib})
    return rows, parity, stacks, zswap


def simulate_neighbours(og, rows: list[dict]) -> None:  # noqa: ANN001
    """Shift induced by each reference's Gaia neighbours: noiseless image rendered with photutils, fitted by the pipeline."""
    libs = {nid: og._frame_inputs(nid).epsf for nid in og.images}
    for r in rows:
        lib = libs[r["frame"]]
        zi = next(z.index for z in lib.zones if (z.binx, z.biny) == tuple(r["zone"]))
        ip = _imagepsf(lib.arrays[zi], lib.oversampling)
        x0, y0 = 10.0 + r["phase_x"], 10.0 + r["phase_y"]
        yy, xx = np.mgrid[0:21, 0:21]
        img = ip.evaluate(xx, yy, flux=1000.0, x_0=x0, y_0=y0) + 5.0
        for nb in r["neighbours"]:
            img = img + ip.evaluate(xx, yy, flux=1000.0 * nb["ratio"], x_0=x0 + nb["dx"], y_0=y0 + nb["dy"])
        f = fit_position(img, np.full(img.shape, 1.0), np.zeros(img.shape, bool), lib.model(zi), x0, y0, half_window=og.cfg.half_window)
        r["neighbour_shift_px"] = [float(f.x - x0), float(f.y - y0)] if f.status == "ok" else None


def zone_swap_injection(zswap: list[dict], quick: bool) -> dict:
    """Render zone A (photutils ImagePSF) on a phase grid, fit with adjacent zone B (pipeline model): pure model-difference shifts."""
    n = 4 if quick else 6
    ph = (np.arange(n) + 0.5) / n - 0.5
    seen, per_det = set(), {}
    for s in zswap:
        key = (s["frame"], s["zone"], s["other"])
        if key in seen:
            continue
        seen.add(key)
        lib = s["lib"]
        ip = _imagepsf(lib.arrays[s["zone"]], lib.oversampling)
        mb = lib.model(s["other"])
        yy, xx = np.mgrid[0:21, 0:21]
        sh = []
        for fx in ph:
            for fy in ph:
                img = ip.evaluate(xx, yy, flux=1000.0, x_0=10 + fx, y_0=10 + fy) + 5.0
                f = fit_position(img, np.ones(img.shape), np.zeros(img.shape, bool), mb, 10 + fx, 10 + fy)
                if f.status == "ok":
                    sh.append((f.x - 10 - fx, f.y - 10 - fy))
        sh = np.array(sh)
        d = per_det.setdefault(s["detector"], {"mean_shift": [], "phase_rms": []})
        d["mean_shift"].append(sh.mean(axis=0))
        d["phase_rms"].append(sh.std(axis=0))
    out = {}
    for det, d in sorted(per_det.items()):
        ms, pr = np.array(d["mean_shift"]), np.array(d["phase_rms"])
        out[f"D{det}"] = {"n_pairs": int(len(ms)), "mean_shift_rms_x_px": _rms(ms[:, 0]), "mean_shift_rms_y_px": _rms(ms[:, 1]),
                          "max_abs_mean_shift_px": float(np.max(np.abs(ms))), "phase_dependent_rms_x_px": _rms(pr[:, 0]), "phase_dependent_rms_y_px": _rms(pr[:, 1])}
    return out


def aggregate(rows: list[dict], stacks: dict) -> dict:
    ok = [r for r in rows if r["ok_frame"]]
    # frame-mean-subtracted residuals in detector pixels isolate star-dependent effects from frame offsets
    by_frame: dict[str, list[dict]] = {}
    for r in ok:
        by_frame.setdefault(r["frame"], []).append(r)
    for fr in by_frame.values():
        for ax in ("x", "y"):
            w = np.array([1 / r[f"sig_{ax}_px"] ** 2 for r in fr])
            v = np.array([r[f"res_{ax}_px"] for r in fr])
            mu = float(np.sum(w * v) / np.sum(w))
            for r in fr:
                r[f"res_{ax}_px_frame_sub"] = r[f"res_{ax}_px"] - mu

    def summary(sel: list[dict]) -> dict:
        if not sel:
            return {"n": 0}
        e, n = np.array([r["res_east"] for r in sel]), np.array([r["res_north"] for r in sel])
        se, sn = np.array([r["sig_east"] for r in sel]), np.array([r["sig_north"] for r in sel])
        chi = np.array([r["chi2_red"] for r in sel])
        snr = np.array([r["snr"] for r in sel])
        eps = np.sqrt(np.clip(chi - 1, 0, None)) / snr
        out = {"n": len(sel), "rms_east_arcsec": _rms(e), "rms_north_arcsec": _rms(n), "rms_2d_arcsec": _rms(np.hypot(e, n)),
               "pull_rms_east": _rms(e / se), "pull_rms_north": _rms(n / sn), "median_sigma_arcsec": float(np.median(np.hypot(se, sn) / math.sqrt(2))),
               "chi2_red_median": float(np.median(chi)), "model_error_eps_median": float(np.median(eps)), "snr_median": float(np.median(snr))}
        if all("res_x_px_frame_sub" in r for r in sel):
            out["frame_sub_rms_x_px"] = _rms([r["res_x_px_frame_sub"] for r in sel])
            out["frame_sub_rms_y_px"] = _rms([r["res_y_px_frame_sub"] for r in sel])
        return out

    agg: dict = {"n_used_all_frames": len(rows), "n_used_ok_frames": len(ok)}
    agg["by_detector"] = {f"D{d}": summary([r for r in ok if r["detector"] == d]) for d in range(1, 7) if any(r["detector"] == d for r in ok)}
    agg["by_detector_all_frames"] = {f"D{d}": summary([r for r in rows if r["detector"] == d]) for d in range(1, 7) if any(r["detector"] == d for r in rows)}
    agg["by_snr"] = {f"{lo:g}-{hi:g}": summary([r for r in ok if lo <= r["snr"] < hi]) for lo, hi in ((10, 30), (30, 100), (100, 300), (300, 1e9))}
    agg["by_g_mag"] = {f"{lo:g}-{hi:g}": summary([r for r in ok if lo <= r["g"] < hi]) for lo, hi in ((0, 13), (13, 15), (15, 16.5), (16.5, 18.6))}
    agg["by_abs_phase"] = {}
    for lo, hi in ((0, 0.125), (0.125, 0.25), (0.25, 0.375), (0.375, 0.51)):
        sel = [r for r in ok if lo <= math.hypot(r["phase_x"], r["phase_y"]) / math.sqrt(2) < hi]
        agg["by_abs_phase"][f"{lo:g}-{hi:g}"] = summary(sel)
    # zone position: distance from the zone centre in units of the zone half-width (PSF variation within a zone)
    agg["by_zone_offset"] = {}
    for lo, hi in ((0, 0.25), (0.25, 0.5), (0.5, 0.8)):
        sel = [r for r in ok if lo <= max(abs(r["zone_offset"][0]), abs(r["zone_offset"][1])) < hi]
        agg["by_zone_offset"][f"{lo:g}-{hi:g}"] = summary(sel)
    agg["pixel_phase_scurve"] = {}
    for label, sel in (("D1-D4", [r for r in ok if r["detector"] <= 4]), ("D5-D6", [r for r in ok if r["detector"] >= 5]), ("all", ok)):
        if len(sel) >= 10:
            agg["pixel_phase_scurve"][label] = {
                "x": _wfit_scurve(np.array([r["phase_x"] for r in sel]), np.array([r["res_x_px_frame_sub"] for r in sel]), np.array([r["sig_x_px"] for r in sel])),
                "y": _wfit_scurve(np.array([r["phase_y"] for r in sel]), np.array([r["res_y_px_frame_sub"] for r in sel]), np.array([r["sig_y_px"] for r in sel])),
            }
    # chi2 growth with brightness. The reported S/N is deflated by sqrt(chi2_red), so it cannot serve as the
    # brightness axis (circular); use the formal S/N (VARIANCE only) and, independently, the Gaia RP flux with
    # per-frame intercepts. A pure fractional PSF error gives chi2-1 ~ flux^2; a brightness-independent excess
    # (structure in the window that VARIANCE does not describe) gives flux^0.
    agg["chi2_growth"] = {}
    for label, sel in (("D1-D4", [r for r in rows if r["detector"] <= 4]), ("D5-D6", [r for r in rows if r["detector"] >= 5])):
        entry: dict = {"by_formal_snr": {}}
        sf = np.array([r["snr"] * math.sqrt(max(1.0, r["chi2_red"])) for r in sel])
        chi = np.array([r["chi2_red"] for r in sel])
        for lo, hi in ((10, 30), (30, 100), (100, 300), (300, 1e9)):
            m = (sf >= lo) & (sf < hi)
            if m.any():
                entry["by_formal_snr"][f"{lo:g}-{hi:g}"] = {"n": int(m.sum()), "chi2_red_median": float(np.median(chi[m]))}
        s = [r for r in sel if r["rp"] is not None]
        frames = sorted({r["frame"] for r in s})
        if len(s) >= len(frames) + 5:
            X = np.zeros((len(s), len(frames) + 1))
            y = np.zeros(len(s))
            for k, r in enumerate(s):
                X[k, frames.index(r["frame"])] = 1.0
                X[k, -1] = -0.4 * r["rp"]
                y[k] = math.log10(max(r["chi2_red"] - 1.0, 0.05))
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ coef
            cov = np.linalg.inv(X.T @ X) * float(np.sum(resid**2) / (len(y) - X.shape[1]))
            entry["rp_flux_exponent"] = {"n": len(s), "exponent": float(coef[-1]), "exponent_sigma": float(math.sqrt(cov[-1, -1])),
                                         "scatter_dex": float(np.std(resid)), "model": "log10(chi2_red - 1) = a_frame + k log10(F_RP)"}
        agg["chi2_growth"][label] = entry
    # pixel integration test
    agg["pixel_integration"] = {}
    for d in range(1, 7):
        s = [r for r in rows if r["detector"] == d and r["chi2_red_integrated"] is not None]
        if s:
            c1 = np.array([r["chi2_red"] for r in s])
            c2 = np.array([r["chi2_red_integrated"] for r in s])
            sh = np.array([r["shift_integrated_px"] for r in s])
            agg["pixel_integration"][f"D{d}"] = {"n": len(s), "chi2_median_nominal": float(np.median(c1)), "chi2_median_integrated_again": float(np.median(c2)),
                                                 "sum_chi2_ratio": float(c2.sum() / c1.sum()), "n_worse": int((c2 > c1).sum()),
                                                 "shift_rms_px": [_rms(sh[:, 0]), _rms(sh[:, 1])]}
    # stacked residuals and central-pixel ratio
    agg["stacked_residual"] = {}
    for d, st in stacks.items():
        if not st:
            continue
        S = np.mean(st, axis=0)
        cr = [r["central_ratio"] for r in rows if r["detector"] == d and r["central_ratio"] is not None]
        agg["stacked_residual"][f"D{d}"] = {"n": len(st), "max_abs_frac_per_pixel_central_5x5": float(np.max(np.abs(S[1:6, 1:6]))),
                                            "central_5x5_x_right_y_up": np.round(np.flipud(S[1:6, 1:6]), 4).tolist(),
                                            "central_pixel_ratio_median": float(np.median(cr)) if cr else None,
                                            "central_pixel_ratio_16_84": [float(np.percentile(cr, 16)), float(np.percentile(cr, 84))] if cr else None}
    # colour dependence of the misfit on D1-D4
    s = [r for r in rows if r["detector"] <= 4 and r["bp_rp"] is not None]
    if len(s) >= 10:
        eps = np.array([math.sqrt(max(r["chi2_red"] - 1, 0)) / r["snr"] for r in s])
        col = np.array([r["bp_rp"] for r in s])
        agg["misfit_vs_colour_D1_D4"] = {"n": len(s), "spearman_eps_bp_rp": float(_spearman(eps, col))}
    s = [r for r in rows if r["detector"] <= 4]
    if len(s) >= 10:
        eps = np.array([math.sqrt(max(r["chi2_red"] - 1, 0)) / r["snr"] for r in s])
        zo = np.array([max(abs(r["zone_offset"][0]), abs(r["zone_offset"][1])) for r in s])
        cr = np.array([r["central_ratio"] if r["central_ratio"] is not None else np.nan for r in s])
        snr = np.array([r["snr"] for r in s])
        good = np.isfinite(cr)
        agg["misfit_vs_zone_offset_D1_D4"] = {"n": len(s), "spearman_eps_zone_offset": float(_spearman(eps, zo))}
        agg["central_ratio_vs_snr_D1_D4"] = {"n": int(good.sum()), "spearman": float(_spearman(cr[good], snr[good]))}
    return agg


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    from scipy import stats

    return float(stats.spearmanr(a, b).statistic)


def neighbour_summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["ok_frame"] and r.get("neighbour_shift_px") is not None]
    sh = np.array([r["neighbour_shift_px"] for r in ok])
    mag = np.hypot(sh[:, 0], sh[:, 1])
    out = {"n": len(ok), "n_with_neighbour_within_4p5px": int(sum(1 for r in ok if r["neighbours"])),
           "induced_shift_median_px": float(np.median(mag)), "induced_shift_p90_px": float(np.percentile(mag, 90)), "induced_shift_max_px": float(mag.max()),
           "n_induced_over_0p02px": int((mag > 0.02).sum()), "n_induced_over_0p05px": int((mag > 0.05).sum())}
    # does the simulated neighbour shift explain part of the measured (frame-subtracted) residual?
    rx = np.array([r["res_x_px_frame_sub"] for r in ok])
    ry = np.array([r["res_y_px_frame_sub"] for r in ok])
    sx = np.array([r["sig_x_px"] for r in ok])
    sy = np.array([r["sig_y_px"] for r in ok])
    pred = np.concatenate([sh[:, 0], sh[:, 1]])
    meas = np.concatenate([rx, ry])
    sig = np.concatenate([sx, sy])
    sel = np.abs(pred) > 0.005
    if sel.sum() >= 5:
        w = 1 / sig[sel] ** 2
        slope = float(np.sum(w * pred[sel] * meas[sel]) / np.sum(w * pred[sel] ** 2))
        slope_sigma = float(1 / math.sqrt(np.sum(w * pred[sel] ** 2)))
        out["regression_measured_on_simulated"] = {"n_axes": int(sel.sum()), "slope": slope, "slope_sigma": slope_sigma,
                                                   "note": "slope 1 = neighbour shift fully present in the residuals; 0 = not detectable at this noise"}
    out["worst"] = sorted(({"frame": r["frame"], "source_id": r["source_id"], "detector": r["detector"], "shift_px": r["neighbour_shift_px"],
                            "neighbours": r["neighbours"]} for r in ok if math.hypot(*r["neighbour_shift_px"]) > 0.02),
                          key=lambda x: -math.hypot(*x["shift_px"]))[:10]
    return out


def sky_structure(og) -> dict:  # noqa: ANN001
    """Is the pixel structure that VARIANCE does not describe fixed on the sky? High-pass images (pixel minus 5x5
    median, over sqrt(VARIANCE)) with Gaia G < 18.5 stars masked, correlated between frames of the same compatibility
    group at the same sky positions (bilinear). White noise gives rho = 0; faint sources / background give rho > 0."""
    import itertools

    from scipy.ndimage import map_coordinates, median_filter

    g_all = np.asarray(og.catalog.columns["phot_g_mean_mag"], float)
    z, meta = {}, {}
    for nid, img in og.images.items():
        fi = og._frame_inputs(nid)
        bad = (fi.flags.astype(np.int64) & excluded_mask(fi.flag_masks)) != 0
        im, var = np.asarray(fi.image, float), np.asarray(fi.variance, float)
        zz = (im - median_filter(np.where(bad, np.nan, im), size=5, mode="nearest")) / np.sqrt(var)
        pred = og.prediction(nid)
        px, py = fi.sky_to_pixel(pred.ra_deg, pred.dec_deg)
        yy, xx = np.mgrid[0 : im.shape[0], 0 : im.shape[1]]
        m = bad | ~np.isfinite(zz)
        for j in np.flatnonzero((g_all < 18.5) & (px > -3) & (px < im.shape[1] + 3) & (py > -3) & (py < im.shape[0] + 3)):
            m |= np.hypot(xx - px[j], yy - py[j]) < 2.5
        zz = np.where(m, np.nan, zz)
        valid = zz[np.isfinite(zz)]
        z[nid] = (zz, fi)
        obs = next(o for o in og.dataset.observations if nid in o.frame_ids)
        meta[nid] = {"band": obs.band_id, "detector": int(img.detector), "date": obs.timing.mid.iso_utc[:10],
                     "highpass_robust_z": float(1.4826 * np.median(np.abs(valid - np.median(valid)))) if valid.size else None}
    pairs = []
    for band in sorted({m["band"] for m in meta.values()}):
        ids = [k for k, m in meta.items() if m["band"] == band]
        for a, c in itertools.combinations(ids, 2):
            za, fa = z[a]
            zb, fb = z[c]
            yy, xx = np.mgrid[4 : za.shape[0] - 4, 4 : za.shape[1] - 4]
            ra, dec = fa.pixel_to_sky(xx.ravel().astype(float), yy.ravel().astype(float))
            bx, by = fb.sky_to_pixel(ra, dec)
            vb = map_coordinates(np.nan_to_num(zb, nan=0.0), [by, bx], order=1, mode="constant", cval=np.nan)
            nb = map_coordinates(np.isnan(zb).astype(float), [by, bx], order=1, mode="constant", cval=1.0)
            va = za[4:-4, 4:-4].ravel()
            ok = np.isfinite(va) & np.isfinite(vb) & (nb < 1e-6) & (bx > 3) & (by > 3) & (bx < zb.shape[1] - 4) & (by < zb.shape[0] - 4)
            A, B = va[ok], vb[ok]
            keep = (np.abs(A) < 6) & (np.abs(B) < 6)
            A, B = A[keep], B[keep]
            if A.size < 50:
                continue
            pairs.append({"band": band, "detector": meta[a]["detector"], "dates": [meta[a]["date"], meta[c]["date"]], "n_pixels": int(A.size),
                          "rho": float(np.corrcoef(A, B)[0, 1]), "cov_in_variance_units": float(np.mean((A - A.mean()) * (B - B.mean())))})
    per_det = {}
    for d in sorted({p["detector"] for p in pairs}):
        r = [p["rho"] for p in pairs if p["detector"] == d]
        hz = [m["highpass_robust_z"] for m in meta.values() if m["detector"] == d and m["highpass_robust_z"] is not None]
        per_det[f"D{d}"] = {"n_pairs": len(r), "rho_min": float(min(r)), "rho_max": float(max(r)), "highpass_robust_z_median": float(np.median(hz)) if hz else None}
    wn = np.random.default_rng(0).normal(size=(200, 200))
    wz = (wn - median_filter(wn, size=5, mode="nearest"))[4:-4, 4:-4]
    return {"method": " ".join(sky_structure.__doc__.split()),
            "white_noise_expectation": {"rho": 0.0, "highpass_robust_z": float(1.4826 * np.median(np.abs(wz - np.median(wz))))},
            "per_detector": per_det, "pairs": pairs}


def detectability(rep, agg: dict, nb: dict, scale: float) -> dict:  # noqa: ANN001
    """Illustrative 5-sigma (2-D) displacement thresholds from a reference-star error-budget model.

    Not a validated target-detection, completeness or false-positive measurement.

    Per axis and epoch: target centroid sigma_c = k * sqrt(chi2(S/N_f)) / S/N_f px (k = median sigma_px * S/N
    of the real references; chi2 from the formal-S/N bins of the same detector group), plus either
    (A, archive WCS as is) the empirical frame-to-frame scatter of the frame offsets, or (B, differential
    against the frame's references - would need a correction this build does not apply) the random part of the
    frame tie and the PSF-mismatch term; plus the star-to-star extra scatter and the median simulated
    neighbour shift. Epochs are independent; n frames per season average every per-frame term down by sqrt(n)
    (shared-all-frame terms are ~1e-5" and ignored). Threshold: |d| >= sqrt(chi2_2^-1(1 - 5.7e-7)) sigma_d,
    sigma_d = sqrt(2) sigma_epoch / sqrt(n)."""
    from scipy import stats

    ok = [f for f in rep.frames if f.status == "ok" and f.statistics and f.statistics.n >= 5]
    we = np.array([f.statistics.wmean_east_arcsec for f in ok])
    wn = np.array([f.statistics.wmean_north_arcsec for f in ok])
    frame_rms = float(np.sqrt(0.5 * (np.mean(we**2) + np.mean(wn**2))))
    tie = float(np.median([math.sqrt(0.5 * (f.translation.sigma_random_east_arcsec**2 + f.translation.sigma_random_north_arcsec**2)) for f in ok if f.translation.evaluated]))
    psf = float(np.median([f.shared.psf_mismatch_arcsec for f in ok if f.shared and f.shared.psf_mismatch_arcsec is not None]))
    extra = float(np.median([f.statistics.extra_scatter_arcsec for f in ok if f.statistics.extra_scatter_arcsec is not None]))
    nb_as = nb["induced_shift_median_px"] / math.sqrt(2) * scale  # per axis
    kfac = math.sqrt(stats.chi2.isf(2 * stats.norm.sf(5.0), 2))  # 2-D test at the two-sided 5-sigma tail probability: 5.36
    rows = [r for r in agg["_rows"] if r["ok_frame"]]
    out = {"method": " ".join(detectability.__doc__.split()), "k_threshold_sigma": kfac,
           "terms_arcsec_per_axis": {"frame_offset_rms_A": frame_rms, "frame_tie_random_B": tie, "psf_mismatch_B": psf, "extra_scatter": extra, "neighbour_median": nb_as},
           "cases": []}
    for group, dets in (("D1-D4", (1, 2, 3, 4)), ("D5-D6", (5, 6))):
        sel = [r for r in rows if r["detector"] in dets]
        k = float(np.median([math.sqrt(0.5 * (r["sig_x_px"] ** 2 + r["sig_y_px"] ** 2)) * r["snr"] for r in sel]))
        bins = agg["chi2_growth"][group]["by_formal_snr"]
        for snr_f, bin_key in ((50, "30-100"), (150, "100-300"), (400, "300-1e+09")):
            chi = bins.get(bin_key, {}).get("chi2_red_median") or max(v["chi2_red_median"] for v in bins.values())
            sc = k * math.sqrt(max(1.0, chi)) / snr_f * scale
            for approach in ("A", "B"):
                base = (frame_rms**2) if approach == "A" else (tie**2 + psf**2)
                se = math.sqrt(sc**2 + base + extra**2 + nb_as**2)
                for n in (1, 3, 10):
                    sd = math.sqrt(2.0) * se / math.sqrt(n)
                    out["cases"].append({"detector_group": group, "snr_formal": snr_f, "chi2_red_assumed": chi, "k_px": k, "sigma_centroid_arcsec": sc,
                                         "approach": approach, "frames_per_season": n, "sigma_epoch_arcsec": se / math.sqrt(n),
                                         "sigma_displacement_arcsec": sd, "min_displacement_arcsec": kfac * sd,
                                         "min_proper_motion_arcsec_yr_for_0p5yr": kfac * sd / 0.5})
    return out


def stress(quick: bool) -> dict:
    model, cases = es.default_matrix()
    nominal = es.moffat(1.15, 3.0)
    extra = [
        es.Case("neighbour 100% at 2.05 px (allowed by the 2 px / 10 % rule)", nominal, neighbour=(2.05, 0.0, 1.0)),
        es.Case("neighbour 100% at 2.5 px", nominal, neighbour=(2.5, 0.0, 1.0)),
        es.Case("neighbour 100% at 3.0 px", nominal, neighbour=(3.0, 0.0, 1.0)),
        es.Case("neighbour 100% at 4.0 px", nominal, neighbour=(4.0, 0.0, 1.0)),
        es.Case("neighbour 9% at 1.0 px (allowed by the rule)", nominal, neighbour=(1.0, 0.0, 0.09)),
        es.Case("neighbour 9% at 1.5 px (allowed by the rule)", nominal, neighbour=(1.5, 0.0, 0.09)),
        es.Case("3 masked pixels + PSF 10% broader", es.moffat(1.15 * 1.1, 3.0), n_masked=3),
        es.Case("PSF 10% broader, S/N~50", es.moffat(1.15 * 1.1, 3.0), noise_sigma=1000.0 / (50.0 * math.sqrt(3.6)), realizations=4),
    ]
    out = []
    for c in cases + extra:
        if quick:
            c.n_grid = min(c.n_grid, 4)
            c.realizations = min(c.realizations, 2)
        elif c.noise_sigma > 0:
            c.realizations = max(c.realizations, 8)
        out.append(es.run_case(c, model, seed=11))
    return {"renderer": "analytic Moffat (FWHM 1.15 px, beta 3) integrated over each native pixel (9x9 midpoint sub-samples); "
                        "fitting model: an A&K ePSF built from the nominal PSF on the 5x grid, evaluated by the pipeline",
            "cases": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true", help="smaller phase grids (for a smoke run)")
    args = ap.parse_args()
    t0 = time.time()
    b = SpherexProvider().load_dataset(FIELD)
    if not b.extras.get("spectral_images"):
        print("SPHEREx cutout cache absent: run the fetch command in CLAUDE.md first", file=sys.stderr)
        return 2
    og = observed_gaia(b, load_recorded_field(FIELD))
    rep = og.report()
    rows, parity, stacks, zswap = collect(og, rep)
    simulate_neighbours(og, rows)
    agg = aggregate(rows, stacks)
    nbs = neighbour_summary(rows)
    det = detectability(rep, {**agg, "_rows": rows}, nbs, float(b.dataset.instrument.pixel_scale_arcsec or 6.15))
    result = {
        "field": FIELD, "generated_by": "backend/scripts/estimator_review.py", "quick": bool(args.quick),
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(), "source_hash": source_hash(),
        "alignment_report_cache": rep.cache.model_dump() if rep.cache else None,
        "documentation_parity": parity, "real_residuals": agg, "neighbours": nbs, "detectability": det,
        "sky_fixed_structure": sky_structure(og),
        "zone_swap_injection": zone_swap_injection(zswap, args.quick), "stress_matrix": stress(args.quick),
        "detector_frame_offsets": rep.detector_frame_offsets.model_dump() if rep.detector_frame_offsets else None,
        "frame_offsets_detector_px": [{"frame": f.frame_id, "detector": f.detector, "offset_px": f.offset_detector_px, "sigma_px": f.offset_detector_sigma_px}
                                      for f in rep.frames if f.status == "ok" and f.offset_detector_px],
        "rows": [{k: v for k, v in r.items()} for r in rows],
        "runtime_s": None,
    }
    result["runtime_s"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    p = result["documentation_parity"]
    print(f"photutils parity max |diff|/peak {p['photutils_max_abs_diff_rel_peak']:.1e} over {p['zones_compared']} zones; "
          f"zone choice mismatches {p['zone_choice_mismatch']}/{p['zone_choice_checked']}; detector-coordinate max diff {p['detector_coord_max_abs_diff_px']:.1e} px")
    for k, v in agg["pixel_integration"].items():
        print(f"{k}: chi2 median {v['chi2_median_nominal']:.2f} -> {v['chi2_median_integrated_again']:.2f} if integrated again (sum ratio {v['sum_chi2_ratio']:.2f})")
    for k, v in agg["by_detector"].items():
        print(f"{k}: n {v['n']}, RMS E {v['rms_east_arcsec']:.3f} N {v['rms_north_arcsec']:.3f} 2-D {v['rms_2d_arcsec']:.3f}\"; pulls {v['pull_rms_east']:.2f}/{v['pull_rms_north']:.2f}; "
              f"chi2 {v['chi2_red_median']:.2f}; eps {v['model_error_eps_median']:.3f}")
    print("chi2 growth:", json.dumps(agg["chi2_growth"]))
    print("sky-fixed structure:", json.dumps(result["sky_fixed_structure"]["per_detector"]), result["sky_fixed_structure"]["white_noise_expectation"])
    print("S-curve:", json.dumps(agg["pixel_phase_scurve"], indent=None)[:600])
    print("neighbours:", {k: v for k, v in result["neighbours"].items() if k != "worst"})
    print("zone swap (injection):", result["zone_swap_injection"])
    print("detectability terms:", json.dumps(det["terms_arcsec_per_axis"]), "k =", round(det["k_threshold_sigma"], 2))
    for c in det["cases"]:
        if c["frames_per_season"] in (1, 10):
            print(f"  {c['detector_group']} S/N_f {c['snr_formal']:3d} ({c['approach']}, n={c['frames_per_season']:2d}): sigma_c {c['sigma_centroid_arcsec']:.3f}\" "
                  f"sigma_epoch {c['sigma_epoch_arcsec']:.3f}\" -> min displacement {c['min_displacement_arcsec']:.2f}\" (mu >= {c['min_proper_motion_arcsec_yr_for_0p5yr']:.2f}\"/yr over 0.5 yr)")
    print(f"wrote {OUT.relative_to(REPO)} in {result['runtime_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
