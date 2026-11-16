/* Evidence notebook store.
 *
 * - buildEvidenceRecord turns the Observatory's analysis state into a contract
 *   EvidenceRecord (skyshift.evidence/1). Truth is kept in the separate
 *   `simulation` section, filtered to the record's own source.
 * - Records live in this browser only (localStorage `skyshift.notebook.v1`).
 *   Every storage access is guarded: unreadable data is never overwritten until
 *   the user resets the notebook (after downloading the raw text if wanted),
 *   and a full storage quota is reported instead of silently dropping a record.
 * - Imported records are accepted only after backend validation.
 */
import { create } from 'zustand'
import { api, describeError } from '../api/client'
import type {
  CatalogAssociation,
  Dataset,
  DetectedSource,
  Epoch,
  EvidenceRecord,
  EvidenceValidation,
  MeasurementSet,
  ModelFit,
  Observation,
  SimulationSection,
  SimulationTruth,
  TruthSource,
  ViewState,
} from '../api/types'

export const NOTEBOOK_STORAGE_KEY = 'skyshift.notebook.v1'
export const NOTEBOOK_STORAGE_SCHEMA = 'skyshift.notebook-storage/1'
export const EVIDENCE_SCHEMA_VERSION = 'skyshift.evidence/1'
export const CONTRACTS_VERSION = 'skyshift.contracts/1.1'
/** A truth source belongs to a record's detection when it lies within this radius of the measured reference position. */
export const TRUTH_MATCH_RADIUS_ARCSEC = 0.5
export const FRONTEND_SOFTWARE = { name: 'skyshift-frontend', version: '0.1.0' } as const
const BUILD_METHOD = 'skyshift.frontend.buildEvidenceRecord'
const BUILD_METHOD_VERSION = '1.0.0'
const MAX_IMPORT_RECORDS = 500

export interface EvidenceDraft {
  dataset: Dataset
  source: DetectedSource
  bandIds: string[]
  frameIds: string[]
  view: ViewState
  measurementSet: MeasurementSet
  excludedIds: string[]
  fit: ModelFit | null
  fitStale: boolean
  associations: CatalogAssociation[] | null
  truth: SimulationTruth | null
  title?: string
  notes?: string
}

/* ---------- Record construction ---------- */

/** frame id -> observation, for native and registered products alike. */
function observationsByFrame(dataset: Dataset): Map<string, Observation> {
  const map = new Map<string, Observation>()
  for (const obs of dataset.observations) for (const frameId of obs.frame_ids) map.set(frameId, obs)
  return map
}

/** Great-circle separation (haversine; stable for tiny angles) in arcsec. */
export function separationArcsec(ra1Deg: number, dec1Deg: number, ra2Deg: number, dec2Deg: number): number {
  const r = Math.PI / 180
  const sDec = Math.sin(((dec2Deg - dec1Deg) * r) / 2)
  const sRa = Math.sin(((ra2Deg - ra1Deg) * r) / 2)
  const h = sDec * sDec + Math.cos(dec1Deg * r) * Math.cos(dec2Deg * r) * sRa * sRa
  return 2 * Math.asin(Math.min(1, Math.sqrt(h))) * (180 / Math.PI) * 3600
}

/**
 * Simulation truth restricted to one detected source: the truth source nearest
 * to the source's measured reference position (within 0.5″), its per-frame true
 * positions, and the frame truth (true WCS, pointing errors) of the selected
 * frames. Moving truth sources are compared at the detection frame, where the
 * reference position was measured; stationary ones at their fixed position.
 * A FrameTruth belongs to a selected frame when it is that frame or the native
 * product of the same observation (truth WCS exists for native frames only).
 */
export function truthForSource(truth: SimulationTruth, source: DetectedSource, dataset: Dataset, frameIds: string[]): SimulationTruth {
  const obsByFrame = observationsByFrame(dataset)
  const detectionObs = obsByFrame.get(source.detected_in_frame_id)?.id ?? null
  const inDetectionFrame = (frameId: string) =>
    frameId === source.detected_in_frame_id || (detectionObs !== null && obsByFrame.get(frameId)?.id === detectionObs)
  let best: { source: TruthSource; sep: number } | null = null
  for (const t of truth.sources) {
    const atDetection = truth.positions.find((p) => p.truth_id === t.truth_id && inDetectionFrame(p.frame_id))
    const sep = separationArcsec(
      source.position.ra_deg,
      source.position.dec_deg,
      atDetection?.ra_deg ?? t.ra_deg,
      atDetection?.dec_deg ?? t.dec_deg,
    )
    if (sep <= TRUTH_MATCH_RADIUS_ARCSEC && (best === null || sep < best.sep)) best = { source: t, sep }
  }
  const selectedFrames = new Set(frameIds)
  const selectedObs = new Set(frameIds.map((f) => obsByFrame.get(f)?.id).filter((id): id is string => !!id))
  const keepFrame = (frameId: string) => {
    if (selectedFrames.has(frameId)) return true
    const obsId = obsByFrame.get(frameId)?.id
    return obsId !== undefined && selectedObs.has(obsId)
  }
  const matched = best?.source ?? null
  return {
    ...truth,
    sources: matched ? [matched] : [],
    positions: matched ? truth.positions.filter((p) => p.truth_id === matched.truth_id) : [],
    frames: truth.frames.filter((f) => keepFrame(f.frame_id)),
  }
}

export function defaultRecordTitle(source: DetectedSource, dataset: Dataset): string {
  return `${source.label} · ${dataset.id}`
}

export function buildEvidenceRecord(draft: EvidenceDraft, nowIso: string, id: string): EvidenceRecord {
  const { dataset, source, measurementSet, fit } = draft
  const obsByFrame = observationsByFrame(dataset)

  // One observation id and mid-exposure epoch per distinct observation of the selected frames (frame order).
  const observationIds: string[] = []
  const epochs: Epoch[] = []
  for (const frameId of draft.frameIds) {
    const obs = obsByFrame.get(frameId)
    if (!obs || observationIds.includes(obs.id)) continue
    observationIds.push(obs.id)
    epochs.push(obs.timing.mid)
  }

  const measurements = measurementSet.measurements
  const excluded = new Set(draft.excludedIds)
  const included = measurements.filter((m) => m.status === 'measured' && !excluded.has(m.id)).map((m) => m.id)
  const qualityFlags = [...new Set(measurements.flatMap((m) => m.quality.flags))].sort()
  const simulated = dataset.origin === 'simulated'

  let simulation: SimulationSection | null = null
  if (simulated && dataset.seed !== null && dataset.generator && dataset.generator_version) {
    simulation = {
      seed: dataset.seed,
      generator: dataset.generator,
      generator_version: dataset.generator_version,
      truth: draft.truth ? truthForSource(draft.truth, source, dataset, draft.frameIds) : null,
    }
  }

  // The reference position was measured in the detection frame: record that epoch when the source has none.
  const detectionEpoch = source.position.epoch ?? obsByFrame.get(source.detected_in_frame_id)?.timing.mid ?? null

  return {
    schema_version: EVIDENCE_SCHEMA_VERSION,
    contracts_version: CONTRACTS_VERSION,
    id,
    created_utc: nowIso,
    updated_utc: nowIso,
    title: draft.title?.trim() || defaultRecordTitle(source, dataset),
    record_label: simulated ? 'synthetic training record' : 'candidate for review',
    dataset: {
      dataset_id: dataset.id,
      provider: dataset.provider,
      origin: dataset.origin,
      release: dataset.release,
      generator: dataset.generator,
      generator_version: dataset.generator_version,
      seed: dataset.seed,
      scenario_parameters: null,
    },
    source: {
      source_id: source.id,
      label: source.label,
      origin: 'derived_measurement',
      reference_position: { ...source.position, epoch: detectionEpoch },
      catalog_associations: draft.associations ?? [],
    },
    selection: {
      band_ids: [...draft.bandIds],
      frame_ids: [...draft.frameIds],
      observation_ids: observationIds,
      epochs,
      view: draft.view,
    },
    measurements,
    included_measurement_ids: included,
    fit,
    fit_status: fit ? (draft.fitStale ? 'stale' : 'current') : 'none',
    assumptions: fit?.assumptions ?? [],
    quality_flags: qualityFlags,
    notes: draft.notes ?? '',
    simulation,
    provenance: {
      origin: 'derived_measurement',
      provider: 'skyshift',
      dataset_id: dataset.id,
      method: BUILD_METHOD,
      method_version: BUILD_METHOD_VERSION,
      parents: [...measurements.map((m) => m.id), ...(fit ? [fit.id] : [])],
      software: [{ ...FRONTEND_SOFTWARE }],
      notes: [],
      processing_version: null,
      release: null,
      retrieved_utc: null,
      source_url: null,
    },
  }
}

export function newRecordId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  // Fallback (non-secure contexts): RFC 4122 v4 layout from Math.random; ids only need to be unique locally.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = Math.floor(Math.random() * 16)
    return (ch === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

export function nowUtcIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
}

/* ---------- Storage ---------- */

export type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

/** The browser's localStorage, or null when it does not exist or access is denied. */
export function getBrowserStorage(): StorageLike | null {
  try {
    const storage = (globalThis as { localStorage?: Storage }).localStorage
    return storage ?? null
  } catch {
    return null
  }
}

function isObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x)
}

const RECORD_LABELS = new Set(['synthetic training record', 'candidate for review'])
const FIT_STATUSES = new Set(['current', 'stale', 'none'])

/** Structural check of a stored record: enough that the notebook UI can render it. */
function storedRecordProblem(r: unknown): string | null {
  if (!isObject(r)) return 'is not an object'
  if (r.schema_version !== EVIDENCE_SCHEMA_VERSION) return `has schema_version ${JSON.stringify(r.schema_version)}`
  if (typeof r.id !== 'string' || !r.id) return 'has no id'
  if (typeof r.title !== 'string') return 'has no title'
  if (!RECORD_LABELS.has(r.record_label as string)) return 'has an unknown record_label'
  if (!FIT_STATUSES.has(r.fit_status as string)) return 'has an unknown fit_status'
  if (!isObject(r.dataset) || typeof r.dataset.dataset_id !== 'string') return 'has no dataset reference'
  if (!isObject(r.source) || typeof r.source.source_id !== 'string') return 'has no source identity'
  if (!isObject(r.selection) || !Array.isArray(r.selection.frame_ids)) return 'has no selection'
  if (!Array.isArray(r.measurements) || !Array.isArray(r.included_measurement_ids)) return 'has no measurements'
  if (!isObject(r.provenance)) return 'has no provenance'
  return null
}

export interface StorageRead {
  records: EvidenceRecord[]
  /** Set when stored data exists but cannot be used. */
  error: string | null
  /** The stored text when it could be read (kept for "Download raw data"). */
  raw: string | null
  available: boolean
}

export function readNotebookStorage(storage: StorageLike | null): StorageRead {
  if (!storage) return { records: [], error: null, raw: null, available: false }
  let raw: string | null
  try {
    raw = storage.getItem(NOTEBOOK_STORAGE_KEY)
  } catch (e) {
    return { records: [], error: `Browser storage could not be read (${describeError(e)}).`, raw: null, available: false }
  }
  if (raw === null) return { records: [], error: null, raw: null, available: true }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { records: [], error: 'The stored notebook is not valid JSON.', raw, available: true }
  }
  if (!isObject(parsed) || parsed.schema !== NOTEBOOK_STORAGE_SCHEMA) {
    const found = isObject(parsed) ? JSON.stringify(parsed.schema ?? null) : 'a non-object value'
    return { records: [], error: `The stored notebook has an unknown format (expected ${NOTEBOOK_STORAGE_SCHEMA}, found ${found}).`, raw, available: true }
  }
  if (!Array.isArray(parsed.records)) {
    return { records: [], error: 'The stored notebook has no record list.', raw, available: true }
  }
  for (const [i, r] of parsed.records.entries()) {
    const problem = storedRecordProblem(r)
    if (problem) return { records: [], error: `Stored record ${i + 1} of ${parsed.records.length} ${problem}.`, raw, available: true }
  }
  return { records: parsed.records as EvidenceRecord[], error: null, raw, available: true }
}

export function isQuotaError(e: unknown): boolean {
  if (!isObject(e) && !(e instanceof Error)) return false
  const err = e as { name?: unknown; code?: unknown }
  return err.name === 'QuotaExceededError' || err.name === 'NS_ERROR_DOM_QUOTA_REACHED' || err.code === 22 || err.code === 1014
}

export type StorageWrite = { ok: true; bytes: number } | { ok: false; quota: boolean; message: string }

export function writeNotebookStorage(storage: StorageLike | null, records: EvidenceRecord[]): StorageWrite {
  if (!storage) {
    return {
      ok: false,
      quota: false,
      message: 'Browser storage is not available here, so records last only until this page is closed. Export them as JSON to keep them.',
    }
  }
  const payload = JSON.stringify({ schema: NOTEBOOK_STORAGE_SCHEMA, records })
  try {
    storage.setItem(NOTEBOOK_STORAGE_KEY, payload)
    return { ok: true, bytes: payload.length }
  } catch (e) {
    if (isQuotaError(e)) {
      const kb = Math.ceil(payload.length / 1024)
      return {
        ok: false,
        quota: true,
        message: `Browser storage is full: the notebook (${records.length} record${records.length === 1 ? '' : 's'}, about ${kb} KB) could not be saved. Export records you want to keep as JSON and delete some to free space.`,
      }
    }
    return { ok: false, quota: false, message: `The notebook could not be saved to browser storage (${describeError(e)}).` }
  }
}

/* ---------- Store ---------- */

export interface ImportResult {
  ok: boolean
  message: string
  imported: number
  rejected: number
  renamed: number
  warnings: string[]
}

interface NotebookState {
  records: EvidenceRecord[]
  selectedId: string | null
  loadError: string | null
  /** Raw stored text that could not be read; kept until reset so it can be downloaded. */
  rawStorage: string | null
  /** Last persistence problem (quota, unavailable storage, unreadable data), or null. */
  saveError: string | null
  /** Throws (after rolling back) when browser storage is full; otherwise keeps the record even if it cannot be persisted. */
  addRecord: (record: EvidenceRecord) => void
  updateRecord: (id: string, patch: Partial<Pick<EvidenceRecord, 'title' | 'notes'>>) => void
  removeRecord: (id: string) => void
  select: (id: string | null) => void
  importFromText: (text: string) => Promise<ImportResult>
  /** Discard unreadable stored data and save the records currently in memory. */
  resetStorage: () => void
  reloadFromStorage: () => void
  dismissSaveError: () => void
}

const UNREADABLE_NOTE =
  'Not saved: the stored notebook could not be read, so it is left untouched. Download its raw data if you need it, then reset the notebook to save again.'

function initialState(): Pick<NotebookState, 'records' | 'selectedId' | 'loadError' | 'rawStorage' | 'saveError'> {
  const read = readNotebookStorage(getBrowserStorage())
  return {
    records: read.records,
    selectedId: read.records[0]?.id ?? null,
    loadError: read.error,
    rawStorage: read.error ? read.raw : null,
    saveError: read.available || read.error ? null : 'Browser storage is not available here, so records last only until this page is closed.',
  }
}

function describeItem(item: unknown, index: number, total: number): string {
  const where = total > 1 ? `Record ${index + 1}` : 'The record'
  if (isObject(item) && typeof item.title === 'string' && item.title) return `${where} ("${item.title}")`
  return where
}

export const useNotebookStore = create<NotebookState>((set, get) => {
  /** Persist and report; returns the write result (null when skipped because stored data is unreadable). */
  const persist = (records: EvidenceRecord[]): StorageWrite | null => {
    if (get().loadError) {
      set({ saveError: UNREADABLE_NOTE })
      return null
    }
    const result = writeNotebookStorage(getBrowserStorage(), records)
    set({ saveError: result.ok ? null : result.message })
    return result
  }

  return {
    ...initialState(),

    addRecord: (record) => {
      const before = get().records
      const records = [record, ...before.filter((r) => r.id !== record.id)]
      const previousSelection = get().selectedId
      set({ records, selectedId: record.id })
      const result = persist(records)
      if (result && !result.ok && result.quota) {
        // Do not pretend a record was saved when the browser refused it.
        set({ records: before, selectedId: previousSelection })
        throw new Error(result.message)
      }
    },

    updateRecord: (id, patch) => {
      let changed = false
      const now = nowUtcIso()
      const records = get().records.map((r) => {
        if (r.id !== id) return r
        const next: EvidenceRecord = { ...r }
        if (patch.title !== undefined && patch.title !== r.title) {
          next.title = patch.title
          changed = true
        }
        if (patch.notes !== undefined && patch.notes !== r.notes) {
          next.notes = patch.notes
          changed = true
        }
        if (!changed) return r
        next.updated_utc = now
        return next
      })
      if (!changed) return
      set({ records })
      persist(records)
    },

    removeRecord: (id) => {
      const current = get().records
      const index = current.findIndex((r) => r.id === id)
      if (index < 0) return
      const records = current.filter((r) => r.id !== id)
      const selectedId = get().selectedId === id ? (records[index]?.id ?? records[index - 1]?.id ?? null) : get().selectedId
      set({ records, selectedId })
      persist(records)
    },

    select: (id) => set({ selectedId: id }),

    importFromText: async (text) => {
      const fail = (message: string): ImportResult => ({ ok: false, message, imported: 0, rejected: 0, renamed: 0, warnings: [] })
      let parsed: unknown
      try {
        parsed = JSON.parse(text)
      } catch (e) {
        return fail(`The file is not valid JSON (${describeError(e)}). Nothing was imported.`)
      }
      const items: unknown[] = Array.isArray(parsed)
        ? parsed
        : isObject(parsed) && Array.isArray(parsed.records)
          ? parsed.records
          : [parsed]
      if (items.length === 0) return fail('The file contains no records. Nothing was imported.')
      if (items.length > MAX_IMPORT_RECORDS) return fail(`The file contains ${items.length} records; at most ${MAX_IMPORT_RECORDS} can be imported at once.`)

      const accepted: EvidenceRecord[] = []
      const problems: string[] = []
      const warnings: string[] = []
      const renamedNotes: string[] = []
      const knownIds = new Set(get().records.map((r) => r.id))
      for (const [i, item] of items.entries()) {
        const label = describeItem(item, i, items.length)
        let validation: EvidenceValidation
        try {
          validation = await api.validateEvidence(item)
        } catch (e) {
          return fail(`The records could not be validated (${describeError(e)}). Nothing was imported; validation needs the SkyShift API.`)
        }
        if (!validation.valid || !validation.record) {
          const errs = validation.errors.length ? validation.errors : ['rejected by validation']
          problems.push(`${label} was rejected: ${errs.slice(0, 3).join('; ')}${errs.length > 3 ? ` (and ${errs.length - 3} more)` : ''}.`)
          continue
        }
        // The normalised record from the API, with the fit status recomputed from its own content.
        let record: EvidenceRecord = { ...validation.record, fit_status: validation.recomputed_fit_status }
        if (validation.warnings.length) warnings.push(`${label}: ${validation.warnings.join(' ')}`)
        if (knownIds.has(record.id)) {
          const newId = newRecordId()
          const now = nowUtcIso()
          const note = `Imported on ${now} as a separate copy: a record with id ${record.id} already exists in this notebook, so this copy was given the id ${newId}.`
          renamedNotes.push(`${label} has the same id as a record already in the notebook (${record.id.slice(0, 8)}…). Both are kept: the imported copy was given a new id and a note.`)
          record = { ...record, id: newId, notes: record.notes ? `${record.notes}\n\n${note}` : note, updated_utc: now }
        }
        knownIds.add(record.id)
        accepted.push(record)
      }

      if (accepted.length) {
        const before = get().records
        const previousSelection = get().selectedId
        const records = [...accepted, ...before]
        set({ records, selectedId: accepted[0].id })
        const result = persist(records)
        if (result && !result.ok && result.quota) {
          set({ records: before, selectedId: previousSelection })
          return { ok: false, message: `${result.message} Nothing was imported.`, imported: 0, rejected: problems.length, renamed: 0, warnings }
        }
      }

      const parts: string[] = []
      parts.push(
        accepted.length
          ? `Imported ${accepted.length} record${accepted.length === 1 ? '' : 's'} after validation.`
          : 'No record was imported.',
      )
      parts.push(...renamedNotes, ...problems)
      if (warnings.length) parts.push(`Validation warnings: ${warnings.join(' ')}`)
      const saveError = get().saveError
      if (accepted.length && saveError) parts.push(saveError)
      return {
        ok: accepted.length > 0,
        message: parts.join(' '),
        imported: accepted.length,
        rejected: problems.length,
        renamed: renamedNotes.length,
        warnings,
      }
    },

    resetStorage: () => {
      const storage = getBrowserStorage()
      try {
        storage?.removeItem(NOTEBOOK_STORAGE_KEY)
      } catch (e) {
        set({ saveError: `The stored notebook could not be removed (${describeError(e)}).` })
        return
      }
      set({ loadError: null, rawStorage: null, saveError: null })
      if (get().records.length) persist(get().records)
    },

    reloadFromStorage: () => {
      const s = initialState()
      const keep = get().selectedId
      set({ ...s, selectedId: keep && s.records.some((r) => r.id === keep) ? keep : s.selectedId })
    },

    dismissSaveError: () => set({ saveError: null }),
  }
})

// Keep several open tabs in step: another tab's save replaces this tab's list.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === NOTEBOOK_STORAGE_KEY || event.key === null) useNotebookStore.getState().reloadFromStorage()
  })
}
