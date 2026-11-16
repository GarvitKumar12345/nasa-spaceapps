# Review: real-source position estimator, uncertainty budget, API/UI and tests (2026-11-15)

**Scope.** This review covers the SPHEREx DR1 Barnard's Star field: 17 cutouts and the Gaia DR3 field query recorded 2026-11-14T22:46:35Z (3180 rows). It examines:
- the ePSF position estimator;
- the Gaia-reference residuals and their uncertainty budget;
- the WCS convention claim;
- the API/UI handling of unavailable, cached and failed results;
- the test suite.

No centroid was adjusted to agree with Gaia. No correction is applied to any product. Target motion fitting, photometry and difference imaging stay unavailable.

**Evidence files:**
- `validation/estimator_review.json` (`cd backend && uv run python scripts/estimator_review.py`, ~150 s);
- `validation/report.json` (`cd backend && uv run python scripts/validate.py --live`);
- `validation/next_target_coverage.json`.

## Summary of findings

| # | Finding | Evidence | Action |
|---|---|---|---|
| 1 | The estimator follows the IRSA ePSF tutorial and photutils: parent = cutout + 1 − CRPIX1A, zone = containing rectangle (= nearest centre), `[iy, ix]` order, 5× oversampling, value = 25 × stored, reference point = array centre (16, 16) | photutils `ImagePSF` max diff 6e-16 of the peak (184 zones); zone choice 0 mismatches in 6800 positions; detector coordinates identical | none needed |
| 2 | The stored ePSF already contains the pixel response; no extra integration step | Integrating once more raises χ² on every detector (sum ratio 1.45–2.43; median D1 13.0 → 28.8, D6 1.7 → 3.0). The tutorial's prose says "integrate" but its code samples at pixel centres | none needed (documented) |
| 3 | The per-frame injection test used the same model to render and fit, so it could not test PSF mismatch | — | added independent renderers and a controlled stress matrix (below); docstring now says "internal consistency" |
| 4 | The 2 px / 10 % isolation rule admits neighbours that bias a 7×7 fit | Equal-flux neighbour at 2.05 px: +0.27 px; at 3 px: −0.025 px. 9 % neighbour at 1 px: +0.050 px. Real references, simulated from their Gaia neighbours: median 0.008 px, 90th percentile 0.024 px, max 0.081 px; residuals regress on the simulated shifts with slope 0.49 ± 0.18 | documented, not corrected |
| 5 | D1–D4 fits are poor (χ²_red ≈ 6–54) | See "Real-star residuals" | cause partly identified; rest documented as unresolved |
| 6 | Shared per-frame errors were treated as shrinking with N | PSF mismatch 0.03–0.12″ and centroid convention 0.11–0.19″ per axis | budget split into random / unexplained / shared terms; shared terms enter each offset without 1/√N |
| 7 | **None of the five "offset justified" classifications survives** | p = 0.16–0.62 with shared terms (random-only p = 7e-19 … 0.0021) | reclassified: no translation justified |
| 8 | The convention status "resolved" overstated the evidence | The test rejects full aberration only | status `partially_resolved`, with six documented / tested / bounded aspects |
| 9 | Gaia capabilities claimed "available" whenever fixture files existed: a corrupted response or an empty SPHEREx cache gave a 503/404 behind an "available" capability | — | capability requires a verified response (same loader as the API) and ≥ 1 cached cutout |
| 10 | Shared PSF term silently 0 when a file has no adjacent-zone ePSF | — | now `null` + `missing_terms`; the decision text states the significance is then optimistic |
| 11 | Overlay convention depended on request order ("approximate … no frame with enough references" before the report existed) | — | overlay reads the disk-cached report (key-checked) and otherwise says "not computed yet"; the UI prefers the report's convention |
| 12 | The UI could show a previous dataset's request error on the new dataset; 409 was shown as a generic error | — | errors are guarded by dataset; 409 `not_available` → "unavailable" state |
| 13 | A translation-consistency test had become vacuous (it only checked justified frames) | — | now checks every evaluated frame |
| 14 | Live Gaia checks: the ESA archive remained unreachable | Probes 2026-11-15 20:43–20:46Z: HTTP 000 after 20 s × 3 attempts each (IRSA 200 in 0.4 s); live tests in the validation run | status stays `unavailable` (never "tested"), now with the last successful retrieval in the capability detail |

## Estimator audit (step 1)
The evaluation uses `RectBivariateSpline(s=0)` on 25 × the stored array. This is the photutils `ImagePSF` model, and the two agree to 6e-16.

- **Gradients:** checked against the spline derivatives. Axis order is `[iy, ix]`; the first spline axis is rows.
- **Normalisation:** stored sum = 1. Native-spacing sums × 25 = 1 within the per-file check.
- **Detector coordinates:** the tutorial formula `xpix_orig = 1 + xpix_cutout − crpix1a` is reproduced exactly.
- **Zone choice:** the rectangle containing the detector position. The table tiles the detector, so this equals the tutorial's nearest-centre rule.
- **Support:** the 33×33 ePSF covers ±3.2 px. Pixels in the 7×7 window beyond that are modelled by the plane background only; this is documented.

## Independent injection tests (step 2)
Renderer (`skyshift/science/estimator_stress.py`):
- an analytic elliptical Moffat, optionally with a displaced satellite, integrated over every native pixel by sub-sampling, with no ePSF code involved;
- real SPHEREx zones rendered by photutils.

The fitting model is an Anderson & King ePSF built from the nominal PSF. Each case is fitted over an 8×8 sub-pixel phase grid; noisy cases use 512 fits. All entries are in px.

| Variation | Mean bias (x, y) | RMS over phase (x, y) | Interpretation |
|---|---|---|---|
| matched, noiseless | 0, 0 | 1e-4 | interpolation error only |
| matched, S/N 10 / 50 / 200 | ≤ 0.005 | 0.13 / 0.025 / 0.0063 | scatter equals the independent Cramér–Rao bound (test); reported σ within +10 % |
| PSF 10 % broader / narrower | 0 | 0.014 / 0.015 | odd in phase (exact symmetry test); mean-free pixel-phase error |
| elongated q = 0.85 | 0 | 0.008, 0.019 | — |
| wings β = 2.5 | 0 | 0.002 | — |
| 5 % satellite at 0.5 px / 10 % at 0.3 px | +0.022 / +0.029 | — | ≈ light-centroid shift (0.025 / 0.030); first-order theory exact for small d (test) |
| plane gradient 2 % of peak per px | 0 | 1e-4 | absorbed exactly (test) |
| 1 % curvature at 3 px | 1e-4 | 0.002 | — |
| 1 or 3 masked pixels; 3 masked + 10 % broader PSF | 0 | 1e-4 / 0.014 | masks add no bias; σ grows (test) |
| neighbour 10 % / 5 % at 2 px | +0.016 / +0.008 | — | linear in flux (test) |
| neighbour 100 % at 2.05 / 2.5 / 3 / 4 px | +0.27 / +0.034 / −0.025 / −0.016 | — | admitted by the isolation rule |
| neighbour 9 % at 1.0 / 1.5 px | +0.050 / +0.035 | — | admitted by the isolation rule |
| 10 % broader PSF, S/N 50 | 0.001 | 0.033 | robust pulls 1.17 / 1.09 |

- **Real-zone zone swap:** one zone rendered with photutils and fitted with an adjacent zone's model. The mean shift RMS is 0.004–0.025 px and the phase-dependent RMS is 0.013–0.038 px, depending on detector. This supports the PSF-mismatch shared term.
- **Real ePSF round trip:** a real ePSF rendered by photutils is recovered to < 1e-6 px.
- **Tests:** `tests/test_estimator_stress.py`, 9 tests. Each expectation comes from an independent derivation, not from re-running the fitter's model.

## Real-star residuals and fit quality (step 3)
The 139 references from the 15 usable frames enter. Residual = ePSF position − Gaia prediction, before any correction. All values are arcsec.

| Detector | n | RMS east | RMS north | 2-D RMS | pull RMS E / N | median χ²_red |
|---|---|---|---|---|---|---|
| D1 | 45 | 0.125 | 0.143 | 0.190 | 1.06 / 1.09 | 13.0 |
| D2 | 15 | 0.159 | 0.430 | 0.458 | 1.35 / 2.57 | 25.1 |
| D3 | 23 | 0.329 | 0.169 | 0.370 | 2.26 / 1.21 | 26.9 |
| D4 | 26 | 0.162 | 0.187 | 0.248 | 1.13 / 1.24 | 8.3 |
| D5 | 15 | 0.264 | 0.310 | 0.407 | 1.55 / 1.09 | 1.4 |
| D6 | 15 | 0.236 | 0.183 | 0.298 | 2.12 / 1.41 | 1.6 |
| **pooled** | 139 | **0.210** | **0.228** | **0.310** | — | — |

The 2-D RMS is √(mean(ΔE² + ΔN²)). It is not a per-axis value. Pulls include each frame's offset, so pulls above 1 on D2/D3/D6 partly reflect frame offsets.

**Dependence on brightness, phase and position:**
- **Brightness:** S/N 10–30 gives RMS E/N/2-D 0.220/0.255/0.337 (n 96); S/N 30–100 gives 0.186/0.149/0.238 (n 43).
- **Sub-pixel phase** (frame-mean-subtracted residuals in detector pixels, sinusoidal pixel-phase fit):
  - D1–D4 sine amplitudes: x 0.006 ± 0.003 px, y −0.006 ± 0.002 px;
  - D5–D6: x −0.014 ± 0.007 px.
  - At most 2.7σ: no significant pixel-phase error above ~0.01 px.
- **Position within a zone:** no significant trend (Spearman 0.12 for the D1–D4 misfit vs distance from the zone centre).

**Detector-fixed offset:**
- Frame means mapped to detector pixels: x +0.0153 ± 0.0035 px (positive in 14 of 15 frames), y +0.0057 ± 0.0045 px.
- The frames' sky orientations differ. The detector-linked offset is consistent with an estimator or centroid-convention effect, but archive-WCS calibration can also contribute; these results do not uniquely identify its origin.
- Its size equals the Gaia-free difference between the ePSF reference point and centroid-type estimators (windowed +0.005, 5×5 barycentre +0.037 px in x).
- It is reported and carried in the budget, not removed.

### D1–D4 misfit
| Test | Result | Reading |
|---|---|---|
| Stacked residual (flux-normalised, central 5×5) | ≤ 1.1 % of the flux per pixel on every detector; central-pixel ratio 1.00 ± 0.02 | not an average shape error |
| Extra pixel integration | χ² worse everywhere | ePSF already pixel-integrated |
| χ²_red vs brightness (formal S/N, not the √χ²-deflated S/N) | D1–D4: 5.8, 10.3, 22.9, 53.8 for S/N 10–30, 30–100, 100–300, > 300 | grows with brightness |
| χ²_red − 1 vs Gaia RP flux, per-frame intercepts | ∝ F^0.49±0.06 (D1–D4), F^0.72±0.24 (D5–D6) | shallower than a pure fractional PSF error (F²) |
| High-pass pixels (Gaia G < 18.5 masked) between epochs of one compatibility group | ρ = 0.22–0.45 on D1–D4, 0.03–0.11 on D5–D6 (white noise: 0) | structure fixed on the sky that VARIANCE does not describe |
| High-pass robust z (5×5 median) | 1.32–1.82 on D1–D4, 1.02–1.03 on D5–D6 (white noise 0.96) | ditto |
| Misfit vs colour / zone position / central ratio vs S/N | Spearman −0.11 / 0.12 / −0.21 (n = 109) | no strong dependence |

**Reading:**
- A brightness-independent part of the D1–D4 misfit comes from faint sources and background structure in the fit window. This is consistent with the lower noise of the short-wavelength detectors.
- The brightness-dependent part is a star-to-star misfit whose cause is **unresolved**. Candidates not tested here: PSF variation within a zone or with the local wavelength, and nonlinearity / brighter-fatter below the flag thresholds.
- The ePSF header records `SMOOTH='quartic'`.
- Uncertainties are inflated by √χ²_red. Because confusion noise is correlated on PSF scales, this inflation is approximate.

## Uncertainty budget and reassessment (step 4)
Per axis, as stored in `AlignmentReport.uncertainty_budget` and shown in the UI:

| Term | Kind | Typical (″) | Range (″) |
|---|---|---|---|
| ePSF centroid (fit σ × √χ²_red) | random per star | 0.162 | 0.046–0.538 |
| Gaia DR3 prediction (6×6 covariance + parallax) | random per star | 0.0002 | 0.0001–0.0007 |
| Paule–Mandel extra scatter | unexplained per star | 0.025 | 0–0.276 |
| PSF-model mismatch (½ RMS of adjacent-zone refits) | shared per frame | 0.057 | 0.030–0.123 |
| Centroid convention (from the frame's ePSFs, Gaia-free) | shared per frame | 0.136 | 0.105–0.189 |
| Gaia frame systematics | shared, all frames | 2e-5 | — |
| Calibrator parallax convention | shared, all frames | bound | ≤ 0.0026 |

The translation test uses σ_total = σ_random ⊕ σ_shared; the shared part does not fall with N (tested). Reassessment of the five frames previously "justified":

| Frame | random-only p | total p | decision |
|---|---|---|---|
| D2 2025-08-25 | 7e-19 | 0.16 | not justified |
| D2 2026-03-15 | 4.6e-4 | 0.58 | not justified |
| D4 2026-03-11 | 4.2e-5 | 0.36 | not justified |
| D6 2026-03-22 | 0.0021 | 0.47 | not justified |
| D6 2026-05-04 | 2.9e-5 | 0.62 | not justified |

**Sensitivity:**
- Using the empirical common detector-frame offset (0.071″ per axis) in place of the convention term, every frame stays at p > 0.0027; the smallest is D2 2025-08-25 at p = 0.011.
- With the PSF term alone, D2 2025-08-25 remains significant (p = 5e-5). Its north offset rests on RMS N 0.54″ over 9 stars.
- So that one frame's classification depends on the undocumented centroid convention.
- The held-out test cannot separate a shared estimator bias from a WCS offset.

## WCS convention (step 5)
- **Test result:** with total uncertainties, catalogue frame χ² = 12.5 against 39 884 for full aberration (30 dof). With random errors only, the catalogue-frame χ² is 197.
- **Status:** `partially_resolved`. Evidence against full aberration is not proof of every convention.
- **Aspects:**
  - Reference catalogue and epoch: documented.
  - Aberration: documented and tested (full aberration only).
  - Calibrator parallax: undocumented, bounded ≤ 2.6 mas.
  - Light deflection: untested, ≤ 4 mas.
  - Centroid definition: undocumented, bounded, and carried in the budget.
  - Time scale: untested, < 0.03 mas.

## API/UI review (step 6)
- **Unavailable capabilities stay unavailable:**
  - API: 409 `not_available` for sources, measurements, associations, catalog, difference and astrometric fits on observed data.
  - UI: shown as "unavailable"; Playwright checks photometry, astrometric_fit, difference_imaging, source_measurement and registration.
  - New: the Gaia capabilities themselves are unavailable, with a reason and a command, when the Gaia response fails its checks or no cutout is cached (finding 9).
- **Cached results keep provenance:**
  - The alignment report carries `cache.key` (a hash of the inputs and code), `computed_utc`, `served_from_cache` and the input identities: Gaia response sha256, Gaia retrieval time and the SPHEREx cutout hash.
  - A cache file with another key is never served. An unreadable cache file is deleted and recomputed (tested).
  - The UI shows the computation time and key.
- **Failures never substitute data:**
  - A Gaia response that fails its sha256 or schema checks gives 503 `provider_unavailable`, with no predictions or frames in the body (tested).
  - The UI keeps the failure state and shows nothing else (vitest, Playwright).
  - A failure arriving after a dataset switch is dropped (vitest).

## Test-quality review
**Reviewed:** test_alignment, test_epsf, test_estimator_stress (new), test_epoch_propagation, test_gaia_dr3, test_spherex, test_api_evidence and the frontend gaia store tests. The synthetic-pipeline tests were not re-reviewed this session.

**Changes:**
- **Replaced a vacuous test:** the translation-consistency test now checks every evaluated frame (χ² formula with total σ, decision rule, weighted mean).
- **Added independent checks:**
  - the Cramér–Rao bound from finite differences of the independent renderer;
  - odd phase symmetry;
  - first-order perturbation theory for asymmetric PSFs and faint neighbours;
  - exact plane absorption;
  - Fisher-information monotonicity under masking;
  - the observer parallax by explicit position-vector geometry, instead of the implementation's parallax factors (agreement < 3e-3 mas).
- **New property tests:**
  - shared error does not shrink with N (10 vs 160 stars);
  - windowed centroid exact on a well-sampled symmetric source;
  - budget kinds and cache provenance;
  - cache-key enforcement;
  - 503/409 without substitution;
  - capability gating;
  - live-status wording with the last successful retrieval.
- **Labels:** the same-model injection test is now explicitly labelled "internal consistency".

## Live Gaia checks (step 7)
- **Bounded probes:** three attempts each, 20 s timeout. `tap/availability` and `tap/tables`: HTTP 000 at 2026-11-15T20:43–20:46Z. IRSA TAP: 200.
- **Live tests:** two `validate.py --live` runs reached the live Gaia tests. Each test made the client's bounded 6 attempts and ended with `ArchiveRequestFailed: URLError [WinError 10060]`.
  - ~21:00Z: an interrupted run, with pytest only recorded.
  - 22:04Z: the final run, below.
- **Reported status:** both Gaia live capabilities stay **unavailable**, not "tested". Their detail states: last successful retrieval 2026-11-14T22:46:35Z (HTTP 200, job 3cf2ac3f-e07d-11f1-87a2-bc97e148b76b-O, 3180 rows).

## Final validation
`cd backend && uv run python scripts/validate.py --live` → `validation/report.json`, generated **2026-11-15T22:15:39Z**.
- **Freshness:** source hash `b0d2d6c02d365f2f…`. This equals the hash of the current tree, so the report is not stale. The hash also covers lockfiles, runner configuration and compressed fixtures.

| Suite | Result |
|---|---|
| pytest (incl. live) | 175 / 177 passed. The 2 failures are the live Gaia tests above (ESA archive unreachable → status `unavailable`). SPHEREx live: 3 / 3 passed (SIA2 row count unchanged, 239 products; range screening; cutout download). |
| vitest | 105 / 105 passed |
| Playwright (system Chrome, fresh servers) | 26 / 26 passed |
| Frontend production build, type check | passed (existing chunk-size warnings only) |

- `validation/estimator_review.json` was regenerated at 2026-11-15T21:59:56Z under the same source hash. Its scientific values are unchanged from the run quoted in this review.

## Detectable inter-epoch displacement and next target
Model (`detectability` in `validation/estimator_review.json`), per axis and epoch:
- **Target centroid:** σ_c = k·√χ²(S/N_f)/S/N_f, with k = 0.57 px (D1–D4) or 0.66 px (D5–D6) from the real references, and χ² from the formal-S/N bins.
- **Approach A (archive WCS used as is):** the frame-to-frame scatter of the frame offsets, 0.116″.
- **Approach B (differential, needs a correction this build does not apply):** frame-tie random part 0.039″ ⊕ PSF mismatch 0.057″.
- **Per-star terms:** extra scatter 0.025″ and neighbour shift 0.037″ (median).
- **Epochs and threshold:** epochs are independent. The threshold is 5.36 σ_Δ (two-dimensional test at the two-sided 5σ tail), with σ_Δ = √2 σ_epoch/√n for n frames averaged per season.

| Target (formal S/N per frame) | A, single pair | A, 10 frames per season | B, single pair |
|---|---|---|---|
| D1–D4, S/N 50 | 1.95″ | 0.62″ | 1.81″ |
| D1–D4, S/N 150 | 1.27″ | 0.40″ | 1.05″ |
| D1–D4, S/N 400 | 1.06″ | 0.34″ | 0.79″ |
| D5–D6, S/N 150 | 0.98″ | 0.31″ | 0.68″ |

- **Single pair:** the illustrative error-budget model estimates a threshold of **≈ 1.0–1.3″** for a bright unsaturated star, and ≈ 2″ at S/N 50. This is not a validated target-detection or completeness result.
- **Season means:** ≈ 0.3–0.6″ if per-frame errors are independent. Any error common to a season would set a floor, and this is not tested.
- **Proper motion:** over the ~0.5 yr DR1 baseline, a single pair needs μ ≳ 2–2.5″/yr; season means need ≳ 0.7–1.2″/yr. The parallax change between seasons must come from the Gaia prediction.

**Recommendation: van Maanen 2 (WD 0046+051).**
- **Motion:** a white dwarf with μ ≈ 2.98″/yr and ϖ ≈ 232 mas (literature values; to be confirmed with the recorded Gaia DR3 query when the ESA archive answers).
- **Brightness:** G ≈ 12.4, with near-IR AB ≈ 12.6 (J) to 13.3 (Ks). These estimates and the listed SPHEREx nonlinearity limits (AB 11.5 / 11.5 / 11.3 / 11.7 / 10.2 / 9.75 for bands 1–6) suggest a candidate worth checking. Broad-band photometry does not establish per-channel saturation or S/N; unsaturated exposures and S/N ≳ 150 on D1–D3 remain unverified until actual cutouts, flags and uncertainties are inspected.
- **Field:** at b ≈ −58°; isolation still requires the neighbour checks below.
- **Coverage:** IRSA SIA2 on 2026-11-15T20:50:49Z (the first attempt returned HTTP 502) found 216 DR1 images, 32–38 per detector, in two seasons: 2025-06-29…07-19 and 2025-12-19…2026-01-06.
- **Expected displacement:** ≈ 1.5″ of proper motion between seasons, with a parallax contribution of up to ≈ 0.46″. Its direction and magnitude require the actual observer geometry and dates; no particular combined displacement or detection significance is established here.
- **Still to check before use:** compatibility groups at the target position, per-frame S/N and flags, and Gaia neighbours within 4.5 px.

## Remaining limitations
- **D1–D4:** the cause of the brightness-dependent misfit is unresolved, and √χ² inflation only approximates its effect on positions.
- **Neighbours and sources missing from Gaia:**
  - Neighbour shifts admitted by the isolation rule are not modelled. Simultaneous fitting or a stricter rule is a future option.
  - IR-bright sources absent from Gaia are invisible to the isolation test.
- **Pipeline conventions:** the pipeline's centroid definition and calibrator parallax handling are undocumented. The centroid term dominates the shared budget and decides the D2 2025-08-25 classification.
- **Correction model:** only a translation is tested. With 5–13 references per 6′ cutout, rotation, scale and distortion are not constrained.
- **Detectability:** the estimate assumes independent epochs and Gaussian errors. A real target adds its own neighbour and confusion terms, which must be measured before any claim.
- **Live Gaia:** checks are unavailable while the ESA archive is unreachable. The recorded response (2026-11-14) is the last verified state.
