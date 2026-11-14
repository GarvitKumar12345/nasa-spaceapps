/* Evidence notebook helpers: file names, downloads, display labels, truth overlay points. */
import type { DataOrigin, EvidenceRecord, SourceMeasurement, TruthPosition, TruthSource } from '../../api/types'
import { fmtDate } from '../../lib/format'

const safePart = (s: string) => s.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'x'

/** skyshift-evidence-<dataset>-<source>-<id8>.<ext> */
export function recordFileName(record: EvidenceRecord, ext: 'json' | 'csv'): string {
  const id8 = record.id.replace(/[^A-Za-z0-9]/g, '').slice(0, 8) || 'record'
  return `skyshift-evidence-${safePart(record.dataset.dataset_id)}-${safePart(record.source.source_id)}-${id8}.${ext}`
}

/** Offer `text` as a file download. */
export function downloadText(fileName: string, text: string, mime: string): void {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.rel = 'noopener'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Exactly the stored record, pretty-printed. */
export function recordJson(record: EvidenceRecord): string {
  return `${JSON.stringify(record, null, 2)}\n`
}

/** "2025-03-19 G1" style label for a measurement. */
export function measurementLabel(m: SourceMeasurement): string {
  return `${fmtDate(m.epoch.iso_utc)} ${m.band_id}`
}

/** Replace a leading measurement id in a reproduction-check quantity with a short label. */
export function shortQuantity(quantity: string, measurements: SourceMeasurement[]): string {
  for (const m of measurements) {
    if (quantity.startsWith(`${m.id}:`)) return `${measurementLabel(m)}${quantity.slice(m.id.length)}`
  }
  return quantity
}

export function excludedMeasuredIds(record: EvidenceRecord): Set<string> {
  const included = new Set(record.included_measurement_ids)
  return new Set(record.measurements.filter((m) => m.status === 'measured' && !included.has(m.id)).map((m) => m.id))
}

export interface TruthOverlay {
  source: TruthSource | null
  points: TruthPosition[]
  /** How the points were obtained, for the caption. */
  basis: 'per_frame' | 'fixed_position' | 'none'
}

/**
 * Truth points for the plots. Moving and variable truth sources carry per-frame
 * true positions. A truth source with zero proper motion and zero parallax does
 * not move, so its true position at every measured epoch is its fixed position
 * (flux and pixel fields are not used by the plots and are left undefined as NaN).
 */
export function truthOverlay(record: EvidenceRecord): TruthOverlay {
  const truth = record.simulation?.truth ?? null
  const source = truth?.sources[0] ?? null
  if (!truth || !source) return { source: null, points: [], basis: 'none' }
  const own = truth.positions.filter((p) => p.truth_id === source.truth_id)
  if (own.length) return { source, points: own, basis: 'per_frame' }
  if (source.pmra_mas_yr === 0 && source.pmdec_mas_yr === 0 && source.parallax_mas === 0) {
    const points = record.measurements
      .filter((m) => m.status === 'measured')
      .map((m) => ({ truth_id: source.truth_id, frame_id: m.frame_id, ra_deg: source.ra_deg, dec_deg: source.dec_deg, flux: Number.NaN, x_px: Number.NaN, y_px: Number.NaN }))
    return { source, points, basis: 'fixed_position' }
  }
  return { source, points: [], basis: 'none' }
}

export const PROVIDER_LABEL: Record<EvidenceRecord['dataset']['provider'], string> = {
  synthetic: 'Synthetic generator (in-process)',
  spherex: 'SPHEREx (NASA/IPAC IRSA)',
  gaia_dr3: 'Gaia DR3 (ESA)',
  wise: 'WISE / unWISE',
  neossat: 'NEOSSat (CADC)',
}

export function datasetOrigin(record: EvidenceRecord): DataOrigin {
  return record.dataset.origin
}

/** Generic number display for reproduction checks (positions in degrees need ~10 decimals). */
export function fmtCheckValue(x: number | null): string {
  if (x === null || !Number.isFinite(x)) return '—'
  if (x === 0) return '0'
  const ax = Math.abs(x)
  if (ax >= 1e7 || ax < 1e-3) return x.toExponential(4)
  return Number(x.toPrecision(12)).toString()
}

export function fmtTiny(x: number | null): string {
  if (x === null || !Number.isFinite(x)) return '—'
  if (x === 0) return '0'
  return x.toExponential(2)
}

export function fmtPValue(p: number | null): string {
  if (p === null || !Number.isFinite(p)) return '—'
  if (p < 1e-3) return p.toExponential(2)
  return p.toFixed(3)
}
