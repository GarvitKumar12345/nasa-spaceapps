/* Analyze mode: diagnostics tabs (measurements, fit, plots, catalog, registration, provenance). */
import { useEffect, useMemo, useState } from 'react'
import { BookmarkPlus, Orbit, Play } from 'lucide-react'
import type { AstrometricModel, Dataset, ModelFit, SourceMeasurement } from '../../api/types'
import { fmt, fmtDate, fmtPm, fmtUtc } from '../../lib/format'
import { offsetsMas } from '../../lib/tangent'
import { isFitStale, useObservatoryStore } from '../../state/observatory'
import { OffsetTimePlots } from '../astrometry/OffsetTimePlot'
import { SkyTrackPlot } from '../astrometry/SkyTrackPlot'
import { meanPosition } from '../astrometry/common'
import { Callout, EmptyState, ErrorState, KV, LoadingState, OriginBadge, Panel, Segmented, StatusPill, TabPanel, Tabs, Toggle } from '../ui'
import { canExplainMotion, explainInMotionLab, saveCandidate } from './actions'
import { truthFor } from './derive'

type Tab = 'measurements' | 'fit' | 'plots' | 'catalog' | 'registration' | 'provenance'

export function AnalyzeTabs({ dataset }: { dataset: Dataset }) {
  const [tab, setTab] = useState<Tab>('measurements')
  const s = useObservatoryStore()
  const source = s.sources.status === 'ready' ? s.sources.data.find((x) => x.id === s.selectedSourceId) ?? null : null
  return (
    <section className="analyze-tabs panel" aria-label="Analysis">
      <Tabs<Tab>
        idPrefix="an"
        ariaLabel="Analysis views"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'measurements', label: 'Measurements' },
          { id: 'fit', label: 'Motion fit' },
          { id: 'plots', label: 'Plots & residuals' },
          { id: 'catalog', label: 'Catalog' },
          { id: 'registration', label: 'Registration' },
          { id: 'provenance', label: 'Provenance & export' },
        ]}
      />
      <TabPanel idPrefix="an" id={tab}>
        <div className="analyze-body">
          {tab === 'registration' ? (
            <RegistrationTab dataset={dataset} />
          ) : tab === 'provenance' ? (
            <ProvenanceTab dataset={dataset} />
          ) : !source ? (
            <EmptyState title="No source selected">Select a source in the image or search for a source ID to measure it across epochs.</EmptyState>
          ) : s.measurements.status === 'loading' || s.measurements.status === 'idle' ? (
            <LoadingState label="Measuring the source in every frame…" />
          ) : s.measurements.status === 'error' ? (
            <ErrorState message={s.measurements.message} onRetry={() => s.selectSource(null)} />
          ) : s.measurements.status === 'unavailable' ? (
            <EmptyState title="Measurement unavailable">{s.measurements.message}</EmptyState>
          ) : tab === 'measurements' ? (
            <MeasurementsTab measurements={s.measurements.data.measurements} notes={s.measurements.data.notes} />
          ) : tab === 'fit' ? (
            <FitTab />
          ) : tab === 'plots' ? (
            <PlotsTab dataset={dataset} />
          ) : (
            <CatalogTab />
          )}
        </div>
      </TabPanel>
    </section>
  )
}

function MeasurementsTab({ measurements, notes }: { measurements: SourceMeasurement[]; notes: string[] }) {
  const s = useObservatoryStore()
  const excluded = new Set(s.excludedIds)
  const tp = meanPosition(measurements)
  const stale = isFitStale(s)
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="row">
          <OriginBadge origin="derived_measurement" />
          <span className="small muted">PSF fit on native frames · offsets about the mean position · 1σ uncertainties</span>
        </div>
        {stale && <StatusPill status="stale" label="Fit is stale: inclusion changed" />}
      </div>
      <div className="table-wrap" style={{ maxHeight: 360 }}>
        <table className="table" data-testid="measurement-table">
          <thead>
            <tr>
              <th>Include</th>
              <th>Epoch (UTC)</th>
              <th>Band</th>
              <th>Status</th>
              <th className="r">Δα·cosδ (mas)</th>
              <th className="r">Δδ (mas)</th>
              <th className="r">Flux (e⁻)</th>
              <th className="r">S/N</th>
              <th className="r">χ²/dof</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {measurements.map((m) => {
              const measured = m.status === 'measured' && m.ra_deg != null && m.dec_deg != null
              const [e, n] = measured && tp ? offsetsMas(m.ra_deg!, m.dec_deg!, tp.ra_deg, tp.dec_deg) : [null, null]
              const isEx = excluded.has(m.id)
              return (
                <tr key={m.id} className={isEx || !measured ? 'excluded' : undefined} data-status={m.status}>
                  <td>
                    {measured ? (
                      <input type="checkbox" checked={!isEx} onChange={() => s.toggleExcluded(m.id)} aria-label={`Include ${fmtDate(m.epoch.iso_utc)} ${m.band_id} in the fit`} />
                    ) : (
                      <span className="faint">—</span>
                    )}
                  </td>
                  <td>{fmtUtc(m.epoch.iso_utc, false)}</td>
                  <td>{m.band_id}</td>
                  <td title={m.status_reason ?? undefined}>
                    <StatusPill status={m.status} />
                  </td>
                  <td className="r">{measured ? fmtPm(e, m.sigma_ra_cosdec_mas) : '—'}</td>
                  <td className="r">{measured ? fmtPm(n, m.sigma_dec_mas) : '—'}</td>
                  <td className="r">{measured ? fmtPm(m.flux, m.flux_err) : '—'}</td>
                  <td className="r">{fmt(m.snr, 0)}</td>
                  <td className="r">{fmt(m.fit_chi2_reduced, 2)}</td>
                  <td className="small">{m.quality.flags.join(', ') || (m.status_reason && !measured ? m.status_reason : '')}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <ul className="small muted notes">
        {notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  )
}

const MODEL_LABEL: Record<AstrometricModel, string> = { static: 'Static', proper_motion: 'Proper motion', proper_motion_parallax: 'PM + parallax' }

function FitTab() {
  const s = useObservatoryStore()
  const stale = isFitStale(s)
  const fit = s.fit.status === 'ready' ? s.fit.data : null
  const explain = canExplainMotion()
  return (
    <div className="stack">
      <div className="row fit-controls">
        <Segmented<AstrometricModel>
          ariaLabel="Astrometric model"
          value={s.fitModel}
          onChange={s.setFitModel}
          options={(['static', 'proper_motion', 'proper_motion_parallax'] as AstrometricModel[]).map((m) => ({ value: m, label: MODEL_LABEL[m] }))}
          testId="fit-model"
        />
        <button type="button" className="btn btn-primary" onClick={() => void s.runFit()} disabled={s.fit.status === 'loading'} data-testid="run-fit">
          <Play size={14} aria-hidden /> {fit ? 'Re-run fit' : 'Run fit'}
        </button>
        <span className="small muted">{s.excludedIds.length ? `${s.excludedIds.length} measurement(s) excluded` : 'All measured epochs included'}</span>
      </div>
      {s.fit.status === 'loading' && <LoadingState label="Fitting…" />}
      {s.fit.status === 'error' && <ErrorState title="Fit failed" message={s.fit.message} />}
      {stale && (
        <Callout tone="warning" role="status">
          <strong>Stale fit.</strong> The included measurements or the model changed after this fit was computed. Re-run the fit before using these numbers.
        </Callout>
      )}
      {fit && <FitResult fit={fit} stale={stale} />}
      {fit && (
        <div className="row">
          <button type="button" className="btn" onClick={explainInMotionLab} disabled={!explain.ok} data-testid="analyze-explain">
            <Orbit size={14} aria-hidden /> Explain in Motion lab
          </button>
          <span className="small faint">Opens the nearby-source lesson with these fitted values (teaching observer approximation).</span>
        </div>
      )}
      {!fit && s.fit.status === 'idle' && (
        <p className="small muted">
          Choose a model and run the fit. Proper motion and parallax are reported only when the epochs constrain them; otherwise the result is marked underconstrained.
        </p>
      )}
    </div>
  )
}

export function FitResult({ fit, stale }: { fit: ModelFit; stale: boolean }) {
  const ident = fit.identifiability
  const corr = useMemo(() => {
    if (!fit.covariance) return null
    const d = fit.covariance.map((row, i) => Math.sqrt(row[i]))
    return fit.covariance.map((row, i) => row.map((v, j) => v / (d[i] * d[j])))
  }, [fit])
  const bicMin = Math.min(...fit.comparisons.map((c) => c.bic ?? Infinity))
  return (
    <div className={`fit-result ${stale ? 'is-stale' : ''}`} data-testid="fit-result">
      <div className="row">
        <OriginBadge origin="derived_measurement" label="Fit estimates" />
        <StatusPill status={fit.status} label={`fit ${fit.status}`} />
        <StatusPill status={ident.status} label={ident.status.replace(/_/g, ' ')} />
        <span className="small muted num">
          χ² {fmt(fit.chi2, 1)} / dof {fit.dof} = {fmt(fit.reduced_chi2, 2)} · p = {fit.p_value == null ? '—' : fit.p_value.toPrecision(2)} · {ident.n_measurements} positions, {ident.n_epochs} epochs,{' '}
          {fmt(ident.time_baseline_yr, 2)} yr
        </span>
      </div>
      <div className="fit-grid">
        <div className="table-wrap">
          <table className="table" data-testid="fit-parameters">
            <thead>
              <tr>
                <th>Parameter</th>
                <th className="r">Value ± 1σ</th>
                <th>Unit</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {fit.parameters.map((p) => (
                <tr key={p.name} className={p.status === 'not_in_model' ? 'excluded' : undefined} data-param={p.name}>
                  <td>{p.label}</td>
                  <td className="r num">{p.status === 'not_in_model' ? '—' : fmtPm(p.value, p.uncertainty)}</td>
                  <td>{p.unit}</td>
                  <td>
                    <StatusPill status={p.status === 'estimated' ? 'ok' : p.status === 'not_constrained' ? 'warning' : 'none'} label={p.status.replace(/_/g, ' ')} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-wrap">
          <table className="table" data-testid="fit-derived">
            <thead>
              <tr>
                <th>Derived</th>
                <th className="r">Value</th>
                <th>Basis</th>
              </tr>
            </thead>
            <tbody>
              {fit.derived
                .filter((d) => !d.name.endsWith('_at_reference_epoch'))
                .map((d) => (
                  <tr key={d.name} data-derived={d.name}>
                    <td>{d.name.replace(/_/g, ' ')}</td>
                    <td className="r num">{d.status === 'derived' ? `${fmtPm(d.value, d.uncertainty)} ${d.unit}` : 'not derived'}</td>
                    <td className="small">{d.reason}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="fit-grid">
        {corr && (
          <div>
            <h4 className="small muted">Correlation matrix</h4>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th />
                    {fit.covariance_parameters.map((p) => (
                      <th key={p} className="r">
                        {p.replace('offset_', 'Δ').replace('_cosdec', '*')}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {corr.map((row, i) => (
                    <tr key={i}>
                      <th>{fit.covariance_parameters[i].replace('offset_', 'Δ').replace('_cosdec', '*')}</th>
                      {row.map((v, j) => (
                        <td key={j} className="r num" style={{ color: i !== j && Math.abs(v) > 0.9 ? 'var(--amber)' : undefined }}>
                          {v.toFixed(2)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div>
          <h4 className="small muted">Model comparison (same data)</h4>
          <div className="table-wrap">
            <table className="table" data-testid="fit-comparison">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="r">χ²</th>
                  <th className="r">dof</th>
                  <th className="r">ΔBIC</th>
                </tr>
              </thead>
              <tbody>
                {fit.comparisons.map((c) => (
                  <tr key={c.model}>
                    <td>{MODEL_LABEL[c.model]}</td>
                    <td className="r num">{c.status === 'fit' ? fmt(c.chi2, 1) : c.status.replace(/_/g, ' ')}</td>
                    <td className="r">{c.dof}</td>
                    <td className="r num">{c.bic != null && Number.isFinite(bicMin) ? (c.bic - bicMin).toFixed(1) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small faint">A good fit is evidence about this model only — not a classification or discovery.</p>
        </div>
      </div>
      <details className="fit-details">
        <summary>Identifiability, assumptions and warnings</summary>
        <div className="stack small">
          <ul>
            {ident.messages.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
          <dl className="kvs">
            <KV k="Condition number">{fmt(ident.condition_number, 1)}</KV>
            <KV k="Max |correlation|">{fmt(ident.max_abs_correlation, 3)}</KV>
            <KV k="Parallax-factor span">{ident.parallax_factor_span ? `${ident.parallax_factor_span[0].toFixed(2)}, ${ident.parallax_factor_span[1].toFixed(2)}` : '—'}</KV>
            <KV k="Reference epoch">{fmtUtc(fit.reference_epoch.iso_utc)} (MJD {fit.reference_epoch.mjd_tdb.toFixed(3)} TDB)</KV>
          </dl>
          <h4>Assumptions</h4>
          <ul>
            {fit.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          {fit.warnings.length > 0 && (
            <>
              <h4>Warnings</h4>
              <ul>
                {fit.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </details>
    </div>
  )
}

function PlotsTab({ dataset }: { dataset: Dataset }) {
  const s = useObservatoryStore()
  const ms = s.measurements.status === 'ready' ? s.measurements.data.measurements : []
  const fit = s.fit.status === 'ready' ? s.fit.data : null
  const stale = isFitStale(s)
  const excluded = useMemo(() => new Set(s.excludedIds), [s.excludedIds])
  const source = s.sources.status === 'ready' ? s.sources.data.find((x) => x.id === s.selectedSourceId) ?? null : null
  const simulated = dataset.origin === 'simulated'
  const truthMatch = s.display.truth && s.truth.status === 'ready' ? truthFor(s.truth.data, source) : null
  const truthPositions = truthMatch
    ? truthMatch.positions.length
      ? truthMatch.positions
      : ms.filter((m) => m.status === 'measured').map((m) => ({ frame_id: m.frame_id, truth_id: truthMatch.source.truth_id, x_px: 0, y_px: 0, ra_deg: truthMatch.source.ra_deg, dec_deg: truthMatch.source.dec_deg, flux: 0 }))
    : null
  useEffect(() => {
    if (s.display.truth && simulated) void s.loadTruth()
  }, [s.display.truth, simulated]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="row">
          <OriginBadge origin="derived_measurement" label="Measured positions" />
          {fit && <OriginBadge origin="model_prediction" label={stale ? 'Model prediction (stale)' : 'Model prediction'} />}
          {truthPositions && <OriginBadge origin="simulation_truth" />}
        </div>
        {simulated && (
          <Toggle
            checked={s.display.truth}
            onChange={(v) => s.setDisplay({ truth: v })}
            label="Show simulation truth (validation only)"
            testId="toggle-truth"
            title="Injected positions used to generate the synthetic pixels. Never a measurement."
          />
        )}
      </div>
      {!fit && <Callout tone="neutral">No fit yet: plots show measurements only. Run a fit in “Motion fit” to add the model prediction and residuals.</Callout>}
      <div className="plots-grid">
        <div className="plots-sky">
          <SkyTrackPlot measurements={ms} excludedIds={excluded} fit={fit} fitStale={stale} truth={truthPositions} height={380} testId="sky-track-plot" />
          <div className="plots-guide small">
            <h4>Reading the sky track</h4>
            <p>Each point is the source position measured in one frame (both bands), with 1σ error bars, plotted on the sky with north up and east to the left at equal scale on both axes.</p>
            <p>The dashed curve is the fitted model: a straight secular drift (proper motion) plus a yearly loop whose size is the parallax and whose shape comes from the observer’s orbit and the field’s ecliptic latitude.</p>
            <p>Residuals below show data − model for each axis; points scattered within their error bars mean the model describes these measurements — it does not by itself classify the source.</p>
          </div>
        </div>
        <OffsetTimePlots measurements={ms} excludedIds={excluded} fit={fit} fitStale={stale} truth={truthPositions} />
      </div>
    </div>
  )
}

function CatalogTab() {
  const s = useObservatoryStore()
  useEffect(() => {
    if (s.associations.status === 'idle') void s.loadAssociations()
  }, [s.associations.status, s.selectedSourceId]) // eslint-disable-line react-hooks/exhaustive-deps
  if (s.associations.status === 'loading' || s.associations.status === 'idle') return <LoadingState label="Propagating catalog positions to each epoch…" />
  if (s.associations.status === 'error') return <ErrorState message={s.associations.message} onRetry={() => void s.loadAssociations()} />
  if (s.associations.status === 'unavailable') return <EmptyState title="Catalog associations unavailable">{s.associations.message}</EmptyState>
  const assoc = s.associations.data
  const counts = assoc.reduce<Record<string, number>>((acc, a) => ({ ...acc, [a.status]: (acc[a.status] ?? 0) + 1 }), {})
  return (
    <div className="stack">
      <div className="row">
        <OriginBadge origin="simulated" label="Simulated reference catalog" />
        <OriginBadge origin="model_prediction" label="Propagated to each epoch" />
        {Object.entries(counts).map(([k, v]) => (
          <StatusPill key={k} status={k} label={`${v} ${k}`} />
        ))}
        <Toggle checked={s.display.catalog} onChange={(v) => s.setDisplay({ catalog: v })} label="Show catalog on image" testId="toggle-catalog" />
      </div>
      <div className="table-wrap" style={{ maxHeight: 320 }}>
        <table className="table" data-testid="association-table">
          <thead>
            <tr>
              <th>Epoch</th>
              <th>Status</th>
              <th>Candidate(s)</th>
              <th className="r">Sep (″)</th>
              <th className="r">Norm. sep</th>
              <th>Propagation</th>
            </tr>
          </thead>
          <tbody>
            {assoc.map((a) => (
              <tr key={`${a.measurement_id}`}>
                <td>{fmtDate(a.epoch.iso_utc)}</td>
                <td>
                  <StatusPill status={a.status} />
                </td>
                <td className="mono small">{a.candidates.map((c) => c.catalog_source_id).join(', ') || '—'}</td>
                <td className="r num">{a.candidates.map((c) => c.separation_arcsec.toFixed(3)).join(', ') || '—'}</td>
                <td className="r num">{a.candidates.map((c) => fmt(c.normalized_separation, 1)).join(', ') || '—'}</td>
                <td className="small">{a.candidates[0]?.propagated.method.split(' (')[0] ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {assoc[0] && <p className="small muted">Criteria: {assoc[0].criteria}.</p>}
      <ul className="small muted notes">
        {[...new Set(assoc.flatMap((a) => a.notes))].map((n) => (
          <li key={n}>{n}</li>
        ))}
        <li>Catalog values are simulated (Gaia-like format) at J2016.0 TCB; they are propagated with space motion and observer parallax before matching.</li>
      </ul>
    </div>
  )
}

function RegistrationTab({ dataset }: { dataset: Dataset }) {
  const cal = dataset.astrometric_calibration
  const natives = dataset.frames.filter((f) => f.kind === 'native')
  return (
    <div className="stack">
      {cal && (
        <Panel title="Astrometric calibration" eyebrow="Registration reference">
          <dl className="kvs">
            <KV k="Method">{cal.method}</KV>
            <KV k="Catalog">{cal.catalog ?? 'none (zero point uncalibrated)'}</KV>
            <KV k="Median stars used">{cal.n_used}</KV>
            <KV k="Median residual rms">{fmt(cal.rms_residual_mas, 1)} mas</KV>
            <KV k="Reference header error">
              {fmt(cal.offset_east_mas, 0)} mas E, {fmt(cal.offset_north_mas, 0)} mas N
            </KV>
          </dl>
          <ul className="small muted notes">
            {cal.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Panel>
      )}
      <div className="table-wrap" style={{ maxHeight: 360 }}>
        <table className="table" data-testid="registration-table">
          <thead>
            <tr>
              <th>Frame</th>
              <th>Band</th>
              <th className="r">Matched</th>
              <th className="r">Used</th>
              <th className="r">RMS (mas)</th>
              <th className="r">χ²/dof</th>
              <th className="r">Shift (px)</th>
              <th className="r">Rotation (°)</th>
              <th>Quality</th>
            </tr>
          </thead>
          <tbody>
            {natives.map((f) => {
              const r = f.registration
              return (
                <tr key={f.id}>
                  <td className="mono small">{f.observation_id.split(':')[1]}</td>
                  <td>{f.band_id}</td>
                  <td className="r">{r?.n_matched ?? '—'}</td>
                  <td className="r">{r?.n_used ?? '—'}</td>
                  <td className="r num">{fmt(r?.rms_residual_mas, 1)}</td>
                  <td className="r num">{fmt(r?.chi2_per_dof, 2)}</td>
                  <td className="r num">{r ? `${r.transform.dx_px.toFixed(2)}, ${r.transform.dy_px.toFixed(2)}` : '—'}</td>
                  <td className="r num">{r ? r.transform.rotation_deg.toFixed(4) : '—'}</td>
                  <td title={r?.quality.messages.join(' ')}>{r ? <StatusPill status={r.quality.status} /> : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted">
        The shift and rotation correct each frame’s deliberately imperfect header WCS. Residuals are measured positions of reference stars minus catalog positions
        propagated to the frame epoch. A visually aligned blink is not by itself proof of a valid comparison; see these residuals.
      </p>
    </div>
  )
}

function ProvenanceTab({ dataset }: { dataset: Dataset }) {
  const [msg, setMsg] = useState<{ ok: boolean; message: string } | null>(null)
  const s = useObservatoryStore()
  return (
    <div className="stack">
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={!s.selectedSourceId || s.measurements.status !== 'ready'} onClick={async () => setMsg(await saveCandidate())} data-testid="analyze-save">
          <BookmarkPlus size={14} aria-hidden /> Save investigation to notebook
        </button>
        <span className="small muted">Saves the source, frames, view, measurements, exclusions, fit (with its current/stale status), associations, and — for synthetic data — the seed and truth, separately.</span>
      </div>
      {msg && (
        <Callout tone={msg.ok ? 'info' : 'warning'} role="status">
          {msg.message} {msg.ok && <a href="#/evidence">Open notebook</a>}
        </Callout>
      )}
      <div className="fit-grid">
        <Panel title="Dataset" eyebrow="Provenance">
          <dl className="kvs">
            <KV k="Dataset">{dataset.id}</KV>
            <KV k="Provider">{dataset.provider}</KV>
            <KV k="Origin">
              <OriginBadge origin={dataset.origin === 'simulated' ? 'simulated' : 'observed'} />
            </KV>
            <KV k="Release">{dataset.release}</KV>
            <KV k="Generator">
              {dataset.generator} {dataset.generator_version}
            </KV>
            <KV k="Seed">{dataset.seed ?? '—'}</KV>
            <KV k="Instrument">{dataset.instrument.name}</KV>
          </dl>
          <ul className="small muted notes">
            {dataset.instrument.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Panel>
        <Panel title="Limitations" eyebrow="Read before interpreting">
          <ul className="small notes">
            {dataset.limitations.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <p className="small">
            Full methods and validation status: <a href="#/methods">Methods</a>.
          </p>
        </Panel>
      </div>
      <details className="fit-details">
        <summary>Software versions</summary>
        <ul className="small mono">
          {dataset.provenance.software.map((v) => (
            <li key={v.name}>
              {v.name} {v.version}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}
