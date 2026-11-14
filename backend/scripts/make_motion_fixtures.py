"""Generate fixtures/motion/*.json: independent references for the Motion lab physics.

Usage (from backend/): uv run python scripts/make_motion_fixtures.py

The TypeScript tests (frontend/src/physics/kepler.test.ts, nearbySource.test.ts)
compare the browser implementations with these values. Both references are computed
by routes that differ from the TypeScript code on purpose:

* kepler_cases.json: the two-body equations of motion r'' = -mu r / |r|^3 integrated
  numerically with scipy.integrate.solve_ivp (DOP853). No Kepler equation is solved:
  each integration starts at the time of perihelion passage t_p = t0 - M0 / n, where the
  state follows from geometry and vis-viva alone (r = a(1-e), v = sqrt(mu(1+e)/(a(1-e)))).
  Each requested time is a separate integration ending exactly on that time (no dense-
  output interpolation). The integrator error is estimated from a second run with
  10x tighter tolerances and from the drift of energy and angular momentum.
* nearby_source_cases.json: a numpy vector model of the declared nearby-source geometry
  written independently of the TypeScript: the local triad comes from a rotation matrix,
  the space velocity from D * mu (rad/yr), the observer from the backend teaching
  observer (skyshift.coords.observer.circular_observer_ecliptic_au), and the offsets from
  the spherical-trigonometry form of the gnomonic projection applied to the apparent
  ecliptic longitude/latitude (cross-checked against skyshift.coords.tangent.offsets_mas).

Units: AU, days, radians (Kepler); pc, mas, mas/yr, Julian years from the model epoch
(nearby source). Everything here is a synthetic teaching model, not an ephemeris.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import solve_ivp

from skyshift.coords.observer import circular_observer_ecliptic_au
from skyshift.coords.tangent import offsets_mas

OUT = Path(__file__).resolve().parents[2] / "fixtures" / "motion"
GENERATOR = "backend/scripts/make_motion_fixtures.py"

GAUSS_K = 0.01720209895  # AU^(3/2) day^-1 Msun^(-1/2)
RTOL, ATOL = 1e-12, 1e-14
RTOL_REF, ATOL_REF = 1e-13, 1e-15

MAS_PER_RAD = 180.0 / np.pi * 3600.0 * 1000.0
AU_PER_PC = 648000.0 / np.pi  # IAU 2015 B2


def _versions() -> dict:
    return {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}


# ---------------------------------------------------------------- Kepler / two-body


def _rhs(_t: float, w: np.ndarray, mu: float) -> list[float]:
    x, y, vx, vy = w
    r3 = (x * x + y * y) ** 1.5
    return [vx, vy, -mu * x / r3, -mu * y / r3]


def _perihelion_state(a: float, e: float, omega: float, mu: float) -> np.ndarray:
    """State at perihelion from geometry + vis-viva only (no anomalies)."""
    rp = a * (1.0 - e)
    vp = np.sqrt(mu * (1.0 + e) / (a * (1.0 - e)))
    c, s = np.cos(omega), np.sin(omega)
    # perifocal: position along +x', velocity along +y' (prograde), rotated by omega
    return np.array([rp * c, rp * s, -vp * s, vp * c])


def _propagate(w0: np.ndarray, tp: float, t: float, mu: float, rtol: float, atol: float) -> np.ndarray:
    if t == tp:
        return w0.copy()
    sol = solve_ivp(_rhs, (tp, t), w0, method="DOP853", rtol=rtol, atol=atol, args=(mu,))
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol.y[:, -1]


def kepler_cases() -> dict:
    specs = [
        # label, a [AU], e, omega [deg], M0 [rad], t0 [day], central mass [Msun]
        ("circular, 1 AU, 1 Msun", 1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        ("e = 0.3, a = 2.5 AU, 0.5 Msun", 2.5, 0.3, 40.0, 1.0, 100.0, 0.5),
        ("e = 0.7, a = 5.2 AU, 1 Msun", 5.2, 0.7, 250.0, 4.0, -300.0, 1.0),
        ("e = 0.95, a = 17.8 AU, 2 Msun", 17.8, 0.95, 111.0, 0.2, 1000.0, 2.0),
        ("e = 0.95, a = 0.8 AU, 0.3 Msun", 0.8, 0.95, 300.0, 5.9, 50.0, 0.3),
    ]
    fractions = [-0.37, 0.0, 0.013, 0.11, 0.5, 0.93, 1.0, 1.42, 2.07, 2.75]
    cases = []
    for label, a, e, omega_deg, m0, t0, mass in specs:
        mu = GAUSS_K**2 * mass
        n = np.sqrt(mu / a**3)
        period = 2.0 * np.pi / n
        tp = t0 - m0 / n  # mean anomaly is M = n (t - t_p) by definition
        omega = np.radians(omega_deg)
        w0 = _perihelion_state(a, e, omega, mu)
        times = sorted({t0 + f * period for f in fractions} | {tp + period, tp + 2.0 * period + 0.004 * period})
        energy0 = 0.5 * (w0[2] ** 2 + w0[3] ** 2) - mu / np.hypot(w0[0], w0[1])
        h0 = w0[0] * w0[3] - w0[1] * w0[2]
        states, est_err, est_verr, max_rel_energy, max_rel_h = [], 0.0, 0.0, 0.0, 0.0
        one_orbit = solve_ivp(_rhs, (tp, tp + period), w0, method="DOP853", rtol=RTOL, atol=ATOL, args=(mu,))
        for t in times:
            w = _propagate(w0, tp, t, mu, RTOL, ATOL)
            w_ref = _propagate(w0, tp, t, mu, RTOL_REF, ATOL_REF)
            est_err = max(est_err, float(np.hypot(w[0] - w_ref[0], w[1] - w_ref[1])))
            est_verr = max(est_verr, float(np.hypot(w[2] - w_ref[2], w[3] - w_ref[3])))
            r = np.hypot(w[0], w[1])
            energy = 0.5 * (w[2] ** 2 + w[3] ** 2) - mu / r
            h = w[0] * w[3] - w[1] * w[2]
            max_rel_energy = max(max_rel_energy, abs(energy / energy0 - 1.0))
            max_rel_h = max(max_rel_h, abs(h / h0 - 1.0))
            states.append({"t": t, "x": w[0], "y": w[1], "vx": w[2], "vy": w[3], "periods_from_perihelion_start": (t - tp) / period})
        cases.append({
            "label": label,
            "elements": {"a": a, "e": e, "omegaRad": omega, "M0Rad": m0, "t0Days": t0, "mu": mu, "mass_msun": mass},
            "period_days": period,
            "perihelion_time_days": tp,
            "states": states,
            "integrator_error_estimate_au": est_err,
            "integrator_velocity_error_estimate_au_per_day": est_verr,
            "steps_per_orbit": int(one_orbit.t.size - 1),
            "max_relative_energy_drift": max_rel_energy,
            "max_relative_angular_momentum_drift": max_rel_h,
            "max_periods_propagated": max(abs(s["periods_from_perihelion_start"]) for s in states),
        })
    return {
        "generator": GENERATOR,
        "versions": _versions(),
        "units": {"distance": "AU", "time": "day", "angle": "rad", "mu": "AU^3/day^2 (mu = k^2 M/Msun, k = 0.01720209895)"},
        "method": (
            "scipy.integrate.solve_ivp, DOP853, rtol=1e-12, atol=1e-14, on r'' = -mu r/|r|^3 (2-D, test particle). "
            "Initial state at perihelion passage t_p = t0 - M0/n from r = a(1-e), v = sqrt(mu(1+e)/(a(1-e))) rotated by omega; "
            "no Kepler equation is solved. One integration per requested time, ending exactly on it (no interpolation)."
        ),
        "tolerance_rationale": (
            "DOP853 controls the local error per step to ~rtol*|y| + atol. For the Kepler problem the global error is "
            "dominated by an along-track phase error that grows roughly linearly with the number of orbits propagated, "
            "concentrated at perihelion for high e. integrator_error_estimate_au is the largest position difference from a "
            "run with 10x tighter tolerances (rtol=1e-13, atol=1e-15), i.e. an estimate of this fixture's own error. "
            "steps_per_orbit records how many steps one orbit takes; if every local error (~rtol) added coherently, the "
            "relative error after N orbits would be ~steps_per_orbit * rtol * N. The browser comparison allows 10x the larger "
            "of that propagation bound (scaled by a for positions, by the perihelion speed for velocities; N >= 1) and the "
            "estimated error. Any convention error (wrong focus, sense of motion, epoch or unit) is >= 1e-3 * a."
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------- nearby source


def _rot_y(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _rot_z(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _gnomonic_spherical(lon: np.ndarray, lat: np.ndarray, lon0: float, lat0: float) -> tuple[np.ndarray, np.ndarray]:
    """Gnomonic (TAN) projection in spherical-trigonometry form; radians in, radians out."""
    dl = lon - lon0
    cos_c = np.sin(lat0) * np.sin(lat) + np.cos(lat0) * np.cos(lat) * np.cos(dl)
    xi = np.cos(lat) * np.sin(dl) / cos_c
    eta = (np.cos(lat0) * np.sin(lat) - np.sin(lat0) * np.cos(lat) * np.cos(dl)) / cos_c
    return xi, eta


def nearby_offsets_mas(d_pc: float, beta_deg: float, pm_e: float, pm_n: float, phi0: float, t_yr: np.ndarray, pm_on: bool, plx_on: bool) -> tuple[np.ndarray, np.ndarray]:
    beta = np.radians(beta_deg)
    lon0 = 0.0
    # Local triad at (lon0, beta): columns = (radial, east, north) of Rz(lon0) Ry(-beta).
    triad = _rot_z(lon0) @ _rot_y(-beta)
    radial, east, north = triad[:, 0], triad[:, 1], triad[:, 2]
    dist_au = d_pc * AU_PER_PC
    # Space velocity = distance * angular rate (rad/yr): AU/yr.
    vel = dist_au * (pm_e * east + pm_n * north) / MAS_PER_RAD if pm_on else np.zeros(3)
    pos = dist_au * radial[None, :] + t_yr[:, None] * vel[None, :]
    obs = circular_observer_ecliptic_au(t_yr, phi0) if plx_on else np.zeros((t_yr.size, 3))
    s = pos - obs
    lon = np.arctan2(s[:, 1], s[:, 0])
    lat = np.arctan2(s[:, 2], np.hypot(s[:, 0], s[:, 1]))
    xi, eta = _gnomonic_spherical(lon, lat, lon0, beta)
    east_mas, north_mas = xi * MAS_PER_RAD, eta * MAS_PER_RAD
    # Cross-check with the backend gnomonic implementation (treating lon/lat as ra/dec).
    e_chk, n_chk = offsets_mas(np.degrees(lon) % 360.0, np.degrees(lat), lon0, beta_deg)
    assert np.allclose(e_chk, east_mas, rtol=0, atol=1e-6) and np.allclose(n_chk, north_mas, rtol=0, atol=1e-6)
    return east_mas, north_mas


def nearby_cases() -> dict:
    specs = [
        # distance [pc], ecliptic latitude [deg], pm east, pm north [mas/yr], observer phase phi0 [rad]
        (10.0, 30.0, 120.0, -80.0, 0.0),
        (1.3, 0.0, -3000.0, 1500.0, 1.0),
        (50.0, 90.0, 10.0, 25.0, 2.5),
        (4.0, -62.0, 500.0, 700.0, 4.0),
        (250.0, -90.0, 0.0, 0.0, 0.3),
        (2.5, 12.0, -800.0, -1200.0, 5.5),
    ]
    t_yr = np.array([-1.3, 0.0, 0.125, 0.37, 0.5, 1.0, 1.75, 3.2, 7.9])
    cases = []
    for d, beta, pm_e, pm_n, phi0 in specs:
        variants = []
        for pm_on, plx_on in ((True, True), (True, False), (False, True), (False, False)):
            e, n = nearby_offsets_mas(d, beta, pm_e, pm_n, phi0, t_yr, pm_on, plx_on)
            variants.append({"properMotion": pm_on, "parallax": plx_on, "east_mas": e.tolist(), "north_mas": n.tolist()})
        cases.append({
            "params": {"distancePc": d, "eclipticLatDeg": beta, "pmEastMasYr": pm_e, "pmNorthMasYr": pm_n, "observerPhaseRad": phi0},
            "t_yr": t_yr.tolist(),
            "variants": variants,
        })
    return {
        "generator": GENERATOR,
        "versions": _versions(),
        "units": {"distance": "pc", "offsets": "mas (gnomonic, east = +ecliptic longitude, north = +ecliptic latitude)", "proper_motion": "mas/yr", "time": "Julian years from the model epoch (synthetic)", "phase": "rad"},
        "geometry": (
            "Heliocentric ecliptic frame. Source at ecliptic longitude 0, latitude beta, distance d at t = 0; constant space "
            "velocity d*mu in the plane of the sky (radial velocity 0, declared). Observer on a circular 1 AU ecliptic orbit "
            "of period 1 Julian year (teaching approximation; skyshift.coords.observer.circular_observer_ecliptic_au), or at "
            "the Sun when parallax is off. Apparent direction = source - observer; offsets on the tangent plane at the t = 0 "
            "heliocentric direction."
        ),
        "method": "numpy rotation-matrix triad + spherical-trig gnomonic projection of the apparent longitude/latitude (independent of the TypeScript dot-product form).",
        "tolerance_rationale": (
            "Both implementations are closed-form double-precision vector geometry. The source is ~2e5-5e7 AU away, so "
            "position components carry ~1e-16 relative rounding, i.e. ~1e-16 rad ~ 2e-8 mas in direction; converting to "
            "longitude/latitude and back adds similar terms. A parity tolerance of 1e-6 mas is ~50x the expected rounding."
        ),
        "cases": cases,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    k = kepler_cases()
    (OUT / "kepler_cases.json").write_text(json.dumps(k, indent=1) + "\n", encoding="utf-8")
    (OUT / "nearby_source_cases.json").write_text(json.dumps(nearby_cases(), indent=1) + "\n", encoding="utf-8")
    for c in k["cases"]:
        print(
            f"{c['label']:<34} est. integrator error {c['integrator_error_estimate_au']:.2e} AU over "
            f"{c['max_periods_propagated']:.2f} orbits ({c['steps_per_orbit']} steps/orbit, v err "
            f"{c['integrator_velocity_error_estimate_au_per_day']:.1e} AU/d); energy drift {c['max_relative_energy_drift']:.1e}, "
            f"h drift {c['max_relative_angular_momentum_drift']:.1e}"
        )
    print(f"wrote {OUT} ({sys.executable})")


if __name__ == "__main__":
    main()
