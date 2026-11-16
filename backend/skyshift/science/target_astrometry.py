"""Position of one known target in SPHEREx frames, its displacement between epochs, and the error budget.

This is a validation study of a single, named target; it does not enable target measurement in the API. Every
quantity keeps its origin: the measured position is a `derived_measurement` from native pixels (the frame's own
zone ePSF, flags as masks, a plane background); the Gaia propagation is a `model_prediction`. A predicted
position is used only to choose which pixels to look at; the fit starts from the brightest pixel near it and must
reach the same answer from offset starting points, so the prediction cannot pull the measurement.

Error budget of one epoch (arcsec per axis), for the target position tied to the frame's reference stars:
  random, target   ePSF fit sigma x sqrt(chi2_red) when > 1
  random, frame    random part of the frame's mean reference residual (per-star errors + extra scatter, /sqrt(N))
  per star         the frame's Paule-Mandel extra scatter (the star-to-star scatter the references show)
  differential     centroid-convention offset of the target's zone minus the mean over the references' zones
  differential     PSF mismatch for the target itself (half the shift when refitted with adjacent-zone ePSFs)
  systematic       shift simulated from the target's catalogued Gaia neighbours (sign unknown in real data)
The centroid convention and PSF terms are shared by all stars of a frame and largely cancel in a position tied to
that frame's references; only their differences between the target's zone and the references' zones remain.
Epochs are independent exposures. Whether this budget describes the data is tested on pairs with zero true
displacement (same instant on two detectors; same detector two minutes apart) before any significance is quoted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from skyshift.imaging.epsf import fit_position
from skyshift.science.alignment import FrameInputs, centroid_convention_offsets, excluded_mask

TARGET_ASTROMETRY_VERSION = "1.0.0"


@dataclass(frozen=True)
class TargetConfig:
    """Predefined acceptance rules (fixed before the target is measured)."""

    min_diagnostic_snr: float = 30.0  # stage-1 criterion (diagnostic 3x3 pixel S/N)
    max_sigma_px: float = 0.25  # as for the reference stars
    min_references: int = 5
    half_window: int = 3
    max_shift_px: float = 2.0
    search_radius_px: float = 2.0  # brightest pixel within this radius of the predicted pixel starts the fit
    start_offsets_px: tuple[tuple[float, float], ...] = ((0.4, 0.0), (-0.4, 0.0), (0.0, 0.4), (0.0, -0.4))
    start_tolerance_px: float = 2e-3
    neighbour_radius_px: float = 4.5
    neighbour_flag_px: float = 0.02  # simulated neighbour shift above this is reported as a concern
    primary_detectors: tuple[int, ...] = (1, 2, 3)
    secondary_detectors: tuple[int, ...] = (4, 5)
    detection_p: float = 2 * stats.norm.sf(5.0)  # 2-D test at the two-sided 5-sigma tail probability (k = 5.36)
    consistency_p: float = 0.0027  # 3-sigma
    null_test_p: float = 0.0027  # the budget is rejected if the zero-displacement pairs are inconsistent at this level


@dataclass
class TargetFit:
    status: str  # ok | rejected
    reason: str
    x: float | None = None
    y: float | None = None
    sigma_x: float | None = None
    sigma_y: float | None = None
    corr_xy: float | None = None
    chi2_red: float | None = None
    snr: float | None = None
    n_masked: int | None = None
    zone: int | None = None
    start_xy: tuple[float, float] | None = None
    start_spread_px: float | None = None  # starts offset by start_offsets_px, window re-centred on each start (predefined criterion)
    start_spread_fixed_window_px: float | None = None  # the same starts inside the primary fit's window (start dependence alone)
    window_choice_rms_px: tuple[float, float] | None = None  # RMS shift over the windows the offset starts select
    zone_swap_shift_px: tuple[float, float] | None = None
    neighbour_shift_px: tuple[float, float] | None = None
    neighbours: list[dict] = field(default_factory=list)


def _bad(frame: FrameInputs) -> np.ndarray:
    return (frame.flags.astype(np.int64) & excluded_mask(frame.flag_masks)) != 0


def fit_target(frame: FrameInputs, x_pred: float, y_pred: float, neighbours: list[dict], cfg: TargetConfig = TargetConfig()) -> TargetFit:
    """ePSF position of the target near its predicted pixel (the prediction only selects the search region).

    `neighbours`: other catalogued sources near the target, as dicts with dx, dy (px, relative to the target's
    predicted position at this epoch) and flux ratio (target = 1); used only to simulate the shift they induce."""
    img = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    bad = _bad(frame)
    ny, nx = img.shape
    h = cfg.half_window
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.hypot(xx - x_pred, yy - y_pred)
    region = (r <= cfg.search_radius_px) & ~bad & np.isfinite(img)
    if not region.any():
        return TargetFit("rejected", "no usable pixel within the search radius of the predicted position")
    ann = (r >= 4.0) & (r <= 7.0) & ~bad & np.isfinite(img)
    bg = float(np.median(img[ann])) if ann.any() else 0.0
    k = int(np.argmax(np.where(region, img - bg, -np.inf)))
    sy, sx = divmod(k, nx)
    if sx - h < 0 or sy - h < 0 or sx + h >= nx or sy + h >= ny:
        return TargetFit("rejected", "fit window not inside the cutout")
    zone = frame.epsf.zone_index(sx + frame.detector_offset[0], sy + frame.detector_offset[1])
    model = frame.epsf.model(zone)
    f = fit_position(img, var, bad, model, float(sx), float(sy), half_window=h, max_shift_px=cfg.max_shift_px)
    if f.status != "ok":
        return TargetFit("rejected", f"ePSF fit {f.status}: {f.message}", zone=zone, start_xy=(float(sx), float(sy)))
    # the answer must not depend on where the fit starts
    ends = [(f.x, f.y)]
    for dx, dy in cfg.start_offsets_px:
        g = fit_position(img, var, bad, model, f.x + dx, f.y + dy, half_window=h, max_shift_px=cfg.max_shift_px)
        if g.status == "ok":
            ends.append((g.x, g.y))
    ends_arr = np.array(ends)
    spread = float(np.max(np.hypot(ends_arr[:, 0] - f.x, ends_arr[:, 1] - f.y)))
    fixed = [(f.x, f.y)]
    for dx, dy in cfg.start_offsets_px:
        g = fit_position(img, var, bad, model, f.x + dx, f.y + dy, half_window=h, max_shift_px=cfg.max_shift_px, window_center=(sx, sy))
        if g.status == "ok":
            fixed.append((g.x, g.y))
    fixed_arr = np.array(fixed)
    out = TargetFit("ok", "measured", x=f.x, y=f.y, sigma_x=f.sigma_x, sigma_y=f.sigma_y, corr_xy=f.corr_xy, chi2_red=f.chi2_red, snr=f.snr,
                    n_masked=f.n_masked, zone=zone, start_xy=(float(sx), float(sy)), start_spread_px=spread, neighbours=neighbours,
                    start_spread_fixed_window_px=float(np.max(np.hypot(fixed_arr[:, 0] - f.x, fixed_arr[:, 1] - f.y))),
                    window_choice_rms_px=(float(np.sqrt(np.mean((ends_arr[:, 0] - f.x) ** 2))), float(np.sqrt(np.mean((ends_arr[:, 1] - f.y) ** 2)))))
    # PSF-model sensitivity of this star: refit with each adjacent zone's ePSF
    shifts = []
    for kz in frame.epsf.neighbours(zone):
        g = fit_position(img, var, bad, frame.epsf.model(kz), f.x, f.y, half_window=h, max_shift_px=cfg.max_shift_px)
        if g.status == "ok":
            shifts.append((g.x - f.x, g.y - f.y))
    if shifts:
        s = np.array(shifts)
        out.zone_swap_shift_px = (float(np.sqrt(np.mean(s[:, 0] ** 2))), float(np.sqrt(np.mean(s[:, 1] ** 2))))
    # catalogued neighbours: shift they would induce on a noiseless rendering with this zone's ePSF
    if neighbours:
        sub = np.zeros((21, 21))
        x0, y0 = 10.0 + (f.x - round(f.x)), 10.0 + (f.y - round(f.y))
        sub = model.render(sub.shape, x0, y0, 1000.0) + 5.0
        for nb in neighbours:
            sub = sub + model.render(sub.shape, x0 + nb["dx"], y0 + nb["dy"], 1000.0 * nb["ratio"])
        g = fit_position(sub, np.ones(sub.shape), np.zeros(sub.shape, bool), model, x0, y0, half_window=h, max_shift_px=cfg.max_shift_px)
        out.neighbour_shift_px = (float(g.x - x0), float(g.y - y0)) if g.status == "ok" else None
    if out.sigma_x is None or max(out.sigma_x, out.sigma_y or 0) > cfg.max_sigma_px:
        out.status, out.reason = "rejected", f"position sigma above {cfg.max_sigma_px} px"
    elif spread > cfg.start_tolerance_px:
        out.status, out.reason = "rejected", f"fit depends on the starting point ({spread:.4f} px > {cfg.start_tolerance_px} px)"
    return out


def convention_differential_px(frame: FrameInputs, target_zone: int, reference_zones: list[int]) -> tuple[float, float]:
    """Per-axis size (px) of the centroid-convention offset of the target's zone relative to the mean over the
    references' zones (Gaia-free, from the ePSFs). The pipeline's centroid definition is undocumented, so the RMS of the
    windowed-centroid and 5x5-barycentre differentials is used, as for the shared term."""
    if not reference_zones:
        a, b = centroid_convention_offsets(frame.epsf.model(target_zone))
        d_w, d_b = np.asarray(a), np.asarray(b)
    else:
        a, b = centroid_convention_offsets(frame.epsf.model(target_zone))
        rw = np.mean([centroid_convention_offsets(frame.epsf.model(z))[0] for z in reference_zones], axis=0)
        rb = np.mean([centroid_convention_offsets(frame.epsf.model(z))[1] for z in reference_zones], axis=0)
        d_w, d_b = np.asarray(a) - rw, np.asarray(b) - rb
    d = np.sqrt((d_w**2 + d_b**2) / 2.0)
    return float(d[0]), float(d[1])


def epoch_budget(fit: TargetFit, frame_sigma_random_arcsec: tuple[float, float], extra_scatter_arcsec: float, conv_diff_px: tuple[float, float],
                 jacobian: np.ndarray) -> dict:
    """Per-axis (east, north) uncertainty terms of one tied target position, in arcsec.

    jacobian = d(east, north arcsec)/d(x, y px). Independent per-axis pixel sigmas map in quadrature; the simulated
    neighbour shift is a vector and maps linearly (its size per sky axis is used as an uncertainty, not a correction)."""
    J = np.asarray(jacobian, dtype=float)

    def sky_sigma(sx: float, sy: float) -> tuple[float, float]:
        v = (J**2) @ np.array([sx**2, sy**2])
        return float(math.sqrt(v[0])), float(math.sqrt(v[1]))

    c = (fit.corr_xy or 0.0) * fit.sigma_x * fit.sigma_y
    cov_fit = J @ np.array([[fit.sigma_x**2, c], [c, fit.sigma_y**2]]) @ J.T
    nb = np.abs(J @ np.asarray(fit.neighbour_shift_px)) if fit.neighbour_shift_px else np.zeros(2)
    terms = {
        "fit": (math.sqrt(cov_fit[0, 0]), math.sqrt(cov_fit[1, 1])),
        "frame_tie": tuple(float(v) for v in frame_sigma_random_arcsec),
        "extra_scatter": (extra_scatter_arcsec, extra_scatter_arcsec),
        "convention_differential": sky_sigma(*conv_diff_px),
        "psf_target": sky_sigma(*(0.5 * np.asarray(fit.zone_swap_shift_px))) if fit.zone_swap_shift_px else (0.0, 0.0),
        "neighbours": (float(nb[0]), float(nb[1])),
    }
    tot = tuple(math.sqrt(sum(v[i] ** 2 for v in terms.values())) for i in (0, 1))
    return {"terms_arcsec": {k: [float(v[0]), float(v[1])] for k, v in terms.items()}, "total_arcsec": [float(tot[0]), float(tot[1])],
            "random_arcsec": [math.hypot(terms["fit"][i], terms["frame_tie"][i], terms["extra_scatter"][i]) for i in (0, 1)],
            "systematic_arcsec": [math.hypot(terms["convention_differential"][i], terms["psf_target"][i], terms["neighbours"][i]) for i in (0, 1)]}


def chi2_2d(d: np.ndarray, sigma: np.ndarray) -> tuple[float, float]:
    """chi2 (2 dof, diagonal per-axis errors) of a 2-D vector against zero, and its p-value."""
    c = float(np.sum((np.asarray(d) / np.asarray(sigma)) ** 2))
    return c, float(stats.chi2.sf(c, 2))


def displacement(e1: np.ndarray, e2: np.ndarray, s1: np.ndarray, s2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Displacement e2 - e1 (east, north) and its per-axis sigma for independent epochs."""
    return np.asarray(e2) - np.asarray(e1), np.hypot(np.asarray(s1), np.asarray(s2))


def along_ratio(measured: np.ndarray, predicted: np.ndarray, sigma: np.ndarray) -> tuple[float, float, float, float]:
    """Measured displacement projected on the predicted direction, as a fraction of the predicted length
    (1 = as predicted), with its sigma; and the perpendicular component (arcsec) with its sigma."""
    p = np.asarray(predicted, dtype=float)
    u = p / np.linalg.norm(p)
    v = np.array([-u[1], u[0]])
    s2 = np.asarray(sigma) ** 2
    along, perp = float(measured @ u), float(measured @ v)
    s_along, s_perp = math.sqrt(float(u**2 @ s2)), math.sqrt(float(v**2 @ s2))
    return along / float(np.linalg.norm(p)), s_along / float(np.linalg.norm(p)), perp, s_perp


def interpolated_epsf(frame: FrameInputs, det_x: float, det_y: float):  # noqa: ANN201 - EPSFModel
    """ePSF bilinearly interpolated between the four zone centres around a detector position (a sensitivity variant:
    the pipeline, like the IRSA tutorial, uses the zone containing the star). Missing zones (trimmed table) drop out
    with the remaining weights renormalised; returns (model, weights by zone index)."""
    from skyshift.imaging.epsf import EPSFModel

    lib = frame.epsf
    xs = sorted({z.x_center for z in lib.zones})
    ys = sorted({z.y_center for z in lib.zones})

    def bracket(vals: list[float], v: float) -> tuple[float, float, float]:
        lo = max([c for c in vals if c <= v], default=vals[0])
        hi = min([c for c in vals if c > v], default=vals[-1])
        t = 0.0 if hi == lo else (v - lo) / (hi - lo)
        return lo, hi, t

    x0, x1, tx = bracket(xs, det_x)
    y0, y1, ty = bracket(ys, det_y)
    want = {(x0, y0): (1 - tx) * (1 - ty), (x1, y0): tx * (1 - ty), (x0, y1): (1 - tx) * ty, (x1, y1): tx * ty}
    weights: dict[int, float] = {}
    for z in lib.zones:
        w = want.get((z.x_center, z.y_center))
        if w:
            weights[z.index] = weights.get(z.index, 0.0) + w
    total = sum(weights.values())
    arr = sum(w * lib.arrays[k] for k, w in weights.items()) / total
    return EPSFModel(arr, lib.oversampling), {k: w / total for k, w in weights.items()}


def fit_with_neighbours(frame: FrameInputs, model, x_start: float, y_start: float, neighbours: list[dict], half_window: int = 3,  # noqa: ANN001
                        window_center: tuple[int, int] | None = None) -> dict | None:
    """Joint fit of the target and its catalogued neighbours: target (x, y, flux), one free flux per neighbour at the
    catalogue offset from the target (both propagated to this epoch), and a plane background. Returns the target
    position with the fit's chi2/dof and the fitted neighbour/target flux ratios (the neighbours are modelled, not bounded)."""
    from scipy.optimize import least_squares

    img = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    bad = _bad(frame)
    ix0, iy0 = window_center or (int(round(x_start)), int(round(y_start)))
    h = half_window
    sl = (slice(iy0 - h, iy0 + h + 1), slice(ix0 - h, ix0 + h + 1))
    yy, xx = np.mgrid[iy0 - h : iy0 + h + 1, ix0 - h : ix0 + h + 1]
    good = ~bad[sl] & np.isfinite(img[sl]) & (var[sl] > 0)
    xs, ys, ds, w = xx[good].astype(float), yy[good].astype(float), img[sl][good], 1.0 / np.sqrt(var[sl][good])
    nbs = [nb for nb in neighbours if abs(nb["dx"]) <= h + 2.5 and abs(nb["dy"]) <= h + 2.5]

    def resid(p: np.ndarray) -> np.ndarray:
        x, y, f, b0, bx, by = p[:6]
        m = f * model.evaluate(xs - x, ys - y) + b0 + bx * (xs - ix0) + by * (ys - iy0)
        for k, nb in enumerate(nbs):
            m = m + p[6 + k] * model.evaluate(xs - (x + nb["dx"]), ys - (y + nb["dy"]))
        return (ds - m) * w

    f0 = float(np.sum(ds - np.median(ds)))
    p0 = np.array([x_start, y_start, f0, float(np.median(ds)), 0.0, 0.0] + [f0 * nb["ratio"] for nb in nbs])
    sol = least_squares(resid, p0, method="trf", x_scale="jac", xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=2000)
    if not sol.success or abs(sol.x[0] - x_start) > 2 or abs(sol.x[1] - y_start) > 2:
        return None
    dof = max(1, len(ds) - len(p0))
    chi2_red = float(np.sum(sol.fun**2) / dof)
    try:
        cov = np.linalg.inv(sol.jac.T @ sol.jac) * max(1.0, chi2_red)
        sig = (float(math.sqrt(cov[0, 0])), float(math.sqrt(cov[1, 1])), float(cov[0, 1] / math.sqrt(cov[0, 0] * cov[1, 1])))
    except np.linalg.LinAlgError:
        sig = (None, None, None)
    return {"x": float(sol.x[0]), "y": float(sol.x[1]), "sigma_x": sig[0], "sigma_y": sig[1], "corr_xy": sig[2], "chi2_red": chi2_red, "n_neighbours_modelled": len(nbs),
            "flux_ratios_fitted": [float(sol.x[6 + k] / sol.x[2]) for k in range(len(nbs))], "flux_ratios_gaia": [float(nb["ratio"]) for nb in nbs],
            "neighbour_offsets_px": [[float(nb["dx"]), float(nb["dy"])] for nb in nbs]}


def uncatalogued_features(frame: FrameInputs, x: float, y: float, catalogue_xy: np.ndarray, r_min: float = 3.5, r_max: float = 7.5,
                          snr: float = 5.0) -> list[dict]:
    """Groups of pixels >= snr sigma above the local median at r_min..r_max px from the target that no catalogued
    source (within 1.5 px) explains, with the flag names they carry."""
    img = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    ny, nx = img.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    r = np.hypot(xx - x, yy - y)
    ring = (r >= r_min) & (r <= r_max) & np.isfinite(img) & (var > 0)
    bg = float(np.median(img[(r >= 4) & (r <= 9) & np.isfinite(img)]))
    hot = ring & ((img - bg) / np.sqrt(np.where(var > 0, var, np.inf)) >= snr)
    if catalogue_xy.size:
        for cx, cy in catalogue_xy:
            hot &= np.hypot(xx - cx, yy - cy) > 1.5
    from scipy import ndimage

    lab, n = ndimage.label(hot)
    out = []
    for k in range(1, n + 1):
        sel = lab == k
        fx, fy = float(np.mean(xx[sel])), float(np.mean(yy[sel]))
        word = int(np.bitwise_or.reduce(frame.flags[sel]))
        out.append({"x": fx, "y": fy, "distance_px": float(math.hypot(fx - x, fy - y)), "n_pixels": int(sel.sum()),
                    "peak_snr": float(np.max(((img - bg) / np.sqrt(np.where(var > 0, var, np.inf)))[sel])),
                    "flags": [n_ for n_, m in frame.flag_masks.items() if word & m]})
    return out


def fit_stamps(frame: FrameInputs, fit: TargetFit, half: int = 4) -> dict:
    """Data, model (ePSF + plane refitted at the measured position) and normalised residual around the target."""
    from skyshift.imaging.epsf import fit_position

    img = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    bad = _bad(frame)
    model = frame.epsf.model(fit.zone)
    f = fit_position(img, var, bad, model, fit.x, fit.y, half_window=3)
    ix, iy = int(round(fit.x)), int(round(fit.y))
    yy, xx = np.mgrid[iy - half : iy + half + 1, ix - half : ix + half + 1]
    b0, bx, by = f.background
    m = f.flux * model.evaluate(xx - f.x, yy - f.y) + b0 + bx * (xx - int(round(f.x))) + by * (yy - int(round(f.y)))
    d = img[iy - half : iy + half + 1, ix - half : ix + half + 1]
    v = var[iy - half : iy + half + 1, ix - half : ix + half + 1]
    return {"x0": ix - half, "y0": iy - half, "data": d.tolist(), "model": m.tolist(), "residual_over_sigma": ((d - m) / np.sqrt(v)).tolist(),
            "masked": bad[iy - half : iy + half + 1, ix - half : ix + half + 1].astype(int).tolist(), "fit_window_half": 3}


__all__ = ["TARGET_ASTROMETRY_VERSION", "TargetConfig", "TargetFit", "along_ratio", "chi2_2d", "convention_differential_px", "displacement",
           "epoch_budget", "fit_stamps", "fit_target", "fit_with_neighbours", "interpolated_epsf", "uncatalogued_features"]
