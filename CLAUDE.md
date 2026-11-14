# SkyShift — project guidance

Local observatory app for finding, explaining, and documenting changes in astronomical images.
Requirements (authoritative, keep detail there): `planning/SkyShift_Claude_Code_Brief.md`.
Architecture, synthetic scenario, module/API contracts: `docs/architecture.md`.
Design background: `planning/SkyShift_Project_Blueprint.md`, `planning/skyshift-design.html` (sketch, synthetic only).

## Run (Windows; Git Bash or PowerShell)
- First time: `cd backend && uv sync` · `cd frontend && npm install` · `npm install` (repo root)
- Dev (both servers): `npm run dev` at repo root → http://127.0.0.1:5173 (API on :8000, proxied at `/api`)
- Backend only: `cd backend && uv run uvicorn skyshift.api.app:app --host 127.0.0.1 --port 8000`

## Test
- Python: `cd backend && uv run pytest` (markers: math, coords, measurement, registration, catalog, pipeline, contracts, api, slow; `-m live` for archive tests, skipped by default)
- TypeScript: `cd frontend && npm run test` (vitest) · `npm run typecheck` · `npm run build`
- Browser: `cd frontend && npm run e2e` (Playwright, system Chrome; starts servers if needed)
- Full validation report for Methods: `npm run validate` (repo root) → `validation/report.json`
- After editing `backend/skyshift/contracts.py`: `cd frontend && npm run gen:contracts`
- Parity fixtures (commit them): `cd backend && uv run python scripts/make_wcs_fixtures.py && uv run python scripts/make_motion_fixtures.py`
- Extra dev/e2e instances: set `SKYSHIFT_API_PORT` / `SKYSHIFT_WEB_PORT` (Vite proxy and Playwright read them)
- Demo walkthrough: `docs/demo-script.md`; provider boundaries and planned live checks: `docs/providers/`

## Scientific conventions (do not break)
- Pixels 0-based, integer = pixel centre; numpy `[iy, ix]`; FITS headers keep 1-based CRPIX.
- RA in [0, 360); `pmra`/`ra_cosdec` = dRA·cos(Dec); offsets east/north in mas; display north up, east left.
- Models use TDB (`Epoch.mjd_tdb`, Julian years); recorded times keep their scale; Gaia epochs are J2016.0 TCB.
- Observer = geocentre via astropy `builtin` ephemeris; IERS downloads disabled (`skyshift/_astropy_config.py`).
- Every result carries an origin: observed / simulated / simulation_truth / derived_measurement / model_prediction / catalog. Truth never enters measurement tables.
- Measure only native original arrays (image/variance/mask). Reprojected frames are display-only. Missing data stays missing; never substitute synthetic data for a failed archive request.
- Never invert weak/negative parallax into a distance; report underconstrained fits as such.
- Live archive integrations (SPHEREx/IRSA, Gaia DR3, WISE, NEOSSat/CADC) are not implemented yet: keep their status honest (`backend/skyshift/providers/`, `docs/providers/`).
- Tests must check behaviour against independent methods or noise-justified tolerances, not restate the implementation.
