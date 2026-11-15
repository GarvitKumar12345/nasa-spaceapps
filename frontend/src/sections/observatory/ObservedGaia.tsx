/* Gaia DR3 predictions and alignment diagnostics on observed SPHEREx frames.
 * Catalogue predictions (model) are hollow squares; ePSF positions of reference candidates
 * (derived measurements) are teal crosses. Neither is a detection of anything new: a prediction
 * without a counterpart is reported with its reason, never as a discovery. Source IDs are strings. */
import { useEffect, useMemo, useState } from 'react'
import type { AlignmentReport, Dataset, FrameAlignment, GaiaFrameOverlay, GaiaSourceDetail, ReferenceStarResidual } from '../../api/types'
import { fmt, fmtPm, fmtSigned, fmtUtc } from '../../lib/format'
import { RESIDUAL_MAGNIFICATION, measuredDisplayPoint, predictionKind, useGaiaStore, visiblePredictions } from '../../state/gaia'
import type { Load } from '../../state/observatory'
import { Callout, EmptyState, ErrorState, KV, LoadingState, OriginBadge, StatusPill } from '../../components/ui'
import { ErrorBarPoints, Legend, PLOT_COLOR, PlotFrame, linear, useElementWidth } from '../../components/plot'
import type { CanvasOverlays, CanvasPoint, PredictionMarker } from '../../components/observatory/SkyCanvas'

/** Overlay of one display frame (loads on demand). */
export function useGaiaOverlay(datasetId: string | null, frameId: string | null, enabled: boolean): Load<GaiaFrameOverlay> | null {
  const g = useGaiaStore()
  useEffect(() => {
    if (enabled && datasetId && frameId) void g.loadOverlay(datasetId, frameId)
  }, [enabled, datasetId, frameId]) // eslint-disable-line react-hooks/exhaustive-deps
  return enabled && frameId ? g.overlays[frameId] ?? { status: 'idle' } : null
}

function residualMap(report: AlignmentReport | null, nativeFrameId: string | null): Map<string, ReferenceStarResidual> {
  const m = new Map<string, ReferenceStarResidual>()
  const f = report?.frames.find((x) => x.frame_id === nativeFrameId)
  f?.residuals.forEach((r) => m.set(r.source_id, r))
  return m
}

/** Canvas inputs: hit-test points, prediction markers, measured crosses and magnified residual vectors. */
export function useGaiaCanvas(dataset: Dataset, overlay: GaiaFrameOverlay | null): { sources: CanvasPoint[]; overlays: CanvasOverlays } {
  const g = useGaiaStore()
  const report = g.alignment.status === 'ready' ? g.alignment.data : null
  return useMemo(() => {
    if (!overlay || !g.show.overlay) return { sources: [], overlays: {} }
    const vis = visiblePredictions(overlay, g.show.maxG)
    const sources: CanvasPoint[] = vis.map((p) => ({ id: p.source_id, x: p.x_display as number, y: p.y_display as number, label: `Gaia DR3 ${p.source_id} (prediction)` }))
    const predictions: PredictionMarker[] = vis.map((p) => ({ id: p.source_id, x: p.x_display as number, y: p.y_display as number, kind: predictionKind(p) }))
    const res = residualMap(report, overlay.native_frame_id)
    const scale = dataset.instrument.pixel_scale_arcsec || 6.15
    const measured: CanvasPoint[] = []
    const vectors: NonNullable<CanvasOverlays['vectors']> = []
    for (const p of vis) {
      const r = res.get(p.source_id)
      if (!r || r.residual_east_arcsec == null || r.residual_north_arcsec == null) continue
      const d = { east: r.residual_east_arcsec, north: r.residual_north_arcsec }
      const m = measuredDisplayPoint(p, d, scale)
      if (m && g.show.measured) measured.push({ id: `m-${p.source_id}`, x: m[0], y: m[1] })
      const v = measuredDisplayPoint(p, d, scale, RESIDUAL_MAGNIFICATION)
      if (v && g.show.vectors) vectors.push({ id: `v-${p.source_id}`, x0: p.x_display as number, y0: p.y_display as number, x1: v[0], y1: v[1] })
    }
    return { sources, overlays: { predictions, measured: g.show.measured ? measured : null, vectors: g.show.vectors ? vectors : null } }
  }, [overlay, g.show, report, dataset])
}

export function GaiaControls({ datasetId }: { datasetId: string | null }) {
  const g = useGaiaStore()
  const needReport = g.show.measured || g.show.vectors
  useEffect(() => {
    if (needReport && datasetId) void g.loadAlignment(datasetId)
  }, [needReport, datasetId]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="display-controls gaia-controls" aria-label="Gaia DR3 overlay">
      <label className="toggle">
        <input type="checkbox" role="switch" checked={g.show.overlay} onChange={(e) => g.setShow({ overlay: e.target.checked })} data-testid="gaia-toggle" /> Gaia DR3 predictions
      </label>
      <label className="field-inline">
        <span className="small muted">to G</span>
        <select className="select" value={g.show.maxG} onChange={(e) => g.setShow({ maxG: Number(e.target.value) })} aria-label="Faintest Gaia G magnitude shown" data-testid="gaia-maxg">
          {[14, 16, 17, 18.5, 20, 21.5].map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <label className="toggle">
        <input type="checkbox" role="switch" checked={g.show.measured} onChange={(e) => g.setShow({ measured: e.target.checked })} data-testid="gaia-measured-toggle" /> ePSF positions
      </label>
      <label className="toggle">
        <input type="checkbox" role="switch" checked={g.show.vectors} onChange={(e) => g.setShow({ vectors: e.target.checked })} data-testid="gaia-vectors-toggle" /> Residuals ×{RESIDUAL_MAGNIFICATION}
      </label>
      {needReport && g.alignment.status === 'loading' && <span className="small muted">measuring reference stars…</span>}
      <GaiaLegend />
    </div>
  )
}

export function GaiaLegend() {
  return (
    <div className="gaia-legend small" data-testid="gaia-legend">
      <span className="legend-item">
        <svg width={14} height={14} aria-hidden>
          <rect x={2} y={2} width={10} height={10} className="lg-gaia" />
        </svg>
        Gaia DR3 prediction (model, not a measurement)
      </span>
      <span className="legend-item">
        <svg width={14} height={14} aria-hidden>
          <rect x={2} y={2} width={10} height={10} className="lg-gaia lg-gaia-used" />
        </svg>
        used reference
      </span>
      <span className="legend-item">
        <svg width={14} height={14} aria-hidden>
          <rect x={2} y={2} width={10} height={10} className="lg-gaia" />
          <path d="M2 2 L12 12 M12 2 L2 12" className="lg-gaia" />
        </svg>
        saturated
      </span>
      <span className="legend-item">
        <svg width={14} height={14} aria-hidden>
          <circle cx={7} cy={7} r={5} className="lg-gaia lg-gaia-dash" />
        </svg>
        no proper motion
      </span>
      <span className="legend-item">
        <svg width={14} height={14} aria-hidden>
          <path d="M3 7 L11 7 M7 3 L7 11" className="lg-measured" />
        </svg>
        ePSF position (derived measurement)
      </span>
    </div>
  )
}

// ---------------------------------------------------------------- inspector panel

export function GaiaSourcePanel({ datasetId, frameId }: { datasetId: string; frameId: string | null }) {
  const g = useGaiaStore()
  useEffect(() => {
    if (g.selectedSourceId && frameId) void g.loadDetail(datasetId, frameId)
  }, [g.selectedSourceId, frameId, datasetId]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!g.selectedSourceId) return null
  const close = (
    <button type="button" className="btn btn-sm" onClick={() => g.select(null)} data-testid="gaia-close">
      Clear
    </button>
  )
  return (
    <section className="insp-block gaia-panel" data-testid="gaia-panel" data-source-id={g.selectedSourceId}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="eyebrow">Gaia DR3 source</div>
        {close}
      </div>
      <div className="mono gaia-id" data-testid="gaia-source-id">
        {g.selectedSourceId}
      </div>
      {g.detail.status === 'loading' || g.detail.status === 'idle' ? (
        <LoadingState label="Propagating the catalogue entry to this exposure…" />
      ) : g.detail.status === 'error' || g.detail.status === 'unavailable' ? (
        <ErrorState message={g.detail.message} />
      ) : (
        <GaiaDetailBody d={g.detail.data} />
      )}
    </section>
  )
}

function GaiaDetailBody({ d }: { d: GaiaSourceDetail }) {
  const s = d.source
  const p = d.propagated
  const m = d.measurement
  const ruwe = s.quality_indicators['ruwe']
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div>
        <div className="row" style={{ gap: 6 }}>
          <OriginBadge origin="catalog" label="Catalogue values" />
          <span className="small muted">epoch J{String(s.reference_epoch.value)} ({s.reference_epoch.scale.toUpperCase()})</span>
        </div>
        <dl className="kvs" data-testid="gaia-catalog-values">
          <KV k="Solution">{s.astrometric_solution}</KV>
          <KV k="RA, Dec (J2016.0)" mono>
            {fmt(s.ra_deg, 7)}°, {fmtSigned(s.dec_deg, 7)}°
          </KV>
          <KV k="σ RA*, σ Dec">{s.ra_error_mas != null ? `${fmt(s.ra_error_mas, 3)}, ${fmt(s.dec_error_mas, 3)} mas` : '—'}</KV>
          <KV k="Parallax">{s.parallax_mas != null ? fmtPm(s.parallax_mas, s.parallax_error_mas, 'mas') : 'not solved'}</KV>
          <KV k="pmRA* (incl. cos Dec)">{s.pmra_mas_yr != null ? fmtPm(s.pmra_mas_yr, s.pmra_error_mas_yr, 'mas/yr') : 'not solved'}</KV>
          <KV k="pmDec">{s.pmdec_mas_yr != null ? fmtPm(s.pmdec_mas_yr, s.pmdec_error_mas_yr, 'mas/yr') : 'not solved'}</KV>
          <KV k="Radial velocity">{s.radial_velocity_km_s != null ? fmtPm(s.radial_velocity_km_s, s.radial_velocity_error_km_s, 'km/s') : 'not catalogued'}</KV>
          <KV k="G, BP−RP">
            {fmt(s.photometry['phot_g_mean_mag'] ?? null, 2)} mag{s.photometry['bp_rp'] != null ? `, ${fmt(s.photometry['bp_rp'], 2)}` : ''}
          </KV>
          <KV k="RUWE">{ruwe != null ? fmt(Number(ruwe), 2) : '—'}</KV>
        </dl>
      </div>
      <div data-testid="gaia-prediction">
        <div className="row" style={{ gap: 6 }}>
          <OriginBadge origin="model_prediction" label="Prediction at this exposure" />
        </div>
        {p ? (
          <dl className="kvs">
            <KV k="Epoch (UTC)" mono>
              {fmtUtc(p.epoch.iso_utc)}
            </KV>
            <KV k="RA, Dec" mono>
              {fmt(p.ra_deg, 7)}°, {fmtSigned(p.dec_deg, 7)}°
            </KV>
            <KV k="σ RA*, σ Dec">
              {fmt(p.sigmas['ra_cosdec'], 3)}, {fmt(p.sigmas['dec'], 3)} mas
            </KV>
            <KV k="Observer parallax applied">
              ({fmtSigned(p.observer_parallax_offset_mas[0], 2)}, {fmtSigned(p.observer_parallax_offset_mas[1], 2)}) mas E, N
            </KV>
            <KV k="Radial velocity">{p.radial_velocity_assumed ? `assumed 0 (bound ${fmt(p.perspective_bound_mas, 2)} mas)` : `${fmt(p.radial_velocity_used_km_s, 2)} km/s (catalogued)`}</KV>
          </dl>
        ) : (
          <p className="small muted">Not propagated: a 2-parameter solution has no proper motion or parallax.</p>
        )}
        {d.prediction && (
          <p className="small muted mono">
            pixel ({fmt(d.prediction.x_native, 2)}, {fmt(d.prediction.y_native, 2)}) native · flags {d.prediction.flags.join(', ') || 'none'}
          </p>
        )}
      </div>
      <div data-testid="gaia-measurement">
        <div className="row" style={{ gap: 6 }}>
          <OriginBadge origin="derived_measurement" label="Image measurement (ePSF)" />
        </div>
        {m ? (
          <dl className="kvs">
            <KV k="Reference role">
              <StatusPill status={m.status === 'used' ? 'ok' : 'warning'} label={m.status} /> {m.reason_text ?? ''}
            </KV>
            {m.detail && <KV k="Detail">{m.detail}</KV>}
            {m.residual_east_arcsec != null && (
              <KV k="Measured − predicted">
                {fmtSigned(m.residual_east_arcsec, 3)}″ E ± {fmt(m.sigma_east_arcsec, 3)}, {fmtSigned(m.residual_north_arcsec, 3)}″ N ± {fmt(m.sigma_north_arcsec, 3)}
              </KV>
            )}
            {m.snr != null && (
              <KV k="S/N, χ²/dof">
                {fmt(m.snr, 1)}, {fmt(m.chi2_red, 2)}
              </KV>
            )}
          </dl>
        ) : (
          <p className="small muted">Not a reference candidate here (fainter than the candidate limit or outside the frame); no image measurement.</p>
        )}
      </div>
      <div>
        <div className="eyebrow">Prediction limitations</div>
        <ul className="obs-list" data-testid="gaia-limitations">
          {d.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- Gaia DR3 tab

export function GaiaCatalogTab({ dataset, overlay }: { dataset: Dataset; overlay: Load<GaiaFrameOverlay> | null }) {
  if (!overlay || overlay.status === 'idle' || overlay.status === 'loading') return <LoadingState label="Propagating Gaia DR3 to this exposure…" />
  if (overlay.status === 'error' || overlay.status === 'unavailable') return <ErrorState message={overlay.message} />
  const o = overlay.data
  const c = o.convention
  return (
    <div className="stack" data-testid="gaia-tab">
      <Callout tone="info">
        <strong>Catalogue predictions, not image measurements.</strong> {o.label}. {o.n_in_frame} Gaia DR3 sources fall in this cutout ({o.n_catalog_rows} in the recorded field query).
      </Callout>
      <dl className="kvs">
        <KV k="Table · release">
          {o.catalog} · {o.release}
        </KV>
        <KV k="Retrieved (UTC)" mono>
          {fmtUtc(o.retrieved_utc)}
        </KV>
        <KV k="ADQL" mono>
          <span className="obs-url" data-testid="gaia-adql">
            {o.adql}
          </span>
        </KV>
        <KV k="Exposure epoch" mono>
          {fmtUtc(o.epoch.iso_utc)} UTC (MJD {fmt(o.epoch.mjd_tdb, 6)} TDB)
        </KV>
      </dl>
      <div>
        <div className="row" style={{ gap: 6 }}>
          <div className="eyebrow">Convention</div>
          <StatusPill status={c.status === 'resolved' ? 'ok' : 'warning'} label={c.status} />
        </div>
        <p className="small" data-testid="gaia-convention">
          {c.wcs_convention}
        </p>
        <p className="small">
          <strong>Frame:</strong> {c.frame}. <strong>Included:</strong> {c.includes.join('; ')}. <strong>Not applied:</strong> {c.excludes.join('; ')}.
        </p>
        <ul className="obs-list">
          {c.evidence.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      </div>
      <div>
        <div className="eyebrow">Positional error budget</div>
        <table className="table" data-testid="gaia-error-budget">
          <thead>
            <tr>
              <th>Term</th>
              <th>Treatment</th>
              <th className="num nocase">Bound (″)</th>
              <th className="num nocase">Typical (″)</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {c.error_budget.map((t) => (
              <tr key={t.term}>
                <td>{t.term}</td>
                <td>{t.treatment.replace(/_/g, ' ')}</td>
                <td className="num mono">{t.bound_arcsec != null ? t.bound_arcsec.toPrecision(2) : '—'}</td>
                <td className="num mono">{t.typical_arcsec != null ? t.typical_arcsec.toPrecision(2) : '—'}</td>
                <td className="small">{t.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="small">
        <div className="eyebrow">Reproduce</div>
        <pre className="obs-pre">{`cd backend
uv run python -m skyshift.providers.gaia_dr3.fetch --field ${dataset.id} --dry-run   # print the ADQL and the radius derivation
uv run python -m skyshift.providers.gaia_dr3.fetch --field ${dataset.id}             # live query + recorded response
uv run pytest tests/test_gaia_dr3.py -m live                                          # live ESA archive checks`}</pre>
      </div>
      <ul className="obs-list small">
        {o.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------- Alignment tab

const FRAME_STATUS: Record<FrameAlignment['status'], string> = {
  ok: 'ok',
  insufficient_reference_stars: 'too few references',
  estimator_not_validated: 'estimator not validated',
  not_available: 'not available',
}

export function AlignmentTab({ datasetId, nativeFrameId }: { datasetId: string; nativeFrameId: string | null }) {
  const g = useGaiaStore()
  useEffect(() => {
    void g.loadAlignment(datasetId)
  }, [datasetId]) // eslint-disable-line react-hooks/exhaustive-deps
  const [pick, setPick] = useState<string | null>(null)
  if (g.alignment.status === 'idle' || g.alignment.status === 'loading')
    return <LoadingState label="Fitting reference stars in every frame (first run ~1 min, then cached)…" />
  if (g.alignment.status === 'error' || g.alignment.status === 'unavailable') return <ErrorState message={g.alignment.message} />
  const r = g.alignment.data
  const frameId = pick ?? nativeFrameId ?? r.frames[0]?.frame_id ?? null
  const f = r.frames.find((x) => x.frame_id === frameId) ?? null
  return (
    <div className="stack" data-testid="alignment-tab">
      <Callout tone={r.status === 'available' ? 'info' : 'warning'}>
        <strong>{r.status === 'available' ? 'Residuals before any correction.' : 'Alignment results withheld.'}</strong> {r.status_reason} {r.field_assessment}
      </Callout>
      <div className="row" style={{ gap: 6 }}>
        <div className="eyebrow">Archive-WCS convention test</div>
        <StatusPill status={r.convention.status === 'resolved' ? 'ok' : 'warning'} label={r.convention.status} />
      </div>
      <p className="small" data-testid="convention-test">
        {r.convention_test.decision} (χ² {fmt(r.convention_test.chi2_catalog_frame, 1)} vs {fmt(r.convention_test.chi2_apparent_frame, 0)} for {r.convention_test.dof} dof over{' '}
        {r.convention_test.n_frames} frames).
      </p>
      <table className="table" data-testid="alignment-frames">
        <thead>
          <tr>
            <th>Frame</th>
            <th>Status</th>
            <th className="num">Used / candidates</th>
            <th className="num nocase">Mean E, N (″)</th>
            <th className="num nocase">RMS (″)</th>
            <th className="num nocase">Extra scatter (″)</th>
            <th>Translation (held out)</th>
            <th>Estimator</th>
          </tr>
        </thead>
        <tbody>
          {r.frames.map((x) => {
            const s = x.statistics
            return (
              <tr key={x.frame_id} className={x.frame_id === frameId ? 'row-selected' : ''} data-frame={x.frame_id} onClick={() => setPick(x.frame_id)} style={{ cursor: 'pointer' }}>
                <td className="mono small">
                  {fmtUtc(x.epoch.iso_utc, false)} · D{x.detector}
                </td>
                <td>
                  <StatusPill status={x.status === 'ok' ? 'ok' : 'warning'} label={FRAME_STATUS[x.status]} />
                </td>
                <td className="num">
                  {x.n_used} / {x.n_candidates}
                </td>
                <td className="num mono">{s && s.n >= 2 ? `${fmtSigned(s.mean_east_arcsec, 3)} ± ${fmt(s.se_east_arcsec, 3)}, ${fmtSigned(s.mean_north_arcsec, 3)} ± ${fmt(s.se_north_arcsec, 3)}` : '—'}</td>
                <td className="num mono">{s && s.n ? fmt(s.rms_total_arcsec, 3) : '—'}</td>
                <td className="num mono">{s && s.n >= 2 ? fmt(s.extra_scatter_arcsec, 3) : '—'}</td>
                <td className="small">{x.translation.evaluated ? (x.translation.justified ? 'justified' : 'not justified') : 'not evaluated'}</td>
                <td className="small">{x.estimator?.passed ? 'validated' : 'not validated'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {f && <FrameDetail f={f} report={r} />}
      {r.pooled && r.pooled.n > 0 && (
        <p className="small" data-testid="alignment-pooled">
          Pooled over {r.pooled_over}: {r.pooled.n} references, mean ({fmtSigned(r.pooled.mean_east_arcsec, 3)}″, {fmtSigned(r.pooled.mean_north_arcsec, 3)}″), RMS ({fmt(r.pooled.rms_east_arcsec, 3)}″,{' '}
          {fmt(r.pooled.rms_north_arcsec, 3)}″), extra scatter {fmt(r.pooled.extra_scatter_arcsec, 3)}″.
        </p>
      )}
      <div className="small">
        <div className="eyebrow">Reference selection</div>
        <ul className="obs-list">
          {r.selection_criteria.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <div className="eyebrow">Limitations</div>
        <ul className="obs-list">
          {r.limitations.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function FrameDetail({ f, report }: { f: FrameAlignment; report: AlignmentReport }) {
  const used = f.residuals.filter((r) => r.status === 'used')
  const s = f.statistics
  const t = f.translation
  return (
    <div className="stack" data-testid="alignment-frame-detail" data-frame={f.frame_id}>
      <p className="small">
        <strong>{fmtUtc(f.epoch.iso_utc)} UTC · D{f.detector}</strong> — {f.status_reason} {f.n_in_frame} Gaia predictions in the cutout: {f.n_fainter_than_limit} fainter than the
        candidate limit, {f.n_candidates} candidates, {f.n_used} used, {f.n_rejected} rejected.
      </p>
      <div className="alignment-grid">
        <ResidualPlot used={used} mean={s && s.n >= 2 ? [s.wmean_east_arcsec ?? 0, s.wmean_north_arcsec ?? 0] : null} />
        <div className="stack" style={{ gap: 8 }}>
          <table className="table" data-testid="rejection-reasons">
            <thead>
              <tr>
                <th>Rejected because</th>
                <th className="num">n</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(f.rejected_by_reason).map(([k, n]) => (
                <tr key={k} data-reason={k}>
                  <td className="small">{report.reason_texts[k] ?? k}</td>
                  <td className="num">{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small" data-testid="translation-decision">
            <strong>Translation model:</strong> {t.decision}
            {t.evaluated && t.offset_east_arcsec != null && ` Estimated offset (${fmtSigned(t.offset_east_arcsec, 3)} ± ${fmt(t.sigma_east_arcsec, 3)}″ E, ${fmtSigned(t.offset_north_arcsec, 3)} ± ${fmt(t.sigma_north_arcsec, 3)}″ N); not applied to any product.`}
          </p>
          {f.estimator && (
            <div className="small" data-testid="estimator-validation">
              <strong>Estimator validation ({f.estimator.passed ? 'passed' : 'not passed'}):</strong> {f.estimator.method}.{' '}
              {f.estimator.per_target.map((x) => (
                <span key={x.snr_target}>
                  S/N≈{x.snr_target}
                  {x.snr_target < 30 ? ' (information only)' : ''}: {x.n_recovered}/{x.n_injected} recovered
                  {x.n_recovered >= 10
                    ? `, bias (${fmtSigned(x.bias_x_px, 3)}, ${fmtSigned(x.bias_y_px, 3)}) px, pulls (${fmt(x.robust_pull_x, 2)}, ${fmt(x.robust_pull_y, 2)})`
                    : ' (too few above the S/N cut to summarise)'}
                  .{' '}
                </span>
              ))}
              {f.estimator.near_saturated.length > 0 && (
                <span>
                  Near the saturated star:{' '}
                  {f.estimator.near_saturated.map((b) => `${b.r_min_px}–${b.r_max_px} px ${b.n_recovered}/${b.n_injected}${b.bias_x_px != null ? ` bias (${fmtSigned(b.bias_x_px, 3)}, ${fmtSigned(b.bias_y_px, 3)})` : ''}`).join('; ')}.
                </span>
              )}
            </div>
          )}
          <p className="small muted">If this frame's WCS mapped to apparent (aberrated) directions, residuals would be offset by ({fmtSigned(f.aberration_if_apparent_arcsec[0], 1)}″, {fmtSigned(f.aberration_if_apparent_arcsec[1], 1)}″).</p>
        </div>
      </div>
      {used.length > 0 && (
        <table className="table" data-testid="residual-table">
          <thead>
            <tr>
              <th>Gaia DR3 source_id</th>
              <th className="num">G</th>
              <th className="num nocase">S/N</th>
              <th className="num nocase">χ²/dof</th>
              <th className="num nocase">ΔE (″)</th>
              <th className="num nocase">ΔN (″)</th>
            </tr>
          </thead>
          <tbody>
            {used.map((r) => (
              <tr key={r.source_id} data-source-id={r.source_id}>
                <td className="mono small">{r.source_id}</td>
                <td className="num">{fmt(r.g_mag, 2)}</td>
                <td className="num">{fmt(r.snr, 0)}</td>
                <td className="num">{fmt(r.chi2_red, 1)}</td>
                <td className="num mono">
                  {fmtSigned(r.residual_east_arcsec, 3)} ± {fmt(r.sigma_east_arcsec, 3)}
                </td>
                <td className="num mono">
                  {fmtSigned(r.residual_north_arcsec, 3)} ± {fmt(r.sigma_north_arcsec, 3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** Measured-minus-predicted residuals (arcsec): equal axes, 1-sigma bars, documented 0.3" RMS ring, weighted mean. */
function ResidualPlot({ used, mean }: { used: ReferenceStarResidual[]; mean: [number, number] | null }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(320)
  const pts = used.filter((r) => r.residual_east_arcsec != null && r.residual_north_arcsec != null)
  const lim = Math.max(0.6, ...pts.map((r) => Math.max(Math.abs(r.residual_east_arcsec as number) + (r.sigma_east_arcsec ?? 0), Math.abs(r.residual_north_arcsec as number) + (r.sigma_north_arcsec ?? 0)))) * 1.1
  const size = Math.min(width, 360)
  const m = { top: 12, right: 14, bottom: 38, left: 52 }
  const inner = size - m.left - m.right
  // east to the left (sky convention), north up; equal scales on both axes
  const x = linear([lim, -lim], [0, inner])
  const y = linear([-lim, lim], [size - m.top - m.bottom, 0])
  if (!pts.length) return <EmptyState title="No reference residuals">No reference star passed the selection in this frame.</EmptyState>
  return (
    <div ref={ref} className="plot-wrap" data-testid="residual-plot">
      <div className="plot-title small">Measured − predicted (″), east left</div>
      <PlotFrame width={size} height={size} margin={m} x={x} y={y} xLabel="ΔRA·cos Dec (″, east +)" yLabel="ΔDec (″)" ariaLabel={`Residuals of ${pts.length} reference stars`} zeroLineY>
        <circle cx={x(0)} cy={y(0)} r={Math.abs(x(0.3) - x(0))} className="resid-ring" />
        <line x1={x(0)} x2={x(0)} y1={0} y2={size} className="zero-line" />
        <ErrorBarPoints
          points={pts.map((r) => ({ key: r.source_id, x: r.residual_east_arcsec as number, y: r.residual_north_arcsec as number, xerr: r.sigma_east_arcsec, yerr: r.sigma_north_arcsec }))}
          x={x}
          y={y}
          color={PLOT_COLOR.measured}
        />
        {mean && <path d={`M${x(mean[0]) - 6} ${y(mean[1])} L${x(mean[0]) + 6} ${y(mean[1])} M${x(mean[0])} ${y(mean[1]) - 6} L${x(mean[0])} ${y(mean[1]) + 6}`} className="resid-mean" />}
      </PlotFrame>
      <Legend
        items={[
          { label: 'reference star (ePSF − Gaia), 1σ', kind: 'point', color: PLOT_COLOR.measured },
          { label: 'documented 0.3″ RMS', kind: 'hollow', color: 'var(--line-strong)' },
          { label: 'weighted mean', kind: 'line', color: 'var(--text)' },
        ]}
      />
    </div>
  )
}
