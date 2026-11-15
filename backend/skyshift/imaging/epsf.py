"""SPHEREx effective PSF (ePSF): evaluation and point-source position fitting.

Conventions (SPHEREx Explanatory Supplement v2.1, Sects. 4.1.2 and 4.2.3; the
file's own EPSF table and header):

* One 33x33 ePSF per detector zone, oversampled OVSMPX x OVSMPY (5 x 5) relative
  to the native pixels. Zone centres/widths (XCENTER, YCENTER, XWIDTH, YWIDTH)
  are 0-based detector pixel coordinates (pixel centres at integers).
* Anderson & King (2000) formalism: P_eff(dx, dy) is the fraction of the source
  flux recorded in a native pixel whose centre lies (dx, dy) native pixels from
  the source position. It already contains the detector-pixel response, so the
  model of pixel j is F * P_eff(x_j - x*, y_j - y*) + background, with no
  further integration over the pixel.
* The stored array is normalised to unit sum over the oversampled grid
  ("normalized to its integral"); samples taken at native spacing then sum to
  1/(OVSMPX*OVSMPY), so P_eff = OVSMPX * OVSMPY * stored. This is checked per
  file (`EPSFLibrary.native_sum_check`).
* The array centre, index (n - 1) / 2, is the reference point of the source
  position (photutils EPSFBuilder convention, which the SPHEREx ePSF builder
  uses; the stored peak is at that index).
* Between samples the model is a bicubic interpolating spline (scipy
  RectBivariateSpline, s = 0), as photutils ImagePSF evaluates ePSFs.

Pixel convention: 0-based, integer = pixel centre, numpy arrays indexed [iy, ix].
The fit returns a position estimate with a formal covariance; whether it is an
adequate estimator for a given frame is established by the injection-recovery
validation in skyshift.science.alignment, not assumed here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import RectBivariateSpline
from scipy.optimize import least_squares

EPSF_METHOD_VERSION = "1.0.0"


@dataclass(frozen=True)
class EPSFZone:
    index: int
    binx: int
    biny: int
    x_center: float
    y_center: float
    x_width: float
    y_width: float
    nstar: int
    neff_mean: float
    cwave_um: float
    cband_um: float

    def contains(self, det_x: float, det_y: float) -> bool:
        return abs(det_x - self.x_center) <= 0.5 * self.x_width and abs(det_y - self.y_center) <= 0.5 * self.y_width


class EPSFModel:
    """One zone's ePSF as a function of native-pixel offsets (dx, dy) from the source."""

    def __init__(self, samples: np.ndarray, oversampling: tuple[int, int]):
        s = np.asarray(samples, dtype=float)
        if s.ndim != 2 or s.shape[0] < 5 or s.shape[1] < 5:
            raise ValueError(f"ePSF samples must be a 2-D array, got shape {s.shape}")
        if not np.all(np.isfinite(s)):
            raise ValueError("ePSF samples contain non-finite values")
        ox, oy = int(oversampling[0]), int(oversampling[1])
        if ox < 1 or oy < 1:
            raise ValueError("oversampling must be >= 1")
        self.samples = s
        self.ox, self.oy = ox, oy
        self.scale = float(ox * oy)
        self.ny, self.nx = s.shape
        self.cx = (self.nx - 1) / 2.0
        self.cy = (self.ny - 1) / 2.0
        self.half_extent_px = min(self.cx / ox, self.cy / oy)
        # first spline axis = rows (y / v), second = columns (x / u)
        self._spline = RectBivariateSpline(np.arange(self.ny, dtype=float), np.arange(self.nx, dtype=float), s * self.scale, kx=3, ky=3, s=0)

    def _uv(self, dx: np.ndarray, dy: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        u = self.cx + np.asarray(dx, dtype=float) * self.ox
        v = self.cy + np.asarray(dy, dtype=float) * self.oy
        inside = (u >= 0.0) & (u <= self.nx - 1) & (v >= 0.0) & (v <= self.ny - 1)
        return u, v, inside

    def evaluate(self, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
        """P_eff at native-pixel offsets (pixel centre minus source position); 0 outside the sampled support."""
        u, v, inside = self._uv(dx, dy)
        out = np.zeros(np.broadcast(u, v).shape)
        if np.any(inside):
            uu, vv = np.broadcast_arrays(u, v)
            out[inside] = self._spline.ev(vv[inside], uu[inside])
        return out

    def evaluate_with_gradient(self, dx: np.ndarray, dy: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(P, dP/d(dx), dP/d(dy)) at native-pixel offsets (bicubic spline value and exact spline derivatives)."""
        u, v, inside = self._uv(dx, dy)
        shape = np.broadcast(u, v).shape
        p, gx, gy = np.zeros(shape), np.zeros(shape), np.zeros(shape)
        if np.any(inside):
            uu, vv = np.broadcast_arrays(u, v)
            vi, ui = vv[inside], uu[inside]
            p[inside] = self._spline(vi, ui, grid=False)
            gx[inside] = self._spline(vi, ui, dy=1, grid=False) * self.ox
            gy[inside] = self._spline(vi, ui, dx=1, grid=False) * self.oy
        return p, gx, gy

    def render(self, shape: tuple[int, int], x0: float, y0: float, flux: float) -> np.ndarray:
        """Native-pixel image (ny, nx) of a point source of total flux `flux` at (x0, y0)."""
        ny, nx = shape
        yy, xx = np.mgrid[0:ny, 0:nx]
        return flux * self.evaluate(xx - x0, yy - y0)

    def sample_exact(self, shape: tuple[int, int], x0: float, y0: float, flux: float) -> np.ndarray:
        """Render using stored samples only (no interpolation).

        Valid only when (x0, y0) is on the oversampled lattice, i.e. x0 * ox and
        y0 * oy are integers: then every native pixel centre falls exactly on a
        stored sample. Used to test the interpolating evaluation independently.
        """
        fx, fy = x0 * self.ox, y0 * self.oy
        if abs(fx - round(fx)) > 1e-9 or abs(fy - round(fy)) > 1e-9:
            raise ValueError("sample_exact needs a source position on the oversampled lattice")
        ny, nx = shape
        out = np.zeros(shape)
        for iy in range(ny):
            v = self.cy + (iy - y0) * self.oy
            vi = int(round(v))
            if not (0 <= vi < self.ny) or abs(v - vi) > 1e-9:
                continue
            for ix in range(nx):
                u = self.cx + (ix - x0) * self.ox
                ui = int(round(u))
                if 0 <= ui < self.nx and abs(u - ui) < 1e-9:
                    out[iy, ix] = flux * self.scale * self.samples[vi, ui]
        return out

    def centroid_offset_px(self) -> tuple[float, float]:
        """First moment of the stored array minus its reference point, in native pixels.

        Non-zero for an asymmetric ePSF: a centroid-type estimator and an ePSF fit
        then define positions that differ by this amount (an estimator-definition offset).
        """
        yy, xx = np.mgrid[0 : self.ny, 0 : self.nx]
        tot = float(self.samples.sum())
        return (float((self.samples * xx).sum() / tot - self.cx) / self.ox, float((self.samples * yy).sum() / tot - self.cy) / self.oy)


class EPSFLibrary:
    """All zones of one Spectral Image's EPSF table (read by column name)."""

    def __init__(self, zones: list[EPSFZone], arrays: np.ndarray, oversampling: tuple[int, int], detector: str | None = None):
        if len(zones) != len(arrays):
            raise ValueError("one ePSF array per zone is required")
        self.zones = zones
        self.arrays = np.asarray(arrays, dtype=float)
        self.oversampling = (int(oversampling[0]), int(oversampling[1]))
        self.detector = detector
        self._models: dict[int, EPSFModel] = {}

    @classmethod
    def from_hdu(cls, hdu) -> EPSFLibrary:  # noqa: ANN001 - astropy BinTableHDU
        h = hdu.header
        ox, oy = h.get("OVSMPX"), h.get("OVSMPY")
        if ox is None or oy is None:
            raise ValueError("EPSF table lacks OVSMPX/OVSMPY")
        d = hdu.data
        names = set(d.columns.names)
        required = {"XCENTER", "YCENTER", "XWIDTH", "YWIDTH", "EPSF"}
        if not required <= names:
            raise ValueError(f"EPSF table lacks columns {sorted(required - names)}")

        def col(name: str, default: float = float("nan")) -> np.ndarray:
            return np.asarray(d[name], dtype=float) if name in names else np.full(len(d), default)

        zones = [
            EPSFZone(
                index=i,
                binx=int(col("BINX", -1)[i]),
                biny=int(col("BINY", -1)[i]),
                x_center=float(col("XCENTER")[i]),
                y_center=float(col("YCENTER")[i]),
                x_width=float(col("XWIDTH")[i]),
                y_width=float(col("YWIDTH")[i]),
                nstar=int(col("NSTAR", -1)[i]),
                neff_mean=float(col("NEFF_MEAN")[i]),
                cwave_um=float(col("CWAVE")[i]),
                cband_um=float(col("CBAND")[i]),
            )
            for i in range(len(d))
        ]
        return cls(zones, np.asarray(d["EPSF"], dtype=float), (int(ox), int(oy)), str(h.get("DETECTOR", "")).strip() or None)

    def zone_index(self, det_x: float, det_y: float) -> int:
        """Zone containing the detector position; the nearest zone centre if none contains it (trimmed tables)."""
        for z in self.zones:
            if z.contains(det_x, det_y):
                return z.index
        d2 = [((z.x_center - det_x) / z.x_width) ** 2 + ((z.y_center - det_y) / z.y_width) ** 2 for z in self.zones]
        return int(np.argmin(d2))

    def zone_contains(self, index: int, det_x: float, det_y: float) -> bool:
        return self.zones[index].contains(det_x, det_y)

    def model(self, index: int) -> EPSFModel:
        if index not in self._models:
            self._models[index] = EPSFModel(self.arrays[index], self.oversampling)
        return self._models[index]

    def native_sum_check(self) -> dict[str, float]:
        """Stored sums: total over the oversampled grid and the range of native-spacing sums times ox*oy."""
        totals = self.arrays.sum(axis=(1, 2))
        ox, oy = self.oversampling
        native = [float(a[py::oy, px::ox].sum()) * ox * oy for a in self.arrays for py in range(oy) for px in range(ox)]
        return {
            "oversampled_sum_min": float(totals.min()),
            "oversampled_sum_max": float(totals.max()),
            "native_sum_scaled_min": float(min(native)),
            "native_sum_scaled_max": float(max(native)),
        }


@dataclass(frozen=True)
class PositionFit:
    """Weighted least-squares ePSF fit of one point source (native pixel coordinates)."""

    status: str  # "ok" | "edge" | "too_few_pixels" | "not_converged" | "at_bound"
    x: float | None = None
    y: float | None = None
    sigma_x: float | None = None
    sigma_y: float | None = None
    corr_xy: float | None = None
    flux: float | None = None
    sigma_flux: float | None = None
    snr: float | None = None
    background: tuple[float, float, float] | None = None
    chi2: float | None = None
    dof: int | None = None
    n_pix: int = 0
    n_masked: int = 0
    nfev: int = 0
    message: str = ""

    @property
    def chi2_red(self) -> float | None:
        return self.chi2 / self.dof if self.chi2 is not None and self.dof else None


def fit_position(
    image: np.ndarray,
    variance: np.ndarray,
    bad: np.ndarray,
    model: EPSFModel,
    x_init: float,
    y_init: float,
    half_window: int = 3,
    max_shift_px: float = 2.0,
    min_good_fraction: float = 0.75,
    background: str = "plane",
) -> PositionFit:
    """Fit x, y, flux and a local background (constant or plane) in a (2h+1)^2 window.

    Pixels with `bad` set, non-finite values or non-positive variance are excluded.
    The window is centred on the nearest pixel to (x_init, y_init) and must lie
    inside the array. A solution farther than `max_shift_px` from the initial
    guess (in x or y) is reported as 'at_bound', never as a measurement.
    Uncertainties are formal (from J^T J at the solution), scaled by
    sqrt(chi2_red) when chi2_red > 1.
    """
    ny, nx = image.shape
    ix0, iy0 = int(round(x_init)), int(round(y_init))
    h = int(half_window)
    if ix0 - h < 0 or iy0 - h < 0 or ix0 + h >= nx or iy0 + h >= ny:
        return PositionFit(status="edge", message="fit window extends beyond the image")
    sl = (slice(iy0 - h, iy0 + h + 1), slice(ix0 - h, ix0 + h + 1))
    d = np.asarray(image[sl], dtype=float)
    var = np.asarray(variance[sl], dtype=float)
    good = (~np.asarray(bad[sl], dtype=bool)) & np.isfinite(d) & np.isfinite(var) & (var > 0)
    n_total = d.size
    n_good = int(good.sum())
    if n_good < max(7, math.ceil(min_good_fraction * n_total)):
        return PositionFit(status="too_few_pixels", n_pix=n_good, n_masked=n_total - n_good,
                           message=f"{n_good} of {n_total} window pixels usable (< {min_good_fraction:.0%})")
    yy, xx = np.mgrid[iy0 - h : iy0 + h + 1, ix0 - h : ix0 + h + 1]
    xs, ys, ds = xx[good].astype(float), yy[good].astype(float), d[good]
    w = 1.0 / np.sqrt(var[good])
    plane = background == "plane"
    edge = good & ((np.abs(yy - iy0) == h) | (np.abs(xx - ix0) == h))
    b0 = float(np.median(d[edge])) if np.any(edge) else float(np.median(ds))
    f0 = max(float(np.sum(ds - b0)), float(np.sqrt(np.sum(var[good]))))
    p0 = np.array([x_init, y_init, f0, b0] + ([0.0, 0.0] if plane else []))
    lo = np.array([x_init - max_shift_px, y_init - max_shift_px, -np.inf, -np.inf] + ([-np.inf, -np.inf] if plane else []))
    hi = np.array([x_init + max_shift_px, y_init + max_shift_px, np.inf, np.inf] + ([np.inf, np.inf] if plane else []))

    last: dict[str, object] = {}

    def model_and_jac(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        key = p.tobytes()
        if last.get("key") == key:
            return last["value"]  # type: ignore[return-value]
        x0, y0, flux, c0 = p[:4]
        pv, gx, gy = model.evaluate_with_gradient(xs - x0, ys - y0)
        m = flux * pv + c0
        cols = [-flux * gx, -flux * gy, pv, np.ones_like(pv)]
        if plane:
            m = m + p[4] * (xs - ix0) + p[5] * (ys - iy0)
            cols += [xs - ix0, ys - iy0]
        last["key"], last["value"] = key, (m, np.column_stack(cols))
        return last["value"]  # type: ignore[return-value]

    def resid(p: np.ndarray) -> np.ndarray:
        return (ds - model_and_jac(p)[0]) * w

    def jac(p: np.ndarray) -> np.ndarray:
        return -model_and_jac(p)[1] * w[:, None]

    # Levenberg-Marquardt (MINPACK) without bounds; a solution farther than max_shift_px from the initial
    # position is reported as 'at_bound' (never as a measurement), which is equivalent to a bounded search box.
    sol = least_squares(resid, p0, jac=jac, method="lm", x_scale="jac", xtol=1e-10, ftol=1e-10, gtol=1e-10, max_nfev=400)
    x, y, flux = float(sol.x[0]), float(sol.x[1]), float(sol.x[2])
    del lo, hi
    npar = len(p0)
    dof = n_good - npar
    chi2 = float(np.sum(sol.fun**2))
    bg = (float(sol.x[3]), float(sol.x[4]) if plane else 0.0, float(sol.x[5]) if plane else 0.0)
    if not sol.success:
        return PositionFit(status="not_converged", x=x, y=y, flux=flux, chi2=chi2, dof=dof, n_pix=n_good, n_masked=n_total - n_good, nfev=int(sol.nfev), message=str(sol.message))
    on_bound = (abs(x - x_init) >= max_shift_px) or (abs(y - y_init) >= max_shift_px)
    jj = sol.jac
    try:
        cov = np.linalg.inv(jj.T @ jj)
    except np.linalg.LinAlgError:
        return PositionFit(status="not_converged", x=x, y=y, flux=flux, chi2=chi2, dof=dof, n_pix=n_good, n_masked=n_total - n_good, nfev=int(sol.nfev), message="singular normal matrix")
    scale = max(1.0, chi2 / dof) if dof > 0 else 1.0
    cov = cov * scale
    sx, sy, sf = (float(math.sqrt(max(cov[i, i], 0.0))) for i in (0, 1, 2))
    corr = float(cov[0, 1] / (sx * sy)) if sx > 0 and sy > 0 else None
    return PositionFit(
        status="at_bound" if on_bound else "ok",
        x=x, y=y, sigma_x=sx, sigma_y=sy, corr_xy=corr, flux=flux, sigma_flux=sf,
        snr=float(flux / sf) if sf > 0 else None, background=bg, chi2=chi2, dof=dof,
        n_pix=n_good, n_masked=n_total - n_good, nfev=int(sol.nfev),
        message="position on the search bound" if on_bound else "",
    )


__all__ = ["EPSF_METHOD_VERSION", "EPSFLibrary", "EPSFModel", "EPSFZone", "PositionFit", "fit_position"]
