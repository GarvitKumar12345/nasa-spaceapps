"""Image-to-catalogue alignment diagnostics for real frames (archive WCS vs Gaia predictions).

For one frame, Gaia DR3 sources are propagated to the exposure mid-time
(skyshift.science.epoch_propagation) and placed in the native cutout through
the archive WCS. Suitable reference stars are fitted with the frame's own
effective PSF (skyshift.imaging.epsf); the measured pixel position is mapped
back to the sky through the same WCS and compared with the prediction. The
residuals describe the archive WCS (plus measurement and catalogue errors)
before any correction.

Reference selection (each rejection is recorded with its reason):
  catalogue  5/6-parameter solution, RUWE <= 1.4, not duplicated_source,
             ipd_frac_multi_peak <= 2, non_single_star = 0, G <= g_max;
  isolation  no other Gaia source within 2 native pixels brighter than 10 % of
             the reference flux (Delta G or Delta RP < 2.5 mag) - the
             criterion the SPHEREx pipeline uses for its astrometric
             calibrators (ES v2.1 Sect. 3.2.8), with Gaia G/RP as the flux proxy;
  saturation no saturation-type flag (OVERFLOW, SUR_ERROR, NONLINEAR, BLOOM)
             in the fit window, and farther than `saturated_exclusion_px` (8 px)
             from every saturated region (connected OVERFLOW pixels, assigned to
             the brightest Gaia source there). The radius was chosen from
             injection-recovery around the saturated source (not from the real
             residuals): pooled over the 17 Barnard-field frames, S/N ~ 40
             injections 8-12 px away show bias (-0.0002 +/- 0.003, +0.0005 +/-
             0.003) px, as far out as 20-40 px, while 4-8 px has few clean windows;
             `injection_near_saturated` repeats the test in every frame;
  pixels     no excluded flag in the 3x3 core; >= 75 % usable window pixels;
  fit        converged inside a 2-pixel search box and S/N >= snr_min.

Statistics, the translation-model evaluation and the injection-recovery
validation are plain functions so they can be tested against independent
computations.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from skyshift.imaging.epsf import EPSFLibrary, fit_position

ALIGNMENT_METHOD_VERSION = "1.0.0"
SATURATION_FLAGS = ("OVERFLOW", "SUR_ERROR", "NONLINEAR", "BLOOM")
SATURATED_CORE_FLAGS = ("OVERFLOW", "SUR_ERROR")
INFORMATIONAL_FLAGS = ("SOURCE", "FULLSAMPLE")
C_KM_S = 299_792.458
ARCSEC_PER_RAD = 180.0 * 3600.0 / math.pi

REASONS: dict[str, str] = {
    "study_target": "target of a motion study in this field: excluded from the reference stars that tie its own frame",
    "outside_frame": "fit window not entirely inside the cutout",
    "no_proper_motion": "2-parameter Gaia solution (no proper motion: position at the exposure epoch not predictable)",
    "ruwe_high": "RUWE > 1.4 (poor single-star astrometric fit; possible binary)",
    "duplicated_source": "Gaia duplicated_source flag",
    "multi_peak": "ipd_frac_multi_peak > 2 (possible resolved double)",
    "non_single_star": "Gaia non_single_star > 0 (catalogued binary)",
    "too_faint": "fainter than the candidate magnitude limit",
    "saturated": "saturated in this frame (OVERFLOW/SUR_ERROR at its predicted position)",
    "near_saturated_source": "within the exclusion radius of a saturated source (wings, bloom)",
    "saturation_flags_in_window": "saturation-type flags (OVERFLOW, SUR_ERROR, NONLINEAR, BLOOM) in the fit window",
    "neighbour_within_2px": "another Gaia source within 2 px brighter than 10 % of the reference (G or RP)",
    "flagged_core": "excluded pixel flag in the 3x3 core",
    "too_few_pixels": "fewer than 75 % usable pixels in the fit window",
    "fit_not_converged": "ePSF fit did not converge",
    "fit_at_bound": "ePSF fit moved to the 2-pixel search bound (no clean counterpart at the prediction)",
    "low_snr": "fitted S/N below the threshold",
    "poorly_constrained": "position uncertainty above 0.25 px (truncated, blended or badly modelled fit)",
}


@dataclass(frozen=True)
class AlignmentConfig:
    g_max: float = 18.5
    snr_min: float = 10.0
    max_sigma_px: float = 0.25  # ~1.5": far above the 0.02-0.1 px of good fits, removes fits that converged on a wing or a blend
    half_window: int = 3
    max_shift_px: float = 2.0
    isolation_radius_px: float = 2.0
    isolation_delta_mag: float = 2.5  # 10 % flux
    saturated_exclusion_px: float = 8.0
    saturated_core_radius_px: float = 1.5
    ruwe_max: float = 1.4
    ipd_multi_peak_max: float = 2.0
    min_references: int = 5
    n_injections: int = 40
    excluded_source_ids: tuple[str, ...] = ()  # study targets: never references of their own frames

    def criteria(self) -> list[str]:
        return [
            f"Gaia: 5/6-parameter solution, RUWE <= {self.ruwe_max}, duplicated_source false, ipd_frac_multi_peak <= {self.ipd_multi_peak_max:g}, non_single_star = 0, G <= {self.g_max}",
            f"Isolation: no Gaia source within {self.isolation_radius_px:g} px brighter than 10 % of the reference flux (Delta G or Delta RP < {self.isolation_delta_mag} mag; SPHEREx ES v2.1 Sect. 3.2.8 calibrator criterion, Gaia flux proxy)",
            f"Saturation: no {', '.join(SATURATION_FLAGS)} pixel in the {2 * self.half_window + 1}x{2 * self.half_window + 1} fit window; farther than {self.saturated_exclusion_px:g} px from any saturated Gaia source",
            "Pixels: no excluded flag in the 3x3 core (all documented flags except the informational SOURCE and FULLSAMPLE are excluded); >= 75 % usable window pixels",
            f"Fit: per-zone ePSF + plane background, weighted by VARIANCE, converged within {self.max_shift_px:g} px of the prediction, S/N >= {self.snr_min:g}, "
            f"position sigma <= {self.max_sigma_px:g} px (formal sigma x sqrt(chi2_red) when chi2_red > 1)",
            f"A frame needs >= {self.min_references} references for statistics and the translation test",
        ]


@dataclass
class FrameInputs:
    """Everything needed to diagnose one native frame."""

    frame_id: str
    image: np.ndarray
    variance: np.ndarray
    flags: np.ndarray  # uint32
    flag_masks: dict[str, int]
    sky_to_pixel: object  # callable(ra, dec) -> (x, y) arrays, 0-based native pixels (archive WCS incl. SIP)
    pixel_to_sky: object  # callable(x, y) -> (ra, dec)
    pixel_scale_arcsec: float
    detector_offset: tuple[float, float]
    epsf: EPSFLibrary


@dataclass
class CatalogInputs:
    """Predicted positions at this frame's epoch plus the catalogue columns needed for selection."""

    source_id: list[str]
    ra_deg: np.ndarray
    dec_deg: np.ndarray
    sigma_east_mas: np.ndarray
    sigma_north_mas: np.ndarray
    g_mag: np.ndarray
    rp_mag: np.ndarray
    params_solved: np.ndarray
    ruwe: np.ndarray
    duplicated: np.ndarray
    ipd_multi_peak: np.ndarray
    non_single_star: np.ndarray


@dataclass
class ReferenceResult:
    index: int
    status: str  # used | rejected
    reason: str | None
    detail: str | None = None
    x_pred: float = float("nan")
    y_pred: float = float("nan")
    x: float | None = None
    y: float | None = None
    sigma_x: float | None = None
    sigma_y: float | None = None
    corr_xy: float | None = None
    snr: float | None = None
    chi2_red: float | None = None
    n_masked: int | None = None
    zone: int | None = None
    dist_saturated_px: float | None = None
    ra_meas: float | None = None
    dec_meas: float | None = None
    d_east_arcsec: float | None = None
    d_north_arcsec: float | None = None
    s_east_arcsec: float | None = None
    s_north_arcsec: float | None = None


@dataclass
class FrameDiagnosis:
    frame_id: str
    n_in_frame: int
    results: list[ReferenceResult]
    saturated: list[int]
    in_frame: np.ndarray  # bool per catalogue source: predicted position inside the native frame
    saturated_xy: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))  # centres of saturated regions (x, y)

    @property
    def used(self) -> list[ReferenceResult]:
        return [r for r in self.results if r.status == "used"]

    def rejected_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            if r.status == "rejected" and r.reason:
                out[r.reason] = out.get(r.reason, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _mask_of(masks: dict[str, int], names: tuple[str, ...]) -> int:
    return int(sum(masks[n] for n in names if n in masks))


def excluded_mask(masks: dict[str, int]) -> int:
    return int(sum(v for n, v in masks.items() if n not in INFORMATIONAL_FLAGS))


def saturated_sources(flags: np.ndarray, masks: dict[str, int], px: np.ndarray, py: np.ndarray, g: np.ndarray, in_frame: np.ndarray,
                      core_radius_px: float = 1.5) -> tuple[list[int], np.ndarray]:
    """Saturated regions and the Gaia source responsible for each.

    A saturated region is a connected (8-neighbour) group of OVERFLOW pixels (ES Table 16: the overflow
    threshold, ~half of full well, was reached). Each region is assigned to the brightest Gaia source
    within (region radius + core_radius_px) of its centroid; a region with no such source is kept as an
    anonymous saturated region. SUR_ERROR alone is not used (without OVERFLOW/TRANSIENT it flags a data
    handling error, not saturation). Returns (catalogue indices, region centres (K, 2) as x, y).
    """
    from scipy import ndimage

    ovf = (flags & _mask_of(masks, ("OVERFLOW",))) != 0
    if not np.any(ovf):
        return [], np.zeros((0, 2))
    labels, n = ndimage.label(ovf, structure=np.ones((3, 3), dtype=bool))
    idx: list[int] = []
    centres: list[tuple[float, float]] = []
    cand = np.flatnonzero(in_frame)
    for lab in range(1, n + 1):
        ys, xs = np.nonzero(labels == lab)
        cx, cy = float(xs.mean()), float(ys.mean())
        rad = float(np.max(np.hypot(xs - cx, ys - cy))) + core_radius_px
        near = cand[np.hypot(px[cand] - cx, py[cand] - cy) <= rad]
        if near.size:
            best = int(near[np.argmin(g[near])])
            if best not in idx:
                idx.append(best)
                centres.append((float(px[best]), float(py[best])))
            continue
        centres.append((cx, cy))
    return idx, np.array(centres, dtype=float)


def local_wcs_jacobian(pixel_to_sky, x: float, y: float, ra0: float, dec0: float, step: float = 0.5) -> np.ndarray:  # noqa: ANN001
    """d(east, north arcsec)/d(x, y px) at (x, y) by central differences through the full WCS."""
    from skyshift.coords.tangent import offsets_mas

    out = np.zeros((2, 2))
    for k, (dx, dy) in enumerate(((step, 0.0), (0.0, step))):
        rp, dp = pixel_to_sky(np.array([x + dx]), np.array([y + dy]))
        rm, dm = pixel_to_sky(np.array([x - dx]), np.array([y - dy]))
        ep, np_ = offsets_mas(rp, dp, ra0, dec0)
        em, nm = offsets_mas(rm, dm, ra0, dec0)
        out[0, k] = float((ep[0] - em[0]) / (2 * step)) / 1000.0
        out[1, k] = float((np_[0] - nm[0]) / (2 * step)) / 1000.0
    return out


def diagnose_frame(frame: FrameInputs, cat: CatalogInputs, cfg: AlignmentConfig = AlignmentConfig()) -> FrameDiagnosis:
    """Select references, fit them with the ePSF and compute image-minus-catalogue residuals (before any correction)."""
    from skyshift.coords.tangent import offsets_mas

    ny, nx = frame.image.shape
    h = cfg.half_window
    px, py = frame.sky_to_pixel(cat.ra_deg, cat.dec_deg)
    px, py = np.asarray(px, dtype=float), np.asarray(py, dtype=float)
    in_frame = (px >= -0.5) & (px <= nx - 0.5) & (py >= -0.5) & (py <= ny - 0.5)
    flags = frame.flags.astype(np.int64)
    sat_mask = _mask_of(frame.flag_masks, SATURATION_FLAGS)
    bad = (flags & excluded_mask(frame.flag_masks)) != 0
    g = np.where(np.isfinite(cat.g_mag), cat.g_mag, np.inf)
    rp = np.where(np.isfinite(cat.rp_mag), cat.rp_mag, np.inf)
    saturated, sat_xy = saturated_sources(flags, frame.flag_masks, px, py, g, in_frame, cfg.saturated_core_radius_px)
    results: list[ReferenceResult] = []
    img = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    for i in np.flatnonzero(in_frame):
        r = ReferenceResult(index=int(i), status="rejected", reason=None, x_pred=float(px[i]), y_pred=float(py[i]))
        results.append(r)
        if len(sat_xy):
            d_sat = np.hypot(sat_xy[:, 0] - px[i], sat_xy[:, 1] - py[i])
            r.dist_saturated_px = float(d_sat.min())
        if cat.source_id[i] in cfg.excluded_source_ids:
            r.reason = "study_target"
            continue
        if i in saturated:
            r.reason = "saturated"
            continue
        if not (g[i] <= cfg.g_max):
            r.reason = "too_faint"
            continue
        aps = cat.params_solved[i]
        if not (np.isfinite(aps) and aps != 3):
            r.reason = "no_proper_motion"
            continue
        if not (np.isfinite(cat.ruwe[i]) and cat.ruwe[i] <= cfg.ruwe_max):
            r.reason = "ruwe_high"
            continue
        if bool(cat.duplicated[i]):
            r.reason = "duplicated_source"
            continue
        if np.isfinite(cat.ipd_multi_peak[i]) and cat.ipd_multi_peak[i] > cfg.ipd_multi_peak_max:
            r.reason = "multi_peak"
            continue
        if np.isfinite(cat.non_single_star[i]) and cat.non_single_star[i] > 0:
            r.reason = "non_single_star"
            continue
        ix, iy = int(round(px[i])), int(round(py[i]))
        if ix - h < 0 or iy - h < 0 or ix + h >= nx or iy + h >= ny:
            r.reason = "outside_frame"
            continue
        if r.dist_saturated_px is not None and r.dist_saturated_px < cfg.saturated_exclusion_px:
            r.reason = "near_saturated_source"
            r.detail = f"{r.dist_saturated_px:.1f} px from a saturated source (exclusion radius {cfg.saturated_exclusion_px:g} px)"
            continue
        win = flags[iy - h : iy + h + 1, ix - h : ix + h + 1]
        if np.any(win & sat_mask):
            r.reason = "saturation_flags_in_window"
            continue
        dpx = np.hypot(px - px[i], py - py[i])
        near = (dpx < cfg.isolation_radius_px) & (np.arange(len(px)) != i)
        bright = near & ((g < g[i] + cfg.isolation_delta_mag) | (rp < rp[i] + cfg.isolation_delta_mag))
        if np.any(bright):
            j = int(np.flatnonzero(bright)[0])
            r.reason = "neighbour_within_2px"
            r.detail = f"Gaia {cat.source_id[j]} at {dpx[j]:.2f} px (G {g[j]:.2f} vs {g[i]:.2f})"
            continue
        if np.any(bad[iy - 1 : iy + 2, ix - 1 : ix + 2]):
            names = sorted({n for n, m in frame.flag_masks.items() if n not in INFORMATIONAL_FLAGS and np.any(flags[iy - 1 : iy + 2, ix - 1 : ix + 2] & m)})
            r.reason = "flagged_core"
            r.detail = ", ".join(names)
            continue
        zone = frame.epsf.zone_index(px[i] + frame.detector_offset[0], py[i] + frame.detector_offset[1])
        r.zone = zone
        fit = fit_position(img, var, bad, frame.epsf.model(zone), float(px[i]), float(py[i]), half_window=h, max_shift_px=cfg.max_shift_px)
        r.n_masked = fit.n_masked
        if fit.status == "too_few_pixels":
            r.reason = "too_few_pixels"
            r.detail = fit.message
            continue
        if fit.status == "not_converged":
            r.reason = "fit_not_converged"
            r.detail = fit.message
            continue
        r.x, r.y, r.sigma_x, r.sigma_y, r.corr_xy = fit.x, fit.y, fit.sigma_x, fit.sigma_y, fit.corr_xy
        r.snr, r.chi2_red = fit.snr, fit.chi2_red
        if fit.status == "at_bound":
            r.reason = "fit_at_bound"
            continue
        if fit.snr is None or not (fit.snr >= cfg.snr_min):
            r.reason = "low_snr"
            r.detail = f"S/N {fit.snr:.1f} < {cfg.snr_min:g}" if fit.snr is not None else "no S/N"
            continue
        if max(fit.sigma_x or np.inf, fit.sigma_y or np.inf) > cfg.max_sigma_px:
            r.reason = "poorly_constrained"
            r.detail = f"sigma ({fit.sigma_x:.2f}, {fit.sigma_y:.2f}) px > {cfg.max_sigma_px:g} px; chi2_red {fit.chi2_red:.1f}"
            continue
        ra_m, dec_m = frame.pixel_to_sky(np.array([fit.x]), np.array([fit.y]))
        r.ra_meas, r.dec_meas = float(ra_m[0]), float(dec_m[0])
        de, dn = offsets_mas(r.ra_meas, r.dec_meas, float(cat.ra_deg[i]), float(cat.dec_deg[i]))
        r.d_east_arcsec, r.d_north_arcsec = float(de) / 1000.0, float(dn) / 1000.0
        jac = local_wcs_jacobian(frame.pixel_to_sky, fit.x, fit.y, float(cat.ra_deg[i]), float(cat.dec_deg[i]))
        cxy = np.array([[fit.sigma_x**2, (fit.corr_xy or 0.0) * fit.sigma_x * fit.sigma_y], [(fit.corr_xy or 0.0) * fit.sigma_x * fit.sigma_y, fit.sigma_y**2]])
        csky = jac @ cxy @ jac.T
        csky[0, 0] += (cat.sigma_east_mas[i] / 1000.0) ** 2
        csky[1, 1] += (cat.sigma_north_mas[i] / 1000.0) ** 2
        r.s_east_arcsec, r.s_north_arcsec = float(math.sqrt(csky[0, 0])), float(math.sqrt(csky[1, 1]))
        r.status, r.reason = "used", None
    return FrameDiagnosis(frame_id=frame.frame_id, n_in_frame=int(in_frame.sum()), results=results, saturated=saturated, in_frame=in_frame, saturated_xy=sat_xy)


# ---------------------------------------------------------------------------------------------- statistics


def extra_scatter(res: np.ndarray, sig: np.ndarray, dof: int, hi: float = 30.0) -> float:
    """sigma_x >= 0 with sum(res^2 / (sig^2 + sigma_x^2)) = dof (0 if the formal errors already explain the scatter)."""
    res, sig = np.asarray(res, dtype=float), np.asarray(sig, dtype=float)
    if dof <= 0 or res.size == 0:
        return 0.0

    def f(sx: float) -> float:
        return float(np.sum(res**2 / (sig**2 + sx**2))) - dof

    if f(0.0) <= 0:
        return 0.0
    lo, top = 0.0, hi
    if f(top) > 0:
        return top
    for _ in range(100):
        mid = 0.5 * (lo + top)
        if f(mid) > 0:
            lo = mid
        else:
            top = mid
    return 0.5 * (lo + top)


def _weighted_q(e: np.ndarray, n: np.ndarray, se: np.ndarray, sn: np.ndarray, sx: float) -> float:
    """sum w (x - xbar_w)^2 over both axes, w = 1/(sigma^2 + sx^2), xbar_w the weighted mean for that sx."""
    we, wn = 1.0 / (se**2 + sx**2), 1.0 / (sn**2 + sx**2)
    me, mn = np.sum(we * e) / np.sum(we), np.sum(wn * n) / np.sum(wn)
    return float(np.sum(we * (e - me) ** 2) + np.sum(wn * (n - mn) ** 2))


def extra_scatter_pm(e: np.ndarray, n: np.ndarray, se: np.ndarray, sn: np.ndarray, hi: float = 30.0) -> float:
    """Extra scatter sx >= 0 (Paule & Mandel 1982), solved with the weighted means recomputed for every sx.

    Root of sum_e w(e - ebar_w)^2 + sum_n w(n - nbar_w)^2 = 2(k - 1), w = 1/(sigma^2 + sx^2). About the
    weighted mean this statistic is chi2 with 2(k - 1) dof under the null hypothesis (no extra scatter),
    whatever the spread of the per-star sigmas; residuals about the unweighted mean would not be, and
    would bias sx upward when the sigmas differ. The statistic decreases monotonically with sx.
    """
    e, n, se, sn = (np.asarray(v, dtype=float) for v in (e, n, se, sn))
    k = e.size
    dof = 2 * (k - 1)
    if k < 2 or _weighted_q(e, n, se, sn, 0.0) <= dof:
        return 0.0
    lo, top = 0.0, hi
    if _weighted_q(e, n, se, sn, top) > dof:
        return top
    for _ in range(100):
        mid = 0.5 * (lo + top)
        if _weighted_q(e, n, se, sn, mid) > dof:
            lo = mid
        else:
            top = mid
    return 0.5 * (lo + top)


def residual_statistics(e: np.ndarray, n: np.ndarray, se: np.ndarray, sn: np.ndarray) -> dict:
    """Residual statistics (arcsec) of one frame's references, before any correction."""
    e, n, se, sn = (np.asarray(v, dtype=float) for v in (e, n, se, sn))
    k = e.size
    out: dict = {"n": int(k)}
    if k == 0:
        return out
    res = np.concatenate([e, n])
    sig = np.concatenate([se, sn])
    out.update(
        mean_east_arcsec=float(e.mean()), mean_north_arcsec=float(n.mean()),
        rms_east_arcsec=float(np.sqrt(np.mean(e**2))), rms_north_arcsec=float(np.sqrt(np.mean(n**2))),
        rms_total_arcsec=float(np.sqrt(np.mean(e**2 + n**2))),
        median_east_arcsec=float(np.median(e)), median_north_arcsec=float(np.median(n)),
        chi2_zero=float(np.sum((res / sig) ** 2)), dof_zero=int(2 * k),
    )
    if k >= 2:
        out.update(
            std_east_arcsec=float(e.std(ddof=1)), std_north_arcsec=float(n.std(ddof=1)),
            se_east_arcsec=float(e.std(ddof=1) / math.sqrt(k)), se_north_arcsec=float(n.std(ddof=1) / math.sqrt(k)),
            robust_sigma_east_arcsec=float(1.4826 * np.median(np.abs(e - np.median(e)))),
            robust_sigma_north_arcsec=float(1.4826 * np.median(np.abs(n - np.median(n)))),
        )
        sx = extra_scatter_pm(e, n, se, sn)
        we, wn = 1.0 / (se**2 + sx**2), 1.0 / (sn**2 + sx**2)
        out.update(
            extra_scatter_arcsec=float(sx),
            wmean_east_arcsec=float(np.sum(we * e) / np.sum(we)), wmean_north_arcsec=float(np.sum(wn * n) / np.sum(wn)),
            wse_east_arcsec=float(1.0 / math.sqrt(np.sum(we))), wse_north_arcsec=float(1.0 / math.sqrt(np.sum(wn))),
            # about the inverse-variance weighted means (formal errors only): chi2 with 2(k-1) dof under the null
            chi2_mean=_weighted_q(e, n, se, sn, 0.0), dof_mean=int(2 * (k - 1)),
        )
        rob = math.hypot(out["robust_sigma_east_arcsec"], out["robust_sigma_north_arcsec"]) / math.sqrt(2.0)
        out["n_outliers_5sigma"] = int(np.sum(np.hypot(e - np.median(e), n - np.median(n)) > 5.0 * max(rob, 1e-6) * math.sqrt(2.0))) if rob > 0 else 0
    return out


def weighted_offset(e: np.ndarray, n: np.ndarray, se: np.ndarray, sn: np.ndarray) -> tuple[float, float, float, float, float]:
    """(offset_e, offset_n, sigma_e, sigma_n, extra_scatter) with weights 1/(sigma^2 + sigma_x^2)."""
    sx = extra_scatter_pm(e, n, se, sn)
    we, wn = 1.0 / (se**2 + sx**2), 1.0 / (sn**2 + sx**2)
    return float(np.sum(we * e) / np.sum(we)), float(np.sum(wn * n) / np.sum(wn)), float(1 / math.sqrt(np.sum(we))), float(1 / math.sqrt(np.sum(wn))), float(sx)


def evaluate_translation(e: np.ndarray, n: np.ndarray, se: np.ndarray, sn: np.ndarray, min_refs: int = 5, alpha: float = 0.0027,
                         shared_sigma_arcsec: float = 0.0) -> dict:
    """Simplest correction model (a constant offset) evaluated on held-out references (leave-one-out).

    The offset is the weighted mean residual. Its uncertainty has a random part (per-star errors plus
    the Paule-Mandel extra scatter; shrinks as 1/sqrt(N)) and a shared part `shared_sigma_arcsec`
    (per axis): errors common to every reference of the frame - PSF-model mismatch and the centroid
    convention of the estimator - which do not shrink with N. Justified only if the offset differs
    from zero at the 3-sigma level with the TOTAL uncertainty (chi^2, 2 dof, p < alpha) AND the
    offset estimated from the other references reduces the held-out RMS. Held-out stars share the
    frame's shared errors, so the held-out test cannot distinguish a shared estimator bias from a
    WCS offset; only the shared term in the significance test protects against that.
    """
    e, n, se, sn = (np.asarray(v, dtype=float) for v in (e, n, se, sn))
    k = e.size
    if k < min_refs:
        return {"evaluated": False, "justified": False, "n": int(k), "sigma_shared_arcsec": float(shared_sigma_arcsec),
                "decision": f"not evaluated: {k} reference star(s), {min_refs} needed for a translation estimate with held-out evaluation"}
    oe, on, s_e, s_n, sx = weighted_offset(e, n, se, sn)
    t_e, t_n = math.hypot(s_e, shared_sigma_arcsec), math.hypot(s_n, shared_sigma_arcsec)
    chi2_r = (oe / s_e) ** 2 + (on / s_n) ** 2
    chi2 = (oe / t_e) ** 2 + (on / t_n) ** 2
    p_r = float(stats.chi2.sf(chi2_r, 2))
    p = float(stats.chi2.sf(chi2, 2))
    held = []
    for i in range(k):
        m = np.arange(k) != i
        ce, cn, *_ = weighted_offset(e[m], n[m], se[m], sn[m])
        held.append((e[i] - ce, n[i] - cn))
    held_arr = np.array(held)
    rms_unc = float(np.sqrt(np.mean(e**2 + n**2)))
    rms_cor = float(np.sqrt(np.mean(np.sum(held_arr**2, axis=1))))
    significant = p < alpha
    improves = rms_cor < rms_unc
    justified = significant and improves
    tail = f" (random-only p = {p_r:.2g}; shared {shared_sigma_arcsec:.3f}\" per axis included)"
    if justified:
        decision = f"translation justified: offset significant with shared errors (p = {p:.2g}) and held-out 2-D RMS {rms_unc:.3f}\" -> {rms_cor:.3f}\"" + tail
    elif not significant:
        decision = f"no correction justified: offset within its total uncertainty (p = {p:.2g} >= {alpha}); held-out 2-D RMS {rms_unc:.3f}\" vs {rms_cor:.3f}\"" + tail
    else:
        decision = f"no correction justified: offset significant (p = {p:.2g}) but held-out 2-D RMS does not improve ({rms_unc:.3f}\" -> {rms_cor:.3f}\")" + tail
    return {"evaluated": True, "justified": bool(justified), "n": int(k), "offset_east_arcsec": oe, "offset_north_arcsec": on,
            "sigma_east_arcsec": t_e, "sigma_north_arcsec": t_n, "sigma_random_east_arcsec": s_e, "sigma_random_north_arcsec": s_n,
            "sigma_shared_arcsec": float(shared_sigma_arcsec), "extra_scatter_arcsec": sx, "chi2": float(chi2), "p_value": p,
            "chi2_random_only": float(chi2_r), "p_value_random_only": p_r,
            "heldout_rms_uncorrected_arcsec": rms_unc, "heldout_rms_corrected_arcsec": rms_cor, "decision": decision}


# ---------------------------------------------------------------------------------------------- shared systematics


def zone_swap_shifts(frame: FrameInputs, refs: list[ReferenceResult], cfg: AlignmentConfig = AlignmentConfig()) -> np.ndarray:
    """(M, 2) position shifts (px) when each reference is refitted with an adjacent zone's ePSF.

    A measure of how much the position depends on the PSF model at the level of zone-to-zone PSF
    changes (~97 px; ~50 px along the dispersion direction on D3)."""
    img = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    bad = (frame.flags.astype(np.int64) & excluded_mask(frame.flag_masks)) != 0
    out = []
    for r in refs:
        if r.zone is None or r.x is None:
            continue
        for k in frame.epsf.neighbours(r.zone):
            f = fit_position(img, var, bad, frame.epsf.model(k), r.x_pred, r.y_pred, half_window=cfg.half_window, max_shift_px=cfg.max_shift_px)
            if f.status == "ok":
                out.append((f.x - r.x, f.y - r.y))
    return np.array(out, dtype=float).reshape(-1, 2)


def windowed_centroid(stamp: np.ndarray, x0: float, y0: float, sigma: float, n_iter: int = 30) -> tuple[float, float]:
    """SExtractor-style windowed centroid (iterative Gaussian window, XWIN/YWIN recipe)."""
    ny, nx = stamp.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    x, y = float(x0), float(y0)
    for _ in range(n_iter):
        w = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma * sigma))
        s = float(np.sum(w * stamp))
        if s <= 0:
            break
        x += 2.0 * float(np.sum(w * stamp * (xx - x))) / s
        y += 2.0 * float(np.sum(w * stamp * (yy - y))) / s
    return x, y


def centroid_convention_offsets(model, n_grid: int = 6) -> tuple[tuple[float, float], tuple[float, float]]:  # noqa: ANN001
    """Mean offsets (px) of two centroid-type estimators from the ePSF reference point, on noiseless native stamps.

    Returns ((xwin - ref), (5x5 barycentre - ref)) averaged over a regular n_grid x n_grid grid of sub-pixel phases. The pipeline fitted
    its WCS with SExtractor positions whose exact definition is not documented, so the spread between
    the ePSF reference point and centroid-type definitions is an estimator-convention uncertainty that
    is common to all stars of a zone (Gaia-free: computed from the ePSF alone)."""
    w_off, c_off = [], []
    phases = (np.arange(n_grid) + 0.5) / n_grid - 0.5
    for px, py in ((float(a), float(b)) for a in phases for b in phases):
        st = model.render((15, 15), 7 + px, 7 + py, 1.0)
        yy, xx = np.mgrid[0:15, 0:15]
        r = np.hypot(xx - (7 + px), yy - (7 + py)).ravel()
        o = np.argsort(r)
        c = np.cumsum(st.ravel()[o])
        r50 = float(r[o][np.searchsorted(c, 0.5 * c[-1])])
        xw, yw = windowed_centroid(st, 7 + px, 7 + py, max(2.0 * r50 / 2.354, 0.3))
        w_off.append((xw - 7 - px, yw - 7 - py))
        ix, iy = int(round(7 + px)), int(round(7 + py))
        m5 = st[iy - 2 : iy + 3, ix - 2 : ix + 3]
        y5, x5 = np.mgrid[-2:3, -2:3]
        c_off.append((float((m5 * (x5 + ix)).sum() / m5.sum()) - 7 - px, float((m5 * (y5 + iy)).sum() / m5.sum()) - 7 - py))
    w = np.mean(w_off, axis=0)
    cc = np.mean(c_off, axis=0)
    return (float(w[0]), float(w[1])), (float(cc[0]), float(cc[1]))


def shared_systematics(frame: FrameInputs, refs: list[ReferenceResult], cfg: AlignmentConfig = AlignmentConfig()) -> dict:
    """Per-frame errors common to all references (arcsec per sky axis, isotropic).

    psf_mismatch: half the RMS zone-swap shift (assumes the zone ePSF is wrong at a star by at most half the
    difference between adjacent zones); convention: RMS of the windowed-centroid and 5x5-barycentre offsets
    from the ePSF reference point, averaged over the zones used; gaia_frame: Gaia DR3 reference-frame and
    magnitude-dependent systematics (~0.02 mas; negligible). Detector-axis values are combined isotropically
    because each frame's detector axes have a different orientation on the sky."""
    scale = frame.pixel_scale_arcsec
    shifts = zone_swap_shifts(frame, refs, cfg)
    missing: list[str] = []
    rms: tuple[float | None, float | None] = (None, None)
    psf_as: float | None = None
    iso = lambda v: float(np.sqrt(np.mean(np.asarray(v, dtype=float) ** 2)))  # noqa: E731
    if len(shifts):
        r = np.sqrt(np.mean(shifts**2, axis=0))
        rms = (float(r[0]), float(r[1]))
        psf_as = iso(0.5 * r) * scale
    else:
        missing.append("PSF-model mismatch: no adjacent-zone ePSF in this file (not estimated; the total omits it)")
    zones = sorted({r.zone for r in refs if r.zone is not None})
    xw, cm = [], []
    for z in zones:
        a, b = centroid_convention_offsets(frame.epsf.model(z))
        xw.append(a)
        cm.append(b)
    xw_m = np.mean(xw, axis=0) if xw else np.zeros(2)
    cm_m = np.mean(cm, axis=0) if cm else np.zeros(2)
    conv_px = np.sqrt((xw_m**2 + cm_m**2) / 2.0)
    conv_as, gaia_as = iso(conv_px) * scale, 2e-5
    return {
        "n_zone_swaps": int(len(shifts)), "zone_swap_rms_x_px": rms[0], "zone_swap_rms_y_px": rms[1],
        "psf_mismatch_arcsec": psf_as, "convention_windowed_px": (float(xw_m[0]), float(xw_m[1])), "convention_barycentre_px": (float(cm_m[0]), float(cm_m[1])),
        "convention_arcsec": conv_as, "gaia_frame_arcsec": gaia_as, "total_arcsec": float(math.sqrt((psf_as or 0.0) ** 2 + conv_as**2 + gaia_as**2)),
        "missing_terms": missing,
    }


# ---------------------------------------------------------------------------------------------- estimator validation


def _seed(frame_id: str) -> int:
    return int.from_bytes(hashlib.sha256(frame_id.encode()).digest()[:8], "little")


def injection_recovery(frame: FrameInputs, cat: CatalogInputs, diag: FrameDiagnosis, cfg: AlignmentConfig = AlignmentConfig(),
                       snr_targets: tuple[float, ...] = (15.0, 40.0)) -> dict:
    """Inject ePSF point sources into the real frame and recover them with the same estimator.

    Positions are random (seeded by the frame id) inside the region where references are accepted:
    window inside the frame, no saturation flags in the window, no excluded flag in the core, beyond
    the saturated-source exclusion radius and > 3 px from any Gaia source with G < 18. Fluxes give the
    target S/N (estimated from the local noise and the zone's effective pixel count). Fits start from
    the true position plus a 0.3 px Gaussian offset. Pass criteria: |bias| <= 0.03 px per axis and a
    robust pull width in [0.7, 1.5] per axis, with >= 20 recoveries.
    """
    rng = np.random.default_rng(_seed(frame.frame_id))
    ny, nx = frame.image.shape
    h = cfg.half_window
    flags = frame.flags.astype(np.int64)
    sat_mask = _mask_of(frame.flag_masks, SATURATION_FLAGS)
    bad = (flags & excluded_mask(frame.flag_masks)) != 0
    px, py = frame.sky_to_pixel(cat.ra_deg, cat.dec_deg)
    px, py = np.asarray(px, dtype=float), np.asarray(py, dtype=float)
    bright = np.isfinite(cat.g_mag) & (cat.g_mag < 18.0)
    sat_xy = diag.saturated_xy
    img0 = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    sig_pix = float(np.nanmedian(np.sqrt(var[np.isfinite(var) & (var > 0)]))) if np.any(np.isfinite(var) & (var > 0)) else float("nan")
    rows = []
    attempts = 0
    n_target = cfg.n_injections
    while len(rows) < n_target * len(snr_targets) and attempts < 4000:
        attempts += 1
        x0, y0 = rng.uniform(h, nx - 1 - h), rng.uniform(h, ny - 1 - h)
        ix, iy = int(round(x0)), int(round(y0))
        if ix - h < 0 or iy - h < 0 or ix + h >= nx or iy + h >= ny:
            continue
        if np.any(flags[iy - h : iy + h + 1, ix - h : ix + h + 1] & sat_mask) or np.any(bad[iy - 1 : iy + 2, ix - 1 : ix + 2]):
            continue
        if len(sat_xy) and np.min(np.hypot(sat_xy[:, 0] - x0, sat_xy[:, 1] - y0)) < cfg.saturated_exclusion_px:
            continue
        if np.any(bright & (np.hypot(px - x0, py - y0) < 3.0)):
            continue
        zone = frame.epsf.zone_index(x0 + frame.detector_offset[0], y0 + frame.detector_offset[1])
        model = frame.epsf.model(zone)
        neff = 1.0 / float(np.sum(model.render((2 * h + 1, 2 * h + 1), h + (x0 - ix), h + (y0 - iy), 1.0) ** 2))
        unit = model.render(img0.shape, x0, y0, 1.0)
        for target in snr_targets:
            flux = target * sig_pix * math.sqrt(neff)
            img = img0 + flux * unit
            xs, ys = x0 + rng.normal(0.0, 0.3), y0 + rng.normal(0.0, 0.3)
            fit = fit_position(img, var, bad, model, xs, ys, half_window=h, max_shift_px=cfg.max_shift_px)
            rows.append((target, fit.status, fit.x, fit.y, fit.sigma_x, fit.sigma_y, fit.snr, x0, y0))
    out: dict = {"n_injected": len(rows), "snr_targets": list(snr_targets), "pixel_noise_median": sig_pix, "per_target": []}
    passed_all = True
    for target in snr_targets:
        sel = [r for r in rows if r[0] == target]
        ok = [r for r in sel if r[1] == "ok" and r[6] is not None and r[6] >= cfg.snr_min]
        dx = np.array([r[2] - r[7] for r in ok])
        dy = np.array([r[3] - r[8] for r in ok])
        sx = np.array([r[4] for r in ok])
        sy = np.array([r[5] for r in ok])
        entry = {"snr_target": target, "n_injected": len(sel), "n_recovered": len(ok)}
        if len(ok) >= 2:
            px_ = dx / sx
            py_ = dy / sy
            entry.update(
                snr_median=float(np.median([r[6] for r in ok])),
                bias_x_px=float(dx.mean()), bias_y_px=float(dy.mean()),
                se_x_px=float(dx.std(ddof=1) / math.sqrt(len(ok))), se_y_px=float(dy.std(ddof=1) / math.sqrt(len(ok))),
                rms_x_px=float(dx.std(ddof=1)), rms_y_px=float(dy.std(ddof=1)),
                robust_pull_x=float(1.4826 * np.median(np.abs(px_ - np.median(px_)))), robust_pull_y=float(1.4826 * np.median(np.abs(py_ - np.median(py_)))),
            )
            ok_bias = abs(entry["bias_x_px"]) <= 0.03 and abs(entry["bias_y_px"]) <= 0.03
            ok_pull = entry["robust_pull_x"] <= 1.5 and entry["robust_pull_y"] <= 1.5
            entry["passed"] = bool(len(ok) >= 15 and ok_bias and ok_pull)
        else:
            entry["passed"] = False
        # S/N-15 injections near the S/N threshold are reported but do not gate (recovery there is partly S/N-limited)
        if target >= 30.0:
            passed_all = passed_all and entry["passed"]
        out["per_target"].append(entry)
    out["passed"] = bool(passed_all)
    out["criteria"] = ("at S/N ~ 40: >= 15 recoveries, |bias| <= 0.03 px (0.18\") per axis and robust pull width (1.4826 x MAD) <= 1.5 per axis "
                       "(uncertainties not underestimated; widths < 1 mean conservative uncertainties). S/N ~ 15 injections are reported for information.")
    return out


def injection_near_saturated(frame: FrameInputs, cat: CatalogInputs, diag: FrameDiagnosis, cfg: AlignmentConfig = AlignmentConfig(),
                             bins: tuple[tuple[float, float], ...] = ((4.0, 8.0), (8.0, 12.0), (12.0, 20.0), (20.0, 40.0)),
                             per_bin: int = 12, snr_target: float = 40.0) -> list[dict]:
    """Injection-recovery as a function of distance from the saturated source(s): checks the exclusion radius.

    Same placement rules as `injection_recovery` (clean core, no saturation flag in the window, > 3 px from
    G < 18 Gaia sources) except that positions are drawn in annuli around the nearest saturated region.
    """
    if not len(diag.saturated_xy):
        return []
    rng = np.random.default_rng(_seed(frame.frame_id + ":radial"))
    ny, nx = frame.image.shape
    h = cfg.half_window
    flags = frame.flags.astype(np.int64)
    sat_mask = _mask_of(frame.flag_masks, SATURATION_FLAGS)
    bad = (flags & excluded_mask(frame.flag_masks)) != 0
    px, py = frame.sky_to_pixel(cat.ra_deg, cat.dec_deg)
    px, py = np.asarray(px, dtype=float), np.asarray(py, dtype=float)
    bright = np.isfinite(cat.g_mag) & (cat.g_mag < 18.0)
    img0 = np.asarray(frame.image, dtype=float)
    var = np.asarray(frame.variance, dtype=float)
    good_var = np.isfinite(var) & (var > 0)
    sig_pix = float(np.nanmedian(np.sqrt(var[good_var]))) if np.any(good_var) else float("nan")
    cx, cy = diag.saturated_xy[0]
    out = []
    for r_min, r_max in bins:
        rows = []
        attempts = 0
        while len(rows) < per_bin and attempts < 600:
            attempts += 1
            r, th = rng.uniform(r_min, r_max), rng.uniform(0.0, 2.0 * math.pi)
            x0, y0 = cx + r * math.cos(th), cy + r * math.sin(th)
            ix, iy = int(round(x0)), int(round(y0))
            if ix - h < 0 or iy - h < 0 or ix + h >= nx or iy + h >= ny:
                continue
            if np.min(np.hypot(diag.saturated_xy[:, 0] - x0, diag.saturated_xy[:, 1] - y0)) < r_min:
                continue
            if np.any(flags[iy - h : iy + h + 1, ix - h : ix + h + 1] & sat_mask) or np.any(bad[iy - 1 : iy + 2, ix - 1 : ix + 2]):
                continue
            if np.any(bright & (np.hypot(px - x0, py - y0) < 3.0)):
                continue
            zone = frame.epsf.zone_index(x0 + frame.detector_offset[0], y0 + frame.detector_offset[1])
            model = frame.epsf.model(zone)
            neff = 1.0 / float(np.sum(model.render((2 * h + 1, 2 * h + 1), h + (x0 - ix), h + (y0 - iy), 1.0) ** 2))
            img = img0 + snr_target * sig_pix * math.sqrt(neff) * model.render(img0.shape, x0, y0, 1.0)
            fit = fit_position(img, var, bad, model, x0 + rng.normal(0.0, 0.3), y0 + rng.normal(0.0, 0.3), half_window=h, max_shift_px=cfg.max_shift_px)
            rows.append((fit.status, fit.x, fit.y, fit.sigma_x, fit.sigma_y, fit.snr, x0, y0))
        ok = [t for t in rows if t[0] == "ok" and t[5] is not None and t[5] >= cfg.snr_min]
        entry: dict = {"r_min_px": r_min, "r_max_px": r_max, "n_injected": len(rows), "n_recovered": len(ok)}
        if len(ok) >= 3:
            dx = np.array([t[1] - t[6] for t in ok])
            dy = np.array([t[2] - t[7] for t in ok])
            sx = np.array([t[3] for t in ok])
            sy = np.array([t[4] for t in ok])
            entry.update(bias_x_px=float(dx.mean()), bias_y_px=float(dy.mean()), rms_x_px=float(dx.std(ddof=1)), rms_y_px=float(dy.std(ddof=1)),
                         robust_pull_x=float(1.4826 * np.median(np.abs(dx / sx - np.median(dx / sx)))),
                         robust_pull_y=float(1.4826 * np.median(np.abs(dy / sy - np.median(dy / sy)))))
        out.append(entry)
    return out


# ---------------------------------------------------------------------------------------------- convention test


def aberration_displacement_arcsec(ra_deg: float, dec_deg: float, observer_velocity_km_s: np.ndarray) -> tuple[float, float]:
    """First-order stellar aberration displacement (east, north; arcsec) for an observer moving with v (ICRS axes)."""
    a, d = math.radians(ra_deg), math.radians(dec_deg)
    p = np.array([-math.sin(a), math.cos(a), 0.0])
    q = np.array([-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d)])
    v = np.asarray(observer_velocity_km_s, dtype=float) / C_KM_S
    return float(np.dot(v, p) * ARCSEC_PER_RAD), float(np.dot(v, q) * ARCSEC_PER_RAD)


def convention_test(offsets: list[tuple[float, float, float, float]], aberrations: list[tuple[float, float]]) -> dict:
    """Compare per-frame mean residuals with two hypotheses about the archive WCS frame.

    H_catalog: the WCS maps pixels to catalogue-frame directions (aberration absorbed by the fit) ->
    expected mean residual 0. H_apparent: the WCS maps to apparent directions -> expected mean
    residual = the aberration displacement. `offsets` holds (mean_e, mean_n, se_e, se_n) per frame.
    """
    if not offsets:
        return {"n_frames": 0, "decision": "not evaluated: no frame with references"}
    o = np.array(offsets, dtype=float)
    ab = np.array(aberrations, dtype=float)
    chi_cat = float(np.sum((o[:, 0] / o[:, 2]) ** 2 + (o[:, 1] / o[:, 3]) ** 2))
    chi_app = float(np.sum(((o[:, 0] - ab[:, 0]) / o[:, 2]) ** 2 + ((o[:, 1] - ab[:, 1]) / o[:, 3]) ** 2))
    dof = 2 * len(o)
    max_off = float(np.max(np.hypot(o[:, 0], o[:, 1])))
    max_off_app = float(np.max(np.hypot(o[:, 0] - ab[:, 0], o[:, 1] - ab[:, 1])))
    max_ab = float(np.max(np.hypot(ab[:, 0], ab[:, 1])))
    min_ab = float(np.min(np.hypot(ab[:, 0], ab[:, 1])))
    # Decide only when the hypotheses are separated by far more than the residual frame offsets: under the
    # favoured hypothesis every frame offset must be well below the smallest aberration displacement, and the
    # other hypothesis must be rejected outright.
    if chi_cat < chi_app and stats.chi2.sf(chi_app, dof) < 1e-6 and max_off < 0.25 * min_ab:
        decision = (f"catalogue frame (aberration absorbed by the archive WCS fit): frame offsets <= {max_off:.2f}\" against expected "
                    f"aberration displacements of {min_ab:.1f}-{max_ab:.1f}\"; chi2 exceeds dof when some frames have real offsets (translation tests)")
    elif chi_app < chi_cat and stats.chi2.sf(chi_cat, dof) < 1e-6 and max_off_app < 0.25 * min_ab:
        decision = f"apparent frame (aberration included in the archive WCS): frame offsets match the aberration to <= {max_off_app:.2f}\""
    else:
        decision = "undetermined"
    return {"n_frames": int(len(o)), "dof": int(dof), "chi2_catalog_frame": chi_cat, "chi2_apparent_frame": chi_app,
            "p_catalog_frame": float(stats.chi2.sf(chi_cat, dof)), "p_apparent_frame": float(stats.chi2.sf(chi_app, dof)),
            "max_aberration_arcsec": max_ab, "min_aberration_arcsec": min_ab, "max_frame_offset_arcsec": max_off, "decision": decision}


__all__ = [
    "ALIGNMENT_METHOD_VERSION", "AlignmentConfig", "CatalogInputs", "FrameDiagnosis", "FrameInputs", "REASONS", "ReferenceResult",
    "aberration_displacement_arcsec", "convention_test", "diagnose_frame", "evaluate_translation", "excluded_mask", "extra_scatter", "extra_scatter_pm",
    "centroid_convention_offsets", "injection_recovery", "local_wcs_jacobian", "residual_statistics", "shared_systematics", "weighted_offset", "windowed_centroid", "zone_swap_shifts",
]
