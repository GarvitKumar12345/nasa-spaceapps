# SkyShift — project guidance

Local observatory app for finding, explaining, and documenting changes in astronomical images.
Requirements (authoritative, keep detail there): `planning/SkyShift_Claude_Code_Brief.md`.
Architecture, synthetic scenario, module/API contracts: `docs/architecture.md`.
Design background: `planning/SkyShift_Project_Blueprint.md`, `planning/skyshift-design.html` (sketch, synthetic only).

## Run (Windows; Git Bash or PowerShell)
- First time: `cd backend && uv sync` · `cd frontend && npm install` · `npm install` (repo root)
- Dev (both servers): `npm run dev` at repo root → http://127.0.0.1:5173 (API on :8000, proxied at `/api`)
- Backend only: `cd backend && uv run uvicorn skyshift.api.app:app --host 127.0.0.1 --port 8000`
- SPHEREx DR1 cutouts (real data; local cache `backend/cache/spherex/`, not committed): `cd backend && uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --from-manifest`. The API never downloads; the manifest `fixtures/spherex/<field>/manifest.json` is the committed retrieval record (details: `docs/providers/spherex.md`).
- Gaia DR3 for a field (committed: `fixtures/gaia_dr3/<field>/`): `cd backend && uv run python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-barnard [--dry-run]` (needs the SPHEREx cache for the footprints). Alignment reports are disk-cached in `backend/cache/alignment/` (key = inputs + code hash).

## Test
- Python: `cd backend && uv run pytest` (markers: math, coords, measurement, registration, catalog, pipeline, contracts, api, archive, slow; `-m live` for IRSA/ESA tests, skipped by default; SPHEREx dataset tests skip if the cutout cache is absent). Live tests record count changes with `record_property("note", …)` and fail only on schema/provenance/pinned-product differences.
- TypeScript: `cd frontend && npm run test` (vitest) · `npm run typecheck` · `npm run build`
- Browser: `cd frontend && npm run e2e` (Playwright, system Chrome; starts servers if needed)
- Full validation report for Methods: `npm run validate` (repo root) → `validation/report.json`; add live IRSA checks with `cd backend && uv run python scripts/validate.py --live`
- Estimator review (needs the SPHEREx cache, ~150 s): `cd backend && uv run python scripts/estimator_review.py` → `validation/estimator_review.json` (independent-renderer stress matrix, real-star dependences, neighbour simulation, detectability); findings in `docs/reviews/`
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
- SPHEREx is read-only: explicit collection (`spherex_dr1`), extensions read by EXTNAME, flag bits from each file's FLAGS header, units MJy/sr (surface brightness incl. zodi), times UTC (`MJD-AVG`). Blink/compare only within a compatibility group (same detector AND |Δλ| ≤ 0.25 × bandwidth at the field centre, WCS-WAVE). Measurement, registration, fits and differences stay unavailable for observed data (`Dataset.capabilities`, API 409 `not_available`) until validated.
- Gaia DR3: `gaiadr3.gaia_source` named explicitly; source_id is always a decimal string (never float/JSON number). Propagate from J2016.0 TCB with the Gaia-documented model (RV where catalogued; Barnard's Star needs it); apply observer parallax once and no aberration (the SPHEREx WCS is catalogue-frame: ES §3.2.8 + convention test). Predictions are `model_prediction`, reference ePSF positions `derived_measurement`; an unmatched prediction is never a discovery. Alignment residuals are reported before correction; no correction is applied anywhere. Frame-offset tests use random ⊕ shared per-frame errors (PSF mismatch, centroid convention); shared terms never shrink with N, and a term that cannot be estimated is named, never set to 0. The WCS convention is `partially_resolved`: full aberration is rejected, while the calibrator parallax and centroid definition are undocumented and only bounded. Report east/north RMS separately from the 2-D RMS. Never adjust centroids to agree with Gaia; document estimator effects instead (`docs/reviews/`).
- SPHEREx photometry, target astrometry/motion fits and difference imaging stay unavailable (`Dataset.capabilities`, API 409).
- WISE and NEOSSat/CADC live integrations are not implemented: keep their status honest (`backend/skyshift/providers/`, `docs/providers/`).
- Tests must check behaviour against independent methods or noise-justified tolerances, not restate the implementation.
