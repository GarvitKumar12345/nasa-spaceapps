"""Evidence notebook backend: validation, staleness detection, reproduction, CSV export.

Records are stored in the browser; the backend is the single place that
validates them against the contract and re-derives synthetic results.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from skyshift.contracts import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceRecord,
    EvidenceValidation,
    FitRequest,
    ReproductionCheck,
    ReproductionReport,
    SourceMeasurement,
)
from skyshift.providers.base import DatasetBundle
from skyshift.science.astrometry import fit_astrometry, fit_input_hash
from skyshift.synthetic.generator import GENERATOR_VERSION
from skyshift.versions import software_versions

SUPPORTED_SCHEMAS = (EVIDENCE_SCHEMA_VERSION,)
POSITION_TOLERANCE_DEG = 1e-9  # 3.6 microarcsec: same code, seed and pinned versions should agree to rounding
FLUX_RELATIVE_TOLERANCE = 1e-6
PARAMETER_TOLERANCE = 1e-6  # in the parameter's unit (mas or mas/yr)

CSV_COLUMNS = [
    "record_id", "dataset_id", "release", "source_id", "measurement_id", "origin", "frame_id", "observation_id", "band_id",
    "epoch_utc", "epoch_mjd_tdb", "status", "included", "method", "method_version", "x_px", "y_px", "ra_deg", "dec_deg",
    "sigma_ra_cosdec_mas", "sigma_dec_mas", "corr_ra_dec", "flux", "flux_err", "flux_unit", "snr", "quality_status", "quality_flags",
]


def _usable(m: SourceMeasurement) -> bool:
    return m.status == "measured" and None not in (m.ra_deg, m.dec_deg, m.sigma_ra_cosdec_mas, m.sigma_dec_mas)


def recompute_fit_status(rec: EvidenceRecord) -> tuple[str, bool | None, list[str]]:
    """('current' | 'stale' | 'none', input-hash match, reasons) from the record's own content."""
    if rec.fit is None:
        return "none", None, []
    reasons: list[str] = []
    by_id = {m.id: m for m in rec.measurements}
    fit_ids = rec.fit.inputs.measurement_ids
    missing = [i for i in fit_ids if i not in by_id]
    if missing:
        return "stale", False, [f"The fit used {len(missing)} measurement(s) not present in the record."]
    matches = fit_input_hash(rec.fit.inputs, [by_id[i] for i in fit_ids]) == rec.fit.input_hash
    if not matches:
        reasons.append("Fit inputs or measurement values differ from those the fit was computed with (input hash mismatch).")
    included_usable = {i for i in rec.included_measurement_ids if i in by_id and _usable(by_id[i])}
    if included_usable != set(fit_ids):
        reasons.append("The included measurements changed after the fit was computed.")
    return ("current" if not reasons else "stale"), matches, reasons


def validate_record(raw: Any) -> EvidenceValidation:
    """Validate a raw JSON record: schema, semantics, and fit freshness."""
    if not isinstance(raw, dict):
        return EvidenceValidation(valid=False, errors=["The record must be a JSON object."], recomputed_fit_status="none")
    schema = raw.get("schema_version")
    if schema not in SUPPORTED_SCHEMAS:
        return EvidenceValidation(valid=False, errors=[f"Unsupported schema_version {schema!r}; this build reads {', '.join(SUPPORTED_SCHEMAS)}."],
                                  recomputed_fit_status="none")
    try:
        rec = EvidenceRecord.model_validate(raw)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:50]]
        return EvidenceValidation(valid=False, errors=errors, recomputed_fit_status="none")
    errors: list[str] = []
    warnings: list[str] = []
    ids = {m.id for m in rec.measurements}
    if missing := [i for i in rec.included_measurement_ids if i not in ids]:
        errors.append(f"included_measurement_ids lists {len(missing)} id(s) that are not in measurements.")
    for m in rec.measurements:
        if m.source_id != rec.source.source_id or m.dataset_id != rec.dataset.dataset_id:
            errors.append(f"Measurement {m.id} belongs to another source or dataset.")
    origin = rec.dataset.origin
    if origin == "simulated" and rec.record_label != "synthetic training record":
        errors.append("Records of simulated datasets must be labelled 'synthetic training record'.")
    if origin == "observed" and rec.record_label != "candidate for review":
        errors.append("Records of observed datasets must be labelled 'candidate for review'.")
    if rec.simulation is not None and origin != "simulated":
        errors.append("A simulation section is only allowed for simulated datasets.")
    if origin == "simulated" and (rec.simulation is None or rec.dataset.seed is None):
        warnings.append("No simulation seed recorded: the record cannot be reproduced.")
    if rec.simulation is not None and rec.simulation.truth is not None and rec.simulation.truth.origin != "simulation_truth":
        errors.append("Simulation truth must carry origin 'simulation_truth'.")
    if rec.dataset.provider == "synthetic" and rec.dataset.generator_version not in (None, GENERATOR_VERSION):
        warnings.append(f"Generator version {rec.dataset.generator_version} differs from this build ({GENERATOR_VERSION}); reproduction may differ.")
    status, matches, reasons = recompute_fit_status(rec)
    warnings.extend(reasons)
    if rec.fit is not None and rec.fit_status != status:
        warnings.append(f"Record states fit_status '{rec.fit_status}', but the content gives '{status}'.")
    if rec.fit is None and rec.fit_status != "none":
        warnings.append("Record states a fit status but contains no fit.")
    valid = not errors
    return EvidenceValidation(
        valid=valid,
        errors=errors,
        warnings=warnings,
        fit_input_hash_matches=matches,
        recomputed_fit_status=status,  # type: ignore[arg-type]
        record=rec.model_copy(update={"fit_status": status}) if valid else None,
    )


def reproduce_record(rec: EvidenceRecord, load_dataset: Callable[[str, int | None], DatasetBundle] | None = None) -> ReproductionReport:
    """Re-derive a synthetic record from its seed and compare every saved value."""
    from skyshift.pipeline.investigation import get_investigation

    software = software_versions()
    if rec.dataset.origin != "simulated":
        return ReproductionReport(reproducible=False, status="not_reproducible", software=software,
                                  reason="Observed records cannot be re-derived: archive providers are not implemented in this build.")
    if rec.dataset.seed is None:
        return ReproductionReport(reproducible=False, status="not_reproducible", reason="No seed is recorded.", software=software)
    if rec.dataset.generator_version != GENERATOR_VERSION:
        return ReproductionReport(reproducible=False, status="not_reproducible", software=software,
                                  reason=f"Generator version {rec.dataset.generator_version} differs from this build ({GENERATOR_VERSION}).")
    try:
        inv = get_investigation(rec.dataset.dataset_id, seed=rec.dataset.seed)
        method = rec.measurements[0].method if rec.measurements else "psf_gaussian_fit"
        reproduced = inv.measure(rec.source.source_id, method)
    except KeyError as exc:
        return ReproductionReport(reproducible=False, status="not_reproducible", software=software,
                                  reason=f"{exc.args[0]!r} does not exist in the regenerated dataset.")
    by_id = {m.id: m for m in reproduced.measurements}
    checks: list[ReproductionCheck] = []
    for m in rec.measurements:
        r = by_id.get(m.id)
        if r is None:
            checks.append(ReproductionCheck(quantity=f"{m.id}: present", saved=None, reproduced=None, abs_diff=None, tolerance=0.0, passed=False))
            continue
        if m.status != r.status:
            checks.append(ReproductionCheck(quantity=f"{m.id}: status {m.status} vs {r.status}", saved=None, reproduced=None, abs_diff=None, tolerance=0.0, passed=False))
            continue
        for field, tol in (("ra_deg", POSITION_TOLERANCE_DEG), ("dec_deg", POSITION_TOLERANCE_DEG)):
            a, b = getattr(m, field), getattr(r, field)
            if a is None and b is None:
                continue
            diff = abs(a - b) if a is not None and b is not None else None
            checks.append(ReproductionCheck(quantity=f"{m.id}: {field}", saved=a, reproduced=b, abs_diff=diff, tolerance=tol, passed=diff is not None and diff <= tol))
        if m.flux is not None and r.flux is not None:
            tol = FLUX_RELATIVE_TOLERANCE * max(abs(m.flux), 1.0)
            diff = abs(m.flux - r.flux)
            checks.append(ReproductionCheck(quantity=f"{m.id}: flux ({m.flux_unit})", saved=m.flux, reproduced=r.flux, abs_diff=diff, tolerance=tol, passed=diff <= tol))
    if rec.fit is not None:
        refit = fit_astrometry(
            FitRequest(
                dataset_id=rec.dataset.dataset_id,
                source_id=rec.source.source_id,
                model=rec.fit.model,
                measurements=reproduced.measurements,
                excluded_measurement_ids=rec.fit.inputs.excluded_measurement_ids,
                reference_epoch_mjd_tdb=rec.fit.inputs.reference_epoch_mjd_tdb,
            ),
            observer=rec.fit.inputs.observer,
        )
        saved = {p.name: p for p in rec.fit.parameters}
        for p in refit.parameters:
            s = saved.get(p.name)
            if s is None or (s.value is None and p.value is None):
                continue
            diff = abs(s.value - p.value) if s.value is not None and p.value is not None else None
            checks.append(ReproductionCheck(quantity=f"fit {p.name} ({p.unit})", saved=s.value, reproduced=p.value, abs_diff=diff,
                                            tolerance=PARAMETER_TOLERANCE, passed=diff is not None and diff <= PARAMETER_TOLERANCE))
        checks.append(ReproductionCheck(quantity="fit input hash identical", saved=None, reproduced=None, abs_diff=None, tolerance=0.0,
                                        passed=refit.input_hash == rec.fit.input_hash))
    ok = bool(checks) and all(c.passed for c in checks)
    n_bad = sum(1 for c in checks if not c.passed)
    return ReproductionReport(
        reproducible=ok,
        status="reproduced" if ok else "mismatch",
        reason=(f"Regenerated with seed {rec.dataset.seed} ({rec.dataset.generator} {rec.dataset.generator_version}); "
                f"{len(checks) - n_bad}/{len(checks)} checks within tolerance."),
        checks=checks,
        software=software,
    )


def _fmt(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)
    return str(v)


def record_to_csv(rec: EvidenceRecord) -> str:
    """Measurements as CSV with '#' header lines carrying origin, units and provenance."""
    out = io.StringIO()
    d = rec.dataset
    out.write(f"# SkyShift evidence export ({rec.schema_version}; contracts {rec.contracts_version})\n")
    out.write(f"# record_id: {rec.id}; title: {rec.title}\n")
    out.write(f"# record_label: {rec.record_label}\n")
    out.write(f"# dataset: {d.dataset_id}; provider: {d.provider}; origin: {d.origin}; release: {d.release}; generator: {d.generator} {d.generator_version}; seed: {d.seed}\n")
    out.write("# rows: derived measurements made from image pixels; simulation truth is not included in this file\n")
    out.write("# units: ra_deg/dec_deg ICRS degrees; sigma_* mas (sigma_ra_cosdec = sigma of RA*cos(Dec)); epoch_mjd_tdb = mid-exposure MJD (TDB); x_px/y_px = native frame, 0-based pixel centres; flux in flux_unit\n")
    if rec.fit is not None:
        params = "; ".join(f"{p.name}={_fmt(p.value)}+/-{_fmt(p.uncertainty)} {p.unit} [{p.status}]" for p in rec.fit.parameters if p.status != "not_in_model")
        out.write(f"# fit: model={rec.fit.model}; status={rec.fit.status}; identifiability={rec.fit.identifiability.status}; fit_status={rec.fit_status}; {params}\n")
    included = set(rec.included_measurement_ids)
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for m in rec.measurements:
        writer.writerow([
            rec.id, d.dataset_id, d.release, m.source_id, m.id, m.origin, m.frame_id, m.observation_id, m.band_id,
            m.epoch.iso_utc or "", _fmt(m.epoch.mjd_tdb), m.status, "true" if m.id in included else "false", m.method, m.method_version,
            _fmt(m.x_px), _fmt(m.y_px), _fmt(m.ra_deg), _fmt(m.dec_deg), _fmt(m.sigma_ra_cosdec_mas), _fmt(m.sigma_dec_mas),
            _fmt(m.corr_ra_dec), _fmt(m.flux), _fmt(m.flux_err), m.flux_unit or "", _fmt(m.snr), m.quality.status, "|".join(m.quality.flags),
        ])
    return out.getvalue()
