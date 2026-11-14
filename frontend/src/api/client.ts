/* Typed client for the SkyShift FastAPI backend (see docs/architecture.md §5).
 * All JSON shapes come from contracts.gen.ts (generated from the Python contracts). */
import type {
  CatalogAssociation,
  CatalogOverlay,
  Dataset,
  DatasetSummary,
  DetectedSource,
  DifferenceInfo,
  EvidenceRecord,
  EvidenceValidation,
  FitRequest,
  HealthStatus,
  MeasurementSet,
  ModelFit,
  ProviderStatus,
  ReproductionReport,
  ResolveResult,
  SimulationTruth,
  ValidationReport,
} from './contracts.gen'

export type PixelPlane = 'image' | 'variance' | 'mask'

export interface PlaneData {
  /** Row-major, row 0 = pixel y 0. NaN = no coverage / masked (registered products). */
  data: Float32Array | Uint16Array
  shape: [number, number] // [ny, nx]
  unit: string
  origin: string
  frameId: string
  plane: string
  displayOnly: boolean
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** True when the backend could not be reached at all. */
  get isNetwork(): boolean {
    return this.status === 0
  }
}

const BASE = '/api'
const DEFAULT_TIMEOUT_MS = 60_000

const enc = encodeURIComponent

async function raw(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(BASE + path, { ...init, signal: init.signal ?? controller.signal })
  } catch (err) {
    clearTimeout(timer)
    const aborted = err instanceof DOMException && err.name === 'AbortError'
    throw new ApiError(
      0,
      aborted ? 'timeout' : 'network_error',
      aborted
        ? `The SkyShift API did not respond within ${Math.round(timeoutMs / 1000)} s.`
        : 'The SkyShift API is not reachable. Start it with "npm run dev" at the repository root.',
    )
  }
  clearTimeout(timer)
  if (!response.ok) {
    let code = 'http_error'
    let message = `${response.status} ${response.statusText}`
    let details: Record<string, unknown> = {}
    try {
      const body = await response.json()
      const detail = body?.detail
      if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        code = String(detail.code ?? code)
        message = String(detail.message ?? message)
        details = (detail.details as Record<string, unknown>) ?? {}
      } else if (Array.isArray(detail)) {
        code = 'invalid_request'
        message = detail.map((d: { msg?: string; loc?: unknown[] }) => `${(d.loc ?? []).join('.')}: ${d.msg}`).join('; ')
      } else if (typeof detail === 'string') {
        message = detail
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, code, message, details)
  }
  return response
}

async function json<T>(path: string, init: RequestInit = {}, timeoutMs?: number): Promise<T> {
  const response = await raw(path, init, timeoutMs)
  return (await response.json()) as T
}

function post(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

async function plane(path: string): Promise<PlaneData> {
  const response = await raw(path)
  const buffer = await response.arrayBuffer()
  const shapeHeader = response.headers.get('X-SkyShift-Shape') ?? ''
  const [ny, nx] = shapeHeader.split(',').map((v) => Number.parseInt(v, 10))
  const dtype = response.headers.get('X-SkyShift-Dtype') ?? 'float32'
  if (!Number.isFinite(ny) || !Number.isFinite(nx)) {
    throw new ApiError(500, 'internal_error', 'Pixel response is missing its shape header.')
  }
  const data = dtype === 'uint16' ? new Uint16Array(buffer) : new Float32Array(buffer)
  if (data.length !== ny * nx) {
    throw new ApiError(500, 'internal_error', `Pixel payload has ${data.length} values; expected ${ny * nx}.`)
  }
  return {
    data,
    shape: [ny, nx],
    unit: response.headers.get('X-SkyShift-Unit') ?? '',
    origin: response.headers.get('X-SkyShift-Origin') ?? '',
    frameId: response.headers.get('X-SkyShift-Frame') ?? '',
    plane: response.headers.get('X-SkyShift-Plane') ?? '',
    displayOnly: response.headers.get('X-SkyShift-Display-Only') === 'true',
  }
}

export const api = {
  health: () => json<HealthStatus>('/health', {}, 8_000),
  providers: () => json<ProviderStatus[]>('/providers'),
  datasets: () => json<DatasetSummary[]>('/datasets'),
  dataset: (datasetId: string) => json<Dataset>(`/datasets/${enc(datasetId)}`, {}, 120_000),
  framePixels: (datasetId: string, frameId: string, which: PixelPlane = 'image') =>
    plane(`/datasets/${enc(datasetId)}/frames/${enc(frameId)}/pixels?plane=${which}`),
  sources: (datasetId: string) => json<DetectedSource[]>(`/datasets/${enc(datasetId)}/sources`, {}, 120_000),
  measurements: (datasetId: string, sourceId: string, method = 'psf_gaussian_fit') =>
    json<MeasurementSet>(`/datasets/${enc(datasetId)}/sources/${enc(sourceId)}/measurements?method=${enc(method)}`),
  associations: (datasetId: string, sourceId: string) =>
    json<CatalogAssociation[]>(`/datasets/${enc(datasetId)}/sources/${enc(sourceId)}/associations`),
  catalogOverlay: (datasetId: string, frameId: string) =>
    json<CatalogOverlay>(`/datasets/${enc(datasetId)}/catalog?frame_id=${enc(frameId)}`),
  differenceInfo: (datasetId: string, a: string, b: string) =>
    json<DifferenceInfo>(`/datasets/${enc(datasetId)}/difference/info?a=${enc(a)}&b=${enc(b)}`),
  differencePixels: (datasetId: string, a: string, b: string) =>
    plane(`/datasets/${enc(datasetId)}/difference/pixels?a=${enc(a)}&b=${enc(b)}`),
  truth: (datasetId: string) => json<SimulationTruth>(`/datasets/${enc(datasetId)}/truth`),
  resolve: (query: string, datasetId?: string) =>
    json<ResolveResult>(`/resolve?q=${enc(query)}${datasetId ? `&dataset_id=${enc(datasetId)}` : ''}`),
  fitAstrometric: (request: FitRequest) => json<ModelFit>('/fits/astrometric', post(request)),
  validateEvidence: (record: unknown) => json<EvidenceValidation>('/evidence/validate', post(record)),
  reproduceEvidence: (record: EvidenceRecord) =>
    json<ReproductionReport>('/evidence/reproduce', post(record), 180_000),
  evidenceCsv: async (record: EvidenceRecord): Promise<string> => {
    const response = await raw('/evidence/csv', post(record))
    return response.text()
  },
  validation: () => json<ValidationReport>('/validation'),
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}
