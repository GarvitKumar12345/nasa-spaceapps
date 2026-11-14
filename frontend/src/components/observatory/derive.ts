/* Derived, display-only geometry for the Observatory (positions on the common grid). */
import { useEffect, useMemo, useState } from 'react'
import type { CatalogOverlay, Dataset, DetectedSource, ModelFit, Observation, SimulationTruth, SourceMeasurement } from '../../api/types'
import { angularSepArcsec } from '../../lib/sky'
import { applyOffsetsMas } from '../../lib/tangent'
import { TanWcs } from '../../lib/tanwcs'
import { availableObservations, nativeFrameId, registeredFrameId } from '../../state/observatory'
import type { CanvasPoint } from './SkyCanvas'
import { loadPlane, percentiles, type StretchLimits } from './pixels'

export function useGridWcs(dataset: Dataset | null): TanWcs | null {
  return useMemo(() => (dataset ? new TanWcs(dataset.common_grid) : null), [dataset])
}

/** Measured (linked) source positions at a given native frame. Sources not detected in that
 * frame are omitted: drawing them at their reference-epoch position would misplace moving sources. */
export function sourcePointsAt(sources: DetectedSource[] | null, nativeId: string | null, wcs: TanWcs | null): CanvasPoint[] {
  if (!sources || !wcs || !nativeId) return []
  const out: CanvasPoint[] = []
  for (const s of sources) {
    const tp = s.track.find((t) => t.frame_id === nativeId)
    if (tp?.status !== 'measured' || tp.ra_deg == null || tp.dec_deg == null) continue
    const [x, y] = wcs.skyToPixel(tp.ra_deg, tp.dec_deg)
    out.push({ id: s.id, x, y })
  }
  return out
}

/** Display stretch limits for a band, from its first available frame (same limits for every epoch: no blink flicker). */
export function useBandLimits(datasetId: string | null, dataset: Dataset | null, bandId: string | null, pLow: number, pHigh: number): StretchLimits | null {
  const refFrame = useMemo(() => registeredFrameId(availableObservations(dataset, bandId)[0]), [dataset, bandId])
  const [limits, setLimits] = useState<StretchLimits | null>(null)
  useEffect(() => {
    if (!datasetId || !refFrame) return
    let alive = true
    loadPlane(datasetId, refFrame)
      .then((p) => {
        const [lo, hi] = percentiles(p.data, [pLow, pHigh])
        if (alive) setLimits({ lo, hi })
      })
      .catch(() => alive && setLimits(null))
    return () => {
      alive = false
    }
  }, [datasetId, refFrame, pLow, pHigh])
  return limits
}

export function measurementAt(ms: SourceMeasurement[] | null, obs: Observation | null): SourceMeasurement | null {
  if (!ms || !obs) return null
  return ms.find((m) => m.observation_id === obs.id) ?? null
}

/** Fit prediction path and the predicted position at a given epoch, in grid pixels. */
export function modelGeometry(fit: ModelFit | null, wcs: TanWcs | null, mjdTdb: number | null): { path: [number, number][]; now: [number, number] | null } | null {
  const pred = fit?.prediction
  if (!pred || !wcs) return null
  const ref = fit.inputs.reference_position
  const path = pred.t_mjd_tdb.map((_, i) => {
    const [ra, dec] = applyOffsetsMas(pred.ra_cosdec_offset_mas[i], pred.dec_offset_mas[i], ref.ra_deg, ref.dec_deg)
    return wcs.skyToPixel(ra, dec)
  })
  let now: [number, number] | null = null
  if (mjdTdb != null) {
    const t = pred.t_mjd_tdb
    const k = t.findIndex((v) => v >= mjdTdb)
    if (k > 0) {
      const f = (mjdTdb - t[k - 1]) / (t[k] - t[k - 1])
      const e = pred.ra_cosdec_offset_mas[k - 1] + f * (pred.ra_cosdec_offset_mas[k] - pred.ra_cosdec_offset_mas[k - 1])
      const n = pred.dec_offset_mas[k - 1] + f * (pred.dec_offset_mas[k] - pred.dec_offset_mas[k - 1])
      const [ra, dec] = applyOffsetsMas(e, n, ref.ra_deg, ref.dec_deg)
      now = wcs.skyToPixel(ra, dec)
    }
  }
  return { path, now }
}

/** Simulation-truth source matching a detected source (validation display only). */
export function truthFor(truth: SimulationTruth | null, source: DetectedSource | null) {
  if (!truth || !source) return null
  let best: SimulationTruth['sources'][number] | null = null
  let bestSep = 0.5
  for (const t of truth.sources) {
    const sep = angularSepArcsec(t.ra_deg, t.dec_deg, source.position.ra_deg, source.position.dec_deg)
    if (sep < bestSep) {
      bestSep = sep
      best = t
    }
  }
  if (!best) return null
  return { source: best, positions: truth.positions.filter((p) => p.truth_id === best!.truth_id) }
}

export function truthPointAt(t: ReturnType<typeof truthFor>, obs: Observation | null, wcs: TanWcs | null): [number, number] | null {
  if (!t || !wcs) return null
  const fid = nativeFrameId(obs)
  const p = t.positions.find((q) => q.frame_id === fid)
  const [ra, dec] = p ? [p.ra_deg, p.dec_deg] : [t.source.ra_deg, t.source.dec_deg]
  return wcs.skyToPixel(ra, dec)
}

export function catalogPoints(overlay: CatalogOverlay | null, wcs: TanWcs | null) {
  if (!overlay || !wcs) return null
  return overlay.propagated.map((p) => {
    const [x, y] = wcs.skyToPixel(p.ra_deg, p.dec_deg)
    return { id: p.catalog_source_id, x, y }
  })
}
