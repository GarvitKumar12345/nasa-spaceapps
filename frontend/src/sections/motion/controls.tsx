/* Motion lab controls: playback loop, reduced-motion preference, log-scale slider and the
 * time transport (scrubber, step, play/pause). Playback only ever starts from an explicit
 * Play; callers pause it when the section is hidden. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Pause, Play, SkipBack, StepBack, StepForward } from 'lucide-react'
import { Slider } from '../../components/ui'

const REDUCED_QUERY = '(prefers-reduced-motion: reduce)'

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(REDUCED_QUERY).matches,
  )
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(REDUCED_QUERY)
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return reduced
}

/**
 * While `active`, calls advance(dtSeconds) on every animation frame, or once per second
 * (discrete jumps, no continuous animation) when the user prefers reduced motion.
 */
export function usePlayback(active: boolean, advance: (dtSeconds: number) => void, reducedMotion: boolean): void {
  const advanceRef = useRef(advance)
  useEffect(() => {
    advanceRef.current = advance
  })
  useEffect(() => {
    if (!active) return
    if (reducedMotion) {
      const id = window.setInterval(() => advanceRef.current(1), 1000)
      return () => window.clearInterval(id)
    }
    let raf = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000))
      last = now
      advanceRef.current(dt)
      raf = window.requestAnimationFrame(tick)
    }
    raf = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(raf)
  }, [active, reducedMotion])
}

const roundSig = (x: number, digits: number) => Number(x.toPrecision(digits))

/** Slider on a log10 scale; the value passed in and out is linear. */
export function LogSlider({
  label,
  value,
  min,
  max,
  onChange,
  format,
  hint,
  testId,
}: {
  label: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
  format: (value: number) => string
  hint?: ReactNode
  testId?: string
}) {
  const lo = Math.log10(min)
  const hi = Math.log10(max)
  return (
    <Slider
      label={label}
      value={Math.log10(value)}
      min={lo}
      max={hi}
      step={(hi - lo) / 600}
      onChange={(u) => onChange(roundSig(10 ** u, 3))}
      format={(u) => format(10 ** u)}
      hint={hint}
      testId={testId}
    />
  )
}

export interface Choice {
  id: string
  label: string
  value: number
}

export function TimeControls({
  label,
  value,
  max,
  step,
  format,
  onChange,
  stepChoices,
  stepId,
  onStepId,
  speedChoices,
  speedId,
  onSpeedId,
  playing,
  onTogglePlay,
  reducedMotion,
  unit,
  hint,
  testIdPrefix,
}: {
  label: string
  value: number
  max: number
  step: number
  format: (v: number) => string
  onChange: (v: number) => void
  stepChoices: Choice[]
  stepId: string
  onStepId: (id: string) => void
  speedChoices: Choice[]
  speedId: string
  onSpeedId: (id: string) => void
  playing: boolean
  onTogglePlay: () => void
  reducedMotion: boolean
  unit: string
  hint?: ReactNode
  testIdPrefix: string
}) {
  const stepSize = (stepChoices.find((c) => c.id === stepId) ?? stepChoices[0]).value
  const clampT = (v: number) => Math.min(max, Math.max(0, v))
  return (
    <div className="stack ml-time">
      <Slider label={label} value={value} min={0} max={max} step={step} onChange={onChange} format={format} hint={hint} testId={`${testIdPrefix}-time`} />
      <div className="ml-transport" role="group" aria-label="Time steps and playback">
        <button type="button" className="btn btn-sm btn-icon" onClick={() => onChange(0)} aria-label={`Go to t = 0 ${unit}`} title={`Go to t = 0 ${unit}`}>
          <SkipBack size={14} aria-hidden />
        </button>
        <button type="button" className="btn btn-sm" onClick={() => onChange(clampT(value - stepSize))} aria-label="Step back one step" data-testid={`${testIdPrefix}-step-back`}>
          <StepBack size={14} aria-hidden /> Back
        </button>
        <button type="button" className="btn btn-sm btn-primary ml-play" onClick={onTogglePlay} data-testid={`${testIdPrefix}-play`}>
          {playing ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
          {playing ? 'Pause' : 'Play'}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => onChange(clampT(value + stepSize))} aria-label="Step forward one step" data-testid={`${testIdPrefix}-step-forward`}>
          Forward <StepForward size={14} aria-hidden />
        </button>
      </div>
      <div className="ml-selects">
        <label className="field">
          <span className="field-label">Step size</span>
          <select className="select" value={stepId} onChange={(e) => onStepId(e.target.value)}>
            {stepChoices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Playback speed</span>
          <select className="select" value={speedId} onChange={(e) => onSpeedId(e.target.value)}>
            {speedChoices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {reducedMotion && <p className="small faint">Reduced motion is on: playback jumps once per second instead of animating.</p>}
    </div>
  )
}
