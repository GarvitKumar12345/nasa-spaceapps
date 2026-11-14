/* Observatory for observed archive data (SPHEREx): a read-only viewer.
 * Explore and Analyze share the same store state as the synthetic view. Blink/compare is offered
 * only within a wavelength-compatibility group; measurement, fitting and difference imaging are
 * shown as unavailable with the dataset's own stated reasons. */
import { useEffect, useMemo, useState } from 'react'
import type { Band, Dataset, FileCheck, Observation } from '../../api/types'
import { fmt, fmtUtc } from '../../lib/format'
import { FLAG_CLASS_LABEL, classMasks, flagClass, overlayColour } from '../../lib/spherexFlags'
import { useAppStore } from '../../state/app'
import { availableObservations, blinkState, displayFrameId, useObservatoryStore } from '../../state/observatory'
import { Callout, EmptyState, KV, OriginBadge, QualityTag, Segmented, StatusPill, TabPanel, Tabs } from '../../components/ui'
import { SkyCanvas } from '../../components/observatory/SkyCanvas'
import { Timeline } from '../../components/observatory/Timeline'
import { Toolbar } from '../../components/observatory/Toolbar'
import { useBandLimits, useGridWcs } from '../../components/observatory/derive'
import { renderMaskOverlay, usePlane, type StretchLimits } from '../../components/observatory/pixels'
import type { TanWcs } from '../../lib/tanwcs'

const CHECK_STATUS: Record<FileCheck['status'], string> = { pass: 'passed', warn: 'warning', fail: 'failed' }

function bandOf(dataset: Dataset, obs: Observation | null): Band | null {
  return dataset.bands.find((b) => b.id === obs?.band_id) ?? null
}

function groupMean(dataset: Dataset, band: Band | null): number | null {
  if (!band?.compatibility) return null
  const lams = band.compatibility.member_observation_ids
    .map((id) => dataset.observations.find((o) => o.id === id)?.archive?.local_wavelength_um)
    .filter((v): v is number => typeof v === 'number')
  return lams.length ? lams.reduce((a, b) => a + b, 0) / lams.length : null
}

export function ObservedObservatory({ dataset, active }: { dataset: Dataset; active: boolean }) {
  const s = useObservatoryStore()
  const wcs = useGridWcs(dataset)
  const [blinkPhase, setBlinkPhase] = useState(false)
  const avail = availableObservations(dataset, s.bandId)
  const blink = blinkState(dataset, s.bandId)
  const obsA = dataset.observations.find((o) => o.id === s.epochObsId) ?? null
  const obsB = dataset.observations.find((o) => o.id === s.compareObsId) ?? null
  const displayed: Observation | null = s.playback.blink && blinkPhase && blink.ok ? obsB : obsA
  const limits = useBandLimits(s.datasetId, dataset, s.bandId, s.display.pLow, s.display.pHigh)

  useEffect(() => {
    if ((!active || !blink.ok) && (s.playback.playing || s.playback.blink)) s.setPlayback({ playing: false, blink: false })
  }, [active, blink.ok]) // eslint-disable-line react-hooks/exhaustive-deps
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
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, [contenteditable="true"], .sky-canvas, .timeline-track, [role="radiogroup"], [role="tablist"]')) return
      if (e.key === 'ArrowRight' || e.key === '.') s.step(1)
      else if (e.key === 'ArrowLeft' || e.key === ',') s.step(-1)
      else if ((e.key === 'b' || e.key === 'B') && blink.ok) s.setPlayback({ blink: !s.playback.blink, playing: false })
      else if ((e.key === 'p' || e.key === 'P') && blink.ok) s.setPlayback({ playing: !s.playback.playing, blink: false })
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, s, blink.ok])

  if (!wcs || !s.bandId) return null
  const gridShape = dataset.common_grid.shape as [number, number]
  const band = dataset.bands.find((b) => b.id === s.bandId) ?? null
  const [mx, my] = wcs.skyToPixel(dataset.field.center.ra_deg, dataset.field.center.dec_deg)
  const marker = { x: mx, y: my, label: 'field centre (query position)' }
  const canvas = (obs: Observation | null, label: string, testId: string, minHeight: number) => (
    <ObservedCanvas key={testId} dataset={dataset} obs={obs} label={label} testId={testId} minHeight={minHeight} limits={limits} wcs={wcs} gridShape={gridShape} marker={marker} />
  )
  const nUnavailable = dataset.observations.filter((o) => o.status !== 'available').length

  return (
    <div className={`page obs-page mode-${s.mode}`} data-mode={s.mode} data-origin="observed">
      <Toolbar dataset={dataset} datasets={s.datasets.status === 'ready' ? s.datasets.data : []} providers={s.providers.status === 'ready' ? s.providers.data : []} />
      <Callout tone="info">
        <span data-testid="observed-banner">
          <strong>Real SPHEREx {dataset.archive_query?.collection ?? dataset.release} data · read-only viewer.</strong> Frames are aligned for display with the archive's WCS only (not
          registered by SkyShift). Source measurement, motion fits and difference images are unavailable for observed data in this build.
          {nUnavailable > 0 && ` ${nUnavailable} selected observation(s) are not available; see the timeline and the Observations tab.`}
        </span>
      </Callout>
      <div className="obs-layout">
        <div className="obs-main">
          {s.mode === 'explore' ? (
            canvas(displayed, s.playback.blink && blinkPhase && blink.ok ? 'B' : 'A', 'sky-explore', 520)
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
                        {fmtUtc(o.timing.mid.iso_utc, false)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field compare-pick">
                  <span className="field-label">B</span>
                  <select className="select" value={s.compareObsId ?? ''} onChange={(e) => s.setCompare(e.target.value)} aria-label="Epoch B" data-testid="compare-select" disabled={!blink.ok}>
                    {avail.map((o) => (
                      <option key={o.id} value={o.id}>
                        {fmtUtc(o.timing.mid.iso_utc, false)}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="small muted">Same detector and local wavelength at the field centre; aligned by the archive WCS (not SkyShift-registered).</span>
              </div>
              {s.display.compareView === 'side-by-side' ? (
                <div className="compare-pair">
                  {canvas(obsA, 'A', 'sky-a', 360)}
                  {blink.ok ? canvas(obsB, 'B', 'sky-b', 360) : <EmptyState title="No comparison frame">{blink.reason}</EmptyState>}
                </div>
              ) : (
                <div className="diff-refused" data-testid="difference-unavailable">
                  <Callout tone="warning" role="status">
                    <strong>Difference imaging is unavailable for observed data.</strong>{' '}
                    {dataset.capabilities.find((c) => c.id === 'difference_imaging')?.reason}
                  </Callout>
                </div>
              )}
              <div className="row compare-toggles">
                <label className="toggle">
                  <input type="checkbox" role="switch" checked={s.display.flags} onChange={(e) => s.setDisplay({ flags: e.target.checked })} data-testid="flags-toggle-analyze" /> Archive flags
                </label>
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
            showCompare={blink.ok}
            playback={s.playback}
            onSelectEpoch={s.setEpoch}
            onStep={s.step}
            onPlayback={s.setPlayback}
            blinkDisabledReason={blink.ok ? null : blink.reason}
          />
          <ObservedDisplayControls />
        </div>
        <ObservedInspector dataset={dataset} obs={s.mode === 'explore' ? displayed : obsA} role={s.mode === 'explore' ? (displayed?.id === obsB?.id && displayed?.id !== obsA?.id ? 'B' : 'A') : 'A'} band={band} />
      </div>
      {s.mode === 'analyze' && <ObservedAnalyze dataset={dataset} />}
    </div>
  )
}

function ObservedCanvas(props: {
  dataset: Dataset
  obs: Observation | null
  label: string
  testId: string
  minHeight: number
  limits: StretchLimits | null
  wcs: TanWcs
  gridShape: [number, number]
  marker: { x: number; y: number; label: string }
}) {
  const s = useObservatoryStore()
  const { dataset, obs } = props
  const frameId = obs?.status === 'available' ? displayFrameId(obs) : null
  const plane = usePlane(s.datasetId, frameId)
  const mask = usePlane(s.datasetId, s.display.flags ? frameId : null, 'mask')
  const frame = dataset.frames.find((f) => f.id === frameId) ?? null
  const overlay = useMemo(() => {
    if (!s.display.flags || mask.status !== 'ready' || !frame) return null
    const masks = classMasks(frame.mask_bits)
    return renderMaskOverlay(mask.plane, (w) => overlayColour(w, masks))
  }, [s.display.flags, mask, frame])
  const band = bandOf(dataset, obs)
  const lam = obs?.archive?.local_wavelength_um
  return (
    <div className="canvas-frame" data-frame={frameId ?? ''}>
      <SkyCanvas
        plane={plane}
        limits={props.limits}
        stretch={s.display.stretch}
        wcs={props.wcs}
        gridShape={props.gridShape}
        view={s.view}
        onView={s.setView}
        sources={[]}
        selectedId={null}
        hoverId={null}
        onSelect={() => undefined}
        onHover={() => undefined}
        showGrid={s.display.grid}
        showLabels={s.display.labels}
        valueUnit="MJy/sr"
        minHeight={props.minHeight}
        testId={props.testId}
        overlayImage={overlay}
        marker={props.marker}
        ariaLabel={`SPHEREx image ${props.label}: ${obs ? fmtUtc(obs.timing.mid.iso_utc) : 'no frame'}, ${band?.label ?? ''}`}
        cornerTopLeft={
          <span className="row" style={{ gap: 6 }}>
            <span className="canvas-ab">{props.label}</span>
            <OriginBadge origin="observed" label="Observed · SPHEREx" />
            <span>{band?.label}</span>
          </span>
        }
        cornerBottomLeft={
          <span data-testid={`${props.testId}-caption`}>
            {obs ? `${fmtUtc(obs.timing.mid.iso_utc)} UTC` : 'No frame'}
            {lam != null ? ` · λ ${lam.toFixed(4)} µm at centre` : ''} · archive-WCS display, not registered
            {obs && obs.status !== 'available' ? ` · ${obs.status}` : ''}
          </span>
        }
      />
    </div>
  )
}

function ObservedDisplayControls() {
  const s = useObservatoryStore()
  return (
    <div className="display-controls" aria-label="Display settings (display only; archive arrays are unaffected)">
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
        <input type="checkbox" role="switch" checked={s.display.flags} onChange={(e) => s.setDisplay({ flags: e.target.checked })} data-testid="flags-toggle" /> Archive flags
      </label>
      <label className="toggle">
        <input type="checkbox" role="switch" checked={s.display.grid} onChange={(e) => s.setDisplay({ grid: e.target.checked })} /> Grid
      </label>
      <span className="small faint">
        <span className="flag-swatch flag-swatch-mask" aria-hidden /> masked for photometry <span className="flag-swatch flag-swatch-caution" aria-hidden /> warning flags (ES Sect. 3.3) · MJy/sr, display stretch only
      </span>
    </div>
  )
}

function FlagChips({ names }: { names: string[] }) {
  if (!names.length) return <p className="small muted">No flags set within 2.5 px.</p>
  return (
    <ul className="flag-chips">
      {names.map((n) => {
        const c = flagClass(n)
        return (
          <li key={n} className={`flag-chip flag-${c}`} title={FLAG_CLASS_LABEL[c]} data-flag={n}>
            {n} <span className="faint">· {FLAG_CLASS_LABEL[c]}</span>
          </li>
        )
      })}
    </ul>
  )
}

function ObservedInspector({ dataset, obs, role, band }: { dataset: Dataset; obs: Observation | null; role: string; band: Band | null }) {
  const a = obs?.archive ?? null
  const mean = groupMean(dataset, bandOf(dataset, obs) ?? band)
  const checks = a?.validation ?? []
  const counts = { pass: checks.filter((c) => c.status === 'pass').length, warn: checks.filter((c) => c.status === 'warn').length, fail: checks.filter((c) => c.status === 'fail').length }
  const hq = a?.header_quality ?? {}
  return (
    <aside className="inspector" aria-label="Observation details" data-testid="obs-inspector">
      <section className="insp-block">
        <div className="eyebrow">Observation · {role}</div>
        {!obs || !a ? (
          <p className="small muted">No observation selected.</p>
        ) : (
          <>
            <div className="row" style={{ gap: 6 }}>
              <OriginBadge origin="observed" label={`Observed · ${a.release}`} />
              <QualityTag quality={obs.quality} />
              {obs.status !== 'available' && <StatusPill status={obs.status === 'failed' ? 'failed' : 'unavailable'} label={obs.status} />}
            </div>
            {obs.status !== 'available' && (
              <Callout tone="warning" role="status">
                <span data-testid="obs-status-reason">{obs.status_reason}</span>
              </Callout>
            )}
            <dl className="kvs">
              <KV k="Mid-exposure (UTC)" mono>
                <span data-testid="obs-date">{fmtUtc(obs.timing.mid.iso_utc)}</span>
              </KV>
              <KV k="Exposure" title={obs.timing.mid_derivation}>
                {fmt(obs.timing.exposure_s, 1)} s
              </KV>
              <KV k="Observation ID" mono>
                {a.obs_id}
              </KV>
              <KV k="Detector">
                {obs.detector} · {a.bandpass_name}
              </KV>
              <KV k="λ at field centre" title={a.wavelength_method}>
                <span data-testid="obs-wavelength">
                  {a.local_wavelength_um != null ? `${a.local_wavelength_um.toFixed(4)} µm` : 'not available'}
                  {a.local_bandwidth_um != null ? ` (bandwidth ${a.local_bandwidth_um.toFixed(4)} µm)` : ''}
                </span>
              </KV>
              {mean != null && a.local_wavelength_um != null && a.local_bandwidth_um != null && (
                <KV k="Δλ from group mean">
                  {(1000 * (a.local_wavelength_um - mean)).toFixed(2)} nm = {((a.local_wavelength_um - mean) / a.local_bandwidth_um).toFixed(3)} × bandwidth
                </KV>
              )}
            </dl>
            <p className="small faint">WCS-WAVE lookup at the field-centre pixel: visualization-grade (~1 nm). Science would need the CWAVE/CBAND calibration product.</p>
          </>
        )}
      </section>
      {a && (
        <section className="insp-block" data-testid="obs-flags">
          <div className="eyebrow">Archive flags within 2.5 px of the field centre</div>
          <FlagChips names={a.flags_near_query} />
        </section>
      )}
      {a && (
        <section className="insp-block" data-testid="obs-quality">
          <div className="eyebrow">Archive quality and file checks</div>
          <dl className="kvs">
            <KV k="FINAST" title="0 good, 1 partial, >1 poor (ES Sect. 3.2.8)">
              {String(hq.FINAST ?? '—')}
            </KV>
            <KV k="L2 DQA">{String(hq.L2DQAFLG ?? '—')}</KV>
            {hq.PSF_FWHM != null && <KV k="PSF FWHM (median)">{fmt(Number(hq.PSF_FWHM), 2)}″</KV>}
          </dl>
          <div className="row" style={{ gap: 6 }} data-testid="obs-checks">
            <StatusPill status="passed" label={`${counts.pass} checks passed`} />
            {counts.warn > 0 && <StatusPill status="warning" label={`${counts.warn} warnings`} />}
            {counts.fail > 0 && <StatusPill status="failed" label={`${counts.fail} failed`} />}
          </div>
          {checks.length > 0 && (
            <details className="obs-details">
              <summary>File checks against the documented DR1 format</summary>
              <ul className="check-list">
                {checks.map((c) => (
                  <li key={c.id}>
                    <StatusPill status={CHECK_STATUS[c.status]} label={c.id.replace(/_/g, ' ')} /> <span className="small">{c.detail}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
      {a && (
        <section className="insp-block" data-testid="obs-provenance">
          <div className="eyebrow">Provenance</div>
          <dl className="kvs">
            <KV k="Collection">{a.collection}</KV>
            <KV k="Processing" mono>
              {a.processing_tag}
              {a.pipeline_version ? ` · pipeline ${a.pipeline_version}` : ''}
            </KV>
            <KV k="Retrieved (UTC)" mono>
              {a.retrieved_utc ? fmtUtc(a.retrieved_utc) : '—'}
            </KV>
            <KV k="sha256" mono title={a.sha256 ?? ''}>
              {a.sha256 ? `${a.sha256.slice(0, 16)}…` : '—'}
            </KV>
          </dl>
          {a.cutout_url && (
            <a className="small mono obs-url" href={a.cutout_url} target="_blank" rel="noreferrer">
              IRSA cutout URL
            </a>
          )}
        </section>
      )}
    </aside>
  )
}

type ObsTab = 'observations' | 'compatibility' | 'flags' | 'archive' | 'unavailable'

function ObservedAnalyze({ dataset }: { dataset: Dataset }) {
  const [tab, setTab] = useState<ObsTab>('observations')
  return (
    <section className="analyze-tabs panel" aria-label="Analysis of observed data">
      <Tabs<ObsTab>
        idPrefix="ob"
        ariaLabel="Observed-data views"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'observations', label: 'Observations' },
          { id: 'compatibility', label: 'Wavelength compatibility' },
          { id: 'flags', label: 'Flags & quality' },
          { id: 'archive', label: 'Archive & provenance' },
          { id: 'unavailable', label: 'Unavailable analyses' },
        ]}
      />
      <TabPanel idPrefix="ob" id={tab}>
        <div className="analyze-body">
          {tab === 'observations' ? (
            <ObservationsTable dataset={dataset} />
          ) : tab === 'compatibility' ? (
            <CompatibilityTab dataset={dataset} />
          ) : tab === 'flags' ? (
            <FlagsTab dataset={dataset} />
          ) : tab === 'archive' ? (
            <ArchiveTab dataset={dataset} />
          ) : (
            <UnavailableTab dataset={dataset} />
          )}
        </div>
      </TabPanel>
    </section>
  )
}

function ObservationsTable({ dataset }: { dataset: Dataset }) {
  const s = useObservatoryStore()
  const rows = [...dataset.observations].sort((a, b) => (a.band_id === b.band_id ? a.timing.mid.mjd_tdb - b.timing.mid.mjd_tdb : a.band_id < b.band_id ? -1 : 1))
  return (
    <div className="table-wrap">
      <table className="table" data-testid="obs-table">
        <thead>
          <tr>
            <th>Group</th>
            <th>Mid-exposure (UTC)</th>
            <th>Observation ID</th>
            <th>Det.</th>
            <th className="r nocase">λ (µm)</th>
            <th className="r nocase">Bandwidth (µm)</th>
            <th>Flags near centre</th>
            <th>FINAST / DQA</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => {
            const a = o.archive
            const masked = (a?.flags_near_query ?? []).filter((n) => flagClass(n) === 'photometry_mask')
            const band = dataset.bands.find((b) => b.id === o.band_id)
            return (
              <tr key={o.id} data-obs-id={o.id} className={o.id === s.epochObsId ? 'row-selected' : undefined}>
                <td>
                  <button type="button" className="link-btn" onClick={() => { s.setBand(o.band_id); s.setEpoch(o.id) }} title="Show in the viewer">
                    {band?.label ?? o.band_id}
                  </button>
                </td>
                <td className="mono">{fmtUtc(o.timing.mid.iso_utc)}</td>
                <td className="mono">{a?.obs_id}</td>
                <td>{o.detector}</td>
                <td className="r mono">{a?.local_wavelength_um != null ? a.local_wavelength_um.toFixed(4) : '—'}</td>
                <td className="r mono">{a?.local_bandwidth_um != null ? a.local_bandwidth_um.toFixed(4) : '—'}</td>
                <td className="small">{masked.length ? masked.join(', ') : 'none masked'}</td>
                <td>
                  {String(a?.header_quality.FINAST ?? '—')} / {String(a?.header_quality.L2DQAFLG ?? '—')}
                </td>
                <td>
                  <StatusPill status={o.status === 'available' ? 'ok' : o.status === 'failed' ? 'failed' : 'unavailable'} label={o.status} title={o.status_reason ?? undefined} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function CompatibilityTab({ dataset }: { dataset: Dataset }) {
  const rule = dataset.bands[0]?.compatibility?.rule
  return (
    <div className="stack">
      <p className="small muted">
        Rule: {rule}. Wavelength depends on detector position, so it is evaluated at the field-centre pixel of every frame; the detector number alone never makes two frames comparable.
      </p>
      <div className="table-wrap">
        <table className="table" data-testid="compat-table">
          <thead>
            <tr>
              <th>Group</th>
              <th>Detector</th>
              <th className="r nocase">λ range (µm)</th>
              <th className="r nocase">Max |Δλ| / bandwidth</th>
              <th className="r">Members</th>
              <th>Blink</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {dataset.bands.map((b) => {
              const c = b.compatibility
              const spread = c && c.lambda_min_um != null && c.lambda_max_um != null && c.min_bandwidth_um ? (c.lambda_max_um - c.lambda_min_um) / c.min_bandwidth_um : null
              return (
                <tr key={b.id} data-band={b.id}>
                  <td>{b.label}</td>
                  <td>D{c?.detector}</td>
                  <td className="r mono">{c?.lambda_min_um != null && c.lambda_max_um != null ? `${c.lambda_min_um.toFixed(4)}–${c.lambda_max_um.toFixed(4)}` : '—'}</td>
                  <td className="r mono">{spread != null ? spread.toFixed(3) : '—'}</td>
                  <td className="r">{c?.member_observation_ids.length}</td>
                  <td>
                    <StatusPill status={c?.blinkable ? 'ok' : 'unavailable'} label={c?.blinkable ? 'allowed' : 'not allowed'} />
                  </td>
                  <td className="small">{c?.reason}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function FlagsTab({ dataset }: { dataset: Dataset }) {
  const s = useObservatoryStore()
  const obs = dataset.observations.find((o) => o.id === s.epochObsId) ?? null
  const frame = dataset.frames.find((f) => f.id === obs?.frame_ids.find((id) => id.endsWith(':native'))) ?? null
  if (!frame) return <EmptyState title="No available frame">Select an available observation to see its flag definitions.</EmptyState>
  return (
    <div className="stack">
      <p className="small muted">
        Bit definitions read from this file's FLAGS header (MSKN/MSKM/MSKD keywords) and checked against the Explanatory Supplement Table 16. Classes follow ES Sect. 3.3: pixels with
        “masked for photometry” flags are excluded from SPHEREx photometry; warning flags raise CONTAINS_BAD_PIXEL. SOURCE is informational.
      </p>
      <div className="table-wrap">
        <table className="table" data-testid="flag-table">
          <thead>
            <tr>
              <th className="r">Bit</th>
              <th>Name</th>
              <th>Description (from the file)</th>
              <th>Class</th>
              <th>Near field centre</th>
            </tr>
          </thead>
          <tbody>
            {frame.mask_bits.map((b) => (
              <tr key={b.bit}>
                <td className="r mono">{b.bit}</td>
                <td className="mono">{b.name}</td>
                <td className="small">{b.description}</td>
                <td>
                  <span className={`flag-chip flag-${flagClass(b.name)}`}>{FLAG_CLASS_LABEL[flagClass(b.name)]}</span>
                </td>
                <td>{obs?.archive?.flags_near_query.includes(b.name) ? 'set' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ArchiveTab({ dataset }: { dataset: Dataset }) {
  const q = dataset.archive_query
  if (!q) return <EmptyState title="No archive record">This dataset has no retrieval summary.</EmptyState>
  return (
    <div className="stack" data-testid="archive-summary">
      <dl className="kvs">
        <KV k="Discovery query" mono>
          <span className="obs-url" data-testid="archive-query-url">
            {q.query_url}
          </span>
        </KV>
        <KV k="Collection">{q.collection}</KV>
        <KV k="Retrieved (UTC)" mono>
          {fmtUtc(q.retrieved_utc)}
        </KV>
        <KV k="Products">
          {q.n_rows} discovered · {q.n_superseded} superseded duplicates · {q.n_screened} screened ({q.n_screen_failed} failed) · {q.n_selected} selected · {q.n_downloaded} downloaded ·{' '}
          {q.n_failed} failed
        </KV>
        <KV k="Selection">{q.selection_rule}</KV>
        <KV k="Manifest" mono>
          {q.manifest_path}
        </KV>
      </dl>
      <ul className="obs-list">
        {q.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
      <div className="small">
        <div className="eyebrow">Reproduce</div>
        <pre className="obs-pre">{`cd backend
uv run python -m skyshift.providers.spherex.fetch --field ${dataset.id} --from-manifest   # re-download the recorded selection
uv run python -m skyshift.providers.spherex.fetch --field ${dataset.id}                   # new discovery + screening + selection
uv run pytest tests/test_spherex.py -m live                                              # live IRSA checks`}</pre>
      </div>
      <div className="small">
        <div className="eyebrow">Dataset limitations</div>
        <ul className="obs-list">
          {dataset.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function UnavailableTab({ dataset }: { dataset: Dataset }) {
  const setSection = useAppStore((a) => a.setSection)
  return (
    <div className="stack" data-testid="capabilities">
      <p className="small muted">
        These analyses run on the synthetic training data. For observed SPHEREx pixels they stay unavailable until the listed calibration and compatibility checks are implemented and validated.
      </p>
      <ul className="cap-list">
        {dataset.capabilities.map((c) => (
          <li key={c.id} data-capability={c.id}>
            <div className="row" style={{ gap: 6 }}>
              <StatusPill status={c.status === 'available' ? 'ok' : 'unavailable'} label={c.status} />
              <strong>{c.id.replace(/_/g, ' ')}</strong>
            </div>
            <p className="small">{c.reason}</p>
            {c.requirements.length > 0 && (
              <ul className="obs-list">
                {c.requirements.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
      <button type="button" className="btn btn-sm" onClick={() => setSection('methods')}>
        Methods: checks and limitations
      </button>
    </div>
  )
}
