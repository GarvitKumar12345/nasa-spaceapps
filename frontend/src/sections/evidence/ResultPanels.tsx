/* Results of the backend Validate and Reproduce actions. */
import { X } from 'lucide-react'
import type { EvidenceRecord, EvidenceValidation, ReproductionReport } from '../../api/types'
import { Callout, KV, Panel, StatusPill } from '../../components/ui'
import { FitStatusBadge } from './badges'
import { fmtCheckValue, fmtTiny, shortQuantity } from './helpers'

type Outcome<T> = { kind: 'ok'; data: T } | { kind: 'error'; message: string }

function CloseButton({ onClose, label }: { onClose: () => void; label: string }) {
  return (
    <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label={label} title={label}>
      <X size={14} aria-hidden />
    </button>
  )
}

export function ValidationPanel({ outcome, record, onClose }: { outcome: Outcome<EvidenceValidation>; record: EvidenceRecord; onClose: () => void }) {
  if (outcome.kind === 'error') {
    return (
      <Panel title="Validation" eyebrow="Backend check" actions={<CloseButton onClose={onClose} label="Close validation result" />}>
        <Callout tone="error" role="alert">
          Validation could not run: {outcome.message}
        </Callout>
      </Panel>
    )
  }
  const v = outcome.data
  const statusDiffers = v.recomputed_fit_status !== record.fit_status
  return (
    <Panel
      title="Validation"
      eyebrow="Backend check: contract schema, record semantics, fit freshness"
      actions={
        <>
          <StatusPill status={v.valid ? 'passed' : 'failed'} label={v.valid ? 'Valid' : 'Invalid'} />
          <CloseButton onClose={onClose} label="Close validation result" />
        </>
      }
      className="ev-result"
    >
      <div data-testid="ev-validation-result" className="stack">
        <dl className="kvs ev-kv-grid">
          <KV k="Record">{v.valid ? 'Valid against skyshift.evidence/1' : `Invalid (${v.errors.length} error${v.errors.length === 1 ? '' : 's'})`}</KV>
          <KV k="Stored fit status">
            <FitStatusBadge status={record.fit_status} />
          </KV>
          <KV k="Recomputed fit status">
            <FitStatusBadge status={v.recomputed_fit_status} />
          </KV>
          <KV k="Fit input hash">{v.fit_input_hash_matches === null ? 'no fit' : v.fit_input_hash_matches ? 'matches the saved measurements' : 'does not match'}</KV>
        </dl>
        {statusDiffers && (
          <Callout tone="warning">
            The stored fit status ({record.fit_status}) differs from what the record&apos;s content gives ({v.recomputed_fit_status}). Treat the fit as{' '}
            {v.recomputed_fit_status}.
          </Callout>
        )}
        {v.errors.length > 0 && (
          <div>
            <h3 className="ev-subhead">Errors</h3>
            <ul className="ev-list-plain ev-errors">
              {v.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        )}
        {v.warnings.length > 0 && (
          <div>
            <h3 className="ev-subhead">Warnings</h3>
            <ul className="ev-list-plain ev-warnings">
              {v.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}
        {v.errors.length === 0 && v.warnings.length === 0 && <p className="small muted">No errors or warnings.</p>}
      </div>
    </Panel>
  )
}

export function ReproductionPanel({ outcome, record, onClose }: { outcome: Outcome<ReproductionReport>; record: EvidenceRecord; onClose: () => void }) {
  if (outcome.kind === 'error') {
    return (
      <Panel title="Reproduction" eyebrow="Backend re-derivation" actions={<CloseButton onClose={onClose} label="Close reproduction result" />}>
        <Callout tone="error" role="alert">
          Reproduction could not run: {outcome.message}
        </Callout>
      </Panel>
    )
  }
  const r = outcome.data
  const passed = r.checks.filter((c) => c.passed).length
  return (
    <Panel
      title="Reproduction"
      eyebrow="Regenerated from the recorded seed and compared value by value"
      actions={
        <>
          <StatusPill status={r.status} />
          <CloseButton onClose={onClose} label="Close reproduction result" />
        </>
      }
      className="ev-result"
    >
      <div data-testid="ev-reproduction-result" className="stack">
        <p className="small">{r.reason}</p>
        {r.checks.length > 0 && (
          <>
            <p className="small muted">
              {passed} of {r.checks.length} checks within tolerance. Positions in degrees, fluxes in the frame unit, fit parameters in their own unit.
            </p>
            <div className="table-wrap ev-scroll">
              <table className="table">
                <caption className="sr-only">Reproduction checks</caption>
                <thead>
                  <tr>
                    <th scope="col">Quantity</th>
                    <th scope="col" className="r">
                      Saved
                    </th>
                    <th scope="col" className="r">
                      Reproduced
                    </th>
                    <th scope="col" className="r">
                      |Δ|
                    </th>
                    <th scope="col" className="r">
                      Tolerance
                    </th>
                    <th scope="col">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {r.checks.map((c, i) => (
                    <tr key={i}>
                      <td title={c.quantity}>{shortQuantity(c.quantity, record.measurements)}</td>
                      <td className="r mono">{fmtCheckValue(c.saved)}</td>
                      <td className="r mono">{fmtCheckValue(c.reproduced)}</td>
                      <td className="r mono">{fmtTiny(c.abs_diff)}</td>
                      <td className="r mono">{fmtTiny(c.tolerance)}</td>
                      <td>
                        <StatusPill status={c.passed ? 'passed' : 'failed'} label={c.passed ? 'pass' : 'fail'} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {r.software.length > 0 && (
          <p className="small muted">
            Reproduced with {r.software.map((s) => `${s.name} ${s.version}`).join(', ')}.
          </p>
        )}
      </div>
    </Panel>
  )
}
