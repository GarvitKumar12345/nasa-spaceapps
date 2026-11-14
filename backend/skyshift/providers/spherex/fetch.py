"""Bounded live acquisition of one SPHEREx field and its retrieval manifest.

    cd backend
    uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard            # discover, screen, select, download
    uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --dry-run  # no cutouts
    uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --from-manifest  # re-download the recorded selection

Steps: (1) SIA2 discovery in one explicit collection; (2) byte-range screening of every
discovered image (query pixel, edge margin, local wavelength, DQA keywords); (3) wavelength-
compatibility groups among eligible images; (4) a bounded selection (best group per
detector, plus one same-detector incompatible-wavelength contrast frame); (5) cutout
downloads with validation. Every request, failure and decision is written to the manifest
(fixtures/spherex/<field>/manifest.json); cutouts go to the local cache only.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from skyshift.providers.spherex.discovery import DiscoveryRow, build_sia_url, parse_sia_votable, resolve_duplicates
from skyshift.providers.spherex.fields import PRESETS, FieldPreset
from skyshift.providers.spherex.fitsfile import UnsupportedSpherexProduct, checks_passed, read_spectral_image, validate_spectral_image
from skyshift.providers.spherex.http import ArchiveClient, ArchiveRequestFailed, utc_now
from skyshift.providers.spherex.paths import FIXTURE_ROOT, cutout_path, manifest_path
from skyshift.providers.spherex.reference import COLLECTIONS, FINAST_GOOD, NOMINAL_PIXEL_SCALE_ARCSEC
from skyshift.providers.spherex.screening import screen_row
from skyshift.providers.spherex.wavelength import WavelengthSample, compatibility_groups
from skyshift.versions import software_versions

MANIFEST_SCHEMA = "skyshift.spherex-manifest/1"
MAX_CUTOUT_BYTES = 40_000_000


def row_key(obs_id: str, detector: int) -> str:
    return f"{obs_id}:D{detector}"


def cutout_url(row: DiscoveryRow, ra: float, dec: float, size_deg: float) -> str:
    return f"{row.access_url}?center={ra:.6f},{dec:.6f}deg&size={size_deg:g}deg"


def data_sha256(img) -> str:
    """Hash of the science arrays (IMAGE, FLAGS, VARIANCE, ZODI) independent of header bytes."""
    h = hashlib.sha256()
    for a in (img.image, img.flags, img.variance, img.zodi):
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def eligibility(s: dict, preset: FieldPreset) -> tuple[bool, str]:
    if s.get("status") != "screened":
        return False, f"screening failed: {s.get('error')}"
    if not s.get("identity_consistent"):
        return False, "header OBSID/DETECTOR disagree with the discovery row"
    if not s.get("inside"):
        return False, "query position outside the detector"
    if s["edge_margin_px"] < preset.min_edge_margin_px:
        return False, f"query position {s['edge_margin_px']:.0f} px from the detector edge (< {preset.min_edge_margin_px:.0f}; cutout would be clipped)"
    hdr = s.get("header", {})
    if hdr.get("FINAST") != FINAST_GOOD:
        return False, f"FINAST={hdr.get('FINAST')} (astrometry not good)"
    if str(hdr.get("L2DQAFLG", "")).lower() != "pass":
        return False, f"L2DQAFLG={hdr.get('L2DQAFLG')}"
    if s.get("lambda_um") is None or s.get("bandwidth_um") is None:
        return False, "no local wavelength"
    return True, "eligible"


def _spread(members: list[WavelengthSample], n: int) -> list[WavelengthSample]:
    by_t = sorted(members, key=lambda m: m.t_mjd)
    if len(by_t) <= n:
        return by_t
    idx = sorted({int(round(i)) for i in np.linspace(0, len(by_t) - 1, n)})
    return [by_t[i] for i in idx]


def select(preset: FieldPreset, samples: list[WavelengthSample]) -> dict:
    f = preset.max_delta_fraction
    groups = compatibility_groups(samples, f)
    chosen: list[dict] = []
    for det in sorted({s.detector for s in samples}):
        cands = [g for g in groups if g[0].detector == det and len(g) >= 2]
        if not cands:
            continue
        best = max(cands, key=lambda g: (len(g), max(m.t_mjd for m in g) - min(m.t_mjd for m in g)))
        members = _spread(best, preset.max_per_group)
        chosen.append({"detector": det, "group_size_available": len(best), "members": [m.key for m in members],
                       "lambda_min_um": min(m.lambda_um for m in best), "lambda_max_um": max(m.lambda_um for m in best),
                       "min_bandwidth_um": min(m.bandwidth_um for m in best),
                       "baseline_days": max(m.t_mjd for m in members) - min(m.t_mjd for m in members)})
    chosen.sort(key=lambda g: (-len(g["members"]), g["detector"]))
    total = 0
    kept = []
    for g in chosen:
        if total + len(g["members"]) <= preset.max_cutouts - preset.contrast_per_detector:
            kept.append(g)
            total += len(g["members"])
    contrast: list[dict] = []
    if kept and preset.contrast_per_detector:
        g = kept[0]
        lam_mid = 0.5 * (g["lambda_min_um"] + g["lambda_max_um"])
        in_group = set(g["members"])
        first_t = min(s.t_mjd for s in samples if s.key in in_group)
        others = [s for s in samples if s.detector == g["detector"] and s.key not in in_group and abs(s.lambda_um - lam_mid) > 3 * f * g["min_bandwidth_um"]]
        for s in sorted(others, key=lambda s: abs(s.t_mjd - first_t))[: preset.contrast_per_detector]:
            contrast.append({"key": s.key, "detector": s.detector, "lambda_um": s.lambda_um, "delta_lambda_um": s.lambda_um - lam_mid,
                             "reason": "same detector as the largest group but incompatible local wavelength: shows that detector number alone does not establish compatibility"})
    return {"groups_all": [[m.key for m in grp] for grp in groups], "selected_groups": kept, "contrast": contrast,
            "rule": (f"same detector and |lambda_i - lambda_j| <= {f} x min(bandwidth) at the field centre (WCS-WAVE, visualization-grade); "
                     f"per detector the largest group (ties: longest baseline), at most {preset.max_per_group} members spread in time; "
                     f"plus {preset.contrast_per_detector} contrast frame; at most {preset.max_cutouts} cutouts")}


def _download(client: ArchiveClient, preset: FieldPreset, row: DiscoveryRow, screening: dict) -> dict:
    url = cutout_url(row, preset.ra_deg, preset.dec_deg, preset.cutout_size_deg)
    entry: dict = {"key": row_key(row.obs_id, row.detector), "obs_id": row.obs_id, "detector": row.detector, "file_name": row.file_name, "url": url}
    try:
        body, rec = client.get(url, max_bytes=MAX_CUTOUT_BYTES)
    except ArchiveRequestFailed as exc:
        return {**entry, "status": "failed", "error": exc.reason, "request": exc.record.as_dict()}
    entry.update({"retrieved_utc": rec.started_utc, "sha256": rec.sha256, "bytes": rec.bytes, "request": rec.as_dict()})
    path = cutout_path(preset.id, row.file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(path)
    try:
        img = read_spectral_image(body)
    except (UnsupportedSpherexProduct, ValueError, OSError) as exc:
        return {**entry, "status": "failed", "error": f"unreadable/unsupported file: {exc}"}
    size_px = int(round(preset.cutout_size_deg * 3600.0 / NOMINAL_PIXEL_SCALE_ARCSEC))
    checks = validate_spectral_image(img, collection=preset.collection, row=row, requested_size_px=size_px)
    x, y = img.sky_to_pixel(preset.ra_deg, preset.dec_deg)
    lam, bw, cross = img.wavelength_at(x, y)
    off = img.detector_offset() or (0.0, 0.0)
    det_xy = (x + off[0], y + off[1])
    sx, sy = screening["query_pixel_detector"]
    d_pix = float(np.hypot(det_xy[0] - sx, det_xy[1] - sy))
    d_lam = abs(lam - float(screening["lambda_um"]))
    checks.append(validate_cutout_vs_screening(d_pix, d_lam))
    entry.update({
        "status": "downloaded" if checks_passed(checks) else "failed",
        "error": None if checks_passed(checks) else "file checks failed: " + "; ".join(c.id for c in checks if c.status == "fail"),
        "data_sha256": data_sha256(img), "shape": list(img.shape), "pipeline_version": img.pipeline_version,
        "query_pixel_cutout": [x, y], "query_pixel_detector": list(det_xy), "lambda_um": lam, "bandwidth_um": bw, "wavelength_crosscheck_um": cross,
        "flags_near_query": img.flags_near(x, y), "checks": [c.model_dump() for c in checks],
    })
    return entry


def validate_cutout_vs_screening(d_pix: float, d_lam: float):
    from skyshift.contracts import FileCheck

    ok = d_pix < 1e-3 and d_lam < 1e-6
    return FileCheck(id="cutout_vs_screening", status="pass" if ok else "fail",
                     detail=f"cutout and full-file screening agree: query pixel {d_pix:.1e} px, local wavelength {d_lam:.1e} um (independent request paths)")


def run(preset: FieldPreset, *, dry_run: bool = False, from_manifest: bool = False, client: ArchiveClient | None = None, log=print) -> dict:
    client = client or ArchiveClient()
    coll = preset.collection
    if coll not in COLLECTIONS:
        raise ValueError(f"preset collection {coll!r} is not a supported searchable collection")
    out_dir = FIXTURE_ROOT / preset.id
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    previous = json.loads(manifest_path(preset.id).read_text(encoding="utf-8")) if from_manifest else None

    url = build_sia_url(coll, preset.ra_deg, preset.dec_deg, preset.search_radius_deg)
    log(f"[1/5] SIA2 discovery: {url}")
    body, rec = client.get(url, max_bytes=50_000_000)
    rows_all = parse_sia_votable(body, coll)
    rows, superseded = resolve_duplicates(rows_all)
    if not dry_run:
        (out_dir / "sia_response.xml.gz").write_bytes(gzip.compress(body, mtime=0))
    log(f"      {len(rows_all)} rows ({len(superseded)} superseded duplicates), {len({r.detector for r in rows})} detectors")
    by_key = {row_key(r.obs_id, r.detector): r for r in rows}

    log(f"[2/5] screening {len(rows)} images by byte-range reads (concurrency {client.max_concurrency})")

    def _screen(r: DiscoveryRow) -> dict:
        try:
            return screen_row(client, r, preset.ra_deg, preset.dec_deg)
        except (ArchiveRequestFailed, ValueError, KeyError) as exc:
            return {"obs_id": r.obs_id, "detector": r.detector, "file_name": r.file_name, "status": "failed", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=client.max_concurrency) as pool:
        screening = list(pool.map(_screen, rows))
    for s in screening:
        s["key"] = row_key(s["obs_id"], s["detector"])
        s["eligible"], s["eligibility"] = eligibility(s, preset)
    n_fail = sum(s["status"] != "screened" for s in screening)
    n_elig = sum(s["eligible"] for s in screening)
    log(f"      screened {len(screening) - n_fail}, failed {n_fail}, eligible {n_elig}")

    samples = [WavelengthSample(s["key"], s["detector"], float(s["lambda_um"]), float(s["bandwidth_um"]), by_key[s["key"]].t_min_mjd) for s in screening if s["eligible"]]
    log("[3/5] wavelength-compatibility groups and bounded selection")
    if previous is not None:
        selection = previous["selection"]
        log("      using the selection recorded in the existing manifest")
    else:
        selection = select(preset, samples)
    wanted = [k for g in selection["selected_groups"] for k in g["members"]] + [c["key"] for c in selection["contrast"]]
    for g in selection["selected_groups"]:
        log(f"      D{g['detector']}: {len(g['members'])} of {g['group_size_available']} compatible, lambda {g['lambda_min_um']:.4f}-{g['lambda_max_um']:.4f} um, baseline {g['baseline_days']:.0f} d")
    downloads: list[dict] = []
    if not dry_run:
        log(f"[4/5] downloading {len(wanted)} cutouts ({preset.cutout_size_deg} deg) with validation")
        screen_by_key = {s["key"]: s for s in screening}
        with ThreadPoolExecutor(max_workers=client.max_concurrency) as pool:
            downloads = list(pool.map(lambda k: _download(client, preset, by_key[k], screen_by_key[k]) if k in by_key and screen_by_key.get(k, {}).get("status") == "screened"
                                      else {"key": k, "status": "failed", "error": "not in the current discovery/screening result"}, wanted))
        for d in downloads:
            log(f"      {d['key']}: {d['status']}" + (f" ({d.get('error')})" if d["status"] != "downloaded" else f", {d['bytes'] / 1e6:.1f} MB"))
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "field": preset.as_dict(),
        "collection": coll,
        "release": COLLECTIONS[coll].release,
        "created_utc": utc_now(),
        "software": [s.model_dump() for s in software_versions()],
        "discovery": {"url": url, "retrieved_utc": rec.started_utc, "request": rec.as_dict(), "n_rows": len(rows_all),
                      "response_file": "sia_response.xml.gz", "rows": [r.as_dict() for r in rows], "superseded": superseded},
        "screening": screening,
        "selection": selection,
        "downloads": downloads,
        "http_summary": {"requests": len(client.log), "bytes": sum(r.bytes for r in client.log), "failed": sum(r.error is not None for r in client.log),
                         "retried": sum(r.attempts > 1 for r in client.log)},
        "notes": [
            "Cutouts are stored in the local cache (backend/cache/spherex/), not in the repository; re-download with --from-manifest.",
            "Local wavelengths come from the WCS-WAVE lookup (visualization-grade); CWAVE/CBAND calibration products were not retrieved.",
        ],
    }
    if previous is not None:
        manifest["previous_manifest_created_utc"] = previous.get("created_utc")
    log("[5/5] " + ("dry run: manifest not written" if dry_run else "writing manifest " + str(manifest_path(preset.id))))
    if not dry_run:
        manifest_path(preset.id).write_text(json.dumps(manifest, indent=1, default=_json_default), encoding="utf-8")
    return manifest


def _json_default(o: object):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--field", default="spherex-dr1-barnard", choices=sorted(PRESETS))
    p.add_argument("--dry-run", action="store_true", help="discover, screen and select only; write nothing")
    p.add_argument("--from-manifest", action="store_true", help="reuse the selection recorded in the existing manifest")
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args(argv)
    m = run(PRESETS[args.field], dry_run=args.dry_run, from_manifest=args.from_manifest, client=ArchiveClient(max_concurrency=args.concurrency))
    n_ok = sum(d["status"] == "downloaded" for d in m["downloads"])
    print(json.dumps({"rows": m["discovery"]["n_rows"], "downloaded": n_ok, "failed": len(m["downloads"]) - n_ok, "http": m["http_summary"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
