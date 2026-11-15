"""Bounded live retrieval of Gaia DR3 for one SPHEREx field, with a retrieval manifest.

    cd backend
    uv run python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-barnard            # query + record
    uv run python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-barnard --dry-run  # print the ADQL only

Steps: (1) footprint of every cached SPHEREx cutout of the field (corners at the
pixel edges through each cutout's archive WCS) and the interval from J2016.0
(TCB) to each exposure mid-time; (2) the search circle (query.search_geometry);
(3) an independent COUNT(*) of the circle; (4) the field query on
gaiadr3.gaia_source (all columns listed in reference.FIELD_COLUMNS, no
magnitude cut, ORDER BY source_id); (5) a second query in which the archive
itself propagates a pinned subset to each exposure epoch (EPOCH_PROP), recorded
only as an independent check of SkyShift's propagation; (6) schema/provenance
checks. The VOTable responses are written gzip-compressed (mtime 0) next to the
manifest under fixtures/gaia_dr3/<field>/. The API never queries Gaia.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys

import numpy as np

from skyshift.coords.time import make_epoch
from skyshift.providers.gaia_dr3 import reference as ref
from skyshift.providers.gaia_dr3.catalog import parse_gaia_votable, schema_checks
from skyshift.providers.gaia_dr3.paths import EPOCH_PROP_NAME, OVERFLOW_PROBE_NAME, RESPONSE_NAME, epoch_prop_path, field_dir, manifest_path, response_path
from skyshift.providers.gaia_dr3.query import SearchGeometry, build_count_query, build_field_query, search_geometry, tap_sync_fields
from skyshift.providers.spherex.http import ArchiveClient, ArchiveRequestFailed, utc_now
from skyshift.versions import software_versions

MANIFEST_SCHEMA = "skyshift.gaia-dr3-manifest/1"
MAX_RESPONSE_BYTES = 30_000_000
N_PINNED_REFERENCE_LIKE = 6


def gaia_client() -> ArchiveClient:
    return ArchiveClient(allowed_prefixes=ref.ALLOWED_PREFIXES, user_agent=ref.USER_AGENT, max_concurrency=1, max_attempts=6, timeout_s=180.0)


def _sep_deg(ra1: np.ndarray, d1: np.ndarray, ra2: float, d2: float) -> np.ndarray:
    a1, b1, a2, b2 = np.radians(ra1), np.radians(d1), np.radians(ra2), np.radians(d2)
    c = np.sin(b1) * np.sin(b2) + np.cos(b1) * np.cos(b2) * np.cos(a1 - a2)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def field_footprints(field_id: str) -> tuple[float, float, list[dict]]:
    """(centre ra, centre dec, one record per cached cutout) from the SPHEREx manifest + cache."""
    from skyshift.providers.spherex.fields import PRESETS
    from skyshift.providers.spherex.fitsfile import read_spectral_image
    from skyshift.providers.spherex.paths import cutout_path
    from skyshift.providers.spherex.paths import manifest_path as spherex_manifest_path

    preset = PRESETS[field_id]
    sm = json.loads(spherex_manifest_path(field_id).read_text(encoding="utf-8"))
    ref_epoch = make_epoch(ref.REFERENCE_EPOCH_JYEAR, "jyear", ref.REFERENCE_EPOCH_SCALE)
    out = []
    for d in sm["downloads"]:
        if d.get("status") != "downloaded":
            continue
        path = cutout_path(field_id, d["file_name"])
        if not path.exists():
            raise FileNotFoundError(f"SPHEREx cutout {d['file_name']} not cached; run: uv run python -m skyshift.providers.spherex.fetch --field {field_id} --from-manifest")
        img = read_spectral_image(path.read_bytes())
        ny, nx = img.shape
        xs = np.array([-0.5, nx - 0.5, nx - 0.5, -0.5])
        ys = np.array([-0.5, -0.5, ny - 0.5, ny - 0.5])
        ra, dec = img.wcs.all_pix2world(xs, ys, 0)
        mid = make_epoch(str(img.image_header["DATE-AVG"]).strip(), "isot", "utc")
        dt = (mid.mjd_tdb - ref_epoch.mjd_tdb) / 365.25
        out.append({
            "key": d["key"], "file_name": d["file_name"], "shape": [ny, nx],
            "corners_icrs_deg": [[float(a) % 360.0, float(b)] for a, b in zip(ra, dec)],
            "max_corner_distance_deg": float(_sep_deg(ra, dec, preset.ra_deg, preset.dec_deg).max()),
            "mid_utc": mid.value, "mid_mjd_tdb": mid.mjd_tdb, "dt_from_catalog_epoch_yr": dt,
        })
    if not out:
        raise RuntimeError(f"no downloaded SPHEREx cutouts recorded for {field_id}")
    return preset.ra_deg, preset.dec_deg, out


def geometry_for(field_id: str) -> tuple[SearchGeometry, list[dict]]:
    ra, dec, fps = field_footprints(field_id)
    return search_geometry(ra, dec, max(f["max_corner_distance_deg"] for f in fps), max(f["dt_from_catalog_epoch_yr"] for f in fps)), fps


def _pinned_ids(cat, fps: list[dict]) -> list[str]:
    """Deterministic pinned set: the highest-proper-motion source plus bright, clean 5/6-parameter stars."""
    pm = np.hypot(np.nan_to_num(cat.columns["pmra"]), np.nan_to_num(cat.columns["pmdec"]))
    pinned = [cat.source_id[int(np.argmax(pm))]]
    g = cat.columns["phot_g_mean_mag"]
    aps = cat.columns["astrometric_params_solved"]
    ruwe = cat.columns["ruwe"]
    ok = np.isfinite(g) & (g > 11.5) & (g < 15.5) & (aps != 3) & np.isfinite(ruwe) & (ruwe < ref.RUWE_THRESHOLD)
    order = [i for i in np.argsort(np.where(ok, g, np.inf)) if ok[i]]
    pinned += [cat.source_id[int(i)] for i in order[:N_PINNED_REFERENCE_LIKE]]
    # one 2-parameter source (no motion) so that NULL handling is pinned as well
    two = [i for i in np.argsort(np.where(aps == 3, g, np.inf)) if aps[i] == 3]
    if two:
        pinned.append(cat.source_id[int(two[0])])
    return pinned


def _pinned_rows(cat, ids: list[str]) -> list[dict]:
    return [cat.row(cat.index[s]) for s in ids]


EPOCH_PROP_ERROR_ARGS = (
    "ra, dec, parallax, pmra, pmdec, radial_velocity, ra_error, dec_error, parallax_error, pmra_error, pmdec_error, radial_velocity_error, "
    "ra_dec_corr, ra_parallax_corr, ra_pmra_corr, ra_pmdec_corr, dec_parallax_corr, dec_pmra_corr, dec_pmdec_corr, "
    "parallax_pmra_corr, parallax_pmdec_corr, pmra_pmdec_corr"
)


def build_epoch_prop_query(source_ids: list[str], target_epochs_jyear: list[float]) -> str:
    """Archive-side propagation of pinned sources to each target epoch (independent check only).

    ESDC_EPOCH_PROP(ra, dec, plx, pmra, pmdec, rv, T0, T1) returns double[6] = (ra deg, dec deg,
    plx mas, pmra mas/yr, pmdec mas/yr, mu_r mas/yr); ESDC_EPOCH_PROP_ERROR(..., T0, T1) returns
    double[21] = 6 uncertainties then 15 correlations. Both implement the ESA 1997 rigorous
    propagation without light time; NULL inputs are treated as 0 by the archive. Target epochs are
    Julian years on the Gaia (TCB) time axis.
    """
    if not source_ids or len(source_ids) > 50:
        raise ValueError("1..50 pinned sources")
    if not target_epochs_jyear or len(target_epochs_jyear) > 30:
        raise ValueError("1..30 target epochs")
    ids = ", ".join(source_ids)
    sel = []
    for k, t in enumerate(target_epochs_jyear):
        sel.append(f"ESDC_EPOCH_PROP(ra, dec, parallax, pmra, pmdec, radial_velocity, ref_epoch, {t:.8f}) AS p{k}")
        sel.append(f"ESDC_EPOCH_PROP_ERROR({EPOCH_PROP_ERROR_ARGS}, ref_epoch, {t:.8f}) AS e{k}")
    return f"SELECT source_id, {', '.join(sel)} FROM {ref.GAIA_TABLE} WHERE source_id IN ({ids}) ORDER BY source_id"


def jyear_tcb(mjd_tdb: float) -> float:
    """Julian epoch on the TCB axis of an instant given as MJD(TDB) (Gaia epochs are TCB Julian years)."""
    from astropy.time import Time

    return float(Time(mjd_tdb, format="mjd", scale="tdb").tcb.jyear)


def _write_gz(path, body: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    gz = gzip.compress(body, compresslevel=9, mtime=0)
    path.write_bytes(gz)
    return hashlib.sha256(gz).hexdigest()


def run(field_id: str, *, dry_run: bool = False, client: ArchiveClient | None = None, epoch_prop: bool = True) -> dict:
    geom, fps = geometry_for(field_id)
    field_adql = build_field_query(geom)
    count_adql = build_count_query(geom)
    print(geom.derivation())
    print(field_adql)
    if dry_run:
        return {"geometry": geom.as_dict(), "field_adql": field_adql, "count_adql": count_adql}
    client = client or gaia_client()
    started = utc_now()
    notes: list[str] = []
    # (3) independent row count
    body, count_rec = client.post_form(ref.TAP_SYNC_URL, tap_sync_fields(count_adql, "csv"), max_bytes=10_000)
    lines = body.decode("utf-8").strip().splitlines()
    if len(lines) != 2 or lines[0].strip() != "n_rows":
        raise RuntimeError(f"unexpected COUNT response: {lines[:3]}")
    n_count = int(lines[1].strip())
    # (4) field query
    body, field_rec = client.post_form(ref.TAP_SYNC_URL, tap_sync_fields(field_adql), max_bytes=MAX_RESPONSE_BYTES)
    retrieved = utc_now()
    cat = parse_gaia_votable(body)
    checks = schema_checks(cat, expected_rows=n_count)
    failed = [c for c in checks if c.status == "fail"]
    if failed:
        raise RuntimeError("Gaia response failed schema/provenance checks: " + "; ".join(f"{c.id}: {c.detail}" for c in failed))
    gz_sha = _write_gz(response_path(field_id), body)
    pinned = _pinned_ids(cat, fps)
    # (5) archive-side propagation of the pinned subset (independent check only)
    ep: dict | None = None
    if epoch_prop:
        epochs = sorted({round(jyear_tcb(f["mid_mjd_tdb"]), 8) for f in fps})
        ep_adql = build_epoch_prop_query(pinned, epochs)
        try:
            ep_body, ep_rec = client.post_form(ref.TAP_SYNC_URL, tap_sync_fields(ep_adql), max_bytes=5_000_000)
            ep_sha = _write_gz(epoch_prop_path(field_id), ep_body)
            ep = {"adql": ep_adql, "target_epochs_jyear_tcb": epochs, "record": ep_rec.as_dict(), "response_file": EPOCH_PROP_NAME,
                  "response_sha256_gz": ep_sha, "status": "recorded",
                  "note": "Exposure mid-times converted from UTC to Julian years on the TCB axis (the Gaia time scale used by ref_epoch). "
                          "Recorded only as an independent check of skyshift.science.epoch_propagation; never used for predictions."}
        except ArchiveRequestFailed as exc:
            ep = {"adql": ep_adql, "target_epochs_jyear_tcb": epochs, "record": exc.record.as_dict(), "status": "failed", "error": exc.reason}
            notes.append(f"Archive-side ESDC_EPOCH_PROP check query failed ({exc.reason}); propagation checks fall back to astropy/ERFA only.")
    # (6) truncation probe: the same ADQL with MAXREC=5 must be reported as OVERFLOW (records the archive's signalling)
    probe_fields = {**tap_sync_fields(field_adql), "MAXREC": "5"}
    probe: dict
    try:
        pb, prec = client.post_form(ref.TAP_SYNC_URL, probe_fields, max_bytes=2_000_000)
        pcat = parse_gaia_votable(pb)
        probe_sha = _write_gz(field_dir(field_id) / OVERFLOW_PROBE_NAME, pb)
        probe = {"form": {k: v for k, v in probe_fields.items() if k != "QUERY"}, "record": prec.as_dict(), "n_rows": len(pcat),
                 "query_status": pcat.infos.get("QUERY_STATUS"), "query_status_all": pcat.infos.get("QUERY_STATUS_ALL"),
                 "response_file": OVERFLOW_PROBE_NAME, "response_sha256_gz": probe_sha}
    except ArchiveRequestFailed as exc:
        probe = {"status": "failed", "error": exc.reason}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "field": field_id,
        "catalog": ref.GAIA_TABLE,
        "release": cat.params.get("RELEASE"),
        "endpoint": ref.TAP_SYNC_URL,
        "started_utc": started,
        "retrieved_utc": retrieved,
        "software": [v.model_dump() for v in software_versions()],
        "geometry": {**geom.as_dict(), "derivation": geom.derivation()},
        "footprints": fps,
        "count_query": {"adql": count_adql, "form": tap_sync_fields(count_adql, "csv"), "record": count_rec.as_dict(), "n_rows": n_count},
        "field_query": {
            "adql": field_adql, "form": tap_sync_fields(field_adql), "record": field_rec.as_dict(), "n_rows": len(cat),
            "response_file": RESPONSE_NAME, "response_sha256": field_rec.sha256, "response_sha256_gz": gz_sha,
            "job_id": cat.infos.get("JOBID"), "query_status": cat.infos.get("QUERY_STATUS"),
            "fields": [{"name": f.name, "unit": f.unit, "datatype": f.datatype, "ucd": f.ucd} for f in cat.fields],
            "params": cat.params, "coosys": cat.coosys,
        },
        "checks": [c.model_dump() for c in checks],
        "pinned_sources": _pinned_rows(cat, pinned),
        "epoch_prop": ep,
        "overflow_probe": probe,
        "acknowledgement": ref.ACKNOWLEDGEMENT,
        "citations": list(ref.CITATIONS),
        "notes": notes + [
            "Gaia DR3 is a frozen release: a different row count for the same ADQL is reported as a count change, separately from schema, "
            "provenance and pinned-value checks (which must not change).",
            "Source IDs are stored and served as decimal strings (64-bit integers exceed exact JavaScript/float64 integers).",
        ],
        "http_log": [r.as_dict() for r in client.log],
    }
    path = manifest_path(field_id)
    field_dir(field_id).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1, default=_json_default) + "\n", encoding="utf-8")
    print(f"{len(cat)} rows (COUNT {n_count}); wrote {path}")
    return manifest


def _json_default(o: object) -> object:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--field", default="spherex-dr1-barnard")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-epoch-prop", action="store_true", help="skip the archive-side EPOCH_PROP check query")
    args = parser.parse_args(argv)
    run(args.field, dry_run=args.dry_run, epoch_prop=not args.no_epoch_prop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
