/* Explore-mode inspector: concise source and frame information with uncertainty and quality. */
import { useState } from 'react'
import { BookmarkPlus, Microscope, Orbit } from 'lucide-react'
import type { Dataset, DetectedSource, Observation, SourceMeasurement } from '../../api/types'
import { fmt, fmtDecDms, fmtPm, fmtRaHms, fmtUtc } from '../../lib/format'
import { Callout, EmptyState, KV, OriginBadge, StatusPill } from '../ui'
import { canExplainMotion, explainInMotionLab, saveCandidate } from './actions'

export interface InspectorProps {
  dataset: Dataset
  source: DetectedSource | null
  measurement: SourceMeasurement | null
  measurementsLoading: boolean
  observation: Observation | null
  onAnalyze: () => void
  compact?: boolean
}

export function SourceSummary({ source, measurement, measurementsLoading }: Pick<InspectorProps, 'source' | 'measurement' | 'measurementsLoading'>) {
  if (!source) return null
  const m = measurement
  const disp = source.change_indicators.find((c) => c.kind === 'displacement')
  const flux = source.change_indicators.find((c) => c.kind === 'flux_variation')
  return (
    <div className="stack" data-testid="source-summary">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3 className="insp-title">{source.label}</h3>
        <OriginBadge origin="derived_measurement" label="Measured" title="Derived measurement: fitted to the image pixels" />
      </div>
      {measurementsLoading && <p className="small muted">Measuring this source in every frame…</p>}
      {m && m.status === 'measured' ? (
        <dl className="kvs">
          <KV k="RA (ICRS)" mono>
            {fmtRaHms(m.ra_deg, 3)}
          </KV>
          <KV k="Dec (ICRS)" mono>
            {fmtDecDms(m.dec_deg, 2)}
          </KV>
          <KV k="Position σ" title="1-sigma: centroid term combined with frame-registration term">
            {fmt(m.sigma_ra_cosdec_mas, 1)} × {fmt(m.sigma_dec_mas, 1)} mas
          </KV>
          <KV k="Flux">
            {fmtPm(m.flux, m.flux_err)} {m.flux_unit === 'electron' ? 'e⁻' : m.flux_unit}
          </KV>
          <KV k="S/N">{fmt(m.snr, 0)}</KV>
          <KV k="Quality">
            <span className="row" style={{ gap: 4 }}>
              <StatusPill status={m.quality.status} />
              {m.quality.flags.map((f) => (
                <span key={f} className="badge" title={f}>
                  {f.replace(/_/g, ' ').toLowerCase()}
                </span>
              ))}
            </span>
          </KV>
        </dl>
      ) : m ? (
        <Callout tone="neutral">
          Not measured at this epoch: <strong>{m.status.replace(/_/g, ' ')}</strong>
          {m.status_reason ? ` — ${m.status_reason}` : ''}
        </Callout>
      ) : null}
      <div className="insp-indicators">
        {[disp, flux].map((c) =>
          c ? (
            <div key={c.kind} className="insp-indicator" title={c.description}>
              <span className="muted small">{c.kind === 'displacement' ? 'Position change' : 'Brightness change'}</span>
              <span className="num">{c.statistic == null ? 'not evaluated' : `χ²/dof ${c.statistic >= 100 ? c.statistic.toFixed(0) : c.statistic.toFixed(1)}`}</span>
              {c.significant != null && <StatusPill status={c.significant ? 'warning' : 'none'} label={c.significant ? `> ${c.threshold}` : 'below threshold'} />}
            </div>
          ) : null,
        )}
        <p className="small faint">Derived statistics across epochs, not a classification. Uncertainties are 1σ.</p>
      </div>
    </div>
  )
}

export function Inspector({ dataset, source, measurement, measurementsLoading, observation, onAnalyze }: InspectorProps) {
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; message: string } | null>(null)
  const explain = canExplainMotion()
  const reg = dataset.frames.find((f) => f.id === observation?.frame_ids.find((id) => id.endsWith(':registered')))?.registration
  const band = dataset.bands.find((b) => b.id === observation?.band_id)
  return (
    <aside className="inspector" aria-label="Source and frame inspector" data-testid="inspector">
      <section className="insp-block">
        <div className="eyebrow">Selected source</div>
        {source ? (
          <>
            <SourceSummary source={source} measurement={measurement} measurementsLoading={measurementsLoading} />
            <div className="insp-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={async () => setSaveMsg(await saveCandidate())}
                disabled={measurementsLoading}
                data-testid="save-candidate"
              >
                <BookmarkPlus size={15} aria-hidden /> Save candidate
              </button>
              <button type="button" className="btn" onClick={onAnalyze} data-testid="to-analyze">
                <Microscope size={15} aria-hidden /> Analyze
              </button>
              <button type="button" className="btn" onClick={explainInMotionLab} title={explain.ok ? 'Open the nearby-source lesson with the fitted values' : explain.reason} data-testid="explain-motion">
                <Orbit size={15} aria-hidden /> Explain motion
              </button>
            </div>
            {!explain.ok && <p className="small faint">{explain.reason}</p>}
            {saveMsg && (
              <Callout tone={saveMsg.ok ? 'info' : 'warning'} role="status">
                {saveMsg.message} {saveMsg.ok && <a href="#/evidence">Open notebook</a>}
              </Callout>
            )}
          </>
        ) : (
          <EmptyState title="No source selected">
            Blink or play the epochs and look for anything that moves or changes brightness. Click a source in the image, or search for a source ID or
            coordinates.
          </EmptyState>
        )}
      </section>
      <section className="insp-block">
        <div className="eyebrow">Displayed frame</div>
        {observation ? (
          <dl className="kvs">
            <KV k="Observation" mono>
              {observation.id.split(':').slice(1).join(':')}
            </KV>
            <KV k="Mid-exposure">{fmtUtc(observation.timing.mid.iso_utc)}</KV>
            <KV k="MJD (TDB)" mono>
              {observation.timing.mid.mjd_tdb.toFixed(5)}
            </KV>
            <KV k="Exposure">{observation.timing.exposure_s} s</KV>
            <KV k="Band">
              {band?.label ?? observation.band_id}
              {band?.width_um ? ` (±${(band.width_um / 2).toFixed(2)} µm)` : ''}
            </KV>
            <KV k="Registration">
              {reg?.rms_residual_mas != null ? `${reg.rms_residual_mas.toFixed(0)} mas rms, ${reg.n_used} stars` : '—'}
            </KV>
            <KV k="Release">{dataset.release}</KV>
          </dl>
        ) : (
          <p className="small muted">No frame at this epoch.</p>
        )}
        <p className="small faint">Pixels are a reprojected display product; measurements use the native frames.</p>
      </section>
    </aside>
  )
}
