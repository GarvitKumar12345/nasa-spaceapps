/* Record label and fit-status badges (text + shape; colour is never the only cue). */
import type { EvidenceRecord } from '../../api/types'
import { OriginGlyph, StatusPill } from '../../components/ui'

export function RecordLabelBadge({ label }: { label: EvidenceRecord['record_label'] }) {
  if (label === 'synthetic training record') {
    return (
      <span className="badge ev-label ev-label-synthetic" data-testid="ev-record-label" title="Built from simulated data: for training and validation, not a claim about the real sky">
        <OriginGlyph origin="simulated" />
        Synthetic training record
      </span>
    )
  }
  return (
    <span className="badge ev-label ev-label-candidate" data-testid="ev-record-label" title="Built from observed data: a candidate that needs independent review">
      <OriginGlyph origin="observed" />
      Candidate for review
    </span>
  )
}

const FIT_STATUS_TEXT: Record<EvidenceRecord['fit_status'], string> = {
  current: 'Fit current',
  stale: 'Fit stale',
  none: 'No fit',
}
const FIT_STATUS_TITLE: Record<EvidenceRecord['fit_status'], string> = {
  current: 'The fit used exactly the included measurements of this record.',
  stale: 'The measurement selection changed after the fit: its parameters describe an earlier selection.',
  none: 'This record contains no model fit.',
}

export function FitStatusBadge({ status }: { status: EvidenceRecord['fit_status'] }) {
  return <StatusPill status={status} label={FIT_STATUS_TEXT[status]} title={FIT_STATUS_TITLE[status]} />
}
