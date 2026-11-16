# SkyShift demonstration (synthetic training investigation, ~3 minutes)

Sections 1–4 use **simulated** data (badge "Simulated data" / "Simulated pixels"). Section 5 shows real SPHEREx DR1 images (badge "Observed"), read-only, with Gaia DR3 predictions and alignment diagnostics. No WISE or NEOSSat data are involved.

Start: `npm run dev` at the repository root, open http://127.0.0.1:5173. First load builds the investigation (~10 s).

## 1. Notice a change — Observatory, Explore
1. The Observatory opens on *Training field 01* in band G1. Note the origin badges and the timeline: nine available G1 epochs at their real dates (Jan 2025 – May 2027), one **missing** visit and one **failed** visit kept as gaps.
2. Press **Blink A/B** (or key `B`): epoch A (2025-01-08) and epoch B (2027-05-14) alternate on the common sky grid. Background stars stay fixed; one star near the centre jumps.
3. Click that star (or search `S003`). The inspector shows its measured position with 1σ uncertainty (~8.5 mas), flux and S/N, and the derived **position-change** statistic (χ²/dof ≫ 5) — a statistic, not a classification.
4. Press **Play** (`P`) to step through the real frames in time order; nothing is interpolated between epochs.

## 2. Inspect the evidence — Observatory, Analyze
1. Switch to **Analyze**: the same source, band, epoch and view are kept. A and B appear side by side; **Difference B − A** shows the moving source's dark/bright dipole (and the variable star S001), with its compatibility checks and a "display-only" label.
2. **Measurements**: 18 PSF measurements from the native frames (both bands) plus 4 `missing frame` rows. Each has σ, flux, S/N and flags.
3. **Motion fit** → *PM + parallax* → **Run fit**: proper motion ≈ (+637, −1111) mas/yr and parallax ≈ 165 ± 3 mas, χ²/dof ≈ 1, status *constrained*. Distance is shown only because ϖ/σ ≥ 10. The nested-model table shows why the static and proper-motion-only models fail.
4. Untick one measurement: the fit is flagged **stale** until re-run.
5. **Plots & residuals**: measured track (teal), model prediction (violet dashed), residuals within error bars. Toggle **Show simulation truth (validation only)** to compare with the injected values (amber diamonds) — truth is never part of the measurements.
6. **Catalog**: the source matches its simulated-catalog entry at every epoch only after propagating the J2016.0 (TCB) catalog position ~10 yr forward; the close pair is reported as ambiguous.

## 3. Explain the cause — Motion lab
1. In *Motion fit* press **Explain in Motion lab**. The *Nearby source* lesson opens with the fitted proper motion and parallax copied in (labelled as copied from the fit; the lesson's observer is a circular 1 AU orbit, an approximation).
2. Toggle **proper motion** and **parallax** independently: the straight drift and the yearly ellipse combine into the looping track seen in Analyze. Change distance or ecliptic latitude to see the ellipse scale and flatten.
3. Switch to **Orbit and observer** to show the separate Keplerian lesson: equal-time markers bunch near aphelion; the observer's sky view shows apparent retrograde intervals; changing eccentricity leaves the period unchanged.

## 4. Document it — Evidence notebook
1. Back in the Observatory press **Save candidate** (or *Provenance & export → Save investigation*). The record is labelled **synthetic training record**.
2. Open **Evidence notebook**: the record keeps source, frames, dates, measurements with uncertainties, exclusions, the fit and its current/stale status, assumptions, provenance, and the seed and truth separately.
3. **Validate** (backend schema + fit freshness), **Reproduce** (regenerates from the seed and re-derives every value), **Export JSON** and **Export CSV**. Reload the page: the record persists in this browser.

## 5. Real data — SPHEREx DR1 viewer (observed, read-only)
Requires the cutout cache: `cd backend && uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --from-manifest`.
1. In **Data** choose *SPHEREx DR1 · field around Barnard's Star*. The banner and badges say **Observed** and **read-only**.
2. The inspector shows the mid-exposure time (UTC), observation ID, detector, the local wavelength and bandwidth at the field
   centre (WCS-WAVE, visualization-grade), archive flags within 2.5 px (OVERFLOW, SUR_ERROR, BLOOM: the bright source there is
   excluded from SPHEREx photometry by the documented rules), FINAST/L2 DQA, 21 file checks and provenance (collection,
   processing tag, pipeline version, cutout URL, sha256). Toggle **Archive flags** to see flagged pixels.
3. **Wavelength group** *D1 · 0.904 µm*: **Blink A/B** alternates 2025-08-30 and 2026-03-11 (same detector, local wavelengths
   within 0.25 bandwidth). Choose *D1 · 0.883 µm · single*: same detector, different wavelength → blink is refused with the reason.
4. **Analyze**: side-by-side A/B; *Difference B − A* is refused with the reason; tabs list the observations, the compatibility
   table, the flag definitions read from the file, the exact SIA2 query (239 products) and the unavailable analyses with their
   requirements. No target measurement, fit or difference is computed on these pixels.
5. **Gaia DR3 predictions** (Explore): hollow squares are Gaia DR3 sources propagated to this exposure. They are model predictions,
   not detections: violet = used reference, dashed = rejected candidate, amber ✕ = saturated (Barnard's Star). Click a violet square.
   The inspector separates the *catalogue values* (J2016.0 TCB, pmRA* includes cos Dec), the *prediction at this exposure* (σ, observer
   parallax, radial velocity used or assumed) and the *image measurement* (ePSF, measured − predicted ≈ 0.1–0.3″), plus the prediction's
   limitations. Toggle *ePSF positions* and *Residuals ×100* to see the residual pattern.
6. **Analyze → Alignment** (first run ~1 min, then cached; the computation time and cache key are shown at the bottom):
   - The convention test (full aberration rejected; status *partially resolved*, because rejecting full aberration does not prove every convention).
   - The reassessment note: no frame justifies a translation once shared errors are included.
   - 17 frames with used/candidate counts, mean offsets ± SE, RMS east / north / 2-D, extra scatter, the shared σ, and p random-only → total. No translation is ever applied.
   - Click a row for the residual plot, rejection reasons, the shared-error breakdown and the injection-recovery validation. Two frames are honestly "too few references".
   - The uncertainty budget separates random per-star terms from shared per-frame terms.
   - **Analyze → Gaia DR3** shows the exact ADQL, retrieval time, convention evidence, the convention aspects (documented / tested / bounded) and the error budget.

## 6. Honest status — Methods
Show the integration table (SPHEREx and Gaia DR3 implemented, with live statuses and notes from the last `--live` run; WISE and NEOSSat documented, live checks not run) and the validation report generated by `npm run validate`, grouped into mathematical, measurement, registration/alignment, catalog, pipeline, contract, archive, browser and live-data checks, plus the limitations list.
