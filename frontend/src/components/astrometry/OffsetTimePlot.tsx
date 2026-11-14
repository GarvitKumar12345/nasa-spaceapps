/* Offset-versus-time panels (east and north separately; never a dual axis) with a
 * residual panel beneath each. Points: derived measurements +/- 1 sigma.
 * Curve + band: model prediction +/- 1 sigma from the fit covariance. */
import { useMemo, useState } from 'react'
import type { ModelFit, SourceMeasurement, TruthPosition } from '../../api/contracts.gen'
import { fmtDate, fmtPm, mjdTdbToJyear } from '../../lib/format'
import { offsetsMas } from '../../lib/tangent'
import {
  BandArea,
  DEFAULT_MARGIN,
  ErrorBarPoints,
  Legend,
  LinePath,
  PLOT_COLOR,
  PlotFrame,
  PlotTooltip,
  linear,
  nearestByX,
  paddedExtent,
  useElementWidth,
  type LegendKind,
} from '../plot'
import { measuredOffsets, tangentPointFor, type MeasuredOffset } from './common'

type Axis = 'east' | 'north'

export interface OffsetTimePlotProps {
  axis: Axis
  measurements: SourceMeasurement[]
  excludedIds?: ReadonlySet<string>
  fit?: ModelFit | null
  fitStale?: boolean
  truth?: TruthPosition[] | null
  height?: number
  residualHeight?: number
}

const AXIS_LABEL: Record<Axis, string> = { east: 'Δα·cosδ (mas)', north: 'Δδ (mas)' }
const AXIS_TITLE: Record<Axis, string> = { east: 'East offset vs time', north: 'North offset vs time' }

export function OffsetTimePlot({
  axis,
  measurements,
  excludedIds = new Set(),
  fit,
  fitStale = false,
  truth,
  height = 210,
  residualHeight = 120,
}: OffsetTimePlotProps) {
  const [wrapRef, width] = useElementWidth<HTMLDivElement>(420)
  const [hover, setHover] = useState<MeasuredOffset | null>(null)
  const margin = { ...DEFAULT_MARGIN, bottom: 30 }
  const rMargin = { ...DEFAULT_MARGIN, top: 6 }
  const innerW = width - margin.left - margin.right

  const data = useMemo(() => {
    const tp = tangentPointFor(measurements, fit)
    if (!tp) return null
    const pts = measuredOffsets(measurements, tp, excludedIds)
    const val = (p: MeasuredOffset) => (axis === 'east' ? p.east : p.north)
    const sig = (p: MeasuredOffset) => (axis === 'east' ? p.sigmaEast : p.sigmaNorth)
    const curve = fit?.prediction ?? null
    const ct = curve ? curve.t_mjd_tdb.map(mjdTdbToJyear) : []
    const cv = curve ? (axis === 'east' ? curve.ra_cosdec_offset_mas : curve.dec_offset_mas) : []
    const cs = curve ? (axis === 'east' ? curve.sigma_ra_cosdec_mas : curve.sigma_dec_mas) : null
    const truthPts = (truth ?? []).flatMap((t) => {
      const m = measurements.find((mm) => mm.frame_id === t.frame_id)
      if (!m) return []
      const [e, n] = offsetsMas(t.ra_deg, t.dec_deg, tp.ra_deg, tp.dec_deg)
      return [{ key: `truth-${t.frame_id}`, x: mjdTdbToJyear(m.epoch.mjd_tdb), y: axis === 'east' ? e : n }]
    })
    const tAll = [...pts.map((p) => p.jyear), ...ct]
    const vAll = [
      ...pts.flatMap((p) => [val(p) - (sig(p) ?? 0), val(p) + (sig(p) ?? 0)]),
      ...cv,
      ...truthPts.map((p) => p.y),
    ]
    const residuals = new Map((fit?.residuals ?? []).map((r) => [r.measurement_id, r]))
    return { tp, pts, val, sig, ct, cv, cs, truthPts, tAll, vAll, residuals }
  }, [measurements, excludedIds, fit, truth, axis])

  if (!data || data.pts.length === 0) return <div className="plot-empty">No measured positions to plot.</div>
  const { pts, val, sig, ct, cv, cs, truthPts, tAll, vAll, residuals } = data

  const x = linear(paddedExtent(tAll, 0.04), [0, innerW])
  const y = linear(paddedExtent(vAll, 0.08), [height - margin.top - margin.bottom, 0])

  const resid = pts.flatMap((p) => {
    const r = residuals.get(p.id)
    if (!r) return []
    const d = axis === 'east' ? r.d_ra_cosdec_mas : r.d_dec_mas
    const s = axis === 'east' ? r.sigma_ra_cosdec_mas : r.sigma_dec_mas
    return [{ key: p.id, x: p.jyear, y: d, yerr: s, excluded: !r.included }]
  })
  const ry = linear(paddedExtent([0, ...resid.flatMap((r) => [r.y - r.yerr, r.y + r.yerr])], 0.12), [residualHeight - rMargin.top - rMargin.bottom, 0])

  const legend: { label: string; kind: LegendKind; color: string }[] = [{ label: 'Measured, 1σ', kind: 'point', color: PLOT_COLOR.measured }]
  if (pts.some((p) => p.excluded)) legend.push({ label: 'Excluded', kind: 'hollow', color: PLOT_COLOR.excluded })
  if (ct.length) {
    legend.push({ label: fitStale ? 'Model (stale)' : 'Model prediction', kind: 'dashed', color: PLOT_COLOR.model })
    if (cs) legend.push({ label: 'Model ±1σ', kind: 'band', color: PLOT_COLOR.band })
  }
  if (truthPts.length) legend.push({ label: 'Simulation truth', kind: 'diamond', color: PLOT_COLOR.truth })

  const hr = hover ? residuals.get(hover.id) : undefined
  return (
    <div className="plot-wrap" ref={wrapRef}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3 className="plot-title">{AXIS_TITLE[axis]}</h3>
        <Legend items={legend} />
      </div>
      <div style={{ position: 'relative' }}>
        <PlotFrame
          width={width}
          height={height}
          margin={margin}
          x={x}
          y={y}
          yLabel={AXIS_LABEL[axis]}
          xFormat={(v) => v.toFixed(1)}
          ariaLabel={`${AXIS_TITLE[axis]}: ${pts.length} measurements${ct.length ? ' and model prediction' : ''}`}
          onPointer={(px) => setHover(nearestByX(pts, px, (p) => x(p.jyear)))}
          onLeave={() => setHover(null)}
        >
          {cs && cs.length === ct.length && (
            <BandArea xs={ct} lo={cv.map((v, i) => v - cs[i])} hi={cv.map((v, i) => v + cs[i])} x={x} y={y} />
          )}
          {ct.length > 0 && <LinePath xs={ct} ys={cv} x={x} y={y} color={PLOT_COLOR.model} dashed opacity={fitStale ? 0.45 : 1} />}
          {truthPts.length > 0 && <ErrorBarPoints points={truthPts} x={x} y={y} color={PLOT_COLOR.truth} kind="diamond" />}
          <ErrorBarPoints
            points={pts.filter((p) => p.excluded).map((p) => ({ key: p.id, x: p.jyear, y: val(p), yerr: sig(p) }))}
            x={x}
            y={y}
            color={PLOT_COLOR.excluded}
            kind="hollow"
          />
          <ErrorBarPoints
            points={pts.filter((p) => !p.excluded).map((p) => ({ key: p.id, x: p.jyear, y: val(p), yerr: sig(p) }))}
            x={x}
            y={y}
            color={PLOT_COLOR.measured}
            highlightKey={hover?.id}
          />
          {hover && <line x1={x(hover.jyear)} x2={x(hover.jyear)} y1={0} y2={height} stroke="var(--line-strong)" />}
        </PlotFrame>
        {hover && (
          <PlotTooltip left={margin.left + x(hover.jyear)} top={margin.top + y(val(hover))} containerWidth={width}>
            <div className="tt-value">{fmtPm(val(hover), sig(hover), 'mas')}</div>
            <div className="tt-label">
              {fmtDate(hover.isoUtc)} · {hover.bandId}
            </div>
            {hr && (
              <div className="tt-label">
                residual {(axis === 'east' ? hr.d_ra_cosdec_mas : hr.d_dec_mas).toFixed(1)} mas ({(axis === 'east' ? hr.normalized_ra : hr.normalized_dec).toFixed(2)}σ)
              </div>
            )}
          </PlotTooltip>
        )}
      </div>
      {resid.length > 0 ? (
        <PlotFrame
          width={width}
          height={residualHeight}
          margin={rMargin}
          x={x}
          y={ry}
          xLabel="Epoch (Julian year, TDB)"
          yLabel="Residual (mas)"
          xFormat={(v) => v.toFixed(1)}
          zeroLineY
          ariaLabel={`${AXIS_TITLE[axis]} residuals: data minus model`}
        >
          <ErrorBarPoints
            points={resid.filter((r) => r.excluded).map((r) => ({ key: r.key, x: r.x, y: r.y, yerr: r.yerr }))}
            x={x}
            y={ry}
            color={PLOT_COLOR.excluded}
            kind="hollow"
          />
          <ErrorBarPoints
            points={resid.filter((r) => !r.excluded).map((r) => ({ key: r.key, x: r.x, y: r.y, yerr: r.yerr }))}
            x={x}
            y={ry}
            color={PLOT_COLOR.measured}
            highlightKey={hover?.id}
          />
        </PlotFrame>
      ) : (
        <div className="plot-empty small">Residuals appear after a fit (data − model).</div>
      )}
    </div>
  )
}

export function OffsetTimePlots(props: Omit<OffsetTimePlotProps, 'axis'>) {
  return (
    <div className="offset-time-grid">
      <OffsetTimePlot axis="east" {...props} />
      <OffsetTimePlot axis="north" {...props} />
    </div>
  )
}
