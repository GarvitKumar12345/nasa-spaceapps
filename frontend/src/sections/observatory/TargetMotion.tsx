/* Target motion study (recorded): genuine SPHEREx observations of a named moving target in both seasons, its measured
 * positions (derived from native pixels) beside the Gaia DR3 predictions (a model), with uncertainties and quality data.
 * Read-only view of a recorded validation study; it never measures anything itself. */
import { useEffect, useRef, useState } from 'react'
import { api, type PlaneData } from '../../api/client'
import type { Dataset, MotionFrame, MotionPair, TargetMotionStudy } from '../../api/types'
import { fmt, fmtSigned, fmtUtc } from '../../lib/format'
import { failed } from '../../state/gaia'
import type { Load } from '../../state/observatory'
import { Callout, ErrorState, LoadingState, OriginBadge, StatusPill } from '../../components/ui'
import { PLOT_COLOR } from '../../components/plot'

const STATUS_PILL: Record<MotionPair['status'], string> = { pass: 'ok', fail: 'error', inconclusive: 'warning', 'not measured': 'neutral' }

/** Pixel position of an (east, north) arcsec offset in the displacement plot (east to the left, north up). */
export function skyToPlot(e: number, n: number, size: number, limit: number): [number, number] {
  const s = size / (2 * limit)
  return [size / 2 - e * s, size / 2 - n * s]
}

/** arcsinh stretch of a stamp to 0..255 (median background, robust scale); NaN stays transparent. */
export function stretchStamp(values: number[]): number[] {
  const finite = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b)
  if (!finite.length) return values.map(() => Number.NaN)
  const med = finite[Math.floor(finite.length / 2)]
  const mad = finite.map((v) => Math.abs(v - med)).sort((a, b) => a - b)[Math.floor(finite.length / 2)] || 1
  const s = values.map((v) => (Number.isFinite(v) ? Math.asinh((v - med) / (1.4826 * mad)) : Number.NaN))
  const top = Math.max(...s.filter((v) => Number.isFinite(v)), 1e-9)
  return s.map((v) => (Number.isFinite(v) ? Math.max(0, Math.min(255, Math.round((255 * Math.max(v, 0)) / top))) : Number.NaN))
}

function DisplacementPlot({ pairs }: { pairs: MotionPair[] }) {
  const size = 220
  const limit = 2.2
  const measured = pairs.filter((p) => p.measured_arcsec && p.predicted_arcsec)
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Measured and predicted displacement between the seasons" data-testid="motion-plot">
      <rect x={0} y={0} width={size} height={size} fill="var(--panel)" stroke="var(--line)" />
      {[-2, -1, 0, 1, 2].map((v) => {
        const [x] = skyToPlot(v, 0, size, limit)
        const [, y] = skyToPlot(0, v, size, limit)
        return (
          <g key={v}>
            <line x1={x} y1={0} x2={x} y2={size} stroke="var(--line)" strokeWidth={v === 0 ? 1 : 0.5} />
            <line x1={0} y1={y} x2={size} y2={y} stroke="var(--line)" strokeWidth={v === 0 ? 1 : 0.5} />
          </g>
        )
      })}
      {measured.map((p) => {
        const [x0, y0] = skyToPlot(0, 0, size, limit)
        const [xp, yp] = skyToPlot(p.predicted_arcsec![0], p.predicted_arcsec![1], size, limit)
        const [xm, ym] = skyToPlot(p.measured_arcsec![0], p.measured_arcsec![1], size, limit)
        const se = Math.hypot(p.sigma_stat_arcsec![0], p.sigma_sys_arcsec![0]) * (size / (2 * limit))
        const sn = Math.hypot(p.sigma_stat_arcsec![1], p.sigma_sys_arcsec![1]) * (size / (2 * limit))
        return (
          <g key={`${p.label}-${p.approach}`} data-pair={p.label} data-approach={p.approach}>
            <line x1={x0} y1={y0} x2={xp} y2={yp} stroke={PLOT_COLOR.model} strokeWidth={2} />
            <circle cx={xp} cy={yp} r={3} fill={PLOT_COLOR.model} />
            <line x1={xm - se} y1={ym} x2={xm + se} y2={ym} stroke={PLOT_COLOR.measured} strokeWidth={1.5} opacity={p.approach === 'tied' ? 1 : 0.5} />
            <line x1={xm} y1={ym - sn} x2={xm} y2={ym + sn} stroke={PLOT_COLOR.measured} strokeWidth={1.5} opacity={p.approach === 'tied' ? 1 : 0.5} />
            <circle cx={xm} cy={ym} r={4.5} fill={p.approach === 'tied' ? PLOT_COLOR.measured : 'var(--panel)'} stroke={PLOT_COLOR.measured} strokeWidth={1.5} />
            <title>{`D${p.detector} ${p.approach}: measured (${fmtSigned(p.measured_arcsec![0], 2)}, ${fmtSigned(p.measured_arcsec![1], 2)})″ ± (${fmt(se / (size / (2 * limit)), 2)}, ${fmt(sn / (size / (2 * limit)), 2)})″; predicted (${fmtSigned(p.predicted_arcsec![0], 2)}, ${fmtSigned(p.predicted_arcsec![1], 2)})″`}</title>
          </g>
        )
      })}
      <text x={6} y={14} fontSize={10} fill="var(--muted)">N ↑</text>
      <text x={6} y={size / 2 - 4} fontSize={10} fill="var(--muted)">E ←</text>
      <text x={size - 50} y={size - 6} fontSize={10} fill="var(--muted)">±{limit}″</text>
    </svg>
  )
}

function Stamp({ plane, frame, label }: { plane: PlaneData; frame: MotionFrame; label: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const h = 6
  const scale = 12
  const cx = Math.round(frame.measured_x_px ?? frame.predicted_x_px)
  const cy = Math.round(frame.measured_y_px ?? frame.predicted_y_px)
  useEffect(() => {
    const cv = ref.current
    const ctx = cv?.getContext('2d')
    if (!cv || !ctx) return
    const [ny, nx] = plane.shape
    const vals: number[] = []
    for (let y = cy - h; y <= cy + h; y++) for (let x = cx - h; x <= cx + h; x++) vals.push(x >= 0 && y >= 0 && x < nx && y < ny ? Number(plane.data[y * nx + x]) : Number.NaN)
    const g = stretchStamp(vals)
    const n = 2 * h + 1
    ctx.clearRect(0, 0, cv.width, cv.height)
    for (let j = 0; j < n; j++)
      for (let i = 0; i < n; i++) {
        const v = g[j * n + i]
        if (!Number.isFinite(v)) continue
        ctx.fillStyle = `rgb(${255 - v},${255 - v},${255 - v})`
        ctx.fillRect(i * scale, (n - 1 - j) * scale, scale, scale) // row 0 at the bottom (pixel y up)
      }
    const at = (x: number, y: number): [number, number] => [(x - (cx - h) + 0.5) * scale, (n - 1 - (y - (cy - h)) + 0.5) * scale]
    const [px, py] = at(frame.predicted_x_px, frame.predicted_y_px)
    ctx.strokeStyle = getComputedStyle(cv).getPropertyValue('--plot-model') || '#2a78d6'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(px - 8, py)
    ctx.lineTo(px + 8, py)
    ctx.moveTo(px, py - 8)
    ctx.lineTo(px, py + 8)
    ctx.stroke()
    if (frame.measured_x_px != null && frame.measured_y_px != null) {
      const [mx, my] = at(frame.measured_x_px, frame.measured_y_px)
      ctx.strokeStyle = getComputedStyle(cv).getPropertyValue('--plot-measured') || '#eb6834'
      ctx.beginPath()
      ctx.moveTo(mx - 6, my - 6)
      ctx.lineTo(mx + 6, my + 6)
      ctx.moveTo(mx + 6, my - 6)
      ctx.lineTo(mx - 6, my + 6)
      ctx.stroke()
    }
  }, [plane, frame, cx, cy])
  return (
    <figure className="motion-stamp" data-frame={frame.frame_id}>
      <canvas ref={ref} width={(2 * h + 1) * scale} height={(2 * h + 1) * scale} aria-label={`${label}: native pixels around the target`} />
      <figcaption className="small mono">{label}</figcaption>
    </figure>
  )
}

function TwoSeasons({ dataset, pair, frames }: { dataset: Dataset; pair: MotionPair; frames: MotionFrame[] }) {
  const members = frames.filter((f) => pair.observation_ids.includes(f.observation_id) && f.detector === pair.detector).sort((a, b) => a.mid_utc.localeCompare(b.mid_utc))
  const [planes, setPlanes] = useState<Record<string, PlaneData | string>>({})
  useEffect(() => {
    let alive = true
    for (const f of members)
      api.framePixels(dataset.id, f.frame_id).then(
        (p) => alive && setPlanes((s) => ({ ...s, [f.frame_id]: p })),
        (e: unknown) => alive && setPlanes((s) => ({ ...s, [f.frame_id]: String(e) })),
      )
    return () => {
      alive = false
    }
  }, [dataset.id, pair.label]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="row" style={{ gap: 12, flexWrap: 'wrap' }} data-testid="motion-two-seasons">
      {members.map((f) => {
        const p = planes[f.frame_id]
        return p == null ? (
          <LoadingState key={f.frame_id} label="Loading native pixels…" />
        ) : typeof p === 'string' ? (
          <ErrorState key={f.frame_id} message={p} />
        ) : (
          <Stamp key={f.frame_id} plane={p} frame={f} label={`D${f.detector} season ${f.season} · ${fmtUtc(f.mid_utc, false)}`} />
        )
      })}
    </div>
  )
}

export function TargetMotionTab({ dataset }: { dataset: Dataset }) {
  const [load, setLoad] = useState<Load<TargetMotionStudy>>({ status: 'loading' })
  const [pick, setPick] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setLoad({ status: 'loading' })
    api.targetMotion(dataset.id).then(
      (data) => alive && setLoad({ status: 'ready', data }),
      (e: unknown) => alive && setLoad(failed(e)),
    )
    return () => {
      alive = false
    }
  }, [dataset.id])
  if (load.status === 'idle' || load.status === 'loading') return <LoadingState label="Loading the recorded motion study…" />
  if (load.status === 'error' || load.status === 'unavailable') return <ErrorState message={load.message} />
  const s = load.data
  const measuredPairs = s.pairs.filter((p) => p.measured_arcsec)
  const shown = measuredPairs.find((p) => p.label === pick) ?? measuredPairs.find((p) => p.role === 'primary' && p.approach === 'tied') ?? measuredPairs[0]
  return (
    <div className="stack" data-testid="target-motion-tab">
      <Callout tone={s.recovered ? 'info' : 'warning'}>
        <strong data-testid="motion-verdict">{s.recovered ? 'Motion recovered from SPHEREx pixels.' : 'Motion not recovered at the required significance.'}</strong>{' '}
        <span data-testid="motion-statement">{s.statement}</span> {s.plan_disclosure}
      </Callout>
      {s.stale && <Callout tone="warning">The code or data changed since this study was computed ({fmtUtc(s.generated_utc)} UTC): re-run scripts/target_motion_stage2.py before relying on it.</Callout>}
      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }} data-testid="motion-legend">
        <span className="small">
          <OriginBadge origin="derived_measurement" label="SPHEREx measurement" /> ePSF position from native pixels ({s.measured_origin})
        </span>
        <span className="small">
          <OriginBadge origin="model_prediction" label="Gaia DR3 prediction" /> {s.target_name}, Gaia DR3 {s.gaia_source_id}, propagated to each exposure ({s.predicted_origin})
        </span>
      </div>
      <div className="row" style={{ gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div>
          <div className="eyebrow">Season 2 minus season 1 (filled: tied to reference stars; open: archive WCS)</div>
          <DisplacementPlot pairs={measuredPairs} />
        </div>
        <div className="stack" style={{ gap: 6, minWidth: 260, flex: 1 }}>
          <div className="eyebrow">Combined primary pairs</div>
          <table className="table" data-testid="motion-combined">
            <thead>
              <tr>
                <th>Approach</th>
                <th className="num nocase">Measured / predicted</th>
                <th className="num nocase">σ vs 0</th>
                <th className="num nocase">p vs prediction</th>
                <th>Budget</th>
                <th>Recovered</th>
              </tr>
            </thead>
            <tbody>
              {s.combined.map((c) => (
                <tr key={c.approach}>
                  <td>{c.approach} ({c.pairs.join(', ')})</td>
                  <td className="num mono">
                    {fmt(c.along_ratio, 2)} ± {fmt(c.along_ratio_sigma, 2)}
                  </td>
                  <td className="num mono">{fmt(c.sigma_vs_zero, 1)}</td>
                  <td className="num mono">{fmt(c.p_vs_prediction, 2)}</td>
                  <td className="small">{c.budget_validated ? 'validated' : 'not validated'}</td>
                  <td>
                    <StatusPill status={c.recovered ? 'ok' : 'warning'} label={c.recovered ? 'yes' : 'no'} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="obs-list small" data-testid="motion-budget-validation">
            {s.budget_validation.map((v) => (
              <li key={v.approach}>
                {v.approach} budget: {v.test}: χ² {fmt(v.chi2, 1)} for {v.dof} dof (p = {fmt(v.p, 2)}) — {v.passed ? 'passed' : 'failed'}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <table className="table" data-testid="motion-pairs">
        <thead>
          <tr>
            <th>Pair</th>
            <th>Epochs (UTC)</th>
            <th className="num nocase">Predicted E, N (″)</th>
            <th className="num nocase">Measured E, N (″)</th>
            <th className="num nocase">σ stat · sys (″)</th>
            <th className="num nocase">Residual (″)</th>
            <th className="num nocase">Ratio · σ vs 0</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {s.pairs.map((p) => (
            <tr key={`${p.label}-${p.approach}`} data-status={p.status} data-role={p.role} onClick={() => p.measured_arcsec && setPick(p.label)} style={{ cursor: p.measured_arcsec ? 'pointer' : 'default' }}>
              <td className="small">
                D{p.detector} {p.approach} ({p.role})
              </td>
              <td className="small mono">{p.epochs_utc.map((e) => e.slice(0, 10)).join(' → ') || '—'}</td>
              <td className="num mono">{p.predicted_arcsec ? `${fmtSigned(p.predicted_arcsec[0], 3)}, ${fmtSigned(p.predicted_arcsec[1], 3)}` : '—'}</td>
              <td className="num mono">{p.measured_arcsec ? `${fmtSigned(p.measured_arcsec[0], 3)}, ${fmtSigned(p.measured_arcsec[1], 3)}` : '—'}</td>
              <td className="num mono">
                {p.sigma_stat_arcsec && p.sigma_sys_arcsec ? `${fmt(Math.hypot(...p.sigma_stat_arcsec) / Math.SQRT2, 2)} · ${fmt(Math.hypot(...p.sigma_sys_arcsec) / Math.SQRT2, 2)}` : '—'}
              </td>
              <td className="num mono">{p.residual_arcsec ? `${fmtSigned(p.residual_arcsec[0], 2)}, ${fmtSigned(p.residual_arcsec[1], 2)}` : '—'}</td>
              <td className="num mono">{p.along_ratio != null ? `${fmt(p.along_ratio, 2)} ± ${fmt(p.along_ratio_sigma, 2)} · ${fmt(p.sigma_vs_zero, 1)}σ` : '—'}</td>
              <td>
                <StatusPill status={STATUS_PILL[p.status]} label={p.status} title={p.status_reason} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown && (
        <div>
          <div className="eyebrow">
            Two seasons, D{shown.detector} — native pixels (13 × 13 px, detector orientation, not north-up); + Gaia DR3 prediction, × ePSF measurement
          </div>
          <TwoSeasons dataset={dataset} pair={shown} frames={s.frames} />
        </div>
      )}
      <table className="table" data-testid="motion-frames">
        <thead>
          <tr>
            <th>Frame</th>
            <th className="num nocase">λ (µm)</th>
            <th className="num nocase">S/N</th>
            <th className="num">References</th>
            <th className="num nocase">χ²/dof (→ neighbour modelled)</th>
            <th className="num nocase">Measured − predicted, archive WCS (″)</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {s.frames.map((f) => (
            <tr key={f.frame_id} data-status={f.status}>
              <td className="small mono">
                D{f.detector} S{f.season ?? '?'} {fmtUtc(f.mid_utc, false)}
              </td>
              <td className="num">{fmt(f.lambda_um, 3)}</td>
              <td className="num">{fmt(f.stage1_snr, 0)}</td>
              <td className="num">{f.n_references}</td>
              <td className="num mono">{f.chi2_red != null ? `${fmt(f.chi2_red, 1)} → ${fmt(f.chi2_red_neighbour_modelled, 1)}` : '—'}</td>
              <td className="num mono">
                {f.residual_untied_arcsec && f.sigma_total_untied_arcsec
                  ? `${fmtSigned(f.residual_untied_arcsec[0], 2)} ± ${fmt(f.sigma_total_untied_arcsec[0], 2)}, ${fmtSigned(f.residual_untied_arcsec[1], 2)} ± ${fmt(f.sigma_total_untied_arcsec[1], 2)}`
                  : '—'}
              </td>
              <td className="small">{f.status === 'measured' ? 'measured' : `${f.status}: ${f.reason}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {s.post_hoc.length > 0 && (
        <p className="small" data-testid="motion-post-hoc">
          <strong>Post hoc (information only):</strong> {s.post_hoc_note}{' '}
          {s.post_hoc.map((c) => `${c.approach}: ${fmt(c.along_ratio, 2)} ± ${fmt(c.along_ratio_sigma, 2)}, ${fmt(c.sigma_vs_zero, 1)}σ vs 0`).join('; ')}.
        </p>
      )}
      <div className="small">
        <div className="eyebrow">Provenance and limitations</div>
        <p>
          Gaia DR3 record: {s.gaia_service ?? '—'} (verification {s.gaia_verification ?? '—'}, cross-check {s.gaia_crosscheck ?? '—'}). Study computed {fmtUtc(s.generated_utc)} UTC.
          Evidence: {s.evidence_files.join(', ')}.
        </p>
        <ul className="obs-list">
          {s.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}
