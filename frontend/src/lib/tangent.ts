/* Gnomonic tangent-plane projection (browser copy of backend/skyshift/coords/tangent.py).
 * Used only to place measured positions on plots/overlays; parity with the Python
 * implementation is checked in tangent.test.ts against fixtures/wcs/tangent_cases.json.
 * xi = east (+RA), eta = north (+Dec), radians. */

export const MAS_PER_RAD = (180 / Math.PI) * 3600 * 1000
const D2R = Math.PI / 180

export function wrapRaDeg(ra: number): number {
  const r = ((ra % 360) + 360) % 360
  return r >= 360 ? r - 360 : r + 0
}

export function skyToTangent(raDeg: number, decDeg: number, ra0Deg: number, dec0Deg: number): [number, number] {
  const a = (raDeg - ra0Deg) * D2R
  const d = decDeg * D2R
  const d0 = dec0Deg * D2R
  const cosC = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a)
  if (!(cosC > 1e-12)) throw new RangeError('Point is 90° or more from the tangent point')
  const xi = (Math.cos(d) * Math.sin(a)) / cosC
  const eta = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a)) / cosC
  return [xi, eta]
}

export function tangentToSky(xi: number, eta: number, ra0Deg: number, dec0Deg: number): [number, number] {
  const d0 = dec0Deg * D2R
  const denom = Math.cos(d0) - eta * Math.sin(d0)
  const dec = Math.atan2(Math.sin(d0) + eta * Math.cos(d0), Math.hypot(xi, denom))
  const ra = ra0Deg * D2R + Math.atan2(xi, denom)
  return [wrapRaDeg(ra / D2R), dec / D2R]
}

/** (east, north) offsets in mas of (ra, dec) about (ra0, dec0). */
export function offsetsMas(raDeg: number, decDeg: number, ra0Deg: number, dec0Deg: number): [number, number] {
  const [xi, eta] = skyToTangent(raDeg, decDeg, ra0Deg, dec0Deg)
  return [xi * MAS_PER_RAD, eta * MAS_PER_RAD]
}

export function applyOffsetsMas(eastMas: number, northMas: number, ra0Deg: number, dec0Deg: number): [number, number] {
  return tangentToSky(eastMas / MAS_PER_RAD, northMas / MAS_PER_RAD, ra0Deg, dec0Deg)
}
