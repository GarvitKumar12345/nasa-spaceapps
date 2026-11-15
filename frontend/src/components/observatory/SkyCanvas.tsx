/* Sky canvas: registered display frame on the common grid (north up, east left) with
 * vector overlays. Pixel data are display-only; positions come from measurements. */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import type { TanWcs } from '../../lib/tanwcs'
import { fmtDecDms, fmtRaHms } from '../../lib/format'
import type { ViewTransform } from '../../state/observatory'
import { renderImageData, type PlaneState, type StretchKind, type StretchLimits } from './pixels'

export interface CanvasPoint {
  id: string
  x: number // common-grid pixel
  y: number
  /** Text for hover/selection labels (defaults to id). */
  label?: string
}

/** Catalogue prediction marker (model): hollow square; role and limitations set the style. */
export interface PredictionMarker {
  id: string
  x: number
  y: number
  kind: 'used' | 'rejected' | 'saturated' | 'no_motion' | 'other'
}

export interface CanvasOverlays {
  modelPath?: [number, number][] | null
  modelNow?: [number, number] | null
  truthNow?: [number, number] | null
  catalog?: { id: string; x: number; y: number }[] | null
  /** Gaia DR3 predictions at the frame epoch (model predictions, observed data). */
  predictions?: PredictionMarker[] | null
  /** ePSF image measurements of reference candidates (derived measurements). */
  measured?: CanvasPoint[] | null
  /** Magnified measured-minus-predicted residuals (grid pixels). */
  vectors?: { id: string; x0: number; y0: number; x1: number; y1: number }[] | null
}

export interface SkyCanvasProps {
  plane: PlaneState
  limits: StretchLimits | null
  stretch: StretchKind
  mode?: 'sky' | 'difference'
  wcs: TanWcs
  gridShape: [number, number] // [ny, nx]
  view: ViewTransform
  onView: (v: Partial<ViewTransform>) => void
  sources: CanvasPoint[]
  selectedId: string | null
  hoverId: string | null
  onSelect: (id: string | null) => void
  onHover: (id: string | null) => void
  overlays?: CanvasOverlays
  showGrid: boolean
  showLabels: boolean
  cornerTopLeft: ReactNode
  cornerBottomLeft: ReactNode
  ariaLabel: string
  testId?: string
  minHeight?: number
  valueUnit?: string
  /** Optional RGBA raster drawn over the image with the same geometry (e.g. archive flag overlay). */
  overlayImage?: ImageData | null
  /** Optional marker (common-grid pixel) with a label, e.g. the archive query position. */
  marker?: { x: number; y: number; label: string } | null
}

const NICE_ARCSEC = [0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 300]

function niceArcsec(target: number): number {
  return NICE_ARCSEC.find((s) => s >= target) ?? NICE_ARCSEC[NICE_ARCSEC.length - 1]
}

export function SkyCanvas(props: SkyCanvasProps) {
  const { plane, limits, stretch, mode = 'sky', wcs, gridShape, view, onView, sources, selectedId, hoverId, onSelect, onHover, overlays, showGrid, showLabels } = props
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [size, setSize] = useState({ w: 640, h: 480 })
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const drag = useRef<{ sx: number; sy: number; cx: number; cy: number; moved: boolean } | null>(null)
  const helpId = useId()
  const [ny, nx] = gridShape

  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () => {
      const r = el.getBoundingClientRect()
      setSize({ w: Math.max(200, Math.floor(r.width)), h: Math.max(160, Math.floor(r.height)) })
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fitZoom = Math.min(size.w / nx, size.h / ny) * 0.98
  const zoom = view.zoom ?? fitZoom
  const toScreen = (x: number, y: number): [number, number] => [size.w / 2 + (x - view.cx) * zoom, size.h / 2 - (y - view.cy) * zoom]
  const toGrid = (sx: number, sy: number): [number, number] => [view.cx + (sx - size.w / 2) / zoom, view.cy - (sy - size.h / 2) / zoom]

  const offscreen = useMemo(() => {
    if (plane.status !== 'ready' || !limits) return null
    const img = renderImageData(plane.plane, limits, stretch, mode)
    const c = document.createElement('canvas')
    c.width = img.width
    c.height = img.height
    c.getContext('2d')!.putImageData(img, 0, 0)
    return c
  }, [plane, limits, stretch, mode])

  const overlayCanvas = useMemo(() => {
    const img = props.overlayImage
    if (!img) return null
    const c = document.createElement('canvas')
    c.width = img.width
    c.height = img.height
    c.getContext('2d')!.putImageData(img, 0, 0)
    return c
  }, [props.overlayImage])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(size.w * dpr)
    canvas.height = Math.round(size.h * dpr)
    const ctx = canvas.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = '#03050a'
    ctx.fillRect(0, 0, size.w, size.h)
    if (!offscreen) return
    ctx.imageSmoothingEnabled = zoom < 1.5
    const [sx0, sy0] = toScreen(-0.5, ny - 0.5)
    ctx.drawImage(offscreen, sx0, sy0, nx * zoom, ny * zoom)
    if (overlayCanvas) {
      ctx.imageSmoothingEnabled = false
      ctx.drawImage(overlayCanvas, sx0, sy0, nx * zoom, ny * zoom)
    }
  })

  const gridLines = useMemo(() => {
    if (!showGrid) return null
    const scale = wcs.pixelScaleArcsec
    const step = niceArcsec((110 / zoom) * scale)
    const corners = [toGrid(0, 0), toGrid(size.w, 0), toGrid(0, size.h), toGrid(size.w, size.h)].map(([x, y]) => wcs.pixelToSky(x, y))
    const [, dec0] = wcs.pixelToSky(view.cx, view.cy)
    const decs = corners.map((c) => c[1])
    const ras = corners.map((c) => ((c[0] - corners[0][0] + 540) % 360) - 180 + corners[0][0])
    const dStep = step / 3600
    const rStep = dStep / Math.max(Math.cos((dec0 * Math.PI) / 180), 1e-3)
    const lines: { d: string; label: string; lx: number; ly: number; kind: 'ra' | 'dec' }[] = []
    const decMin = Math.min(...decs)
    const decMax = Math.max(...decs)
    const raMin = Math.min(...ras)
    const raMax = Math.max(...ras)
    if ((decMax - decMin) / dStep > 60 || (raMax - raMin) / rStep > 60) return null
    for (let d = Math.ceil(decMin / dStep) * dStep; d <= decMax; d += dStep) {
      let path = ''
      for (let k = 0; k <= 24; k++) {
        const ra = raMin + ((raMax - raMin) * k) / 24
        const [px, py] = wcs.skyToPixel(ra, d)
        const [sx, sy] = toScreen(px, py)
        path += `${k ? 'L' : 'M'}${sx.toFixed(1)},${sy.toFixed(1)}`
      }
      const [lpx, lpy] = wcs.skyToPixel(raMax, d)
      const [lx, ly] = toScreen(lpx, lpy)
      lines.push({ d: path, label: fmtDecDms(d, 0).replace(/^[+−]\d+° /, ''), lx, ly, kind: 'dec' })
    }
    for (let r = Math.ceil(raMin / rStep) * rStep; r <= raMax; r += rStep) {
      let path = ''
      for (let k = 0; k <= 24; k++) {
        const dd = decMin + ((decMax - decMin) * k) / 24
        const [px, py] = wcs.skyToPixel(r, dd)
        const [sx, sy] = toScreen(px, py)
        path += `${k ? 'L' : 'M'}${sx.toFixed(1)},${sy.toFixed(1)}`
      }
      const [lpx, lpy] = wcs.skyToPixel(r, decMin)
      const [lx, ly] = toScreen(lpx, lpy)
      lines.push({ d: path, label: fmtRaHms((r + 360) % 360, 1).replace(/^\d+h /, ''), lx, ly, kind: 'ra' })
    }
    return { lines, step }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showGrid, wcs, zoom, view.cx, view.cy, size.w, size.h])

  const scaleBar = useMemo(() => {
    const arcsec = niceArcsec((90 / zoom) * wcs.pixelScaleArcsec)
    return { arcsec, px: (arcsec / wcs.pixelScaleArcsec) * zoom }
  }, [zoom, wcs])

  const compass = useMemo(() => {
    const [ra, dec] = wcs.pixelToSky(view.cx, view.cy)
    const [nxp, nyp] = wcs.skyToPixel(ra, dec + 2 / 3600)
    const [exp, eyp] = wcs.skyToPixel(ra + 2 / 3600 / Math.max(Math.cos((dec * Math.PI) / 180), 1e-3), dec)
    // Grid-frame direction vectors (y up); drawn below with screen y = -grid y.
    const n = [nxp - view.cx, nyp - view.cy]
    const e = [exp - view.cx, eyp - view.cy]
    const norm = (v: number[]) => {
      const l = Math.hypot(v[0], v[1]) || 1
      return [v[0] / l, v[1] / l]
    }
    return { n: norm(n), e: norm(e) }
  }, [wcs, view.cx, view.cy])

  const nearestSource = (sx: number, sy: number, maxPx = 14): string | null => {
    let best: string | null = null
    let bd = maxPx * maxPx
    for (const s of sources) {
      const [px, py] = toScreen(s.x, s.y)
      const d = (px - sx) ** 2 + (py - sy) ** 2
      if (d < bd) {
        bd = d
        best = s.id
      }
    }
    return best
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    ;(e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId)
    drag.current = { sx: e.clientX, sy: e.clientY, cx: view.cx, cy: view.cy, moved: false }
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const r = wrapRef.current!.getBoundingClientRect()
    const sx = e.clientX - r.left
    const sy = e.clientY - r.top
    const d = drag.current
    if (d) {
      const dx = e.clientX - d.sx
      const dy = e.clientY - d.sy
      if (Math.hypot(dx, dy) > 3) d.moved = true
      if (d.moved) onView({ cx: d.cx - dx / zoom, cy: d.cy + dy / zoom })
      return
    }
    const [gx, gy] = toGrid(sx, sy)
    setCursor({ x: gx, y: gy })
    const near = nearestSource(sx, sy)
    if (near !== hoverId) onHover(near)
  }
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    drag.current = null
    if (d && !d.moved) {
      const r = wrapRef.current!.getBoundingClientRect()
      onSelect(nearestSource(e.clientX - r.left, e.clientY - r.top))
    }
  }

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const sx = e.clientX - r.left
      const sy = e.clientY - r.top
      const z0 = view.zoom ?? fitZoom
      const z1 = Math.min(40, Math.max(fitZoom * 0.5, z0 * Math.exp(-e.deltaY * 0.0015)))
      const gx = view.cx + (sx - size.w / 2) / z0
      const gy = view.cy - (sy - size.h / 2) / z0
      onView({ zoom: z1, cx: gx - (sx - size.w / 2) / z1, cy: gy + (sy - size.h / 2) / z1 })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [view, fitZoom, size, onView])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const pan = 40 / zoom
    const z0 = view.zoom ?? fitZoom
    if (e.key === 'ArrowLeft' && !e.altKey) onView({ cx: view.cx - pan })
    else if (e.key === 'ArrowRight' && !e.altKey) onView({ cx: view.cx + pan })
    else if (e.key === 'ArrowUp') onView({ cy: view.cy + pan })
    else if (e.key === 'ArrowDown') onView({ cy: view.cy - pan })
    else if (e.key === '+' || e.key === '=') onView({ zoom: Math.min(40, z0 * 1.4) })
    else if (e.key === '-' || e.key === '_') onView({ zoom: Math.max(fitZoom * 0.5, z0 / 1.4) })
    else if (e.key === '0') onView({ zoom: null, cx: (nx - 1) / 2, cy: (ny - 1) / 2 })
    else if (e.key === 'Escape') onSelect(null)
    else return
    e.preventDefault()
    e.stopPropagation()
  }

  const sel = sources.find((s) => s.id === selectedId)
  const hov = hoverId && hoverId !== selectedId ? sources.find((s) => s.id === hoverId) : undefined
  const cursorSky = cursor ? wcs.pixelToSky(cursor.x, cursor.y) : null
  let cursorValue: number | null = null
  if (cursor && plane.status === 'ready') {
    const ix = Math.round(cursor.x)
    const iy = Math.round(cursor.y)
    const [pny, pnx] = plane.plane.shape
    if (ix >= 0 && iy >= 0 && ix < pnx && iy < pny) cursorValue = plane.plane.data[iy * pnx + ix]
  }
  const modelPath = overlays?.modelPath?.map(([x, y]) => toScreen(x, y))

  return (
    <div
      ref={wrapRef}
      className="sky-canvas"
      style={{ minHeight: props.minHeight }}
      tabIndex={0}
      role="group"
      aria-label={props.ariaLabel}
      aria-describedby={helpId}
      data-testid={props.testId}
      data-zoom={zoom.toFixed(3)}
      data-cx={view.cx.toFixed(2)}
      data-cy={view.cy.toFixed(2)}
      data-selected={selectedId ?? ''}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={() => {
        setCursor(null)
        if (hoverId) onHover(null)
      }}
      onKeyDown={onKeyDown}
    >
      <span id={helpId} className="sr-only">
        Drag or use arrow keys to pan, mouse wheel or plus and minus to zoom, 0 to fit, click a source to select it, Escape to clear the selection.
      </span>
      <canvas ref={canvasRef} className="sky-canvas-img" style={{ width: size.w, height: size.h }} aria-hidden />
      <svg className="sky-overlay" width={size.w} height={size.h} viewBox={`0 0 ${size.w} ${size.h}`} aria-hidden>
        {gridLines?.lines.map((l, i) => (
          <g key={i}>
            <path d={l.d} className="sky-grid-line" />
            {showLabels && Number.isFinite(l.lx) && (
              <text className="sky-grid-label" x={l.kind === 'dec' ? Math.min(size.w - 4, Math.max(4, l.lx)) : Math.min(size.w - 30, Math.max(4, l.lx + 3))} y={l.kind === 'dec' ? Math.min(size.h - 6, Math.max(12, l.ly - 3)) : size.h - 22} textAnchor={l.kind === 'dec' ? 'end' : 'start'}>
                {l.label}
              </text>
            )}
          </g>
        ))}
        {overlays?.catalog?.map((c) => {
          const [x, y] = toScreen(c.x, c.y)
          return <rect key={c.id} x={x - 5} y={y - 5} width={10} height={10} className="sky-catalog" />
        })}
        {overlays?.predictions?.map((c) => {
          const [x, y] = toScreen(c.x, c.y)
          if (c.kind === 'no_motion') return <circle key={c.id} cx={x} cy={y} r={6} className="sky-gaia sky-gaia-no_motion" data-kind={c.kind} />
          return (
            <g key={c.id} className={`sky-gaia sky-gaia-${c.kind}`} data-kind={c.kind}>
              <rect x={x - 5} y={y - 5} width={10} height={10} />
              {c.kind === 'saturated' && <path d={`M${x - 5} ${y - 5} L${x + 5} ${y + 5} M${x + 5} ${y - 5} L${x - 5} ${y + 5}`} />}
            </g>
          )
        })}
        {overlays?.vectors?.map((v) => {
          const [x0, y0] = toScreen(v.x0, v.y0)
          const [x1, y1] = toScreen(v.x1, v.y1)
          return <line key={v.id} x1={x0} y1={y0} x2={x1} y2={y1} className="sky-residual-vector" />
        })}
        {overlays?.measured?.map((m) => {
          const [x, y] = toScreen(m.x, m.y)
          return <path key={m.id} d={`M${x - 4} ${y} L${x + 4} ${y} M${x} ${y - 4} L${x} ${y + 4}`} className="sky-measured" />
        })}
        {modelPath && modelPath.length > 1 && (
          <path className="sky-model-path" d={modelPath.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('')} />
        )}
        {overlays?.modelNow && (() => {
          const [x, y] = toScreen(...overlays.modelNow)
          return <circle cx={x} cy={y} r={7} className="sky-model-now" />
        })()}
        {overlays?.truthNow && (() => {
          const [x, y] = toScreen(...overlays.truthNow)
          return (
            <g>
              <path d={`M${x} ${y - 7} L${x + 7} ${y} L${x} ${y + 7} L${x - 7} ${y} Z`} className="sky-truth" />
              <text x={x + 10} y={y + 14} className="sky-truth-label">
                simulation truth
              </text>
            </g>
          )
        })()}
        {hov && (() => {
          const [x, y] = toScreen(hov.x, hov.y)
          return (
            <g>
              <circle cx={x} cy={y} r={9} className="sky-hover" />
              <text x={x + 12} y={y - 9} className="sky-hover-label">
                {hov.label ?? hov.id}
              </text>
            </g>
          )
        })()}
        {sel && (() => {
          const [x, y] = toScreen(sel.x, sel.y)
          return (
            <g data-testid="selected-marker">
              <circle cx={x} cy={y} r={12} className="sky-selected" />
              <line x1={x - 19} x2={x - 14} y1={y} y2={y} className="sky-selected-tick" />
              <line x1={x + 14} x2={x + 19} y1={y} y2={y} className="sky-selected-tick" />
              <line x1={x} x2={x} y1={y - 19} y2={y - 14} className="sky-selected-tick" />
              <line x1={x} x2={x} y1={y + 14} y2={y + 19} className="sky-selected-tick" />
              <text x={x + 16} y={y - 14} className="sky-selected-label">
                {sel.label ?? sel.id}
              </text>
            </g>
          )
        })()}
        {props.marker && (() => {
          const [x, y] = toScreen(props.marker.x, props.marker.y)
          return (
            <g data-testid="query-marker">
              <line x1={x - 16} x2={x - 8} y1={y} y2={y} className="sky-query-tick" />
              <line x1={x + 8} x2={x + 16} y1={y} y2={y} className="sky-query-tick" />
              <line x1={x} x2={x} y1={y - 16} y2={y - 8} className="sky-query-tick" />
              <line x1={x} x2={x} y1={y + 8} y2={y + 16} className="sky-query-tick" />
              {showLabels && (
                <text x={x + 18} y={y - 10} className="sky-query-label">
                  {props.marker.label}
                </text>
              )}
            </g>
          )
        })()}
        <g transform={`translate(${size.w - 46},${46})`} className="sky-compass">
          <line x1={0} y1={0} x2={compass.n[0] * 26} y2={-compass.n[1] * 26} />
          <line x1={0} y1={0} x2={compass.e[0] * 26} y2={-compass.e[1] * 26} />
          <text x={compass.n[0] * 34} y={-compass.n[1] * 34 + 4} textAnchor="middle">
            N
          </text>
          <text x={compass.e[0] * 34} y={-compass.e[1] * 34 + 4} textAnchor="middle">
            E
          </text>
        </g>
        <g transform={`translate(${size.w - 16 - scaleBar.px},${size.h - 16})`} className="sky-scale">
          <line x1={0} x2={scaleBar.px} y1={0} y2={0} />
          <line x1={0} x2={0} y1={-4} y2={4} />
          <line x1={scaleBar.px} x2={scaleBar.px} y1={-4} y2={4} />
          <text x={scaleBar.px / 2} y={-7} textAnchor="middle">
            {scaleBar.arcsec}″
          </text>
        </g>
      </svg>
      <div className="sky-corner sky-corner-tl">{props.cornerTopLeft}</div>
      <div className="sky-corner sky-corner-bl">{props.cornerBottomLeft}</div>
      {cursorSky && (
        <div className="sky-corner sky-corner-readout" aria-hidden>
          {fmtRaHms(cursorSky[0], 2)} {fmtDecDms(cursorSky[1], 1)}
          {cursorValue != null && (
            <span className="faint"> · {Number.isFinite(cursorValue) ? `${cursorValue.toFixed(0)} ${props.valueUnit ?? ''}` : 'no data'} (display)</span>
          )}
        </div>
      )}
      {plane.status === 'loading' && (
        <div className="sky-state" role="status">
          <div className="spinner" aria-hidden /> Loading frame…
        </div>
      )}
      {plane.status === 'error' && (
        <div className="sky-state sky-state-error" role="alert">
          Frame unavailable: {plane.message}
        </div>
      )}
    </div>
  )
}
