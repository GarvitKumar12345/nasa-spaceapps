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
  { id: 'measurement', title: 'Source-measurement checks', categories: ['measurement'], blurb: 'Synthetic: PSF rendering/fitting and detection, Monte-Carlo calibration of uncertainties. SPHEREx: ePSF normalisation and lattice samples, noiseless recovery, injection into real pixels (internal consistency); independent renderers (analytic pixel-integrated PSFs, photutils) with PSF-shape, phase, brightness, background, mask and neighbour variations, errors against an independent Cramér–Rao bound.' },
  { id: 'registration', title: 'Image-registration and alignment checks', categories: ['registration'], blurb: 'Synthetic registration against the simulation-truth WCS; SPHEREx alignment diagnostics: residual statistics and decisions against direct formulas, reference selection on a constructed frame, real frames vs Gaia DR3.' },
  { id: 'catalog', title: 'Catalog propagation and matching', categories: ['catalog'], blurb: 'Gaia DR3 epoch propagation vs the archive\'s own ESDC_EPOCH_PROP(_ERROR), ERFA and a Monte Carlo; J2016.0 TCB; missing motion/RV and weak parallaxes; observer parallax applied once; synthetic matching.' },
  { id: 'pipeline', title: 'End-to-end synthetic pipeline', categories: ['pipeline'], blurb: 'Injected motion recovered from image measurements; truth used only for validation.' },
  { id: 'contracts', title: 'Contracts, API and export', categories: ['contracts', 'api'], blurb: 'Schema validation, origins, provenance, evidence round trip, staleness, reproduction, CSV.' },
  { id: 'archive', title: 'Archive product checks (SPHEREx DR1, Gaia DR3)', categories: ['archive'], blurb: 'Recorded real products checked offline: SPHEREx SIA2 response, manifest, cutout fixture and cache against the DR1 format; the Gaia DR3 field response (units, datatypes, RELEASE, COOSYS, COUNT, truncation probe) and its search-radius derivation.' },
  { id: 'browser', title: 'Browser checks', categories: ['browser', 'ui'], blurb: 'Primary controls, failure states, selection, view switching, persistence, exports, responsive layout.' },
  { id: 'live', title: 'Live-data integration checks', categories: ['live'], blurb: 'Real archive requests (run with --live). SPHEREx: discovery, byte-range screening, a cutout download. Gaia DR3: the field query and the archive-side propagation. A changed row count is a note, not a failure; schema, provenance and pinned values must match. A run that never reaches the service is reported as unavailable (with the last successful retrieval), never as passed. WISE and NEOSSat are not implemented.' },
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
      <p className="small muted" data-testid="live-summary">
        {ran.length
          ? `${ran.length} live archive check(s) were executed in the latest validation run and are listed below with their outcome. Anything not listed as executed has not been run.`
          : 'No live archive request is recorded in the latest validation run (live checks run only with --live).'}{' '}
        WISE and NEOSSat have no live checks in this build. Documentation review is not a live test; mocked responses do not count.
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
            {r.notes.length > 0 && (
              <ul className="me-notes" data-testid="live-notes">
                {r.notes.map((n) => (
                  <li key={n} className="small faint">
                    note: {n}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function ScienceSection() {
  const origins: DataOrigin[] = ['observed', 'simulated', 'simulation_truth', 'derived_measurement', 'model_prediction', 'catalog']
  const originText: Record<DataOrigin, string> = {
    observed: 'Recorded by a real instrument and delivered by an archive: SPHEREx DR1 cutouts, shown read-only (archive arrays are never modified).',
    simulated: 'Generated by SkyShift: synthetic pixels and the simulated reference catalog.',
    simulation_truth: 'Injected values used to generate simulated data. Validation only; never a measurement.',
    derived_measurement: 'Computed by SkyShift from data arrays: synthetic positions, fluxes and fits; ePSF positions of Gaia reference stars on SPHEREx frames (alignment diagnostics only).',
    model_prediction: 'Evaluated from a declared model and parameters: fitted paths; Gaia DR3 positions propagated to each exposure (never measurements).',
    catalog: 'Values copied from an external catalog: Gaia DR3 (gaiadr3.gaia_source, recorded field query); source IDs kept as exact strings.',
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
          <h3>Real data: Gaia DR3 predictions and alignment diagnostics (SPHEREx)</h3>
          <p>
            Gaia DR3 is queried once per field with explicit ADQL on gaiadr3.gaia_source over the cutout footprints plus a proper-motion margin (10.5″/yr × the longest
            interval since J2016.0) and a neighbour margin; the response, an independent COUNT(*) and the archive’s own propagation of pinned sources are recorded. Each
            source is propagated to each exposure mid-time with the rigorous uniform-space-motion model of the Gaia DR3 documentation (radial velocity where catalogued,
            6×6 covariance), then the geocentric observer parallax is applied once. Aberration and light deflection are not applied: the SPHEREx WCS is fitted to
            proper-motion-propagated Gaia positions (Explanatory Supplement §3.2.8), and the residuals reject the full-aberration alternative (catalogue frame χ² 12.5
            vs 39 884 for the 5–13″ aberrated frame, 30 dof). That is evidence against full aberration, not proof of every convention: the pipeline’s calibrator parallax
            (≤ 2.6 mas) and centroid definition are undocumented and only bounded, so the convention is reported as partially resolved.
          </p>
          <p>
            Reference stars (5/6-parameter, RUWE ≤ 1.4, isolated by the pipeline’s 10 %-within-2-px rule, unsaturated, ≥ 8 px from saturated regions, clean cores, S/N ≥ 10)
            are fitted with the frame’s own per-zone effective PSF (A&amp;K flux fractions, 25 × the stored array; bicubic spline; zone from detector pixels = cutout + 1 −
            CRPIX1A). The evaluation agrees with photutils ImagePSF to 6e-16 of the peak and the zone choice with the IRSA tutorial rule; the stored ePSF already contains
            the pixel response (integrating it again worsens χ² on every detector). The estimator is checked in every frame by injecting ePSF stars into its real pixels
            (internal consistency) and, independently, against analytic pixel-integrated PSFs and photutils renderings with controlled PSF-shape, phase, brightness,
            background, mask and neighbour variations (errors equal the Cramér–Rao bound for a matched PSF; a 10 % width error gives a 0.01–0.02 px phase error;
            an asymmetry shifts the fit by the first-order light-centroid shift; a plane background is absorbed exactly).
          </p>
          <p>
            Residuals are reported before any correction, per frame and pooled, with RMS east, RMS north and the two-dimensional RMS √(E² + N²) given separately (pooled:
            0.210″, 0.228″, 0.310″). Each frame offset’s uncertainty separates random per-star terms (ePSF centroid, Gaia prediction, Paule–Mandel extra scatter; they shrink
            as 1/√N) from shared per-frame terms that do not average down: PSF-model mismatch (half the shift when refitted with adjacent-zone ePSFs, 0.03–0.12″) and the
            centroid convention (ePSF reference point vs windowed and barycentre centroids, computed from the frame’s ePSFs only, 0.11–0.19″). A constant offset is the only
            correction model; with the shared terms included no frame justifies one (the five frames that did with random errors alone have p = 0.16–0.62), and none is
            applied.
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
        <li>
          Target measurements on synthetic data only. SPHEREx DR1 cutouts are shown read-only: display alignment uses the archive WCS, wavelengths come from the visualization-grade
          WCS-WAVE lookup at the field centre, and no SPHEREx photometry, target astrometry, registration, motion fit or difference image is computed. WISE and NEOSSat are not connected.
        </li>
        <li>
          Gaia DR3 overlays are model predictions placed through the archive WCS (documented RMS &lt; 0.3″). The SPHEREx alignment diagnostics measure only Gaia reference stars;
          they use Gaia G/RP as the isolation flux proxy, the ePSF of the containing zone (no interpolation), and test only a constant offset, which is never applied. Frames
          with fewer than 5 usable references are reported as insufficient.
        </li>
        <li>
          Unresolved estimator effects, documented rather than corrected: on D1–D4 references fit with χ²_red ≈ 6–54, rising with brightness. Part of this is structure
          fixed on the sky that VARIANCE does not describe; the rest is a star-to-star misfit of unknown cause, since the stacked residual is flat to 1 %. The 2 px / 10 %
          isolation rule admits neighbours that shift fits by up to several hundredths of a pixel. A detector-fixed +0.015 px offset in x matches the centroid-convention
          term and is not removed. Centroids are never adjusted to agree with Gaia.
        </li>
        <li>
          Illustrative error-budget estimates of inter-epoch displacement thresholds (5σ, two-dimensional, archive WCS as is): about 1.0–1.3″ for one pair of frames of a bright
          unsaturated star (formal S/N ≥ 150), about 2″ at S/N 50 on D1–D4, and about 0.3–0.6″ when about 10 frames per season are averaged (if their errors are
          independent). These estimates are not validated target detection or completeness measurements. Target motion fitting stays unavailable.
        </li>
        <li>
          The Barnard’s Star field is centred on a star that saturates every selected frame (OVERFLOW, SUR_ERROR and BLOOM within 2.5 px); it is shown only as a prediction and
          excluded from all measurements, together with references within 8 px of saturated regions. CWAVE/CBAND spectral calibration is not used.
        </li>
        <li>
          The van Maanen 2 field (known moving white dwarf): its Gaia DR3 record comes from the ARI partner data centre, used because the ESA archive was unreachable and only
          after ARI reproduced an ESA-recorded response exactly (AIP cross-check identical). An offline validation study, not an app capability, measured the target&rsquo;s
          displacement between the two DR1 seasons. Stage 2 used an analysis plan defined after the first pass, so it is not blind. The two pairs tied to reference stars
          (D2, D3) give 0.94 ± 0.14 of the Gaia-predicted displacement: 5.8σ against zero, consistent with the prediction, and robust to five analysis variants.
          Fifteen reference stars measured in both seasons validate that error budget. Under the plan’s rule the motion is recovered, but no single pair reaches 5σ.
          The target’s high χ² comes from a catalogued neighbour about 2.9 px away that is brighter in the infrared and is not in the nominal model. Modelling it moves
          the target by ≤ 0.008 px; a post-hoc neighbour-modelled estimate gives 9.6σ. The recorded study is shown under Observatory → Analyze → Target motion. No
          general target measurement is enabled, no flux is measured, and no parallax or orbit is fitted from two epochs.
        </li>
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
    ['SPHEREx Explanatory Supplement v2.1 (flags, FINAST, ePSF, WCS-WAVE)', 'https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf'],
    ['IRSA IBE cutout service', 'https://irsa.ipac.caltech.edu/ibe/cutouts.html'],
    ['Gaia DR3 documentation (ESA)', 'https://gea.esac.esa.int/archive/documentation/GDR3/'],
    ['Gaia DR3 data model: gaiadr3.gaia_source', 'https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html'],
    ['ESA Gaia archive: writing queries (ESDC_EPOCH_PROP)', 'https://www.cosmos.esa.int/web/gaia-users/archive/writing-queries'],
    ['Gaia credits and citation (Gaia Collaboration, Vallenari et al. 2023; Prusti et al. 2016)', 'https://www.cosmos.esa.int/web/gaia-users/credits'],
    ['Astroquery Gaia TAP', 'https://astroquery.readthedocs.io/en/latest/gaia/gaia.html'],
    ['IRSA tutorial: SPHEREx ePSF', 'https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/'],
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
        Software: Astropy, NumPy, SciPy, FastAPI, pydantic, React. This work has made use of data from
        the European Space Agency (ESA) mission Gaia, processed by the Gaia Data Processing and Analysis Consortium (DPAC).
        Gaia DR3 recorded catalog data support the overlays and reference-star diagnostics; current live-check availability is reported above.
      </p>
    </Panel>
  )
}
