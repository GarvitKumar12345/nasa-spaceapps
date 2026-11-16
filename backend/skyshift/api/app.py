"""SkyShift HTTP API (FastAPI). Routes: docs/architecture.md section 5.

Run (from backend/):  uv run uvicorn skyshift.api.app:app --host 127.0.0.1 --port 8000
Errors use {"detail": ApiError}. Pixel planes are raw little-endian bytes
(float32 image/variance with NaN = no coverage in display products; uint16 or uint32 mask,
stated in X-SkyShift-Dtype). Observed datasets are read-only: analysis routes answer 409
not_available with the dataset's stated reason. Observed datasets add Gaia DR3 predictions
(/gaia/overlay, /gaia/sources/{source_id}) and alignment diagnostics (/alignment), served from
the recorded catalogue response; the API never queries an archive. Gaia source IDs are strings.
"""

from __future__ import annotations

import re
from typing import Any

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from skyshift import __version__
from skyshift.contracts import (
    AlignmentReport,
    TargetMotionStudy,
    ApiError,
    CatalogAssociation,
    CatalogOverlay,
    CONTRACTS_VERSION,
    Dataset,
    DatasetSummary,
    DetectedSource,
    DifferenceInfo,
    EvidenceRecord,
    EvidenceValidation,
    FitRequest,
    GaiaFrameOverlay,
    GaiaSourceDetail,
    HealthStatus,
    MeasurementSet,
    ModelFit,
    ProviderStatus,
    ReproductionReport,
    ResolveResult,
    SimulationTruth,
    SkyPosition,
    ValidationReport,
)
from skyshift.coords.wcs import description_to_wcs, sky_to_pixel
from skyshift.notebook.evidence import record_to_csv, reproduce_record, validate_record
from skyshift.pipeline.investigation import Investigation, get_investigation
from skyshift.pipeline.observed import ObservedSession
from skyshift.pipeline.observed_gaia import ObservedGaia, observed_gaia
from skyshift.pipeline.target_motion import load_study
from skyshift.providers.base import ProviderUnavailable
from skyshift.providers.gaia_dr3 import load_recorded_field
from skyshift.providers.gaia_dr3.catalog import SOURCE_ID_RE
from skyshift.providers.registry import dataset_provider, list_datasets, load_dataset, provider_statuses
from skyshift.science.astrometry import fit_astrometry
from skyshift.validation.report import report_with_staleness
from skyshift.versions import software_versions

app = FastAPI(title="SkyShift API", version=__version__, description="Local research API for the SkyShift observatory.")
app.add_middleware(GZipMiddleware, minimum_size=2048)


class ApiException(HTTPException):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(status_code=status, detail=ApiError(code=code, message=message, details=details or {}).model_dump())  # type: ignore[arg-type]


@app.exception_handler(ProviderUnavailable)
def _provider_unavailable(_: Request, exc: ProviderUnavailable) -> JSONResponse:
    err = ApiError(code="provider_unavailable", message=str(exc), details={"provider": exc.provider, "capability": exc.capability, "reason": exc.reason})
    return JSONResponse(status_code=503, content={"detail": err.model_dump()})


def _session(dataset_id: str) -> Investigation | ObservedSession:
    """Synthetic datasets get the full investigation; observed datasets a read-only session."""
    try:
        owner = dataset_provider(dataset_id)
        if owner == "synthetic":
            return get_investigation(dataset_id)
        return ObservedSession(load_dataset(dataset_id))
    except KeyError:
        raise ApiException(404, "not_found", f"Unknown dataset {dataset_id!r}.") from None


def _investigation(dataset_id: str, capability: str = "source_detection") -> Investigation:
    """The synthetic investigation, or 409 not_available for observed datasets (never a substitute)."""
    sess = _session(dataset_id)
    if isinstance(sess, ObservedSession):
        cap = sess.capability(capability)
        raise ApiException(409, "not_available", cap.reason or f"{capability} is unavailable for {dataset_id}.",
                           {"capability": capability, "requirements": cap.requirements, "origin": "observed"})
    return sess


def _source_guard(inv: Investigation, source_id: str) -> None:
    try:
        inv.source(source_id)
    except KeyError:
        raise ApiException(404, "not_found", f"Unknown source {source_id!r} in {inv.dataset_id}.") from None


@app.get("/api/health", response_model=HealthStatus)
def health() -> HealthStatus:
    return HealthStatus(status="ok", skyshift_version=__version__, contracts_version=CONTRACTS_VERSION, software=software_versions())


@app.get("/api/providers", response_model=list[ProviderStatus])
def providers() -> list[ProviderStatus]:
    return provider_statuses()


@app.get("/api/datasets", response_model=list[DatasetSummary])
def datasets() -> list[DatasetSummary]:
    return list_datasets()


@app.get("/api/datasets/{dataset_id}", response_model=Dataset)
def dataset(dataset_id: str) -> Dataset:
    return _session(dataset_id).dataset


@app.get("/api/datasets/{dataset_id}/frames/{frame_id}/pixels")
def frame_pixels(dataset_id: str, frame_id: str, plane: str = Query("image", pattern="^(image|variance|mask)$")) -> Response:
    inv = _session(dataset_id)
    try:
        arr, product = inv.pixels(frame_id, plane)
    except KeyError:
        raise ApiException(404, "not_found", f"Unknown frame {frame_id!r}.") from None
    except ValueError as exc:
        raise ApiException(422, "invalid_request", str(exc)) from None
    if plane == "mask":
        dtype = "uint32" if arr.dtype == np.uint32 else "uint16"
        data = np.ascontiguousarray(arr, dtype="<u4" if dtype == "uint32" else "<u2")
    else:
        dtype = "float32"
        data = np.ascontiguousarray(arr, dtype="<f4")
    unit = "" if plane == "mask" else (product.unit if plane == "image" else (product.variance_unit or ""))
    headers = {
        "X-SkyShift-Shape": f"{data.shape[0]},{data.shape[1]}",
        "X-SkyShift-Dtype": dtype,
        "X-SkyShift-Unit": unit,
        "X-SkyShift-Origin": product.provenance.origin,
        "X-SkyShift-Frame": product.id,
        "X-SkyShift-Plane": plane,
        "X-SkyShift-Display-Only": "true" if product.display_only else "false",
        "Cache-Control": "max-age=3600",
    }
    return Response(content=data.tobytes(), media_type="application/octet-stream", headers=headers)


@app.get("/api/datasets/{dataset_id}/sources", response_model=list[DetectedSource])
def sources(dataset_id: str) -> list[DetectedSource]:
    return _investigation(dataset_id, "source_detection").sources


@app.get("/api/datasets/{dataset_id}/sources/{source_id}/measurements", response_model=MeasurementSet)
def measurements(dataset_id: str, source_id: str, method: str = Query("psf_gaussian_fit", pattern="^(psf_gaussian_fit|windowed_centroid)$")) -> MeasurementSet:
    inv = _investigation(dataset_id, "source_measurement")
    _source_guard(inv, source_id)
    return inv.measure(source_id, method)


@app.get("/api/datasets/{dataset_id}/sources/{source_id}/associations", response_model=list[CatalogAssociation])
def associations(dataset_id: str, source_id: str) -> list[CatalogAssociation]:
    # Associations link image-detected sources to the catalogue, so they need source detection.
    inv = _investigation(dataset_id, "source_detection")
    _source_guard(inv, source_id)
    return inv.associations(source_id)


@app.get("/api/datasets/{dataset_id}/catalog", response_model=CatalogOverlay)
def catalog(dataset_id: str, frame_id: str) -> CatalogOverlay:
    sess = _session(dataset_id)
    if isinstance(sess, ObservedSession):
        raise ApiException(409, "not_available", f"{dataset_id} is observed data: its Gaia DR3 predictions are served by /api/datasets/{dataset_id}/gaia/overlay.",
                           {"capability": "catalog_overlay", "route": f"/api/datasets/{dataset_id}/gaia/overlay", "origin": "observed"})
    try:
        return sess.catalog_overlay(frame_id)
    except KeyError:
        raise ApiException(404, "not_found", f"Unknown frame {frame_id!r}.") from None


def _observed_gaia(dataset_id: str, capability: str) -> ObservedGaia:
    sess = _session(dataset_id)
    if not isinstance(sess, ObservedSession):
        raise ApiException(409, "not_available", f"{dataset_id} is simulated: it has its own simulated reference catalogue (/catalog); Gaia DR3 is used for observed data only.",
                           {"capability": capability, "origin": "simulated"})
    cap = sess.capability(capability)
    if cap.status != "available":
        raise ApiException(409, "not_available", cap.reason or f"{capability} is unavailable for {dataset_id}.",
                           {"capability": capability, "requirements": cap.requirements, "origin": "observed"})
    return observed_gaia(sess.bundle, load_recorded_field(dataset_id))


@app.get("/api/datasets/{dataset_id}/gaia/overlay", response_model=GaiaFrameOverlay)
def gaia_overlay(dataset_id: str, frame_id: str) -> GaiaFrameOverlay:
    og = _observed_gaia(dataset_id, "catalog_overlay")
    try:
        return og.overlay(frame_id)
    except KeyError:
        raise ApiException(404, "not_found", f"Unknown frame {frame_id!r}.") from None


@app.get("/api/datasets/{dataset_id}/gaia/sources/{source_id}", response_model=GaiaSourceDetail)
def gaia_source(dataset_id: str, source_id: str, frame_id: str) -> GaiaSourceDetail:
    if not SOURCE_ID_RE.match(source_id):
        raise ApiException(422, "invalid_request", "A Gaia DR3 source_id is a decimal integer string (sent as a string, never a number).")
    og = _observed_gaia(dataset_id, "catalog_overlay")
    try:
        return og.source_detail(frame_id, source_id)
    except KeyError as exc:
        raise ApiException(404, "not_found", str(exc.args[0]) if exc.args else "not found") from None


@app.get("/api/datasets/{dataset_id}/alignment", response_model=AlignmentReport)
def alignment(dataset_id: str) -> AlignmentReport:
    return _observed_gaia(dataset_id, "alignment_diagnostics").report()


@app.get("/api/datasets/{dataset_id}/target-motion", response_model=TargetMotionStudy)
def target_motion(dataset_id: str) -> TargetMotionStudy:
    """The recorded motion study of a field's named target, as recorded (stale flagged); 409 where none exists."""
    sess = _session(dataset_id)
    if not isinstance(sess, ObservedSession):
        raise ApiException(409, "not_available", f"{dataset_id} is simulated: target-motion studies exist for observed fields only.",
                           {"capability": "target_motion_study", "origin": "simulated"})
    cap = sess.capability("target_motion_study")
    if cap.status != "available":
        raise ApiException(409, "not_available", cap.reason or f"No target-motion study for {dataset_id}.",
                           {"capability": "target_motion_study", "requirements": cap.requirements, "origin": "observed"})
    return load_study(dataset_id)


def _difference(dataset_id: str, a: str, b: str) -> tuple[DifferenceInfo, np.ndarray | None]:
    inv = _investigation(dataset_id, "difference_imaging")
    try:
        return inv.difference(a, b)
    except KeyError as exc:
        raise ApiException(404, "not_found", f"Unknown frame {exc.args[0]!r}.") from None


@app.get("/api/datasets/{dataset_id}/difference/info", response_model=DifferenceInfo)
def difference_info(dataset_id: str, a: str, b: str) -> DifferenceInfo:
    return _difference(dataset_id, a, b)[0]


@app.get("/api/datasets/{dataset_id}/difference/pixels")
def difference_pixels(dataset_id: str, a: str, b: str) -> Response:
    info, arr = _difference(dataset_id, a, b)
    if arr is None:
        raise ApiException(409, "incompatible_frames", "Frames are not compatible for a difference preview: " + " ".join(info.reasons), {"reasons": info.reasons})
    data = np.ascontiguousarray(arr, dtype="<f4")
    return Response(
        content=data.tobytes(),
        media_type="application/octet-stream",
        headers={
            "X-SkyShift-Shape": f"{data.shape[0]},{data.shape[1]}",
            "X-SkyShift-Dtype": "float32",
            "X-SkyShift-Unit": "electron",
            "X-SkyShift-Origin": "derived_measurement",
            "X-SkyShift-Frame": f"{info.frame_b} - {info.frame_a}",
            "X-SkyShift-Plane": "difference",
            "X-SkyShift-Display-Only": "true",
        },
    )


@app.get("/api/datasets/{dataset_id}/truth", response_model=SimulationTruth)
def truth(dataset_id: str) -> SimulationTruth:
    inv = _session(dataset_id)
    if inv.bundle.truth is None:
        raise ApiException(404, "not_synthetic", f"{dataset_id} is not a simulated dataset; no simulation truth exists.")
    return inv.bundle.truth


_SOURCE_ID = re.compile(r"^(?:(?P<ds>[\w-]+):)?(?P<sid>S\d{3})$", re.I)


@app.get("/api/resolve", response_model=ResolveResult)
def resolve(q: str = Query(..., min_length=1, max_length=200), dataset_id: str | None = None) -> ResolveResult:
    text = q.strip()
    match = _SOURCE_ID.match(text)
    if match:
        ds = match.group("ds") or dataset_id
        sid = match.group("sid").upper()
        if ds:
            sess = _session(ds)
            if isinstance(sess, ObservedSession):
                return ResolveResult(query=q, kind="unresolved", message=f"{ds} is observed archive data: SkyShift has no source detections there, so source IDs do not apply.")
            inv = sess
            try:
                src = inv.source(sid)
            except KeyError:
                return ResolveResult(query=q, kind="unresolved", message=f"No source {sid} in {ds}.")
            return ResolveResult(query=q, kind="source_id", source_id=sid, position=src.position, in_dataset_field=True, message=f"Source {sid} in {ds}.")
    position: SkyPosition | None = None
    # Sexagesimal input (colons or h/m/s/d letters) has RA in hours; otherwise both values are degrees.
    sexagesimal = bool(re.search(r"[:hms°dD]", text))
    try:
        c = SkyCoord(text.replace(",", " "), unit=(u.hourangle, u.deg) if sexagesimal else (u.deg, u.deg), frame="icrs")
        position = SkyPosition(ra_deg=float(c.ra.deg) % 360.0, dec_deg=float(c.dec.deg))
    except (ValueError, TypeError):
        position = None
    if position is None:
        return ResolveResult(
            query=q, kind="unresolved",
            message="Target-name resolution (e.g. Sesame) is not available in this build. Enter coordinates (degrees or sexagesimal) or a source ID such as S003.",
        )
    in_field = None
    if dataset_id:
        inv = _session(dataset_id)
        w = description_to_wcs(inv.dataset.common_grid)
        x, y = sky_to_pixel(w, position.ra_deg, position.dec_deg)
        ny, nx = inv.dataset.common_grid.shape
        in_field = bool(-0.5 <= float(x) <= nx - 0.5 and -0.5 <= float(y) <= ny - 0.5)
    msg = "Coordinates parsed (ICRS)." + ("" if in_field is None else (" Inside the dataset field." if in_field else " Outside the loaded dataset field; real-archive search is not connected in this build."))
    return ResolveResult(query=q, kind="coordinates", position=position, in_dataset_field=in_field, message=msg)


@app.post("/api/fits/astrometric", response_model=ModelFit)
def fit(request: FitRequest) -> ModelFit:
    inv = _investigation(request.dataset_id, "astrometric_fit")
    _source_guard(inv, request.source_id)
    extra = [
        "Synthetic dataset: positions are geometric (no aberration, light deflection, or light-time); "
        "the observer is exactly the geocentre by declaration."
    ] if inv.bundle.dataset.origin == "simulated" else []
    try:
        observer = next(o.observer for o in inv.dataset.observations if o.status == "available")
        return fit_astrometry(request, observer=observer, extra_assumptions=extra)
    except ValueError as exc:
        raise ApiException(422, "invalid_request", str(exc)) from None


@app.post("/api/evidence/validate", response_model=EvidenceValidation)
def evidence_validate(record: Any = Body(...)) -> EvidenceValidation:
    return validate_record(record)


def _parse_record(raw: Any) -> EvidenceRecord:
    result = validate_record(raw)
    if not result.valid or result.record is None:
        raise ApiException(422, "invalid_record", "Evidence record is invalid: " + "; ".join(result.errors[:5]), {"errors": result.errors})
    return result.record


@app.post("/api/evidence/reproduce", response_model=ReproductionReport)
def evidence_reproduce(record: Any = Body(...)) -> ReproductionReport:
    return reproduce_record(_parse_record(record), load_dataset=load_dataset)


@app.post("/api/evidence/csv", response_class=PlainTextResponse)
def evidence_csv(record: Any = Body(...)) -> PlainTextResponse:
    parsed = _parse_record(record)
    name = f"skyshift-{parsed.dataset.dataset_id}-{parsed.source.source_id}-{parsed.id[:8]}.csv"
    return PlainTextResponse(record_to_csv(parsed), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/validation", response_model=ValidationReport)
def validation() -> ValidationReport:
    return report_with_staleness()
