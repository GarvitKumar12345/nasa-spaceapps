import csv
import glob
import io
import math
import os
from typing import Dict, List, Tuple
import requests

GAIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gaia")
ESA_GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"

# In-memory caches so CSVs are parsed once and live ESA queries aren't repeated
_LOCAL_ROWS: List[Dict] = []
_LOCAL_BOUNDS: List[Tuple[float, float, float, float]] = []
_LOCAL_LOADED = False
_REMOTE_CACHE: Dict[str, List[Dict]] = {}


def _safe_float(val, default=None):
    try:
        if val is None or str(val).strip() in ("", "null", "NaN", "nan"):
            return default
        return float(val)
    except ValueError:
        return default


def _load_local_csvs() -> None:
    """Load and index all Gaia DR3 CSVs in data/gaia/ once into memory."""
    global _LOCAL_LOADED
    if _LOCAL_LOADED:
        return
    _LOCAL_LOADED = True

    search_dirs = [
        GAIA_DIR,
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache", "gaia"),
    ]

    seen_ids = set()
    csv_files = []
    for d in search_dirs:
        if os.path.isdir(d):
            csv_files.extend(glob.glob(os.path.join(d, "*.csv")))

    for csv_path in csv_files:
        try:
            with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or "ra" not in reader.fieldnames:
                    continue  # Skip schema/dictionary CSVs

                ras, decs = [], []
                for row in reader:
                    ra = _safe_float(row.get("ra"))
                    dec = _safe_float(row.get("dec"))
                    if ra is None or dec is None:
                        continue

                    sid = str(row.get("source_id") or "").strip()
                    if sid and sid in seen_ids:
                        continue
                    if sid:
                        seen_ids.add(sid)

                    ras.append(ra)
                    decs.append(dec)
                    _LOCAL_ROWS.append({
                        "source_id": sid or "Gaia-DR3",
                        "ra": ra,
                        "dec": dec,
                        "ref_epoch": _safe_float(row.get("ref_epoch"), 2016.0),
                        "pmra": _safe_float(row.get("pmra"), 0.0),
                        "pmdec": _safe_float(row.get("pmdec"), 0.0),
                        "pm": _safe_float(row.get("pm")),
                        "parallax": _safe_float(row.get("parallax")),
                        "phot_g_mean_mag": _safe_float(row.get("phot_g_mean_mag")),
                        "bp_rp": _safe_float(row.get("bp_rp")),
                        "ruwe": _safe_float(row.get("ruwe")),
                        "teff_gspphot": _safe_float(row.get("teff_gspphot")),
                    })

                if ras and decs:
                    _LOCAL_BOUNDS.append((min(ras), max(ras), min(decs), max(decs)))
        except Exception:
            continue


def _is_covered_locally(ra: float, dec: float) -> bool:
    """Return True if (ra, dec) lies inside the sky footprint of any loaded local CSV."""
    for ra_min, ra_max, dec_min, dec_max in _LOCAL_BOUNDS:
        if ra_min <= ra <= ra_max and dec_min <= dec <= dec_max:
            return True
    return False


def _query_esa_gaia_tap(center_ra: float, center_dec: float, fov_deg: float) -> List[Dict]:
    """Live fallback query against ESA's public Gaia DR3 TAP service."""
    cache_key = f"{center_ra:.4f}_{center_dec:.4f}_{fov_deg:.4f}"
    if cache_key in _REMOTE_CACHE:
        return _REMOTE_CACHE[cache_key]

    # Pad search radius by 0.03 deg (~108") so high-PM stars at epoch 2016.0 aren't missed
    search_radius = (fov_deg / 2.0) + 0.03
    adql = f"""
    SELECT TOP 60
        source_id, ra, dec, ref_epoch, pmra, pmdec, pm,
        parallax, phot_g_mean_mag, bp_rp, ruwe, teff_gspphot
    FROM gaiadr3.gaia_source
    WHERE CONTAINS(
        POINT('ICRS', ra, dec),
        CIRCLE('ICRS', {center_ra:.6f}, {center_dec:.6f}, {search_radius:.6f})
    ) = 1
    ORDER BY phot_g_mean_mag ASC
    """
    resp = requests.post(
        ESA_GAIA_TAP_URL,
        data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql.strip()},
        timeout=12,
    )
    resp.raise_for_status()

    rows = []
    for row in csv.DictReader(io.StringIO(resp.text)):
        ra = _safe_float(row.get("ra"))
        dec = _safe_float(row.get("dec"))
        if ra is None or dec is None:
            continue
        rows.append({
            "source_id": str(row.get("source_id") or "Gaia-DR3").strip(),
            "ra": ra,
            "dec": dec,
            "ref_epoch": _safe_float(row.get("ref_epoch"), 2016.0),
            "pmra": _safe_float(row.get("pmra"), 0.0),
            "pmdec": _safe_float(row.get("pmdec"), 0.0),
            "pm": _safe_float(row.get("pm")),
            "parallax": _safe_float(row.get("parallax")),
            "phot_g_mean_mag": _safe_float(row.get("phot_g_mean_mag")),
            "bp_rp": _safe_float(row.get("bp_rp")),
            "ruwe": _safe_float(row.get("ruwe")),
            "teff_gspphot": _safe_float(row.get("teff_gspphot")),
        })

    _REMOTE_CACHE[cache_key] = rows
    return rows


def _filter_and_propagate(
    candidate_rows: List[Dict],
    center_ra: float,
    center_dec: float,
    fov_deg: float,
    grid_size: int,
    target_epoch: float = 2026.5,
) -> List[Dict]:
    """Propagate 2016.0 Gaia coordinates to 2026.5 and map onto the 64x64 cutout grid."""
    half_fov = fov_deg / 2.0
    cos_dec = max(math.cos(math.radians(center_dec)), 0.05)
    pix_scale = fov_deg / grid_size
    matches: List[Dict] = []

    for star in candidate_rows:
        dt = target_epoch - star["ref_epoch"]
        dec_now = star["dec"] + (star["pmdec"] * dt) / 3_600_000.0
        ra_now = star["ra"] + (star["pmra"] * dt) / (3_600_000.0 * cos_dec)

        d_dec = dec_now - center_dec
        if abs(d_dec) > half_fov:
            continue
        d_ra = ((ra_now - center_ra + 180.0) % 360.0 - 180.0) * cos_dec
        if abs(d_ra) > half_fov:
            continue

        gx = (grid_size / 2.0) - (d_ra / pix_scale)
        gy = (grid_size / 2.0) - (d_dec / pix_scale)
        gx_2016 = (grid_size / 2.0) - (((star["ra"] - center_ra + 180.0) % 360.0 - 180.0) * cos_dec / pix_scale)
        gy_2016 = (grid_size / 2.0) - ((star["dec"] - center_dec) / pix_scale)

        parallax = star["parallax"]
        pm_mas = star["pm"] if star["pm"] is not None else math.hypot(star["pmra"], star["pmdec"])

        matches.append({
            "source_id": star["source_id"],
            "ra": round(ra_now, 6),
            "dec": round(dec_now, 6),
            "gx": round(gx, 2),
            "gy": round(gy, 2),
            "gx_2016": round(gx_2016, 2),
            "gy_2016": round(gy_2016, 2),
            "total_pm_arcsec_yr": round(pm_mas / 1000.0, 4),
            "parallax_mas": round(parallax, 2) if parallax is not None else None,
            "distance_pc": round(1000.0 / parallax, 2) if (parallax and parallax > 0) else None,
            "g_mag": round(star["phot_g_mean_mag"], 2) if star["phot_g_mean_mag"] is not None else None,
            "bp_rp": round(star["bp_rp"], 2) if star["bp_rp"] is not None else None,
            "ruwe": round(star["ruwe"], 2) if star["ruwe"] is not None else None,
            "teff_k": round(star["teff_gspphot"], 0) if star["teff_gspphot"] is not None else None,
        })

    matches.sort(key=lambda s: s["g_mag"] if s["g_mag"] is not None else 99.0)
    return matches[:40]


def query_hybrid_gaia_conesearch(
    center_ra: float, center_dec: float, fov_deg: float, grid_size: int = 64
) -> Tuple[List[Dict], str]:
    """
    Hybrid Gaia DR3 lookup:
      1. Instant local lookup if coordinates fall inside data/gaia/*.csv
      2. Live ESA Gaia TAP fallback for any other region of the sky
    Returns (sources_list, gaia_status) where gaia_status is one of:
      'LOCAL_GAIA_CSV', 'LIVE_ESA_GAIA_TAP', or 'GAIA_TAP_UNAVAILABLE'
    """
    _load_local_csvs()

    if _is_covered_locally(center_ra, center_dec):
        matches = _filter_and_propagate(_LOCAL_ROWS, center_ra, center_dec, fov_deg, grid_size)
        return matches, "LOCAL_GAIA_CSV"

    try:
        remote_rows = _query_esa_gaia_tap(center_ra, center_dec, fov_deg)
        matches = _filter_and_propagate(remote_rows, center_ra, center_dec, fov_deg, grid_size)
        return matches, "LIVE_ESA_GAIA_TAP"
    except Exception as exc:
        print(f"[WARN] Live ESA Gaia TAP lookup failed: {exc}")
        return [], "GAIA_TAP_UNAVAILABLE"

