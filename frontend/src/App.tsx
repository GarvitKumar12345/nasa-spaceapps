import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { SECTIONS, useAppStore, type Section } from './state/app'
import { Observatory } from './sections/observatory'
import { MotionLab } from './sections/motion'
import { Evidence } from './sections/evidence'
import { Methods } from './sections/methods'

function BrandMark() {
  // Two positions of one source joined by its displacement: the "shift".
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden>
      <circle cx="6" cy="15" r="3.2" fill="none" stroke="var(--text-2)" strokeWidth="1.4" />
      <path d="M8.6 12.6 L13.4 8.4" stroke="var(--violet-strong)" strokeWidth="1.6" strokeLinecap="round" strokeDasharray="2.2 2" />
      <circle cx="16" cy="6.5" r="3.2" fill="var(--teal)" />
    </svg>
  )
}

function ApiIndicator() {
  const apiState = useAppStore((s) => s.api)
  const checkApi = useAppStore((s) => s.checkApi)
  if (apiState.kind === 'checking') {
    return (
      <span className="api-indicator" role="status">
        <span className="dot dot-checking" aria-hidden /> Connecting to API…
      </span>
    )
  }
  if (apiState.kind === 'online') {
    const v = apiState.health
    return (
      <span className="api-indicator" title={`SkyShift ${v.skyshift_version} · ${v.contracts_version}`} data-testid="api-online">
        <span className="dot dot-ok" aria-hidden /> API connected
      </span>
    )
  }
  return (
    <button type="button" className="btn btn-sm api-offline" onClick={() => void checkApi()} title={apiState.message} data-testid="api-offline">
      <span className="dot dot-bad" aria-hidden /> API offline <RefreshCw size={12} aria-hidden />
    </button>
  )
}

const SECTION_COMPONENT: Record<Section, () => React.JSX.Element> = {
  observatory: Observatory,
  motion: MotionLab,
  evidence: Evidence,
  methods: Methods,
}

export function App() {
  const section = useAppStore((s) => s.section)
  const liveMessage = useAppStore((s) => s.liveMessage)
  const checkApi = useAppStore((s) => s.checkApi)
  // Mount a section on first visit, then keep it mounted (hidden) so its view
  // state and loaded frames survive switching sections.
  const [visited, setVisited] = useState<Set<Section>>(() => new Set([section]))

  useEffect(() => {
    void checkApi()
  }, [checkApi])

  useEffect(() => {
    setVisited((prev) => (prev.has(section) ? prev : new Set(prev).add(section)))
    const label = SECTIONS.find((s) => s.id === section)?.label ?? ''
    document.title = `${label} · SkyShift`
  }, [section])

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <a className="brand" href="#/observatory" aria-label="SkyShift, go to Observatory">
          <BrandMark />
          <span>SkyShift</span>
        </a>
        <nav className="nav" aria-label="Sections">
          {SECTIONS.map((s) => (
            <a key={s.id} className="nav-link" href={`#/${s.id}`} aria-current={section === s.id ? 'page' : undefined} data-testid={`nav-${s.id}`}>
              {s.label}
            </a>
          ))}
        </nav>
        <div className="topbar-right">
          <ApiIndicator />
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        {SECTIONS.map(({ id }) => {
          if (!visited.has(id)) return null
          const Component = SECTION_COMPONENT[id]
          return (
            <div key={id} className="section-host" hidden={section !== id} data-section={id}>
              <Component />
            </div>
          )
        })}
      </main>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {liveMessage}
      </div>
    </div>
  )
}
