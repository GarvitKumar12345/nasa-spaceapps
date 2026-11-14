"""Registration of a frame to reference star positions (similarity transform).

A detection at native pixel p maps to the reference positions' pixel frame via
T(p) = [[a, -b], [b, a]] p + t. The registered WCS is the frame's nominal
header WCS composed with T. For pure TAN headers T folds exactly into a new
CRPIX/CD (`RegisteredWCS.to_description`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from astropy.wcs import WCS
from scipy import stats
from scipy.spatial import cKDTree

from skyshift.contracts import Quality, RegistrationSummary, WCSDescription
from skyshift.coords.wcs import has_sip, local_jacobian_mas_per_px, make_tan_wcs, pixel_to_sky, sky_to_pixel, wcs_to_description

REGISTRATION_METHOD = "similarity transform fit of detected stars to reference positions with iterative 3-sigma clipping"
REGISTRATION_METHOD_VERSION = "1.0.0"


@dataclass(frozen=True)
class SimilarityTransform:
    a: float = 1.0
    b: float = 0.0
    tx: float = 0.0
    ty: float = 0.0

    @property
    def matrix(self) -> np.ndarray:
        return np.array([[self.a, -self.b], [self.b, self.a]])

    @property
    def scale(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def rotation_deg(self) -> float:
        return math.degrees(math.atan2(self.b, self.a))

    def apply(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        return self.a * x - self.b * y + self.tx, self.b * x + self.a * y + self.ty

    def inverse(self) -> SimilarityTransform:
        d = self.a**2 + self.b**2
        ia, ib = self.a / d, -self.b / d
        return SimilarityTransform(ia, ib, -(ia * self.tx - ib * self.ty), -(ib * self.tx + ia * self.ty))

    def shift_at(self, x: float, y: float) -> tuple[float, float]:
        xt, yt = self.apply(np.array(x), np.array(y))
        return float(xt) - x, float(yt) - y


def _design(src: np.ndarray) -> np.ndarray:
    n = len(src)
    a = np.zeros((2 * n, 4))
    a[0::2, 0], a[0::2, 1], a[0::2, 2] = src[:, 0], -src[:, 1], 1.0
    a[1::2, 0], a[1::2, 1], a[1::2, 3] = src[:, 1], src[:, 0], 1.0
    return a


@dataclass
class SimilarityFit:
    transform: SimilarityTransform
    cov: np.ndarray  # 4x4 on (a, b, tx, ty)
    used: np.ndarray  # bool (N,)
    residuals: np.ndarray  # (N, 2) dst - T(src), px
    chi2: float
    dof: int


def fit_similarity(
    src: np.ndarray,
    dst: np.ndarray,
    cov_src: np.ndarray | None = None,
    cov_dst: np.ndarray | None = None,
    clip_sigma: float = 3.0,
    max_iter: int = 8,
    min_points: int = 3,
) -> SimilarityFit:
    """Weighted LSQ similarity fit dst ~ T(src) with iterative clipping.

    Residual covariance per point = cov_dst + s^2 cov_src (s ~ 1 here). Points
    whose Mahalanobis residual exceeds the 2-D equivalent of `clip_sigma`
    (scaled by a robust, median-based estimate of the residual scale when that
    exceeds 1, so a single strong outlier cannot inflate the cut) are rejected
    and the fit is repeated.
    """
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    n = len(src)
    if n < min_points:
        raise ValueError(f"need at least {min_points} matched points, got {n}")
    cov = np.zeros((n, 2, 2))
    if cov_src is not None:
        cov += cov_src
    if cov_dst is not None:
        cov += cov_dst
    if cov_src is None and cov_dst is None:
        cov[:] = np.eye(2)
    whit = np.array([np.linalg.inv(np.linalg.cholesky(c)) for c in cov])
    cut = math.sqrt(stats.chi2.ppf(1.0 - 2.0 * stats.norm.sf(clip_sigma), df=2))
    used = np.ones(n, dtype=bool)
    params = np.array([1.0, 0.0, 0.0, 0.0])
    for _ in range(max_iter):
        a = _design(src[used])
        y = dst[used].reshape(-1)
        w = whit[used]
        aw = np.einsum("nij,njk->nik", w, a.reshape(-1, 2, 4)).reshape(-1, 4)
        yw = np.einsum("nij,nj->ni", w, y.reshape(-1, 2)).reshape(-1)
        params, *_ = np.linalg.lstsq(aw, yw, rcond=None)
        model = (_design(src) @ params).reshape(-1, 2)
        resid = dst - model
        maha = np.sqrt(np.einsum("ni,nij,nj->n", resid, np.linalg.inv(cov), resid))
        # Median of a 2-D Mahalanobis distance (Rayleigh, sigma 1) is sqrt(2 ln 2).
        robust = float(np.median(maha[used])) / math.sqrt(2.0 * math.log(2.0))
        scale = max(1.0, robust)
        new_used = maha <= cut * scale
        if new_used.sum() < min_points:
            break
        if np.array_equal(new_used, used):
            break
        used = new_used
    a = _design(src[used])
    w = whit[used]
    aw = np.einsum("nij,njk->nik", w, a.reshape(-1, 2, 4)).reshape(-1, 4)
    pcov = np.linalg.inv(aw.T @ aw)
    model = (_design(src) @ params).reshape(-1, 2)
    resid = dst - model
    maha = np.sqrt(np.einsum("ni,nij,nj->n", resid, np.linalg.inv(cov), resid))
    dof = 2 * int(used.sum()) - 4
    return SimilarityFit(SimilarityTransform(*map(float, params)), pcov, used, resid, float(np.sum(maha[used] ** 2)), dof)


def match_by_offset_voting(
    xy_det: np.ndarray, xy_ref: np.ndarray, max_shift_px: float = 15.0, tol_px: float = 1.5
) -> list[tuple[int, int]]:
    """Find the common shift by voting on pairwise offsets, then mutual nearest matches within tol."""
    xy_det = np.asarray(xy_det, dtype=float)
    xy_ref = np.asarray(xy_ref, dtype=float)
    if len(xy_det) == 0 or len(xy_ref) == 0:
        return []
    off = (xy_ref[None, :, :] - xy_det[:, None, :]).reshape(-1, 2)
    off = off[np.all(np.abs(off) <= max_shift_px, axis=1)]
    if len(off) == 0:
        return []
    nbins = max(1, int(math.ceil(2 * max_shift_px / tol_px)))
    hist, xe, ye = np.histogram2d(off[:, 0], off[:, 1], bins=nbins, range=[[-max_shift_px, max_shift_px], [-max_shift_px, max_shift_px]])
    i, j = np.unravel_index(np.argmax(hist), hist.shape)
    cx, cy = 0.5 * (xe[i] + xe[i + 1]), 0.5 * (ye[j] + ye[j + 1])
    near = off[np.hypot(off[:, 0] - cx, off[:, 1] - cy) <= tol_px * 1.5]
    shift = np.median(near, axis=0) if len(near) else np.array([cx, cy])
    tree = cKDTree(xy_ref)
    moved = xy_det + shift
    d, idx = tree.query(moved, distance_upper_bound=tol_px)
    back = cKDTree(moved)
    pairs: list[tuple[int, int]] = []
    for k, (dist, j_ref) in enumerate(zip(d, idx, strict=True)):
        if not np.isfinite(dist):
            continue
        _, k_back = back.query(xy_ref[j_ref])
        if k_back == k:
            pairs.append((k, int(j_ref)))
    return pairs


class RegisteredWCS:
    """Nominal header WCS composed with a native-pixel similarity pre-transform."""

    def __init__(self, nominal: WCS, transform: SimilarityTransform) -> None:
        self.nominal = nominal
        self.transform = transform
        self._inverse = transform.inverse()

    def pixel_to_sky(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xt, yt = self.transform.apply(x, y)
        return pixel_to_sky(self.nominal, xt, yt)

    def sky_to_pixel(self, ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xn, yn = sky_to_pixel(self.nominal, ra, dec)
        return self._inverse.apply(xn, yn)

    def as_astropy(self) -> WCS:
        """Fold T into CRPIX/CD exactly (pure TAN only)."""
        if has_sip(self.nominal):
            raise NotImplementedError("Folding a pixel transform into a SIP-distorted WCS is not supported")
        cd = np.asarray(self.nominal.pixel_scale_matrix, dtype=float)
        m = self.transform.matrix
        crpix0 = np.asarray(self.nominal.wcs.crpix, dtype=float) - 1.0
        new_crpix0 = np.linalg.solve(m, crpix0 - np.array([self.transform.tx, self.transform.ty]))
        w = make_tan_wcs(float(self.nominal.wcs.crval[0]), float(self.nominal.wcs.crval[1]), 1.0, (2, 2))
        w.wcs.crpix = new_crpix0 + 1.0
        w.wcs.cd = cd @ m
        if self.nominal.pixel_shape is not None:
            w.pixel_shape = self.nominal.pixel_shape
        w.wcs.set()
        return w

    def to_description(self, shape: tuple[int, int], kind: str = "registered") -> WCSDescription:
        return wcs_to_description(self.as_astropy(), shape, kind)


@dataclass
class RegistrationResult:
    summary: RegistrationSummary
    wcs: RegisteredWCS
    fit: SimilarityFit | None
    matches: list[tuple[int, int]]
    residuals_mas: np.ndarray  # (n_matched, 2) east/north, mas
    used: np.ndarray
    ref_ids_used: list[str] = field(default_factory=list)


def _cov_mas_to_px(nominal: WCS, x: float, y: float, cov_mas: np.ndarray) -> np.ndarray:
    jinv = np.linalg.inv(local_jacobian_mas_per_px(nominal, x, y))
    return jinv @ cov_mas @ jinv.T


def register_frame(
    det_xy: np.ndarray,
    det_cov: np.ndarray,
    nominal_wcs: WCS,
    ref_ra: np.ndarray,
    ref_dec: np.ndarray,
    ref_cov_mas: np.ndarray,
    ref_ids: list[str],
    reference_label: str,
    max_shift_px: float = 15.0,
    match_tol_px: float = 1.5,
    clip_sigma: float = 3.0,
    min_stars: int = 6,
) -> RegistrationResult:
    """Register one frame: detections -> reference positions projected through the header WCS."""
    det_xy = np.asarray(det_xy, dtype=float)
    rx, ry = sky_to_pixel(nominal_wcs, np.asarray(ref_ra), np.asarray(ref_dec))
    ref_xy = np.column_stack([rx, ry])
    pairs = match_by_offset_voting(det_xy, ref_xy, max_shift_px=max_shift_px, tol_px=match_tol_px)
    if len(pairs) < max(3, min_stars):
        summary = RegistrationSummary(
            method=REGISTRATION_METHOD, method_version=REGISTRATION_METHOD_VERSION, reference=reference_label,
            n_matched=len(pairs), n_used=0, n_rejected=len(pairs), rms_residual_mas=None, median_abs_residual_mas=None,
            transform={"dx_px": 0.0, "dy_px": 0.0, "rotation_deg": 0.0, "scale": 1.0},
            quality=Quality(status="rejected", flags=["TOO_FEW_REFERENCE_MATCHES"],
                            messages=[f"Only {len(pairs)} reference stars matched (need {min_stars}); frame left unregistered."]),
        )
        return RegistrationResult(summary, RegisteredWCS(nominal_wcs, SimilarityTransform()), None, pairs, np.zeros((0, 2)), np.zeros(0, bool))
    di = np.array([p[0] for p in pairs])
    ri = np.array([p[1] for p in pairs])
    src = det_xy[di]
    dst = ref_xy[ri]
    cov_dst = np.array([_cov_mas_to_px(nominal_wcs, float(dst[k, 0]), float(dst[k, 1]), ref_cov_mas[ri[k]]) for k in range(len(ri))])
    fit = fit_similarity(src, dst, cov_src=np.asarray(det_cov)[di], cov_dst=cov_dst, clip_sigma=clip_sigma)
    reg = RegisteredWCS(nominal_wcs, fit.transform)
    jac = local_jacobian_mas_per_px(nominal_wcs, float(np.mean(dst[:, 0])), float(np.mean(dst[:, 1])))
    res_mas = (jac @ fit.residuals.T).T
    used_res = res_mas[fit.used]
    rms = float(math.sqrt(np.mean(np.sum(used_res**2, axis=1)))) if len(used_res) else None
    med = float(np.median(np.hypot(used_res[:, 0], used_res[:, 1]))) if len(used_res) else None
    ny, nx = (nominal_wcs.pixel_shape[1], nominal_wcs.pixel_shape[0]) if nominal_wcs.pixel_shape else (0, 0)
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    dx, dy = fit.transform.shift_at(cx, cy)
    g = np.array([[cx, -cy, 1.0, 0.0], [cy, cx, 0.0, 1.0]])
    shift_cov = g @ fit.cov @ g.T
    a, b = fit.transform.a, fit.transform.b
    s2 = a * a + b * b
    j_rot = np.array([-b / s2, a / s2]) * 180.0 / math.pi
    j_scale = np.array([a, b]) / math.sqrt(s2)
    ab_cov = fit.cov[:2, :2]
    chi2_dof = fit.chi2 / fit.dof if fit.dof > 0 else None
    n_used = int(fit.used.sum())
    flags: list[str] = []
    messages: list[str] = []
    if n_used < min_stars:
        flags.append("FEW_REFERENCE_STARS")
    if chi2_dof is not None and chi2_dof > 3:
        flags.append("HIGH_REGISTRATION_CHI2")
        messages.append(f"Registration chi2/dof = {chi2_dof:.2f}: residuals exceed the position uncertainties.")
    rejected_ids = [ref_ids[ri[k]] for k in range(len(ri)) if not fit.used[k]]
    if rejected_ids:
        messages.append(f"{len(rejected_ids)} matched star(s) rejected by clipping (non-stationary or outliers).")
    summary = RegistrationSummary(
        method=REGISTRATION_METHOD,
        method_version=REGISTRATION_METHOD_VERSION,
        reference=reference_label,
        n_matched=len(pairs),
        n_used=n_used,
        n_rejected=len(pairs) - n_used,
        rms_residual_mas=rms,
        median_abs_residual_mas=med,
        transform={"dx_px": dx, "dy_px": dy, "rotation_deg": fit.transform.rotation_deg, "scale": fit.transform.scale},
        transform_uncertainty={
            "dx_px": float(math.sqrt(shift_cov[0, 0])),
            "dy_px": float(math.sqrt(shift_cov[1, 1])),
            "rotation_deg": float(math.sqrt(j_rot @ ab_cov @ j_rot)),
            "scale": float(math.sqrt(j_scale @ ab_cov @ j_scale)),
        },
        chi2_per_dof=chi2_dof,
        excluded_source_ids=rejected_ids,
        quality=Quality(status="warning" if flags else "ok", flags=flags, messages=messages),
    )
    return RegistrationResult(summary, reg, fit, pairs, res_mas, fit.used, [ref_ids[ri[k]] for k in range(len(ri)) if fit.used[k]])


def registration_cov_mas(result: RegistrationResult, x: float, y: float) -> np.ndarray:
    """2x2 covariance (mas^2, east/north) of the registered position at native pixel (x, y) due to the transform fit."""
    if result.fit is None:
        return np.zeros((2, 2))
    g = np.array([[x, -y, 1.0, 0.0], [y, x, 0.0, 1.0]])
    cov_px = g @ result.fit.cov @ g.T
    xt, yt = result.fit.transform.apply(np.array(x), np.array(y))
    jac = local_jacobian_mas_per_px(result.wcs.nominal, float(xt), float(yt))
    return jac @ cov_px @ jac.T
