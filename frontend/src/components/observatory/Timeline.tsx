/* Epoch timeline: actual observation times (irregular spacing kept), missing/failed
 * visits shown as gaps, playback over real frames only (no interpolation). */
import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { ChevronFirst, ChevronLast, Pause, Play, Repeat, StepBack, StepForward } from 'lucide-react'
import type { Dataset } from '../../api/types'
import { fmtUtc, jyearToMjdTdb, mjdTdbToJyear } from '../../lib/format'
import { availableObservations, bandObservations, type Playback } from '../../state/observatory'

export interface TimelineProps {
  dataset: Dataset
  bandId: string
  epochObsId: string | null
  compareObsId: string | null
  displayedObsId: string | null
  showCompare: boolean
  playback: Playback
  onSelectEpoch: (obsId: string) => void
  onStep: (delta: number) => void
  onPlayback: (p: Partial<Playback>) => void
  /** When set, blink and playback are disabled and this reason is shown (e.g. no wavelength-compatible repeat). */
  blinkDisabledReason?: string | null
}

export function Timeline({ dataset, bandId, epochObsId, compareObsId, displayedObsId, showCompare, playback, onSelectEpoch, onStep, onPlayback, blinkDisabledReason = null }: TimelineProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(800)
  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(Math.max(240, Math.floor(el.getBoundingClientRect().width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const all = dataset.observations.map((o) => o.timing.mid.mjd_tdb)
  const tMin = Math.min(...all) - 20
  const tMax = Math.max(...all) + 20
  const pad = 18
  const x = (t: number) => pad + ((t - tMin) / (tMax - tMin)) * (width - 2 * pad)
  const obs = bandObservations(dataset, bandId)
  const avail = availableObservations(dataset, bandId)
  const idx = avail.findIndex((o) => o.id === epochObsId)
  const current = dataset.observations.find((o) => o.id === displayedObsId) ?? null
  const years: number[] = []
  for (let y = Math.ceil(mjdTdbToJyear(tMin)); y <= mjdTdbToJyear(tMax); y++) years.push(y)
  const disabled = avail.length < 2 || !!blinkDisabledReason

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowRight') onStep(1)
    else if (e.key === 'ArrowLeft') onStep(-1)
    else if (e.key === 'Home' && avail[0]) onSelectEpoch(avail[0].id)
    else if (e.key === 'End' && avail.length) onSelectEpoch(avail[avail.length - 1].id)
    else if (e.key === ' ') onPlayback({ playing: !playback.playing })
    else return
    e.preventDefault()
  }

  return (
    <div className="timeline" data-testid="timeline">
      <div className="timeline-controls">
        <div className="row" role="group" aria-label="Epoch playback">
          <button type="button" className="btn btn-icon btn-sm" aria-label="First epoch" disabled={disabled} onClick={() => avail[0] && onSelectEpoch(avail[0].id)}>
            <ChevronFirst size={15} />
          </button>
          <button type="button" className="btn btn-icon btn-sm" aria-label="Previous epoch" disabled={disabled} onClick={() => onStep(-1)} data-testid="step-back">
            <StepBack size={15} />
          </button>
          <button
            type="button"
            className="btn btn-sm"
            aria-pressed={playback.playing}
            disabled={disabled}
            onClick={() => onPlayback({ playing: !playback.playing, blink: false })}
            data-testid="play"
          >
            {playback.playing ? <Pause size={14} /> : <Play size={14} />} {playback.playing ? 'Pause' : 'Play'}
          </button>
          <button type="button" className="btn btn-icon btn-sm" aria-label="Next epoch" disabled={disabled} onClick={() => onStep(1)} data-testid="step-forward">
            <StepForward size={15} />
          </button>
          <button type="button" className="btn btn-icon btn-sm" aria-label="Last epoch" disabled={disabled} onClick={() => avail.length && onSelectEpoch(avail[avail.length - 1].id)}>
            <ChevronLast size={15} />
          </button>
          <button
            type="button"
            className="btn btn-sm"
            aria-pressed={playback.blink}
            disabled={disabled || !compareObsId || compareObsId === epochObsId}
            onClick={() => onPlayback({ blink: !playback.blink, playing: false })}
            title={blinkDisabledReason ?? 'Alternate between epoch A and comparison epoch B'}
            aria-describedby={blinkDisabledReason ? 'blink-reason' : undefined}
            data-testid="blink"
          >
            <Repeat size={14} /> Blink A/B
          </button>
          <label className="timeline-speed">
            <span className="sr-only">Playback interval</span>
            <select className="select" value={playback.intervalMs} onChange={(e) => onPlayback({ intervalMs: Number(e.target.value) })} aria-label="Playback interval">
              <option value={1600}>Slow</option>
              <option value={900}>Normal</option>
              <option value={450}>Fast</option>
            </select>
          </label>
        </div>
        {blinkDisabledReason && (
          <p id="blink-reason" className="timeline-blink-reason small" data-testid="blink-reason">
            Blink unavailable: {blinkDisabledReason}
          </p>
        )}
        <div className="timeline-readout" aria-live="polite" data-testid="epoch-readout">
          {current ? (
            <>
              <strong>
                {current.id === epochObsId ? 'A' : current.id === compareObsId ? 'B' : ''} {idx >= 0 ? `Epoch ${idx + 1} of ${avail.length}` : ''}
              </strong>{' '}
              · {fmtUtc(current.timing.mid.iso_utc)} <span className="faint">(mid-exposure)</span>
            </>
          ) : (
            'No epoch selected'
          )}
        </div>
      </div>
      <div ref={wrapRef} className="timeline-track" tabIndex={0} role="group" aria-label={`Observation epochs in band ${bandId}; arrow keys step between available frames`} onKeyDown={onKey}>
        <svg width={width} height={58} viewBox={`0 0 ${width} 58`} aria-hidden>
          <line x1={pad} x2={width - pad} y1={30} y2={30} className="tl-axis" />
          {years.map((y) => (
            <g key={y} transform={`translate(${x(jyearToMjdTdb(y))},0)`}>
              <line y1={24} y2={36} className="tl-year-tick" />
              <text y={52} textAnchor="middle" className="tl-year">
                {y}
              </text>
            </g>
          ))}
          {obs.map((o) => {
            const cx = x(o.timing.mid.mjd_tdb)
            const isA = o.id === epochObsId
            const isB = showCompare && o.id === compareObsId
            const shown = o.id === displayedObsId
            if (o.status !== 'available') {
              return (
                <g key={o.id} className="tl-gap">
                  <title>{`${o.timing.start.iso_utc?.slice(0, 10)} ${o.band_id}: ${o.status} — ${o.status_reason ?? ''}`}</title>
                  {o.status === 'failed' ? (
                    <path d={`M${cx - 4} 26 L${cx + 4} 34 M${cx + 4} 26 L${cx - 4} 34`} className="tl-failed" />
                  ) : (
                    <circle cx={cx} cy={30} r={4.5} className="tl-missing" />
                  )}
                  <text x={cx} y={14} textAnchor="middle" className="tl-gap-label">
                    {o.status}
                  </text>
                </g>
              )
            }
            return (
              <g key={o.id} className="tl-epoch" onClick={() => onSelectEpoch(o.id)} style={{ cursor: 'pointer' }} data-testid={`epoch-${o.id}`}>
                <title>{`${fmtUtc(o.timing.mid.iso_utc)} · ${o.band_id} · available`}</title>
                <rect x={cx - 9} y={16} width={18} height={28} fill="transparent" />
                {isB && <circle cx={cx} cy={30} r={9} className="tl-b" />}
                {isA && <circle cx={cx} cy={30} r={9} className="tl-a" />}
                <circle cx={cx} cy={30} r={shown ? 5.5 : 4.5} className={shown ? 'tl-dot tl-dot-shown' : 'tl-dot'} />
                {(isA || isB) && (
                  <text x={cx} y={12} textAnchor="middle" className="tl-ab">
                    {isA && isB ? 'A=B' : isA ? 'A' : 'B'}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
