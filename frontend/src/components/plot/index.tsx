/* Plot primitives for scientific plots rendered from real arrays.
 * Specs (dataviz skill): 2px lines, markers r>=4 with a 2px surface ring, solid
 * hairline grid, ~10% bands, legend for >=2 series, nearest-point tooltips with
 * >=24px hit areas. Dashed strokes are reserved for model predictions. */
import { useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { scaleLinear, type ScaleLinear } from 'd3-scale'

export const PLOT_COLOR = {
  measured: 'var(--plot-measured)',
  model: 'var(--plot-model)',
  truth: 'var(--plot-truth)',
  excluded: 'var(--plot-excluded)',
  band: 'var(--plot-band)',
  catalog: 'var(--plot-catalog)',
  surface: 'var(--panel)',
} as const

export type Scale = ScaleLinear<number, number>

export interface Margin {
  top: number
  right: number
  bottom: number
  left: number
}

export const DEFAULT_MARGIN: Margin = { top: 12, right: 14, bottom: 38, left: 56 }

/** Width of an element, tracked with ResizeObserver. */
export function useElementWidth<T extends HTMLElement>(fallback = 480): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setWidth(Math.max(160, Math.floor(el.getBoundingClientRect().width)))
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

/** Padded [min, max] of finite values; never zero-width. */
export function paddedExtent(values: number[], pad = 0.08, minSpan = 1e-9): [number, number] {
  const finite = values.filter((v) => Number.isFinite(v))
  if (!finite.length) return [0, 1]
  let lo = Math.min(...finite)
  let hi = Math.max(...finite)
  let span = hi - lo
  if (span < minSpan) {
    const c = (lo + hi) / 2
    const half = Math.max(Math.abs(c) * 0.05, minSpan, 1)
    lo = c - half
    hi = c + half
    span = hi - lo
  }
  return [lo - span * pad, hi + span * pad]
}

export function linear(domain: [number, number], range: [number, number]): Scale {
  return scaleLinear().domain(domain).range(range)
}

/**
 * Equal-aspect scales for sky-plane plots: the same mas per screen pixel on both
 * axes, with east increasing to the left (sky convention, north up).
 */
export function skyPlaneScales(
  east: number[],
  north: number[],
  innerWidth: number,
  innerHeight: number,
  pad = 0.1,
): { x: Scale; y: Scale; masPerPx: number } {
  const [e0, e1] = paddedExtent(east, pad)
  const [n0, n1] = paddedExtent(north, pad)
  const masPerPx = Math.max((e1 - e0) / innerWidth, (n1 - n0) / innerHeight)
  const ec = (e0 + e1) / 2
  const nc = (n0 + n1) / 2
  const halfE = (masPerPx * innerWidth) / 2
  const halfN = (masPerPx * innerHeight) / 2
  return {
    x: linear([ec + halfE, ec - halfE], [0, innerWidth]), // east to the left
    y: linear([nc - halfN, nc + halfN], [innerHeight, 0]),
    masPerPx,
  }
}

export interface PlotFrameProps {
  width: number
  height: number
  margin?: Margin
  x: Scale
  y: Scale
  xLabel?: string
  yLabel?: string
  xTicks?: number
  yTicks?: number
  xFormat?: (v: number) => string
  yFormat?: (v: number) => string
  ariaLabel: string
  zeroLineY?: boolean
  children?: ReactNode
  overlay?: ReactNode
  onPointer?: (px: number, py: number) => void
  onLeave?: () => void
  testId?: string
}

const defaultFormat = (v: number) => {
  const a = Math.abs(v)
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(1)
  return Number(v.toPrecision(6)).toString()
}

/** Axes + solid hairline grid + clipped data area. Children draw in inner coordinates. */
export function PlotFrame({
  width,
  height,
  margin = DEFAULT_MARGIN,
  x,
  y,
  xLabel,
  yLabel,
  xTicks = 6,
  yTicks = 5,
  xFormat = defaultFormat,
  yFormat = defaultFormat,
  ariaLabel,
  zeroLineY = false,
  children,
  overlay,
  onPointer,
  onLeave,
  testId,
}: PlotFrameProps) {
  const innerW = Math.max(10, width - margin.left - margin.right)
  const innerH = Math.max(10, height - margin.top - margin.bottom)
  const clipId = `clip-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const xt = x.ticks(xTicks)
  const yt = y.ticks(yTicks)
  return (
    <svg
      className="plot"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel}
      data-testid={testId}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={innerW} height={innerH} />
        </clipPath>
      </defs>
      <g transform={`translate(${margin.left},${margin.top})`}>
        {yt.map((t) => (
          <line key={`gy${t}`} className="gridline" x1={0} x2={innerW} y1={y(t)} y2={y(t)} />
        ))}
        {xt.map((t) => (
          <line key={`gx${t}`} className="gridline" x1={x(t)} x2={x(t)} y1={0} y2={innerH} />
        ))}
        {zeroLineY && y.domain()[0] < 0 && y.domain()[1] > 0 && (
          <line className="zero-line" x1={0} x2={innerW} y1={y(0)} y2={y(0)} />
        )}
        <g className="axis">
          <line x1={0} x2={innerW} y1={innerH} y2={innerH} />
          <line x1={0} x2={0} y1={0} y2={innerH} />
        </g>
        {xt.map((t) => (
          <g key={`tx${t}`} className="tick" transform={`translate(${x(t)},${innerH})`}>
            <line y2={4} stroke="var(--line-strong)" />
            <text y={16} textAnchor="middle">
              {xFormat(t)}
            </text>
          </g>
        ))}
        {yt.map((t) => (
          <g key={`ty${t}`} className="tick" transform={`translate(0,${y(t)})`}>
            <line x2={-4} stroke="var(--line-strong)" />
            <text x={-7} dy="0.32em" textAnchor="end">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {xLabel && (
          <text className="axis-label" x={innerW / 2} y={innerH + 32} textAnchor="middle">
            {xLabel}
          </text>
        )}
        {yLabel && (
          <text
            className="axis-label"
            transform={`translate(${-margin.left + 13},${innerH / 2}) rotate(-90)`}
            textAnchor="middle"
          >
            {yLabel}
          </text>
        )}
        <g clipPath={`url(#${clipId})`}>{children}</g>
        {overlay}
        {onPointer && (
          <rect
            x={0}
            y={0}
            width={innerW}
            height={innerH}
            fill="transparent"
            onPointerMove={(e) => {
              const box = (e.currentTarget as SVGRectElement).getBoundingClientRect()
              onPointer(e.clientX - box.left, e.clientY - box.top)
            }}
            onPointerLeave={onLeave}
          />
        )}
      </g>
    </svg>
  )
}

export interface ErrPoint {
  key: string
  x: number
  y: number
  xerr?: number | null
  yerr?: number | null
}

/** Points with 1-sigma error bars. kind controls the marker shape. */
export function ErrorBarPoints({
  points,
  x,
  y,
  color,
  kind = 'filled',
  highlightKey,
}: {
  points: ErrPoint[]
  x: Scale
  y: Scale
  color: string
  kind?: 'filled' | 'hollow' | 'diamond'
  highlightKey?: string | null
}) {
  return (
    <g>
      {points.map((p) => {
        const cx = x(p.x)
        const cy = y(p.y)
        const hi = p.key === highlightKey
        return (
          <g key={p.key}>
            {p.xerr != null && p.xerr > 0 && (
              <line x1={x(p.x - p.xerr)} x2={x(p.x + p.xerr)} y1={cy} y2={cy} stroke={color} strokeWidth={1.25} />
            )}
            {p.yerr != null && p.yerr > 0 && (
              <line x1={cx} x2={cx} y1={y(p.y - p.yerr)} y2={y(p.y + p.yerr)} stroke={color} strokeWidth={1.25} />
            )}
            {kind === 'diamond' ? (
              <path
                d={`M${cx} ${cy - 5.5} L${cx + 5.5} ${cy} L${cx} ${cy + 5.5} L${cx - 5.5} ${cy} Z`}
                fill={PLOT_COLOR.surface}
                stroke={color}
                strokeWidth={1.75}
              />
            ) : (
              <circle
                cx={cx}
                cy={cy}
                r={hi ? 5.5 : 4.25}
                fill={kind === 'hollow' ? PLOT_COLOR.surface : color}
                stroke={kind === 'hollow' ? color : PLOT_COLOR.surface}
                strokeWidth={2}
              />
            )}
          </g>
        )
      })}
    </g>
  )
}

export function LinePath({
  xs,
  ys,
  x,
  y,
  color,
  dashed = false,
  width = 2,
  opacity = 1,
}: {
  xs: number[]
  ys: number[]
  x: Scale
  y: Scale
  color: string
  dashed?: boolean
  width?: number
  opacity?: number
}) {
  if (xs.length < 2) return null
  let d = ''
  for (let i = 0; i < xs.length; i++) {
    if (!Number.isFinite(xs[i]) || !Number.isFinite(ys[i])) continue
    d += `${d ? 'L' : 'M'}${x(xs[i]).toFixed(2)},${y(ys[i]).toFixed(2)}`
  }
  return (
    <path
      d={d}
      fill="none"
      stroke={color}
      strokeWidth={width}
      strokeLinejoin="round"
      strokeLinecap="round"
      strokeDasharray={dashed ? '6 4' : undefined}
      opacity={opacity}
    />
  )
}

export function BandArea({ xs, lo, hi, x, y, color = PLOT_COLOR.band }: { xs: number[]; lo: number[]; hi: number[]; x: Scale; y: Scale; color?: string }) {
  if (xs.length < 2) return null
  let d = ''
  for (let i = 0; i < xs.length; i++) d += `${i ? 'L' : 'M'}${x(xs[i]).toFixed(2)},${y(hi[i]).toFixed(2)}`
  for (let i = xs.length - 1; i >= 0; i--) d += `L${x(xs[i]).toFixed(2)},${y(lo[i]).toFixed(2)}`
  return <path d={`${d}Z`} fill={color} stroke="none" />
}

export type LegendKind = 'point' | 'hollow' | 'line' | 'dashed' | 'diamond' | 'band' | 'square'

export function Legend({ items }: { items: { label: string; kind: LegendKind; color: string }[] }) {
  return (
    <div className="legend" aria-hidden="false">
      {items.map((it) => (
        <span key={it.label} className="legend-item">
          <svg width={18} height={10} aria-hidden>
            {it.kind === 'point' && <circle cx={9} cy={5} r={4} fill={it.color} />}
            {it.kind === 'hollow' && <circle cx={9} cy={5} r={3.5} fill="none" stroke={it.color} strokeWidth={1.5} />}
            {it.kind === 'line' && <line x1={1} x2={17} y1={5} y2={5} stroke={it.color} strokeWidth={2} />}
            {it.kind === 'dashed' && <line x1={1} x2={17} y1={5} y2={5} stroke={it.color} strokeWidth={2} strokeDasharray="5 3" />}
            {it.kind === 'diamond' && <path d="M9 0.8 L13.2 5 L9 9.2 L4.8 5 Z" fill="none" stroke={it.color} strokeWidth={1.5} />}
            {it.kind === 'band' && <rect x={1} y={1} width={16} height={8} fill={it.color} />}
            {it.kind === 'square' && <rect x={5} y={1} width={8} height={8} fill="none" stroke={it.color} strokeWidth={1.5} />}
          </svg>
          {it.label}
        </span>
      ))}
    </div>
  )
}

/** Tooltip positioned inside a `position: relative` wrapper. Values lead, labels follow. */
export function PlotTooltip({ left, top, containerWidth, children }: { left: number; top: number; containerWidth: number; children: ReactNode }) {
  const w = 230
  const flip = left + w + 16 > containerWidth
  return (
    <div
      className="plot-tooltip"
      role="status"
      style={{ left: flip ? Math.max(4, left - w - 12) : left + 12, top: Math.max(4, top - 8), width: w }}
    >
      {children}
    </div>
  )
}

/** Nearest point within `maxPx` screen pixels. */
export function nearestPoint<T>(items: T[], px: number, py: number, sx: (t: T) => number, sy: (t: T) => number, maxPx = 24): T | null {
  let best: T | null = null
  let bestD = maxPx * maxPx
  for (const it of items) {
    const dx = sx(it) - px
    const dy = sy(it) - py
    const d = dx * dx + dy * dy
    if (d <= bestD) {
      bestD = d
      best = it
    }
  }
  return best
}

/** Nearest item by x only (crosshair snapping). */
export function nearestByX<T>(items: T[], px: number, sx: (t: T) => number, maxPx = 40): T | null {
  let best: T | null = null
  let bestD = maxPx
  for (const it of items) {
    const d = Math.abs(sx(it) - px)
    if (d <= bestD) {
      bestD = d
      best = it
    }
  }
  return best
}
