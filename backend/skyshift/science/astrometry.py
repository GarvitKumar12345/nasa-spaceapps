"""Astrometric motion models and the weighted least-squares fit.

Model (tangent plane about the tangent point (alpha0, delta0); mas, Julian years TDB):

    east(t)  = d_east0  + pmra  * (t - t_ref) + parallax * f_ra(t)
    north(t) = d_north0 + pmdec * (t - t_ref) + parallax * f_dec(t)

with parallax factors from the observer's barycentric position (X, Y, Z) in AU:

    f_ra  = X sin(a) - Y cos(a)
    f_dec = X cos(a) sin(d) + Y sin(a) sin(d) - Z cos(d)

pmra is dRA/dt * cos(Dec). For radial velocity 0, straight-line space motion is
exactly linear in gnomonic coordinates, so the only neglected terms are the
observer-parallax cross terms (order parallax * 1 AU / distance) and the
perspective acceleration caused by an unknown radial velocity (bounded in the
fit's assumptions). `rigorous_offsets` is an independent vector implementation
used by the tests.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from scipy import stats

from skyshift.contracts import (
    AstrometricModel,
    CurveComponent,
    DerivedQuantity,
    FitInputs,
    FitParameter,
    FitRequest,
    FitResidual,
    IdentifiabilityReport,
    ModelComparison,
    ModelFit,
    ObserverModel,
    PredictionCurve,
    Provenance,
    SkyPosition,
    SourceMeasurement,
)
from skyshift.coords.observer import GEOCENTER_BUILTIN, observer_barycentric_au
from skyshift.coords.tangent import MAS_PER_RAD, offsets_mas, tangent_to_sky, wrap_ra_deg
from skyshift.coords.time import JULIAN_YEAR_DAYS, epoch_from_mjd_tdb, mjd_tdb_to_jyear
from skyshift.versions import software_versions

FIT_METHOD = "skyshift.science.astrometry.fit_astrometry"
FIT_METHOD_VERSION = "1.0.0"

PARAM_NAMES: tuple[str, ...] = ("offset_ra_cosdec", "offset_dec", "pmra", "pmdec", "parallax")
PARAM_UNITS = {"offset_ra_cosdec": "mas", "offset_dec": "mas", "pmra": "mas/yr", "pmdec": "mas/yr", "parallax": "mas"}
PARAM_LABELS = {
    "offset_ra_cosdec": "Δα·cosδ at reference epoch",
    "offset_dec": "Δδ at reference epoch",
    "pmra": "Proper motion µα* (= dα/dt·cosδ)",
    "pmdec": "Proper motion µδ",
    "parallax": "Parallax ϖ",
}
MODEL_PARAMS: dict[str, tuple[str, ...]] = {
    "static": PARAM_NAMES[:2],
    "proper_motion": PARAM_NAMES[:4],
    "proper_motion_parallax": PARAM_NAMES,
}
MODEL_DESCRIPTION = {
    "static": "Fixed position (no motion): 2 parameters.",
    "proper_motion": "Linear proper motion, no parallax: 4 parameters.",
    "proper_motion_parallax": "Linear proper motion plus observer-dependent annual parallax: 5 parameters.",
}

THRESHOLDS: dict[str, float] = {
    "min_dof": 2,
    "min_baseline_pm_yr": 0.25,
    "min_baseline_parallax_yr": 0.5,
    "min_parallax_factor_span": 0.5,
    "max_condition_number": 1e4,
    "weak_condition_number": 1e3,
    "max_abs_correlation": 0.95,
    "weak_abs_correlation": 0.9,
    "min_distance_snr": 10.0,
    "poor_fit_p_value": 1e-3,
}

KM_S_PER_AU_YR = 4.740470463533348  # 1 AU/yr in km/s (IAU AU, Julian year)
EPOCH_TOLERANCE_DAYS = 0.01  # measurements closer than this share an epoch (same visit)


# ---------------------------------------------------------------------------
# Model building blocks
# ---------------------------------------------------------------------------


def parallax_factors(ra_deg: float, dec_deg: float, observer_xyz_au: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Parallax factors (f_ra, f_dec): displacement = parallax * f (dimensionless; observer in AU)."""
    xyz = np.atleast_2d(np.asarray(observer_xyz_au, dtype=float))
    a = math.radians(ra_deg)
    d = math.radians(dec_deg)
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    f_ra = x * math.sin(a) - y * math.cos(a)
    f_dec = x * math.cos(a) * math.sin(d) + y * math.sin(a) * math.sin(d) - z * math.cos(d)
    return f_ra, f_dec


def design_matrix(model: AstrometricModel, dt_yr: np.ndarray, f_ra: np.ndarray, f_dec: np.ndarray) -> np.ndarray:
    """Rows interleaved per measurement: [east_0, north_0, east_1, north_1, ...]."""
    dt = np.asarray(dt_yr, dtype=float)
    n = dt.size
    full = np.zeros((2 * n, 5))
    full[0::2, 0] = 1.0
    full[1::2, 1] = 1.0
    full[0::2, 2] = dt
    full[1::2, 3] = dt
    full[0::2, 4] = f_ra
    full[1::2, 4] = f_dec
    return full[:, : len(MODEL_PARAMS[model])]


def linear_offsets(
    params: Sequence[float], dt_yr: np.ndarray, f_ra: np.ndarray, f_dec: np.ndarray, model: AstrometricModel
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate the linear model: (east_mas, north_mas)."""
    a = design_matrix(model, dt_yr, f_ra, f_dec)
    v = a @ np.asarray(params, dtype=float)
    return v[0::2], v[1::2]


def rigorous_offsets(
    ra_deg: float,
    dec_deg: float,
    parallax_mas: float,
    pmra_mas_yr: float,
    pmdec_mas_yr: float,
    radial_velocity_km_s: float,
    ref_epoch_mjd_tdb: float,
    epochs_mjd_tdb: np.ndarray,
    observer_xyz_au: np.ndarray,
    tangent_ra_deg: float | None = None,
    tangent_dec_deg: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Independent vector propagation: astropy space motion minus the observer vector.

    Returns (east_mas, north_mas) about the tangent point (default: the
    reference-epoch position). Requires a positive parallax (a distance).
    """
    if not parallax_mas > 0:
        raise ValueError("rigorous propagation needs a positive parallax (finite distance)")
    epochs = np.atleast_1d(np.asarray(epochs_mjd_tdb, dtype=float))
    coord = SkyCoord(
        ra=ra_deg * u.deg,
        dec=dec_deg * u.deg,
        distance=(1000.0 / parallax_mas) * u.pc,
        pm_ra_cosdec=pmra_mas_yr * u.mas / u.yr,
        pm_dec=pmdec_mas_yr * u.mas / u.yr,
        radial_velocity=radial_velocity_km_s * u.km / u.s,
        obstime=Time(ref_epoch_mjd_tdb, format="mjd", scale="tdb"),
        frame="icrs",
    )
    moved = coord.apply_space_motion(new_obstime=Time(epochs, format="mjd", scale="tdb"))
    src = np.atleast_2d(moved.cartesian.xyz.to_value(u.au).T)
    vec = src - np.atleast_2d(observer_xyz_au)
    ra = np.degrees(np.arctan2(vec[:, 1], vec[:, 0]))
    dec = np.degrees(np.arctan2(vec[:, 2], np.hypot(vec[:, 0], vec[:, 1])))
    t_ra = ra_deg if tangent_ra_deg is None else tangent_ra_deg
    t_dec = dec_deg if tangent_dec_deg is None else tangent_dec_deg
    return offsets_mas(wrap_ra_deg(ra), dec, t_ra, t_dec)


def mean_direction(ra_deg: np.ndarray, dec_deg: np.ndarray) -> tuple[float, float]:
    """Mean direction of unit vectors (safe across RA = 0 and near the poles)."""
    ra = np.radians(np.asarray(ra_deg, dtype=float))
    dec = np.radians(np.asarray(dec_deg, dtype=float))
    x = np.mean(np.cos(dec) * np.cos(ra))
    y = np.mean(np.cos(dec) * np.sin(ra))
    z = np.mean(np.sin(dec))
    return float(wrap_ra_deg(math.degrees(math.atan2(y, x)))), math.degrees(math.atan2(z, math.hypot(x, y)))


def fit_input_hash(inputs: FitInputs, measurements: Sequence[SourceMeasurement]) -> str:
    """sha256 over canonical JSON of the fit inputs and the included measurement values.

    Any change to an included value, the inclusion/exclusion lists, the model,
    the reference epoch, the tangent point, or the observer changes the hash,
    which is how stale fits are detected.
    """
    payload = {
        "inputs": inputs.model_dump(mode="json"),
        "measurements": [
            {
                "id": m.id,
                "ra_deg": m.ra_deg,
                "dec_deg": m.dec_deg,
                "sigma_ra_cosdec_mas": m.sigma_ra_cosdec_mas,
                "sigma_dec_mas": m.sigma_dec_mas,
                "corr_ra_dec": m.corr_ra_dec,
                "mjd_tdb": m.epoch.mjd_tdb,
            }
            for m in measurements
        ],
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Core weighted least squares
# ---------------------------------------------------------------------------


@dataclass
class _Solution:
    params: np.ndarray | None
    cov: np.ndarray | None
    chi2: float | None
    dof: int
    condition_number: float | None
    rank_deficient: bool


def _measurement_cov(m: SourceMeasurement) -> np.ndarray:
    sa = float(m.sigma_ra_cosdec_mas)  # type: ignore[arg-type]
    sd = float(m.sigma_dec_mas)  # type: ignore[arg-type]
    rho = float(m.corr_ra_dec or 0.0)
    return np.array([[sa * sa, rho * sa * sd], [rho * sa * sd, sd * sd]])


def _whiteners(covs: list[np.ndarray]) -> list[np.ndarray]:
    return [np.linalg.inv(np.linalg.cholesky(c)) for c in covs]


def _whiten(a: np.ndarray, y: np.ndarray, whiteners: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    aw = np.empty_like(a)
    yw = np.empty_like(y)
    for i, w in enumerate(whiteners):
        aw[2 * i : 2 * i + 2] = w @ a[2 * i : 2 * i + 2]
        yw[2 * i : 2 * i + 2] = w @ y[2 * i : 2 * i + 2]
    return aw, yw


def _solve(aw: np.ndarray, yw: np.ndarray) -> _Solution:
    n_rows, p = aw.shape
    dof = n_rows - p
    if n_rows < p:
        return _Solution(None, None, None, dof, None, True)
    norms = np.linalg.norm(aw, axis=0)
    if np.any(norms == 0):
        return _Solution(None, None, None, dof, None, True)
    s = np.linalg.svd(aw / norms, compute_uv=False)
    cond = float(s[0] / s[-1]) if s[-1] > 0 else math.inf
    if not math.isfinite(cond) or s[-1] / s[0] < 1e-12:
        return _Solution(None, None, None, dof, None if not math.isfinite(cond) else cond, True)
    params, *_ = np.linalg.lstsq(aw, yw, rcond=None)
    cov = np.linalg.inv(aw.T @ aw)
    resid = aw @ params - yw
    return _Solution(params, cov, float(resid @ resid), dof, cond, False)


def _corr(cov: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.diag(cov))
    return cov / np.outer(d, d)


# ---------------------------------------------------------------------------
# Public fit
# ---------------------------------------------------------------------------


def _usable(request: FitRequest) -> tuple[list[SourceMeasurement], list[str]]:
    excluded = set(request.excluded_measurement_ids)
    usable: list[SourceMeasurement] = []
    warnings: list[str] = []
    for m in request.measurements:
        if m.source_id != request.source_id or m.dataset_id != request.dataset_id:
            raise ValueError(f"measurement {m.id} does not belong to source {request.source_id} in {request.dataset_id}")
        if m.id in excluded:
            continue
        missing = [k for k in ("ra_deg", "dec_deg", "sigma_ra_cosdec_mas", "sigma_dec_mas") if getattr(m, k) is None]
        if m.status != "measured" or missing:
            if m.status not in ("missing_frame",):
                warnings.append(f"{m.id}: not used (status {m.status}{'; missing ' + ', '.join(missing) if missing else ''}).")
            continue
        if not (m.sigma_ra_cosdec_mas > 0 and m.sigma_dec_mas > 0):  # type: ignore[operator]
            warnings.append(f"{m.id}: not used (non-positive uncertainty).")
            continue
        usable.append(m)
    usable.sort(key=lambda m: m.epoch.mjd_tdb)
    return usable, warnings


def _distinct_epochs(mjd: np.ndarray) -> int:
    if mjd.size == 0:
        return 0
    s = np.sort(mjd)
    return int(1 + np.sum(np.diff(s) > EPOCH_TOLERANCE_DAYS))


def _identifiability(
    model: AstrometricModel,
    sol: _Solution,
    n_meas: int,
    n_epochs: int,
    baseline_yr: float | None,
    span: tuple[float, float] | None,
) -> tuple[IdentifiabilityReport, set[str]]:
    """Return the report and the set of parameters that are not constrained."""
    p = len(MODEL_PARAMS[model])
    msgs: list[str] = []
    not_constrained: set[str] = set()
    max_corr: float | None = None
    if sol.cov is not None:
        c = _corr(sol.cov)
        off = np.abs(c - np.eye(p))
        max_corr = float(off.max()) if p > 1 else 0.0

    status: str
    if n_meas == 0 or sol.dof < THRESHOLDS["min_dof"]:
        status = "insufficient_data"
        msgs.append(
            f"{n_meas} usable measurement(s) give {2 * n_meas} values for {p} parameters (dof {sol.dof}); "
            f"at least dof {int(THRESHOLDS['min_dof'])} is required."
        )
        not_constrained = set(MODEL_PARAMS[model])
    elif sol.rank_deficient:
        status = "underconstrained"
        msgs.append("The design matrix is singular: the parameters are not separately identifiable with these epochs.")
        not_constrained = set(MODEL_PARAMS[model])
    else:
        status = "constrained"
        if model != "static" and (baseline_yr or 0) < THRESHOLDS["min_baseline_pm_yr"]:
            status = "underconstrained"
            not_constrained |= {"pmra", "pmdec"}
            msgs.append(f"Time baseline {baseline_yr:.3f} yr < {THRESHOLDS['min_baseline_pm_yr']} yr: proper motion is not constrained.")
        if model == "proper_motion_parallax":
            if (baseline_yr or 0) < THRESHOLDS["min_baseline_parallax_yr"]:
                status = "underconstrained"
                not_constrained.add("parallax")
                msgs.append(f"Time baseline {baseline_yr:.3f} yr < {THRESHOLDS['min_baseline_parallax_yr']} yr: parallax is not constrained.")
            if span is not None and max(span) < THRESHOLDS["min_parallax_factor_span"]:
                status = "underconstrained"
                not_constrained.add("parallax")
                msgs.append(
                    f"Parallax factors span only ({span[0]:.2f}, {span[1]:.2f}) < {THRESHOLDS['min_parallax_factor_span']}: "
                    "the epochs sample too little of the observer's orbit."
                )
            if sol.cov is not None:
                c = _corr(sol.cov)
                plx_corr = float(np.max(np.abs(np.delete(c[4], 4))))
                if plx_corr > THRESHOLDS["max_abs_correlation"]:
                    status = "underconstrained"
                    not_constrained.add("parallax")
                    msgs.append(f"Parallax correlation with another parameter is {plx_corr:.3f} > {THRESHOLDS['max_abs_correlation']}: degenerate.")
                elif plx_corr > THRESHOLDS["weak_abs_correlation"] and status == "constrained":
                    status = "weakly_constrained"
                    msgs.append(f"Parallax correlation {plx_corr:.3f} > {THRESHOLDS['weak_abs_correlation']}: weakly constrained.")
        if sol.condition_number is not None and status in ("constrained", "weakly_constrained"):
            if sol.condition_number > THRESHOLDS["max_condition_number"]:
                status = "underconstrained"
                not_constrained |= set(MODEL_PARAMS[model][2:])
                msgs.append(f"Condition number {sol.condition_number:.3g} > {THRESHOLDS['max_condition_number']:.0e}.")
            elif sol.condition_number > THRESHOLDS["weak_condition_number"]:
                status = "weakly_constrained"
                msgs.append(f"Condition number {sol.condition_number:.3g} > {THRESHOLDS['weak_condition_number']:.0e}: weakly constrained.")
        if status == "constrained":
            msgs.append("Sampling and geometry constrain every model parameter under the stated thresholds.")

    report = IdentifiabilityReport(
        status=status,  # type: ignore[arg-type]
        n_measurements=n_meas,
        n_epochs=n_epochs,
        n_parameters=p,
        dof=sol.dof,
        time_baseline_yr=baseline_yr,
        condition_number=sol.condition_number,
        max_abs_correlation=max_corr,
        parallax_factor_span=span,
        thresholds=dict(THRESHOLDS),
        messages=msgs,
    )
    return report, not_constrained


def _bic(chi2: float | None, k: int, n: int) -> float | None:
    return None if chi2 is None else chi2 + k * math.log(max(n, 1))


def fit_astrometry(
    request: FitRequest,
    observer: ObserverModel = GEOCENTER_BUILTIN,
    extra_assumptions: Sequence[str] = (),
    n_curve: int = 400,
) -> ModelFit:
    """Weighted least-squares astrometric fit of measured positions (see module docstring)."""
    model = request.model
    if model not in MODEL_PARAMS:
        raise ValueError(f"unknown model {model!r}")
    usable, warnings = _usable(request)
    positioned = [m for m in request.measurements if m.ra_deg is not None and m.dec_deg is not None]
    if not positioned:
        raise ValueError("no measurement has a position; nothing to fit")
    basis = usable or positioned
    t_ra, t_dec = mean_direction(np.array([m.ra_deg for m in basis]), np.array([m.dec_deg for m in basis]))
    mjd = np.array([m.epoch.mjd_tdb for m in usable])
    ref_mjd = float(request.reference_epoch_mjd_tdb) if request.reference_epoch_mjd_tdb is not None else (
        float(mjd.mean()) if mjd.size else float(np.mean([m.epoch.mjd_tdb for m in basis]))
    )
    all_ids = {m.id for m in request.measurements}
    inputs = FitInputs(
        measurement_ids=[m.id for m in usable],
        excluded_measurement_ids=sorted(set(request.excluded_measurement_ids) & all_ids),
        model=model,
        reference_epoch_mjd_tdb=ref_mjd,
        reference_position=SkyPosition(ra_deg=t_ra, dec_deg=t_dec),
        observer=observer,
        settings={
            "tangent_point": "mean direction of included measurements",
            "weights": "inverse of each measurement's 2x2 covariance",
            "covariance_rescaled_by_chi2": False,
            "time_unit": "Julian year (TDB)",
        },
    )
    input_hash = fit_input_hash(inputs, usable)
    params_in_model = MODEL_PARAMS[model]
    p = len(params_in_model)

    # Data and design for the included measurements.
    n = len(usable)
    if n:
        east, north = offsets_mas(np.array([m.ra_deg for m in usable]), np.array([m.dec_deg for m in usable]), t_ra, t_dec)
        y = np.empty(2 * n)
        y[0::2], y[1::2] = east, north
        dt = (mjd - ref_mjd) / JULIAN_YEAR_DAYS
        f_ra, f_dec = parallax_factors(t_ra, t_dec, observer_barycentric_au(mjd, observer))
        covs = [_measurement_cov(m) for m in usable]
        aw, yw = _whiten(design_matrix(model, dt, f_ra, f_dec), y, _whiteners(covs))
        sol = _solve(aw, yw)
        baseline = float(dt.max() - dt.min())
        span = (float(f_ra.max() - f_ra.min()), float(f_dec.max() - f_dec.min()))
    else:
        sol = _Solution(None, None, None, -p, None, True)
        baseline, span = None, None
    n_epochs = _distinct_epochs(mjd)
    ident, not_constrained = _identifiability(model, sol, n, n_epochs, baseline, span)

    # Parameters.
    pvals = sol.params
    perr = np.sqrt(np.diag(sol.cov)) if sol.cov is not None else None
    parameters: list[FitParameter] = []
    for name in PARAM_NAMES:
        if name not in params_in_model:
            parameters.append(FitParameter(name=name, label=PARAM_LABELS[name], value=None, uncertainty=None, unit=PARAM_UNITS[name], status="not_in_model"))
            continue
        i = params_in_model.index(name)
        has_value = pvals is not None and ident.status != "insufficient_data"
        parameters.append(
            FitParameter(
                name=name,
                label=PARAM_LABELS[name],
                value=float(pvals[i]) if has_value else None,
                uncertainty=float(perr[i]) if has_value and perr is not None else None,
                unit=PARAM_UNITS[name],
                status="not_constrained" if name in not_constrained else "estimated",
            )
        )
    value = {fp.name: fp.value for fp in parameters}
    sigma = {fp.name: fp.uncertainty for fp in parameters}
    usable_solution = pvals is not None and ident.status != "insufficient_data"

    # Residuals for every positioned, measured measurement (included and excluded).
    residuals: list[FitResidual] = []
    included_ids = set(inputs.measurement_ids)
    if usable_solution:
        candidates = [
            m for m in request.measurements
            if m.status == "measured" and None not in (m.ra_deg, m.dec_deg, m.sigma_ra_cosdec_mas, m.sigma_dec_mas)
        ]
        if candidates:
            cm = np.array([m.epoch.mjd_tdb for m in candidates])
            ce, cn = offsets_mas(np.array([m.ra_deg for m in candidates]), np.array([m.dec_deg for m in candidates]), t_ra, t_dec)
            cfr, cfd = parallax_factors(t_ra, t_dec, observer_barycentric_au(cm, observer))
            me, mn = linear_offsets(pvals, (cm - ref_mjd) / JULIAN_YEAR_DAYS, cfr, cfd, model)  # type: ignore[arg-type]
            for k, m in enumerate(candidates):
                de, dn = float(ce[k] - me[k]), float(cn[k] - mn[k])
                residuals.append(
                    FitResidual(
                        measurement_id=m.id,
                        epoch_mjd_tdb=m.epoch.mjd_tdb,
                        included=m.id in included_ids,
                        d_ra_cosdec_mas=de,
                        d_dec_mas=dn,
                        sigma_ra_cosdec_mas=float(m.sigma_ra_cosdec_mas),  # type: ignore[arg-type]
                        sigma_dec_mas=float(m.sigma_dec_mas),  # type: ignore[arg-type]
                        normalized_ra=de / float(m.sigma_ra_cosdec_mas),  # type: ignore[arg-type]
                        normalized_dec=dn / float(m.sigma_dec_mas),  # type: ignore[arg-type]
                    )
                )

    # Prediction curve with 1-sigma band and components.
    prediction: PredictionCurve | None = None
    if usable_solution and mjd.size:
        tg = np.linspace(mjd.min() - 0.1 * JULIAN_YEAR_DAYS, mjd.max() + 0.1 * JULIAN_YEAR_DAYS, n_curve)
        gfr, gfd = parallax_factors(t_ra, t_dec, observer_barycentric_au(tg, observer))
        ag = design_matrix(model, (tg - ref_mjd) / JULIAN_YEAR_DAYS, gfr, gfd)
        vals = ag @ pvals  # type: ignore[operator]
        var = np.einsum("ij,jk,ik->i", ag, sol.cov, ag)  # type: ignore[arg-type]
        sig = np.sqrt(np.maximum(var, 0.0))
        dtg = (tg - ref_mjd) / JULIAN_YEAR_DAYS
        pm_e = (value["offset_ra_cosdec"] or 0.0) + (value["pmra"] or 0.0) * dtg
        pm_n = (value["offset_dec"] or 0.0) + (value["pmdec"] or 0.0) * dtg
        components = {"proper_motion": CurveComponent(ra_cosdec_offset_mas=pm_e.tolist(), dec_offset_mas=pm_n.tolist())}
        if model == "proper_motion_parallax":
            plx = value["parallax"] or 0.0
            components["parallax"] = CurveComponent(ra_cosdec_offset_mas=(plx * gfr).tolist(), dec_offset_mas=(plx * gfd).tolist())
        prediction = PredictionCurve(
            t_mjd_tdb=tg.tolist(),
            ra_cosdec_offset_mas=vals[0::2].tolist(),
            dec_offset_mas=vals[1::2].tolist(),
            sigma_ra_cosdec_mas=sig[0::2].tolist(),
            sigma_dec_mas=sig[1::2].tolist(),
            components=components,
            note=(
                "Model prediction from the fitted parameters and the observer ephemeris; offsets are about the fit "
                "tangent point. 'proper_motion' = position offset + secular motion; 'parallax' = parallactic "
                "displacement; their sum is the total. Band: 1-sigma from the fit covariance."
            ),
        )

    # Nested-model comparison on the same included data.
    comparisons: list[ModelComparison] = []
    if n:
        for other in ("static", "proper_motion", "proper_motion_parallax"):
            aw_o, yw_o = _whiten(design_matrix(other, dt, f_ra, f_dec), y, _whiteners(covs))  # type: ignore[arg-type]
            s_o = _solve(aw_o, yw_o)
            k = len(MODEL_PARAMS[other])
            state = "insufficient_data" if s_o.dof < THRESHOLDS["min_dof"] else ("underconstrained" if s_o.rank_deficient else "fit")
            comparisons.append(
                ModelComparison(
                    model=other,  # type: ignore[arg-type]
                    chi2=s_o.chi2 if state == "fit" else None,
                    dof=s_o.dof,
                    bic=_bic(s_o.chi2, k, 2 * n) if state == "fit" else None,
                    status=state,  # type: ignore[arg-type]
                )
            )

    chi2 = sol.chi2 if usable_solution else None
    dof = sol.dof
    reduced = chi2 / dof if chi2 is not None and dof > 0 else None
    p_value = float(stats.chi2.sf(chi2, dof)) if chi2 is not None and dof > 0 else None
    if p_value is not None and p_value < THRESHOLDS["poor_fit_p_value"]:
        warnings.append(
            f"chi2/dof = {reduced:.2f} (p = {p_value:.2g}): the model does not describe the data within the "
            "reported uncertainties (model inadequate or uncertainties underestimated)."
        )
    warnings.extend(msg for msg in ident.messages if ident.status != "constrained")

    derived = _derived(model, parameters, value, sigma, sol, params_in_model, t_ra, t_dec, ref_mjd, usable_solution)
    assumptions = _assumptions(model, value, sigma, baseline, t_ra, t_dec, ref_mjd, observer, mjd) + list(extra_assumptions)

    if not usable_solution:
        status = "pending"
    elif ident.status in ("underconstrained", "weakly_constrained") or (p_value is not None and p_value < THRESHOLDS["poor_fit_p_value"]):
        status = "warning"
    else:
        status = "ok"

    return ModelFit(
        id=f"fit:{request.dataset_id}:{request.source_id}:{model}:{input_hash[:12]}",
        source_id=request.source_id,
        dataset_id=request.dataset_id,
        band_ids=sorted({m.band_id for m in usable}),
        model=model,
        model_description=MODEL_DESCRIPTION[model],
        method="weighted linear least squares on tangent-plane offsets (full 2x2 measurement covariances)",
        method_version=FIT_METHOD_VERSION,
        inputs=inputs,
        input_hash=input_hash,
        reference_epoch=epoch_from_mjd_tdb(ref_mjd),
        parameters=parameters,
        covariance=sol.cov.tolist() if (sol.cov is not None and usable_solution) else None,
        covariance_parameters=list(params_in_model),
        chi2=chi2,
        dof=dof,
        reduced_chi2=reduced,
        p_value=p_value,
        identifiability=ident,
        residuals=residuals,
        prediction=prediction,
        derived=derived,
        comparisons=comparisons,
        assumptions=assumptions,
        warnings=warnings,
        status=status,  # type: ignore[arg-type]
        provenance=Provenance(
            origin="derived_measurement",
            provider="skyshift",
            dataset_id=request.dataset_id,
            method=FIT_METHOD,
            method_version=FIT_METHOD_VERSION,
            parents=list(inputs.measurement_ids),
            software=software_versions(),
        ),
    )


def _derived(
    model: str,
    parameters: list[FitParameter],
    value: dict[str, float | None],
    sigma: dict[str, float | None],
    sol: _Solution,
    params_in_model: tuple[str, ...],
    t_ra: float,
    t_dec: float,
    ref_mjd: float,
    usable_solution: bool,
) -> list[DerivedQuantity]:
    out: list[DerivedQuantity] = []
    status_of = {fp.name: fp.status for fp in parameters}
    if usable_solution and value["offset_ra_cosdec"] is not None:
        ra, dec = tangent_to_sky(value["offset_ra_cosdec"] / MAS_PER_RAD, value["offset_dec"] / MAS_PER_RAD, t_ra, t_dec)  # type: ignore[operator]
        out.append(DerivedQuantity(name="ra_at_reference_epoch", value=float(ra), uncertainty=None, unit="deg", status="derived",
                                   reason=f"Position at the reference epoch (MJD TDB {ref_mjd:.5f}); uncertainty: see offset_ra_cosdec."))
        out.append(DerivedQuantity(name="dec_at_reference_epoch", value=float(dec), uncertainty=None, unit="deg", status="derived",
                                   reason="Position at the reference epoch; uncertainty: see offset_dec."))
    has_pm = model != "static" and usable_solution and status_of.get("pmra") == "estimated" and status_of.get("pmdec") == "estimated"
    mu_tot = None
    if has_pm:
        i, j = params_in_model.index("pmra"), params_in_model.index("pmdec")
        pa, pd = float(value["pmra"]), float(value["pmdec"])  # type: ignore[arg-type]
        mu_tot = math.hypot(pa, pd)
        c = sol.cov[np.ix_([i, j], [i, j])]  # type: ignore[index]
        g = np.array([pa, pd]) / mu_tot if mu_tot > 0 else np.zeros(2)
        s_mu = float(math.sqrt(max(g @ c @ g, 0.0)))
        out.append(DerivedQuantity(name="total_proper_motion", value=mu_tot, uncertainty=s_mu, unit="mas/yr", status="derived",
                                   reason="sqrt(pmra^2 + pmdec^2); first-order uncertainty from the covariance."))
        if mu_tot > 0:
            gpa = np.array([pd, -pa]) / mu_tot**2
            s_pa = math.degrees(math.sqrt(max(gpa @ c @ gpa, 0.0)))
            out.append(DerivedQuantity(name="proper_motion_position_angle", value=math.degrees(math.atan2(pa, pd)) % 360.0, uncertainty=s_pa,
                                       unit="deg", status="derived", reason="Direction of motion, east of north."))
    else:
        out.append(DerivedQuantity(name="total_proper_motion", value=None, unit="mas/yr", status="not_derived",
                                   reason="Proper motion is not in the model or not constrained."))

    distance_reason: str
    distance: float | None = None
    plx, splx = value.get("parallax"), sigma.get("parallax")
    if model != "proper_motion_parallax":
        distance_reason = "Parallax is not in this model."
    elif not usable_solution or plx is None or splx is None:
        distance_reason = "No parallax estimate (insufficient data or singular design)."
    elif status_of.get("parallax") != "estimated":
        distance_reason = "Parallax is not constrained by the sampling/geometry; no distance is derived."
    elif plx <= 0:
        distance_reason = f"Parallax {plx:.3g} mas is not positive; a distance cannot be derived by inversion."
    elif plx / splx < THRESHOLDS["min_distance_snr"]:
        distance_reason = (
            f"Parallax/sigma = {plx / splx:.1f} < {THRESHOLDS['min_distance_snr']:.0f}: naive inversion would be biased; "
            "a distance needs a prior-based treatment."
        )
    else:
        distance = 1000.0 / plx
        distance_reason = (
            f"1/parallax with first-order uncertainty; acceptable because parallax/sigma = {plx / splx:.1f} >= "
            f"{THRESHOLDS['min_distance_snr']:.0f} (fractional error <= 0.1)."
        )
    if distance is not None:
        out.append(DerivedQuantity(name="distance", value=distance, uncertainty=1000.0 * splx / plx**2, unit="pc", status="derived", reason=distance_reason))  # type: ignore[operator]
        if mu_tot is not None:
            vt = KM_S_PER_AU_YR * (mu_tot / 1000.0) * distance
            out.append(DerivedQuantity(name="tangential_velocity", value=vt, uncertainty=None, unit="km/s", status="derived",
                                       reason="4.74047 * mu[arcsec/yr] * d[pc]; uncertainty not propagated."))
    else:
        out.append(DerivedQuantity(name="distance", value=None, unit="pc", status="not_derived", reason=distance_reason))
    return out


def _assumptions(
    model: str,
    value: dict[str, float | None],
    sigma: dict[str, float | None],
    baseline: float | None,
    t_ra: float,
    t_dec: float,
    ref_mjd: float,
    observer: ObserverModel,
    mjd: np.ndarray,
) -> list[str]:
    out = [
        f"Tangent plane about RA {t_ra:.6f} deg, Dec {t_dec:+.6f} deg (mean of included positions); offsets in mas.",
        f"Reference epoch MJD {ref_mjd:.5f} TDB (J{float(mjd_tdb_to_jyear(ref_mjd)):.4f}); times are mid-exposure TDB in Julian years.",
        f"Observer: {observer.kind} ({observer.ephemeris or 'no ephemeris'}). {observer.approximation_note or ''}".strip(),
        "Measurement covariances are used as reported; the fit covariance is not rescaled by the reduced chi2.",
    ]
    if model != "static":
        mu = math.hypot(value.get("pmra") or 0.0, value.get("pmdec") or 0.0)
        half = max(abs(float(mjd.max() - ref_mjd)), abs(float(mjd.min() - ref_mjd))) / JULIAN_YEAR_DAYS if mjd.size else 0.0
        plx = value.get("parallax") if model == "proper_motion_parallax" else None
        if plx is not None and plx > 0:
            # Perspective acceleration for |v_r| <= 100 km/s: d(mu)/dt = -2 mu v_r / d.
            rate_per_yr = 100.0 / KM_S_PER_AU_YR * (plx / 1000.0) / 206264.806247  # v_r/d in 1/yr
            bound = 0.5 * 2.0 * mu * rate_per_yr * half**2
            out.append(
                f"Linear motion in the tangent plane (exact for radial velocity 0). Radial velocity is unknown and assumed 0; "
                f"for |v_r| <= 100 km/s the neglected perspective acceleration moves the source by <= {bound:.3g} mas "
                f"within +/-{half:.2f} yr of the reference epoch."
            )
        else:
            out.append("Linear motion in the tangent plane (exact for straight-line space motion with radial velocity 0); radial velocity assumed 0.")
    if model == "proper_motion_parallax":
        plx = abs(value.get("parallax") or 0.0)
        out.append(
            "Parallax factors are evaluated at the tangent point; second-order observer terms "
            f"(parallax x 1 AU / distance) are <= {plx * plx / MAS_PER_RAD:.2g} mas."
        )
    if baseline is not None:
        out.append(f"Included data span {baseline:.3f} yr; irregular sampling is used as observed (no interpolation).")
    return out


__all__ = [
    "FIT_METHOD_VERSION",
    "MODEL_PARAMS",
    "PARAM_NAMES",
    "THRESHOLDS",
    "design_matrix",
    "fit_astrometry",
    "fit_input_hash",
    "linear_offsets",
    "mean_direction",
    "parallax_factors",
    "rigorous_offsets",
]
