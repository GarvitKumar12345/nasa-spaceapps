/* Gaia DR3 predictions and alignment diagnostics for observed (SPHEREx) datasets.
 * Kept apart from the main observatory store: catalogue predictions (model) and reference-star
 * measurements (derived) never mix with the synthetic investigation state. Source IDs are strings. */
import { create } from 'zustand'
import { ApiError, api, describeError } from '../api/client'
import type { AlignmentReport, GaiaFrameOverlay, GaiaPrediction, GaiaSourceDetail } from '../api/types'
import type { Load } from './observatory'

export interface GaiaDisplay {
  overlay: boolean
  /** Faintest G magnitude drawn (predictions fainter than this are hidden, not discarded). */
  maxG: number
  /** Show ePSF-measured positions of reference candidates (derived measurements). */
  measured: boolean
  /** Draw measured-minus-predicted residuals magnified 100x. */
  vectors: boolean
}

export const RESIDUAL_MAGNIFICATION = 100

interface GaiaState {
  datasetId: string | null
  overlays: Record<string, Load<GaiaFrameOverlay>>
  selectedSourceId: string | null
  detailKey: string | null
  detail: Load<GaiaSourceDetail>
  alignment: Load<AlignmentReport>
  show: GaiaDisplay
  reset: (datasetId: string | null) => void
  loadOverlay: (datasetId: string, frameId: string) => Promise<void>
  select: (sourceId: string | null) => void
  loadDetail: (datasetId: string, frameId: string) => Promise<void>
  loadAlignment: (datasetId: string) => Promise<void>
  setShow: (s: Partial<GaiaDisplay>) => void
}

const idle = { status: 'idle' } as const
// Dataset/source keys can recur while their previous requests are still pending.
// Generations distinguish a new visit from an obsolete response for the same key.
let datasetGeneration = 0
let detailGeneration = 0

/** A refused analysis (409 not_available: the dataset declares it unavailable) vs a failed request; neither carries data. */
export function failed(e: unknown): { status: 'unavailable' | 'error'; message: string } {
  const refused = e instanceof ApiError && e.status === 409 && e.code === 'not_available'
  return { status: refused ? 'unavailable' : 'error', message: describeError(e) }
}

export const useGaiaStore = create<GaiaState>((set, get) => ({
  datasetId: null,
  overlays: {},
  selectedSourceId: null,
  detailKey: null,
  detail: idle,
  alignment: idle,
  show: { overlay: true, maxG: 18.5, measured: false, vectors: false },
  reset: (datasetId) => {
    if (get().datasetId === datasetId) return
    datasetGeneration++
    detailGeneration++
    set({ datasetId, overlays: {}, selectedSourceId: null, detailKey: null, detail: idle, alignment: idle })
  },
  loadOverlay: async (datasetId, frameId) => {
    if (get().datasetId !== datasetId) return
    const generation = datasetGeneration
    const cur = get().overlays[frameId]
    if (cur && cur.status !== 'error') return
    set((s) => ({ overlays: { ...s.overlays, [frameId]: { status: 'loading' } } }))
    try {
      const data = await api.gaiaOverlay(datasetId, frameId)
      if (datasetGeneration !== generation || get().datasetId !== datasetId) return
      set((s) => ({ overlays: { ...s.overlays, [frameId]: { status: 'ready', data } } }))
    } catch (e) {
      if (datasetGeneration !== generation || get().datasetId !== datasetId) return
      set((s) => ({ overlays: { ...s.overlays, [frameId]: failed(e) } }))
    }
  },
  select: (sourceId) => {
    if (get().selectedSourceId === sourceId) return
    detailGeneration++
    set({ selectedSourceId: sourceId, detail: idle, detailKey: null })
  },
  loadDetail: async (datasetId, frameId) => {
    if (get().datasetId !== datasetId) return
    const sid = get().selectedSourceId
    if (!sid) return
    const key = `${datasetId}|${frameId}|${sid}`
    if (get().detailKey === key && get().detail.status !== 'error') return
    const generation = ++detailGeneration
    set({ detailKey: key, detail: { status: 'loading' } })
    try {
      const data = await api.gaiaSource(datasetId, sid, frameId)
      if (detailGeneration === generation && get().detailKey === key) set({ detail: { status: 'ready', data } })
    } catch (e) {
      if (detailGeneration === generation && get().detailKey === key) set({ detail: failed(e) })
    }
  },
  loadAlignment: async (datasetId) => {
    if (get().datasetId !== datasetId) return
    const generation = datasetGeneration
    const cur = get().alignment
    if (cur.status === 'ready' || cur.status === 'loading') return
    set({ alignment: { status: 'loading' } })
    try {
      const data = await api.alignment(datasetId)
      if (datasetGeneration === generation && get().datasetId === datasetId) set({ alignment: { status: 'ready', data } })
    } catch (e) {
      if (datasetGeneration === generation && get().datasetId === datasetId) set({ alignment: failed(e) })
    }
  },
  setShow: (s) => set((st) => ({ show: { ...st.show, ...s } })),
}))

export type PredictionKind = 'used' | 'rejected' | 'saturated' | 'no_motion' | 'other'

/** Marker class of a prediction: reference role first, then catalogue limitations. */
export function predictionKind(p: GaiaPrediction): PredictionKind {
  if (p.flags.includes('SATURATED_IN_FRAME')) return 'saturated'
  if (p.reference_status === 'used') return 'used'
  if (p.solution === '2-parameter') return 'no_motion'
  if (p.reference_status === 'rejected') return 'rejected'
  return 'other'
}

/** Predictions to draw on the display grid: inside the frame, brighter than maxG (2-parameter sources included). */
export function visiblePredictions(overlay: GaiaFrameOverlay | null, maxG: number): GaiaPrediction[] {
  if (!overlay) return []
  return overlay.predictions.filter((p) => p.in_native && p.x_display != null && p.y_display != null && (p.g_mag ?? 99) <= maxG)
}

/** Measured position on the display grid, from the predicted display position plus the sky residual (arcsec). */
export function measuredDisplayPoint(p: GaiaPrediction, residual: { east: number; north: number }, gridScaleArcsec: number, magnify = 1): [number, number] | null {
  if (p.x_display == null || p.y_display == null) return null
  // display grid is north up, east left: +east -> -x, +north -> +y (grid y increases with Dec)
  return [p.x_display - (residual.east * magnify) / gridScaleArcsec, p.y_display + (residual.north * magnify) / gridScaleArcsec]
}
