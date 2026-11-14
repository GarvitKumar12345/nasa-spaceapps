/* Methods: actual provider statuses and validation results (from the API, never hard-coded),
 * the scientific model, conventions, limitations, and references. */
import { useEffect, useMemo, useState } from 'react'
import { api, describeError } from '../../api/client'
import type { ProviderStatus, TestResult, ValidationReport } from '../../api/types'
import { fmtUtc } from '../../lib/format'
import { Callout, EmptyState, ErrorState, LoadingState, ORIGIN_LABEL, OriginBadge, Panel, StatusPill } from '../../components/ui'
import type { DataOrigin } from '../../api/types'
import './methods.css'

type Load<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; message: string }

const GROUPS: { id: string; title: string; categories: string[]; blurb: string }[] = [
  { id: 'math', title: 'Mathematical checks', categories: ['math', 'coords'], blurb: 'Kepler, astrometric model, time scales, coordinates and WCS against independent methods (astropy, scipy, published relations).' },
  { id: 'measurement', title: 'Source-measurement checks', categories: ['measurement'], blurb: 'PSF rendering/fitting and detection on generated pixels, including Monte-Carlo calibration of reported uncertainties.' },
  { id: 'registration', title: 'Image-registration checks', categories: ['registration'], blurb: 'Registration accuracy against the simulation-truth WCS, transform covariance, reprojection and masks — distinct from numerical round trips.' },
  { id: 'catalog', title: 'Catalog matching', categories: ['catalog'], blurb: 'Epoch propagation from J2016.0 (TCB), covariance growth, ambiguous/unmatched handling.' },
  { id: 'pipeline', title: 'End-to-end synthetic pipeline', categories: ['pipeline'], blurb: 'Injected motion recovered from image measurements; truth used only for validation.' },
  { id: 'contracts', title: 'Contracts, API and export', categories: ['contracts', 'api'], blurb: 'Schema validation, origins, provenance, evidence round trip, staleness, reproduction, CSV.' },
  { id: 'browser', title: 'Browser checks', categories: ['browser', 'ui'], blurb: 'Primary controls, failure states, selection, view switching, persistence, exports, responsive layout.' },
  { id: 'live', title: 'Live-data integration checks', categories: ['live'], blurb: 'Real archive requests (SPHEREx, Gaia DR3, WISE, NEOSSat). None are implemented in this build.' },
]

const STATUS_HELP: [string, string][] = [
  ['documented', 'Documentation reviewed; no code yet.'],
  ['implemented', 'Code exists; status of its checks is in the validation report.'],
  ['tested', 'Verified by an executed check (only the validation report can show this).'],
  ['failed', 'An executed check failed.'],
  ['unavailable', 'Service unreachable when checked.'],
  ['not_run', 'A check exists or is planned but has not been executed.'],
  ['not_implemented', 'Planned; no code.'],
]

export function Methods() {
  const [providers, setProviders] = useState<Load<ProviderStatus[]>>({ status: 'loading' })
  const [report, setReport] = useState<Load<ValidationReport>>({ status: 'loading' })
  const load = () => {
    setProviders({ status: 'loading' })
    setReport({ status: 'loading' })
    api.providers().then((data) => setProviders({ status: 'ready', data }), (e) => setProviders({ status: 'error', message: describeError(e) }))
    api.validation().then((data) => setReport({ status: 'ready', data }), (e) => setReport({ status: 'error', message: describeError(e) }))
  }
  useEffect(load, [])
  return (
    <div className="page me-page">
      <div className="page-head">
        <div>
          <h1>Methods</h1>
          <p className="sub">What SkyShift computes, how it was checked, and what it does not do. Statuses below come from the running code and the last validation run.</p>
        </div>
        <button type="button" className="btn btn-sm" onClick={load}>
          Refresh status
        </button>
      </div>
      <div className="me-grid">
        <Panel title="Data providers and integration status" eyebrow="From /api/providers">
          {providers.status === 'loading' && <LoadingState label="Loading provider status…" />}
          {providers.status === 'error' && <ErrorState message={providers.message} onRetry={load} />}
          {providers.status === 'ready' && <ProviderTable providers={providers.data} />}
        </Panel>
        <Panel title="Validation results" eyebrow="From validation/report.json (npm run validate)">
          {report.status === 'loading' && <LoadingState label="Loading validation report…" />}
          {report.status === 'error' && <ErrorState message={report.message} onRetry={load} />}
          {report.status === 'ready' && <ValidationView report={report.data} providers={providers.status === 'ready' ? providers.data : []} />}
        </Panel>
        <ScienceSection />
        <LimitationsSection />
        <ReferencesSection />
      </div>
    </div>
  )
}

function ProviderTable({ providers }: { providers: ProviderStatus[] }) {
  return (
    <div className="stack" data-testid="provider-table">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Role</th>
              <th>Status</th>
              <th>Release policy</th>
              <th>Reviewed</th>
            </tr>
          </thead>
          <tbody>
            {providers.map((p) => (
              <tr key={p.id} data-provider={p.id}>
                <td>{p.name}</td>
                <td>{p.role}</td>
                <td>
                  <StatusPill status={p.status} />
                </td>
                <td className="small">{p.release_policy}</td>
                <td className="small">{p.last_reviewed_utc ? p.last_reviewed_utc.slice(0, 10) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {providers.map((p) => (
        <details key={p.id} className="me-details">
          <summary>
            {p.name}: capabilities and references
          </summary>
          <p className="small muted">Access route: {p.access_route}</p>
          <ul className="me-caps">
            {p.capabilities.map((c) => (
              <li key={c.name}>
                <StatusPill status={c.status} /> <strong>{c.name}</strong> — <span className="small">{c.detail}</span>
              </li>
            ))}
          </ul>
          {p.notes.map((n) => (
            <p key={n} className="small faint">
              {n}
            </p>
          ))}
          <ul className="small me-refs">
            {p.references.map((r) => (
              <li key={r.url}>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
              </li>
            ))}
          </ul>
        </details>
      ))}
      <details className="me-details">
        <summary>Status vocabulary</summary>
        <dl className="kvs">
          {STATUS_HELP.map(([k, v]) => (
            <div key={k} className="kv">
              <dt>
                <StatusPill status={k} />
              </dt>
              <dd className="small">{v}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  )
}

function countBy(results: TestResult[]): Record<string, number> {
  return results.reduce<Record<string, number>>((acc, r) => ({ ...acc, [r.status]: (acc[r.status] ?? 0) + 1 }), {})
}

function ValidationView({ report, providers }: { report: ValidationReport; providers: ProviderStatus[] }) {
  const grouped = useMemo(() => {
    const known = new Set(GROUPS.flatMap((g) => g.categories))
    const map = GROUPS.map((g) => ({ ...g, results: report.results.filter((r) => g.categories.includes(r.category)) }))
    const other = report.results.filter((r) => !known.has(r.category))
    return { map, other }
  }, [report])
  const plannedLive = providers.flatMap((p) => p.capabilities.filter((c) => c.status === 'not_run').map((c) => ({ provider: p.name, ...c })))
  if (!report.available) {
    return (
      <div className="stack" data-testid="validation-missing">
        <EmptyState title="No validation report yet">
          Run <code>npm run validate</code> at the repository root. Until then every check counts as <StatusPill status="not_run" /> — nothing is shown as passed.
        </EmptyState>
        <LiveGroup results={[]} planned={plannedLive} />
      </div>
    )
  }
  const totals = countBy(report.results)
  return (
    <div className="stack" data-testid="validation-report">
      {report.stale && (
        <Callout tone="warning" role="status">
          <strong>Report is stale:</strong> source files changed after it was generated. Re-run <code>npm run validate</code> to check the current code.
        </Callout>
      )}
      <div className="row me-summary">
        <span className="small muted">Generated {fmtUtc(report.generated_utc)}</span>
        {Object.entries(totals).map(([k, v]) => (
          <StatusPill key={k} status={k} label={`${v} ${k}`} />
        ))}
      </div>
      <div className="table-wrap">
        <table className="table" data-testid="suite-table">
          <thead>
            <tr>
              <th>Suite</th>
              <th>Ran</th>
              <th>Counts</th>
              <th className="r">Duration</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {report.suites.map((s) => (
              <tr key={s.suite}>
                <td>{s.suite}</td>
                <td>{s.ran ? <StatusPill status="ok" label="ran" /> : <StatusPill status="not_run" />}</td>
                <td className="small">{Object.entries(s.counts).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}</td>
                <td className="r">{s.duration_s != null ? `${s.duration_s.toFixed(0)} s` : '—'}</td>
                <td className="small">{s.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {grouped.map.map((g) =>
        g.id === 'live' ? (
          <LiveGroup key={g.id} results={g.results} planned={plannedLive} />
        ) : (
          <ResultGroup key={g.id} title={g.title} blurb={g.blurb} results={g.results} />
        ),
      )}
      {grouped.other.length > 0 && <ResultGroup title="Other" blurb="Tests without a category tag." results={grouped.other} />}
      <details className="me-details">
        <summary>Environment of this run</summary>
        <ul className="small mono">
          {Object.entries(report.environment).map(([k, v]) => (
            <li key={k}>
              {k}: {v}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function ResultGroup({ title, blurb, results }: { title: string; blurb: string; results: TestResult[] }) {
  const counts = countBy(results)
  const failing = results.filter((r) => r.status === 'failed' || r.status === 'error')
  return (
    <section className="me-group" aria-label={title} data-group={title}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3>{title}</h3>
        <div className="row">
          {results.length === 0 ? <StatusPill status="not_run" label="no checks recorded" /> : Object.entries(counts).map(([k, v]) => <StatusPill key={k} status={k} label={`${v} ${k}`} />)}
        </div>
      </div>
      <p className="small muted">{blurb}</p>
      {failing.length > 0 && (
        <Callout tone="error" role="alert">
          {failing.length} check(s) failed in this group; see the messages below.
        </Callout>
      )}
      {results.length > 0 && (
        <details className="me-details" open={failing.length > 0}>
          <summary>{results.length} checks</summary>
          <ul className="me-results">
            {results.map((r) => (
              <li key={`${r.suite}:${r.id}`}>
                <StatusPill status={r.status} /> <span>{r.name}</span> <span className="faint small">({r.suite}{r.file ? ` · ${r.file}` : ''}{r.duration_s != null ? ` · ${r.duration_s.toFixed(2)} s` : ''})</span>
                {r.message && r.status !== 'passed' && <pre className="me-msg">{r.message}</pre>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function LiveGroup({ results, planned }: { results: TestResult[]; planned: { provider: string; name: string; status: string; detail: string }[] }) {
  const ran = results.filter((r) => r.status === 'passed' || r.status === 'failed' || r.status === 'error')
  return (
    <section className="me-group" aria-label="Live-data integration checks" data-testid="live-group">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3>Live-data integration checks</h3>
        <StatusPill status={ran.length ? 'ok' : 'not_run'} label={ran.length ? `${ran.length} executed` : 'not run'} />
      </div>
      <p className="small muted">
        No live SPHEREx, Gaia DR3, WISE or NEOSSat request has been executed by this build. Documentation review is not a live test; mocked responses do not count.
      </p>
      <ul className="me-results">
        {planned.map((c) => (
          <li key={`${c.provider}:${c.name}`}>
            <StatusPill status={c.status} /> <span>{c.provider}: {c.name}</span> <span className="faint small">— {c.detail}</span>
          </li>
        ))}
        {results.map((r) => (
          <li key={r.id}>
            <StatusPill status={r.status} /> {r.name}
          </li>
        ))}
      </ul>
    </section>
  )
}

function ScienceSection() {
  const origins: DataOrigin[] = ['observed', 'simulated', 'simulation_truth', 'derived_measurement', 'model_prediction', 'catalog']
  const originText: Record<DataOrigin, string> = {
    observed: 'Recorded by a real instrument and delivered by an archive (none in this build).',
    simulated: 'Generated by SkyShift: synthetic pixels and the simulated reference catalog.',
    simulation_truth: 'Injected values used to generate simulated data. Validation only; never a measurement.',
    derived_measurement: 'Computed by SkyShift from data arrays: positions, fluxes, fit estimates.',
    model_prediction: 'Evaluated from a declared model and parameters: fitted paths, propagated catalog positions.',
    catalog: 'Values copied from an external catalog such as Gaia DR3 (none in this build).',
  }
  return (
    <Panel title="Science and methods" eyebrow="Models, measurement, conventions">
      <div className="me-science">
        <section>
          <h3>Astrometric model</h3>
          <p>
            Tangent-plane offsets (east, north, in mas) about the mean measured position: <code>east = Δα*₀ + µα*·Δt + ϖ·f_α</code>, <code>north = Δδ₀ + µδ·Δt + ϖ·f_δ</code>,
            with Δt in Julian years (TDB) and parallax factors from the observer’s barycentric position (X, Y, Z in AU):{' '}
            <code>f_α = X sin α − Y cos α</code>, <code>f_δ = X cos α sin δ + Y sin α sin δ − Z cos δ</code>. µα* = dα/dt·cos δ (Gaia convention). Observer: geocentre with
            the Earth from the astropy builtin ephemeris (ERFA epv00). Straight-line space motion is exactly linear in gnomonic coordinates for zero radial velocity.
          </p>
          <p>
            Weighted least squares with each measurement’s full 2×2 covariance; the parameter covariance is not rescaled by χ². A fit is <em>constrained</em> only if dof ≥ 2,
            the time baseline is ≥ 0.25 yr (proper motion) and ≥ 0.5 yr with a parallax-factor span ≥ 0.5 (parallax), the normalised condition number is ≤ 10⁴ and no parallax
            correlation exceeds 0.95; otherwise parameters are reported as not constrained. A distance (1/ϖ) is derived only when ϖ &gt; 0 and ϖ/σ ≥ 10.
          </p>
        </section>
        <section>
          <h3>Measurement and registration</h3>
          <p>
            Positions and fluxes come from a pixel-integrated Gaussian PSF fitted by weighted least squares to unmasked native pixels (never to display or reprojected arrays).
            Quality gates: S/N &lt; 5 → pending; flags for edge truncation, masked pixels in the fit, and χ²/dof &gt; 2 (possible blend). Each frame is registered with a
            similarity transform to isolated, stationary-consistent catalog stars propagated to its epoch, with robust 3σ clipping; the registration term is added to every
            position uncertainty. Reprojected frames on the common grid are display products (bilinear interpolation correlates noise).
          </p>
          <p>
            Catalog matching propagates J2016.0 (TCB) positions with space motion and observer parallax; 2-parameter solutions are not propagated. Results are matched,
            ambiguous (several candidates or a blend) or unmatched — and an unmatched source is not by itself evidence of a new object.
          </p>
        </section>
        <section>
          <h3>Motion lab models</h3>
          <p>
            Two-body Kepler orbits (Kepler’s equation solved by safeguarded Newton iteration, Sun at a focus, period 2π√(a³/GM) independent of e) seen from a circular
            observer orbit; the nearby-source lesson builds the apparent direction from source minus observer vectors with a circular 1 AU observer (approximation). Both are
            checked against independent Python fixtures (scipy DOP853 integration; separate numpy geometry).
          </p>
        </section>
        <section>
          <h3>Conventions</h3>
          <p>
            Pixels are 0-based with integer values at pixel centres; images are shown north up, east left; offsets and uncertainties in mas; recorded times keep their own
            time scale and models use TDB; RA in [0°, 360°).
          </p>
        </section>
        <section>
          <h3>Data origins</h3>
          <ul className="me-origins">
            {origins.map((o) => (
              <li key={o}>
                <OriginBadge origin={o} label={ORIGIN_LABEL[o]} /> <span className="small">{originText[o]}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Panel>
  )
}

function LimitationsSection() {
  return (
    <Panel title="Limitations" eyebrow="Read before interpreting any result">
      <ul className="me-list" data-testid="limitations">
        <li>Synthetic data only: no SPHEREx, Gaia DR3, WISE or NEOSSat data are connected or validated in this build.</li>
        <li>The toy instrument (0.40″/px, Gaussian PSF, Poisson + read noise) is not a SPHEREx sensitivity, PSF or wavelength model.</li>
        <li>The PSF used for fitting is the exact PSF used to render the pixels; real PSFs add model error.</li>
        <li>Single-PSF fits cannot separate blends within ~1.3 FWHM; such fits are flagged rather than corrected.</li>
        <li>Geometric directions only: aberration, light deflection and light-time are not simulated; radial velocity is unknown and assumed 0.</li>
        <li>The geocentre observer is exact for the synthetic data only by declaration; a real spacecraft needs its own ephemeris (bounded: ϖ × r / 1 AU).</li>
        <li>Difference images are display previews without PSF matching or significance estimates; fluxes are uncalibrated counts.</li>
        <li>No automatic discovery, classification, mass, temperature or hazard estimates; a good fit is evidence about a model only.</li>
        <li>Target-name resolution is not available; the evidence notebook is stored only in this browser.</li>
      </ul>
    </Panel>
  )
}

function ReferencesSection() {
  const refs: [string, string][] = [
    ['NASA/IPAC IRSA SPHEREx resources', 'https://irsa.ipac.caltech.edu/Missions/spherex.html'],
    ['SPHEREx archive access documentation', 'https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/'],
    ['SPHEREx data products', 'https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/'],
    ['IRSA SPHEREx tutorials', 'https://caltech-ipac.github.io/irsa-tutorials/spherex/'],
    ['Gaia DR3 documentation (ESA)', 'https://gea.esac.esa.int/archive/documentation/GDR3/'],
    ['Astroquery Gaia TAP', 'https://docs.astropy.org/projects/astroquery/en/stable/gaia/gaia.html'],
    ['WiseView (design precedent; cite if reused)', 'https://github.com/backyardworlds/wiseview'],
    ['CSA NEOSSat mission', 'https://www.asc-csa.gc.ca/eng/satellites/neossat/'],
    ['CADC NEOSSat collection', 'https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/neossat/'],
    ['CADC public web services', 'https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/services/'],
    ['JPL Keplerian elements for approximate positions', 'https://ssd.jpl.nasa.gov/planets/approx_pos.html'],
    ['JPL Horizons manual', 'https://ssd.jpl.nasa.gov/horizons/manual.html'],
    ['Astropy: apply_space_motion', 'https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html'],
    ['Astropy: WCS', 'https://docs.astropy.org/en/stable/wcs/index.html'],
    ['Astropy: Time', 'https://docs.astropy.org/en/stable/time/'],
  ]
  return (
    <Panel title="References and attribution" eyebrow="Sources used by the design and code">
      <ul className="me-refs">
        {refs.map(([t, u]) => (
          <li key={u}>
            <a href={u} target="_blank" rel="noreferrer">
              {t}
            </a>
          </li>
        ))}
      </ul>
      <p className="small muted">
        Software: Astropy, NumPy, SciPy, FastAPI, pydantic, React. Once Gaia data are displayed, SkyShift will carry the acknowledgement: “This work has made use of data from
        the European Space Agency (ESA) mission Gaia, processed by the Gaia Data Processing and Analysis Consortium (DPAC).” No Gaia data are used yet.
      </p>
    </Panel>
  )
}
