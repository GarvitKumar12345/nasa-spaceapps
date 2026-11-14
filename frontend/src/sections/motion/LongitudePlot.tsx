/* View 2 of the orbit experiment: the observer's sky direction to the target
 * (apparent longitude vs time) from apparentLongitudeSeries, retrograde intervals shaded. */
import { useMemo, useState } from 'react'
import { Legend, LinePath, PLOT_COLOR, PlotFrame, PlotTooltip, linear, nearestByX, paddedExtent, useElementWidth } from '../../components/plot'
import { fmt, fmtSigned } from '../../lib/format'
import { apparentLongitudeSeries, lineOfSight, observerState, orbitState, type CircularObserver, type OrbitElements } from '../../physics/kepler'

const R2D = 180 / Math.PI
const BAND = 'rgba(232, 236, 243, 0.08)'
const MARGIN = { top: 24, right: 14, bottom: 38, left: 58 }

export function LongitudePlot({
  orbit,
  observer,
  tDays,
  t0,
  t1,
}: {
  orbit: OrbitElements
  observer: CircularObserver
  tDays: number
  t0: number
  t1: number
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(640)
  const height = width < 480 ? 230 : 260
  const series = useMemo(() => apparentLongitudeSeries(orbit, observer, t0, t1, 721), [orbit, observer, t0, t1])
  const [hover, setHover] = useState<number | null>(null)
  const innerW = Math.max(10, width - MARGIN.left - MARGIN.right)
  const innerH = Math.max(10, height - MARGIN.top - MARGIN.bottom)
  const x = linear([t0, t1], [0, innerW])
  const y = linear(paddedExtent(series.longitudeDeg, 0.08), [innerH, 0])
  const indices = useMemo(() => series.t.map((_, i) => i), [series])

  // Current time: exact state, unwrapped onto the branch of the nearest sample.
  const los = lineOfSight(orbitState(orbit, tDays), observerState(observer, tDays))
  let current: number | null = null
  if (los.defined && series.t.length) {
    let best = 0
    for (let i = 1; i < series.t.length; i++) if (Math.abs(series.t[i] - tDays) < Math.abs(series.t[best] - tDays)) best = i
    const raw = los.longitudeRad * R2D
    current = raw + 360 * Math.round((series.longitudeDeg[best] - raw) / 360)
  }

  if (!series.t.length) {
    return (
      <div className="plot-empty" role="status">
        Undefined geometry for the whole window: target and observer coincide, so there is no viewing direction to plot.
      </div>
    )
  }

  const h = hover !== null ? hover : null
  const n = series.retrograde.length
  const ariaLabel = `Apparent longitude of the target seen by the observer from t = ${fmt(t0, 0)} to ${fmt(t1, 0)} days; ${n} retrograde interval${n === 1 ? '' : 's'} shaded.`
  return (
    <div className="plot-wrap">
      <div ref={ref} style={{ position: 'relative' }}>
        <PlotFrame
          width={width}
          height={height}
          margin={MARGIN}
          x={x}
          y={y}
          xLabel="Simulation time t (days)"
          yLabel="Apparent longitude (deg, unwrapped)"
          xTicks={width < 480 ? 4 : 7}
          yTicks={5}
          xFormat={(v) => String(Math.round(v))}
          yFormat={(v) => String(Math.round(v))}
          ariaLabel={ariaLabel}
          testId="orbit-longitude"
          onPointer={(px) => setHover(nearestByX(indices, px, (i) => x(series.t[i]), 40))}
          onLeave={() => setHover(null)}
          overlay={series.retrograde.map((iv) => {
            const w = x(iv.end) - x(iv.start)
            if (w < 10) return null
            return (
              <text key={`l${iv.start}`} className="ml-band-label" x={x(iv.start) + w / 2} y={-8} textAnchor="middle">
                {w > 64 ? 'retrograde' : 'R'}
              </text>
            )
          })}
        >
          {series.retrograde.map((iv) => (
            <rect key={iv.start} x={x(iv.start)} y={0} width={Math.max(1, x(iv.end) - x(iv.start))} height={innerH} fill={BAND} />
          ))}
          <LinePath xs={series.t} ys={series.longitudeDeg} x={x} y={y} color={PLOT_COLOR.model} dashed />
          <line x1={x(tDays)} x2={x(tDays)} y1={0} y2={innerH} stroke="var(--teal)" strokeWidth={1.5} />
          {current !== null && <circle cx={x(tDays)} cy={y(current)} r={5} fill="var(--teal)" stroke={PLOT_COLOR.surface} strokeWidth={2} />}
          {h !== null && <circle cx={x(series.t[h])} cy={y(series.longitudeDeg[h])} r={4.5} fill="none" stroke="var(--text)" strokeWidth={1.5} />}
        </PlotFrame>
        {h !== null && (
          <PlotTooltip left={x(series.t[h]) + MARGIN.left} top={y(series.longitudeDeg[h]) + MARGIN.top} containerWidth={width}>
            <div>
              <span className="tt-value">{fmt(series.longitudeDeg[h], 2)}°</span> <span className="tt-label">apparent longitude (unwrapped)</span>
            </div>
            <div>
              <span className="tt-value">{fmt(series.t[h], 1)} d</span> <span className="tt-label">simulation time</span>
            </div>
            <div>
              <span className="tt-value">{fmtSigned(series.rateDegPerDay[h], 3)}°/d</span>{' '}
              <span className="tt-label">{series.rateDegPerDay[h] < 0 ? 'retrograde' : 'prograde'}</span>
            </div>
          </PlotTooltip>
        )}
      </div>
      <Legend
        items={[
          { label: 'apparent longitude (model)', kind: 'dashed', color: PLOT_COLOR.model },
          { label: 'retrograde: longitude decreasing', kind: 'band', color: 'rgba(232, 236, 243, 0.16)' },
          { label: 'current time', kind: 'point', color: 'var(--teal)' },
        ]}
      />
      <p className="small muted" data-testid="orbit-retrograde-list">
        {n
          ? `Retrograde in this window: ${series.retrograde.map((iv) => `${fmt(iv.start, 0)}–${fmt(iv.end, 0)} d (${fmt(iv.end - iv.start, 0)} d)`).join('; ')}.`
          : 'No retrograde motion in this window.'}
        {series.undefinedSamples > 0 && ` ${series.undefinedSamples} samples skipped: undefined geometry.`}
      </p>
    </div>
  )
}
