/* Observatory toolbar: data source (with honest provider availability), target/coordinate
 * search, band (wavelength) selection, field, release, origin, and the Explore/Analyze switch. */
import { useState, type FormEvent } from 'react'
import { Search } from 'lucide-react'
import type { Dataset, DatasetSummary, ProviderStatus } from '../../api/types'
import { useObservatoryStore, type Mode } from '../../state/observatory'
import { Callout, OriginBadge, Segmented } from '../ui'

export function Toolbar({ dataset, datasets, providers }: { dataset: Dataset; datasets: DatasetSummary[]; providers: ProviderStatus[] }) {
  const store = useObservatoryStore()
  const [text, setText] = useState('')
  const onSearch = (e: FormEvent) => {
    e.preventDefault()
    void store.runSearch(text)
  }
  // Placeholders only for image providers that have no dataset of their own in this build.
  const archive = providers.filter((p) => p.id !== 'synthetic' && p.role !== 'catalog' && !datasets.some((d) => d.provider === p.id))
  const observed = dataset.origin === 'observed'
  return (
    <div className="obs-toolbar">
      <div className="obs-heading">
        <div className="row" style={{ gap: 10 }}>
          <h1>Observatory</h1>
          <OriginBadge origin={dataset.origin === 'simulated' ? 'simulated' : 'observed'} label={dataset.origin === 'simulated' ? 'Simulated data' : 'Observed data'} />
        </div>
        <p className="sub">{dataset.title}</p>
      </div>
      <div className="obs-controls">
        <label className="field">
          <span className="field-label">Data</span>
          <select
            className="select"
            value={dataset.id}
            onChange={(e) => void store.selectDataset(e.target.value)}
            aria-label="Dataset"
            data-testid="dataset-select"
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.title} ({d.release}){d.availability !== 'ready' ? ` — ${d.availability.replace('_', ' ')}` : ''}
              </option>
            ))}
            {archive.map((p) => (
              <option key={p.id} value={`provider:${p.id}`} disabled>
                {p.name} — {p.status.replace(/_/g, ' ')}, not connected
              </option>
            ))}
          </select>
        </label>
        <form className="field obs-search" onSubmit={onSearch} role="search">
          <label className="field-label" htmlFor="obs-search">
            Target or coordinates
          </label>
          <div className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>
            <input
              id="obs-search"
              className="input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={observed ? 'Coordinates, e.g. 269.4463 4.7680' : 'S003 · 180.0019 34.9992 · 12:00:00.5 +34:59:57'}
              data-testid="search-input"
            />
            <button type="submit" className="btn btn-icon" aria-label="Search">
              <Search size={15} />
            </button>
          </div>
        </form>
        {observed ? (
          <label className="field">
            <span className="field-label">Wavelength group (at field centre)</span>
            <select className="select obs-group-select" value={store.bandId ?? ''} onChange={(e) => store.setBand(e.target.value)} aria-label="Wavelength group" data-testid="group-select">
              {dataset.bands.map((b) => {
                const n = b.compatibility?.member_observation_ids.length ?? 0
                return (
                  <option key={b.id} value={b.id}>
                    {b.label} · {n} obs{b.compatibility && !b.compatibility.blinkable ? ' · no blink' : ''}
                  </option>
                )
              })}
            </select>
          </label>
        ) : (
          <div className="field">
            <span className="field-label">Band (wavelength)</span>
            <Segmented
              ariaLabel="Band"
              value={store.bandId ?? ''}
              onChange={(v) => store.setBand(v)}
              options={dataset.bands.map((b) => ({ value: b.id, label: `${b.id} ${b.center_um?.toFixed(2)} µm`, title: b.label }))}
              testId="band-select"
            />
          </div>
        )}
        <div className="field">
          <span className="field-label">Field</span>
          <span
            className="obs-static"
            title={observed ? 'Cutout size and archive collection recorded in the retrieval manifest.' : 'Set by the synthetic dataset.'}
          >
            {observed ? `${(dataset.field.fov_arcsec / 60).toFixed(1)}′` : `${dataset.field.fov_arcsec.toFixed(1)}″`} · {dataset.release}
          </span>
        </div>
        <div className="field">
          <span className="field-label">Mode</span>
          <Segmented<Mode>
            ariaLabel="Observatory mode"
            value={store.mode}
            onChange={(m) => store.setMode(m)}
            options={[
              { value: 'explore', label: 'Explore' },
              { value: 'analyze', label: 'Analyze' },
            ]}
            testId="mode-switch"
          />
        </div>
      </div>
      {store.search.message && (
        <div className="obs-search-msg" data-testid="search-message">
          <Callout tone={store.search.tone === 'error' ? 'error' : store.search.tone === 'warning' ? 'warning' : 'info'} role="status">
            {store.search.message}
          </Callout>
        </div>
      )}
    </div>
  )
}
