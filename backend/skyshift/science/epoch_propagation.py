"""Epoch propagation of Gaia-type astrometric parameters with full covariance (vectorised).

Model, as documented for Gaia DR3 (Sect. 4.1.7 "Transformations of astrometric
data and error propagation", following ESA 1997 Vol. 1 Sect. 1.5.5 and Michalik
et al. 2014): uniform rectilinear motion relative to the solar-system
barycentre. With the normal triad (p0, q0, r0) at the reference position,
mu0 = p0 * pmra0 + q0 * pmdec0 (pmra already includes cos(dec)), the radial
proper motion mu_r0 = v_r * parallax / A (A = 1 au/yr in km/s) and t = T - T0:

    f      = [1 + 2 mu_r0 t + (mu0^2 + mu_r0^2) t^2]^(-1/2)
    u      = [r0 (1 + mu_r0 t) + mu0 t] f              (direction at T)
    plx    = plx0 f
    mu     = [mu0 (1 + mu_r0 t) - r0 mu0^2 t] f^3
    mu_r   = [mu_r0 + (mu0^2 + mu_r0^2) t] f^2

Light-time effects are neglected, as in the Gaia documentation (Sect. 4.1.4:
at most ~10 microarcsec after 10 years for normal stars). The 6x6 covariance
is propagated as C = J C0 J^T. C0 is built from the catalogue errors and
correlations and augmented with mu_r per Michalik et al. (2014):
[C0]_i6 = [C0]_i3 v_r/A, [C0]_66 = [C0]_33 (v_r^2 + s_vr^2)/A^2 + (plx s_vr/A)^2.
J is evaluated by central differences of the exact propagation (the model is
smooth; truncation error is far below the catalogue precision), and is checked
in the tests against the Gaia archive's own ESDC_EPOCH_PROP_ERROR and a Monte
Carlo propagation.

Missing quantities are explicit:
  * radial velocity absent -> v_r = 0, with an assumed dispersion
    `unknown_rv_sigma_km_s` entering the covariance (documented recommendation);
  * parallax/proper motion absent (2-parameter solution) -> not propagated;
    the position stays at the catalogue epoch and is flagged;
  * parallax non-positive or insignificant -> used only as the statistical value
    in the parallax and mu_r terms; it is never inverted into a distance.

Results are barycentric (catalogue-frame) directions at the target epoch. The
observer parallax is a separate, explicit step (`observer_parallax_offsets`).
Aberration and gravitational light deflection are never applied in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from skyshift.coords.tangent import apply_offsets_mas, offsets_mas

EPOCH_PROPAGATION_VERSION = "1.0.0"
MAS_TO_RAD = np.pi / (180.0 * 3600.0 * 1000.0)
JULIAN_YEAR_DAYS = 365.25
A_KM_YR_PER_S = 149_597_870.7 / (JULIAN_YEAR_DAYS * 86400.0)  # 1 au per Julian year, in km/s (= 4.7404704635...)
AU_MAS_YR_KM_S = A_KM_YR_PER_S * 1000.0 * 180.0 * 3600.0 / np.pi  # A in mas yr km/s (for perspective bounds)
UNKNOWN_RV_SIGMA_KM_S = 100.0
"""Assumed radial-velocity dispersion when no radial velocity is catalogued (Gaia DR3 doc Sect. 4.1.7 recommends
v_r = 0 with a large sigma, e.g. the velocity dispersion of the stellar type). 100 km/s exceeds the velocity
dispersion of thin- and thick-disc stars; the resulting term is reported per source."""
RV_BOUND_KM_S = 500.0
"""Bound on |v_r| used for the neglected-perspective-acceleration bound of sources without a radial velocity
(exceeds the radial velocities of essentially all Galactic stars except hypervelocity stars)."""

PARAMS = ("ra_cosdec", "dec", "parallax", "pmra", "pmdec", "mu_r")  # mas, mas, mas, mas/yr, mas/yr, mas/yr
# Gaia correlation column for each (i, j) of the first five parameters
CORRELATION_COLUMNS: dict[tuple[int, int], str] = {
    (0, 1): "ra_dec_corr", (0, 2): "ra_parallax_corr", (0, 3): "ra_pmra_corr", (0, 4): "ra_pmdec_corr",
    (1, 2): "dec_parallax_corr", (1, 3): "dec_pmra_corr", (1, 4): "dec_pmdec_corr",
    (2, 3): "parallax_pmra_corr", (2, 4): "parallax_pmdec_corr", (3, 4): "pmra_pmdec_corr",
}
_STEP = np.array([1.0, 1.0, 1.0, 0.1, 0.1, 0.1])  # central-difference steps in parameter units


@dataclass
class AstrometricArrays:
    """N sources with Gaia-type astrometry at one reference epoch (NaN = not catalogued)."""

    ra_deg: np.ndarray
    dec_deg: np.ndarray
    parallax_mas: np.ndarray
    pmra_mas_yr: np.ndarray
    pmdec_mas_yr: np.ndarray
    rv_km_s: np.ndarray
    sigma5: np.ndarray  # (N, 5): sigma ra* (mas), dec (mas), parallax (mas), pmra, pmdec (mas/yr); NaN where absent
    corr5: np.ndarray  # (N, 5, 5) correlation matrices (identity where absent)
    sigma_rv_km_s: np.ndarray
    ref_epoch_mjd_tdb: float

    def __len__(self) -> int:
        return len(self.ra_deg)

    @property
    def has_motion(self) -> np.ndarray:
        return np.isfinite(self.parallax_mas) & np.isfinite(self.pmra_mas_yr) & np.isfinite(self.pmdec_mas_yr)

    @property
    def has_rv(self) -> np.ndarray:
        return np.isfinite(self.rv_km_s)

    @classmethod
    def from_columns(cls, columns: dict[str, np.ndarray], ref_epoch_mjd_tdb: float) -> AstrometricArrays:
        n = len(columns["ra"])
        sig = np.column_stack([columns.get(k, np.full(n, np.nan)) for k in ("ra_error", "dec_error", "parallax_error", "pmra_error", "pmdec_error")]).astype(float)
        corr = np.repeat(np.eye(5)[None, :, :], n, axis=0)
        for (i, j), name in CORRELATION_COLUMNS.items():
            v = np.asarray(columns.get(name, np.full(n, np.nan)), dtype=float)
            v = np.where(np.isfinite(v), v, 0.0)
            corr[:, i, j] = corr[:, j, i] = v
        return cls(
            ra_deg=np.asarray(columns["ra"], dtype=float), dec_deg=np.asarray(columns["dec"], dtype=float),
            parallax_mas=np.asarray(columns["parallax"], dtype=float), pmra_mas_yr=np.asarray(columns["pmra"], dtype=float),
            pmdec_mas_yr=np.asarray(columns["pmdec"], dtype=float), rv_km_s=np.asarray(columns.get("radial_velocity", np.full(n, np.nan)), dtype=float),
            sigma5=sig, corr5=corr, sigma_rv_km_s=np.asarray(columns.get("radial_velocity_error", np.full(n, np.nan)), dtype=float),
            ref_epoch_mjd_tdb=float(ref_epoch_mjd_tdb),
        )

    def subset(self, idx: np.ndarray) -> AstrometricArrays:
        return AstrometricArrays(self.ra_deg[idx], self.dec_deg[idx], self.parallax_mas[idx], self.pmra_mas_yr[idx], self.pmdec_mas_yr[idx],
                                 self.rv_km_s[idx], self.sigma5[idx], self.corr5[idx], self.sigma_rv_km_s[idx], self.ref_epoch_mjd_tdb)


@dataclass
class PropagationResult:
    ra_deg: np.ndarray
    dec_deg: np.ndarray
    parallax_mas: np.ndarray
    pmra_mas_yr: np.ndarray
    pmdec_mas_yr: np.ndarray
    mu_r_mas_yr: np.ndarray
    cov6: np.ndarray  # (N, 6, 6) in PARAMS units; position block in the tangent plane at the propagated position
    propagated: np.ndarray  # bool: False for 2-parameter solutions (position kept at the catalogue epoch)
    rv_used_km_s: np.ndarray  # radial velocity used (0 where none is catalogued)
    rv_assumed: np.ndarray  # True where v_r = 0 was assumed
    dt_yr: float
    perspective_bound_mas: np.ndarray  # bound on the position error from an unknown v_r (|v_r| <= RV_BOUND_KM_S); 0 where v_r is known

    @property
    def sigma_ra_cosdec_mas(self) -> np.ndarray:
        return np.sqrt(np.maximum(self.cov6[:, 0, 0], 0.0))

    @property
    def sigma_dec_mas(self) -> np.ndarray:
        return np.sqrt(np.maximum(self.cov6[:, 1, 1], 0.0))

    @property
    def corr_ra_dec(self) -> np.ndarray:
        s = self.sigma_ra_cosdec_mas * self.sigma_dec_mas
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(s > 0, self.cov6[:, 0, 1] / s, 0.0)


def _triad(ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sa, ca, sd, cd = np.sin(ra), np.cos(ra), np.sin(dec), np.cos(dec)
    p = np.stack([-sa, ca, np.zeros_like(ra)], axis=-1)
    q = np.stack([-sd * ca, -sd * sa, cd], axis=-1)
    r = np.stack([cd * ca, cd * sa, sd], axis=-1)
    return p, q, r


def propagate_core(ra_deg, dec_deg, plx_mas, pmra_mas_yr, pmdec_mas_yr, mur_mas_yr, t_yr):  # noqa: ANN001, ANN201 - array in/out
    """Exact uniform-space-motion propagation (no covariance). Returns (ra_deg, dec_deg, plx, pmra, pmdec, mu_r)."""
    ra0, dec0 = np.radians(ra_deg), np.radians(dec_deg)
    p0, q0, r0 = _triad(ra0, dec0)
    pmra, pmdec, mur = (np.asarray(v, dtype=float) * MAS_TO_RAD for v in (pmra_mas_yr, pmdec_mas_yr, mur_mas_yr))
    t = np.broadcast_to(np.asarray(t_yr, dtype=float), np.shape(pmra))
    mu0 = p0 * pmra[..., None] + q0 * pmdec[..., None]
    mu2 = pmra**2 + pmdec**2
    f = 1.0 / np.sqrt(1.0 + 2.0 * mur * t + (mu2 + mur**2) * t**2)
    u = (r0 * (1.0 + mur * t)[..., None] + mu0 * t[..., None]) * f[..., None]
    plx = np.asarray(plx_mas, dtype=float) * f
    mu = (mu0 * (1.0 + mur * t)[..., None] - r0 * (mu2 * t)[..., None]) * (f**3)[..., None]
    mur_t = (mur + (mu2 + mur**2) * t) * f**2
    ra = np.mod(np.arctan2(u[..., 1], u[..., 0]), 2.0 * np.pi)
    dec = np.arctan2(u[..., 2], np.hypot(u[..., 0], u[..., 1]))
    p, q, _ = _triad(ra, dec)
    pmra_t = np.sum(p * mu, axis=-1) / MAS_TO_RAD
    pmdec_t = np.sum(q * mu, axis=-1) / MAS_TO_RAD
    return np.degrees(ra), np.degrees(dec), plx, pmra_t, pmdec_t, mur_t / MAS_TO_RAD


def initial_covariance(astro: AstrometricArrays, rv_used: np.ndarray, sigma_rv: np.ndarray) -> np.ndarray:
    """(N, 6, 6) catalogue covariance augmented with mu_r (Michalik et al. 2014)."""
    n = len(astro)
    s = np.where(np.isfinite(astro.sigma5), astro.sigma5, 0.0)
    c5 = astro.corr5 * s[:, :, None] * s[:, None, :]
    c6 = np.zeros((n, 6, 6))
    c6[:, :5, :5] = c5
    plx = np.where(np.isfinite(astro.parallax_mas), astro.parallax_mas, 0.0)
    k = rv_used / A_KM_YR_PER_S
    c6[:, :5, 5] = c5[:, :5, 2] * k[:, None]
    c6[:, 5, :5] = c6[:, :5, 5]
    c6[:, 5, 5] = c5[:, 2, 2] * (rv_used**2 + sigma_rv**2) / A_KM_YR_PER_S**2 + (plx * sigma_rv / A_KM_YR_PER_S) ** 2
    return c6


def propagate(
    astro: AstrometricArrays,
    target_mjd_tdb: float,
    *,
    unknown_rv_sigma_km_s: float = UNKNOWN_RV_SIGMA_KM_S,
    use_radial_velocity: bool = True,
) -> PropagationResult:
    """Propagate every source to `target_mjd_tdb` (barycentric directions) with full covariance."""
    t = (float(target_mjd_tdb) - astro.ref_epoch_mjd_tdb) / JULIAN_YEAR_DAYS
    n = len(astro)
    motion = astro.has_motion
    rv_known = astro.has_rv & use_radial_velocity
    rv_used = np.where(rv_known, astro.rv_km_s, 0.0)
    sigma_rv = np.where(rv_known, np.where(np.isfinite(astro.sigma_rv_km_s), astro.sigma_rv_km_s, 0.0), unknown_rv_sigma_km_s)
    plx = np.where(motion, astro.parallax_mas, 0.0)
    pmra = np.where(motion, astro.pmra_mas_yr, 0.0)
    pmdec = np.where(motion, astro.pmdec_mas_yr, 0.0)
    mur = rv_used * plx / A_KM_YR_PER_S
    x0 = np.column_stack([np.zeros(n), np.zeros(n), plx, pmra, pmdec, mur])
    ra_c, dec_c = astro.ra_deg, astro.dec_deg

    def run(dx: np.ndarray) -> np.ndarray:
        """Propagate with parameter offsets dx (N, 6); positions returned as offsets (mas) from the nominal result."""
        ra_in, dec_in = apply_offsets_mas(dx[:, 0], dx[:, 1], ra_c, dec_c) if np.any(dx[:, :2]) else (ra_c, dec_c)
        ra_in, dec_in = np.broadcast_to(ra_in, (n,)), np.broadcast_to(dec_in, (n,))
        out = propagate_core(ra_in, dec_in, x0[:, 2] + dx[:, 2], x0[:, 3] + dx[:, 3], x0[:, 4] + dx[:, 4], x0[:, 5] + dx[:, 5], np.full(n, t))
        return np.column_stack(out)

    nominal = run(np.zeros((n, 6)))
    jac = np.zeros((n, 6, 6))
    for k in range(6):
        d = np.zeros((n, 6))
        d[:, k] = _STEP[k]
        plus, minus = run(d), run(-d)
        e_p, n_p = _offsets_vec(plus[:, 0], plus[:, 1], nominal[:, 0], nominal[:, 1])
        e_m, n_m = _offsets_vec(minus[:, 0], minus[:, 1], nominal[:, 0], nominal[:, 1])
        jac[:, 0, k] = (e_p - e_m) / (2 * _STEP[k])
        jac[:, 1, k] = (n_p - n_m) / (2 * _STEP[k])
        jac[:, 2:, k] = (plus[:, 2:] - minus[:, 2:]) / (2 * _STEP[k])
    c0 = initial_covariance(astro, rv_used, sigma_rv)
    cov = jac @ c0 @ np.transpose(jac, (0, 2, 1))
    # 2-parameter solutions: position kept, covariance = catalogue position block only (motion unknown, see flags)
    if np.any(~motion):
        cov[~motion] = 0.0
        cov[~motion, :2, :2] = c0[~motion, :2, :2]
        nominal[~motion, 0], nominal[~motion, 1] = ra_c[~motion], dec_c[~motion]
        nominal[~motion, 2:] = np.nan
    mu_tot = np.hypot(pmra, pmdec)
    bound = np.where(rv_known | ~motion, 0.0, mu_tot * np.abs(plx) * RV_BOUND_KM_S * t * t / AU_MAS_YR_KM_S)
    return PropagationResult(
        ra_deg=nominal[:, 0], dec_deg=nominal[:, 1], parallax_mas=nominal[:, 2], pmra_mas_yr=nominal[:, 3], pmdec_mas_yr=nominal[:, 4],
        mu_r_mas_yr=nominal[:, 5], cov6=cov, propagated=motion, rv_used_km_s=rv_used, rv_assumed=~rv_known, dt_yr=t, perspective_bound_mas=bound,
    )


def _offsets_vec(ra: np.ndarray, dec: np.ndarray, ra0: np.ndarray, dec0: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Elementwise tangent-plane offsets (mas) of (ra, dec) about (ra0, dec0)."""
    a, d, a0, d0 = (np.radians(v) for v in (ra, dec, ra0, dec0))
    cosc = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a - a0)
    xi = np.cos(d) * np.sin(a - a0) / cosc
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a - a0)) / cosc
    return xi / MAS_TO_RAD, eta / MAS_TO_RAD


def observer_parallax_offsets(ra_deg: np.ndarray, dec_deg: np.ndarray, parallax_mas: np.ndarray, observer_bary_au: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Displacement (east, north; mas) of the observed direction from the barycentric one: -parallax * (b.p, b.q)."""
    p, q, _ = _triad(np.radians(ra_deg), np.radians(dec_deg))
    b = np.asarray(observer_bary_au, dtype=float).reshape(1, 3)
    plx = np.where(np.isfinite(parallax_mas), parallax_mas, 0.0)
    return -plx * np.sum(p * b, axis=-1), -plx * np.sum(q * b, axis=-1)


@dataclass
class ObservedPrediction:
    """Astrometric (catalogue-frame) direction seen by the observer at one epoch, with uncertainty."""

    ra_deg: np.ndarray
    dec_deg: np.ndarray
    sigma_ra_cosdec_mas: np.ndarray
    sigma_dec_mas: np.ndarray
    corr_ra_dec: np.ndarray
    parallax_offset_mas: np.ndarray  # (N, 2) east/north displacement applied for the observer parallax
    propagation: PropagationResult


def predict_observed(astro: AstrometricArrays, target_mjd_tdb: float, observer_bary_au: np.ndarray, **kw) -> ObservedPrediction:  # noqa: ANN003
    """Barycentric propagation + observer parallax (applied once). No aberration, no light deflection."""
    prop = propagate(astro, target_mjd_tdb, **kw)
    plx = np.where(prop.propagated, prop.parallax_mas, 0.0)
    de, dn = observer_parallax_offsets(prop.ra_deg, prop.dec_deg, plx, observer_bary_au)
    ra, dec = apply_offsets_mas(de, dn, prop.ra_deg, prop.dec_deg)
    ra, dec = np.atleast_1d(ra), np.atleast_1d(dec)
    # The parallax term adds (f_ra, f_dec) * d(plx) to the position: fold it into the position covariance
    # using the propagated parallax variance and its cross terms with the position (applied exactly once).
    fr, fd = observer_parallax_offsets(prop.ra_deg, prop.dec_deg, np.where(prop.propagated, 1.0, 0.0), observer_bary_au)
    c = prop.cov6
    s_e2 = c[:, 0, 0] + 2 * fr * c[:, 0, 2] + fr * fr * c[:, 2, 2]
    s_n2 = c[:, 1, 1] + 2 * fd * c[:, 1, 2] + fd * fd * c[:, 2, 2]
    s_en = c[:, 0, 1] + fr * c[:, 1, 2] + fd * c[:, 0, 2] + fr * fd * c[:, 2, 2]
    se, sn = np.sqrt(np.maximum(s_e2, 0.0)), np.sqrt(np.maximum(s_n2, 0.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        rho = np.where(se * sn > 0, s_en / (se * sn), 0.0)
    return ObservedPrediction(ra % 360.0, dec, se, sn, rho, np.column_stack([de, dn]), prop)


__all__ = [
    "A_KM_YR_PER_S", "AU_MAS_YR_KM_S", "AstrometricArrays", "EPOCH_PROPAGATION_VERSION", "ObservedPrediction", "PropagationResult",
    "RV_BOUND_KM_S", "UNKNOWN_RV_SIGMA_KM_S", "initial_covariance", "observer_parallax_offsets", "offsets_mas", "predict_observed",
    "propagate", "propagate_core",
]
