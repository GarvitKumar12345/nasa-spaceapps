/* Motion lab state: settings and absolute simulation time of the two synthetic teaching
 * experiments, playback, and the Observatory hand-off ("Explain in Motion lab").
 * Physics lives in src/physics (kepler.ts, nearbySource.ts); this store only holds inputs.
 * `loadNearbyFromFit` is the agreed entry point used by the Observatory: it copies a fit's
 * values into the nearby-source experiment and selects it (the caller then navigates here). */
import { create } from 'zustand'
import { muFromSolarMasses, period } from '../physics/kepler'
import { useAppStore } from './app'

export interface FitHandoff {
  pmra: number | null // mas/yr (pmra = dRA/dt cos Dec), equatorial
  pmdec: number | null // mas/yr, equatorial
  parallax: number | null // mas
  parallaxSigma: number | null // mas
  eclipticLatDeg: number | null
  /** Position angle (deg, east of equatorial north) of ecliptic north at the source; rotates (pmra, pmdec) into ecliptic components. */
  eclipticNorthPaDeg?: number | null
  label: string
  fitId: string
}

/** Rotate an equatorial proper motion (pmra*, pmdec) into ecliptic (east, north) components. */
export function equatorialToEclipticPm(pmra: number, pmdec: number, paDeg: number): { east: number; north: number } {
  const t = (paDeg * Math.PI) / 180
  return { east: pmra * Math.cos(t) - pmdec * Math.sin(t), north: pmdec * Math.cos(t) + pmra * Math.sin(t) }
}

export type Experiment = 'orbit' | 'nearby'

export interface OrbitSettings {
  /** Target semimajor axis, AU. */
  aAu: number
  /** Target eccentricity, 0 <= e <= 0.95 in the UI. */
  e: number
  /** Argument of perihelion, deg. */
  omegaDeg: number
  /** Central mass, Msun (shared by target and observer). */
  massSun: number
  /** Observer circular-orbit radius, AU. */
  observerRadiusAu: number
  /** Observer longitude at t = 0, deg. */
  observerPhaseDeg: number
  /** Absolute simulation time, days (target at perihelion at t = 0: M0 = 0, t0 = 0). */
  tDays: number
}

export interface NearbySettings {
  distancePc: number
  eclipticLatDeg: number
  pmEastMasYr: number
  pmNorthMasYr: number
  /** Observer ecliptic longitude at the model epoch, deg. */
  observerPhaseDeg: number
  properMotion: boolean
  parallax: boolean
  /** Path span, Julian years from the model epoch. */
  spanYr: number
  /** Current time, Julian years from the model epoch. */
  tYr: number
}

export const DEFAULT_ORBIT: OrbitSettings = {
  aAu: 2.8,
  e: 0.35,
  omegaDeg: 60,
  massSun: 1,
  observerRadiusAu: 1,
  observerPhaseDeg: 0,
  tDays: 0,
}

export const DEFAULT_NEARBY: NearbySettings = {
  distancePc: 10,
  eclipticLatDeg: 35,
  pmEastMasYr: 120,
  pmNorthMasYr: -80,
  observerPhaseDeg: 0,
  properMotion: true,
  parallax: true,
  spanYr: 3,
  tYr: 0,
}

/** A parallax is inverted into a distance only when parallax / sigma reaches this. */
export const MIN_PARALLAX_SNR_FOR_DISTANCE = 10

export type CopiedValue<T> = { copied: true; value: T } | { copied: false; reason: string }

export interface HandoffResult {
  handoff: FitHandoff
  pmEast: CopiedValue<number>
  pmNorth: CopiedValue<number>
  eclipticLat: CopiedValue<number>
  /** Distance = 1000 / parallax, only for a significant positive parallax. */
  distance: CopiedValue<number>
  /** parallax / parallaxSigma when both are finite and sigma > 0. */
  parallaxSnr: number | null
  /** True once the user changes nearby-source settings after the copy. */
  edited: boolean
}

const isNum = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)

/** Map a fit hand-off onto nearby-source settings (pure; exported for tests). */
export function nearbyFromHandoff(h: FitHandoff, current: NearbySettings): { settings: NearbySettings; result: HandoffResult } {
  // The lesson works in ecliptic east/north; the fit reports equatorial pmra*/pmdec. Rotate when the angle is known.
  const pa = isNum(h.eclipticNorthPaDeg) ? h.eclipticNorthPaDeg : null
  const both = isNum(h.pmra) && isNum(h.pmdec)
  const rot = both && pa !== null ? equatorialToEclipticPm(h.pmra as number, h.pmdec as number, pa) : null
  const pmEast: CopiedValue<number> = rot ? { copied: true, value: rot.east } : isNum(h.pmra) ? { copied: true, value: h.pmra } : { copied: false, reason: 'pmra not available from the fit' }
  const pmNorth: CopiedValue<number> = rot ? { copied: true, value: rot.north } : isNum(h.pmdec) ? { copied: true, value: h.pmdec } : { copied: false, reason: 'pmdec not available from the fit' }
  const eclipticLat: CopiedValue<number> =
    isNum(h.eclipticLatDeg) && Math.abs(h.eclipticLatDeg) <= 90
      ? { copied: true, value: h.eclipticLatDeg }
      : { copied: false, reason: 'ecliptic latitude not available from the fit' }
  const parallaxSnr = isNum(h.parallax) && isNum(h.parallaxSigma) && h.parallaxSigma > 0 ? h.parallax / h.parallaxSigma : null
  let distance: CopiedValue<number>
  if (!isNum(h.parallax)) distance = { copied: false, reason: 'the fit has no parallax' }
  else if (h.parallax <= 0) distance = { copied: false, reason: 'the fitted parallax is not positive, so it cannot be inverted into a distance' }
  else if (parallaxSnr === null) distance = { copied: false, reason: 'the parallax has no usable uncertainty' }
  else if (parallaxSnr < MIN_PARALLAX_SNR_FOR_DISTANCE)
    distance = {
      copied: false,
      reason: `parallax / sigma = ${parallaxSnr.toFixed(1)} is below ${MIN_PARALLAX_SNR_FOR_DISTANCE}; inverting a weak parallax gives a biased, unreliable distance`,
    }
  else distance = { copied: true, value: 1000 / h.parallax }
  const settings: NearbySettings = {
    ...current,
    pmEastMasYr: pmEast.copied ? pmEast.value : current.pmEastMasYr,
    pmNorthMasYr: pmNorth.copied ? pmNorth.value : current.pmNorthMasYr,
    eclipticLatDeg: eclipticLat.copied ? eclipticLat.value : current.eclipticLatDeg,
    distancePc: distance.copied ? distance.value : current.distancePc,
    properMotion: true,
    parallax: true,
    tYr: 0,
  }
  return { settings, result: { handoff: h, pmEast, pmNorth, eclipticLat, distance, parallaxSnr, edited: false } }
}

/** Scrubber range for the orbit experiment: at least one target period and two observer periods (days). */
export function orbitTimeRange(o: OrbitSettings): number {
  const mu = muFromSolarMasses(o.massSun)
  return Math.ceil(Math.max(period(o.aAu, mu), 2 * period(o.observerRadiusAu, mu)))
}

interface MotionState {
  experiment: Experiment
  orbit: OrbitSettings
  nearby: NearbySettings
  /** Which experiment is animating (only after an explicit Play). */
  playing: Experiment | null
  /** Last fit hand-off (kept for compatibility with the interface stub). */
  handoff: FitHandoff | null
  handoffResult: HandoffResult | null
  setExperiment: (experiment: Experiment) => void
  setOrbit: (patch: Partial<OrbitSettings>) => void
  setNearby: (patch: Partial<NearbySettings>) => void
  setPlaying: (playing: Experiment | null) => void
  resetOrbit: () => void
  resetNearby: () => void
  loadNearbyFromFit: (handoff: FitHandoff) => void
  dismissHandoff: () => void
}

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x))

export const useMotionStore = create<MotionState>((set, get) => ({
  experiment: 'orbit',
  orbit: DEFAULT_ORBIT,
  nearby: DEFAULT_NEARBY,
  playing: null,
  handoff: null,
  handoffResult: null,
  setExperiment: (experiment) => set({ experiment, playing: null }),
  setOrbit: (patch) => {
    const next = { ...get().orbit, ...patch }
    next.tDays = clamp(next.tDays, 0, orbitTimeRange(next))
    set({ orbit: next })
  },
  setNearby: (patch) => {
    const next = { ...get().nearby, ...patch }
    next.tYr = clamp(next.tYr, 0, next.spanYr)
    const hr = get().handoffResult
    const onlyTime = Object.keys(patch).every((k) => k === 'tYr')
    set({ nearby: next, handoffResult: hr && !onlyTime ? { ...hr, edited: true } : hr })
  },
  setPlaying: (playing) => set({ playing }),
  resetOrbit: () => set({ orbit: DEFAULT_ORBIT, playing: null }),
  resetNearby: () => set({ nearby: DEFAULT_NEARBY, playing: null, handoffResult: null }),
  loadNearbyFromFit: (handoff) => {
    const { settings, result } = nearbyFromHandoff(handoff, DEFAULT_NEARBY)
    set({ handoff, handoffResult: result, nearby: settings, experiment: 'nearby', playing: null })
    useAppStore.getState().announce(`Motion lab: parameters copied from Observatory fit ${handoff.label}.`)
  },
  dismissHandoff: () => set({ handoffResult: null }),
}))
