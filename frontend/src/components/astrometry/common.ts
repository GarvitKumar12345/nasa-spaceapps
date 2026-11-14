/* Helpers shared by astrometry plots. Display geometry only: fitting happens in the backend. */
import type { ModelFit, SourceMeasurement } from '../../api/contracts.gen'
import { offsetsMas } from '../../lib/tangent'
import { mjdTdbToJyear } from '../../lib/format'

export interface TangentPoint {
  ra_deg: number
  dec_deg: number
  source: 'fit_reference' | 'mean_of_measurements'
}

export interface MeasuredOffset {
  id: string
  frameId: string
  bandId: string
  isoUtc: string | null
  mjdTdb: number
  jyear: number
  east: number
  north: number
  sigmaEast: number | null
  sigmaNorth: number | null
  excluded: boolean
  measurement: SourceMeasurement
}

export function usableMeasurements(ms: SourceMeasurement[]): SourceMeasurement[] {
  return ms.filter((m) => m.status === 'measured' && m.ra_deg != null && m.dec_deg != null)
}

/** Mean direction of the measured positions (unit-vector mean; safe across RA = 0). */
export function meanPosition(ms: SourceMeasurement[]): TangentPoint | null {
  const use = usableMeasurements(ms)
  if (!use.length) return null
  let x = 0
  let y = 0
  let z = 0
  for (const m of use) {
    const ra = (m.ra_deg! * Math.PI) / 180
    const dec = (m.dec_deg! * Math.PI) / 180
    x += Math.cos(dec) * Math.cos(ra)
    y += Math.cos(dec) * Math.sin(ra)
    z += Math.sin(dec)
  }
  const ra = ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
  const dec = (Math.atan2(z, Math.hypot(x, y)) * 180) / Math.PI
  return { ra_deg: ra, dec_deg: dec, source: 'mean_of_measurements' }
}

export function tangentPointFor(ms: SourceMeasurement[], fit?: ModelFit | null): TangentPoint | null {
  if (fit) {
    const p = fit.inputs.reference_position
    return { ra_deg: p.ra_deg, dec_deg: p.dec_deg, source: 'fit_reference' }
  }
  return meanPosition(ms)
}

export function measuredOffsets(ms: SourceMeasurement[], tp: TangentPoint, excluded: ReadonlySet<string> = new Set()): MeasuredOffset[] {
  return usableMeasurements(ms).map((m) => {
    const [east, north] = offsetsMas(m.ra_deg!, m.dec_deg!, tp.ra_deg, tp.dec_deg)
    return {
      id: m.id,
      frameId: m.frame_id,
      bandId: m.band_id,
      isoUtc: m.epoch.iso_utc,
      mjdTdb: m.epoch.mjd_tdb,
      jyear: mjdTdbToJyear(m.epoch.mjd_tdb),
      east,
      north,
      sigmaEast: m.sigma_ra_cosdec_mas,
      sigmaNorth: m.sigma_dec_mas,
      excluded: excluded.has(m.id),
      measurement: m,
    }
  })
}
