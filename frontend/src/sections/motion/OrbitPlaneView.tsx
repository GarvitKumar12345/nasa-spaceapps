/* View 1 of the orbit experiment: the orbital plane seen from above (coplanar orbits).
 * Every mark is computed from kepler.ts at absolute simulation time; equal aspect (AU). */
import { useId, useMemo } from 'react'
import { useElementWidth } from '../../components/plot'
import { fmt } from '../../lib/format'
import { equalTimeMarkers, lineOfSight, observerState, orbitState, type CircularObserver, type OrbitElements } from '../../physics/kepler'

const NICE_AU = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100]
const R2D = 180 / Math.PI

/** Label anchor placed `dist` px from (px, py), pointing away from (cx, cy). */
function awayFrom(px: number, py: number, cx: number, cy: number, dist: number) {
  let dx = px - cx
  let dy = py - cy
  const len = Math.hypot(dx, dy)
  if (len < 1e-6) {
    dx = 1
    dy = -1
  } else {
    dx /= len
    dy /= len
  }
  const anchor: 'start' | 'end' | 'middle' = dx > 0.35 ? 'start' : dx < -0.35 ? 'end' : 'middle'
  return { x: px + dx * dist, y: py + dy * dist + (dy > 0.35 ? 8 : dy < -0.35 ? -2 : 4), anchor }
}

export function OrbitPlaneView({
  orbit,
  observer,
  tDays,
  periodDays,
}: {
  orbit: OrbitElements
  observer: CircularObserver
  tDays: number
  periodDays: number
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>(640)
  const height = Math.round(Math.min(500, Math.max(280, width * 0.6)))
  const arrowId = `ml-arrow-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const narrow = width < 520

  const ellipse = useMemo(() => Array.from({ length: 361 }, (_, k) => orbitState(orbit, orbit.t0Days + (k * periodDays) / 360)), [orbit, periodDays])
  const markers = useMemo(() => equalTimeMarkers(orbit, 12), [orbit])
  const wedge = useMemo(() => Array.from({ length: 61 }, (_, k) => orbitState(orbit, tDays + (k * periodDays) / 12 / 60)), [orbit, tDays, periodDays])
  const target = orbitState(orbit, tDays)
  const obs = observerState(observer, tDays)
  const los = lineOfSight(target, obs)

  // World extent in AU: target ellipse, observer circle and the Sun; equal aspect.
  let xmin = -observer.radiusAu
  let xmax = observer.radiusAu
  let ymin = -observer.radiusAu
  let ymax = observer.radiusAu
  for (const s of ellipse) {
    xmin = Math.min(xmin, s.x)
    xmax = Math.max(xmax, s.x)
    ymin = Math.min(ymin, s.y)
    ymax = Math.max(ymax, s.y)
  }
  const pad = narrow ? 18 : 26
  const scale = Math.min((width - 2 * pad) / (xmax - xmin), (height - 2 * pad - 18) / (ymax - ymin))
  const ox = width / 2 - (scale * (xmin + xmax)) / 2
  const oy = (height - 18) / 2 + (scale * (ymin + ymax)) / 2
  const X = (x: number) => ox + x * scale
  const Y = (y: number) => oy - y * scale
  const toPath = (pts: { x: number; y: number }[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join('')

  const sunX = X(0)
  const sunY = Y(0)
  const wedgePath = `M${sunX.toFixed(1)},${sunY.toFixed(1)}${wedge.map((p) => `L${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join('')}Z`
  const q = orbit.a * (1 - orbit.e)
  const periX = X(q * Math.cos(orbit.omegaRad))
  const periY = Y(q * Math.sin(orbit.omegaRad))
  const aphelionMarker = markers.reduce((best, m) => (m.r > best.r ? m : best), markers[0])

  const tX = X(target.x)
  const tY = Y(target.y)
  const oX = X(obs.x)
  const oY = Y(obs.y)
  let losLine: { x1: number; y1: number; x2: number; y2: number; ex: number; ey: number } | null = null
  if (los.defined) {
    const len = Math.hypot(tX - oX, tY - oY)
    if (len > 12) {
      const ux = (tX - oX) / len
      const uy = (tY - oY) / len
      losLine = { x1: oX + ux * 6, y1: oY + uy * 6, x2: tX - ux * 8, y2: tY - uy * 8, ex: tX + ux * 46, ey: tY + uy * 46 }
    }
  }

  const barAu = [...NICE_AU].reverse().find((v) => v * scale <= width * 0.2) ?? NICE_AU[0]
  const barPx = barAu * scale
  const tLabel = awayFrom(tX, tY, sunX, sunY, 11)
  const oLabel = awayFrom(oX, oY, sunX, sunY, 11)
  const pLabel = awayFrom(periX, periY, sunX, sunY, 9)
  const aLabel = awayFrom(X(aphelionMarker.x), Y(aphelionMarker.y), sunX, sunY, 10)

  const summary = los.defined
    ? `Orbital plane at t = ${fmt(tDays, 0)} days: target ${fmt(target.r, 2)} AU from the Sun, observer at longitude ${fmt(((obs.longitudeRad * R2D) % 360 + 360) % 360, 0)} degrees, line of sight ${fmt(los.distance, 2)} AU toward longitude ${fmt(los.longitudeRad * R2D, 1)} degrees.`
    : `Orbital plane at t = ${fmt(tDays, 0)} days: target and observer coincide, line of sight undefined.`

  return (
    <div ref={ref} className="ml-scene-wrap">
      <svg className="ml-svg ml-sky" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary} data-testid="orbit-plane">
        <defs>
          <marker id={arrowId} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--teal)" />
          </marker>
          <marker id={`${arrowId}-n`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--text-2)" />
          </marker>
        </defs>
        <rect x={0} y={0} width={width} height={height} fill="var(--sky)" />
        {/* observer orbit */}
        <circle cx={sunX} cy={sunY} r={observer.radiusAu * scale} fill="none" stroke="var(--faint)" strokeWidth={1.25} />
        {/* target orbit from orbitState samples */}
        <path d={toPath(ellipse)} fill="none" stroke="var(--text-2)" strokeOpacity={0.7} strokeWidth={1.5} />
        {/* area swept during one marker interval (P/12) starting now */}
        <path d={wedgePath} fill="rgba(47, 212, 192, 0.16)" stroke="rgba(47, 212, 192, 0.55)" strokeWidth={1} data-testid="orbit-wedge" />
        {/* equal-time markers */}
        {markers.map((m) => (
          <circle key={m.t} cx={X(m.x)} cy={Y(m.y)} r={3} fill="var(--text-2)" stroke="var(--sky)" strokeWidth={1.5} />
        ))}
        {!narrow && (
          <text className="ml-label-faint" x={aLabel.x} y={aLabel.y} textAnchor={aLabel.anchor}>
            equal time intervals (P/12)
          </text>
        )}
        {orbit.e > 0.02 && (
          <>
            <path d={`M${periX} ${periY - 4} L${periX + 4} ${periY} L${periX} ${periY + 4} L${periX - 4} ${periY} Z`} fill="none" stroke="var(--text-2)" strokeWidth={1.2} />
            {!narrow && Math.hypot(periX - tX, periY - tY) > 36 && (
              <text className="ml-label-faint" x={pLabel.x} y={pLabel.y} textAnchor={pLabel.anchor}>
                perihelion
              </text>
            )}
          </>
        )}
        {/* line of sight: target - observer */}
        {losLine && (
          <>
            <line x1={tX} y1={tY} x2={losLine.ex} y2={losLine.ey} stroke="var(--teal)" strokeOpacity={0.35} strokeWidth={1.25} />
            <line x1={losLine.x1} y1={losLine.y1} x2={losLine.x2} y2={losLine.y2} stroke="var(--teal)" strokeWidth={1.5} markerEnd={`url(#${arrowId})`} />
          </>
        )}
        {/* Sun at the focus */}
        <circle cx={sunX} cy={sunY} r={5} fill="var(--sky)" stroke="var(--text)" strokeWidth={1.4} />
        <circle cx={sunX} cy={sunY} r={1.6} fill="var(--text)" />
        <text className="ml-label" x={sunX + 8} y={sunY - 8}>
          Sun (focus)
        </text>
        {/* observer and target */}
        <rect x={oX - 4.5} y={oY - 4.5} width={9} height={9} fill="var(--text)" stroke="var(--sky)" strokeWidth={1.5} />
        <text className="ml-label" x={oLabel.x} y={oLabel.y} textAnchor={oLabel.anchor}>
          observer
        </text>
        <circle cx={tX} cy={tY} r={5.5} fill="var(--teal)" stroke="var(--sky)" strokeWidth={2} />
        <text className="ml-label ml-label-teal" x={tLabel.x} y={tLabel.y} textAnchor={tLabel.anchor}>
          target
        </text>
        {/* scale bar and reference direction */}
        <g transform={`translate(${pad - 6},${height - 14})`}>
          <line x1={0} x2={barPx} y1={0} y2={0} stroke="var(--text-2)" strokeWidth={1.5} />
          <line x1={0} x2={0} y1={-4} y2={4} stroke="var(--text-2)" strokeWidth={1.5} />
          <line x1={barPx} x2={barPx} y1={-4} y2={4} stroke="var(--text-2)" strokeWidth={1.5} />
          <text className="ml-label-faint" x={barPx + 6} y={4}>
            {barAu} AU
          </text>
        </g>
        <g transform={`translate(${width - pad + 6},${height - 14})`}>
          <line x1={-30} x2={-2} y1={0} y2={0} stroke="var(--text-2)" strokeWidth={1.25} markerEnd={`url(#${arrowId}-n)`} />
          <text className="ml-label-faint" x={-36} y={4} textAnchor="end">
            longitude 0°
          </text>
        </g>
        {!los.defined && (
          <text className="ml-label" x={width / 2} y={20} textAnchor="middle">
            Undefined geometry: target and observer coincide
          </text>
        )}
      </svg>
    </div>
  )
}
