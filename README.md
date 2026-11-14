# SkyShift

A local observatory for finding, explaining and documenting changes in astronomical images: **observe → explain → document**.

**Status (2026-11-14):**
- One complete, deterministic **synthetic** investigation works end to end across the four sections (session 1).
- **Real SPHEREx DR1 data** (session 2): 17 validated cutouts of one field (Barnard's Star, two seasons Aug 2025 – May 2026), shown read-only in Observatory with dates, local wavelength, archive flags and provenance; blink only within wavelength-compatible groups. Measurement, registration, fits and difference images are unavailable for observed data. Details and the exact query: [docs/providers/spherex.md](docs/providers/spherex.md).
- Gaia DR3, WISE/unWISE and NEOSSat/CADC are documented boundaries only — not connected. See [docs/providers/](docs/providers/README.md) and the Methods page.

| Section | What it does |
|---|---|
| Observatory | Synthetic: blink/step/play registered epochs on a common sky grid, select a source, measured position ± σ; Analyze: A/B and difference preview, PSF measurements, astrometric fit with identifiability gating, residuals, catalog associations, registration, provenance, save. SPHEREx: read-only viewer of archive-WCS-aligned DR1 cutouts with compatibility groups, flags overlay, file checks and provenance. |
| Motion lab | Two synthetic lessons: Keplerian orbit with a moving observer (equal-time markers, sky-direction view), and nearby-source proper motion + annual parallax derived from observer geometry. |
| Evidence notebook | Browser-local records with source, frames, measurements, fit and its freshness, assumptions, provenance, and (synthetic) seed + truth kept separately; JSON/CSV export, validated import, reproduction from seed. |
| Methods | Live provider statuses, the validation report from real test runs (grouped by check type, incl. "not run" live checks), models, assumptions, limitations, references. |

## Requirements (Windows 11 as developed; also works on macOS/Linux)
- Node.js 22 (npm 10), [uv](https://docs.astral.sh/uv/) with Python 3.13, Google Chrome (browser tests use the installed Chrome).

## Setup and run
```bash
cd backend && uv sync && cd ..          # Python env from uv.lock (numpy 2.5.4, scipy 1.18.1, astropy 8.0.2, fastapi 0.162.7)
cd frontend && npm install && cd ..     # React 19, TypeScript 7, Vite 8 (package-lock.json)
npm install                             # root dev runner (concurrently)
cd backend && uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --from-manifest && cd ..   # real SPHEREx cutouts (~70 MB, network)
npm run dev                             # API http://127.0.0.1:8000 + web http://127.0.0.1:5173
```
Open http://127.0.0.1:5173. The first request builds the synthetic investigation (~10 s); choose *SPHEREx DR1 · field around Barnard's Star* in **Data** for the real images (without the fetch step it is listed as *not fetched* and its observations show as missing). Walkthrough: [docs/demo-script.md](docs/demo-script.md).

## Checks
```bash
npm run test:py      # backend pytest (science, measurement, registration, catalog, pipeline, contracts, API)
npm run test:web     # frontend vitest (physics/WCS parity vs Python fixtures, notebook logic)
npm run e2e          # Playwright browser checks (starts servers if needed)
npm run validate     # all of the above -> validation/report.json, shown in Methods
cd backend && uv run python scripts/validate.py --live   # same, plus the live IRSA (SPHEREx) checks
```
Regenerate fixtures: `cd backend && uv run python scripts/make_wcs_fixtures.py && uv run python scripts/make_motion_fixtures.py`.
After changing `backend/skyshift/contracts.py`: `cd frontend && npm run gen:contracts`.

## Layout
`backend/skyshift/` contracts, coords (time, tangent plane, WCS, observer), science (astrometric fit, catalog propagation/matching), imaging (PSF, detection, registration, reprojection), synthetic (scenario + generator), providers, pipeline, notebook, api, validation · `frontend/src/` api client + generated types, state (zustand), components, sections, physics · `fixtures/` parity fixtures · `docs/` architecture, providers, demo · `planning/` brief and blueprint.

## Limitations
Measurements on synthetic data only: SPHEREx DR1 frames are displayed read-only (archive-WCS alignment, visualization-grade WCS-WAVE wavelengths at the field centre, no photometry/astrometry/registration/fits/differences, the field-centre star is flagged for early overflow and bloom); the toy instrument is not a SPHEREx sensitivity/PSF/wavelength model; the fitting PSF equals the rendering PSF; single-PSF fits cannot separate blends (flagged); geometric directions (no aberration/light-time); radial velocity assumed 0; difference images are display previews; fluxes are uncalibrated counts; no automatic discovery or classification; no target-name resolution; notebook storage is browser-local. Full list on the Methods page and in [docs/architecture.md](docs/architecture.md).
