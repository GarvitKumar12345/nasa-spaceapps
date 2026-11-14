/* Pixel-plane cache and display stretch. Display values are never used for measurement:
 * all quantitative work happens in the backend on native arrays. */
import { useEffect, useState } from 'react'
import { api, describeError, type PlaneData } from '../../api/client'

const cache = new Map<string, Promise<PlaneData>>()

export function loadPlane(datasetId: string, frameId: string): Promise<PlaneData> {
  const key = `${datasetId}|${frameId}`
  let p = cache.get(key)
  if (!p) {
    p = api.framePixels(datasetId, frameId, 'image')
    cache.set(key, p)
    p.catch(() => cache.delete(key))
  }
  return p
}

export type PlaneState = { status: 'idle' | 'loading' } | { status: 'ready'; plane: PlaneData } | { status: 'error'; message: string }

export function usePlane(datasetId: string | null, frameId: string | null): PlaneState {
  const [state, setState] = useState<PlaneState>({ status: 'idle' })
  useEffect(() => {
    if (!datasetId || !frameId) {
      setState({ status: 'idle' })
      return
    }
    let alive = true
    setState({ status: 'loading' })
    loadPlane(datasetId, frameId)
      .then((plane) => alive && setState({ status: 'ready', plane }))
      .catch((e) => alive && setState({ status: 'error', message: describeError(e) }))
    return () => {
      alive = false
    }
  }, [datasetId, frameId])
  return state
}

/** Percentile of the finite values (NaN = no coverage is ignored). */
export function percentiles(data: ArrayLike<number>, ps: number[]): number[] {
  const finite: number[] = []
  for (let i = 0; i < data.length; i++) {
    const v = data[i]
    if (Number.isFinite(v)) finite.push(v)
  }
  if (!finite.length) return ps.map(() => 0)
  finite.sort((a, b) => a - b)
  return ps.map((p) => finite[Math.min(finite.length - 1, Math.max(0, Math.round((p / 100) * (finite.length - 1))))])
}

export type StretchKind = 'asinh' | 'linear' | 'log'

export interface StretchLimits {
  lo: number
  hi: number
}

function stretchValue(t: number, kind: StretchKind): number {
  if (kind === 'linear') return t
  if (kind === 'log') return Math.log10(1 + 999 * t) / 3
  const beta = 6
  return Math.asinh(t * beta) / Math.asinh(beta)
}

const NODATA: [number, number, number] = [22, 27, 36] // --nodata

/** Render a row-major plane (row 0 = y 0) into ImageData with north (+y) up. */
export function renderImageData(plane: PlaneData, limits: StretchLimits, kind: StretchKind, mode: 'sky' | 'difference' = 'sky'): ImageData {
  const [ny, nx] = plane.shape
  const out = new ImageData(nx, ny)
  const span = limits.hi - limits.lo || 1
  for (let y = 0; y < ny; y++) {
    const row = ny - 1 - y
    for (let x = 0; x < nx; x++) {
      const v = plane.data[y * nx + x]
      const o = (row * nx + x) * 4
      if (!Number.isFinite(v)) {
        out.data[o] = NODATA[0]
        out.data[o + 1] = NODATA[1]
        out.data[o + 2] = NODATA[2]
        out.data[o + 3] = 255
        continue
      }
      let g: number
      if (mode === 'difference') {
        // Symmetric grey scale: mid-grey = 0, darker = negative, brighter = positive (no hue).
        const t = Math.max(-1, Math.min(1, v / Math.max(Math.abs(limits.lo), Math.abs(limits.hi), 1e-9)))
        g = 128 + 127 * t
      } else {
        const t = Math.max(0, Math.min(1, (v - limits.lo) / span))
        g = 255 * stretchValue(t, kind)
      }
      out.data[o] = g * 0.94
      out.data[o + 1] = g * 0.97
      out.data[o + 2] = g
      out.data[o + 3] = 255
    }
  }
  return out
}

export function differenceLimits(plane: PlaneData): StretchLimits {
  const abs: number[] = []
  for (let i = 0; i < plane.data.length; i++) {
    const v = plane.data[i]
    if (Number.isFinite(v)) abs.push(Math.abs(v))
  }
  abs.sort((a, b) => a - b)
  const m = abs.length ? abs[Math.floor(0.995 * (abs.length - 1))] : 1
  return { lo: -m, hi: m }
}
