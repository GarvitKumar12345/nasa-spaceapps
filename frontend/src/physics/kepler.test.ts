import { describe, expect, it } from 'vitest'
import keplerFixture from '../../../fixtures/motion/kepler_cases.json'
import {
  GAUSS_K,
  apparentLongitudeSeries,
  equalTimeMarkers,
  lineOfSight,
  meanMotion,
  observerState,
  orbitState,
  period,
  solveKepler,
  sweptAreaRate,
  validateOrbit,
  visVivaSpeed,
  type OrbitElements,
} from './kepler'

const MU_SUN = GAUSS_K * GAUSS_K
const orbitOf = (el: { a: number; e: number; omegaRad: number; M0Rad: number; t0Days: number; mu: number }): OrbitElements => ({
  a: el.a,
  e: el.e,
  omegaRad: el.omegaRad,
  M0Rad: el.M0Rad,
  t0Days: el.t0Days,
  mu: el.mu,
})

describe('[math] Kepler orbit parity with an independent scipy two-body integration', () => {
  // The fixture integrates r'' = -mu r/|r|^3 with DOP853 (rtol 1e-12) from the perihelion
  // state; it never solves Kepler's equation. Tolerance (see the fixture's tolerance_rationale):
  // 10x the larger of (steps per orbit * rtol * orbits propagated) and the fixture's own
  // error estimate from a 10x tighter run. Positions scale with a, velocities with the
  // perihelion speed.
  const RTOL = 1e-12
  for (const c of keplerFixture.cases) {
    it(`${c.label}: states over ${c.max_periods_propagated.toFixed(1)} orbits agree within the integrator error budget`, () => {
      const el = c.elements
      const orbit = orbitOf(el)
      const orbits = Math.max(1, c.max_periods_propagated)
      const vPeri = Math.sqrt((el.mu * (1 + el.e)) / (el.a * (1 - el.e)))
      const tolPos = 10 * Math.max(c.steps_per_orbit * RTOL * orbits * el.a, c.integrator_error_estimate_au)
      const tolVel = 10 * Math.max(c.steps_per_orbit * RTOL * orbits * vPeri, c.integrator_velocity_error_estimate_au_per_day)
      // The budget must stay far below any convention error (>= 1e-3 a) to mean anything.
      expect(tolPos).toBeLessThan(1e-6 * el.a)
      expect(c.states.some((s) => Math.abs(s.periods_from_perihelion_start) > 1)).toBe(true)
      for (const s of c.states) {
        const st = orbitState(orbit, s.t)
        expect(Math.hypot(st.x - s.x, st.y - s.y)).toBeLessThan(tolPos)
        expect(Math.hypot(st.vx - s.vx, st.vy - s.vy)).toBeLessThan(tolVel)
      }
    })
  }

  it('the comparison is sensitive: a 1e-6 rad error in omega would exceed the budget', () => {
    const c = keplerFixture.cases[2]
    const shifted = { ...orbitOf(c.elements), omegaRad: c.elements.omegaRad + 1e-6 }
    const s = c.states[3]
    const st = orbitState(shifted, s.t)
    const tolPos = 10 * Math.max(c.steps_per_orbit * 1e-12 * Math.max(1, c.max_periods_propagated) * c.elements.a, c.integrator_error_estimate_au)
    expect(Math.hypot(st.x - s.x, st.y - s.y)).toBeGreaterThan(tolPos)
  })
})

describe("[math] Kepler's equation solver", () => {
  const eccentricities = [0, 1e-6, 0.05, 0.3, 0.5, 0.7, 0.8, 0.8000001, 0.9, 0.95, 0.99, 0.995, 0.999]

  it('residual |E - e sin E - M| < 1e-13 over a grid of M in [-4 pi, 4 pi] and e up to 0.999', () => {
    let worst = 0
    for (const e of eccentricities) {
      for (let i = 0; i <= 2400; i++) {
        const M = -4 * Math.PI + (8 * Math.PI * i) / 2400
        const E = solveKepler(M, e)
        worst = Math.max(worst, Math.abs(E - e * Math.sin(E) - M))
      }
    }
    expect(worst).toBeLessThan(1e-13)
  })

  it('handles the hard corners: tiny M at e -> 1, M near pi, exact multiples of pi', () => {
    for (const e of [0.9, 0.99, 0.999]) {
      for (const M of [1e-14, 1e-10, 1e-6, 1e-3, Math.PI - 1e-9, Math.PI, -Math.PI, 2 * Math.PI, -1e-12]) {
        const E = solveKepler(M, e)
        expect(Math.abs(E - e * Math.sin(E) - M)).toBeLessThan(1e-13)
      }
    }
  })

  it('E(M) is continuous and increasing across revolutions (E(M + 2 pi) = E(M) + 2 pi)', () => {
    for (const e of [0.2, 0.7, 0.97]) {
      let prev = -Infinity
      for (let i = 0; i <= 3000; i++) {
        const M = -3 * Math.PI + (9 * Math.PI * i) / 3000
        const E = solveKepler(M, e)
        expect(E).toBeGreaterThan(prev)
        prev = E
        expect(Math.abs(solveKepler(M + 2 * Math.PI, e) - (E + 2 * Math.PI))).toBeLessThan(1e-12)
      }
    }
  })

  it('true anomaly matches the direction of the position vector', () => {
    const orbit: OrbitElements = { a: 2, e: 0.83, omegaRad: 1.1, M0Rad: 0.4, t0Days: 0, mu: MU_SUN }
    for (let i = 0; i < 200; i++) {
      const st = orbitState(orbit, i * 13.7)
      const angle = Math.atan2(st.y, st.x) - orbit.omegaRad
      const d = Math.atan2(Math.sin(angle - st.nu), Math.cos(angle - st.nu))
      expect(Math.abs(d)).toBeLessThan(1e-12)
    }
  })
})

describe('[math] conservation laws and periods', () => {
  const orbits: OrbitElements[] = [
    { a: 1, e: 0, omegaRad: 0, M0Rad: 0, t0Days: 0, mu: MU_SUN },
    { a: 2.8, e: 0.35, omegaRad: 1.05, M0Rad: 2, t0Days: 40, mu: MU_SUN },
    { a: 0.6, e: 0.9, omegaRad: 4, M0Rad: 0.1, t0Days: -10, mu: 0.4 * MU_SUN },
    { a: 30, e: 0.999, omegaRad: 2.2, M0Rad: 3, t0Days: 0, mu: 3 * MU_SUN },
  ]

  it('vis-viva energy v^2/2 - mu/r = -mu/(2a) and angular momentum x vy - y vx = sqrt(mu a (1 - e^2)) are constant', () => {
    for (const o of orbits) {
      const P = period(o.a, o.mu)
      const energy = -o.mu / (2 * o.a)
      const h = Math.sqrt(o.mu * o.a * (1 - o.e * o.e))
      for (let i = 0; i <= 400; i++) {
        const st = orbitState(o, -P + (3 * P * i) / 400)
        const v2 = st.vx * st.vx + st.vy * st.vy
        expect(Math.abs((v2 / 2 - o.mu / st.r) / energy - 1)).toBeLessThan(1e-10)
        expect(Math.abs((st.x * st.vy - st.y * st.vx) / h - 1)).toBeLessThan(1e-10)
        expect(Math.abs(Math.hypot(st.x, st.y) / st.r - 1)).toBeLessThan(1e-12)
        expect(Math.abs(visVivaSpeed(st.r, o.a, o.mu) / Math.sqrt(v2) - 1)).toBeLessThan(1e-10)
      }
    }
  })

  it('period follows Kepler III: one Gaussian year (365.2568983 d) for a = 1 AU around 1 Msun, scaling as a^1.5 / sqrt(M)', () => {
    expect(period(1, MU_SUN)).toBeCloseTo(365.2568983, 6)
    expect(period(4, MU_SUN) / period(1, MU_SUN)).toBeCloseTo(8, 12)
    expect(period(1, 4 * MU_SUN) / period(1, MU_SUN)).toBeCloseTo(0.5, 12)
  })

  it('the dynamical period does not depend on e: successive perihelion passages are one period(a, mu) apart for every e', () => {
    // Perihelion = radial velocity r.v crossing zero from negative to positive, found by bisection on the state.
    const a = 3.3
    const mu = 1.7 * MU_SUN
    const P = period(a, mu)
    for (const e of [0.05, 0.3, 0.7, 0.95, 0.99]) {
      const o: OrbitElements = { a, e, omegaRad: 0.6, M0Rad: 2.5, t0Days: 123, mu }
      const radial = (t: number) => {
        const s = orbitState(o, t)
        return s.x * s.vx + s.y * s.vy
      }
      const crossings: number[] = []
      const steps = 4000
      for (let i = 0; i < steps; i++) {
        let lo = (2.5 * P * i) / steps
        let hi = (2.5 * P * (i + 1)) / steps
        if (radial(lo) < 0 && radial(hi) >= 0) {
          for (let k = 0; k < 80; k++) {
            const m = 0.5 * (lo + hi)
            if (radial(m) < 0) lo = m
            else hi = m
          }
          crossings.push(0.5 * (lo + hi))
        }
      }
      expect(crossings.length).toBeGreaterThanOrEqual(2)
      expect(Math.abs(crossings[1] - crossings[0] - P) / P).toBeLessThan(1e-9)
    }
  })

  it('the state is periodic: orbitState(t + P) = orbitState(t) for every e', () => {
    for (const o of orbits) {
      const P = period(o.a, o.mu)
      for (const t of [-500, 0, 17.3, 1e4]) {
        const s1 = orbitState(o, t)
        const s2 = orbitState(o, t + P)
        expect(Math.hypot(s2.x - s1.x, s2.y - s1.y)).toBeLessThan(1e-9 * o.a)
        expect(Math.hypot(s2.vx - s1.vx, s2.vy - s1.vy)).toBeLessThan(1e-9 * Math.hypot(s1.vx, s1.vy) + 1e-15)
      }
    }
  })

  it('e = 0 moves with uniform angular speed n at constant radius a', () => {
    const o: OrbitElements = { a: 1.7, e: 0, omegaRad: 0.3, M0Rad: 0.2, t0Days: 0, mu: MU_SUN }
    const n = meanMotion(o.a, o.mu)
    const dt = 11.1
    for (let i = 0; i < 100; i++) {
      const s1 = orbitState(o, i * dt)
      const s2 = orbitState(o, (i + 1) * dt)
      const dAngle = Math.atan2(s1.x * s2.y - s1.y * s2.x, s1.x * s2.x + s1.y * s2.y)
      expect(dAngle).toBeCloseTo(n * dt, 12)
      expect(s2.r).toBeCloseTo(o.a, 13)
    }
  })
})

describe("[math] equal areas in equal times (Kepler's second law)", () => {
  // Polygon (fan) area swept from the focus, computed from many sub-samples of the path.
  const sweptPolygonArea = (o: OrbitElements, tStart: number, dt: number, sub = 20000) => {
    let area = 0
    let prev = orbitState(o, tStart)
    for (let i = 1; i <= sub; i++) {
      const cur = orbitState(o, tStart + (dt * i) / sub)
      area += 0.5 * (prev.x * cur.y - prev.y * cur.x)
      prev = cur
    }
    return area
  }

  it('equal dt near perihelion and near aphelion sweep equal areas = (h/2) dt, though the arcs differ greatly', () => {
    const o: OrbitElements = { a: 3, e: 0.6, omegaRad: 0.7, M0Rad: 0, t0Days: 0, mu: MU_SUN } // perihelion at t = 0
    const P = period(o.a, o.mu)
    const dt = P / 12
    const peri = sweptPolygonArea(o, -dt / 2, dt)
    const aph = sweptPolygonArea(o, P / 2 - dt / 2, dt)
    expect(Math.abs(peri / aph - 1)).toBeLessThan(1e-6)
    expect(Math.abs(peri / (sweptAreaRate(o) * dt) - 1)).toBeLessThan(1e-6)
    const chord = (t1: number, t2: number) => {
      const s1 = orbitState(o, t1)
      const s2 = orbitState(o, t2)
      return Math.hypot(s2.x - s1.x, s2.y - s1.y)
    }
    expect(chord(-dt / 2, dt / 2) / chord(P / 2 - dt / 2, P / 2 + dt / 2)).toBeGreaterThan(2.5)
  })

  it('the 12 equal-time marker intervals each sweep pi a b / 12 (total = ellipse area)', () => {
    const o: OrbitElements = { a: 2.2, e: 0.8, omegaRad: 5, M0Rad: 1.3, t0Days: 77, mu: 0.8 * MU_SUN }
    const P = period(o.a, o.mu)
    const markers = equalTimeMarkers(o, 12)
    expect(markers).toHaveLength(12)
    const b = o.a * Math.sqrt(1 - o.e * o.e)
    let total = 0
    for (const m of markers) {
      const area = sweptPolygonArea(o, m.t, P / 12, 8000)
      expect(Math.abs(area / ((Math.PI * o.a * b) / 12) - 1)).toBeLessThan(1e-5)
      total += area
    }
    expect(Math.abs(total / (Math.PI * o.a * b) - 1)).toBeLessThan(1e-5)
  })
})

describe('[math] invalid orbits are rejected', () => {
  const good: OrbitElements = { a: 1, e: 0.2, omegaRad: 0, M0Rad: 0, t0Days: 0, mu: MU_SUN }
  const bad: Partial<OrbitElements>[] = [
    { a: 0 },
    { a: -2 },
    { a: Number.NaN },
    { a: Number.POSITIVE_INFINITY },
    { e: -0.01 },
    { e: 1 },
    { e: 1.4 },
    { e: Number.NaN },
    { mu: 0 },
    { mu: -1 },
    { mu: Number.NaN },
    { omegaRad: Number.NaN },
    { M0Rad: Number.POSITIVE_INFINITY },
    { t0Days: Number.NaN },
  ]
  for (const patch of bad) {
    it(`throws RangeError for ${JSON.stringify(patch, (_k, v) => (typeof v === 'number' && !Number.isFinite(v) ? String(v) : v))}`, () => {
      expect(() => validateOrbit({ ...good, ...patch })).toThrow(RangeError)
      expect(() => orbitState({ ...good, ...patch }, 0)).toThrow(RangeError)
    })
  }

  it('rejects non-finite times, unbound e in the solver, bad observers and marker counts', () => {
    expect(() => orbitState(good, Number.NaN)).toThrow(RangeError)
    expect(() => solveKepler(1, 1)).toThrow(RangeError)
    expect(() => solveKepler(Number.NaN, 0.1)).toThrow(RangeError)
    expect(() => period(0, MU_SUN)).toThrow(RangeError)
    expect(() => observerState({ radiusAu: 0, phaseRad: 0, mu: MU_SUN }, 0)).toThrow(RangeError)
    expect(() => observerState({ radiusAu: 1, phaseRad: 0, mu: -1 }, 0)).toThrow(RangeError)
    expect(() => equalTimeMarkers(good, 0)).toThrow(RangeError)
    expect(() => apparentLongitudeSeries(good, { radiusAu: 1, phaseRad: 0, mu: MU_SUN }, 5, 5, 10)).toThrow(RangeError)
  })
})

describe('[coords] line of sight = target - observer', () => {
  it('points from the observer to the target in the common frame', () => {
    const target = { x: 0.3, y: 2.1 }
    const observer = { x: 1, y: -0.2 }
    const los = lineOfSight(target, observer)
    expect(los.defined).toBe(true)
    if (!los.defined) return
    expect(observer.x + los.distance * Math.cos(los.longitudeRad)).toBeCloseTo(target.x, 14)
    expect(observer.y + los.distance * Math.sin(los.longitudeRad)).toBeCloseTo(target.y, 14)
    expect(los.longitudeRad).toBeGreaterThanOrEqual(0)
    expect(los.longitudeRad).toBeLessThan(2 * Math.PI)
    // Swapping roles reverses the direction.
    const back = lineOfSight(observer, target)
    expect(back.defined && Math.abs(Math.cos(back.longitudeRad - los.longitudeRad) + 1)).toBeLessThan(1e-14)
  })

  it('is reported as undefined (never NaN) when target and observer coincide', () => {
    for (const sep of [0, 1e-12, 5e-10]) {
      const los = lineOfSight({ x: 1 + sep, y: 0 }, { x: 1, y: 0 })
      expect(los.defined).toBe(false)
      if (!los.defined) expect(los.reason).toMatch(/undefined/)
      expect(JSON.stringify(los)).not.toMatch(/NaN|null/)
    }
    expect(lineOfSight({ x: Number.NaN, y: 0 }, { x: 0, y: 0 }).defined).toBe(false)
    expect(lineOfSight({ x: 1 + 2e-9, y: 0 }, { x: 1, y: 0 }).defined).toBe(true)
  })

  it('the series skips (and counts) undefined samples when the target shares the observer orbit and phase', () => {
    const o: OrbitElements = { a: 1, e: 0, omegaRad: 0, M0Rad: 0, t0Days: 0, mu: MU_SUN }
    const s = apparentLongitudeSeries(o, { radiusAu: 1, phaseRad: 0, mu: MU_SUN }, 0, 100, 50)
    expect(s.undefinedSamples).toBe(50)
    expect(s.t).toHaveLength(0)
    expect(s.retrograde).toHaveLength(0)
  })
})

describe('[math] apparent retrograde motion seen by a moving observer', () => {
  // Circular coplanar orbits: an outer target seen from an inner observer. Independent
  // closed form: d(longitude)/dt is proportional to r2^2 n2 + r1^2 n1 - r1 r2 (n1 + n2) cos(psi),
  // psi = heliocentric longitude difference, so retrograde motion is centred on opposition
  // (psi = 0), lasts 2 arccos[(r1^2 n1 + r2^2 n2) / (r1 r2 (n1 + n2))] / (n1 - n2), and
  // recurs every synodic period.
  const r1 = 1
  const r2 = 2.6
  const observer = { radiusAu: r1, phaseRad: 0.4, mu: MU_SUN }
  const target: OrbitElements = { a: r2, e: 0, omegaRad: 1.9, M0Rad: 0, t0Days: 0, mu: MU_SUN }
  const n1 = meanMotion(r1, MU_SUN)
  const n2 = meanMotion(r2, MU_SUN)
  const synodic = (2 * Math.PI) / (n1 - n2)
  const psiStation = Math.acos((r1 * r1 * n1 + r2 * r2 * n2) / (r1 * r2 * (n1 + n2)))
  const duration = (2 * psiStation) / (n1 - n2)

  it('retrograde intervals are centred on oppositions, last the closed-form duration and recur at the synodic period', () => {
    const series = apparentLongitudeSeries(target, observer, 0, 3 * synodic, 3000)
    const full = series.retrograde.filter((iv) => iv.start > 0 && iv.end < 3 * synodic)
    expect(full.length).toBeGreaterThanOrEqual(2)
    for (const iv of full) {
      const mid = 0.5 * (iv.start + iv.end)
      // Opposition: observer and target at the same heliocentric longitude.
      const psi = target.omegaRad + n2 * mid - (observer.phaseRad + n1 * mid)
      expect(Math.abs(Math.sin(psi))).toBeLessThan(1e-6)
      expect(Math.cos(psi)).toBeGreaterThan(0)
      expect(Math.abs(iv.end - iv.start - duration)).toBeLessThan(1e-6)
    }
    expect(Math.abs(full[1].start - full[0].start - synodic)).toBeLessThan(1e-6)
  })

  it('unwrapped longitude is continuous and its numerical derivative matches the reported rate sign', () => {
    const s = apparentLongitudeSeries(target, observer, 0, 2 * 365.25, 1500)
    for (let i = 1; i < s.t.length; i++) {
      const d = s.longitudeDeg[i] - s.longitudeDeg[i - 1]
      expect(Math.abs(d)).toBeLessThan(5)
      const meanRate = 0.5 * (s.rateDegPerDay[i] + s.rateDegPerDay[i - 1])
      if (Math.abs(meanRate) > 1e-3) expect(Math.sign(d)).toBe(Math.sign(meanRate))
    }
  })
})
