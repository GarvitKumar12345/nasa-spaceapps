import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, GAIA_SOURCE_ID, api, assertGaiaSourceId } from '../api/client'
import type { GaiaPrediction } from '../api/types'
import { RESIDUAL_MAGNIFICATION, measuredDisplayPoint, predictionKind, visiblePredictions } from './gaia'

const BARNARD = '4472832130942575872' // Gaia DR3 source_id > 2^53

function pred(over: Partial<GaiaPrediction> = {}): GaiaPrediction {
  return {
    source_id: BARNARD, ra_deg: 269.4, dec_deg: 4.7, sigma_ra_cosdec_mas: 0.3, sigma_dec_mas: 0.3, corr_ra_dec: 0, x_native: 10, y_native: 10,
    x_display: 30, y_display: 31, in_native: true, g_mag: 13, bp_rp: 1, solution: '5-parameter', flags: [], reference_status: 'not_candidate',
    reference_reason: null, origin: 'model_prediction', ...over,
  } as GaiaPrediction
}

describe('[contracts] Gaia source IDs stay strings', () => {
  it('[contracts] JSON numbers cannot carry Gaia IDs exactly; decimal strings do', () => {
    // independent of SkyShift: what JSON.parse does to a 64-bit id
    expect(String(JSON.parse(`{"id":${BARNARD}}`).id)).not.toBe(BARNARD)
    expect(JSON.parse(`{"id":"${BARNARD}"}`).id).toBe(BARNARD)
    expect(Number.isSafeInteger(Number(BARNARD))).toBe(false)
    expect(GAIA_SOURCE_ID.test(BARNARD)).toBe(true)
  })

  it('[contracts] the client refuses numeric or malformed source IDs instead of converting them', () => {
    expect(assertGaiaSourceId(BARNARD, 't')).toBe(BARNARD)
    expect(() => assertGaiaSourceId(4472832130942575872, 't')).toThrow(ApiError)
    expect(() => assertGaiaSourceId('4.47e18', 't')).toThrow(/decimal string/)
    expect(() => assertGaiaSourceId('0123', 't')).toThrow()
  })
})

describe('[api] Gaia overlay transport', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('[api] an overlay whose source_id arrives as a JSON number is rejected', async () => {
    const body = `{"dataset_id":"d","frame_id":"f","predictions":[{"source_id":${BARNARD}}]}`
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } })))
    await expect(api.gaiaOverlay('d', 'f')).rejects.toThrow(/decimal string/)
  })

  it('[api] string IDs pass through unchanged and are URL-encoded in detail requests', async () => {
    const calls: string[] = []
    const body = JSON.stringify({ dataset_id: 'd', frame_id: 'f', predictions: [pred()] })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(String(url))
      return new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const ov = await api.gaiaOverlay('spherex-dr1-barnard', 'a:b:display')
    expect(ov.predictions[0].source_id).toBe(BARNARD)
    expect(calls[0]).toContain('frame_id=a%3Ab%3Adisplay')
    await expect(api.gaiaSource('d', '12.5', 'f')).rejects.toThrow(/decimal string/)
  })
})

describe('[ui] Gaia overlay geometry and classes', () => {
  it('[ui] marker classes follow the reference role, then catalogue limitations', () => {
    expect(predictionKind(pred({ flags: ['SATURATED_IN_FRAME'], reference_status: 'rejected' }))).toBe('saturated')
    expect(predictionKind(pred({ reference_status: 'used' }))).toBe('used')
    expect(predictionKind(pred({ solution: '2-parameter' }))).toBe('no_motion')
    expect(predictionKind(pred({ reference_status: 'rejected' }))).toBe('rejected')
    expect(predictionKind(pred())).toBe('other')
  })

  it('[ui] only in-frame predictions brighter than the limit are drawn', () => {
    const ov = { predictions: [pred({ g_mag: 12 }), pred({ g_mag: 19 }), pred({ in_native: false }), pred({ x_display: null }), pred({ g_mag: null })] }
    expect(visiblePredictions(ov as never, 18.5)).toHaveLength(1)
    expect(visiblePredictions(ov as never, 21.5)).toHaveLength(2)
    expect(visiblePredictions(null, 21.5)).toEqual([])
  })

  it('[ui] residuals map to the north-up/east-left grid: +east -> -x, +north -> +y, magnified on request', () => {
    const p = pred({ x_display: 30, y_display: 31 })
    expect(measuredDisplayPoint(p, { east: 6.15, north: 0 }, 6.15)).toEqual([29, 31])
    expect(measuredDisplayPoint(p, { east: 0, north: 6.15 }, 6.15)).toEqual([30, 32])
    const [x] = measuredDisplayPoint(p, { east: 0.0615, north: 0 }, 6.15, RESIDUAL_MAGNIFICATION) as [number, number]
    expect(x).toBeCloseTo(29, 9)
    expect(measuredDisplayPoint(pred({ x_display: null }), { east: 1, north: 1 }, 6.15)).toBeNull()
  })
})
