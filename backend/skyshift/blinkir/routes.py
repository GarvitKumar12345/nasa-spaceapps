"""BlinkIR simulation API. Live extraction is explicitly unavailable, never substituted."""
import json
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import Response

from skyshift.blinkir.simulation import BENCHMARK_TARGETS, SPHEREX_BANDS, build_simulation

router = APIRouter(prefix="/api/blinkir", tags=["BlinkIR educational simulation"])
LIMITS = ["Synthetic scenes and model curves adapted from the supplied BlinkIR generator; not observed epochs or calibrated spectra.",
          "102 illustrative wavelength samples are not 102 observed SPHEREx channels; detector ranges provide context only.",
          "Water and methane markers are educational references, not feature identifications or atmospheric evidence.",
          "Selected pixels report simulated intensity only; spectral curves belong to the preset model, not a clicked-source extraction.",
          "No measured motion, calibrated flux, artifact verification or discovery claim is produced."]


@router.get("/presets")
def presets():
    return {"origin": "simulated", "presets": list(BENCHMARK_TARGETS.values()), "detectors": SPHEREX_BANDS}


@lru_cache(maxsize=5)
def scene(target: str):
    if target not in BENCHMARK_TARGETS:
        raise HTTPException(404, detail="Unknown simulation preset. Name resolution and arbitrary-coordinate observations are unavailable.")
    return {"schema": "skyshift.blinkir-simulation/1", "origin": "simulated", "spectrum_origin": "model_prediction",
            "preset": BENCHMARK_TARGETS[target], "units": "arbitrary simulation units", "epochs": ["Simulated epoch A", "Simulated epoch B"],
            "generator": "blinkir-educational/1; SHA-256 preset seed; 64 x 64 grid", "limitations": LIMITS,
            "quality": "Simulation: no archive flags or exposure count apply.", **build_simulation(target)}


@router.get("/simulation/{target}")
def simulation(target: str):
    return scene(target)


@router.get("/observations")
def observations():
    raise HTTPException(409, detail="BlinkIR live image/spectrum extraction is unavailable. No archive request was made and no synthetic fallback was substituted. Validated recorded observations are in Observatory.")


class LessonExport(BaseModel):
    preset: str
    x: int = Field(32, ge=0, le=63)
    y: int = Field(32, ge=0, le=63)
    detector: int = Field(1, ge=1, le=6)
    notes: str = Field("", max_length=2000)


@router.post("/export")
def export_lesson(req: LessonExport):
    data = scene(req.preset)
    exported = {"schema": "skyshift.blinkir-lesson/1", "origin": "simulated", "preset": data["preset"], "generator": data["generator"],
                "units": data["units"], "selected_pixel": {"x": req.x, "y": req.y, "values": [a[req.y][req.x] for a in data["images"]]},
                "detector_context": req.detector, "spectrum_origin": "model_prediction", "illustrative_model_samples": data["spectrum"],
                "measured_motion": None, "calibrated_flux": None, "notes": req.notes, "limitations": LIMITS}
    return Response(json.dumps(exported, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="blinkir-simulation-lesson.json"'})
