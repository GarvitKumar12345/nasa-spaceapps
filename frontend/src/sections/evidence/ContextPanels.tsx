/* Dataset reference, source identity and selection of a record. */
import type { Epoch, EvidenceRecord } from '../../api/types'
import { KV, OriginBadge, Panel, StatusPill } from '../../components/ui'
import { DASH, fmt, fmtDecDms, fmtRaHms, fmtUtc, mjdTdbToJyear } from '../../lib/format'
import { PROVIDER_LABEL } from './helpers'

export function DatasetPanel({ record }: { record: EvidenceRecord }) {
  const d = record.dataset
  return (
    <Panel title="Dataset reference" eyebrow={<OriginBadge origin={d.origin} />}>
      <dl className="kvs">
        <KV k="Dataset" mono>
          {d.dataset_id}
        </KV>
        <KV k="Provider">{PROVIDER_LABEL[d.provider] ?? d.provider}</KV>
        <KV k="Release" mono>
          {d.release}
        </KV>
        <KV k="Generator">{d.generator ? `${d.generator} ${d.generator_version ?? ''}`.trim() : DASH}</KV>
        <KV k="Seed" mono>
          {d.seed ?? DASH}
        </KV>
      </dl>
      {d.origin === 'simulated' && (
        <p className="small muted ev-note">Simulated pixels from the seeded generator: training data, not the real sky.</p>
      )}
    </Panel>
  )
}

function epochText(e: Epoch | null | undefined): string {
  if (!e) return DASH
  return `${fmtUtc(e.iso_utc)} (J${mjdTdbToJyear(e.mjd_tdb).toFixed(4)} TDB)`
}

export function SourcePanel({ record }: { record: EvidenceRecord }) {
  const s = record.source
  const p = s.reference_position
  const assoc = s.catalog_associations
  const counts = new Map<string, number>()
  for (const a of assoc) counts.set(a.status, (counts.get(a.status) ?? 0) + 1)
  const simulatedCatalog = record.dataset.origin === 'simulated'
  return (
    <Panel title="Source identity" eyebrow={<OriginBadge origin={s.origin} />}>
      <dl className="kvs">
        <KV k="Source">
          {s.label} <span className="mono faint">({s.source_id})</span>
        </KV>
        <KV k="Reference RA" mono title={`${p.ra_deg.toFixed(7)}°`}>
          {fmtRaHms(p.ra_deg)} · {p.ra_deg.toFixed(6)}°
        </KV>
        <KV k="Reference Dec" mono title={`${p.dec_deg.toFixed(7)}°`}>
          {fmtDecDms(p.dec_deg)} · {p.dec_deg.toFixed(6)}°
        </KV>
        <KV k="Measured at">{epochText(p.epoch)}</KV>
        <KV k="Frame">ICRS</KV>
      </dl>
      <h3 className="ev-subhead">
        Catalog associations{' '}
        <OriginBadge origin="catalog" label={simulatedCatalog ? 'Simulated catalog' : 'Catalog'} />
      </h3>
      {assoc.length === 0 ? (
        <p className="small muted">No catalog association was saved with this record.</p>
      ) : (
        <>
          <p className="row small">
            {[...counts.entries()].map(([status, n]) => (
              <StatusPill key={status} status={status} label={`${n} ${status.replace(/_/g, ' ')}`} />
            ))}
          </p>
          <div className="table-wrap ev-scroll-sm">
            <table className="table">
              <caption className="sr-only">Catalog associations per epoch</caption>
              <thead>
                <tr>
                  <th scope="col">Epoch (UTC)</th>
                  <th scope="col">Status</th>
                  <th scope="col">Nearest</th>
                  <th scope="col" className="r">
                    Sep. (″)
                  </th>
                </tr>
              </thead>
              <tbody>
                {assoc.map((a, i) => {
                  const nearest = [...a.candidates].sort((x, y) => x.separation_arcsec - y.separation_arcsec)[0]
                  return (
                    <tr key={`${a.measurement_id ?? i}`}>
                      <td>{fmtUtc(a.epoch.iso_utc, false)}</td>
                      <td>
                        <StatusPill status={a.status} title={[a.criteria, ...a.notes].join('\n')} />
                      </td>
                      <td className="mono">{nearest?.catalog_source_id ?? DASH}</td>
                      <td className="r">{nearest ? fmt(nearest.separation_arcsec, 3) : DASH}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="small faint ev-note">An unmatched source is not evidence of a new object.</p>
        </>
      )}
    </Panel>
  )
}

export function SelectionPanel({ record }: { record: EvidenceRecord }) {
  const sel = record.selection
  const v = sel.view
  // frame -> (observation, epoch): from the record's measurements, else from the parallel observation/epoch lists.
  const fromMeasurements = new Map(record.measurements.map((m) => [m.frame_id, { obs: m.observation_id, epoch: m.epoch }]))
  const rows = sel.frame_ids.map((frameId) => {
    const m = fromMeasurements.get(frameId)
    if (m) return { frameId, obs: m.obs, epoch: m.epoch as Epoch | null }
    const obsIndex = sel.observation_ids.findIndex((o) => frameId === o || frameId.startsWith(`${o}:`))
    return { frameId, obs: obsIndex >= 0 ? sel.observation_ids[obsIndex] : null, epoch: obsIndex >= 0 ? (sel.epochs[obsIndex] ?? null) : null }
  })
  const stretch = Object.entries(v.stretch)
  return (
    <Panel title="Selection" eyebrow="What was on screen when saved">
      <dl className="kvs">
        <KV k="Bands">{sel.band_ids.length ? sel.band_ids.join(', ') : DASH}</KV>
        <KV k="View">
          {v.mode === 'analyze' ? 'Analyze' : 'Explore'}
          {v.band_id ? ` · band ${v.band_id}` : ''}
          {v.zoom !== null ? ` · zoom ${fmt(v.zoom, 2)}×` : ''}
        </KV>
        <KV k="Centre (grid px)" mono>
          {v.center_x_px !== null && v.center_y_px !== null ? `${fmt(v.center_x_px, 1)}, ${fmt(v.center_y_px, 1)}` : DASH}
        </KV>
        <KV k="Field of view">{v.fov_arcsec !== null ? `${fmt(v.fov_arcsec, 1)}″` : DASH}</KV>
        {stretch.length > 0 && (
          <KV k="Display stretch" mono title="Display-only settings; never used in measurements">
            {stretch.map(([k, val]) => `${k}=${val}`).join(', ')}
          </KV>
        )}
      </dl>
      <h3 className="ev-subhead">Frames</h3>
      {rows.length === 0 ? (
        <p className="small muted">No frames were recorded.</p>
      ) : (
        <ul className="ev-frames">
          {rows.map((r) => (
            <li key={r.frameId}>
              <span className="mono ev-frame-id" title={r.frameId}>
                {r.frameId}
              </span>
              <span className="small muted">
                {r.epoch ? fmtUtc(r.epoch.iso_utc) : 'epoch not recorded'}
                {v.frame_id === r.frameId ? ' · current frame' : v.compare_frame_id === r.frameId ? ' · compare frame' : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
