/* Small spherical helpers for display logic. */
const D2R = Math.PI / 180

/** Great-circle separation in arcsec (Vincenty). */
export function angularSepArcsec(ra1: number, dec1: number, ra2: number, dec2: number): number {
  const l1 = ra1 * D2R
  const b1 = dec1 * D2R
  const l2 = ra2 * D2R
  const b2 = dec2 * D2R
  const dl = l2 - l1
  const num = Math.hypot(Math.cos(b2) * Math.sin(dl), Math.cos(b1) * Math.sin(b2) - Math.sin(b1) * Math.cos(b2) * Math.cos(dl))
  const den = Math.sin(b1) * Math.sin(b2) + Math.cos(b1) * Math.cos(b2) * Math.cos(dl)
  return (Math.atan2(num, den) / D2R) * 3600
}
