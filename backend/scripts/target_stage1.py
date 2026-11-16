"""Stage-1 verification of a candidate moving target in a SPHEREx field. Nothing here measures the target.

Per downloaded frame, from archive pixels only:
  * the target's approximate pixel position (stated literature astrometry, linear proper motion, no parallax),
    used only to choose pixels; the season and the local wavelength at the field centre;
  * saturation-type flags (OVERFLOW, SUR_ERROR, NONLINEAR, BLOOM) within 2.5 px and excluded flags in the 3x3 core;
  * a diagnostic pixel S/N: sum over the 3x3 box of (IMAGE - annulus median) divided by its noise from VARIANCE
    and the background estimate. IMAGE is surface brightness: this is a detectability check, not a flux, not an
    ePSF fit and not a position.
Per compatibility group (same detector, compatible local wavelength): usable frames in each season.

The Gaia DR3 part (target astrometry, neighbours, reference-star counts, the predicted displacement between
seasons) needs a recorded Gaia query for the field (skyshift.providers.gaia_dr3.fetch). Without one it is reported
as pending. The go/no-go criteria are fixed in CRITERIA below, before any data are read.

Run: cd backend && uv run python scripts/target_stage1.py --field spherex-dr1-vanmaanen2
Writes validation/<field>_stage1.json. Reads the local cutout cache and the manifest; makes no network request.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.simplefilter("ignore")

from astropy.time import Time  # noqa: E402

from skyshift.providers.spherex import SpherexProvider  # noqa: E402
from skyshift.science.alignment import SATURATION_FLAGS, excluded_mask  # noqa: E402
from skyshift.validation.report import source_hash  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# Approximate literature astrometry (the field preset's study target), used ONLY to choose pixels. An error of 1" moves the
# box by 0.16 px; parallax (<= 0.23" for van Maanen 2) is ignored for the same reason.
def _targets() -> dict[str, dict]:
    from dataclasses import asdict

    from skyshift.providers.spherex.fields import PRESETS

    return {k: {kk: vv for kk, vv in asdict(p.study_target).items() if kk != "gaia_dr3_source_id"} for k, p in PRESETS.items() if p.study_target}


TARGETS = _targets()

CRITERIA = {
    "season_split_utc": "2025-10-01",
    "flag_radius_px": 2.5,
    "min_diagnostic_snr": 30.0,
    "min_groups_spanning_both_seasons": 2,
    "usable_frame": "no saturation-type flag within 2.5 px, no excluded flag in the 3x3 core, diagnostic S/N >= min_diagnostic_snr",
    "spherex_go": "at least min_groups_spanning_both_seasons compatibility groups with >= 1 usable frame in each season",
    "gaia_pending_checks": [
        "target Gaia DR3 astrometry (5/6-parameter solution, RUWE) recorded with the field query",
        "no Gaia neighbour within 2 px brighter than 10 % (RP), and the simulated neighbour shift < 0.02 px",
        ">= 5 usable reference stars per frame for the alignment diagnostics",
        "predicted displacement between the season frames (proper motion + observer parallax) from the actual epochs",
    ],
}


def _target_radec(t: dict, jyear: float) -> tuple[float, float]:
    dtyr = jyear - 2000.0
    dec = t["dec_j2000_deg"] + t["pmdec_arcsec_yr"] * dtyr / 3600.0
    ra = t["ra_j2000_deg"] + t["pmra_arcsec_yr"] * dtyr / 3600.0 / math.cos(math.radians(dec))
    return ra % 360.0, dec


def frame_checks(img, target: dict) -> dict:  # noqa: ANN001
    mid = float(img.image_header["MJD-AVG"])
    tt = Time(mid, format="mjd", scale="utc")
    ra, dec = _target_radec(target, float(tt.jyear))
    x, y = img.sky_to_pixel(ra, dec)
    ny, nx = img.shape
    masks = {d.name: d.mask_value for d in img.flag_defs}
    bad = (img.flags.astype(np.int64) & excluded_mask(masks)) != 0
    image, var = np.asarray(img.image, float), np.asarray(img.variance, float)
    ix, iy = int(round(x)), int(round(y))
    out = {"obs_id": img.obs_id, "detector": int(img.detector), "mid_utc": tt.isot[:19], "mjd_utc": mid,
           "season": 1 if tt.isot[:10] < CRITERIA["season_split_utc"] else 2, "target_pixel": [float(x), float(y)]}
    near = img.flags_near(x, y, CRITERIA["flag_radius_px"])
    out["flags_within_2p5px"] = near
    out["saturation_flags_within_2p5px"] = [f for f in near if f in SATURATION_FLAGS]
    if not (3 <= ix < nx - 3 and 3 <= iy < ny - 3):
        out.update(usable=False, reason="target box not inside the cutout")
        return out
    core = (slice(iy - 1, iy + 2), slice(ix - 1, ix + 2))
    out["core_excluded_flags"] = sorted({n for n, m in masks.items() if np.any(img.flags[core] & m) and (excluded_mask({n: m}) != 0)})
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.hypot(xx - x, yy - y)
    ann = (r >= 4.0) & (r <= 7.0) & ~bad & np.isfinite(image)
    a = image[ann]
    bg = float(np.median(a))
    sig_bg = 1.4826 * float(np.median(np.abs(a - bg)))
    var_bgmed = (math.pi / 2.0) * sig_bg**2 / a.size  # variance of a median of n roughly Gaussian values
    box = image[core] - bg
    s = float(np.sum(box))
    n = math.sqrt(float(np.sum(var[core])) + 9.0**2 * var_bgmed)
    # Conservative variant (information only; the criterion uses the VARIANCE-based value): add the annulus pixel scatter in excess
    # of VARIANCE (sky-fixed faint structure, see the estimator review) to every box pixel.
    excess = max(0.0, sig_bg**2 - float(np.median(var[ann])))
    n_cons = math.sqrt(float(np.sum(var[core])) + 9.0 * excess + 9.0**2 * var_bgmed)
    out.update({"annulus_n": int(a.size), "background_median": bg, "diagnostic_snr_3x3": s / n if n > 0 else None,
                "diagnostic_snr_3x3_conservative": s / n_cons if n_cons > 0 else None,
                "annulus_scatter_over_variance": float(sig_bg / math.sqrt(float(np.median(var[ann])))),
                "peak_pixel_snr": float(np.max(box / np.sqrt(var[core]))), "unit": str(img.image_header.get("BUNIT", ""))})
    usable = (not out["saturation_flags_within_2p5px"]) and (not out["core_excluded_flags"]) and (out["diagnostic_snr_3x3"] or 0) >= CRITERIA["min_diagnostic_snr"]
    out["usable"] = bool(usable)
    reasons = []
    if out["saturation_flags_within_2p5px"]:
        reasons.append("saturation-type flags within 2.5 px: " + ", ".join(out["saturation_flags_within_2p5px"]))
    if out["core_excluded_flags"]:
        reasons.append("excluded flags in the 3x3 core: " + ", ".join(out["core_excluded_flags"]))
    if (out["diagnostic_snr_3x3"] or 0) < CRITERIA["min_diagnostic_snr"]:
        reasons.append(f"diagnostic S/N {out['diagnostic_snr_3x3']:.1f} < {CRITERIA['min_diagnostic_snr']:g}")
    out["reason"] = "; ".join(reasons) or "usable"
    return out


def predicted_pair_displacements(target: dict, frames: list[dict]) -> list[dict]:
    """Expected target displacement between the two members of each compatibility pair (model prediction).

    Rigorous uniform space motion from J2016.0 plus the geocentric observer parallax at each frame's
    mid-time (skyshift.science.epoch_propagation, the code validated against the Gaia archive's own
    propagation), from the stated literature astrometry. The radial velocity is unknown and set to 0;
    perspective acceleration over half a year is negligible here. Replace by the recorded Gaia DR3 values."""
    from skyshift.coords.observer import observer_barycentric_au
    from skyshift.coords.tangent import offsets_mas
    from skyshift.coords.time import make_epoch
    from skyshift.science.epoch_propagation import AstrometricArrays, predict_observed, propagate

    ra16, dec16 = _target_radec(target, 2016.0)
    arr = AstrometricArrays(np.array([ra16]), np.array([dec16]), np.array([target["parallax_mas"]]),
                            np.array([target["pmra_arcsec_yr"] * 1000.0]), np.array([target["pmdec_arcsec_yr"] * 1000.0]), np.array([np.nan]),
                            np.full((1, 5), 0.1), np.repeat(np.eye(5)[None], 1, axis=0), np.array([np.nan]), make_epoch(2016.0, "jyear", "tcb").mjd_tdb)
    pos = {}
    for f in frames:
        mjd_tdb = float(Time(f["mjd_utc"], format="mjd", scale="utc").tdb.mjd)
        b = observer_barycentric_au(np.array([mjd_tdb]))[0]
        obs, bary = predict_observed(arr, mjd_tdb, b), propagate(arr, mjd_tdb)
        pos[f["frame_id"]] = (float(obs.ra_deg[0]), float(obs.dec_deg[0]), float(bary.ra_deg[0]), float(bary.dec_deg[0]))
    out = []
    bands = sorted({f["band_id"] for f in frames if f["band_id"]})
    for band in bands:
        members = sorted((f for f in frames if f["band_id"] == band), key=lambda f: f["mjd_utc"])
        if len(members) != 2:
            continue
        a, c = pos[members[0]["frame_id"]], pos[members[1]["frame_id"]]
        e, n = offsets_mas(c[0], c[1], a[0], a[1])
        pe, pn = offsets_mas(c[2], c[3], a[2], a[3])
        out.append({"band_id": band, "detector": members[0]["detector"], "from_utc": members[0]["mid_utc"], "to_utc": members[1]["mid_utc"],
                    "interval_days": members[1]["mjd_utc"] - members[0]["mjd_utc"],
                    "east_arcsec": float(e) / 1000.0, "north_arcsec": float(n) / 1000.0, "total_arcsec": float(math.hypot(e, n)) / 1000.0,
                    "proper_motion_part_arcsec": [float(pe) / 1000.0, float(pn) / 1000.0],
                    "parallax_part_arcsec": [float(e - pe) / 1000.0, float(n - pn) / 1000.0],
                    "both_usable": all(m["usable"] for m in members), "origin": "model_prediction"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--field", default="spherex-dr1-vanmaanen2", choices=sorted(TARGETS))
    args = ap.parse_args()
    target = TARGETS[args.field]
    b = SpherexProvider().load_dataset(args.field)
    images = b.extras.get("spectral_images") or {}
    if not images:
        print("no cached cutouts: run the SPHEREx fetch for this field first", file=sys.stderr)
        return 2
    ds = b.dataset
    obs_by_native = {f: o for o in ds.observations for f in o.frame_ids if f.endswith(":native")}
    frames = []
    for nid, img in sorted(images.items(), key=lambda kv: (kv[1].detector, float(kv[1].image_header["MJD-AVG"]))):
        fc = frame_checks(img, target)
        o = obs_by_native.get(nid)
        fc.update({"frame_id": nid, "band_id": o.band_id if o else None})
        frames.append(fc)
    groups = []
    for band in ds.bands:
        comp = band.compatibility
        members = [f for f in frames if f["band_id"] == band.id]
        use = [f for f in members if f["usable"]]
        seasons = {f["season"] for f in use}
        groups.append({"band_id": band.id, "detector": comp.detector if comp else None, "n_frames": len(members), "n_usable": len(use),
                       "usable_seasons": sorted(seasons), "spans_both_seasons": seasons == {1, 2},
                       "baseline_days_usable": (max(f["mjd_utc"] for f in use) - min(f["mjd_utc"] for f in use)) if len(use) >= 2 else 0.0,
                       "lambda_um": [comp.lambda_min_um, comp.lambda_max_um] if comp else None})
    n_both = sum(g["spans_both_seasons"] for g in groups)
    pairs = predicted_pair_displacements(target, frames)
    gaia_recorded = any(c.id == "catalog_overlay" and c.status == "available" for c in ds.capabilities)
    verdict = {
        "spherex_part": "GO" if n_both >= CRITERIA["min_groups_spanning_both_seasons"] else "NO-GO",
        "spherex_reason": f"{n_both} compatibility group(s) with a usable frame in each season (criterion >= {CRITERIA['min_groups_spanning_both_seasons']})",
        "gaia_part": "ready for checking" if gaia_recorded else "pending: no recorded Gaia DR3 query for this field",
        "overall": ("stage 1 incomplete: Gaia checks pending" if not gaia_recorded else "run the Gaia checks"),
    }
    result = {"field": args.field, "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "source_hash": source_hash(),
              "generated_by": "backend/scripts/target_stage1.py", "target": target, "criteria": CRITERIA,
              "not_measured": "No target position, flux or motion is measured; the diagnostic S/N uses surface-brightness pixels.",
              "frames": frames, "groups": groups,
              "predicted_pair_displacements": {"note": " ".join(predicted_pair_displacements.__doc__.split()), "pairs": pairs},
              "verdict": verdict}
    out = REPO / "validation" / f"{args.field.replace('spherex-dr1-', '')}_stage1.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for f in frames:
        snr = f.get("diagnostic_snr_3x3")
        cons = f.get("diagnostic_snr_3x3_conservative")
        print(f"D{f['detector']} {f['mid_utc']} S{f['season']} band {f['band_id'] or '-':>12}: S/N {snr if snr is None else round(snr, 1)} "
              f"(conservative {cons if cons is None else round(cons, 1)}, annulus scatter/sqrt(VAR) {round(f.get('annulus_scatter_over_variance') or 0, 2)}) "
              f"peak {round(f.get('peak_pixel_snr') or 0, 1)} sat {f['saturation_flags_within_2p5px'] or '-'} core {f.get('core_excluded_flags') or '-'} -> {f['reason']}")
    for g in groups:
        print(f"group {g['band_id']}: {g['n_usable']}/{g['n_frames']} usable, seasons {g['usable_seasons']}, both={g['spans_both_seasons']}, baseline {g['baseline_days_usable']:.0f} d")
    for p in pairs:
        print(f"pair {p['band_id']} ({p['interval_days']:.0f} d): predicted displacement E {p['east_arcsec']:+.3f} N {p['north_arcsec']:+.3f} -> {p['total_arcsec']:.3f}\" "
              f"(proper motion {p['proper_motion_part_arcsec'][0]:+.3f},{p['proper_motion_part_arcsec'][1]:+.3f}; parallax {p['parallax_part_arcsec'][0]:+.3f},{p['parallax_part_arcsec'][1]:+.3f}); "
              f"both usable {p['both_usable']}")
    print(json.dumps(verdict, indent=1))
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
