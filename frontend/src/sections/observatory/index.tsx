/* Observatory: Explore (default) and Analyze share dataset, band, epoch, selection, and view. */
import { useEffect, useMemo, useState } from 'react'
import type { Dataset, Observation } from '../../api/types'
import { fmtDate } from '../../lib/format'
import { useAppStore } from '../../state/app'
import { availableObservations, nativeFrameId, registeredFrameId, useObservatoryStore } from '../../state/observatory'
import { Callout, ErrorState, LoadingState, OriginBadge, Segmented, StatusPill } from '../../components/ui'
import { AnalyzeTabs } from '../../components/observatory/Analyze'
import { Inspector, SourceSummary } from '../../components/observatory/Inspector'
import { SkyCanvas, type CanvasOverlays } from '../../components/observatory/SkyCanvas'
import { Timeline } from '../../components/observatory/Timeline'
import { Toolbar } from '../../components/observatory/Toolbar'
import { catalogPoints, measurementAt, modelGeometry, sourcePointsAt, truthFor, truthPointAt, useBandLimits, useGridWcs } from '../../components/observatory/derive'
import { differenceLimits, usePlane } from '../../components/observatory/pixels'
import { ObservedObservatory } from './Observed'
import './observatory.css'

export function Observatory() {
  const s = useObservatoryStore()
  const section = useAppStore((a) => a.section)
  useEffect(() => {
    void s.init()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (s.datasets.status === 'error') {
    return (
      <div className="page">
        <ErrorState title="Cannot reach the SkyShift API" message={s.datasets.message} onRetry={() => location.reload()} />
      </div>
    )
  }
  if (s.dataset.status === 'error') {
    const others = s.datasets.status === 'ready' ? s.datasets.data.filter((d) => d.id !== s.datasetId) : []
    return (
      <div className="page">
        <ErrorState
          title="Dataset unavailable"
          message={s.dataset.message}
          onRetry={() => {
            const id = s.datasetId
            if (!id) return
            useObservatoryStore.setState({ datasetId: null, dataset: { status: 'idle' } })
            void s.selectDataset(id)
          }}
        />
        {others.length > 0 && (
          <div className="row" style={{ justifyContent: 'center', marginTop: 12 }}>
            <button type="button" className="btn btn-sm" onClick={() => void s.selectDataset(others[0].id)} data-testid="open-other-dataset">
              Open {others[0].title}
            </button>
          </div>
        )}
      </div>
    )
  }
  if (s.dataset.status !== 'ready' || s.datasets.status !== 'ready' || s.providers.status !== 'ready') {
    const summary = s.datasets.status === 'ready' ? s.datasets.data.find((d) => d.id === s.datasetId) : undefined
    return (
      <div className="page">
        <LoadingState
          label={
            summary?.origin === 'observed'
              ? 'Reading the cached SPHEREx cutouts, checking them against the manifest and reprojecting them for display (about 10 s on first load)…'
              : 'Preparing the synthetic investigation: generating frames, detecting sources, registering every epoch (about 10 s on first load)…'
          }
        />
      </div>
    )
  }
  const active = section === 'observatory'
  return s.dataset.data.origin === 'observed' ? <ObservedObservatory dataset={s.dataset.data} active={active} /> : <ObservatoryReady dataset={s.dataset.data} active={active} />
}

function ObservatoryReady({ dataset, active }: { dataset: Dataset; active: boolean }) {
  const s = useObservatoryStore()
  const wcs = useGridWcs(dataset)
  const [blinkPhase, setBlinkPhase] = useState(false)
  const avail = availableObservations(dataset, s.bandId)
  const obsA = dataset.observations.find((o) => o.id === s.epochObsId) ?? null
  const obsB = dataset.observations.find((o) => o.id === s.compareObsId) ?? null
  const displayed: Observation | null = s.playback.blink && blinkPhase ? obsB : obsA
  const limits = useBandLimits(s.datasetId, dataset, s.bandId, s.display.pLow, s.display.pHigh)

  // Playback over real frames only; blink alternates A and B. Paused while the section is hidden.
  useEffect(() => {
    if (!active && (s.playback.playing || s.playback.blink)) s.setPlayback({ playing: false, blink: false })
  }, [active]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!s.playback.playing) return
    const id = setInterval(() => useObservatoryStore.getState().step(1), s.playback.intervalMs)
    return () => clearInterval(id)
  }, [s.playback.playing, s.playback.intervalMs])
  useEffect(() => {
    if (!s.playback.blink) {
      setBlinkPhase(false)
      return
    }
    const id = setInterval(() => setBlinkPhase((p) => !p), s.playback.intervalMs)
    return () => clearInterval(id)
  }, [s.playback.blink, s.playback.intervalMs])

  // Keyboard shortcuts for the section (ignored while typing in a field).
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, [contenteditable="true"], .sky-canvas, .timeline-track, [role="radiogroup"], [role="tablist"]')) return
      if (e.key === 'ArrowRight' || e.key === '.') s.step(1)
      else if (e.key === 'ArrowLeft' || e.key === ',') s.step(-1)
      else if (e.key === 'b' || e.key === 'B') s.setPlayback({ blink: !s.playback.blink, playing: false })
      else if (e.key === 'p' || e.key === 'P') s.setPlayback({ playing: !s.playback.playing, blink: false })
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, s])

  const sources = s.sources.status === 'ready' ? s.sources.data : null
  const source = sources?.find((x) => x.id === s.selectedSourceId) ?? null
  const ms = s.measurements.status === 'ready' ? s.measurements.data.measurements : null
  const fit = s.fit.status === 'ready' ? s.fit.data : null
  const truthMatch = s.display.truth && s.truth.status === 'ready' ? truthFor(s.truth.data, source) : null

  const overlaysFor = (obs: Observation | null): CanvasOverlays => {
    const model = s.display.model && s.selectedSourceId ? modelGeometry(fit, wcs, obs?.timing.mid.mjd_tdb ?? null) : null
    return {
      modelPath: model?.path ?? null,
      modelNow: model?.now ?? null,
      truthNow: s.mode === 'analyze' && truthMatch ? truthPointAt(truthMatch, obs, wcs) : null,
      catalog: s.mode === 'analyze' && s.display.catalog && s.catalogOverlay.status === 'ready' ? catalogPoints(s.catalogOverlay.data, wcs) : null,
    }
  }

  useEffect(() => {
    if (s.mode === 'analyze' && s.display.catalog) void s.loadCatalogOverlay()
  }, [s.mode, s.display.catalog, s.epochObsId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (s.mode === 'analyze' && s.display.compareView === 'difference') void s.loadDifference()
  }, [s.mode, s.display.compareView, s.epochObsId, s.compareObsId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!wcs || !s.bandId) return null
  const gridShape = dataset.common_grid.shape as [number, number]
  const bandLabel = dataset.bands.find((b) => b.id === s.bandId)?.label ?? s.bandId

  const canvasFor = (obs: Observation | null, label: string, testId: string, minHeight: number) => (
    <CanvasForObservation
      key={testId}
      dataset={dataset}
      obs={obs}
      label={label}
      bandLabel={bandLabel}
      testId={testId}
      minHeight={minHeight}
      limits={limits}
      overlays={overlaysFor(obs)}
      wcs={wcs}
      gridShape={gridShape}
    />
  )

  return (
    <div className={`page obs-page mode-${s.mode}`} data-mode={s.mode}>
      <Toolbar dataset={dataset} datasets={s.datasets.status === 'ready' ? s.datasets.data : []} providers={s.providers.status === 'ready' ? s.providers.data : []} />
      {s.restoredFrom && (
        <Callout tone="info" role="status">
          Restored from evidence record <span className="mono">{s.restoredFrom.slice(0, 8)}</span>: saved measurements, exclusions and fit are shown.
        </Callout>
      )}
      <div className="obs-layout">
        <div className="obs-main">
          {s.mode === 'explore' ? (
            canvasFor(displayed, s.playback.blink && blinkPhase ? 'B' : 'A', 'sky-explore', 520)
          ) : (
            <div className="compare">
              <div className="compare-bar">
                <Segmented
                  ariaLabel="Comparison view"
                  value={s.display.compareView}
                  onChange={(v) => s.setDisplay({ compareView: v })}
                  options={[
                    { value: 'side-by-side', label: 'Side by side' },
                    { value: 'difference', label: 'Difference B − A' },
                  ]}
                  testId="compare-view"
                />
                <label className="field compare-pick">
                  <span className="field-label">A</span>
                  <select className="select" value={s.epochObsId ?? ''} onChange={(e) => s.setEpoch(e.target.value)} aria-label="Epoch A">
                    {avail.map((o) => (
                      <option key={o.id} value={o.id}>
                        {fmtDate(o.timing.mid.iso_utc)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field compare-pick">
                  <span className="field-label">B</span>
                  <select className="select" value={s.compareObsId ?? ''} onChange={(e) => s.setCompare(e.target.value)} aria-label="Epoch B" data-testid="compare-select">
                    {avail.map((o) => (
                      <option key={o.id} value={o.id}>
                        {fmtDate(o.timing.mid.iso_utc)}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="small muted">Both frames registered to the common sky grid (stationary background aligned).</span>
              </div>
              {s.display.compareView === 'side-by-side' ? (
                <div className="compare-pair">
                  {canvasFor(obsA, 'A', 'sky-a', 360)}
                  {canvasFor(obsB, 'B', 'sky-b', 360)}
                </div>
              ) : (
                <DifferenceView dataset={dataset} wcs={wcs} gridShape={gridShape} />
              )}
              <div className="row compare-toggles">
                <label className="toggle">
                  <input type="checkbox" role="switch" checked={s.display.model} onChange={(e) => s.setDisplay({ model: e.target.checked })} /> Model path
                </label>
                <label className="toggle">
                  <input type="checkbox" role="switch" checked={s.display.catalog} onChange={(e) => s.setDisplay({ catalog: e.target.checked })} /> Catalog (propagated)
                </label>
                {dataset.origin === 'simulated' && (
                  <label className="toggle" title="Injected positions used to generate the pixels; never a measurement.">
                    <input
                      type="checkbox"
                      role="switch"
                      checked={s.display.truth}
                      onChange={(e) => {
                        s.setDisplay({ truth: e.target.checked })
                        if (e.target.checked) void s.loadTruth()
                      }}
                    />{' '}
                    Simulation truth
                  </label>
                )}
                <label className="toggle">
                  <input type="checkbox" role="switch" checked={s.display.grid} onChange={(e) => s.setDisplay({ grid: e.target.checked })} /> Coordinate grid
                </label>
              </div>
            </div>
          )}
          <Timeline
            dataset={dataset}
            bandId={s.bandId}
            epochObsId={s.epochObsId}
            compareObsId={s.compareObsId}
            displayedObsId={displayed?.id ?? null}
            showCompare
            playback={s.playback}
            onSelectEpoch={s.setEpoch}
            onStep={s.step}
            onPlayback={s.setPlayback}
          />
          <DisplayControls />
        </div>
        {s.mode === 'explore' ? (
          <Inspector
            dataset={dataset}
            source={source}
            measurement={measurementAt(ms, displayed)}
            measurementsLoading={s.measurements.status === 'loading'}
            observation={displayed}
            onAnalyze={() => s.setMode('analyze')}
          />
        ) : (
          <aside className="inspector" aria-label="Selected source" data-testid="inspector">
            <section className="insp-block">
              <div className="eyebrow">Selected source · epoch A</div>
              {source ? (
                <SourceSummary source={source} measurement={measurementAt(ms, obsA)} measurementsLoading={s.measurements.status === 'loading'} />
              ) : (
                <p className="small muted">Click a source in either image.</p>
              )}
            </section>
          </aside>
        )}
      </div>
      {s.mode === 'analyze' && <AnalyzeTabs dataset={dataset} />}
    </div>
  )
}

function CanvasForObservation(props: {
  dataset: Dataset
  obs: Observation | null
  label: string
  bandLabel: string
  testId: string
  minHeight: number
  limits: ReturnType<typeof useBandLimits>
  overlays: CanvasOverlays
  wcs: NonNullable<ReturnType<typeof useGridWcs>>
  gridShape: [number, number]
}) {
  const s = useObservatoryStore()
  const { dataset, obs } = props
  const frameId = registeredFrameId(obs)
  const plane = usePlane(s.datasetId, frameId)
  const sources = s.sources.status === 'ready' ? s.sources.data : null
  const points = useMemo(() => sourcePointsAt(sources, nativeFrameId(obs), props.wcs), [sources, obs, props.wcs])
  return (
    <div className="canvas-frame">
      <SkyCanvas
        plane={plane}
        limits={props.limits}
        stretch={s.display.stretch}
        wcs={props.wcs}
        gridShape={props.gridShape}
        view={s.view}
        onView={s.setView}
        sources={points}
        selectedId={s.selectedSourceId}
        hoverId={s.hoverSourceId}
        onSelect={s.selectSource}
        onHover={s.setHover}
        overlays={props.overlays}
        showGrid={s.display.grid}
        showLabels={s.display.labels}
        valueUnit="e⁻"
        minHeight={props.minHeight}
        testId={props.testId}
        ariaLabel={`Sky image ${props.label}: ${obs ? fmtDate(obs.timing.mid.iso_utc) : 'no frame'}, ${props.bandLabel}`}
        cornerTopLeft={
          <span className="row" style={{ gap: 6 }}>
            <span className="canvas-ab">{props.label}</span>
            {dataset.origin === 'simulated' ? <OriginBadge origin="simulated" label="Simulated pixels" /> : <OriginBadge origin="observed" />}
            <span>{props.bandLabel}</span>
          </span>
        }
        cornerBottomLeft={
          <span>
            {obs ? `${obs.timing.mid.iso_utc?.replace('T', ' ').slice(0, 19)} UTC` : 'No frame'} · registered display product
          </span>
        }
      />
    </div>
  )
}

function DifferenceView({ dataset, wcs, gridShape }: { dataset: Dataset; wcs: NonNullable<ReturnType<typeof useGridWcs>>; gridShape: [number, number] }) {
  const s = useObservatoryStore()
  const diff = s.difference
  const plane = diff.status === 'ready' && diff.data.plane ? { status: 'ready' as const, plane: diff.data.plane } : diff.status === 'error' ? { status: 'error' as const, message: diff.message } : { status: 'loading' as const }
  const limits = diff.status === 'ready' && diff.data.plane ? differenceLimits(diff.data.plane) : null
  const sources = s.sources.status === 'ready' ? s.sources.data : null
  const obsA = dataset.observations.find((o) => o.id === s.epochObsId) ?? null
  const points = useMemo(() => sourcePointsAt(sources, nativeFrameId(obsA), wcs), [sources, obsA, wcs])
  if (diff.status === 'ready' && !diff.data.info.compatible) {
    return (
      <div className="diff-refused" data-testid="difference-refused">
        <Callout tone="warning" role="status">
          <strong>No difference preview for these frames.</strong> {diff.data.info.reasons.join(' ')}
        </Callout>
      </div>
    )
  }
  const info = diff.status === 'ready' ? diff.data.info : null
  return (
    <div className="diff-view">
      <SkyCanvas
        plane={plane}
        limits={limits}
        stretch="linear"
        mode="difference"
        wcs={wcs}
        gridShape={gridShape}
        view={s.view}
        onView={s.setView}
        sources={points}
        selectedId={s.selectedSourceId}
        hoverId={s.hoverSourceId}
        onSelect={s.selectSource}
        onHover={s.setHover}
        showGrid={s.display.grid}
        showLabels={s.display.labels}
        valueUnit="e⁻"
        minHeight={380}
        testId="sky-difference"
        ariaLabel="Difference preview, B minus A"
        cornerTopLeft={
          <span className="row" style={{ gap: 6 }}>
            <OriginBadge origin="derived_measurement" label="Derived preview" />
            <span>B − A · grey = 0, dark = negative, bright = positive</span>
          </span>
        }
        cornerBottomLeft={<span>Display-only: PSFs not matched, interpolated noise; no significance implied</span>}
      />
      {info && (
        <div className="diff-checks small" data-testid="difference-checks">
          <StatusPill status={info.checks.same_band ? 'ok' : 'failed'} label="same band" />
          <StatusPill status={info.checks.both_registered ? 'ok' : 'failed'} label="both registered" />
          <span>overlap {(Number(info.checks.overlap_fraction) * 100).toFixed(0)}%</span>
          <span>Δt {Number(info.checks.time_separation_days).toFixed(0)} d</span>
          <span>
            registration rms {Number(info.checks.registration_rms_a_mas).toFixed(0)} / {Number(info.checks.registration_rms_b_mas).toFixed(0)} mas
          </span>
        </div>
      )}
    </div>
  )
}

function DisplayControls() {
  const s = useObservatoryStore()
  return (
    <div className="display-controls" aria-label="Display settings (display only; measurements are unaffected)">
      <Segmented
        ariaLabel="Display stretch"
        value={s.display.stretch}
        onChange={(v) => s.setDisplay({ stretch: v })}
        options={[
          { value: 'asinh', label: 'asinh' },
          { value: 'linear', label: 'linear' },
          { value: 'log', label: 'log' },
        ]}
      />
      <label className="field-inline">
        <span className="small muted">Upper limit</span>
        <select className="select" value={s.display.pHigh} onChange={(e) => s.setDisplay({ pHigh: Number(e.target.value) })} aria-label="Upper display percentile">
          {[99, 99.5, 99.7, 99.9, 100].map((p) => (
            <option key={p} value={p}>
              {p}%
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="btn btn-sm" onClick={() => s.setView({ zoom: null })} data-testid="zoom-fit">
        Fit view
      </button>
      <button type="button" className="btn btn-sm btn-icon" aria-label="Zoom in" onClick={() => s.setView({ zoom: (s.view.zoom ?? 3) * 1.4 })} data-testid="zoom-in">
        +
      </button>
      <button type="button" className="btn btn-sm btn-icon" aria-label="Zoom out" onClick={() => s.setView({ zoom: Math.max(0.5, (s.view.zoom ?? 3) / 1.4) })}>
        −
      </button>
      <label className="toggle">
        <input type="checkbox" role="switch" checked={s.display.grid} onChange={(e) => s.setDisplay({ grid: e.target.checked })} /> Grid
      </label>
      <span className="small faint">Display stretch only · shortcuts: ← → step, P play, B blink</span>
    </div>
  )
}
