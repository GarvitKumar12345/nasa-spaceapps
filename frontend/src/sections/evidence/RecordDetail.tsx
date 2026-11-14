/* Detail view of one evidence record: header, actions, results, and content panels. */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { FileJson, FileSpreadsheet, RotateCcw, ShieldCheck, Telescope, Trash2 } from 'lucide-react'
import { api, describeError } from '../../api/client'
import type { EvidenceRecord, EvidenceValidation, ReproductionReport } from '../../api/types'
import { Callout, OriginBadge } from '../../components/ui'
import { fmtUtc } from '../../lib/format'
import { useAppStore } from '../../state/app'
import { useNotebookStore } from '../../state/notebook'
import { useObservatoryStore } from '../../state/observatory'
import { FitStatusBadge, RecordLabelBadge } from './badges'
import { DatasetPanel, SelectionPanel, SourcePanel } from './ContextPanels'
import { FitPanel, PlotsPanel } from './FitPanels'
import { downloadText, excludedMeasuredIds, recordFileName, recordJson, truthOverlay } from './helpers'
import { MeasurementsPanel } from './MeasurementsPanel'
import { AssumptionsPanel, NotesPanel, ProvenancePanel, QualityPanel, SimulationPanel } from './MiscPanels'
import { ReproductionPanel, ValidationPanel } from './ResultPanels'

type Busy = null | 'validate' | 'reproduce' | 'csv' | 'reopen'
type Outcome<T> = { kind: 'ok'; data: T } | { kind: 'error'; message: string }

export function RecordDetail({ record }: { record: EvidenceRecord }) {
  const announce = useAppStore((s) => s.announce)
  const [busy, setBusy] = useState<Busy>(null)
  const [validation, setValidation] = useState<Outcome<EvidenceValidation> | null>(null)
  const [reproduction, setReproduction] = useState<Outcome<ReproductionReport> | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showTruth, setShowTruth] = useState(false)

  const excludedIds = useMemo(() => excludedMeasuredIds(record), [record])
  const overlay = useMemo(() => truthOverlay(record), [record])

  const run = async <T,>(kind: Exclude<Busy, null>, fn: () => Promise<T>): Promise<T | null> => {
    setBusy(kind)
    setActionError(null)
    try {
      return await fn()
    } catch (e) {
      const message = describeError(e)
      if (kind === 'validate') setValidation({ kind: 'error', message })
      else if (kind === 'reproduce') setReproduction({ kind: 'error', message })
      else setActionError(message)
      announce(`Failed: ${message}`)
      return null
    } finally {
      setBusy(null)
    }
  }

  const exportJson = () => {
    downloadText(recordFileName(record, 'json'), recordJson(record), 'application/json')
    announce(`Exported ${recordFileName(record, 'json')}.`)
  }
  const exportCsv = () =>
    void run('csv', async () => {
      const csv = await api.evidenceCsv(record)
      downloadText(recordFileName(record, 'csv'), csv, 'text/csv')
      announce(`Exported ${recordFileName(record, 'csv')}.`)
    })
  const validate = () =>
    void run('validate', async () => {
      const v = await api.validateEvidence(record)
      setValidation({ kind: 'ok', data: v })
      announce(
        v.valid
          ? `Record is valid${v.warnings.length ? ` with ${v.warnings.length} warning${v.warnings.length === 1 ? '' : 's'}` : ''}; recomputed fit status ${v.recomputed_fit_status}.`
          : `Record is invalid: ${v.errors.length} error${v.errors.length === 1 ? '' : 's'}.`,
      )
    })
  const reproduce = () =>
    void run('reproduce', async () => {
      const r = await api.reproduceEvidence(record)
      setReproduction({ kind: 'ok', data: r })
      announce(`Reproduction: ${r.status.replace(/_/g, ' ')}. ${r.reason}`)
    })
  const reopen = () =>
    void run('reopen', async () => {
      await useObservatoryStore.getState().restoreFromRecord(record)
      useAppStore.getState().setSection('observatory')
      announce(`Reopened "${record.title}" in the Observatory.`)
    })

  return (
    <article className="ev-detail" aria-labelledby="ev-detail-title" data-testid="ev-detail">
      <section className="panel ev-head" aria-labelledby="ev-detail-title">
        <div className="ev-head-main">
          <h2 id="ev-detail-title" className="sr-only">
            {record.title}
          </h2>
          <TitleField record={record} />
          <div className="row ev-head-badges">
            <RecordLabelBadge label={record.record_label} />
            <OriginBadge origin={record.dataset.origin} title="Origin of the dataset the measurements were made on" />
            <OriginBadge origin="derived_measurement" title="Positions, fluxes and fit parameters measured by SkyShift" />
            {record.fit?.prediction && <OriginBadge origin="model_prediction" title="Model curve computed from the fit" />}
            {record.simulation?.truth && <OriginBadge origin="simulation_truth" title="Stored separately; shown only when you switch it on" />}
            <FitStatusBadge status={record.fit_status} />
          </div>
          <p className="small muted ev-head-meta">
            <span>
              Record <span className="mono">{record.id.slice(0, 8)}</span>
            </span>
            <span>Created {fmtUtc(record.created_utc, false)}</span>
            <span>Updated {fmtUtc(record.updated_utc, false)}</span>
            <span>
              {record.schema_version} · {record.contracts_version}
            </span>
          </p>
        </div>
        <div className="ev-actions" role="group" aria-label="Record actions">
          <button type="button" className="btn btn-sm" onClick={exportJson} data-testid="ev-export-json">
            <FileJson size={14} aria-hidden /> Export JSON
          </button>
          <button type="button" className="btn btn-sm" onClick={exportCsv} disabled={busy === 'csv'} data-testid="ev-export-csv">
            <FileSpreadsheet size={14} aria-hidden /> {busy === 'csv' ? 'Exporting…' : 'Export CSV'}
          </button>
          <button type="button" className="btn btn-sm" onClick={validate} disabled={busy === 'validate'} data-testid="ev-validate">
            <ShieldCheck size={14} aria-hidden /> {busy === 'validate' ? 'Validating…' : 'Validate'}
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={reproduce}
            disabled={busy === 'reproduce'}
            title="Regenerate the synthetic dataset from its seed and compare every saved value"
            data-testid="ev-reproduce"
          >
            <RotateCcw size={14} aria-hidden /> {busy === 'reproduce' ? 'Reproducing…' : 'Reproduce'}
          </button>
          <button type="button" className="btn btn-sm" onClick={reopen} disabled={busy === 'reopen'} data-testid="ev-reopen">
            <Telescope size={14} aria-hidden /> {busy === 'reopen' ? 'Opening…' : 'Reopen in Observatory'}
          </button>
          <button
            type="button"
            className="btn btn-sm btn-ghost ev-danger"
            onClick={() => setConfirmDelete(true)}
            aria-expanded={confirmDelete}
            aria-controls="ev-delete-confirm"
            data-testid="ev-delete"
          >
            <Trash2 size={14} aria-hidden /> Delete
          </button>
        </div>
        {confirmDelete && <DeleteConfirm record={record} onCancel={() => setConfirmDelete(false)} />}
      </section>

      {busy === 'reproduce' && (
        <Callout tone="neutral" role="status">
          Regenerating the dataset from seed {record.dataset.seed ?? '—'} and re-measuring the source. The first run can take a few tens of seconds.
        </Callout>
      )}
      {actionError && (
        <Callout tone="error" role="alert">
          {actionError}
        </Callout>
      )}
      {record.fit_status === 'stale' && (
        <Callout tone="warning">
          <strong>Stale fit.</strong> The measurement selection changed after this fit was computed, so its parameters, model curve and residuals describe an
          earlier selection, not the included measurements below. Reopen the record in the Observatory and refit to update it.
        </Callout>
      )}

      {validation && <ValidationPanel outcome={validation} record={record} onClose={() => setValidation(null)} />}
      {reproduction && <ReproductionPanel outcome={reproduction} record={record} onClose={() => setReproduction(null)} />}

      <div className="ev-grid-3">
        <DatasetPanel record={record} />
        <SourcePanel record={record} />
        <SelectionPanel record={record} />
      </div>
      <FitPanel record={record} />
      {record.simulation && <SimulationPanel record={record} overlay={overlay} showTruth={showTruth} onShowTruth={setShowTruth} />}
      <PlotsPanel record={record} excludedIds={excludedIds} truth={showTruth ? overlay.points : null} showTruth={showTruth} overlay={overlay} />
      <MeasurementsPanel record={record} />
      <div className="ev-grid-2">
        <AssumptionsPanel record={record} />
        <QualityPanel record={record} />
      </div>
      <NotesPanel record={record} />
      <ProvenancePanel record={record} />
    </article>
  )
}

function TitleField({ record }: { record: EvidenceRecord }) {
  const updateRecord = useNotebookStore((s) => s.updateRecord)
  const announce = useAppStore((s) => s.announce)
  const [value, setValue] = useState(record.title)
  useEffect(() => setValue(record.title), [record.title])
  const commit = () => {
    const next = value.trim()
    if (!next) {
      setValue(record.title)
      announce('A record needs a title; the previous title was kept.')
      return
    }
    if (next !== record.title) {
      updateRecord(record.id, { title: next })
      const err = useNotebookStore.getState().saveError
      announce(err ? `Title changed but not saved: ${err}` : 'Title saved.')
    }
    setValue(next)
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') e.currentTarget.blur()
    if (e.key === 'Escape') setValue(record.title)
  }
  return (
    <div className="ev-title-field">
      <label htmlFor="ev-title-input" className="sr-only">
        Record title
      </label>
      <input
        id="ev-title-input"
        className="ev-title-input"
        value={value}
        maxLength={200}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={onKey}
        title="Edit the title; saved when you leave the field or press Enter"
        data-testid="ev-title"
      />
    </div>
  )
}

function DeleteConfirm({ record, onCancel }: { record: EvidenceRecord; onCancel: () => void }) {
  const removeRecord = useNotebookStore((s) => s.removeRecord)
  const announce = useAppStore((s) => s.announce)
  const confirmRef = useRef<HTMLButtonElement>(null)
  useEffect(() => confirmRef.current?.focus(), [])
  const remove = () => {
    removeRecord(record.id)
    announce(`Deleted "${record.title}" from the notebook.`)
    requestAnimationFrame(() => document.getElementById('ev-records-heading')?.focus())
  }
  return (
    <div
      id="ev-delete-confirm"
      className="ev-confirm"
      role="group"
      aria-label="Confirm deletion"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel()
      }}
    >
      <p>
        Delete <strong>{record.title}</strong>? It is removed from this browser&apos;s notebook and cannot be recovered. Export it as JSON first if you may need
        it.
      </p>
      <div className="row">
        <button ref={confirmRef} type="button" className="btn btn-sm ev-danger-solid" onClick={remove} data-testid="ev-delete-confirm">
          <Trash2 size={14} aria-hidden /> Delete record
        </button>
        <button type="button" className="btn btn-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}
