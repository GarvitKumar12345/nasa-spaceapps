/* Nearby-source lesson: apparent sky path from declared source + observer geometry
 * (nearbySource.ts). Equal aspect, east left, axes in mas; no visual magnification. */
import { useMemo } from 'react'
import { Legend, LinePath, PLOT_COLOR, PlotFrame, linear, paddedExtent, skyPlaneScales, useElementWidth, type LegendKind } from '../../components/plot'
import { nearbyComponents, nearbyOffsetMas, nearbyPath, type NearbyParams } from '../../physics/nearbySource'

const MARGIN = { top: 14, right: 16, bottom: 40, left: 64 }
const NEUTRAL = 'var(--text-2)'

export function NearbySkyPath({ params, spanYr, tYr }: { params: NearbyParams; spanYr: number; tYr: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(620)
  const height = Math.round(Math.min(460, Math.max(300, width * 0.62)))
  const n = Math.max(60, Math.round(spanYr * 120))
  const geo = useMemo(() => {
    const total = nearbyPath(params, 0, spanYr, n)
    const comps = nearbyComponents(params, 0, spanYr, n)
    const months = Array.from({ length: Math.floor(spanYr * 12) + 1 }, (_, k) => nearbyOffsetMas(params, k / 12))
    return { total, comps, months }
  }, [params, spanYr, n])
  const now = nearbyOffsetMas(params, tYr)
  const innerW = width - MARGIN.left - MARGIN.right
  const innerH = height - MARGIN.top - MARGIN.bottom
  const showPm = params.properMotion && params.parallax
  const allE = [...geo.total.east, ...(showPm ? [...geo.comps.properMotionOnly.east, ...geo.comps.parallaxOnly.east] : []), 0]
  const allN = [...geo.total.north, ...(showPm ? [...geo.comps.properMotionOnly.north, ...geo.comps.parallaxOnly.north] : []), 0]
  const sc = skyPlaneScales(allE, allN, innerW, innerH, 0.12)
  const legend: { label: string; kind: LegendKind; color: string }[] = [
    { label: 'Apparent path (model)', kind: 'dashed', color: PLOT_COLOR.model },
    { label: 'Position now', kind: 'point', color: 'var(--teal)' },
  ]
  if (showPm) {
    legend.push({ label: 'Proper motion only', kind: 'line', color: NEUTRAL })
    legend.push({ label: 'Parallax only', kind: 'hollow', color: NEUTRAL })
  }
  return (
    <div ref={ref} className="plot-wrap ml-sky-path" data-testid="nearby-sky-path">
      <Legend items={legend} />
      <PlotFrame
        width={width}
        height={height}
        margin={MARGIN}
        x={sc.x}
        y={sc.y}
        xLabel="East offset (mas)  ← east"
        yLabel="North offset (mas)"
        ariaLabel={`Apparent sky path over ${spanYr} years; current offset ${now.east.toFixed(1)} mas east, ${now.north.toFixed(1)} mas north`}
      >
        {showPm && (
          <>
            <LinePath xs={geo.comps.properMotionOnly.east} ys={geo.comps.properMotionOnly.north} x={sc.x} y={sc.y} color={NEUTRAL} width={1.25} opacity={0.6} />
            <LinePath xs={geo.comps.parallaxOnly.east} ys={geo.comps.parallaxOnly.north} x={sc.x} y={sc.y} color={NEUTRAL} width={1.25} opacity={0.45} />
          </>
        )}
        <LinePath xs={geo.total.east} ys={geo.total.north} x={sc.x} y={sc.y} color={PLOT_COLOR.model} dashed />
        {geo.months.map((m, k) => (
          <circle key={k} cx={sc.x(m.east)} cy={sc.y(m.north)} r={k % 12 === 0 ? 3.2 : 2} fill={k % 12 === 0 ? 'var(--text)' : 'var(--text-2)'} opacity={0.85} />
        ))}
        <circle cx={sc.x(0)} cy={sc.y(0)} r={3} fill="none" stroke="var(--text-2)" strokeWidth={1} />
        <circle cx={sc.x(now.east)} cy={sc.y(now.north)} r={6} fill="var(--teal)" stroke="var(--panel)" strokeWidth={2} data-testid="nearby-now" />
      </PlotFrame>
      <p className="small faint">
        Dots: monthly positions (larger = whole years from the model epoch). Ring: reference direction at t = 0. Equal aspect: {sc.masPerPx.toFixed(2)} mas per screen pixel; no visual
        magnification.
      </p>
    </div>
  )
}

/** Offset vs time, one small multiple per axis (single series each: no legend needed). */
export function NearbyOffsetTime({ params, spanYr, tYr, axis }: { params: NearbyParams; spanYr: number; tYr: number; axis: 'east' | 'north' }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(300)
  const height = 170
  const margin = { top: 10, right: 10, bottom: 32, left: 56 }
  const path = useMemo(() => nearbyPath(params, 0, spanYr, Math.max(60, Math.round(spanYr * 120))), [params, spanYr])
  const vals = axis === 'east' ? path.east : path.north
  const x = linear([0, spanYr], [0, width - margin.left - margin.right])
  const y = linear(paddedExtent(vals, 0.1), [height - margin.top - margin.bottom, 0])
  const now = nearbyOffsetMas(params, tYr)
  return (
    <div ref={ref} className="plot-wrap">
      <h3 className="plot-title">{axis === 'east' ? 'East offset vs time' : 'North offset vs time'}</h3>
      <PlotFrame
        width={width}
        height={height}
        margin={margin}
        x={x}
        y={y}
        xLabel="Julian years from model epoch"
        yLabel="mas"
        xFormat={(v) => v.toFixed(1)}
        ariaLabel={`${axis} offset in mas versus time`}
      >
        <LinePath xs={path.t} ys={vals} x={x} y={y} color={PLOT_COLOR.model} dashed />
        <line x1={x(tYr)} x2={x(tYr)} y1={0} y2={height} stroke="var(--line-strong)" />
        <circle cx={x(tYr)} cy={y(axis === 'east' ? now.east : now.north)} r={4.5} fill="var(--teal)" stroke="var(--panel)" strokeWidth={2} />
      </PlotFrame>
    </div>
  )
}
