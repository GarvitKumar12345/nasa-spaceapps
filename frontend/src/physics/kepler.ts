/* Bound two-body (Kepler) orbit and a circular observer: Motion lab teaching model.
 *
 * Synthetic teaching model, not an ephemeris. Units and conventions used everywhere
 * in this module (callers convert to degrees / years for display only):
 *   - distance: AU; time: days of absolute simulation time; angles: radians;
 *   - gravitational parameter mu = G M in AU^3/day^2, mu = GAUSS_K^2 * (M / Msun).
 *     Test-particle limit: the orbiting bodies' own masses are neglected;
 *   - orbital-plane frame centred on the central mass, so the Sun sits at a focus of
 *     the ellipse (the origin). +x is the reference direction (longitude 0); angles
 *     increase counter-clockwise, which is also the (prograde) sense of motion;
 *   - omegaRad: argument of perihelion = angle from +x to the perihelion direction;
 *   - M0Rad: mean anomaly at the epoch t0Days; M(t) = M0 + n (t - t0), n = sqrt(mu / a^3).
 * Target and observer orbit the same central mass in the same plane (coplanar).
 * Omitted on purpose: planetary perturbations, light-time, aberration, inclination,
 * finite masses of the orbiting bodies. */

/** Gaussian gravitational constant k, AU^(3/2) day^-1 Msun^(-1/2) (IAU 1976). */
export const GAUSS_K = 0.01720209895
export const TWO_PI = 2 * Math.PI
export const DAYS_PER_JULIAN_YEAR = 365.25
/** 1 AU/day in km/s (IAU 2012 AU = 149 597 870.7 km; 86 400 s per day). */
export const KM_S_PER_AU_DAY = 149_597_870.7 / 86_400
/** Separations below this (AU) make the target - observer direction undefined. */
export const MIN_LINE_OF_SIGHT_AU = 1e-9

/** mu = k^2 M / Msun in AU^3/day^2. */
export function muFromSolarMasses(massSun: number): number {
  if (!Number.isFinite(massSun) || massSun <= 0) throw new RangeError(`central mass must be finite and > 0 Msun (got ${massSun})`)
  return GAUSS_K * GAUSS_K * massSun
}

export interface OrbitElements {
  /** Semimajor axis, AU (> 0). */
  a: number
  /** Eccentricity, 0 <= e < 1 (bound orbits only). */
  e: number
  /** Argument of perihelion, rad (from +x, counter-clockwise). */
  omegaRad: number
  /** Mean anomaly at t0Days, rad. */
  M0Rad: number
  /** Epoch of M0Rad, days of absolute simulation time. */
  t0Days: number
  /** G M of the central mass, AU^3/day^2 (> 0). */
  mu: number
}

export interface OrbitState {
  /** Absolute simulation time, days. */
  t: number
  /** Position relative to the central mass (the focus), AU. */
  x: number
  y: number
  /** Velocity, AU/day. */
  vx: number
  vy: number
  /** Distance from the central mass, AU. */
  r: number
  /** Eccentric anomaly, rad (continuous: same revolution count as M). */
  E: number
  /** True anomaly, rad (continuous: same revolution count as E). */
  nu: number
  /** Mean anomaly M0 + n (t - t0), rad (not reduced). */
  M: number
}

const finite = (x: number) => typeof x === 'number' && Number.isFinite(x)

/** Throws RangeError unless the elements describe a bound Kepler orbit. */
export function validateOrbit(o: OrbitElements): void {
  if (!finite(o.a) || o.a <= 0) throw new RangeError(`semimajor axis must be finite and > 0 AU (got ${o.a})`)
  if (!finite(o.e) || o.e < 0 || o.e >= 1) throw new RangeError(`eccentricity must satisfy 0 <= e < 1 for a bound orbit (got ${o.e})`)
  if (!finite(o.mu) || o.mu <= 0) throw new RangeError(`gravitational parameter mu must be finite and > 0 AU^3/day^2 (got ${o.mu})`)
  if (!finite(o.omegaRad)) throw new RangeError(`argument of perihelion must be finite (got ${o.omegaRad})`)
  if (!finite(o.M0Rad)) throw new RangeError(`mean anomaly at epoch must be finite (got ${o.M0Rad})`)
  if (!finite(o.t0Days)) throw new RangeError(`epoch t0 must be finite (got ${o.t0Days})`)
}

/** Mean motion n = sqrt(mu / a^3), rad/day. */
export function meanMotion(a: number, mu: number): number {
  if (!finite(a) || a <= 0) throw new RangeError(`semimajor axis must be finite and > 0 AU (got ${a})`)
  if (!finite(mu) || mu <= 0) throw new RangeError(`mu must be finite and > 0 (got ${mu})`)
  return Math.sqrt(mu / (a * a * a))
}

/** Orbital period P = 2 pi sqrt(a^3 / mu), days. Depends only on a and mu, never on e. */
export function period(a: number, mu: number): number {
  return TWO_PI / meanMotion(a, mu)
}

/**
 * Solve Kepler's equation E - e sin E = M for the eccentric anomaly E (radians).
 * The returned E is continuous in M: E(M + 2 pi k) = E(M) + 2 pi k.
 * Method: reduce to m = |M| mod 2 pi in [0, pi], where the root is bracketed by
 * [m, min(pi, m + e)] (because E - m = e sin E lies in [0, e] there); Newton steps
 * from E0 = m + e sin m (or E0 = pi for e > 0.8), with a bisection step whenever
 * Newton would leave the bracket. f(E) is increasing and convex on [0, pi], so this
 * converges for every 0 <= e < 1 (residual < 1e-13 checked up to e = 0.999).
 */
export function solveKepler(M: number, e: number): number {
  if (!finite(M)) throw new RangeError(`mean anomaly must be finite (got ${M})`)
  if (!finite(e) || e < 0 || e >= 1) throw new RangeError(`eccentricity must satisfy 0 <= e < 1 (got ${e})`)
  if (e === 0) return M
  const k = Math.round(M / TWO_PI)
  const reduced = M - k * TWO_PI // in [-pi, pi]
  const sign = reduced < 0 ? -1 : 1
  const m = Math.abs(reduced)
  let lo = m
  let hi = Math.min(Math.PI, m + e)
  let E = e > 0.8 ? Math.PI : m + e * Math.sin(m)
  if (E < lo) E = lo
  if (E > hi) E = hi
  for (let i = 0; i < 200; i++) {
    const f = E - e * Math.sin(E) - m
    if (Math.abs(f) <= 1e-15) break
    if (f > 0) hi = E
    else lo = E
    const fp = 1 - e * Math.cos(E) // >= 1 - e > 0
    let next = E - f / fp
    if (!(next > lo && next < hi)) next = 0.5 * (lo + hi) // safeguard: bisection
    const step = Math.abs(next - E)
    E = next
    if (step <= 1e-16 || hi - lo <= 1e-16) break
  }
  return sign * E + k * TWO_PI
}

/** True anomaly from eccentric anomaly, continuous in E (Broucke & Cefola form). */
export function trueAnomalyFromEccentric(E: number, e: number): number {
  const beta = e / (1 + Math.sqrt((1 - e) * (1 + e)))
  return E + 2 * Math.atan2(beta * Math.sin(E), 1 - beta * Math.cos(E))
}

/**
 * Heliocentric state at absolute simulation time tDays (no incremental stepping:
 * the same t always gives the same state). Perifocal position
 * x' = a (cos E - e), y' = a sqrt(1 - e^2) sin E, velocity from dE/dt = n / (1 - e cos E),
 * both rotated by omega about the focus.
 */
export function orbitState(orbit: OrbitElements, tDays: number): OrbitState {
  validateOrbit(orbit)
  if (!finite(tDays)) throw new RangeError(`time must be finite (got ${tDays})`)
  const { a, e, omegaRad, M0Rad, t0Days, mu } = orbit
  const n = Math.sqrt(mu / (a * a * a))
  const M = M0Rad + n * (tDays - t0Days)
  const E = solveKepler(M, e)
  const cosE = Math.cos(E)
  const sinE = Math.sin(E)
  const q = Math.sqrt((1 - e) * (1 + e))
  const oneMinusECosE = 1 - e * cosE
  const xp = a * (cosE - e)
  const yp = a * q * sinE
  const Edot = n / oneMinusECosE
  const vxp = -a * sinE * Edot
  const vyp = a * q * cosE * Edot
  const c = Math.cos(omegaRad)
  const s = Math.sin(omegaRad)
  return {
    t: tDays,
    x: c * xp - s * yp,
    y: s * xp + c * yp,
    vx: c * vxp - s * vyp,
    vy: s * vxp + c * vyp,
    r: a * oneMinusECosE,
    E,
    nu: trueAnomalyFromEccentric(E, e),
    M,
  }
}

/** Speed from the vis-viva relation v^2 = mu (2/r - 1/a), AU/day. */
export function visVivaSpeed(r: number, a: number, mu: number): number {
  return Math.sqrt(Math.max(0, mu * (2 / r - 1 / a)))
}

/** Specific angular momentum h = sqrt(mu a (1 - e^2)), AU^2/day. */
export function specificAngularMomentum(orbit: OrbitElements): number {
  validateOrbit(orbit)
  return Math.sqrt(orbit.mu * orbit.a * (1 - orbit.e) * (1 + orbit.e))
}

/** Areal velocity dA/dt = h / 2, AU^2/day (Kepler's second law: constant). */
export function sweptAreaRate(orbit: OrbitElements): number {
  return specificAngularMomentum(orbit) / 2
}

/** n states at t0 + k P / n, k = 0..n-1: equal time intervals of P / n. */
export function equalTimeMarkers(orbit: OrbitElements, n = 12): OrbitState[] {
  validateOrbit(orbit)
  if (!Number.isInteger(n) || n < 1) throw new RangeError(`marker count must be a positive integer (got ${n})`)
  const P = period(orbit.a, orbit.mu)
  return Array.from({ length: n }, (_, k) => orbitState(orbit, orbit.t0Days + (k * P) / n))
}

export interface CircularObserver {
  /** Orbit radius, AU (> 0). */
  radiusAu: number
  /** Longitude of the observer at t = 0 days, rad. */
  phaseRad: number
  /** G M of the (same) central mass, AU^3/day^2. */
  mu: number
}

export interface ObserverState {
  t: number
  x: number
  y: number
  vx: number
  vy: number
  r: number
  /** Heliocentric longitude, rad (not reduced). */
  longitudeRad: number
}

/** Observer on a prograde circular orbit, longitude(t) = phase + n t with n = sqrt(mu / r^3). */
export function observerState(obs: CircularObserver, tDays: number): ObserverState {
  if (!finite(obs.radiusAu) || obs.radiusAu <= 0) throw new RangeError(`observer orbit radius must be finite and > 0 AU (got ${obs.radiusAu})`)
  if (!finite(obs.mu) || obs.mu <= 0) throw new RangeError(`mu must be finite and > 0 (got ${obs.mu})`)
  if (!finite(obs.phaseRad)) throw new RangeError(`observer phase must be finite (got ${obs.phaseRad})`)
  if (!finite(tDays)) throw new RangeError(`time must be finite (got ${tDays})`)
  const r = obs.radiusAu
  const n = Math.sqrt(obs.mu / (r * r * r))
  const lon = obs.phaseRad + n * tDays
  const c = Math.cos(lon)
  const s = Math.sin(lon)
  return { t: tDays, x: r * c, y: r * s, vx: -r * n * s, vy: r * n * c, r, longitudeRad: lon }
}

export type LineOfSight =
  | { defined: true; dx: number; dy: number; distance: number; longitudeRad: number }
  | { defined: false; reason: string }

/** Viewing vector target - observer (common heliocentric frame); longitude in [0, 2 pi). */
export function lineOfSight(target: { x: number; y: number }, observer: { x: number; y: number }): LineOfSight {
  const dx = target.x - observer.x
  const dy = target.y - observer.y
  const distance = Math.hypot(dx, dy)
  if (!Number.isFinite(distance)) return { defined: false, reason: 'Target or observer position is not finite.' }
  if (distance < MIN_LINE_OF_SIGHT_AU) {
    return { defined: false, reason: `Target and observer coincide (separation below ${MIN_LINE_OF_SIGHT_AU} AU): the viewing direction is undefined.` }
  }
  let lon = Math.atan2(dy, dx)
  if (lon < 0) lon += TWO_PI
  if (lon >= TWO_PI) lon -= TWO_PI
  return { defined: true, dx, dy, distance, longitudeRad: lon }
}

/** Rate of change of the apparent longitude, rad/day, or NaN where the line of sight is undefined. */
export function apparentLongitudeRate(orbit: OrbitElements, observer: CircularObserver, tDays: number): number {
  const T = orbitState(orbit, tDays)
  const O = observerState(observer, tDays)
  const dx = T.x - O.x
  const dy = T.y - O.y
  const d2 = dx * dx + dy * dy
  if (!(d2 >= MIN_LINE_OF_SIGHT_AU * MIN_LINE_OF_SIGHT_AU)) return Number.NaN
  // d/dt atan2(dy, dx) = (dx * d(dy)/dt - dy * d(dx)/dt) / (dx^2 + dy^2)
  return (dx * (T.vy - O.vy) - dy * (T.vx - O.vx)) / d2
}

export interface RetrogradeInterval {
  /** Days. Equal to the window start if the window opens in retrograde motion. */
  start: number
  /** Days. Equal to the window end if the window closes in retrograde motion. */
  end: number
}

export interface LongitudeSeries {
  /** Sample times, days (samples with an undefined line of sight are omitted). */
  t: number[]
  /** Apparent longitude of the target seen by the observer, deg, unwrapped (continuous). */
  longitudeDeg: number[]
  /** d(longitude)/dt, deg/day (analytic, from the relative velocity). */
  rateDegPerDay: number[]
  /** Intervals where d(longitude)/dt < 0 (apparent retrograde motion). */
  retrograde: RetrogradeInterval[]
  /** Number of samples skipped because target and observer coincided. */
  undefinedSamples: number
}

const R2D = 180 / Math.PI

/**
 * Apparent longitude of the target seen from the observer at n evenly spaced times in
 * [t0, t1] (days). Unwrapping picks, at each sample, the 360-degree branch closest to the
 * trapezoidal integral of the analytic rate, so it stays continuous through fast swings.
 * Retrograde boundaries (rate = 0) are refined by bisection on the analytic rate.
 */
export function apparentLongitudeSeries(orbit: OrbitElements, observer: CircularObserver, t0: number, t1: number, n: number): LongitudeSeries {
  validateOrbit(orbit)
  if (!finite(t0) || !finite(t1) || !(t1 > t0)) throw new RangeError(`time window must be finite with t1 > t0 (got ${t0}, ${t1})`)
  if (!Number.isInteger(n) || n < 2) throw new RangeError(`sample count must be an integer >= 2 (got ${n})`)
  const t: number[] = []
  const lon: number[] = []
  const rate: number[] = []
  const retrograde: RetrogradeInterval[] = []
  let undefinedSamples = 0
  let openStart: number | null = null
  let afterGap = true // true before the first defined sample and right after an undefined one
  const rateAt = (tt: number) => apparentLongitudeRate(orbit, observer, tt)
  const zeroCrossing = (ta: number, tb: number) => {
    // rate changes sign between ta and tb; bisect on the sign of the analytic rate.
    let a = ta
    let b = tb
    const sa = rateAt(a) < 0
    for (let i = 0; i < 60; i++) {
      const m = 0.5 * (a + b)
      if (rateAt(m) < 0 === sa) a = m
      else b = m
    }
    return 0.5 * (a + b)
  }
  for (let i = 0; i < n; i++) {
    const ti = t0 + ((t1 - t0) * i) / (n - 1)
    const T = orbitState(orbit, ti)
    const O = observerState(observer, ti)
    const los = lineOfSight(T, O)
    if (!los.defined) {
      undefinedSamples++
      if (openStart !== null && t.length) retrograde.push({ start: openStart, end: t[t.length - 1] })
      openStart = null
      afterGap = true
      continue
    }
    const ri = (los.dx * (T.vy - O.vy) - los.dy * (T.vx - O.vx)) / (los.distance * los.distance)
    const raw = los.longitudeRad * R2D
    let value = raw
    if (t.length) {
      const k = t.length - 1
      const predicted = lon[k] + 0.5 * (rate[k] + ri * R2D) * (ti - t[k])
      value = raw + 360 * Math.round((predicted - raw) / 360)
    }
    if (afterGap) {
      if (ri < 0) openStart = ti
    } else {
      const k = t.length - 1
      const wasRetro = rate[k] < 0
      const isRetro = ri < 0
      if (!wasRetro && isRetro) openStart = zeroCrossing(t[k], ti)
      if (wasRetro && !isRetro && openStart !== null) {
        retrograde.push({ start: openStart, end: zeroCrossing(t[k], ti) })
        openStart = null
      }
    }
    afterGap = false
    t.push(ti)
    lon.push(value)
    rate.push(ri * R2D)
  }
  if (openStart !== null && t.length) retrograde.push({ start: openStart, end: t[t.length - 1] })
  return { t, longitudeDeg: lon, rateDegPerDay: rate, retrograde, undefinedSamples }
}

/** Synodic period 1 / |1/P1 - 1/P2| (days); Infinity when the periods are equal. */
export function synodicPeriod(p1: number, p2: number): number {
  const d = Math.abs(1 / p1 - 1 / p2)
  return d > 0 ? 1 / d : Number.POSITIVE_INFINITY
}

/** Angle reduced to [0, 2 pi). */
export function wrapTwoPi(x: number): number {
  const r = x - TWO_PI * Math.floor(x / TWO_PI)
  return r >= TWO_PI ? 0 : r
}
