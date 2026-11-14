/* Measurement table of a saved record (all epochs, including missing frames). */
import { useMemo, useState } from 'react'
import type { EvidenceRecord, SourceMeasurement } from '../../api/types'
import { tangentPointFor } from '../../components/astrometry/common'
import { OriginBadge, Panel, Segmented, StatusPill } from '../../components/ui'
import { DASH, fmt, fmtPm, fmtUtc } from '../../lib/format'
import { offsetsMas } from '../../lib/tangent'

type PositionMode = 'offsets' | 'coordinates'

function includedLabel(m: SourceMeasurement, included: Set<string>): { text: string; cls: string } {
  if (m.status !== 'measured') return { text: 'not measured', cls: 'ev-inc-none' }
  return included.has(m.id) ? { text: 'included', cls: 'ev-inc-yes' } : { text: 'excluded', cls: 'ev-inc-no' }
}

export function MeasurementsPanel({ record }: { record: EvidenceRecord }) {
  const [mode, setMode] = useState<PositionMode>('offsets')
  const included = useMemo(() => new Set(record.included_measurement_ids), [record])
  const tp = useMemo(() => tangentPointFor(record.measurements, record.fit), [record])
  const fluxUnit = record.measurements.find((m) => m.flux_unit)?.flux_unit ?? ''
  const nMeasured = record.measurements.filter((m) => m.status === 'measured').length

  return (
    <Panel
      title="Measurements"
      eyebrow={<OriginBadge origin="derived_measurement" />}
      actions={
        <Segmented<PositionMode>
          ariaLabel="Position columns"
          value={mode}
          onChange={setMode}
          options={[
            { value: 'offsets', label: 'Offsets (mas)' },
            { value: 'coordinates', label: 'RA, Dec' },
          ]}
        />
      }
    >
      <p className="small muted ev-note">
        {record.measurements.length} epochs: {nMeasured} measured, {record.included_measurement_ids.length} included in the record&apos;s selection.
        {tp && mode === 'offsets' && (
          <>
            {' '}
            Offsets are tangent-plane east (Δα·cosδ) and north (Δδ) from RA {tp.ra_deg.toFixed(6)}°, Dec {tp.dec_deg.toFixed(6)}° (
            {tp.source === 'fit_reference' ? 'fit reference position' : 'mean of measured positions'}).
          </>
        )}{' '}
        Fluxes are PSF-fit amplitudes in the frame unit (uncalibrated).
      </p>
      <div className="table-wrap ev-scroll">
        <table className="table ev-meas-table" data-testid="ev-measurements">
          <caption className="sr-only">Measurements of {record.source.label}, one row per epoch and band</caption>
          <thead>
            <tr>
              <th scope="col">Epoch (UTC)</th>
              <th scope="col">Band</th>
              <th scope="col">Status</th>
              {mode === 'offsets' ? (
                <>
                  <th scope="col" className="r">
                    East ± σ (mas)
                  </th>
                  <th scope="col" className="r">
                    North ± σ (mas)
                  </th>
                </>
              ) : (
                <>
                  <th scope="col" className="r">
                    RA (deg)
                  </th>
                  <th scope="col" className="r">
                    Dec (deg)
                  </th>
                  <th scope="col" className="r">
                    σ RA·cosδ, σ Dec (mas)
                  </th>
                </>
              )}
              <th scope="col" className="r">
                Flux ± σ{fluxUnit ? ` (${fluxUnit})` : ''}
              </th>
              <th scope="col" className="r">
                S/N
              </th>
              <th scope="col">Flags</th>
              <th scope="col">In selection</th>
            </tr>
          </thead>
          <tbody>
            {record.measurements.map((m) => {
              const inc = includedLabel(m, included)
              const has = m.ra_deg !== null && m.dec_deg !== null
              const [e, n] = has && tp ? offsetsMas(m.ra_deg!, m.dec_deg!, tp.ra_deg, tp.dec_deg) : [null, null]
              return (
                <tr key={m.id} className={inc.cls === 'ev-inc-yes' ? undefined : 'excluded'}>
                  <td>{fmtUtc(m.epoch.iso_utc, false)}</td>
                  <td>{m.band_id}</td>
                  <td>
                    <StatusPill status={m.status} title={m.status_reason ?? undefined} />
                    {m.status_reason && <span className="sr-only">: {m.status_reason}</span>}
                  </td>
                  {mode === 'offsets' ? (
                    <>
                      <td className="r mono">{e !== null ? fmtPm(e, m.sigma_ra_cosdec_mas) : DASH}</td>
                      <td className="r mono">{n !== null ? fmtPm(n, m.sigma_dec_mas) : DASH}</td>
                    </>
                  ) : (
                    <>
                      <td className="r mono">{m.ra_deg !== null ? m.ra_deg.toFixed(7) : DASH}</td>
                      <td className="r mono">{m.dec_deg !== null ? m.dec_deg.toFixed(7) : DASH}</td>
                      <td className="r mono">
                        {m.sigma_ra_cosdec_mas !== null ? `${fmt(m.sigma_ra_cosdec_mas, 1)}, ${fmt(m.sigma_dec_mas, 1)}` : DASH}
                      </td>
                    </>
                  )}
                  <td className="r mono">{m.flux !== null ? fmtPm(m.flux, m.flux_err) : DASH}</td>
                  <td className="r">{fmt(m.snr, 1)}</td>
                  <td className="ev-flags">{m.quality.flags.length ? m.quality.flags.join(', ') : DASH}</td>
                  <td>
                    <span className={`ev-inc ${inc.cls}`}>{inc.text}</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
