/* Fit summary and the shared astrometry plots for a saved record. */
import type { EvidenceRecord, TruthPosition } from '../../api/types'
import { OffsetTimePlots } from '../../components/astrometry/OffsetTimePlot'
import { SkyTrackPlot } from '../../components/astrometry/SkyTrackPlot'
import { Callout, EmptyState, KV, OriginBadge, Panel, StatusPill } from '../../components/ui'
import { DASH, fmt, fmtPm, mjdTdbToJyear, titleCase } from '../../lib/format'
import { FitStatusBadge } from './badges'
import { fmtPValue, type TruthOverlay } from './helpers'

const MODEL_LABEL: Record<NonNullable<EvidenceRecord['fit']>['model'], string> = {
  static: 'Static position',
  proper_motion: 'Proper motion',
  proper_motion_parallax: 'Proper motion + parallax',
}

export function FitPanel({ record }: { record: EvidenceRecord }) {
  const fit = record.fit
  if (!fit) {
    return (
      <Panel title="Astrometric fit" actions={<FitStatusBadge status="none" />}>
        <EmptyState title="No fit saved">This record holds measurements only. Reopen it in the Observatory to fit a motion model.</EmptyState>
      </Panel>
    )
  }
  const id = fit.identifiability
  const stale = record.fit_status === 'stale'
  return (
    <Panel
      title={`Astrometric fit · ${MODEL_LABEL[fit.model]}`}
      eyebrow={<OriginBadge origin="derived_measurement" label="Derived measurement (fit)" />}
      actions={<FitStatusBadge status={record.fit_status} />}
      className={stale ? 'ev-fit ev-fit-stale' : 'ev-fit'}
    >
      <div className="stack" data-testid="ev-fit">
        {stale && (
          <Callout tone="warning">
            <strong>Stale:</strong> computed from a different measurement selection than the one saved in this record.
          </Callout>
        )}
        <p className="small muted">{fit.model_description}</p>
        <div className="ev-fit-grid">
          <dl className="kvs">
            <KV k="Fit quality">
              <StatusPill status={fit.status} />
            </KV>
            <KV k="χ² / dof">
              {fmt(fit.chi2, 2)} / {fit.dof}
            </KV>
            <KV k="Reduced χ²">{fmt(fit.reduced_chi2, 3)}</KV>
            <KV k="p-value" title="Probability of a χ² at least this large if the model and the uncertainties are right">
              {fmtPValue(fit.p_value)}
            </KV>
            <KV k="Reference epoch">
              MJD {fit.reference_epoch.mjd_tdb.toFixed(4)} TDB · J{mjdTdbToJyear(fit.reference_epoch.mjd_tdb).toFixed(3)}
            </KV>
            <KV k="Observer">{fit.inputs.observer.kind.replace(/_/g, ' ')}{fit.inputs.observer.ephemeris ? ` · ${fit.inputs.observer.ephemeris}` : ''}</KV>
          </dl>
          <dl className="kvs">
            <KV k="Identifiability">
              <StatusPill status={id.status} />
            </KV>
            <KV k="Measurements / epochs">
              {id.n_measurements} / {id.n_epochs}
            </KV>
            <KV k="Time baseline">{id.time_baseline_yr !== null ? `${fmt(id.time_baseline_yr, 3)} yr` : DASH}</KV>
            <KV k="Parallax-factor span">{id.parallax_factor_span ? `${fmt(id.parallax_factor_span[0], 2)}, ${fmt(id.parallax_factor_span[1], 2)}` : DASH}</KV>
            <KV k="Condition number">{id.condition_number !== null ? id.condition_number.toPrecision(3) : DASH}</KV>
            <KV k="Max |correlation|">{fmt(id.max_abs_correlation, 3)}</KV>
          </dl>
        </div>
        {id.messages.length > 0 && (
          <ul className="ev-list-plain ev-messages" aria-label="Identifiability messages">
            {id.messages.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}

        <div className="table-wrap">
          <table className="table" data-testid="ev-fit-params">
            <caption className="sr-only">Fitted parameters with 1σ uncertainties</caption>
            <thead>
              <tr>
                <th scope="col">Parameter</th>
                <th scope="col" className="r">
                  Value ± 1σ
                </th>
                <th scope="col">Unit</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {fit.parameters.map((p) => (
                <tr key={p.name}>
                  <td>
                    {p.label} <span className="mono faint">{p.name}</span>
                  </td>
                  <td className="r mono">{p.status === 'not_in_model' ? DASH : fmtPm(p.value, p.uncertainty)}</td>
                  <td>{p.unit}</td>
                  <td>
                    <StatusPill status={p.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3 className="ev-subhead">Derived quantities</h3>
        {fit.derived.length === 0 ? (
          <p className="small muted">None.</p>
        ) : (
          <div className="table-wrap">
            <table className="table ev-table-wrapcells">
              <caption className="sr-only">Quantities derived from the fit</caption>
              <thead>
                <tr>
                  <th scope="col">Quantity</th>
                  <th scope="col" className="r">
                    Value
                  </th>
                  <th scope="col">Status</th>
                  <th scope="col">Basis</th>
                </tr>
              </thead>
              <tbody>
                {fit.derived.map((d) => (
                  <tr key={d.name}>
                    <td>{titleCase(d.name)}</td>
                    <td className="r mono">{d.status === 'derived' ? `${fmtPm(d.value, d.uncertainty)} ${d.unit}` : 'not derived'}</td>
                    <td>
                      <StatusPill status={d.status === 'derived' ? 'ok' : 'not_evaluated'} label={d.status.replace('_', ' ')} />
                    </td>
                    <td className="ev-reason">{d.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {fit.comparisons.length > 0 && (
          <>
            <h3 className="ev-subhead">Model comparison</h3>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Alternative models fitted to the same measurements</caption>
                <thead>
                  <tr>
                    <th scope="col">Model</th>
                    <th scope="col" className="r">
                      χ²
                    </th>
                    <th scope="col" className="r">
                      dof
                    </th>
                    <th scope="col" className="r">
                      BIC
                    </th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {fit.comparisons.map((c) => (
                    <tr key={c.model} className={c.model === fit.model ? 'ev-row-current' : undefined}>
                      <td>
                        {MODEL_LABEL[c.model]}
                        {c.model === fit.model ? ' (saved fit)' : ''}
                      </td>
                      <td className="r">{fmt(c.chi2, 2)}</td>
                      <td className="r">{c.dof}</td>
                      <td className="r">{fmt(c.bic, 2)}</td>
                      <td>
                        <StatusPill status={c.status === 'fit' ? 'ok' : c.status} label={c.status.replace(/_/g, ' ')} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {fit.warnings.length > 0 && (
          <Callout tone="warning">
            <ul className="ev-list-plain">
              {fit.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Callout>
        )}
        <p className="small faint">
          Fit {fit.id.slice(0, 8)} · {fit.method} {fit.method_version} · input hash <span className="mono">{fit.input_hash.slice(0, 12)}…</span> ·{' '}
          {fit.inputs.measurement_ids.length} measurements used, {fit.inputs.excluded_measurement_ids.length} excluded
        </p>
      </div>
    </Panel>
  )
}

export function PlotsPanel({
  record,
  excludedIds,
  truth,
  showTruth,
  overlay,
}: {
  record: EvidenceRecord
  excludedIds: ReadonlySet<string>
  truth: TruthPosition[] | null
  showTruth: boolean
  overlay: TruthOverlay
}) {
  const stale = record.fit_status === 'stale'
  return (
    <Panel
      title="Positions"
      eyebrow="Derived measurements (points, 1σ) and model prediction (dashed)"
      actions={showTruth && overlay.points.length > 0 ? <OriginBadge origin="simulation_truth" label="Simulation truth shown" /> : undefined}
    >
      <div className="ev-plots" data-testid="ev-plots">
        {stale && record.fit?.prediction && (
          <p className="small ev-stale-note">The model curve belongs to a stale fit and is drawn faded.</p>
        )}
        <div>
          <h3 className="plot-title">Sky-plane track (north up, east left)</h3>
          <SkyTrackPlot
            measurements={record.measurements}
            excludedIds={excludedIds}
            fit={record.fit}
            fitStale={stale}
            truth={truth}
            height={340}
            testId="ev-skytrack"
          />
        </div>
        <div>
          <h3 className="plot-title">Offsets versus time</h3>
          <OffsetTimePlots measurements={record.measurements} excludedIds={excludedIds} fit={record.fit} fitStale={stale} truth={truth} />
        </div>
        {showTruth && overlay.basis === 'fixed_position' && (
          <p className="small faint">The matched truth source does not move: its true position is drawn at each measured epoch.</p>
        )}
      </div>
    </Panel>
  )
}
