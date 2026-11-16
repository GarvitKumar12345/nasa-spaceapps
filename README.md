# SkyShift

A local observatory for finding, explaining and documenting changes in astronomical images: **observe → explain → document**.

**Current local release:** SkyShift Discover and BlinkIR Explore share one native application. The work remains on local branch `session-4-estimator-review`; remote main does not include this release.

- **Recorded real-data result:** van Maanen 2's seasonal displacement in SPHEREx DR1: 216 discovered image products, 13 validated cutouts, primary reference-tied D2 + D3 result **0.94 ± 0.14** of the Gaia prediction, **5.8σ** against zero, **p = 0.93** against the prediction. Not blind; no individual pair reaches 5σ, and no independent proper-motion or parallax fit was made. The separate post-hoc 9.6σ estimate is exploratory. [Authoritative Stage 2 record](docs/reviews/2026-11-16-van-maanen-2-stage2.md).
- **Observed viewing:** Barnard and van Maanen 2 fields, dates, archive flags, provenance, Gaia predictions and reference-star diagnostics. Generic target fitting, calibrated photometry and real difference imaging remain unavailable.
- **Integrity and export:** Target motion displays a science-specific integrity check against commit `0c7f4ab`, independent of application test freshness. Export downloads the original study, CSV, figures, manifests, integrity status and reproduction notes. Missing local cutouts remain explicit.
- **BlinkIR:** five supplied educational presets, side-by-side scenes, blinking, synthetic subtraction, pixel inspection, illustrative infrared model curves and simulation lesson export. All imagery is simulated and model values are arbitrary units; live calibrated spectroscopy and observed epoch extraction are unavailable.
- The complete synthetic investigation, Motion lab and reproducible Evidence Notebook remain available. WISE/unWISE and NEOSSat/CADC are documented boundaries, without live integrations.

| Section | What it does |
|---|---|
| Observatory | Synthetic: blink/step/play registered epochs on a common sky grid, select a source, measured position ± σ; Analyze: A/B and difference preview, PSF measurements, astrometric fit with identifiability gating, residuals, catalog associations, registration, provenance, save. SPHEREx: recorded van Maanen 2 Target motion study and evidence ZIP, plus a read-only viewer of archive-WCS-aligned DR1 cutouts with compatibility groups, flags overlay, file checks and provenance; Gaia DR3 predictions per exposure (select a marker for catalogue values, prediction and image measurement); Analyze → Gaia DR3 / Alignment for the query, convention, error budget and residuals. |
| Motion lab | Two synthetic lessons: Keplerian orbit with a moving observer (equal-time markers, sky-direction view), and nearby-source proper motion + annual parallax derived from observer geometry. |
| Evidence notebook | Browser-local records with source, frames, measurements, fit and its freshness, assumptions, provenance, and (synthetic) seed + truth kept separately; JSON/CSV export, validated import, reproduction from seed. |
| BlinkIR | Native educational infrared studio; explicitly simulated images and model spectra, isolated simulation exports. |
| Methods | Live provider statuses, the validation report from real test runs (grouped by check type, incl. "not run" live checks), models, assumptions, limitations, references. |

## Requirements (Windows 11 as developed; also works on macOS/Linux)
- Node.js 22 (npm 10), [uv](https://docs.astral.sh/uv/) with Python 3.13, Google Chrome (browser tests use the installed Chrome).

## Setup and run
```bash
cd backend && uv sync && cd ..          # Python env from uv.lock (numpy 2.5.4, scipy 1.18.1, astropy 8.0.2, fastapi 0.162.7)
cd frontend && npm install && cd ..     # React 19, TypeScript 7, Vite 8 (package-lock.json)
npm install                             # root dev runner (concurrently)
cd backend && uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --from-manifest && cd ..   # real SPHEREx cutouts (~70 MB, network)
# Gaia DR3 for that field is committed (fixtures/gaia_dr3/); to re-query: cd backend && uv run python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-barnard
npm run dev                             # API http://127.0.0.1:8000 + web http://127.0.0.1:5173
```
For the recorded van Maanen 2 images, also run from backend: `uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-vanmaanen2 --from-manifest`. Both Gaia DR3 responses and scientific evidence are committed; image cutouts are downloaded caches. No ESA re-query is required to view the committed study. Its field uses the verified ARI record, with the AIP cross-check recorded in provenance.

Open http://127.0.0.1:5173. The first request builds the synthetic investigation (~10 s); choose *SPHEREx DR1 · field around Barnard's Star* in **Data** for the real images (without the fetch step it is listed as *not fetched* and its observations show as missing). Walkthrough: [docs/demo-script.md](docs/demo-script.md).

## Checks
```bash
npm run test:py      # backend pytest (science, measurement, registration, catalog, pipeline, contracts, API)
npm run test:web     # frontend vitest (physics/WCS parity vs Python fixtures, notebook logic)
npm run e2e          # Playwright browser checks (starts servers if needed)
npm run validate     # all of the above -> validation/report.json, shown in Methods
cd backend && uv run python scripts/validate.py --live   # same, plus the live IRSA (SPHEREx) and ESA (Gaia DR3) checks
```
Regenerate fixtures: `cd backend && uv run python scripts/make_wcs_fixtures.py && uv run python scripts/make_motion_fixtures.py`.
After changing `backend/skyshift/contracts.py`: `cd frontend && npm run gen:contracts`.

## Layout
`backend/skyshift/` contracts, coords (time, tangent plane, WCS, observer), science (astrometric fit, catalog propagation/matching), imaging (PSF, detection, registration, reprojection), synthetic (scenario + generator), providers, pipeline, notebook, api, validation · `frontend/src/` api client + generated types, state (zustand), components, sections, physics · `fixtures/` parity fixtures · `docs/` architecture, providers, demo · `planning/` brief and blueprint.

## Limitations
General target measurements use synthetic data. The van Maanen 2 viewer presents a **recorded, limited validation study**, not an arbitrary-target fitting service. Its primary analysis is not blind, ignores east/north covariance in pair tests, and combines D2 + D3; D1 failed the start test, D5 lacks tied references and D6 fails the S/N criterion. No independent proper motion or parallax is solved. Barnard's Star saturates the selected frames. SPHEREx photometry, general registration/fitting and calibrated differences remain unavailable. Gaia overlays are predictions. BlinkIR uses toy Gaussian images and illustrative spectra, not an instrument simulation or atmospheric confirmation. Synthetic notebook records and simulation lesson exports are separate from real scientific evidence.

The study seal checks the original committed science code/import closure, selected shared declarations, recorded inputs, dependency lock, outputs and local cutout checksums. It canonicalizes LF/CRLF for text. Missing cutouts affect reproducibility, not the integrity of available recorded evidence. The original execution hash differs from the committed tree hash and is retained: the seal certifies equality to that reference commit, not retrospective execution. Full application test freshness is checked independently by Methods. See [Stage 3 handoff](docs/reviews/2026-11-16-stage3-handoff.md).

No hosted demonstration URL is configured. The supplied GitHub URL could not be verified publicly during this continuation; no publication was performed.
