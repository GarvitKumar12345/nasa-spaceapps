/* Observatory store: dataset, band, epoch, selected source, view (pan/zoom), display,
 * playback, and Analyze state. Explore and Analyze read the same fields, so switching
 * modes never resets the investigation. */
import { create } from 'zustand'
import { api, describeError, type PlaneData } from '../api/client'
import type {
  AstrometricModel,
  CatalogAssociation,
  CatalogOverlay,
  Dataset,
  DatasetSummary,
  DetectedSource,
  DifferenceInfo,
  EvidenceRecord,
  MeasurementSet,
  ModelFit,
  Observation,
  ProviderStatus,
  SimulationTruth,
} from '../api/types'

export type Mode = 'explore' | 'analyze'
export type Stretch = 'asinh' | 'linear' | 'log'
export type CompareView = 'side-by-side' | 'difference'

export type Load<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string }

const idle = { status: 'idle' } as const
const loading = { status: 'loading' } as const

/** Viewer transform in common-grid pixels: (cx, cy) at the viewer centre, zoom = screen px per grid px. */
export interface ViewTransform {
  cx: number
  cy: number
  zoom: number | null // null = fit to viewer
}

export interface DisplaySettings {
  stretch: Stretch
  pLow: number
  pHigh: number
  grid: boolean
  labels: boolean
  model: boolean
  truth: boolean
  catalog: boolean
  compareView: CompareView
}

export interface Playback {
  playing: boolean
  blink: boolean
  intervalMs: number
}

export interface ObservatoryState {
  providers: Load<ProviderStatus[]>
  datasets: Load<DatasetSummary[]>
  datasetId: string | null
  dataset: Load<Dataset>
  sources: Load<DetectedSource[]>
  bandId: string | null
  epochObsId: string | null
  compareObsId: string | null
  selectedSourceId: string | null
  hoverSourceId: string | null
  mode: Mode
  view: ViewTransform
  display: DisplaySettings
  playback: Playback
  measurements: Load<MeasurementSet>
  excludedIds: string[]
  fitModel: AstrometricModel
  fit: Load<ModelFit>
  fitKey: string | null
  associations: Load<CatalogAssociation[]>
  truth: Load<SimulationTruth>
  catalogOverlay: Load<CatalogOverlay>
  difference: Load<{ info: DifferenceInfo; plane: PlaneData | null }>
  search: { message: string | null; tone: 'info' | 'warning' | 'error' | null }
  restoredFrom: string | null

  init: () => Promise<void>
  selectDataset: (id: string) => Promise<void>
  setBand: (bandId: string) => void
  setEpoch: (obsId: string) => void
  step: (delta: number) => void
  setCompare: (obsId: string | null) => void
  selectSource: (id: string | null) => void
  setHover: (id: string | null) => void
  setMode: (mode: Mode) => void
  setView: (view: Partial<ViewTransform>) => void
  setDisplay: (display: Partial<DisplaySettings>) => void
  setPlayback: (playback: Partial<Playback>) => void
  toggleExcluded: (measurementId: string) => void
  setFitModel: (model: AstrometricModel) => void
  runFit: () => Promise<void>
  loadAssociations: () => Promise<void>
  loadTruth: () => Promise<void>
  loadCatalogOverlay: () => Promise<void>
  loadDifference: () => Promise<void>
  runSearch: (text: string) => Promise<void>
  restoreFromRecord: (record: EvidenceRecord) => Promise<void>
}

// ---------------------------------------------------------------- helpers

export function bandObservations(dataset: Dataset | null, bandId: string | null): Observation[] {
  if (!dataset || !bandId) return []
  return dataset.observations.filter((o) => o.band_id === bandId).sort((a, b) => a.timing.mid.mjd_tdb - b.timing.mid.mjd_tdb)
}

export function availableObservations(dataset: Dataset | null, bandId: string | null): Observation[] {
  return bandObservations(dataset, bandId).filter((o) => o.status === 'available')
}

export function registeredFrameId(obs: Observation | undefined | null): string | null {
  return obs?.frame_ids.find((id) => id.endsWith(':registered')) ?? null
}

export function nativeFrameId(obs: Observation | undefined | null): string | null {
  return obs?.frame_ids.find((id) => id.endsWith(':native')) ?? null
}

export function observationForFrame(dataset: Dataset | null, frameId: string | null): Observation | null {
  if (!dataset || !frameId) return null
  return dataset.observations.find((o) => o.frame_ids.includes(frameId) || o.id === frameId) ?? null
}

/** Key of the inputs a fit depends on; a different key marks a stored fit as stale. */
export function fitInputsKey(sourceId: string | null, model: AstrometricModel, excluded: string[], ms: MeasurementSet | null): string {
  const ids = ms ? ms.measurements.filter((m) => m.status === 'measured').map((m) => m.id) : []
  return JSON.stringify([sourceId, model, [...excluded].sort(), ids])
}

export function isFitStale(s: Pick<ObservatoryState, 'fit' | 'fitKey' | 'selectedSourceId' | 'fitModel' | 'excludedIds' | 'measurements'>): boolean {
  if (s.fit.status !== 'ready') return false
  const ms = s.measurements.status === 'ready' ? s.measurements.data : null
  return s.fitKey !== fitInputsKey(s.selectedSourceId, s.fitModel, s.excludedIds, ms)
}

const DEFAULT_DISPLAY: DisplaySettings = {
  stretch: 'asinh',
  pLow: 20, // ~median - 0.8 sigma: sky renders dark grey with visible noise
  pHigh: 99.7,
  grid: true,
  labels: true,
  model: true,
  truth: false,
  catalog: false,
  compareView: 'side-by-side',
}

const resetSourceState = {
  measurements: idle,
  excludedIds: [] as string[],
  fit: idle,
  fitKey: null,
  associations: idle,
} as const

// ---------------------------------------------------------------- store

export const useObservatoryStore = create<ObservatoryState>((set, get) => {
  const loadMeasurements = async (sourceId: string) => {
    const datasetId = get().datasetId
    if (!datasetId) return
    set({ measurements: loading })
    try {
      const data = await api.measurements(datasetId, sourceId)
      if (get().selectedSourceId === sourceId) set({ measurements: { status: 'ready', data } })
    } catch (e) {
      if (get().selectedSourceId === sourceId) set({ measurements: { status: 'error', message: describeError(e) } })
    }
  }

  return {
    providers: idle,
    datasets: idle,
    datasetId: null,
    dataset: idle,
    sources: idle,
    bandId: null,
    epochObsId: null,
    compareObsId: null,
    selectedSourceId: null,
    hoverSourceId: null,
    mode: 'explore',
    view: { cx: 0, cy: 0, zoom: null },
    display: DEFAULT_DISPLAY,
    playback: { playing: false, blink: false, intervalMs: 900 },
    measurements: idle,
    excludedIds: [],
    fitModel: 'proper_motion_parallax',
    fit: idle,
    fitKey: null,
    associations: idle,
    truth: idle,
    catalogOverlay: idle,
    difference: idle,
    search: { message: null, tone: null },
    restoredFrom: null,

    init: async () => {
      if (get().datasets.status === 'loading' || get().datasets.status === 'ready') return
      set({ datasets: loading, providers: loading })
      try {
        const [datasets, providers] = await Promise.all([api.datasets(), api.providers()])
        set({ datasets: { status: 'ready', data: datasets }, providers: { status: 'ready', data: providers } })
        if (!get().datasetId && datasets.length) await get().selectDataset(datasets[0].id)
      } catch (e) {
        const message = describeError(e)
        set({ datasets: { status: 'error', message }, providers: { status: 'error', message } })
      }
    },

    selectDataset: async (id) => {
      if (get().datasetId === id && get().dataset.status === 'ready') return
      set({ datasetId: id, dataset: loading, sources: loading, selectedSourceId: null, epochObsId: null, compareObsId: null, truth: idle, catalogOverlay: idle, difference: idle, ...resetSourceState })
      try {
        const [dataset, sources] = await Promise.all([api.dataset(id), api.sources(id)])
        if (get().datasetId !== id) return
        const bandId = dataset.bands[0]?.id ?? null
        const avail = availableObservations(dataset, bandId)
        const [ny, nx] = dataset.common_grid.shape
        set({
          dataset: { status: 'ready', data: dataset },
          sources: { status: 'ready', data: sources },
          bandId,
          epochObsId: avail[0]?.id ?? null,
          compareObsId: avail[avail.length - 1]?.id ?? null,
          view: { cx: (nx - 1) / 2, cy: (ny - 1) / 2, zoom: null },
        })
      } catch (e) {
        const message = describeError(e)
        set({ dataset: { status: 'error', message }, sources: { status: 'error', message } })
      }
    },

    setBand: (bandId) => {
      const ds = get().dataset.status === 'ready' ? (get().dataset as { data: Dataset }).data : null
      if (!ds || bandId === get().bandId) return
      // Keep the epoch closest in time to the current one; never invent a frame for a gap.
      const current = ds.observations.find((o) => o.id === get().epochObsId)
      const avail = availableObservations(ds, bandId)
      const t = current?.timing.mid.mjd_tdb ?? avail[0]?.timing.mid.mjd_tdb ?? 0
      const nearest = avail.reduce<Observation | null>((best, o) => (!best || Math.abs(o.timing.mid.mjd_tdb - t) < Math.abs(best.timing.mid.mjd_tdb - t) ? o : best), null)
      const cmp = ds.observations.find((o) => o.id === get().compareObsId)
      const ct = cmp?.timing.mid.mjd_tdb ?? avail[avail.length - 1]?.timing.mid.mjd_tdb ?? 0
      const nearestCmp = avail.reduce<Observation | null>((best, o) => (!best || Math.abs(o.timing.mid.mjd_tdb - ct) < Math.abs(best.timing.mid.mjd_tdb - ct) ? o : best), null)
      set({ bandId, epochObsId: nearest?.id ?? null, compareObsId: nearestCmp?.id ?? null, difference: idle, catalogOverlay: idle })
    },

    setEpoch: (obsId) => set({ epochObsId: obsId, catalogOverlay: idle }),

    step: (delta) => {
      const ds = get().dataset.status === 'ready' ? (get().dataset as { data: Dataset }).data : null
      const avail = availableObservations(ds, get().bandId)
      if (!avail.length) return
      const i = Math.max(0, avail.findIndex((o) => o.id === get().epochObsId))
      const next = avail[(i + delta + avail.length) % avail.length]
      set({ epochObsId: next.id, catalogOverlay: idle })
    },

    setCompare: (obsId) => set({ compareObsId: obsId, difference: idle }),

    selectSource: (id) => {
      if (id === get().selectedSourceId) return
      set({ selectedSourceId: id, restoredFrom: null, ...resetSourceState })
      if (id) void loadMeasurements(id)
    },

    setHover: (id) => set({ hoverSourceId: id }),
    setMode: (mode) => set({ mode }),
    setView: (view) => set({ view: { ...get().view, ...view } }),
    setDisplay: (display) => set({ display: { ...get().display, ...display } }),
    setPlayback: (playback) => set({ playback: { ...get().playback, ...playback } }),

    toggleExcluded: (measurementId) => {
      const ex = new Set(get().excludedIds)
      if (ex.has(measurementId)) ex.delete(measurementId)
      else ex.add(measurementId)
      set({ excludedIds: [...ex] })
    },

    setFitModel: (model) => set({ fitModel: model }),

    runFit: async () => {
      const s = get()
      if (!s.datasetId || !s.selectedSourceId || s.measurements.status !== 'ready') return
      const ms = s.measurements.data
      const key = fitInputsKey(s.selectedSourceId, s.fitModel, s.excludedIds, ms)
      set({ fit: loading })
      try {
        const data = await api.fitAstrometric({
          dataset_id: s.datasetId,
          source_id: s.selectedSourceId,
          model: s.fitModel,
          measurements: ms.measurements,
          excluded_measurement_ids: s.excludedIds,
          reference_epoch_mjd_tdb: null,
        })
        if (get().selectedSourceId === s.selectedSourceId) set({ fit: { status: 'ready', data }, fitKey: key })
      } catch (e) {
        set({ fit: { status: 'error', message: describeError(e) }, fitKey: null })
      }
    },

    loadAssociations: async () => {
      const { datasetId, selectedSourceId } = get()
      if (!datasetId || !selectedSourceId) return
      set({ associations: loading })
      try {
        const data = await api.associations(datasetId, selectedSourceId)
        if (get().selectedSourceId === selectedSourceId) set({ associations: { status: 'ready', data } })
      } catch (e) {
        set({ associations: { status: 'error', message: describeError(e) } })
      }
    },

    loadTruth: async () => {
      const { datasetId, truth } = get()
      if (!datasetId || truth.status === 'ready' || truth.status === 'loading') return
      set({ truth: loading })
      try {
        set({ truth: { status: 'ready', data: await api.truth(datasetId) } })
      } catch (e) {
        set({ truth: { status: 'error', message: describeError(e) } })
      }
    },

    loadCatalogOverlay: async () => {
      const s = get()
      const ds = s.dataset.status === 'ready' ? s.dataset.data : null
      const obs = ds?.observations.find((o) => o.id === s.epochObsId)
      const fid = registeredFrameId(obs)
      if (!s.datasetId || !fid) return
      set({ catalogOverlay: loading })
      try {
        const data = await api.catalogOverlay(s.datasetId, fid)
        if (get().epochObsId === s.epochObsId) set({ catalogOverlay: { status: 'ready', data } })
      } catch (e) {
        set({ catalogOverlay: { status: 'error', message: describeError(e) } })
      }
    },

    loadDifference: async () => {
      const s = get()
      const ds = s.dataset.status === 'ready' ? s.dataset.data : null
      const a = registeredFrameId(ds?.observations.find((o) => o.id === s.epochObsId))
      const b = registeredFrameId(ds?.observations.find((o) => o.id === s.compareObsId))
      if (!s.datasetId || !a || !b) return
      set({ difference: loading })
      try {
        const info = await api.differenceInfo(s.datasetId, a, b)
        const plane = info.compatible ? await api.differencePixels(s.datasetId, a, b) : null
        if (get().epochObsId === s.epochObsId && get().compareObsId === s.compareObsId) set({ difference: { status: 'ready', data: { info, plane } } })
      } catch (e) {
        set({ difference: { status: 'error', message: describeError(e) } })
      }
    },

    runSearch: async (text) => {
      const q = text.trim()
      if (!q) return
      try {
        const res = await api.resolve(q, get().datasetId ?? undefined)
        if (res.kind === 'source_id' && res.source_id) {
          get().selectSource(res.source_id)
          set({ search: { message: res.message, tone: 'info' } })
        } else if (res.kind === 'coordinates' && res.position) {
          if (res.in_dataset_field) {
            const ds = get().dataset.status === 'ready' ? (get().dataset as { data: Dataset }).data : null
            if (ds) {
              const { TanWcs } = await import('../lib/tanwcs')
              const [x, y] = new TanWcs(ds.common_grid).skyToPixel(res.position.ra_deg, res.position.dec_deg)
              set({ view: { ...get().view, cx: x, cy: y } })
            }
          }
          set({ search: { message: res.message, tone: res.in_dataset_field ? 'info' : 'warning' } })
        } else {
          set({ search: { message: res.message, tone: 'warning' } })
        }
      } catch (e) {
        set({ search: { message: describeError(e), tone: 'error' } })
      }
    },

    restoreFromRecord: async (record) => {
      await get().selectDataset(record.dataset.dataset_id)
      const s = get()
      if (s.dataset.status !== 'ready') return
      const ds = s.dataset.data
      const v = record.selection.view
      const bandId = v.band_id && ds.bands.some((b) => b.id === v.band_id) ? v.band_id : (ds.bands[0]?.id ?? null)
      const epoch = observationForFrame(ds, v.frame_id)
      const cmp = observationForFrame(ds, v.compare_frame_id ?? null)
      const ms: MeasurementSet = {
        dataset_id: record.dataset.dataset_id,
        source_id: record.source.source_id,
        band_ids: record.selection.band_ids,
        method: record.measurements[0]?.method ?? 'psf_gaussian_fit',
        method_version: record.measurements[0]?.method_version ?? '',
        measurements: record.measurements,
        association_method: 'restored from evidence record',
        notes: ['Measurements restored from the saved evidence record.'],
      }
      const included = new Set(record.included_measurement_ids)
      const excludedIds = record.measurements.filter((m) => m.status === 'measured' && !included.has(m.id)).map((m) => m.id)
      const fitModel = record.fit?.model ?? get().fitModel
      const [ny, nx] = ds.common_grid.shape
      set({
        bandId,
        epochObsId: epoch?.id ?? get().epochObsId,
        compareObsId: cmp?.id ?? get().compareObsId,
        selectedSourceId: record.source.source_id,
        mode: v.mode,
        view: { cx: v.center_x_px ?? (nx - 1) / 2, cy: v.center_y_px ?? (ny - 1) / 2, zoom: v.zoom ?? null },
        measurements: { status: 'ready', data: ms },
        excludedIds,
        fitModel,
        fit: record.fit ? { status: 'ready', data: record.fit } : idle,
        // A record saved with a stale fit stays stale after restoring.
        fitKey: record.fit && record.fit_status === 'current' ? fitInputsKey(record.source.source_id, fitModel, excludedIds, ms) : null,
        associations: idle,
        restoredFrom: record.id,
      })
    },
  }
})
