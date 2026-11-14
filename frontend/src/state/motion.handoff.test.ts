import { describe, expect, it } from 'vitest'
import { eclipticNorthPositionAngleDeg } from '../components/observatory/actions'
import { DEFAULT_NEARBY, equatorialToEclipticPm, nearbyFromHandoff } from './motion'

// Reference values from astropy (GeocentricMeanEcliptic, equinox J2000): position angle of the
// ecliptic-north direction at each ICRS position, computed with SkyCoord.position_angle.
const ASTROPY_PA = [
  { ra: 180, dec: 35, pa: 27.8894 },
  { ra: 0, dec: 0, pa: -23.4393 },
  { ra: 45, dec: -30, pa: -23.2718 },
]

describe('[coords] Observatory -> Motion lab hand-off frame rotation', () => {
  it('ecliptic-north position angle agrees with astropy to 0.02 deg', () => {
    for (const c of ASTROPY_PA) expect(Math.abs(eclipticNorthPositionAngleDeg(c.ra, c.dec) - c.pa)).toBeLessThan(0.02)
  })

  it('rotating equatorial proper motion into ecliptic components preserves its magnitude', () => {
    const { east, north } = equatorialToEclipticPm(640, -1110, 27.8894)
    expect(Math.hypot(east, north)).toBeCloseTo(Math.hypot(640, -1110), 9)
    // A motion purely along ecliptic north appears at PA = 27.9 deg in equatorial axes.
    const t = (27.8894 * Math.PI) / 180
    const r = equatorialToEclipticPm(100 * Math.sin(t), 100 * Math.cos(t), 27.8894)
    expect(r.east).toBeCloseTo(0, 9)
    expect(r.north).toBeCloseTo(100, 9)
  })

  it('copies rotated motion and inverts only a significant positive parallax', () => {
    const base = { pmra: 640, pmdec: -1110, eclipticLatDeg: 31.7, eclipticNorthPaDeg: 27.8894, label: 'S003', fitId: 'fit:x' }
    const good = nearbyFromHandoff({ ...base, parallax: 165, parallaxSigma: 2.7 }, DEFAULT_NEARBY)
    expect(good.result.distance.copied && good.settings.distancePc).toBeCloseTo(1000 / 165, 9)
    expect(Math.hypot(good.settings.pmEastMasYr, good.settings.pmNorthMasYr)).toBeCloseTo(Math.hypot(640, 1110), 9)
    const weak = nearbyFromHandoff({ ...base, parallax: 12, parallaxSigma: 7 }, DEFAULT_NEARBY)
    expect(weak.result.distance.copied).toBe(false)
    expect(weak.settings.distancePc).toBe(DEFAULT_NEARBY.distancePc)
    const negative = nearbyFromHandoff({ ...base, parallax: -3, parallaxSigma: 0.2 }, DEFAULT_NEARBY)
    expect(negative.result.distance.copied).toBe(false)
  })
})
