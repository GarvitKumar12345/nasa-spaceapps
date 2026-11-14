import { describe, expect, it } from 'vitest'
import tanFixture from '../../../fixtures/wcs/tan_cases.json'
import tangentFixture from '../../../fixtures/wcs/tangent_cases.json'
import { TanWcs } from './tanwcs'
import { offsetsMas, skyToTangent, tangentToSky, wrapRaDeg } from './tangent'

const sepMas = (ra1: number, dec1: number, ra2: number, dec2: number) => {
  const [e, n] = offsetsMas(ra1, dec1, ra2, dec2)
  return Math.hypot(e, n)
}

describe('[coords] browser TAN WCS parity with astropy', () => {
  for (const c of tanFixture.cases) {
    it(`${c.label}: pixel -> sky within 1e-4 mas and sky -> pixel within 1e-6 px`, () => {
      const w = new TanWcs({ header: c.wcs.header as Record<string, number | string> })
      for (const p of c.points) {
        const [ra, dec] = w.pixelToSky(p.x, p.y)
        expect(sepMas(ra, dec, p.ra, p.dec)).toBeLessThan(1e-4)
        const [x, y] = w.skyToPixel(p.ra, p.dec)
        expect(Math.hypot(x - p.x, y - p.y)).toBeLessThan(1e-6)
      }
    })
  }

  it('refuses distorted or non-TAN headers instead of approximating them', () => {
    const header = { ...(tanFixture.cases[0].wcs.header as Record<string, number | string>), CTYPE1: 'RA---TAN-SIP', CTYPE2: 'DEC--TAN-SIP' }
    expect(() => new TanWcs({ header })).toThrow(/pure TAN/)
  })
})

describe('[coords] gnomonic projection parity with Python', () => {
  for (const c of tangentFixture.cases) {
    it(`tangent point (${c.ra0}, ${c.dec0}): offsets within 1e-4 mas and round trip exact`, () => {
      for (const p of c.points) {
        const [e, n] = offsetsMas(p.ra, p.dec, c.ra0, c.dec0)
        expect(Math.abs(e - p.east_mas)).toBeLessThan(1e-4)
        expect(Math.abs(n - p.north_mas)).toBeLessThan(1e-4)
        const [xi, eta] = skyToTangent(p.ra, p.dec, c.ra0, c.dec0)
        const [ra, dec] = tangentToSky(xi, eta, c.ra0, c.dec0)
        expect(sepMas(ra, dec, p.ra, p.dec)).toBeLessThan(1e-6)
      }
    })
  }

  it('wraps RA into [0, 360)', () => {
    expect(wrapRaDeg(-0.5)).toBeCloseTo(359.5, 12)
    expect(wrapRaDeg(360)).toBe(0)
    expect(Object.is(wrapRaDeg(-0), -0)).toBe(false)
  })
})
