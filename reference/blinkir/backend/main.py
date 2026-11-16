"""SkyShift FastAPI Application — 2026 NASA Space Apps Challenge (Planet X & SPHEREx)."""

import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.targets import BENCHMARK_TARGETS, SPHEREX_BANDS
from backend.irsa_pipeline import (
    load_cached_target,
    resolve_object_name,
    fetch_and_coadd_live_cutouts,
)
from backend.gaia_catalog import query_hybrid_gaia_conesearch

app = FastAPI(
    title="SkyShift — 4D SPHEREx Time-Machine & Citizen Spectrometer",
    description="Multi-epoch Blink Comparator & 102-band Infrared Spectrometer for NASA SPHEREx DR1 & QR3.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


class DiscoveryExportRequest(BaseModel):
    target_name: str
    ra: float
    dec: float
    fov_deg: float
    measured_shift_arcsec: float
    proper_motion_arcsec_yr: float
    flag_status: str
    notes: Optional[str] = ""


@app.get("/api/health")
def health_check():
    return {"status": "ok", "release": "SPHEREx DR1 + QR3 (Nov 2026)", "bands": 6, "channels": 102}


@app.get("/api/presets")
def list_presets():
    return {
        "targets": list(BENCHMARK_TARGETS.values()),
        "bands": SPHEREX_BANDS,
    }


@app.get("/api/sky-cutout")
def get_sky_cutout(
    query: Optional[str] = Query(None, description="Object name, preset ID, or 'RA, Dec'"),
    ra: Optional[float] = Query(None, description="Right Ascension in degrees"),
    dec: Optional[float] = Query(None, description="Declination in degrees"),
    fov: float = Query(0.04, ge=0.01, le=0.5, description="Field of view in degrees"),
    prefer_live: bool = Query(False, description="Force live IRSA SIA2 cutout download"),
):
    # Coerce FastAPI Query defaults if called as a normal Python function
    if not isinstance(fov, (int, float)):
        fov = float(getattr(fov, "default", 0.04) or 0.04)
    if not isinstance(prefer_live, bool):
        prefer_live = bool(getattr(prefer_live, "default", False))
    if not isinstance(query, str) and query is not None:
        query = getattr(query, "default", None)
    if not isinstance(ra, (int, float)) and ra is not None:
        ra = getattr(ra, "default", None)
    if not isinstance(dec, (int, float)) and dec is not None:
        dec = getattr(dec, "default", None)

    preset_id = None
    resolved_name = "Custom Coordinate"

    if query:
        try:
            resolved = resolve_object_name(query)
            ra = resolved["ra"]
            dec = resolved["dec"]
            resolved_name = resolved["resolved_name"]
            preset_id = resolved["preset_id"]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not resolve target '{query}': {exc}")

    if ra is None or dec is None:
        preset_id = "WISE_0855"
        meta = BENCHMARK_TARGETS[preset_id]
        ra, dec, resolved_name = meta["ra"], meta["dec"], meta["name"]

    if not preset_id:
        for key, meta in BENCHMARK_TARGETS.items():
            if abs(meta["ra"] - ra) < 0.01 and abs(meta["dec"] - dec) < 0.01:
                preset_id = key
                resolved_name = meta["name"]
                break

    def _attach_gaia(data_dict: dict) -> dict:
        target_ra = data_dict.get("ra", ra)
        target_dec = data_dict.get("dec", dec)
        gaia_sources, gaia_mode = query_hybrid_gaia_conesearch(
            target_ra, target_dec, fov, data_dict.get("grid_size", 64)
        )
        data_dict["gaia_sources"] = gaia_sources
        data_dict["gaia_source_mode"] = gaia_mode
        data_dict["gaia_status"] = gaia_mode
        if "spectrum" not in data_dict and "spectrum_102" in data_dict:
            data_dict["spectrum"] = data_dict["spectrum_102"]
        if "epoch1" not in data_dict and "epoch1_image" in data_dict:
            data_dict["epoch1"] = data_dict["epoch1_image"]
        if "epoch2" not in data_dict and "epoch2_image" in data_dict:
            data_dict["epoch2"] = data_dict["epoch2_image"]
        return data_dict

    if preset_id and not prefer_live:
        cached = load_cached_target(preset_id)
        if cached:
            cached["resolved_name"] = resolved_name
            return _attach_gaia(cached)

    try:
        live_payload = fetch_and_coadd_live_cutouts(ra=ra, dec=dec, fov_deg=fov)
        live_payload["resolved_name"] = resolved_name
        return _attach_gaia(live_payload)
    except Exception as exc:
        if preset_id:
            cached = load_cached_target(preset_id)
            if cached:
                cached["resolved_name"] = resolved_name
                cached["fallback_notice"] = f"Live IRSA timeout ({exc}); serving cached DR1+QR3 benchmark data."
                return _attach_gaia(cached)
        raise HTTPException(status_code=502, detail=f"IRSA SIA2 query failed: {exc}")


@app.post("/api/export-candidate")
def export_discovery_card(req: DiscoveryExportRequest):
    """Generate a structured citizen-science Discovery Card payload ready for submission."""
    card = {
        "schema": "SkyShift-NASA-SpaceApps-2026-DiscoveryCard-v1",
        "target_label": req.target_name,
        "coordinates_icrs": {
            "ra_deg": round(req.ra, 6),
            "dec_deg": round(req.dec, 6),
            "fov_deg": req.fov_deg,
        },
        "kinematics": {
            "measured_shift_arcsec": round(req.measured_shift_arcsec, 3),
            "estimated_proper_motion_arcsec_yr": round(req.proper_motion_arcsec_yr, 3),
        },
        "artifact_shield_status": req.flag_status,
        "observer_notes": req.notes,
        "data_attribution": [
            "NASA/IPAC Infrared Science Archive (IRSA) SPHEREx DR1 (spherex_dr1)",
            "NASA/IPAC Infrared Science Archive (IRSA) SPHEREx QR3 (spherex_qr3)",
            "AllWISE & ESA Gaia DR3 Astrometric Reference Catalogs",
        ],
    }
    return JSONResponse(content=card)


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
