/* Simulation, assumptions, quality flags, notes and provenance panels. */
import { useEffect, useId, useState } from 'react'
import type { EvidenceRecord, SoftwareVersion } from '../../api/types'
import { Callout, KV, OriginBadge, Panel, Toggle } from '../../components/ui'
import { DASH, fmt, fmtPm, fmtUtc } from '../../lib/format'
import { useAppStore } from '../../state/app'
import { useNotebookStore } from '../../state/notebook'
import type { TruthOverlay } from './helpers'

const TRUTH_KIND: Record<string, string> = {
  stationary_star: 'stationary star',
  moving_nearby_source: 'moving nearby source',
  variable_star: 'variable star',
}

export function SimulationPanel({
  record,
  overlay,
  showTruth,
  onShowTruth,
}: {
  record: EvidenceRecord
  overlay: TruthOverlay
  showTruth: boolean
  onShowTruth: (v: boolean) => void
}) {
  const sim = record.simulation!
  const truth = sim.truth
  const t = overlay.source
  const params = new Map((record.fit?.parameters ?? []).map((p) => [p.name, p]))
  const comparisons = t
    ? [
        { name: 'pmra', label: 'μα* (pmra)', unit: 'mas/yr', truth: t.pmra_mas_yr },
        { name: 'pmdec', label: 'μδ (pmdec)', unit: 'mas/yr', truth: t.pmdec_mas_yr },
        { name: 'parallax', label: 'ϖ (parallax)', unit: 'mas', truth: t.parallax_mas },
      ]
    : []
  const toggleDisabled = !truth || !t || overlay.points.length === 0
  return (
    <Panel title="Simulation" eyebrow={<OriginBadge origin="simulated" />} className="ev-sim">
      <div className="stack">
        <dl className="kvs ev-kv-grid">
          <KV k="Seed" mono>
            {sim.seed}
          </KV>
          <KV k="Generator">
            {sim.generator} {sim.generator_version}
          </KV>
          <KV k="Truth saved">
            {!truth ? 'no (truth was not loaded when the record was saved)' : t ? `yes · ${t.truth_id} (${TRUTH_KIND[t.kind] ?? t.kind})` : 'no truth source within 0.5″ of this detection'}
          </KV>
          <KV k="Truth frames">{truth ? `${truth.frames.length} frame WCS record${truth.frames.length === 1 ? '' : 's'}` : DASH}</KV>
        </dl>
        <Toggle
          checked={showTruth && !toggleDisabled}
          onChange={onShowTruth}
          disabled={toggleDisabled}
          label="Show simulation truth (validation only)"
          title={toggleDisabled ? 'No truth positions are stored for this record' : 'Overlay the generator’s true positions on the plots'}
          testId="ev-truth-toggle"
        />
        {showTruth && t && (
          <>
            <Callout tone="warning">
              Simulation truth is shown for validation only. It is never an input to measurements or fits, and it is not part of the CSV export.
            </Callout>
            <div className="table-wrap">
              <table className="table" data-testid="ev-truth-table">
                <caption className="sr-only">Fitted values compared with simulation truth</caption>
                <thead>
                  <tr>
                    <th scope="col">Quantity</th>
                    <th scope="col" className="r">
                      Fit (derived)
                    </th>
                    <th scope="col" className="r">
                      Truth
                    </th>
                    <th scope="col" className="r">
                      Fit − truth
                    </th>
                    <th scope="col" className="r">
                      (Fit − truth) / σ
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {comparisons.map((c) => {
                    const p = params.get(c.name)
                    const estimated = p && p.status === 'estimated' && p.value !== null
                    const diff = estimated ? p.value! - c.truth : null
                    return (
                      <tr key={c.name}>
                        <th scope="row" className="ev-th-row">
                          {c.label} <span className="faint">({c.unit})</span>
                        </th>
                        <td className="r mono">{estimated ? fmtPm(p.value, p.uncertainty) : p ? p.status.replace(/_/g, ' ') : 'not in fit'}</td>
                        <td className="r mono ev-truth-cell">{fmt(c.truth, 2)}</td>
                        <td className="r mono">{diff !== null ? fmt(diff, 2) : DASH}</td>
                        <td className="r mono">{diff !== null && p?.uncertainty ? fmt(diff / p.uncertainty, 2) : DASH}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="small faint">
              Truth reference epoch {t.reference_epoch.format === 'jyear' ? `J${t.reference_epoch.value}` : String(t.reference_epoch.value)}{' '}
              {t.reference_epoch.scale.toUpperCase()}; radial velocity {fmt(t.radial_velocity_km_s, 1)} km/s (declared). {truth?.warning}
            </p>
          </>
        )}
      </div>
    </Panel>
  )
}

export function AssumptionsPanel({ record }: { record: EvidenceRecord }) {
  return (
    <Panel title="Assumptions">
      {record.assumptions.length === 0 ? (
        <p className="small muted">{record.fit ? 'The fit declared no assumptions.' : 'No fit, so no model assumptions.'}</p>
      ) : (
        <ul className="ev-list-plain ev-bullets">
          {record.assumptions.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function QualityPanel({ record }: { record: EvidenceRecord }) {
  const count = (flag: string) => record.measurements.filter((m) => m.quality.flags.includes(flag)).length
  return (
    <Panel title="Quality flags" eyebrow="Union over all measurements">
      {record.quality_flags.length === 0 ? (
        <p className="small muted">No measurement carries a quality flag.</p>
      ) : (
        <ul className="ev-flag-list">
          {record.quality_flags.map((f) => (
            <li key={f}>
              <span className="badge mono">{f}</span>
              <span className="small muted">
                {count(f)} of {record.measurements.length} epochs
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function NotesPanel({ record }: { record: EvidenceRecord }) {
  const updateRecord = useNotebookStore((s) => s.updateRecord)
  const announce = useAppStore((s) => s.announce)
  const id = useId()
  const [value, setValue] = useState(record.notes)
  const [state, setState] = useState<'idle' | 'saved' | 'error'>('idle')
  useEffect(() => setValue(record.notes), [record.notes])
  const dirty = value !== record.notes
  const save = () => {
    if (!dirty) return
    updateRecord(record.id, { notes: value })
    const err = useNotebookStore.getState().saveError
    setState(err ? 'error' : 'saved')
    announce(err ? `Notes changed but not saved: ${err}` : 'Notes saved.')
  }
  return (
    <Panel title="Notes">
      <div className="field">
        <label htmlFor={id} className="field-label">
          Your notes on this record (saved when you leave the field)
        </label>
        <textarea
          id={id}
          className="input ev-notes"
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            setState('idle')
          }}
          onBlur={save}
          rows={4}
          data-testid="ev-notes"
        />
        <span className="small faint" aria-live="off">
          {dirty ? 'Unsaved changes' : state === 'saved' ? `Saved · updated ${fmtUtc(record.updated_utc, false)}` : state === 'error' ? 'Not saved (see the notice above)' : ' '}
        </span>
      </div>
    </Panel>
  )
}

function SoftwareList({ items }: { items: SoftwareVersion[] }) {
  if (!items.length) return <>{DASH}</>
  return (
    <span className="ev-software">
      {items.map((s) => (
        <span key={`${s.name}-${s.version}`} className="mono">
          {s.name} {s.version}
        </span>
      ))}
    </span>
  )
}

export function ProvenancePanel({ record }: { record: EvidenceRecord }) {
  const p = record.provenance
  const m0 = record.measurements.find((m) => m.status === 'measured') ?? record.measurements[0]
  const nMeas = p.parents.filter((id) => record.measurements.some((m) => m.id === id)).length
  return (
    <Panel title="Provenance" eyebrow={<OriginBadge origin={p.origin} />}>
      <dl className="kvs ev-kv-grid">
        <KV k="Record built by">
          {p.method} {p.method_version}
        </KV>
        <KV k="Record software">
          <SoftwareList items={p.software} />
        </KV>
        <KV k="Inputs">
          {nMeas} measurement{nMeas === 1 ? '' : 's'}
          {record.fit && p.parents.includes(record.fit.id) ? ' + 1 fit' : ''}
        </KV>
        <KV k="Provider">{p.provider}</KV>
        {m0 && (
          <KV k="Measurements by">
            {m0.method} {m0.method_version}
            {m0.provenance.method ? ` · ${m0.provenance.method}` : ''}
          </KV>
        )}
        {m0 && m0.provenance.software.length > 0 && (
          <KV k="Measurement software">
            <SoftwareList items={m0.provenance.software} />
          </KV>
        )}
        {record.fit && (
          <KV k="Fit by">
            {record.fit.method} {record.fit.method_version}
          </KV>
        )}
        {record.fit && (
          <KV k="Fit software">
            <SoftwareList items={record.fit.provenance.software} />
          </KV>
        )}
        <KV k="Record id" mono>
          {record.id}
        </KV>
      </dl>
    </Panel>
  )
}
