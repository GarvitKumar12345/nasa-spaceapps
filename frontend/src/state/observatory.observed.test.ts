import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { Dataset } from '../api/types'
import { blinkState, capability, displayFrameId } from './observatory'

type Obs = { id: string; band_id: string; status: string; frame_ids: string[]; timing: { mid: { mjd_tdb: number } } }
const obs = (id: string, band: string, status = 'available', t = 0): Obs => ({ id, band_id: band, status, frame_ids: status === 'available' ? [`${id}:native`, `${id}:display`] : [], timing: { mid: { mjd_tdb: t } } })
const group = (id: string, members: string[], blinkable: boolean, reason: string) => ({ id, compatibility: { blinkable, reason, member_observation_ids: members } })

function dataset(bands: unknown[], observations: Obs[], capabilities: unknown[] = []): Dataset {
  return { bands, observations, capabilities } as unknown as Dataset
}

describe('[ui] observed-data helpers', () => {
  it('[ui] display frame: registered product first, archive-WCS display product otherwise', () => {
    expect(displayFrameId({ frame_ids: ['a:native', 'a:registered'] } as never)).toBe('a:registered')
    expect(displayFrameId({ frame_ids: ['a:native', 'a:display'] } as never)).toBe('a:display')
    expect(displayFrameId({ frame_ids: ['a:native'] } as never)).toBeNull()
    expect(displayFrameId(null)).toBeNull()
  })

  it('[ui] blink only for a compatibility group marked blinkable with two available members', () => {
    const ds = dataset(
      [group('D1-g1', ['a', 'b'], true, 'two compatible'), group('D1-single1', ['c'], false, 'Single observation: no wavelength-compatible repeat.')],
      [obs('a', 'D1-g1', 'available', 1), obs('b', 'D1-g1', 'available', 2), obs('c', 'D1-single1')],
    )
    expect(blinkState(ds, 'D1-g1')).toEqual({ ok: true, reason: null })
    expect(blinkState(ds, 'D1-single1')).toEqual({ ok: false, reason: 'Single observation: no wavelength-compatible repeat.' })
    // A group whose backend verdict is "blinkable" but with one member missing locally is still refused.
    const partial = dataset([group('D1-g1', ['a', 'b'], true, 'two compatible')], [obs('a', 'D1-g1'), obs('b', 'D1-g1', 'missing')])
    expect(blinkState(partial, 'D1-g1').ok).toBe(false)
  })

  it('[ui] synthetic bands (no compatibility record) keep their existing behaviour', () => {
    const ds = dataset([{ id: 'G1', compatibility: null }], [obs('a', 'G1', 'available', 1), obs('b', 'G1', 'available', 2)])
    expect(blinkState(ds, 'G1').ok).toBe(true)
    expect(capability(ds, 'difference_imaging')).toBeNull()
    const observed = dataset([], [], [{ id: 'difference_imaging', status: 'unavailable', reason: 'needs PSF matching', requirements: [] }])
    expect(capability(observed, 'difference_imaging')?.status).toBe('unavailable')
  })
})

describe('[api] pixel transport', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('[api] uint32 flag planes decode exactly, including bit 31', async () => {
    const values = new Uint32Array([0, 2 ** 21, 2 ** 31 + 2 ** 26, 4294967295, 7, 2 ** 28])
    const headers = { 'X-SkyShift-Shape': '2,3', 'X-SkyShift-Dtype': 'uint32', 'X-SkyShift-Unit': '', 'X-SkyShift-Origin': 'observed', 'X-SkyShift-Frame': 'f', 'X-SkyShift-Plane': 'mask', 'X-SkyShift-Display-Only': 'false' }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(values.buffer.slice(0), { status: 200, headers })))
    const plane = await api.framePixels('ds', 'f', 'mask')
    expect(plane.data).toBeInstanceOf(Uint32Array)
    expect(Array.from(plane.data)).toEqual(Array.from(values))
    expect(plane.shape).toEqual([2, 3])
    expect(plane.origin).toBe('observed')
  })

  it('[api] a payload whose length disagrees with its shape is rejected', async () => {
    const headers = { 'X-SkyShift-Shape': '4,4', 'X-SkyShift-Dtype': 'uint32' }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(new Uint32Array(3).buffer, { status: 200, headers })))
    await expect(api.framePixels('ds', 'f', 'mask')).rejects.toThrow(/expected 16/)
  })
})
