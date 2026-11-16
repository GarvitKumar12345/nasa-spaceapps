import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import contractSchema from '../api/contracts.schema.json'
import type {
  CatalogAssociation,
  Dataset,
  DetectedSource,
  Epoch,
  EvidenceRecord,
  FrameTruth,
  ModelFit,
  Observation,
  Provenance,
  SimulationTruth,
  SourceMeasurement,
  TruthPosition,
  TruthSource,
  ViewState,
} from '../api/types'

const mocks = vi.hoisted(() => ({ validateEvidence: vi.fn() }))
vi.mock('../api/client', () => ({
  api: { validateEvidence: mocks.validateEvidence },
  describeError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}))

import {
  NOTEBOOK_STORAGE_KEY,
  NOTEBOOK_STORAGE_SCHEMA,
  buildEvidenceRecord,
  readNotebookStorage,
  useNotebookStore,
  type EvidenceDraft,
} from './notebook'

/* ---------- Minimal JSON-Schema checker for the generated contract schema ---------- */
type Schema = { [k: string]: unknown }
const DEFS = (contractSchema as unknown as { $defs: Record<string, Schema> }).$defs

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x)
}
function typeMatches(v: unknown, t: string): boolean {
  switch (t) {
    case 'null':
      return v === null
    case 'string':
      return typeof v === 'string'
    case 'number':
      return typeof v === 'number' && Number.isFinite(v)
    case 'integer':
      return typeof v === 'number' && Number.isInteger(v)
    case 'boolean':
      return typeof v === 'boolean'
    case 'array':
      return Array.isArray(v)
    case 'object':
      return isPlainObject(v)
    default:
      return false
  }
}
function schemaErrors(value: unknown, s: Schema, path = '$', out: string[] = []): string[] {
  if (typeof s.$ref === 'string') return schemaErrors(value, DEFS[s.$ref.replace('#/$defs/', '')], path, out)
  if (Array.isArray(s.anyOf)) {
    if (!s.anyOf.some((sub) => schemaErrors(value, sub as Schema, path).length === 0)) out.push(`${path}: matches no allowed form`)
    return out
  }
  if ('const' in s && value !== s.const) out.push(`${path}: expected ${JSON.stringify(s.const)}`)
  if (Array.isArray(s.enum) && !s.enum.includes(value)) out.push(`${path}: ${JSON.stringify(value)} not in enum`)
  if (typeof s.type === 'string' && !typeMatches(value, s.type)) {
    out.push(`${path}: expected ${s.type}`)
    return out
  }
  if (typeof value === 'number') {
    if (typeof s.minimum === 'number' && value < s.minimum) out.push(`${path}: below minimum`)
    if (typeof s.maximum === 'number' && value > s.maximum) out.push(`${path}: above maximum`)
    if (typeof s.exclusiveMaximum === 'number' && value >= s.exclusiveMaximum) out.push(`${path}: not below exclusiveMaximum`)
  }
  if (Array.isArray(value)) {
    if (typeof s.minItems === 'number' && value.length < s.minItems) out.push(`${path}: too few items`)
    if (typeof s.maxItems === 'number' && value.length > s.maxItems) out.push(`${path}: too many items`)
    if (Array.isArray(s.items)) value.forEach((v, i) => s.items && schemaErrors(v, (s.items as Schema[])[i] ?? {}, `${path}[${i}]`, out))
    else if (isPlainObject(s.items)) value.forEach((v, i) => schemaErrors(v, s.items as Schema, `${path}[${i}]`, out))
  }
  if (isPlainObject(value) && (s.type === 'object' || s.properties)) {
    const props = (s.properties ?? {}) as Record<string, Schema>
    for (const req of (s.required ?? []) as string[]) if (!(req in value)) out.push(`${path}.${req}: required`)
    for (const [k, v] of Object.entries(value)) {
      if (k in props) schemaErrors(v, props[k], `${path}.${k}`, out)
      else if (s.additionalProperties === false) out.push(`${path}.${k}: unknown field`)
      else if (isPlainObject(s.additionalProperties)) schemaErrors(v, s.additionalProperties, `${path}.${k}`, out)
    }
  }
  return out
}

/* ---------- Fixtures (shaped like the SYN-NB-01 contracts) ---------- */
const DS = 'syn-test'
const OK = { status: 'ok' as const, flags: [], messages: [] }
const prov = (origin: Provenance['origin']): Provenance => ({
  dataset_id: DS,
  method: null,
  method_version: null,
  notes: [],
  origin,
  parents: [],
  processing_version: null,
  provider: 'synthetic',
  release: 'synthetic-v1',
  retrieved_utc: null,
  software: [],
  source_url: null,
})
const epoch = (iso: string, mjdTdb: number): Epoch => ({ format: 'isot', scale: 'utc', value: iso, iso_utc: iso, mjd_tdb: mjdTdb })

const VISITS: Record<string, { start: string; mid: string; mjd: number }> = {
  v01: { start: '2025-01-08T03:10:00Z', mid: '2025-01-08T03:11:30Z', mjd: 60683.1336 },
  v02: { start: '2025-03-19T22:40:00Z', mid: '2025-03-19T22:41:30Z', mjd: 60753.9461 },
  v03: { start: '2025-05-27T20:05:00Z', mid: '2025-05-27T20:06:30Z', mjd: 60822.8384 },
}
const obsId = (visit: string, band: string) => `${DS}:${visit}:${band}`
const nativeId = (visit: string, band: string) => `${obsId(visit, band)}:native`
const registeredId = (visit: string, band: string) => `${obsId(visit, band)}:registered`
// G2 exposures start 240 s after G1 in the same visit.
const shiftIso = (iso: string, seconds: number) => new Date(Date.parse(iso) + seconds * 1000).toISOString().replace('.000Z', 'Z')
const midEpoch = (visit: string, band: string) =>
  epoch(band === 'G2' ? shiftIso(VISITS[visit].mid, 240) : VISITS[visit].mid, VISITS[visit].mjd + (band === 'G2' ? 240 / 86400 : 0))

function observation(visit: string, band: string, available = true): Observation {
  return {
    id: obsId(visit, band),
    dataset_id: DS,
    band_id: band,
    detector: null,
    archive: null,
    frame_ids: available ? [nativeId(visit, band), registeredId(visit, band)] : [],
    instrument: 'GTI-1',
    observer: { kind: 'geocenter', ephemeris: 'astropy builtin (ERFA epv00)', approximation_note: null, max_position_error_km: null },
    pointing: null,
    provenance: prov('simulated'),
    provider: 'synthetic',
    quality: OK,
    status: available ? 'available' : 'missing',
    status_reason: available ? null : 'scheduled; no frame delivered (simulated)',
    timing: { exposure_s: 180, start: epoch(VISITS[visit].start, VISITS[visit].mjd), mid: midEpoch(visit, band), mid_derivation: 'start + exposure/2', raw: {} },
  }
}

// Only the Dataset fields read by buildEvidenceRecord are needed.
const dataset = {
  id: DS,
  title: 'Test field (synthetic)',
  provider: 'synthetic',
  origin: 'simulated',
  release: 'synthetic-v1',
  generator: 'skyshift.synthetic.generator',
  generator_version: '1.0.0',
  seed: 20261114,
  observations: [observation('v01', 'G1'), observation('v02', 'G1'), observation('v03', 'G1', false), observation('v01', 'G2'), observation('v02', 'G2')],
} as unknown as Dataset

const SRC_RA = 180.0016
const SRC_DEC = 34.9989
const source: DetectedSource = {
  id: 'S001',
  label: 'S001',
  dataset_id: DS,
  band_id: 'G1',
  detected_in_frame_id: nativeId('v01', 'G1'),
  change_indicators: [],
  flux: 9000,
  flux_err: 95,
  flux_unit: 'electron',
  origin: 'derived_measurement',
  position: { ra_deg: SRC_RA, dec_deg: SRC_DEC, frame: 'icrs', epoch: null },
  quality: OK,
  sigma_dec_mas: 12,
  sigma_ra_cosdec_mas: 12,
  snr: 95,
  track: [],
  x_px: 80,
  y_px: 70,
}

function measurement(visit: string, band: string, status: SourceMeasurement['status'], flags: string[] = []): SourceMeasurement {
  const measured = status === 'measured'
  const frameId = nativeId(visit, band)
  return {
    id: `${DS}:S001:${frameId}:psf_gaussian_fit`,
    association_note: null,
    band_id: band,
    corr_ra_dec: measured ? 0.1 : null,
    cov_xy_px: null,
    dataset_id: DS,
    dec_deg: measured ? SRC_DEC : null,
    epoch: midEpoch(visit, band),
    fit_chi2_reduced: measured ? 1.02 : null,
    flux: measured ? 9000 : null,
    flux_err: measured ? 95 : null,
    flux_unit: 'electron',
    frame_id: frameId,
    method: 'psf_gaussian_fit',
    method_version: '1.0.0',
    n_pixels: measured ? 49 : null,
    observation_id: obsId(visit, band),
    origin: 'derived_measurement',
    provenance: prov('derived_measurement'),
    psf_fwhm_arcsec: 1.0,
    quality: { status: measured ? (flags.length ? 'warning' : 'ok') : 'pending', flags, messages: [] },
    ra_deg: measured ? SRC_RA : null,
    sigma_components_mas: measured ? { centroid: 10, registration: 5 } : {},
    sigma_dec_mas: measured ? 12 : null,
    sigma_ra_cosdec_mas: measured ? 12 : null,
    snr: measured ? 95 : null,
    source_id: 'S001',
    status,
    status_reason: measured ? null : `${status} (test)`,
    uncertainty_status: measured ? 'estimated' : 'not_available',
    wcs_used: measured ? `registered:${frameId}` : null,
    x_px: measured ? 80 : null,
    y_px: measured ? 70 : null,
  }
}

const M = {
  v01G1: measurement('v01', 'G1', 'measured', ['MASKED_PIXELS_IN_FIT']),
  v02G1: measurement('v02', 'G1', 'measured'),
  v03G1: measurement('v03', 'G1', 'missing_frame', ['MISSING_FRAME']),
  v01G2: measurement('v01', 'G2', 'pending', ['LOW_SNR']),
  v02G2: measurement('v02', 'G2', 'measured', ['MASKED_PIXELS_IN_FIT', 'EDGE_TRUNCATED']),
}
const ALL_MEASUREMENTS = [M.v01G1, M.v02G1, M.v03G1, M.v01G2, M.v02G2]

const OBSERVER = { kind: 'geocenter' as const, ephemeris: 'astropy builtin (ERFA epv00)', approximation_note: null, max_position_error_km: null }
const fit: ModelFit = {
  assumptions: ['Radial velocity assumed 0 (unknown).', 'Observer: geocenter (astropy builtin (ERFA epv00)).'],
  band_ids: ['G1', 'G2'],
  chi2: 1.7,
  comparisons: [],
  covariance: [
    [25, 1],
    [1, 25],
  ],
  covariance_parameters: ['offset_ra_cosdec', 'offset_dec'],
  dataset_id: DS,
  derived: [{ name: 'distance', reason: 'Parallax is not in this model.', status: 'not_derived', uncertainty: null, unit: 'pc', value: null }],
  dof: 2,
  id: 'fit-0001',
  identifiability: {
    condition_number: 1.2,
    dof: 2,
    max_abs_correlation: 0.04,
    messages: [],
    n_epochs: 2,
    n_measurements: 2,
    n_parameters: 2,
    parallax_factor_span: null,
    status: 'constrained',
    thresholds: { min_dof: 2 },
    time_baseline_yr: 0.19,
  },
  input_hash: 'f'.repeat(64),
  inputs: {
    excluded_measurement_ids: [M.v02G1.id],
    measurement_ids: [M.v01G1.id, M.v02G2.id],
    model: 'static',
    observer: OBSERVER,
    reference_epoch_mjd_tdb: 60718.5,
    reference_position: { ra_deg: SRC_RA, dec_deg: SRC_DEC, frame: 'icrs', epoch: null },
    settings: { covariance_rescaled_by_chi2: false },
  },
  method: 'skyshift.science.astrometry.fit_astrometry',
  method_version: '1.0.0',
  model: 'static',
  model_description: 'Fixed position (no motion): 2 parameters.',
  origin: 'derived_measurement',
  p_value: 0.43,
  parameters: [
    { label: 'East offset', name: 'offset_ra_cosdec', status: 'estimated', uncertainty: 5, unit: 'mas', value: 1.5 },
    { label: 'North offset', name: 'offset_dec', status: 'estimated', uncertainty: 5, unit: 'mas', value: -0.7 },
  ],
  prediction: null,
  provenance: prov('derived_measurement'),
  reduced_chi2: 0.85,
  reference_epoch: epoch('2025-02-12T12:00:00Z', 60718.5),
  residuals: [],
  source_id: 'S001',
  status: 'ok',
  warnings: [],
}

const VIEW: ViewState = {
  band_id: 'G1',
  center_x_px: 87.5,
  center_y_px: 87.5,
  compare_frame_id: registeredId('v02', 'G1'),
  fov_arcsec: 70.4,
  frame_id: registeredId('v01', 'G1'),
  mode: 'analyze',
  stretch: { kind: 'asinh', p_low: 0.5, p_high: 99.7 },
  zoom: 2,
}

const ASSOCIATION: CatalogAssociation = {
  candidates: [],
  criteria: 'test criteria',
  epoch: midEpoch('v01', 'G1'),
  image_source_id: 'S001',
  match_radius_arcsec: 0.5,
  measurement_id: M.v01G1.id,
  notes: [],
  status: 'unmatched',
}

// Truth: offsets purely in declination, so separations from the source are exact (|Δδ|).
const ARCSEC = 1 / 3600
const truthSource = (id: string, kind: TruthSource['kind'], decOffsetArcsec: number, pm = 0): TruthSource => ({
  truth_id: id,
  kind,
  ra_deg: SRC_RA,
  dec_deg: SRC_DEC + decOffsetArcsec * ARCSEC,
  flux_by_band: { G1: 9000, G2: 26000 },
  in_simulated_catalog: true,
  matched_detected_source_id: null,
  origin: 'simulation_truth',
  parallax_mas: pm ? 165 : 0,
  pmdec_mas_yr: -pm,
  pmra_mas_yr: pm / 2,
  radial_velocity_km_s: 0,
  reference_epoch: { format: 'jyear', scale: 'tdb', value: 2026, iso_utc: null, mjd_tdb: 61041 },
  variability: null,
})
const truthPos = (truthId: string, frameId: string, decOffsetArcsec: number): TruthPosition => ({
  truth_id: truthId,
  frame_id: frameId,
  ra_deg: SRC_RA,
  dec_deg: SRC_DEC + decOffsetArcsec * ARCSEC,
  flux: 9000,
  x_px: 80,
  y_px: 70,
})
const frameTruth = (frameId: string): FrameTruth => ({
  frame_id: frameId,
  header_error_arcsec: [0.3, -0.2],
  header_rotation_error_deg: 0.01,
  pointing_offset_px: [1.5, -2.5],
  rotation_deg: 0.12,
  true_wcs: { distortion: 'none', header: { CTYPE1: 'RA---TAN', CTYPE2: 'DEC--TAN' }, kind: 'simulation_truth', pixel_convention: '0-based-centers', shape: [160, 160] },
})
// The moving source's reference-epoch (2026.0) position is 1.3″ away, but in the detection frame it is 0.12″ away.
// A stationary star sits 0.40″ away: inside the radius but farther than the moving source at the detection epoch.
const TRUTH: SimulationTruth = {
  dataset_id: DS,
  generator: 'skyshift.synthetic.generator',
  generator_version: '1.0.0',
  origin: 'simulation_truth',
  seed: 20261114,
  scenario_parameters: {},
  warning: 'Simulation truth: validation only.',
  sources: [truthSource('T-moving', 'moving_nearby_source', 1.3, 1100), truthSource('T-near', 'stationary_star', -0.4), truthSource('T-far', 'stationary_star', 5)],
  positions: [
    truthPos('T-moving', nativeId('v01', 'G1'), 0.12),
    truthPos('T-moving', nativeId('v02', 'G1'), 0.35),
    truthPos('T-moving', nativeId('v01', 'G2'), 0.13),
    truthPos('T-other-mover', nativeId('v01', 'G1'), 30),
  ],
  frames: [frameTruth(nativeId('v01', 'G1')), frameTruth(nativeId('v02', 'G1')), frameTruth(nativeId('v01', 'G2')), frameTruth(nativeId('v02', 'G2'))],
}

function draft(overrides: Partial<EvidenceDraft> = {}): EvidenceDraft {
  return {
    dataset,
    source,
    bandIds: ['G1', 'G2'],
    frameIds: [registeredId('v01', 'G1'), registeredId('v02', 'G1')],
    view: VIEW,
    measurementSet: { association_method: 'test', band_ids: ['G1', 'G2'], dataset_id: DS, measurements: ALL_MEASUREMENTS, method: 'psf_gaussian_fit', method_version: '1.0.0', notes: [], source_id: 'S001' },
    excludedIds: [M.v02G1.id, M.v01G2.id],
    fit,
    fitStale: false,
    associations: [ASSOCIATION],
    truth: TRUTH,
    ...overrides,
  }
}
const NOW = '2025-12-01T00:00:00Z'

/* ---------- buildEvidenceRecord ---------- */
describe('[contracts] buildEvidenceRecord', () => {
  it('[contracts] produces a record that satisfies the generated EvidenceRecord schema (no unknown fields)', () => {
    const record = buildEvidenceRecord(draft(), NOW, 'rec-1')
    expect(schemaErrors(record, DEFS.EvidenceRecord)).toEqual([])
    // The checker is not vacuous: it rejects an unknown field and a wrong literal.
    expect(schemaErrors({ ...record, extra: 1 }, DEFS.EvidenceRecord)).toContain('$.extra: unknown field')
    expect(schemaErrors({ ...record, record_label: 'discovery' }, DEFS.EvidenceRecord).length).toBeGreaterThan(0)
    expect(record.schema_version).toBe('skyshift.evidence/1')
    expect(record.contracts_version).toBe('skyshift.contracts/1.1')
    expect(record.created_utc).toBe(NOW)
    expect(record.updated_utc).toBe(NOW)
  })

  it('[contracts] labels simulated datasets as synthetic training records and observed ones as candidates for review', () => {
    const sim = buildEvidenceRecord(draft(), NOW, 'rec-sim')
    expect(sim.record_label).toBe('synthetic training record')
    expect(sim.dataset).toEqual({
      dataset_id: DS,
      provider: 'synthetic',
      origin: 'simulated',
      release: 'synthetic-v1',
      generator: 'skyshift.synthetic.generator',
      generator_version: '1.0.0',
      seed: 20261114,
      scenario_parameters: null,
    })
    expect(sim.simulation?.seed).toBe(20261114)

    const observedDataset = { ...dataset, origin: 'observed', provider: 'spherex', generator: null, generator_version: null, seed: null } as unknown as Dataset
    const obs = buildEvidenceRecord(draft({ dataset: observedDataset, truth: null }), NOW, 'rec-obs')
    expect(obs.record_label).toBe('candidate for review')
    expect(obs.simulation).toBeNull()
    expect(schemaErrors(obs, DEFS.EvidenceRecord)).toEqual([])
  })

  it('[contracts] keeps every measurement but includes only measured, non-excluded ones', () => {
    const record = buildEvidenceRecord(draft(), NOW, 'rec-2')
    expect(record.measurements.map((m) => m.id)).toEqual(ALL_MEASUREMENTS.map((m) => m.id))
    // v02G1 excluded by the user, v03G1 missing frame, v01G2 pending (also listed as excluded): none included.
    expect(record.included_measurement_ids).toEqual([M.v01G1.id, M.v02G2.id])
    expect(record.quality_flags).toEqual(['EDGE_TRUNCATED', 'LOW_SNR', 'MASKED_PIXELS_IN_FIT', 'MISSING_FRAME'])
    expect(record.provenance.parents).toEqual([...ALL_MEASUREMENTS.map((m) => m.id), 'fit-0001'])
    expect(record.provenance.origin).toBe('derived_measurement')
    expect(record.provenance.software).toEqual([{ name: 'skyshift-frontend', version: '0.1.0' }])
  })

  it('[contracts] sets fit_status none / current / stale and copies the fit assumptions', () => {
    const none = buildEvidenceRecord(draft({ fit: null }), NOW, 'a')
    expect(none.fit_status).toBe('none')
    expect(none.fit).toBeNull()
    expect(none.assumptions).toEqual([])
    expect(none.provenance.parents).not.toContain('fit-0001')
    const current = buildEvidenceRecord(draft({ fitStale: false }), NOW, 'b')
    expect(current.fit_status).toBe('current')
    expect(current.assumptions).toEqual(fit.assumptions)
    expect(buildEvidenceRecord(draft({ fitStale: true }), NOW, 'c').fit_status).toBe('stale')
    // A stale flag without a fit is still "none": there is nothing to be stale.
    expect(buildEvidenceRecord(draft({ fit: null, fitStale: true }), NOW, 'd').fit_status).toBe('none')
  })

  it('[contracts] filters simulation truth to the one source nearest the detection (within 0.5″) and to the selected frames', () => {
    const record = buildEvidenceRecord(draft(), NOW, 'rec-3')
    const truth = record.simulation?.truth
    expect(truth).toBeTruthy()
    // Nearest at the detection epoch: the mover (0.12″), not the stationary star (0.40″) and not by its 2026.0 position (1.3″).
    expect(truth!.sources.map((s) => s.truth_id)).toEqual(['T-moving'])
    expect(truth!.positions.every((p) => p.truth_id === 'T-moving')).toBe(true)
    expect(truth!.positions).toHaveLength(3)
    // Selected frames are registered products of v01/v02 G1; their truth WCS belongs to the native frames of those observations.
    expect(truth!.frames.map((f) => f.frame_id)).toEqual([nativeId('v01', 'G1'), nativeId('v02', 'G1')])
    expect(truth!.origin).toBe('simulation_truth')
    // Truth never enters the measurement list.
    expect(record.measurements.some((m) => (m as { origin: string }).origin === 'simulation_truth')).toBe(false)
  })

  it('[contracts] keeps no truth source when none lies within 0.5″, and no truth when none was loaded', () => {
    const shifted: DetectedSource = { ...source, position: { ...source.position, dec_deg: SRC_DEC + 2.0 * ARCSEC } }
    const far = buildEvidenceRecord(draft({ source: shifted }), NOW, 'rec-4').simulation!.truth!
    // Nearest candidate is now T-far at 3.0″ (others ≥ 1.88″): outside the radius.
    expect(far.sources).toEqual([])
    expect(far.positions).toEqual([])
    const noTruth = buildEvidenceRecord(draft({ truth: null }), NOW, 'rec-5')
    expect(noTruth.simulation).not.toBeNull()
    expect(noTruth.simulation!.truth).toBeNull()
  })

  it('[contracts] looks up observation ids and mid-exposure epochs for the selected frames', () => {
    const frameIds = [registeredId('v02', 'G1'), nativeId('v01', 'G1'), registeredId('v01', 'G1'), nativeId('v01', 'G2'), 'unknown:frame']
    const record = buildEvidenceRecord(draft({ frameIds }), NOW, 'rec-6')
    expect(record.selection.frame_ids).toEqual(frameIds)
    // One entry per distinct observation, in selection order; unknown frames are not invented.
    expect(record.selection.observation_ids).toEqual([obsId('v02', 'G1'), obsId('v01', 'G1'), obsId('v01', 'G2')])
    expect(record.selection.epochs.map((e) => e.iso_utc)).toEqual([VISITS.v02.mid, VISITS.v01.mid, '2025-01-08T03:15:30Z'])
    expect(record.selection.epochs[2].mjd_tdb).toBeCloseTo(VISITS.v01.mjd + 240 / 86400, 9)
    expect(record.selection.view).toEqual(VIEW)
    expect(record.selection.band_ids).toEqual(['G1', 'G2'])
    // The reference position is the measured position, dated by the detection frame's mid-exposure epoch.
    expect(record.source.reference_position.ra_deg).toBe(SRC_RA)
    expect(record.source.reference_position.dec_deg).toBe(SRC_DEC)
    expect(record.source.reference_position.epoch?.iso_utc).toBe(VISITS.v01.mid)
    expect(record.source.catalog_associations).toEqual([ASSOCIATION])
    expect(buildEvidenceRecord(draft({ associations: null }), NOW, 'x').source.catalog_associations).toEqual([])
  })
})

/* ---------- Persistence ---------- */
class MemoryStorage {
  data = new Map<string, string>()
  failWith: (() => Error) | null = null
  getItem(key: string): string | null {
    return this.data.has(key) ? this.data.get(key)! : null
  }
  setItem(key: string, value: string): void {
    if (this.failWith) throw this.failWith()
    this.data.set(key, String(value))
  }
  removeItem(key: string): void {
    this.data.delete(key)
  }
}

const EMPTY = { records: [], selectedId: null, loadError: null, rawStorage: null, saveError: null }

function sampleRecord(id: string, title = `Record ${id}`): EvidenceRecord {
  return buildEvidenceRecord(draft({ title }), NOW, id)
}

describe('[contracts] notebook persistence', () => {
  let storage: MemoryStorage
  beforeEach(() => {
    storage = new MemoryStorage()
    vi.stubGlobal('localStorage', storage)
    useNotebookStore.setState(EMPTY)
    useNotebookStore.getState().reloadFromStorage()
    mocks.validateEvidence.mockReset()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    useNotebookStore.setState(EMPTY)
  })

  it('[contracts] round-trips records through localStorage under skyshift.notebook.v1', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-14T12:00:00Z'))
    const store = useNotebookStore.getState()
    store.addRecord(sampleRecord('r1'))
    store.addRecord(sampleRecord('r2'))
    useNotebookStore.getState().updateRecord('r1', { title: 'Renamed', notes: 'checked residuals' })
    useNotebookStore.getState().removeRecord('r2')
    useNotebookStore.getState().addRecord(sampleRecord('r3'))

    const stored = JSON.parse(storage.getItem(NOTEBOOK_STORAGE_KEY)!)
    expect(stored.schema).toBe(NOTEBOOK_STORAGE_SCHEMA)
    expect(stored.records.map((r: EvidenceRecord) => r.id)).toEqual(['r3', 'r1'])

    const inMemory = useNotebookStore.getState().records
    useNotebookStore.setState(EMPTY)
    useNotebookStore.getState().reloadFromStorage()
    const reloaded = useNotebookStore.getState()
    expect(reloaded.loadError).toBeNull()
    expect(reloaded.records).toEqual(inMemory)
    const r1 = reloaded.records.find((r) => r.id === 'r1')!
    expect(r1.title).toBe('Renamed')
    expect(r1.notes).toBe('checked residuals')
    expect(r1.created_utc).toBe(NOW)
    expect(r1.updated_utc).toBe('2026-11-14T12:00:00Z')
    // Unchanged content is byte-identical after the round trip.
    expect(reloaded.records.find((r) => r.id === 'r3')).toEqual(sampleRecord('r3'))
  })

  it('[contracts] reports corrupted storage, starts empty, and never overwrites it before a reset', () => {
    storage.data.set(NOTEBOOK_STORAGE_KEY, '{"schema": "skyshift.notebook-storage/1", "records": [')
    useNotebookStore.getState().reloadFromStorage()
    let s = useNotebookStore.getState()
    expect(s.loadError).toMatch(/not valid JSON/)
    expect(s.records).toEqual([])
    expect(s.rawStorage).toBe('{"schema": "skyshift.notebook-storage/1", "records": [')

    // A new record stays in memory, but the unreadable data is left untouched.
    s.addRecord(sampleRecord('r-new'))
    s = useNotebookStore.getState()
    expect(s.records.map((r) => r.id)).toEqual(['r-new'])
    expect(s.saveError).toMatch(/could not be read/)
    expect(storage.getItem(NOTEBOOK_STORAGE_KEY)).toBe('{"schema": "skyshift.notebook-storage/1", "records": [')

    // Reset discards the unreadable data and saves what is in memory.
    s.resetStorage()
    s = useNotebookStore.getState()
    expect(s.loadError).toBeNull()
    expect(s.saveError).toBeNull()
    expect(readNotebookStorage(storage).records.map((r) => r.id)).toEqual(['r-new'])
  })

  it('[contracts] treats a foreign format or a malformed record as unreadable', () => {
    storage.data.set(NOTEBOOK_STORAGE_KEY, JSON.stringify({ schema: 'other-app/2', records: [] }))
    expect(readNotebookStorage(storage).error).toMatch(/unknown format/)
    storage.data.set(NOTEBOOK_STORAGE_KEY, JSON.stringify({ schema: NOTEBOOK_STORAGE_SCHEMA, records: [sampleRecord('ok'), { id: 'x' }] }))
    const read = readNotebookStorage(storage)
    expect(read.error).toMatch(/Stored record 2 of 2/)
    expect(read.records).toEqual([])
    expect(readNotebookStorage(null)).toMatchObject({ records: [], error: null, available: false })
  })

  it('[contracts] surfaces a full storage quota and does not keep a record the browser refused', () => {
    useNotebookStore.getState().addRecord(sampleRecord('r1'))
    storage.failWith = () => new DOMException('The quota has been exceeded.', 'QuotaExceededError')
    expect(() => useNotebookStore.getState().addRecord(sampleRecord('r2'))).toThrow(/storage is full/)
    const s = useNotebookStore.getState()
    expect(s.saveError).toMatch(/storage is full/)
    expect(s.records.map((r) => r.id)).toEqual(['r1'])
    expect(s.selectedId).toBe('r1')
    // What was stored before is intact.
    expect(readNotebookStorage(storage).records.map((r) => r.id)).toEqual(['r1'])
    // A note edit that cannot be saved is kept in memory and reported.
    useNotebookStore.getState().updateRecord('r1', { notes: 'draft' })
    expect(useNotebookStore.getState().records[0].notes).toBe('draft')
    expect(useNotebookStore.getState().saveError).toMatch(/storage is full/)
  })

  it('[contracts] imports validated records, keeps both on an id conflict, and recomputes fit status', async () => {
    const existing = sampleRecord('dup-id', 'Original')
    useNotebookStore.getState().addRecord(existing)
    const incoming = { ...sampleRecord('dup-id', 'Imported'), fit_status: 'current' as const }
    mocks.validateEvidence.mockResolvedValueOnce({
      valid: true,
      errors: [],
      warnings: ['The included measurements changed after the fit was computed.'],
      fit_input_hash_matches: true,
      recomputed_fit_status: 'stale',
      record: incoming,
    })
    const result = await useNotebookStore.getState().importFromText(JSON.stringify(incoming))
    expect(result.ok).toBe(true)
    expect(result.imported).toBe(1)
    expect(result.renamed).toBe(1)
    expect(result.message).toMatch(/same id/)
    const records = useNotebookStore.getState().records
    expect(records).toHaveLength(2)
    const copy = records.find((r) => r.title === 'Imported')!
    const original = records.find((r) => r.title === 'Original')!
    expect(original).toEqual(existing)
    expect(copy.id).not.toBe('dup-id')
    expect(copy.notes).toContain('dup-id')
    expect(copy.fit_status).toBe('stale')
    expect(useNotebookStore.getState().selectedId).toBe(copy.id)
    expect(readNotebookStorage(storage).records).toHaveLength(2)
  })

  it('[contracts] rejects records the backend marks invalid and unparseable files', async () => {
    mocks.validateEvidence.mockResolvedValueOnce({
      valid: false,
      errors: ['dataset: Field required'],
      warnings: [],
      fit_input_hash_matches: null,
      recomputed_fit_status: 'none',
      record: null,
    })
    const bad = await useNotebookStore.getState().importFromText(JSON.stringify({ records: [{ schema_version: 'skyshift.evidence/1', title: 'Broken' }] }))
    expect(bad.ok).toBe(false)
    expect(bad.rejected).toBe(1)
    expect(bad.message).toContain('dataset: Field required')
    expect(useNotebookStore.getState().records).toEqual([])

    const notJson = await useNotebookStore.getState().importFromText('{oops')
    expect(notJson.ok).toBe(false)
    expect(notJson.message).toMatch(/not valid JSON/)

    mocks.validateEvidence.mockRejectedValueOnce(new Error('The SkyShift API is not reachable.'))
    const offline = await useNotebookStore.getState().importFromText(JSON.stringify(sampleRecord('z')))
    expect(offline.ok).toBe(false)
    expect(offline.message).toMatch(/not reachable/)
    expect(useNotebookStore.getState().records).toEqual([])
  })
})
