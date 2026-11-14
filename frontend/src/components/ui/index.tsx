/* Shared UI primitives. Keep them small, accessible, and token-driven. */
import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { AlertTriangle, Info, OctagonAlert, RefreshCw } from 'lucide-react'
import type { DataOrigin, Quality } from '../../api/types'

/* ---------- Origin ---------- */

export const ORIGIN_LABEL: Record<DataOrigin, string> = {
  observed: 'Observed',
  simulated: 'Simulated',
  simulation_truth: 'Simulation truth',
  derived_measurement: 'Derived measurement',
  model_prediction: 'Model prediction',
  catalog: 'Catalog',
}

/** Shape glyph that accompanies each origin colour (colour is never the only cue). */
export function OriginGlyph({ origin, size = 10 }: { origin: DataOrigin; size?: number }) {
  const s = size
  const h = s / 2
  const common = { width: s, height: s, viewBox: `0 0 ${s} ${s}`, 'aria-hidden': true as const }
  switch (origin) {
    case 'derived_measurement':
      return (
        <svg {...common}>
          <circle cx={h} cy={h} r={h - 1.2} fill="currentColor" />
        </svg>
      )
    case 'model_prediction':
      return (
        <svg {...common}>
          <circle cx={h} cy={h} r={h - 1.2} fill="none" stroke="currentColor" strokeWidth={1.4} strokeDasharray="2 1.5" />
        </svg>
      )
    case 'simulation_truth':
      return (
        <svg {...common}>
          <path d={`M${h} 1 L${s - 1} ${h} L${h} ${s - 1} L1 ${h} Z`} fill="none" stroke="currentColor" strokeWidth={1.3} />
        </svg>
      )
    case 'catalog':
      return (
        <svg {...common}>
          <rect x={1.2} y={1.2} width={s - 2.4} height={s - 2.4} fill="none" stroke="currentColor" strokeWidth={1.3} />
        </svg>
      )
    case 'simulated':
      return (
        <svg {...common}>
          <path d={`M${h} 1 L${s - 1} ${s - 1} L1 ${s - 1} Z`} fill="none" stroke="currentColor" strokeWidth={1.3} />
        </svg>
      )
    default:
      return (
        <svg {...common}>
          <circle cx={h} cy={h} r={h - 1.5} fill="none" stroke="currentColor" strokeWidth={1.3} />
        </svg>
      )
  }
}

export function OriginBadge({ origin, label, title }: { origin: DataOrigin; label?: string; title?: string }) {
  return (
    <span className={`badge origin-${origin}`} title={title ?? ORIGIN_LABEL[origin]} data-origin={origin}>
      <OriginGlyph origin={origin} />
      {label ?? ORIGIN_LABEL[origin]}
    </span>
  )
}

/* ---------- Status ---------- */

export function StatusPill({ status, label, title }: { status: string; label?: string; title?: string }) {
  const text = label ?? status.replace(/_/g, ' ')
  return (
    <span className={`badge status-${status}`} title={title} data-status={status}>
      {text}
    </span>
  )
}

export function QualityTag({ quality }: { quality: Quality }) {
  const detail = [...quality.flags, ...quality.messages].join('\n')
  return <StatusPill status={quality.status} title={detail || undefined} />
}

/* ---------- Layout ---------- */

export function Panel({
  title,
  eyebrow,
  actions,
  children,
  className = '',
  bodyClassName = 'panel-body',
  labelledBy,
}: {
  title?: ReactNode
  eyebrow?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  labelledBy?: string
}) {
  const id = useId()
  return (
    <section className={`panel ${className}`} aria-labelledby={title ? (labelledBy ?? id) : undefined}>
      {(title || actions) && (
        <div className="panel-head">
          <div>
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            {title && <h2 id={labelledBy ?? id}>{title}</h2>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

export function KV({ k, children, mono = false, title }: { k: ReactNode; children: ReactNode; mono?: boolean; title?: string }) {
  return (
    <div className="kv" title={title}>
      <dt>{k}</dt>
      <dd className={mono ? 'mono' : undefined}>{children}</dd>
    </div>
  )
}

export function Callout({
  tone = 'info',
  children,
  role,
}: {
  tone?: 'info' | 'warning' | 'error' | 'neutral'
  children: ReactNode
  role?: 'status' | 'alert'
}) {
  const Icon = tone === 'error' ? OctagonAlert : tone === 'warning' ? AlertTriangle : Info
  return (
    <div className={`callout callout-${tone}`} role={role}>
      <Icon size={15} aria-hidden />
      <div>{children}</div>
    </div>
  )
}

/* ---------- States ---------- */

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden />
      <p>{label}</p>
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <h3>{title}</h3>
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          <RefreshCw size={14} aria-hidden /> Retry
        </button>
      )}
    </div>
  )
}

/* ---------- Controls ---------- */

export interface SegmentedOption<T extends string> {
  value: T
  label: ReactNode
  disabled?: boolean
  title?: string
}

/** Radio-group segmented control with arrow-key navigation. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  testId,
}: {
  options: SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  ariaLabel: string
  testId?: string
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const enabled = options.filter((o) => !o.disabled)
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const idx = enabled.findIndex((o) => o.value === value)
    let next = idx
    if (event.key === 'ArrowRight') next = (idx + 1) % enabled.length
    if (event.key === 'ArrowLeft') next = (idx - 1 + enabled.length) % enabled.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = enabled.length - 1
    const opt = enabled[next]
    if (opt) {
      onChange(opt.value)
      refs.current[options.indexOf(opt)]?.focus()
    }
  }
  return (
    <div className="segmented" role="radiogroup" aria-label={ariaLabel} onKeyDown={onKey} data-testid={testId}>
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => {
            refs.current[i] = el
          }}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          disabled={o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
          data-value={o.value}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
  testId,
  title,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: ReactNode
  disabled?: boolean
  testId?: string
  title?: string
}) {
  return (
    <label className="toggle" title={title}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={testId}
      />
      <span>{label}</span>
    </label>
  )
}

export function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = (v) => String(v),
  disabled,
  testId,
  hint,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
  format?: (value: number) => string
  disabled?: boolean
  testId?: string
  hint?: ReactNode
}) {
  const id = useId()
  return (
    <div className="slider">
      <div className="slider-head">
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id}>{format(value)}</output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={format(value)}
        data-testid={testId}
      />
      {hint && <div className="small faint">{hint}</div>}
    </div>
  )
}

export interface TabDef<T extends string> {
  id: T
  label: ReactNode
}

/** WAI-ARIA tabs (roving tabindex). Render the active panel with role="tabpanel". */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  ariaLabel,
  idPrefix,
}: {
  tabs: TabDef<T>[]
  value: T
  onChange: (id: T) => void
  ariaLabel: string
  idPrefix: string
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const idx = tabs.findIndex((t) => t.id === value)
    let next = idx
    if (event.key === 'ArrowRight') next = (idx + 1) % tabs.length
    else if (event.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = tabs.length - 1
    else return
    event.preventDefault()
    onChange(tabs[next].id)
    refs.current[next]?.focus()
  }
  return (
    <div className="tabs" role="tablist" aria-label={ariaLabel} onKeyDown={onKey}>
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[i] = el
          }}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${t.id}`}
          aria-controls={`${idPrefix}-panel-${t.id}`}
          aria-selected={t.id === value}
          tabIndex={t.id === value ? 0 : -1}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function TabPanel({ idPrefix, id, children }: { idPrefix: string; id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-tab-${id}`} tabIndex={0}>
      {children}
    </div>
  )
}
