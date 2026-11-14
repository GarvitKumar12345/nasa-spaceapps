/* Nearby source with independently switchable proper motion and annual parallax.
 * Motion lab teaching model (synthetic); the sky path is derived from declared
 * source and observer geometry (vectors), not from a prescribed sine wave.
 *
 * Frame: heliocentric ecliptic Cartesian, AU. +x toward ecliptic longitude 0
 * (reference direction), +z toward the north ecliptic pole.
 * Time: Julian years from the model epoch t = 0 (synthetic; 1 Julian year = 365.25 d).
 * Declared geometry:
 *   - source at ecliptic longitude 0 and latitude beta at t = 0, at distance d (pc) from
 *     the Sun: P(0) = D u0 with D = d * AU_PER_PC (AU);
 *   - constant space velocity in the plane of the sky at t = 0, v = mu * d along local
 *     east/north (AU/yr for mu in arcsec/yr and d in pc; here mu in mas/yr -> v = mu d / 1000);
 *     radial velocity 0 (declared). Proper motion off -> v = 0;
 *   - observer on a circular 1 AU orbit in the ecliptic, period 1 Julian year, prograde,
 *     longitude phi0 + 2 pi t (the convention of backend/skyshift/coords/observer.py,
 *     circular_observer_ecliptic_au). This is an approximation: the real Earth orbit has
 *     e = 0.0167 and the Sun is offset from the barycentre. Parallax off -> observer at the Sun.
 * Apparent direction = source position - observer position (no light-time, aberration
 * or light deflection). Offsets: gnomonic projection onto the tangent plane at the t = 0
 * heliocentric direction u0, east = increasing ecliptic longitude, north = increasing
 * ecliptic latitude, in mas. */
import { MAS_PER_RAD } from '../lib/tangent'

/** AU per parsec (IAU 2015 Resolution B2: 1 pc = 648000/pi au). */
export const AU_PER_PC = 648000 / Math.PI
/** 1 AU per Julian year in km/s (149 597 870.7 km / (365.25 * 86 400 s)). */
export const KM_S_PER_AU_YR = 149_597_870.7 / (365.25 * 86_400)

const D2R = Math.PI / 180

export interface NearbyParams {
  /** Distance from the Sun, pc (> 0). */
  distancePc: number
  /** Ecliptic latitude beta at t = 0, deg in [-90, 90]; ecliptic longitude is 0 by construction. */
  eclipticLatDeg: number
  /** Proper motion along local ecliptic east (mu_lambda* = d lambda/dt cos beta), mas/yr. */
  pmEastMasYr: number
  /** Proper motion along local ecliptic north (mu_beta), mas/yr. */
  pmNorthMasYr: number
  /** Observer heliocentric ecliptic longitude at t = 0, rad. */
  observerPhaseRad: number
  /** Proper motion switched on (off -> zero space velocity). */
  properMotion: boolean
  /** Parallax switched on (off -> observer at the Sun). */
  parallax: boolean
}

export type Vec3 = readonly [number, number, number]

const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

export interface TangentBasis {
  /** Unit vector toward the source at t = 0 (from the Sun). */
  u0: Vec3
  /** Local east (direction of increasing ecliptic longitude) at u0. */
  east: Vec3
  /** Local north (direction of increasing ecliptic latitude) at u0. */
  north: Vec3
}

/** Orthonormal triad at ecliptic longitude 0, latitude beta (deg). */
export function tangentBasis(eclipticLatDeg: number): TangentBasis {
  const b = eclipticLatDeg * D2R
  const cb = Math.cos(b)
  const sb = Math.sin(b)
  // u0 = (cos b cos l, cos b sin l, sin b) at l = 0; east = (du0/dl) / cos b; north = du0/db.
  return { u0: [cb, 0, sb], east: [0, 1, 0], north: [-sb, 0, cb] }
}

export function validateNearby(p: NearbyParams): void {
  if (!Number.isFinite(p.distancePc) || p.distancePc <= 0) throw new RangeError(`distance must be finite and > 0 pc (got ${p.distancePc})`)
  if (!Number.isFinite(p.eclipticLatDeg) || Math.abs(p.eclipticLatDeg) > 90) throw new RangeError(`ecliptic latitude must be within [-90, 90] deg (got ${p.eclipticLatDeg})`)
  if (!Number.isFinite(p.pmEastMasYr) || !Number.isFinite(p.pmNorthMasYr)) throw new RangeError('proper-motion components must be finite (mas/yr)')
  if (!Number.isFinite(p.observerPhaseRad)) throw new RangeError(`observer phase must be finite (got ${p.observerPhaseRad})`)
}

/** Space velocity of the source, AU per Julian year (zero when proper motion is off). */
export function sourceVelocityAuPerYr(p: NearbyParams, basis: TangentBasis = tangentBasis(p.eclipticLatDeg)): Vec3 {
  if (!p.properMotion) return [0, 0, 0]
  const scale = p.distancePc / 1000 // (mas/yr -> arcsec/yr) * pc = AU/yr
  const ve = p.pmEastMasYr * scale
  const vn = p.pmNorthMasYr * scale
  return [ve * basis.east[0] + vn * basis.north[0], ve * basis.east[1] + vn * basis.north[1], ve * basis.east[2] + vn * basis.north[2]]
}

/** Heliocentric source position at t (Julian years), AU. */
export function sourcePositionAu(p: NearbyParams, tYr: number, basis: TangentBasis = tangentBasis(p.eclipticLatDeg)): Vec3 {
  const D = p.distancePc * AU_PER_PC
  const v = sourceVelocityAuPerYr(p, basis)
  return [D * basis.u0[0] + v[0] * tYr, D * basis.u0[1] + v[1] * tYr, D * basis.u0[2] + v[2] * tYr]
}

/** Heliocentric observer position at t (Julian years), AU: circular 1 AU ecliptic orbit, or the Sun when parallax is off. */
export function observerPositionAu(p: NearbyParams, tYr: number): Vec3 {
  if (!p.parallax) return [0, 0, 0]
  const lon = p.observerPhaseRad + 2 * Math.PI * tYr
  return [Math.cos(lon), Math.sin(lon), 0]
}

export interface SkyOffset {
  /** Gnomonic east offset from the t = 0 reference direction, mas (east = +ecliptic longitude). */
  east: number
  /** Gnomonic north offset, mas (north = +ecliptic latitude). */
  north: number
}

/** Apparent (east, north) offset in mas at t (Julian years from the model epoch). */
export function nearbyOffsetMas(p: NearbyParams, tYr: number): SkyOffset {
  validateNearby(p)
  if (!Number.isFinite(tYr)) throw new RangeError(`time must be finite (got ${tYr})`)
  const basis = tangentBasis(p.eclipticLatDeg)
  const P = sourcePositionAu(p, tYr, basis)
  const O = observerPositionAu(p, tYr)
  const s: Vec3 = [P[0] - O[0], P[1] - O[1], P[2] - O[2]] // apparent direction = source - observer
  const w = dot(s, basis.u0)
  if (!(w > 0)) throw new RangeError('source is 90 deg or more from the reference direction: gnomonic offsets undefined')
  return { east: (dot(s, basis.east) / w) * MAS_PER_RAD, north: (dot(s, basis.north) / w) * MAS_PER_RAD }
}

export interface SkyPath {
  /** Julian years from the model epoch. */
  t: number[]
  east: number[]
  north: number[]
}

/** n evenly spaced samples of the apparent path over [t0, t1] (Julian years). */
export function nearbyPath(p: NearbyParams, t0: number, t1: number, n: number): SkyPath {
  validateNearby(p)
  if (!Number.isFinite(t0) || !Number.isFinite(t1) || !(t1 >= t0)) throw new RangeError(`time span must be finite with t1 >= t0 (got ${t0}, ${t1})`)
  if (!Number.isInteger(n) || n < 2) throw new RangeError(`sample count must be an integer >= 2 (got ${n})`)
  const t: number[] = []
  const east: number[] = []
  const north: number[] = []
  for (let i = 0; i < n; i++) {
    const ti = t0 + ((t1 - t0) * i) / (n - 1)
    const o = nearbyOffsetMas(p, ti)
    t.push(ti)
    east.push(o.east)
    north.push(o.north)
  }
  return { t, east, north }
}

/** Each effect on its own (regardless of the toggles): proper motion only, parallax only. */
export function nearbyComponents(p: NearbyParams, t0: number, t1: number, n: number): { properMotionOnly: SkyPath; parallaxOnly: SkyPath } {
  return {
    properMotionOnly: nearbyPath({ ...p, properMotion: true, parallax: false }, t0, t1, n),
    parallaxOnly: nearbyPath({ ...p, properMotion: false, parallax: true }, t0, t1, n),
  }
}

/** Annual-parallax amplitude for a 1 AU observer orbit: 1000 / d mas (d in pc). */
export function parallaxAmplitudeMas(distancePc: number): number {
  if (!Number.isFinite(distancePc) || distancePc <= 0) throw new RangeError(`distance must be finite and > 0 pc (got ${distancePc})`)
  return 1000 / distancePc
}

/** Semi-minor axis of the parallax ellipse, parallax * |sin beta| mas (the semi-major axis, along east, is the parallax). */
export function parallaxSemiMinorMas(distancePc: number, eclipticLatDeg: number): number {
  return parallaxAmplitudeMas(distancePc) * Math.abs(Math.sin(eclipticLatDeg * D2R))
}

/** Transverse speed for a total proper motion (mas/yr) at d (pc): AU/yr and km/s (4.74047 km/s per arcsec/yr per pc). */
export function transverseSpeed(pmTotalMasYr: number, distancePc: number): { auPerYr: number; kmPerS: number } {
  const auPerYr = (pmTotalMasYr / 1000) * distancePc
  return { auPerYr, kmPerS: auPerYr * KM_S_PER_AU_YR }
}
