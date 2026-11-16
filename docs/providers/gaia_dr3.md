# Gaia DR3 — reference catalogue for SPHEREx predictions and alignment diagnostics

**Status: implemented.** One recorded field query (`spherex-dr1-barnard`), epoch propagation to every SPHEREx exposure, an epoch-dependent overlay, and alignment diagnostics of the archive WCS. Live checks: `uv run pytest tests/test_gaia_dr3.py -m live` (their outcome is in `validation/report.json` and on the Methods page).

## Release, table and access
- **Release:** Gaia DR3. The table `gaiadr3.gaia_source` is named explicitly in every ADQL query. The archive's `RELEASE` parameter (`Gaia DR3`) and `COOSYS` (ICRS, epoch J2016.0) are checked in every response.
- **Access route:** ESA Gaia archive TAP sync (`https://gea.esac.esa.int/tap-server/tap/sync`), queried with explicit ADQL and `MAXREC=50000`, the anonymous row cap.
  - Truncation is signalled by a *trailing* `QUERY_STATUS=OVERFLOW` INFO; the leading INFO still says OK. All status INFOs are therefore checked, and a recorded `MAXREC=5` probe proves the check works.
  - CSV output would truncate silently, so it is used only for the 1-row `COUNT(*)`.
- **Where queries run:** only `python -m skyshift.providers.gaia_dr3.fetch` makes requests. The API reads the committed response in `fixtures/gaia_dr3/<field>/` and never queries Gaia.
- **Source IDs:** `source_id` is a 64-bit integer (≤ 6.9e18 > 2^53). It is converted once from the VOTable `long` column to a decimal string and stays a string in contracts, JSON and the frontend.
  - A float or JSON number would already have lost digits (Barnard's Star 4472832130942575872 → 4472832130942575616), so the parser, the API (422) and the client refuse them.

## The query (recorded 2026-11-14 22:46:35 UTC, job `3cf2ac3f-e07d-11f1-87a2-bc97e148b76b-O`)
```sql
SELECT source_id, ref_epoch, ra, ra_error, dec, dec_error, parallax, parallax_error, pmra, pmra_error, pmdec, pmdec_error,
       ra_dec_corr, ra_parallax_corr, ra_pmra_corr, ra_pmdec_corr, dec_parallax_corr, dec_pmra_corr, dec_pmdec_corr,
       parallax_pmra_corr, parallax_pmdec_corr, pmra_pmdec_corr, astrometric_params_solved, nu_eff_used_in_astrometry, pseudocolour,
       visibility_periods_used, ruwe, astrometric_excess_noise, astrometric_excess_noise_sig, ipd_frac_multi_peak, ipd_gof_harmonic_amplitude,
       duplicated_source, non_single_star, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, bp_rp, phot_variable_flag,
       radial_velocity, radial_velocity_error, grvs_mag, rv_template_teff
FROM gaiadr3.gaia_source
WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', 269.4462800, 4.7680300, 0.1133729))
ORDER BY source_id
```
**Search region:** radius = footprint 262.4″ + proper-motion margin 10.5″/yr × 10.338 yr = 108.6″ + neighbour margin 6 px × 6.20″/px = 37.2″ → 0.1133729° (408.1″). The terms are derived as follows:
- **Footprint:** the largest distance from the field centre to any corner (pixel edges) of the 17 cutouts, through each cutout's archive WCS.
- **Proper-motion margin:** 10.5″/yr bounds every stellar proper motion. The fastest known star, Barnard's Star at 10.39″/yr, is also the fastest in this response. The interval runs from J2016.0 (TCB) to the latest exposure mid-time.
- **Neighbour margin:** stars just outside a cutout still put flux into its edge pixels (ePSF support ±3.2 px) and must be known for the isolation test.
- **What it is not:** the 0.0003° SIA2 radius used to find SPHEREx images containing the field centre is unrelated and never used here.

**Result:** 3180 rows, equal to an independent `COUNT(*)` of the same circle.
- **Solution types:** 339 two-parameter (no parallax/pm), 1319 five-parameter and 1522 six-parameter solutions.
- **Radial velocities:** 56 sources have one.
- **Checks passed:** columns, units (astropy comparison), datatypes, RELEASE, table, COOSYS, QUERY_STATUS, ref_epoch = 2016.0 for all rows, unique ascending decimal-string IDs, solution codes with NULL patterns, and the row count.
- **Recorded files:**
  - `manifest.json`: ADQL, form fields, HTTP records, footprints, geometry, checks, pinned rows, acknowledgement.
  - `gaia_dr3_response.vot.gz`.
  - `gaia_dr3_epoch_prop.vot.gz`: the archive's own `ESDC_EPOCH_PROP` / `ESDC_EPOCH_PROP_ERROR` for 8 pinned sources at the 12 distinct exposure epochs, recorded only as an independent check.
  - `gaia_dr3_overflow_probe.vot.gz`.

```bash
cd backend
uv run python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-barnard --dry-run   # ADQL + radius derivation (needs the SPHEREx cache)
uv run python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-barnard             # live query; rewrites the fixtures
uv run pytest tests/test_gaia_dr3.py tests/test_epoch_propagation.py                        # offline checks on the recorded data
uv run pytest tests/test_gaia_dr3.py -m live                                                # live: same ADQL + archive propagation
```
Equivalent with astroquery: `from astroquery.gaia import Gaia; Gaia.launch_job(adql)`. `Gaia.ROW_LIMIT` does not apply to `launch_job`, and anonymous sync queries return up to 50 000 rows, despite older documentation saying 2000.

## Epoch propagation (`skyshift/science/epoch_propagation.py`)
- **Model:** uniform rectilinear motion relative to the barycentre, from the Gaia DR3 documentation Sect. 4.1.7 (ESA 1997 Vol. 1 §1.5.5):
  - f = [1 + 2μ_r t + (μ² + μ_r²) t²]^-½
  - u = [r₀(1 + μ_r t) + μ₀ t] f
  - μ_r = v_r ϖ / A
- **Proper motion:** `pmra` already includes cos δ.
- **Time scales:** ref_epoch J2016.0 is a TCB epoch and is converted to TDB with astropy (it is 19.1 s earlier than J2016.0 TDB). Exposure mid-times are MJD-AVG (UTC) → TDB.
- **Light time:** neglected, as in the Gaia convention (≤ ~10 µas over 10 yr for normal stars).
- **Covariance:** the full 6×6 covariance is propagated as J C₀ Jᵀ, with C₀ augmented for μ_r (Michalik et al. 2014). J is computed by central differences of the exact model.
- **Missing quantities are explicit:**
  - No radial velocity: v_r = 0, with a 100 km/s dispersion in the covariance and a reported perspective-acceleration bound for |v_r| ≤ 500 km/s (largest in the field: 8.5 µas).
  - Barnard's Star uses its Gaia RV (−110.47 km/s). Its DR3 solution itself includes perspective acceleration (DR3 doc. §4.3.3, Table 4.3), so omitting the RV would cost about 52 mas over 9 yr.
  - Two-parameter sources are not propagated: they keep their J2016.0 position, are flagged and are never references.
  - Negative or insignificant parallaxes are used only as statistical values; no distance is ever formed.
- **Observer parallax:** a separate step, −ϖ(b·p, b·q) for the geocentre (ERFA epv00), applied exactly once. Aberration and light deflection are not applied (see the convention below).
- **Checks** (`tests/test_epoch_propagation.py`):
  - Positions agree with the archive's ESDC_EPOCH_PROP at every exposure epoch to < 0.001 mas, using the archive's own time argument.
  - Sigmas and correlations agree with ESDC_EPOCH_PROP_ERROR within 10⁻³.
  - astropy/ERFA `apply_space_motion` (which includes light time) agrees to < 1e-4 mas, and to 0.011 mas for Barnard's Star.
  - A 20 000-draw Monte Carlo reproduces the covariance.
  - The closed-form gnomonic motion and the cos δ convention at Dec 80° hold, and the TCB offset matches.
  - Of the research claims, two refuted astropy edge cases (zero or negative parallax gives NaN or frozen positions) explain why the ERFA comparison uses only significant positive parallaxes.

## SPHEREx WCS convention (partially resolved)
- **Documented:** the L2 WCS is fitted with scamp so that detected stars match the Reference Catalog.
  - Gaia DR3 is the astrometric reference, and "Proper motions provided by Gaia are used to propagate stellar positions to the current observation epoch" (ES v2.1 §3.2.8, Table 17).
  - No aberration, parallax, light-deflection or apparent-place step is described anywhere in the Supplement.
  - So the WCS maps pixels to catalogue-frame directions at the exposure epoch, and the common annual + orbital aberration (up to ~26″) is absorbed by the fitted pointing.
- **Empirical test:** the per-frame mean residuals were compared with the 4.7–12.8″ displacement that the full-aberration (apparent-place) hypothesis predicts (Earth barycentric velocity + SPHEREx `VX_SC…`).
  - Each frame offset's uncertainty is random ⊕ shared per-frame terms (see the uncertainty budget below).
  - Catalogue frame: χ² = 12.5 for 30 dof, frame offsets ≤ 0.30″. Apparent frame: χ² = 39 884.
  - With random errors only, the catalogue-frame χ² is 197. The excess over dof came from treating shared estimator errors as if they averaged down.
  - SkyShift therefore applies no aberration. Applying it would shift every prediction by 5–13″, i.e. 1–2 pixels.
- **What this establishes, and what it does not.** The data reject *full* aberration. They do not prove every convention of the pipeline's astrometric calibration: smaller differences below the frame-offset scatter (~0.1–0.3″) are not tested.

  | Aspect | Status | Bound (″) | Evidence |
  |---|---|---|---|
  | Reference catalogue and epoch (Gaia DR3, proper motion to the observation epoch) | documented | 2e-5 | ES §3.2.8, Table 17; start/mid epoch and perspective handling not stated |
  | Stellar aberration (apparent vs catalogue place) | documented and tested | 0.033 | full aberration rejected (χ² above); partial conventions not tested |
  | Observer parallax of the pipeline's calibrators | undocumented, bounded | 0.0026 | 99th-percentile \|ϖ\| of G < 17 stars in the field |
  | Gravitational light deflection | untested, bounded | 0.004 | ~4 mas, nearly uniform over a 6′ cutout |
  | Centroid definition used to fit the WCS (SExtractor settings) | undocumented, bounded | 0.25 | differs from the ePSF reference point by 0.005–0.04 px (shared term of each frame) |
  | Time scale and time of the WCS solution (UTC mid-exposure assumed) | untested, bounded | 3e-5 | 57 s or 69 s moves the fastest star by < 0.03 mas |

- The overlay reports status `partially_resolved` once the alignment report exists. Before that, it reports `approximate` with "convention test not computed yet"; it does not claim the test failed.

## Positional error budget of a prediction placed on a SPHEREx frame
| Term | Treatment | Bound (″) | Typical (″) |
|---|---|---|---|
| Archive WCS accuracy (ES v2.1 §4.2.2: RMS < 0.3″) | dominant uncertainty | — | 0.3 |
| Differential stellar aberration across the cutout | absorbed by the WCS | 0.033 | — |
| Gravitational light deflection by the Sun | absorbed by the WCS | 0.004 | — |
| Pipeline calibrator parallaxes (undocumented) | absorbed by the WCS | 0.0026 | — |
| Gaia astrometry propagated to 2025–26 (6×6 covariance) | included | — | 0.0005 |
| Light-time effects | neglected | 0.0001 | — |
| Gaia parallax zero-point (~−0.02 mas) | neglected | 0.00004 | — |
| Geocentre instead of SPHEREx (≤ 7100 km) | neglected | 0.00003 | — |
| Exposure duration (mid-time used) | neglected | 0.00002 | — |
| Unknown radial velocities (perspective) | neglected | 0.000009 | — |
| Inverse SIP solution | included | 0.00001 | — |

## Overlay
- **Endpoint:** `GET /api/datasets/{id}/gaia/overlay?frame_id=…` returns `GaiaFrameOverlay`: every Gaia source predicted inside the cutout at that exposure (native and display pixels), its reference role and its flags.
  - Flags: `NO_PROPER_MOTION`, `RV_USED` / `RV_ASSUMED_ZERO`, `PARALLAX_NOT_SIGNIFICANT`, `HIGH_PROPER_MOTION`, `RUWE_HIGH`, `DUPLICATED_SOURCE`, `SATURATED_IN_FRAME`.
- **Endpoint:** `GET …/gaia/sources/{source_id}?frame_id=…` returns `GaiaSourceDetail`, which keeps three things apart:
  - catalogue values (`catalog`);
  - the six propagated parameters with sigmas, the observer-parallax offset, the RV used or assumed and the perspective bound (`model_prediction`);
  - the ePSF image measurement, if the source was a reference candidate (`derived_measurement`), plus prediction limitations.
- **Display:** markers are hollow squares (predictions), teal crosses (ePSF positions, optional) and residual vectors ×100 (optional). A prediction without a counterpart is never a discovery.

## Alignment diagnostics (`skyshift/science/alignment.py`, `GET /api/datasets/{id}/alignment`)
**Reference selection** (each rejection recorded with its reason):
- **Gaia quality:** 5/6-parameter solution, RUWE ≤ 1.4, not duplicated, `ipd_frac_multi_peak` ≤ 2, `non_single_star` = 0, G ≤ 18.5.
- **Isolation:** no Gaia neighbour within 2 px brighter than 10 % of the reference in G or RP. This is the SPHEREx calibrator rule, with Gaia fluxes as the proxy.
- **Saturation:** no OVERFLOW/SUR_ERROR/NONLINEAR/BLOOM in the 7×7 window, and ≥ 8 px from every saturated region (connected OVERFLOW pixels, assigned to the brightest Gaia source there).
- **Pixels:** no excluded flag in the 3×3 core (all documented flags except the informational SOURCE and FULLSAMPLE).
- **Fit:** per-zone ePSF fit with a plane background, converged within 2 px, S/N ≥ 10, σ ≤ 0.25 px.

**Estimator:** the frame's own effective PSF.
- 5× oversampled; Anderson & King flux fractions, i.e. 25 × the stored array, which sums to 1 over the oversampled grid. The zone is chosen in detector pixels: cutout + 1 − CRPIX1A.
- Fitted by Levenberg–Marquardt with VARIANCE weights. σ is scaled by √χ²_red when χ²_red > 1.
  - On D1–D4 references fit with χ²_red ≈ 6 (formal S/N 10–30) to ≈ 54 (S/N > 300). On D5–D6, χ²_red ≈ 1.3–2.7.
  - The cause is examined in the [estimator review](../reviews/2026-11-15-estimator-api-tests-review.md): part is structure fixed on the sky, part a star-to-star misfit of unresolved cause.
- **Audit against the IRSA tutorial and photutils:** parent/cutout coordinates, zone choice, axis order, oversampling, normalisation and reference point agree.
  - photutils `ImagePSF` evaluation agrees to 6e-16 of the peak over 184 zones; the zone choice agrees at 6800 positions; detector coordinates are identical.
  - The stored ePSF already contains the pixel response: integrating it once more raises χ² on every detector (sum ratio 1.45–2.43).
- **Validation in every frame:** 40 ePSF stars at S/N ≈ 40 are injected into the frame's real pixels and recovered with the same estimator. Requirements: |bias| ≤ 0.03 px and robust pull width ≤ 1.5.
  - 16 of 17 frames pass: max |bias| 0.027 px, pull widths 0.48–1.43. The exception is the PERSIST-dominated D3 frame with no references.
  - This checks internal consistency in real noise, masks and backgrounds, because the same ePSF renders and fits. Accuracy under PSF mismatch comes from the independent-renderer tests (`tests/test_estimator_stress.py`, estimator review).
- **Exclusion radius:** chosen from injections around the saturated star (pooled bias at 8–12 px: (−0.0002 ± 0.003, +0.0005 ± 0.003) px). This test is repeated in every frame.

**Results (before any correction; residual = ePSF position − Gaia prediction):**

RMS columns are given per axis (east, north) and as the two-dimensional RMS √(mean(ΔE² + ΔN²)), which is not a per-axis value. "Shared σ" is the per-axis error common to all references of the frame. The p-values are for a constant offset, first with random errors only, then with the total uncertainty.

| Mid-exposure (UTC) | Det | Status | Used / candidates | Mean ΔE, ΔN (″) ± SE | RMS E / N / 2-D (″) | Extra scatter (″) | Shared σ (″) | p random-only → total | Translation |
|---|---|---|---|---|---|---|---|---|---|
| 2025-08-30 22:45 | D1 | ok | 13 / 195 | +0.057 ± 0.020, −0.028 ± 0.037 | 0.091 / 0.130 / 0.159 | 0.000 | 0.143 | 0.071 → 0.88 | not justified |
| 2025-08-30 22:47 | D1 | ok | 10 / 196 | +0.073 ± 0.057, −0.077 ± 0.031 | 0.186 / 0.121 / 0.221 | 0.053 | 0.143 | 0.0081 → 0.72 | not justified |
| 2025-09-05 02:35 | D1 | ok | 12 / 192 | +0.039 ± 0.028, −0.059 ± 0.048 | 0.100 / 0.171 / 0.198 | 0.000 | 0.157 | 1.6e-4 → 0.68 | not justified |
| 2026-03-11 13:34 | D1 | ok | 10 / 193 | −0.051 ± 0.035, +0.065 ± 0.042 | 0.116 / 0.142 / 0.183 | 0.000 | 0.133 | 0.53 → 0.97 | not justified |
| 2025-08-25 17:13 | D2 | ok | 9 / 193 | +0.142 ± 0.024, −0.407 ± 0.125 | 0.158 / 0.539 / 0.562 | 0.000 | 0.147 | 7e-19 → 0.16 | not justified (previously justified) |
| 2026-03-15 07:18 | D2 | ok | 6 / 195 | −0.038 ± 0.069, +0.148 ± 0.028 | 0.160 / 0.161 / 0.227 | 0.026 | 0.131 | 4.6e-4 → 0.58 | not justified (previously justified) |
| 2025-08-25 00:56 | D3 | ok | 13 / 194 | +0.184 ± 0.113, +0.015 ± 0.051 | 0.434 / 0.178 / 0.469 | 0.276 | 0.181 | 0.25 → 0.76 | not justified |
| 2026-03-22 08:45 | D3 | too few references | 0 / 194 | — | — | — | — | — | not evaluated (PERSIST over ~40 % of the cutout) |
| 2026-05-04 14:35 | D3 | ok | 10 / 190 | +0.014 ± 0.022, +0.043 ± 0.050 | 0.069 / 0.156 / 0.170 | 0.025 | 0.132 | 0.97 → 1.00 | not justified |
| 2025-08-27 05:07 | D4 | ok | 9 / 189 | +0.061 ± 0.035, +0.077 ± 0.057 | 0.116 / 0.177 / 0.212 | 0.059 | 0.124 | 0.57 → 0.93 | not justified |
| 2025-09-30 14:03 | D4 | ok | 12 / 192 | −0.003 ± 0.049, +0.075 ± 0.032 | 0.161 / 0.129 / 0.206 | 0.033 | 0.124 | 0.91 → 0.99 | not justified |
| 2026-03-11 02:12 | D4 | ok | 5 / 192 | −0.171 ± 0.072, +0.278 ± 0.046 | 0.224 / 0.293 / 0.369 | 0.000 | 0.176 | 4.2e-5 → 0.36 | not justified (previously justified) |
| 2025-08-25 17:13 | D5 | ok | 9 / 194 | +0.012 ± 0.114, −0.055 ± 0.132 | 0.323 / 0.378 / 0.498 | 0.100 | 0.188 | 0.11 → 0.78 | not justified |
| 2026-03-15 07:18 | D5 | ok | 6 / 193 | −0.099 ± 0.040, −0.084 ± 0.060 | 0.133 / 0.159 / 0.207 | 0.000 | 0.176 | 0.26 → 0.90 | not justified |
| 2025-08-25 00:56 | D6 | too few references | 4 / 190 | +0.027 ± 0.117, −0.015 ± 0.056 | 0.205 / 0.099 / 0.227 | 0.129 | 0.140 | — | not evaluated (< 5) |
| 2026-03-22 08:45 | D6 | ok | 5 / 190 | −0.235 ± 0.110, +0.083 ± 0.088 | 0.321 / 0.195 / 0.376 | 0.130 | 0.225 | 0.0021 → 0.47 | not justified (previously justified) |
| 2026-05-04 14:35 | D6 | ok | 10 / 190 | −0.075 ± 0.054, −0.113 ± 0.045 | 0.179 / 0.176 / 0.251 | 0.020 | 0.221 | 2.9e-5 → 0.62 | not justified (previously justified) |

- **Pooled** over the 15 usable frames (139 references, per-frame offsets not removed):
  - Mean (+0.016 ± 0.018″ E, −0.015 ± 0.019″ N).
  - RMS east 0.210″, RMS north 0.228″; two-dimensional RMS 0.310″.
  - Robust σ (0.170″, 0.190″).
  - Extra scatter beyond the formal errors 0.109″ (Paule–Mandel estimator about the weighted mean); χ²/dof about the weighted mean 595/276.
- **Uncertainty budget of a frame offset** (per axis; `AlignmentReport.uncertainty_budget`):

  | Term | Kind | Typical (″) | Range (″) | Enters as |
  |---|---|---|---|---|
  | ePSF centroid (fit σ × √χ²_red when > 1) | random, per star | 0.162 | 0.046–0.538 | per star; the frame offset's random part shrinks as 1/√N |
  | Gaia DR3 prediction (6×6 covariance + parallax) | random, per star | 0.0002 | 0.0001–0.0007 | per star |
  | Unexplained star-to-star scatter (Paule–Mandel) | unexplained, per star | 0.025 | 0–0.276 | in quadrature per star |
  | PSF-model mismatch (half the RMS shift when refitted with adjacent-zone ePSFs) | shared within a frame | 0.057 | 0.030–0.123 | added to the offset uncertainty without 1/√N |
  | Centroid convention (ePSF reference point vs windowed / 5×5 barycentre centroids, from the frame's ePSFs only) | shared within a frame | 0.136 | 0.105–0.189 | added without 1/√N |
  | Gaia DR3 frame / magnitude systematics | shared by all frames | 0.00002 | — | added |
  | Calibrator parallax convention (undocumented) | shared by all frames | — | 0–0.0026 | bound only |

- **Translation tests, reassessed.**
  - With random errors only, 6 frames had p < 0.0027. Five of them also lowered the held-out RMS and were reported as "justified" in the previous version: D2 ×2, D4 2026-03-11 and D6 ×2.
  - With the shared per-frame terms included (total 0.12–0.23″ per axis), none remains significant: the five have p = 0.16–0.62. No translation is justified in any frame; none is ever applied.
  - **Sensitivity:**
    - Replacing the convention term by the empirical common detector-frame offset (0.071″ per axis) leaves every frame at p > 0.0027; the smallest is D2 2025-08-25 at p = 0.011.
    - With the PSF-mismatch term alone, D2 2025-08-25 stays significant (p = 5e-5). Its north offset rests on a large star-to-star scatter (RMS N 0.54″).
    - That frame's classification therefore depends on the undocumented centroid convention.
  - The held-out test cannot separate a shared estimator bias from a WCS offset, because held-out stars share it. Only the shared term in the significance test protects against that.
- **Frame offsets in detector pixels:** mean x +0.0153 ± 0.0035 px, y +0.0057 ± 0.0045 px; frame-to-frame scatter 0.0135 and 0.0176 px; x positive in 14 of 15 frames.
  - The frames' sky orientations differ, so a common detector-x offset points to the estimator, not to the WCS solutions.
  - Its size matches the Gaia-free centroid-convention difference (windowed +0.005 px, 5×5 barycentre +0.037 px in x). It is reported, not removed.
- **Rejections across all frames** (3272 candidates; another 10 347 predictions are fainter than G = 18.5):

  | Reason | Count |
  |---|---|
  | Neighbour within 2 px | 1237 |
  | Fit window outside the cutout | 704 |
  | S/N < 10 | 343 |
  | Saturation flags in the window | 322 |
  | Within 8 px of a saturated region | 277 |
  | Flagged core | 102 |
  | RUWE > 1.4 | 66 |
  | Saturated | 30 |
  | Multi-peak | 17 |
  | Two-parameter solution | 16 |
  | Fit at the search bound | 13 |
  | Too few usable pixels | 2 |
- **Field assessment:** 15 of 17 frames have 5–13 references (median 9). That supports per-frame statistics and a constant-offset check, not rotation/scale/distortion terms. The two frames with too few references are reported and excluded from conclusions. No additional field was needed for this check.

## Limitations
- **Catalogue coverage:** predictions are only as complete as Gaia. Infrared-bright, Gaia-faint sources can contaminate references undetected; the χ² and σ cuts catch only part of this.
- **ePSF:** the zone's ePSF is used without interpolation, and the ePSF centre is the photutils array centre (the builder's recentring is undocumented).
  - Estimator offsets of 0.005–0.04 px relative to centroid-type definitions are carried as a shared term, not removed.
  - The 33×33 ePSF covers ±3.2 px. Fit-window pixels beyond that are modelled by the plane background alone.
- **Neighbours:** the 2 px / 10 % isolation rule admits neighbours that shift a 7×7 fit.
  - An equal-flux neighbour at 2.05 px shifts it by 0.25 px; one at 3 px by 0.024 px; a 9 % neighbour at 1 px by 0.05 px (independent-renderer injections).
  - Simulated from each reference's catalogued Gaia neighbours, the shift is 0.008 px median and 0.024 px at the 90th percentile; it is 0.081 px at most, and 20 of 139 references exceed 0.02 px.
  - Measured residuals regress on these simulated shifts with slope 0.49 ± 0.18. Not corrected.
- **D1–D4 fit quality:** χ²_red rises with brightness (∝ F_RP^0.49±0.06 with per-frame intercepts).
  - A brightness-independent part is structure fixed on the sky that VARIANCE does not describe. High-pass pixels, with Gaia G < 18.5 stars masked, correlate between epochs of a compatibility group at ρ = 0.22–0.45 on D1–D4 and 0.03–0.11 on D5–D6.
  - The stacked residual is flat to ≤ 1 % of the flux per pixel and the central-pixel ratio is 1.00 ± 0.02. The brightness-dependent part is therefore a star-to-star misfit whose cause is unresolved. It shows no significant correlation with colour or position within the zone.
- **Correction model:** the translation test is the only one; no correction is applied to any product, overlay or measurement. SkyShift does not re-register SPHEREx frames.
- **Still unavailable:** photometry, target astrometry and motion fits, and difference imaging for SPHEREx data (dataset capabilities and API 409).
- **Credit:** "This work has made use of data from the European Space Agency (ESA) mission Gaia (https://www.cosmos.esa.int/gaia), processed by the Gaia Data Processing and Analysis Consortium (DPAC, https://www.cosmos.esa.int/web/gaia/dpac/consortium). Funding for the DPAC has been provided by national institutions, in particular the institutions participating in the Gaia Multilateral Agreement."
  - Cite Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1 and Gaia Collaboration, Prusti et al. 2016, A&A 595, A1.
