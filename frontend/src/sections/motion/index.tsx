/* Motion lab: two separate, explicitly synthetic teaching experiments.
 * 1) Bound two-body orbit + moving observer (kepler.ts). 2) Nearby source with independent
 * proper motion and annual parallax from declared geometry (nearbySource.ts). */
import { useEffect, useMemo, useState } from 'react'
import { RotateCcw, X } from 'lucide-react'
import { fmt, fmtSigned } from '../../lib/format'
import { useAppStore } from '../../state/app'
import { MIN_PARALLAX_SNR_FOR_DISTANCE, orbitTimeRange, useMotionStore, type Experiment } from '../../state/motion'
import {
  DAYS_PER_JULIAN_YEAR,
  KM_S_PER_AU_DAY,
  lineOfSight,
  muFromSolarMasses,
  observerState,
  orbitState,
  period,
  visVivaSpeed,
  type CircularObserver,
  type OrbitElements,
} from '../../physics/kepler'
import { nearbyOffsetMas, parallaxAmplitudeMas, parallaxSemiMinorMas, transverseSpeed, type NearbyParams } from '../../physics/nearbySource'
import { Callout, KV, OriginBadge, Panel, Segmented, Slider, Toggle } from '../../components/ui'
import { LogSlider, TimeControls, usePlayback, usePrefersReducedMotion, type Choice } from './controls'
import { LongitudePlot } from './LongitudePlot'
import { NearbyOffsetTime, NearbySkyPath } from './NearbyView'
import { OrbitPlaneView } from './OrbitPlaneView'
import './motion.css'

const D2R = Math.PI / 180

export function MotionLab() {
  const experiment = useMotionStore((s) => s.experiment)
  const setExperiment = useMotionStore((s) => s.setExperiment)
  const setPlaying = useMotionStore((s) => s.setPlaying)
  const active = useAppStore((s) => s.section) === 'motion'
  useEffect(() => {
    if (!active) setPlaying(null) // never animate while hidden
  }, [active, setPlaying])
  return (
    <div className="page ml-page">
      <div className="page-head">
        <div>
          <div className="row" style={{ gap: 10 }}>
            <h1>Motion lab</h1>
            <OriginBadge origin="simulated" label="Synthetic teaching model" />
          </div>
          <p className="sub">Why things move on the sky: idealised geometry computed in your browser. Illustrative bodies only — no real object is modelled.</p>
        </div>
        <Segmented<Experiment>
          ariaLabel="Experiment"
          value={experiment}
          onChange={setExperiment}
          options={[
            { value: 'orbit', label: 'Orbit and observer' },
            { value: 'nearby', label: 'Nearby source' },
          ]}
          testId="ml-experiment"
        />
      </div>
      {experiment === 'orbit' ? <OrbitExperiment active={active} /> : <NearbyExperiment active={active} />}
    </div>
  )
}

/* ------------------------------------------------------------------ orbit */

const ORBIT_STEPS: Choice[] = [
  { id: '1d', label: '1 day', value: 1 },
  { id: '10d', label: '10 days', value: 10 },
  { id: '30d', label: '30 days', value: 30 },
  { id: '100d', label: '100 days', value: 100 },
]
const ORBIT_SPEEDS: Choice[] = [
  { id: 'slow', label: '20 days / s', value: 20 },
  { id: 'normal', label: '60 days / s', value: 60 },
  { id: 'fast', label: '180 days / s', value: 180 },
]

function OrbitExperiment({ active }: { active: boolean }) {
  const o = useMotionStore((s) => s.orbit)
  const setOrbit = useMotionStore((s) => s.setOrbit)
  const playing = useMotionStore((s) => s.playing) === 'orbit'
  const setPlaying = useMotionStore((s) => s.setPlaying)
  const reset = useMotionStore((s) => s.resetOrbit)
  const reduced = usePrefersReducedMotion()
  const [stepId, setStepId] = useState('10d')
  const [speedId, setSpeedId] = useState('normal')
  const mu = muFromSolarMasses(o.massSun)
  const orbit: OrbitElements = useMemo(() => ({ a: o.aAu, e: o.e, omegaRad: o.omegaDeg * D2R, M0Rad: 0, t0Days: 0, mu }), [o.aAu, o.e, o.omegaDeg, mu])
  const observer: CircularObserver = useMemo(() => ({ radiusAu: o.observerRadiusAu, phaseRad: o.observerPhaseDeg * D2R, mu }), [o.observerRadiusAu, o.observerPhaseDeg, mu])
  const P = period(o.aAu, mu)
  const Pobs = period(o.observerRadiusAu, mu)
  const tMax = orbitTimeRange(o)
  const speed = (ORBIT_SPEEDS.find((c) => c.id === speedId) ?? ORBIT_SPEEDS[1]).value
  usePlayback(active && playing, (dt) => {
    const t = useMotionStore.getState().orbit.tDays + (reduced ? (ORBIT_STEPS.find((c) => c.id === stepId)?.value ?? 10) : dt * speed)
    setOrbit({ tDays: t > tMax ? 0 : t })
  }, reduced)
  const target = orbitState(orbit, o.tDays)
  const obs = observerState(observer, o.tDays)
  const los = lineOfSight(target, obs)
  const v = visVivaSpeed(target.r, o.aAu, mu)
  const lonWindow = Math.max(2 * Pobs, Math.min(P, 6 * Pobs))
  const t0 = Math.max(0, Math.min(o.tDays - lonWindow / 2, tMax - lonWindow))

  return (
    <div className="ml-layout">
      <div className="ml-scenes">
        <Panel title="View 1 · Orbital plane (seen from above)" eyebrow="Common heliocentric frame, AU" bodyClassName="ml-panel-body">
          <OrbitPlaneView orbit={orbit} observer={observer} tDays={o.tDays} periodDays={P} />
          <p className="small faint">
            Teal wedge: area swept by the target–Sun line during the next P/12. Equal-time markers crowd near aphelion because the target moves slowest there (Kepler’s
            second law). Body sizes are symbolic; distances are to scale.
          </p>
        </Panel>
        <Panel title="View 2 · The observer’s sky direction" eyebrow="Apparent longitude of target − observer" bodyClassName="ml-panel-body">
          <LongitudePlot orbit={orbit} observer={observer} tDays={o.tDays} t0={t0} t1={t0 + lonWindow} />
          <p className="small faint">
            The same states seen from the moving observer: the viewing vector is target position minus observer position. Shaded intervals are apparent retrograde motion,
            produced by the observer’s own orbit — not by the target reversing.
          </p>
        </Panel>
      </div>
      <aside className="ml-controls" aria-label="Orbit experiment controls">
        <Panel title="Target orbit" actions={<button type="button" className="btn btn-sm btn-ghost" onClick={reset}><RotateCcw size={13} aria-hidden /> Reset</button>}>
          <div className="stack">
            <LogSlider label="Semimajor axis a" value={o.aAu} min={0.3} max={40} onChange={(aAu) => setOrbit({ aAu })} format={(x) => `${x.toFixed(x < 10 ? 2 : 1)} AU`} testId="ml-a" />
            <Slider label="Eccentricity e" value={o.e} min={0} max={0.95} step={0.01} onChange={(e) => setOrbit({ e })} format={(x) => x.toFixed(2)} testId="ml-e"
              hint="Bound orbits only: 0 ≤ e < 1. The period does not change with e." />
            <Slider label="Argument of perihelion ω" value={o.omegaDeg} min={0} max={359} step={1} onChange={(omegaDeg) => setOrbit({ omegaDeg })} format={(x) => `${x.toFixed(0)}°`} />
            <LogSlider label="Central mass" value={o.massSun} min={0.1} max={10} onChange={(massSun) => setOrbit({ massSun })} format={(x) => `${x.toFixed(2)} M☉`} />
          </div>
        </Panel>
        <Panel title="Observer orbit (circular)">
          <div className="stack">
            <LogSlider label="Orbit radius" value={o.observerRadiusAu} min={0.3} max={5} onChange={(observerRadiusAu) => setOrbit({ observerRadiusAu })} format={(x) => `${x.toFixed(2)} AU`} />
            <Slider label="Phase at t = 0" value={o.observerPhaseDeg} min={0} max={359} step={1} onChange={(observerPhaseDeg) => setOrbit({ observerPhaseDeg })} format={(x) => `${x.toFixed(0)}°`} />
          </div>
        </Panel>
        <Panel title="Time">
          <TimeControls
            label="Absolute simulation time"
            value={o.tDays}
            max={tMax}
            step={1}
            format={(x) => `${x.toFixed(0)} d (${(x / DAYS_PER_JULIAN_YEAR).toFixed(2)} yr)`}
            onChange={(tDays) => setOrbit({ tDays })}
            stepChoices={ORBIT_STEPS}
            stepId={stepId}
            onStepId={setStepId}
            speedChoices={ORBIT_SPEEDS}
            speedId={speedId}
            onSpeedId={setSpeedId}
            playing={playing}
            onTogglePlay={() => setPlaying(playing ? null : 'orbit')}
            reducedMotion={reduced}
            unit="days"
            hint="Target at perihelion at t = 0. Positions are computed from this absolute time, not accumulated."
            testIdPrefix="ml-orbit"
          />
        </Panel>
        <Panel title="Readouts" eyebrow="Model values">
          <dl className="kvs" data-testid="ml-orbit-readouts">
            <KV k="Period P">
              {fmt(P, 1)} d = {fmt(P / DAYS_PER_JULIAN_YEAR, 3)} yr
            </KV>
            <KV k="Distance r">{fmt(target.r, 3)} AU</KV>
            <KV k="Speed (vis-viva)">{fmt(v * KM_S_PER_AU_DAY, 2)} km/s</KV>
            <KV k="Mean / ecc. / true anomaly">
              {fmt(((target.M % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI) / D2R, 1)}° / {fmt(((target.E % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI) / D2R, 1)}° /{' '}
              {fmt(((target.nu % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI) / D2R, 1)}°
            </KV>
            <KV k="Line of sight">{los.defined ? `${fmt(los.distance, 3)} AU toward longitude ${fmt(los.longitudeRad / D2R, 2)}°` : `undefined — ${los.reason}`}</KV>
            <KV k="Observer period">{fmt(Pobs, 1)} d</KV>
          </dl>
          <p className="small faint">P = 2π √(a³ / GM) depends only on a and the central mass: change e and the period stays the same.</p>
        </Panel>
        <Panel title="What this model omits">
          <ul className="small ml-list">
            <li>Planetary perturbations and the observer’s own mass (independent two-body orbits).</li>
            <li>Light-time, aberration and relativistic effects.</li>
            <li>Inclination: both orbits are coplanar, so the sky view is one longitude.</li>
            <li>Illustrative bodies — no real object, and no Planet X orbit, is implied.</li>
          </ul>
        </Panel>
      </aside>
    </div>
  )
}

/* ------------------------------------------------------------------ nearby source */

const NEARBY_STEPS: Choice[] = [
  { id: 'week', label: '1 week', value: 7 / 365.25 },
  { id: 'month', label: '1 month', value: 1 / 12 },
  { id: 'quarter', label: '3 months', value: 0.25 },
]
const NEARBY_SPEEDS: Choice[] = [
  { id: 'slow', label: '0.25 yr / s', value: 0.25 },
  { id: 'normal', label: '0.5 yr / s', value: 0.5 },
  { id: 'fast', label: '1 yr / s', value: 1 },
]

function NearbyExperiment({ active }: { active: boolean }) {
  const s = useMotionStore((st) => st.nearby)
  const setNearby = useMotionStore((st) => st.setNearby)
  const playing = useMotionStore((st) => st.playing) === 'nearby'
  const setPlaying = useMotionStore((st) => st.setPlaying)
  const reset = useMotionStore((st) => st.resetNearby)
  const handoff = useMotionStore((st) => st.handoffResult)
  const dismiss = useMotionStore((st) => st.dismissHandoff)
  const reduced = usePrefersReducedMotion()
  const [stepId, setStepId] = useState('month')
  const [speedId, setSpeedId] = useState('normal')
  const params: NearbyParams = useMemo(
    () => ({
      distancePc: s.distancePc,
      eclipticLatDeg: s.eclipticLatDeg,
      pmEastMasYr: s.pmEastMasYr,
      pmNorthMasYr: s.pmNorthMasYr,
      observerPhaseRad: s.observerPhaseDeg * D2R,
      properMotion: s.properMotion,
      parallax: s.parallax,
    }),
    [s.distancePc, s.eclipticLatDeg, s.pmEastMasYr, s.pmNorthMasYr, s.observerPhaseDeg, s.properMotion, s.parallax],
  )
  const speed = (NEARBY_SPEEDS.find((c) => c.id === speedId) ?? NEARBY_SPEEDS[1]).value
  usePlayback(active && playing, (dt) => {
    const cur = useMotionStore.getState().nearby
    const t = cur.tYr + (reduced ? (NEARBY_STEPS.find((c) => c.id === stepId)?.value ?? 1 / 12) : dt * speed)
    setNearby({ tYr: t > cur.spanYr ? 0 : t })
  }, reduced)
  const now = nearbyOffsetMas(params, s.tYr)
  const plx = parallaxAmplitudeMas(s.distancePc)
  const pmTot = Math.hypot(s.pmEastMasYr, s.pmNorthMasYr)
  const vt = transverseSpeed(pmTot, s.distancePc)

  return (
    <div className="ml-layout">
      <div className="ml-scenes">
        {handoff && (
          <div className="ml-handoff" data-testid="ml-handoff">
            <Callout tone="info" role="status">
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <strong>
                  Parameters copied from Observatory fit {handoff.handoff.label} <span className="mono small">({handoff.handoff.fitId.split(':').slice(-1)[0]})</span>
                </strong>
                <button type="button" className="btn btn-sm btn-ghost btn-icon" aria-label="Dismiss" onClick={dismiss}>
                  <X size={13} />
                </button>
              </div>
              <ul className="small ml-list">
                <li>
                  <OriginBadge origin="derived_measurement" label="Fit estimate" /> Proper motion µα* {fmt(handoff.handoff.pmra, 1)}, µδ {fmt(handoff.handoff.pmdec, 1)} mas/yr
                  {handoff.handoff.eclipticNorthPaDeg != null
                    ? ` → rotated by ${fmt(handoff.handoff.eclipticNorthPaDeg, 1)}° into ecliptic east ${fmt(handoff.pmEast.copied ? handoff.pmEast.value : null, 1)}, north ${fmt(handoff.pmNorth.copied ? handoff.pmNorth.value : null, 1)} mas/yr.`
                    : ' (copied without frame rotation).'}
                </li>
                <li>Ecliptic latitude {handoff.eclipticLat.copied ? `${fmt(handoff.eclipticLat.value, 1)}°` : `kept at default (${handoff.eclipticLat.reason})`}.</li>
                <li>
                  Distance:{' '}
                  {handoff.distance.copied
                    ? `${fmt(handoff.distance.value, 2)} pc = 1000 / parallax (parallax/σ = ${fmt(handoff.parallaxSnr, 0)} ≥ ${MIN_PARALLAX_SNR_FOR_DISTANCE}).`
                    : `kept at the default ${s.distancePc} pc because ${handoff.distance.reason}.`}
                </li>
                <li>
                  The fit used the real Earth ephemeris; this lesson uses a circular 1 AU observer and places the source at ecliptic longitude 0, so the shape matches but the
                  timing of the yearly loop is illustrative.{handoff.edited ? ' Settings were edited after the copy.' : ''}
                </li>
              </ul>
            </Callout>
          </div>
        )}
        <Panel title="Apparent sky path" eyebrow="Source − observer, gnomonic offsets about the t = 0 direction" bodyClassName="ml-panel-body">
          <NearbySkyPath params={params} spanYr={s.spanYr} tYr={s.tYr} />
        </Panel>
        <div className="ml-pair">
          <Panel bodyClassName="ml-panel-body">
            <NearbyOffsetTime params={params} spanYr={s.spanYr} tYr={s.tYr} axis="east" />
          </Panel>
          <Panel bodyClassName="ml-panel-body">
            <NearbyOffsetTime params={params} spanYr={s.spanYr} tYr={s.tYr} axis="north" />
          </Panel>
        </div>
      </div>
      <aside className="ml-controls" aria-label="Nearby-source experiment controls">
        <Panel title="Effects" actions={<button type="button" className="btn btn-sm btn-ghost" onClick={reset}><RotateCcw size={13} aria-hidden /> Reset</button>}>
          <div className="stack">
            <Toggle checked={s.properMotion} onChange={(properMotion) => setNearby({ properMotion })} label="Proper motion (source moves through space)" testId="ml-toggle-pm" />
            <Toggle checked={s.parallax} onChange={(parallax) => setNearby({ parallax })} label="Annual parallax (observer orbits the Sun)" testId="ml-toggle-plx" />
            {!s.properMotion && !s.parallax && <p className="small muted">Both effects off: the source stays at its reference direction.</p>}
          </div>
        </Panel>
        <Panel title="Source (declared)">
          <div className="stack">
            <LogSlider label="Distance" value={s.distancePc} min={1} max={1000} onChange={(distancePc) => setNearby({ distancePc })} format={(x) => `${x.toFixed(x < 10 ? 2 : 0)} pc`} testId="ml-distance" />
            <Slider label="Ecliptic latitude β" value={s.eclipticLatDeg} min={-90} max={90} step={0.5} onChange={(eclipticLatDeg) => setNearby({ eclipticLatDeg })} format={(x) => `${x.toFixed(1)}°`}
              hint="β = ±90° gives a circle, β = 0° a line: the parallax ellipse is the observer’s orbit seen from the source." />
            <Slider label="Proper motion, ecliptic east" value={s.pmEastMasYr} min={-2000} max={2000} step={5} onChange={(pmEastMasYr) => setNearby({ pmEastMasYr })} format={(x) => `${x.toFixed(0)} mas/yr`} />
            <Slider label="Proper motion, ecliptic north" value={s.pmNorthMasYr} min={-2000} max={2000} step={5} onChange={(pmNorthMasYr) => setNearby({ pmNorthMasYr })} format={(x) => `${x.toFixed(0)} mas/yr`} />
            <Slider label="Observer longitude at t = 0" value={s.observerPhaseDeg} min={0} max={359} step={1} onChange={(observerPhaseDeg) => setNearby({ observerPhaseDeg })} format={(x) => `${x.toFixed(0)}°`} />
            <Slider label="Time span shown" value={s.spanYr} min={1} max={6} step={0.5} onChange={(spanYr) => setNearby({ spanYr })} format={(x) => `${x.toFixed(1)} yr`} />
          </div>
        </Panel>
        <Panel title="Time">
          <TimeControls
            label="Time from model epoch"
            value={s.tYr}
            max={s.spanYr}
            step={1 / 365.25}
            format={(x) => `${x.toFixed(3)} yr`}
            onChange={(tYr) => setNearby({ tYr })}
            stepChoices={NEARBY_STEPS}
            stepId={stepId}
            onStepId={setStepId}
            speedChoices={NEARBY_SPEEDS}
            speedId={speedId}
            onSpeedId={setSpeedId}
            playing={playing}
            onTogglePlay={() => setPlaying(playing ? null : 'nearby')}
            reducedMotion={reduced}
            unit="years"
            hint="Julian years from the model epoch (synthetic)."
            testIdPrefix="ml-nearby"
          />
        </Panel>
        <Panel title="Readouts" eyebrow="Model values">
          <dl className="kvs" data-testid="ml-nearby-readouts">
            <KV k="Parallax amplitude">{fmt(plx, 2)} mas (1000 / d)</KV>
            <KV k="Ellipse semi-minor">{fmt(parallaxSemiMinorMas(s.distancePc, s.eclipticLatDeg), 2)} mas (ϖ |sin β|)</KV>
            <KV k="Total proper motion">{fmt(pmTot, 1)} mas/yr</KV>
            <KV k="Transverse speed">{fmt(vt.kmPerS, 1)} km/s</KV>
            <KV k="Offset now">
              {fmtSigned(now.east, 1)} E, {fmtSigned(now.north, 1)} N mas
            </KV>
          </dl>
          <ul className="small faint ml-list">
            <li>Observer: circular 1 AU orbit in the ecliptic (approximation; Earth’s orbit has e = 0.0167).</li>
            <li>Radial velocity 0 (declared); assumed distance {fmt(s.distancePc, 2)} pc.</li>
            <li>Visual magnification: none — axes are in mas.</li>
          </ul>
        </Panel>
      </aside>
    </div>
  )
}
