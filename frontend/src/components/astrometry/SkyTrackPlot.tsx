/* Sky-plane track: measured positions (derived measurements) with 1-sigma error
 * bars, the fitted model path (model prediction), and optional simulation truth.
 * Equal aspect (mas per pixel identical on both axes), north up, east left. */
import { useMemo, useState } from 'react'
import type { ModelFit, SourceMeasurement, TruthPosition } from '../../api/contracts.gen'
import { fmtDate, fmtPm } from '../../lib/format'
import { offsetsMas } from '../../lib/tangent'
import {
  DEFAULT_MARGIN,
  ErrorBarPoints,
  Legend,
  LinePath,
  PLOT_COLOR,
  PlotFrame,
  PlotTooltip,
  nearestPoint,
  skyPlaneScales,
  useElementWidth,
  type LegendKind,
} from '../plot'
import { measuredOffsets, tangentPointFor, type MeasuredOffset } from './common'

export interface SkyTrackPlotProps {
  measurements: SourceMeasurement[]
  excludedIds?: ReadonlySet<string>
  fit?: ModelFit | null
  fitStale?: boolean
  truth?: TruthPosition[] | null
  height?: number
  testId?: string
}

export function SkyTrackPlot({ measurements, excludedIds = new Set(), fit, fitStale = false, truth, height = 320, testId }: SkyTrackPlotProps) {
  const [wrapRef, width] = useElementWidth<HTMLDivElement>(520)
  const [hover, setHover] = useState<MeasuredOffset | null>(null)
  const margin = { ...DEFAULT_MARGIN, left: 62 }
  const innerW = width - margin.left - margin.right
  const innerH = height - margin.top - margin.bottom

  const model = useMemo(() => {
    const tp = tangentPointFor(measurements, fit)
    if (!tp) return null
    const pts = measuredOffsets(measurements, tp, excludedIds)
    const curve = fit?.prediction ?? null
    const truthPts = (truth ?? []).map((t) => {
      const [e, n] = offsetsMas(t.ra_deg, t.dec_deg, tp.ra_deg, tp.dec_deg)
      return { key: `truth-${t.frame_id}`, x: e, y: n }
    })
    const allE = [...pts.map((p) => p.east), ...(curve?.ra_cosdec_offset_mas ?? []), ...truthPts.map((p) => p.x)]
    const allN = [...pts.map((p) => p.north), ...(curve?.dec_offset_mas ?? []), ...truthPts.map((p) => p.y)]
    const scales = skyPlaneScales(allE, allN, innerW, innerH)
    return { tp, pts, curve, truthPts, scales }
  }, [measurements, excludedIds, fit, truth, innerW, innerH])

  if (!model || model.pts.length === 0) {
    return (
      <div className="plot-empty" data-testid={testId}>
        No measured positions to plot.
      </div>
    )
  }
  const { tp, pts, curve, truthPts, scales } = model
  const included = pts.filter((p) => !p.excluded)
  const excluded = pts.filter((p) => p.excluded)
  const residualById = new Map((fit?.residuals ?? []).map((r) => [r.measurement_id, r]))

  const legend: { label: string; kind: LegendKind; color: string }[] = [
    { label: 'Measured (derived), 1σ', kind: 'point', color: PLOT_COLOR.measured },
  ]
  if (excluded.length) legend.push({ label: 'Excluded from fit', kind: 'hollow', color: PLOT_COLOR.excluded })
  if (curve) legend.push({ label: fitStale ? 'Model prediction (stale)' : 'Model prediction', kind: 'dashed', color: PLOT_COLOR.model })
  if (truthPts.length) legend.push({ label: 'Simulation truth', kind: 'diamond', color: PLOT_COLOR.truth })

  const onPointer = (px: number, py: number) =>
    setHover(nearestPoint(pts, px, py, (p) => scales.x(p.east), (p) => scales.y(p.north)))

  return (
    <div className="plot-wrap" ref={wrapRef} data-testid={testId}>
      <Legend items={legend} />
      <div style={{ position: 'relative' }}>
        <PlotFrame
          width={width}
          height={height}
          margin={margin}
          x={scales.x}
          y={scales.y}
          xLabel="East offset Δα·cosδ (mas)  ← east"
          yLabel="North offset Δδ (mas)"
          ariaLabel={`Sky-plane track of ${pts.length} measured positions${curve ? ' with model prediction' : ''}`}
          onPointer={onPointer}
          onLeave={() => setHover(null)}
        >
          {curve && (
            <LinePath
              xs={curve.ra_cosdec_offset_mas}
              ys={curve.dec_offset_mas}
              x={scales.x}
              y={scales.y}
              color={PLOT_COLOR.model}
              dashed
              opacity={fitStale ? 0.45 : 1}
            />
          )}
          {truthPts.length > 0 && <ErrorBarPoints points={truthPts} x={scales.x} y={scales.y} color={PLOT_COLOR.truth} kind="diamond" />}
          <ErrorBarPoints
            points={excluded.map((p) => ({ key: p.id, x: p.east, y: p.north, xerr: p.sigmaEast, yerr: p.sigmaNorth }))}
            x={scales.x}
            y={scales.y}
            color={PLOT_COLOR.excluded}
            kind="hollow"
          />
          <ErrorBarPoints
            points={included.map((p) => ({ key: p.id, x: p.east, y: p.north, xerr: p.sigmaEast, yerr: p.sigmaNorth }))}
            x={scales.x}
            y={scales.y}
            color={PLOT_COLOR.measured}
            highlightKey={hover?.id}
          />
        </PlotFrame>
        {hover && (
          <PlotTooltip left={margin.left + scales.x(hover.east)} top={margin.top + scales.y(hover.north)} containerWidth={width}>
            <div className="tt-value">
              {fmtPm(hover.east, hover.sigmaEast)} E, {fmtPm(hover.north, hover.sigmaNorth)} N mas
            </div>
            <div className="tt-label">
              {fmtDate(hover.isoUtc)} · {hover.bandId} · {hover.excluded ? 'excluded' : 'derived measurement'}
            </div>
            {residualById.get(hover.id) && (
              <div className="tt-label">
                residual {residualById.get(hover.id)!.d_ra_cosdec_mas.toFixed(1)} E, {residualById.get(hover.id)!.d_dec_mas.toFixed(1)} N mas
              </div>
            )}
          </PlotTooltip>
        )}
      </div>
      <p className="small faint plot-caption">
        Tangent point RA {tp.ra_deg.toFixed(6)}°, Dec {tp.dec_deg.toFixed(6)}° ({tp.source === 'fit_reference' ? 'fit reference position' : 'mean of measurements'}). Equal
        aspect: {scales.masPerPx.toFixed(2)} mas per screen pixel.
      </p>
    </div>
  )
}
