/* Evidence notebook: saved records (left) and the selected record (right). */
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Download, RotateCcw, Telescope, Upload, X } from 'lucide-react'
import type { EvidenceRecord } from '../../api/types'
import { Callout, EmptyState } from '../../components/ui'
import { fmtUtc } from '../../lib/format'
import { useAppStore } from '../../state/app'
import { useNotebookStore, type ImportResult } from '../../state/notebook'
import { FitStatusBadge, RecordLabelBadge } from './badges'
import { downloadText } from './helpers'
import { RecordDetail } from './RecordDetail'
import './evidence.css'

const MAX_IMPORT_BYTES = 25 * 1024 * 1024

export function Evidence() {
  const records = useNotebookStore((s) => s.records)
  const selectedId = useNotebookStore((s) => s.selectedId)
  const select = useNotebookStore((s) => s.select)
  const loadError = useNotebookStore((s) => s.loadError)
  const saveError = useNotebookStore((s) => s.saveError)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const selected = records.find((r) => r.id === selectedId) ?? null

  useEffect(() => {
    if (!selected && records.length) select(records[0].id)
  }, [selected, records, select])

  return (
    <div className="page ev-page" data-testid="evidence-page">
      <div className="page-head">
        <div>
          <h1>Evidence notebook</h1>
          <p className="sub">Saved measurement records with their provenance. Kept in this browser only: export JSON to keep or share a record.</p>
        </div>
        <div className="row">
          <ImportButton onResult={setImportResult} />
        </div>
      </div>

      <div className="ev-notices">
        {loadError && <StorageProblem message={loadError} />}
        {saveError && <SaveProblem message={saveError} />}
        {importResult && (
          <Callout tone={importResult.ok ? (importResult.rejected || importResult.renamed ? 'warning' : 'info') : 'error'} role="status">
            <div className="ev-callout-row">
              <span data-testid="ev-import-result">{importResult.message}</span>
              <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label="Dismiss import result" onClick={() => setImportResult(null)}>
                <X size={14} aria-hidden />
              </button>
            </div>
          </Callout>
        )}
      </div>

      {records.length === 0 ? (
        <section className="panel" aria-labelledby="ev-records-heading">
          <h2 id="ev-records-heading" className="sr-only" tabIndex={-1}>
            Records
          </h2>
          <EmptyState
            title="No evidence records yet"
            action={
              <div className="row ev-empty-actions">
                <button type="button" className="btn" onClick={() => useAppStore.getState().setSection('observatory')}>
                  <Telescope size={14} aria-hidden /> Go to the Observatory
                </button>
              </div>
            }
          >
            Records are saved from the Observatory: select a source, then use <strong>Save candidate</strong> in the inspector or{' '}
            <strong>Save investigation to notebook</strong> in Analyze mode. Each record keeps the measurements, the fit and its status, the selection and
            the provenance. You can also import a record that was exported as JSON.
          </EmptyState>
        </section>
      ) : (
        <div className="ev-layout">
          <RecordList records={records} selectedId={selected?.id ?? null} onSelect={select} />
          <div className="ev-detail-host">{selected ? <RecordDetail key={selected.id} record={selected} /> : null}</div>
        </div>
      )}
    </div>
  )
}

function RecordList({ records, selectedId, onSelect }: { records: EvidenceRecord[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const listRef = useRef<HTMLUListElement>(null)
  const onKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
    const buttons = [...(listRef.current?.querySelectorAll<HTMLButtonElement>('button.ev-item') ?? [])]
    const idx = buttons.findIndex((b) => b === document.activeElement)
    if (idx < 0) return
    e.preventDefault()
    let next = idx
    if (e.key === 'ArrowDown') next = Math.min(buttons.length - 1, idx + 1)
    if (e.key === 'ArrowUp') next = Math.max(0, idx - 1)
    if (e.key === 'Home') next = 0
    if (e.key === 'End') next = buttons.length - 1
    buttons[next]?.focus()
    const id = buttons[next]?.dataset.recordId
    if (id) onSelect(id)
  }
  return (
    <section className="panel ev-list" aria-labelledby="ev-records-heading">
      <div className="panel-head">
        <h2 id="ev-records-heading" tabIndex={-1}>
          Records
        </h2>
        <span className="badge" aria-label={`${records.length} records`}>
          {records.length}
        </span>
      </div>
      <ul className="ev-items" ref={listRef} onKeyDown={onKey} data-testid="ev-record-list">
        {records.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className="ev-item"
              aria-current={r.id === selectedId ? 'true' : undefined}
              onClick={() => onSelect(r.id)}
              data-record-id={r.id}
            >
              <span className="ev-item-title">{r.title}</span>
              <span className="ev-item-badges">
                <RecordLabelBadge label={r.record_label} />
                {r.fit_status !== 'current' && <FitStatusBadge status={r.fit_status} />}
              </span>
              <span className="ev-item-meta">
                {r.source.label} · <span className="mono">{r.dataset.dataset_id}</span>
              </span>
              <span className="ev-item-meta faint">Updated {fmtUtc(r.updated_utc, false)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ImportButton({ onResult }: { onResult: (r: ImportResult) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const importFromText = useNotebookStore((s) => s.importFromText)
  const announce = useAppStore((s) => s.announce)
  const onFile = async (file: File | undefined) => {
    if (!file) return
    const fail = (message: string) => {
      onResult({ ok: false, message, imported: 0, rejected: 0, renamed: 0, warnings: [] })
      announce(message)
    }
    if (file.size > MAX_IMPORT_BYTES) return fail(`${file.name} is larger than ${MAX_IMPORT_BYTES / 1024 / 1024} MB; nothing was imported.`)
    setBusy(true)
    try {
      const text = await file.text()
      const result = await importFromText(text)
      onResult(result)
      announce(result.message)
    } catch (e) {
      fail(`${file.name} could not be read (${e instanceof Error ? e.message : String(e)}).`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          void onFile(file)
        }}
        data-testid="ev-import-input"
      />
      <button
        type="button"
        className="btn"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        title="Import evidence records (.json); each record is validated by the backend first"
        data-testid="ev-import"
      >
        <Upload size={14} aria-hidden /> {busy ? 'Importing…' : 'Import JSON'}
      </button>
    </>
  )
}

function StorageProblem({ message }: { message: string }) {
  const rawStorage = useNotebookStore((s) => s.rawStorage)
  const resetStorage = useNotebookStore((s) => s.resetStorage)
  const announce = useAppStore((s) => s.announce)
  const [confirm, setConfirm] = useState(false)
  const downloadRaw = () => {
    if (rawStorage === null) return
    const stamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-')
    downloadText(`skyshift-notebook-unreadable-${stamp}.txt`, rawStorage, 'text/plain')
    announce('Downloaded the raw notebook data.')
  }
  return (
    <Callout tone="error" role="alert">
      <div className="stack ev-storage-problem" data-testid="ev-load-error">
        <p>
          <strong>The saved notebook could not be read.</strong> {message} It has not been changed and no records are shown. Download the raw data to keep a
          copy, then reset the notebook to start saving again.
        </p>
        <div className="row">
          <button type="button" className="btn btn-sm" onClick={downloadRaw} disabled={rawStorage === null} data-testid="ev-download-raw">
            <Download size={14} aria-hidden /> Download raw data
          </button>
          {!confirm ? (
            <button type="button" className="btn btn-sm ev-danger" onClick={() => setConfirm(true)} data-testid="ev-reset">
              <RotateCcw size={14} aria-hidden /> Reset notebook
            </button>
          ) : (
            <>
              <span className="small">This permanently deletes the unreadable data.</span>
              <button
                type="button"
                className="btn btn-sm ev-danger-solid"
                onClick={() => {
                  resetStorage()
                  setConfirm(false)
                  announce('Notebook storage reset.')
                }}
                data-testid="ev-reset-confirm"
              >
                Reset now
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setConfirm(false)}>
                Cancel
              </button>
            </>
          )}
        </div>
      </div>
    </Callout>
  )
}

function SaveProblem({ message }: { message: string }) {
  const dismiss = useNotebookStore((s) => s.dismissSaveError)
  return (
    <Callout tone="warning" role="alert">
      <div className="ev-callout-row">
        <span data-testid="ev-save-error">{message}</span>
        <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label="Dismiss storage notice" onClick={dismiss}>
          <X size={14} aria-hidden />
        </button>
      </div>
    </Callout>
  )
}
