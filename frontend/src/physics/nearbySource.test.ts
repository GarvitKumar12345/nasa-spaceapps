import { describe, expect, it } from 'vitest'
import nearbyFixture from '../../../fixtures/motion/nearby_source_cases.json'
import { MAS_PER_RAD } from '../lib/tangent'
import {
  KM_S_PER_AU_YR,
  nearbyComponents,
  nearbyOffsetMas,
  nearbyPath,
  observerPositionAu,
  parallaxAmplitudeMas,
  parallaxSemiMinorMas,
  tangentBasis,
  transverseSpeed,
  type NearbyParams,
} from './nearbySource'

const base: NearbyParams = {
  distancePc: 10,
  eclipticLatDeg: 30,
  pmEastMasYr: 120,
  pmNorthMasYr: -80,
  observerPhaseRad: 0.4,
  properMotion: true,
  parallax: true,
}
const parallaxOnly = (p: Partial<NearbyParams>): NearbyParams => ({ ...base, ...p, properMotion: false, parallax: true })
const span = (lo: number, hi: number, n: number) => Array.from({ length: n }, (_, i) => lo + ((hi - lo) * i) / (n - 1))

describe('[math] nearby source: limits and geometry', () => {
  it('zero-motion limit: with proper motion and parallax both off the source stays at the reference direction', () => {
    for (const beta of [-90, -20, 0, 45, 90]) {
      for (const t of span(-3, 8, 23)) {
        const o = nearbyOffsetMas({ ...base, eclipticLatDeg: beta, properMotion: false, parallax: false }, t)
        expect(Math.hypot(o.east, o.north)).toBeLessThan(1e-12)
      }
    }
  })

  it('an ecliptic-pole source traces a circle of radius = parallax, once per Julian year, displaced away from the observer', () => {
    for (const beta of [90, -90]) {
      for (const d of [1.3, 10, 200]) {
        const p = parallaxOnly({ eclipticLatDeg: beta, distancePc: d })
        const plx = 1000 / d
        const basis = tangentBasis(beta)
        let prevAngle: number | null = null
        for (const t of span(0, 1, 97)) {
          const o = nearbyOffsetMas(p, t)
          expect(Math.abs(Math.hypot(o.east, o.north) / plx - 1)).toBeLessThan(1e-6)
          // Parallactic displacement is opposite to the observer's offset from the Sun, projected on the sky.
          const O = observerPositionAu(p, t)
          const oe = O[0] * basis.east[0] + O[1] * basis.east[1] + O[2] * basis.east[2]
          const on = O[0] * basis.north[0] + O[1] * basis.north[1] + O[2] * basis.north[2]
          expect((o.east * oe + o.north * on) / (Math.hypot(o.east, o.north) * Math.hypot(oe, on))).toBeCloseTo(-1, 9)
          const angle = Math.atan2(o.north, o.east)
          if (prevAngle !== null) {
            const dA = Math.atan2(Math.sin(angle - prevAngle), Math.cos(angle - prevAngle))
            expect(Math.abs(Math.abs(dA) - (2 * Math.PI) / 96)).toBeLessThan(1e-9)
          }
          prevAngle = angle
        }
      }
    }
  })

  it('an ecliptic-plane source moves only east-west under parallax (no north excursion)', () => {
    const p = parallaxOnly({ eclipticLatDeg: 0, distancePc: 3 })
    let maxEast = 0
    for (const t of span(0, 1, 4001)) {
      const o = nearbyOffsetMas(p, t)
      expect(Math.abs(o.north)).toBeLessThan(1e-9)
      maxEast = Math.max(maxEast, Math.abs(o.east))
    }
    expect(Math.abs(maxEast / (1000 / 3) - 1)).toBeLessThan(1e-6)
  })

  it('parallax amplitude scales as 1/d (semi-major axis x d = 1000 mas pc)', () => {
    for (const d of [1.5, 4, 25, 100, 1000]) {
      const p = parallaxOnly({ eclipticLatDeg: 40, distancePc: d })
      const path = nearbyPath(p, 0, 1, 20001)
      const semiMajor = Math.max(...path.east.map(Math.abs))
      expect(Math.abs((semiMajor * d) / 1000 - 1)).toBeLessThan(1e-6)
      expect(parallaxAmplitudeMas(d) * d).toBeCloseTo(1000, 9)
    }
  })

  it('the parallax ellipse has semi-minor axis = parallax * |sin beta| along north', () => {
    for (const beta of [-45, 12, 30, 60]) {
      const p = parallaxOnly({ eclipticLatDeg: beta, distancePc: 8 })
      const path = nearbyPath(p, 0, 1, 20001)
      const semiMinor = (Math.max(...path.north) - Math.min(...path.north)) / 2
      expect(Math.abs(semiMinor / parallaxSemiMinorMas(8, beta) - 1)).toBeLessThan(1e-6)
      expect(parallaxSemiMinorMas(8, beta)).toBeCloseTo(125 * Math.abs(Math.sin((beta * Math.PI) / 180)), 10)
    }
  })

  it('proper motion alone is a straight line through the origin with slope mu (east = mu_E t, north = mu_N t)', () => {
    for (const [pmE, pmN, d, beta] of [
      [120, -80, 10, 30],
      [-3000, 1500, 1.3, 0],
      [0, 700, 4, 89.9],
      [250, 0, 500, -60],
    ]) {
      const p: NearbyParams = { ...base, pmEastMasYr: pmE, pmNorthMasYr: pmN, distancePc: d, eclipticLatDeg: beta, parallax: false }
      for (const t of span(-5, 10, 31)) {
        const o = nearbyOffsetMas(p, t)
        expect(Math.abs(o.east - pmE * t)).toBeLessThan(1e-7)
        expect(Math.abs(o.north - pmN * t)).toBeLessThan(1e-7)
      }
    }
  })

  it('the parallax-only path repeats after one Julian year', () => {
    const p = parallaxOnly({ eclipticLatDeg: -25, distancePc: 2 })
    for (const t of span(-1, 2, 37)) {
      const a = nearbyOffsetMas(p, t)
      const b = nearbyOffsetMas(p, t + 1)
      expect(Math.hypot(a.east - b.east, a.north - b.north)).toBeLessThan(1e-9)
    }
  })

  it('total motion = proper motion + parallax up to the second-order perspective term |pm offset| * parallax(rad)', () => {
    const p: NearbyParams = { ...base, distancePc: 1.5, pmEastMasYr: 4000, pmNorthMasYr: -2500 }
    const t = span(0, 6, 61)
    const total = nearbyPath(p, 0, 6, 61)
    const { properMotionOnly, parallaxOnly: plx } = nearbyComponents(p, 0, 6, 61)
    const plxRad = 1000 / p.distancePc / MAS_PER_RAD
    for (let i = 0; i < t.length; i++) {
      const de = total.east[i] - properMotionOnly.east[i] - plx.east[i]
      const dn = total.north[i] - properMotionOnly.north[i] - plx.north[i]
      const bound = 1.01 * Math.hypot(properMotionOnly.east[i], properMotionOnly.north[i]) * plxRad + 1e-9
      expect(Math.hypot(de, dn)).toBeLessThanOrEqual(bound)
    }
  })

  it('transverse speed: 1 arcsec/yr at 1 pc is 1 AU/yr = 4.74047 km/s', () => {
    const v = transverseSpeed(1000, 1)
    expect(v.auPerYr).toBeCloseTo(1, 14)
    expect(KM_S_PER_AU_YR).toBeCloseTo(4.740470464, 8)
  })

  it('rejects invalid declared geometry', () => {
    for (const patch of [{ distancePc: 0 }, { distancePc: -2 }, { distancePc: Number.NaN }, { eclipticLatDeg: 90.5 }, { pmEastMasYr: Number.POSITIVE_INFINITY }, { observerPhaseRad: Number.NaN }]) {
      expect(() => nearbyOffsetMas({ ...base, ...patch }, 0)).toThrow(RangeError)
    }
    expect(() => nearbyOffsetMas(base, Number.NaN)).toThrow(RangeError)
    expect(() => nearbyPath(base, 2, 1, 10)).toThrow(RangeError)
    expect(() => parallaxAmplitudeMas(0)).toThrow(RangeError)
  })
})

describe('[contracts] nearby source parity with the independent numpy model', () => {
  for (const c of nearbyFixture.cases) {
    const pr = c.params
    it(`d = ${pr.distancePc} pc, beta = ${pr.eclipticLatDeg} deg, pm = (${pr.pmEastMasYr}, ${pr.pmNorthMasYr}) mas/yr: all four toggle combinations within 1e-6 mas`, () => {
      for (const v of c.variants) {
        const p: NearbyParams = { ...pr, properMotion: v.properMotion, parallax: v.parallax }
        c.t_yr.forEach((t, i) => {
          const o = nearbyOffsetMas(p, t)
          expect(Math.abs(o.east - v.east_mas[i])).toBeLessThan(1e-6)
          expect(Math.abs(o.north - v.north_mas[i])).toBeLessThan(1e-6)
        })
      }
    })
  }
})
