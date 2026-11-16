# van Maanen 2 — stage 2: recovering the motion from real SPHEREx pixels (2026-11-16)

## Answer
**Yes, within the stated limits.** SkyShift recovered van Maanen 2's seasonal displacement from real SPHEREx DR1 pixels.

**Result by the stage-2 rule (tied D2 + D3):**
- The two primary pairs tied to reference stars give **0.94 ± 0.14 of the Gaia-predicted 1.51–1.54″ displacement**.
- Against zero: **5.8σ** (χ² for 4 dof). Against the prediction: consistent (p = 0.93).
- The tied error budget is **validated**: 15 reference stars measured in both seasons give χ² 24.7 for 30 dof (p = 0.74).
- The detection holds under each of five analysis variants (5.7–6.3σ).

**Limits on the claim:**
- **Plan not blind:** it was written after the first pass, whose results were known. That pass's rules and results are kept unchanged.
- **No single pair passes:** the best are D2 at 4.98σ (p = 6.3 × 10⁻⁷ against the 5.7 × 10⁻⁷ threshold) and D4 at 4.9σ. The claim rests on the combination of two independent exposures.
- **Untied version is weaker:** archive WCS without the reference tie gives 0.94 ± 0.19 at 4.1σ, below the rule.
- **Not a measurement of parallax or proper motion:** two epochs per detector give displacements only, which are compared with the prediction.

**Key systematic finding.** The target's poor fits (χ²_red 27–70) are caused by a catalogued neighbour 2.9 px away that is bright in the infrared and absent from the nominal model.
- Modelling it drops χ² to 0.9–3.5 and moves the target by ≤ 0.008 px.
- The nominal uncertainties are therefore conservative. A post-hoc neighbour-modelled estimate gives 0.94 ± 0.09 at 9.6σ, for information only.

**Evidence:**
- `validation/vanmaanen2_motion_stage2.json`, `validation/vanmaanen2_motion_stage2_pairs.csv`
- `validation/plots/vanmaanen2_stage2_*.png`
- **Reproduce:** `cd backend && uv run python scripts/target_motion_stage2.py`
- **Not rerun:** the first pass, `scripts/target_astrometry.py` → `validation/vanmaanen2_motion.json`, is kept as recorded.

## Phase 1 — validation and Gaia
- **Validation:** the last full run before this stage (2026-11-16 01:23Z) was current. Its only failures were the two ESA live checks, because ESA was unreachable.
- **ESA:** still unreachable (HTTP 000 at 01:27Z). Nothing was substituted.
- **Gaia record:** the van Maanen 2 field is the verified ARI record from the motion milestone. ARI reproduced the ESA-recorded Barnard response exactly (3180 × 41), and AIP's field response was identical.
- **Propagation:** Gaia positions were propagated to each exposure mid-time with rigorous space motion and geocentric parallax.
- **Target matching:** matched by propagation at all 13 epochs: Gaia DR3 2552928187080872832.
- **WCS:** 6 frames tie to 5–7 references. No translation is justified, and the convention test gives the catalogue frame.

## Phase 2 — target positions
**Fit.** The ePSF of the zone containing the star (the IRSA-tutorial convention), with A&K normalisation and a bicubic spline. A plane background, VARIANCE weights, excluded flags masked, 7×7 window. Fitted separately per season and detector; metadata per frame is in the JSON (zone, window, detector pixel, start tests).

**Systematics tested** (shifts relative to the nominal fit, in px):

| Test | Result |
|---|---|
| ePSF interpolated between zone centres | 0.0006–0.024 (largest on D3, at a zone edge) |
| Constant instead of plane background | ≤ 0.007 |
| 5×5 or 9×9 window | ≤ 0.013 |
| Catalogued neighbour modelled jointly (free flux) | ≤ 0.008; χ²/dof 27–70 → 0.9–3.5 on D1–D4 |
| D2 season-1 feature (5.1 px, S/N 24; flagged TRANSIENT, SUR_ERROR, PERSIST) | outside the 7×7 window. Its flagged pixels are excluded, so masking it explicitly changes nothing. An 11×11 window moves the target 0.002–0.003 px |

**Neighbour flux.** The fitted flux ratio rises with wavelength: 0.08 at 0.75 µm (equal to the Gaia RP ratio), 0.12–0.13 at 1.1 µm and 0.16–0.20 at 1.7–3.8 µm. That is a red field star next to a blue white dwarf.

**Per-epoch systematic budget.** The RMS over the five variants (the "analysis choice" term) is added to the existing systematics:
- target-zone vs reference-zone centroid convention;
- the target's PSF sensitivity;
- the simulated neighbour shift;
- the fit-window choice.

## Phase 3 — displacement per detector
Measured displacement = the two ePSF positions only, minus the change in the frames' reference offsets ("tied"), or as is ("untied"). The prediction is never an input.

| Pair | Observation IDs | Epochs | Predicted E, N (″) | Measured E, N (″) | σ stat (″) | σ sys (″) | Residual (″) | Measured/predicted | vs 0 | p vs pred | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **D2 tied** (primary) | 2025W27_2A_0674_2 / 2026W01_2A_0614_1 | 2025-07-06 → 2026-01-04 | +0.187, −1.532 | +0.353, −1.488 | 0.240, 0.269 | 0.061, 0.106 | +0.166, +0.043 | 0.99 ± 0.19 | 4.98σ | 0.79 | inconclusive |
| D2 untied | same | same | +0.187, −1.532 | +0.303, −1.440 | 0.309, 0.366 | 0.197, 0.147 | +0.116, +0.092 | 0.95 ± 0.26 | 3.3σ | 0.93 | inconclusive |
| **D3 tied** (primary) | 2025W28_1B_0122_2 / 2026W01_2A_0039_1 | 2025-07-07 → 2026-01-01 | +0.174, −1.502 | +0.040, −1.320 | 0.325, 0.299 | 0.145, 0.163 | −0.134, +0.182 | 0.87 ± 0.23 | 3.5σ | 0.81 | inconclusive |
| D3 untied | same | same | +0.174, −1.502 | +0.324, −1.367 | 0.358, 0.371 | 0.270, 0.185 | +0.150, +0.136 | 0.92 ± 0.27 | 2.9σ | 0.90 | inconclusive |
| D4 tied (secondary) | 2025W26_2A_0530_2 / 2026W02_1A_0218_2 | 2025-06-29 → 2026-01-06 | +0.218, −1.597 | +0.417, −1.567 | 0.299, 0.298 | 0.070, 0.072 | +0.199, +0.030 | 1.00 ± 0.19 | 4.9σ | 0.81 | inconclusive |
| D4 untied | same | same | +0.218, −1.597 | +0.291, −1.392 | 0.358, 0.391 | 0.178, 0.121 | +0.073, +0.205 | 0.88 ± 0.25 | 3.0σ | 0.87 | inconclusive |
| D5 untied (secondary) | 2025W27_2A_0674_2 / 2026W01_2A_0614_1 | 2025-07-06 → 2026-01-04 | +0.187, −1.532 | −0.237, −1.128 | 0.377, 0.403 | 0.320, 0.240 | −0.424, +0.404 | 0.71 ± 0.30 | 2.0σ | 0.48 | inconclusive |

The table above lists measured pairs only. Not measured:
- **D1:** its season-1 frame failed the start test. From one of four starts, the fixed-window fit converged 0.0046 px away with a lower χ²: the nominal fit had stopped in a local minimum. The rule rejected it, and it was not replaced by the better solution.
- **D5 tied:** only 2 references per frame.
- **D6:** excluded (stage-1 S/N 23–25 < 30).

**Combined primary pairs (D2 + D3):**

| Approach | Measured / predicted | vs zero | vs prediction | Budget validated | Robust across variants | Recovered |
|---|---|---|---|---|---|---|
| tied | 0.94 ± 0.14 | **5.8σ** | p = 0.93 | yes (15 reference stars, χ² 24.7/30) | yes (5.7–6.3σ) | **yes** |
| untied | 0.94 ± 0.19 | 4.1σ | p = 0.98 | yes (3 target zero-displacement pairs, χ² 1.7/6) | no | no |

Two seasonal measurements are not used to solve for proper motion or parallax separately. The parallax change between the seasons (−0.43″ E, −0.18″ N) is part of the prediction.

## Audit of the combined statistics (recomputed from the recorded per-pair values)
The figures **0.94 ± 0.14** and **5.8σ** are two different statistics of the same two tied pairs. Neither was changed for this audit.

**Detection against zero (5.8σ), direction-free.** It uses each pair's measured vector and its per-axis total σ (statistical ⊕ systematic):
- D2: (+0.353, −1.488)″ ± (0.248, 0.289)″. Pulls (+1.42, −5.15), χ² = 28.54.
- D3: (+0.040, −1.320)″ ± (0.356, 0.340)″. Pulls (+0.11, −3.88), χ² = 15.07.
- Total χ² = 43.61 for 4 dof. p = P(χ²₄ ≥ 43.61) = 7.7 × 10⁻⁹, which is **5.77σ** as a two-sided normal equivalent.
- The test does not use Gaia's predicted direction. It spends 4 dof, two of which (mostly the east components) carry little signal, so it is conservative. The stage-2 rule uses this statistic.

**Amplitude along the predicted direction (0.94 ± 0.14).**
- Each measured vector is projected onto the Gaia-predicted direction:
  - D2: 1.520 ± 0.288″ of a predicted 1.543″, ratio 0.985 ± 0.187.
  - D3: 1.316 ± 0.341″ of a predicted 1.512″, ratio 0.870 ± 0.225.
- Combined by inverse-variance weighting: 0.938 ± 0.144.
- This is one model-informed parameter. Its distance from zero is 0.938 / 0.144 = **6.5σ** (1-D), and its distance from 1 (= as predicted) is 0.43σ.
- It is quoted as an amplitude, not as the detection statistic.

**Agreement with the prediction (p = 0.93).** χ² = Σ ((measured − predicted)/σ_total)² over both pairs and axes.
- D2 contributes 0.470, D3 0.427. Total χ² = 0.896 for 4 dof, so p = P(χ²₄ ≥ 0.896) = **0.925**.
- The low χ² (P(χ²₄ ≤ 0.896) = 0.075) is consistent with conservative uncertainties: the unmodelled neighbour inflates them. It is not significant.

**Approximation.** The pair tests treat east and north errors as independent (diagonal). Correlations from the WCS Jacobian and the fit are neglected.

**Transcription correction.** An earlier version of this review rounded D2's tied significance to 4.99σ. The recorded value is 4.980σ (p = 6.35 × 10⁻⁷ > 5.7 × 10⁻⁷), so the pair stays inconclusive. No recorded value or status changed.

## Phase 4 — verification and plots
`validation/plots/`:

| File | Content |
|---|---|
| `vanmaanen2_stage2_positions.png` | measured vs predicted season-2 − season-1 positions (tied, untied) |
| `vanmaanen2_stage2_two_seasons.png` | native-pixel stamps for every measured pair, with prediction (+), measurement (×) and the flagged feature |
| `vanmaanen2_stage2_detector_estimates.png` | measured/predicted per detector |
| `vanmaanen2_stage2_residuals.png` | measured − predicted with statistical and total errors |
| `vanmaanen2_stage2_fits.png` | data, ePSF + plane model and normalised residual for every fit (the neighbour is the dominant residual) |
| `vanmaanen2_stage2_diagnostics.png` | S/N, χ², references, analysis-choice RMS vs fit σ |

**Investigated:**

| Topic | Finding |
|---|---|
| PSF centring convention | target-zone vs reference-zone differential in the budget; Gaia-free |
| WCS alignment uncertainty | reference tie (random part) or frame-offset RMS (untied, conservative) |
| Neighbour blending | modelled, ≤ 0.008 px |
| Background | constant vs plane, ≤ 0.007 px |
| Detector consistency | all six detector estimates 0.71–1.00, each within 1σ of 1 |

## Phase 5 — SkyShift integration
**Observatory:** the van Maanen 2 dataset gains an **Analyze → Target motion** tab. It appears only where the new `target_motion_study` capability is available; the Barnard field has no such tab. The tab shows:
- the verdict and the plan disclosure;
- a measurement vs model legend;
- the displacement plot (east left);
- the combined and per-pair tables with statuses;
- both seasons' native-pixel stamps with the predicted and measured positions;
- the per-frame quality table;
- the post-hoc note, provenance and limitations.

**API:** `GET /api/datasets/{id}/target-motion` serves the **recorded** study, flagged `stale` if code or data changed since it was computed. It answers 409 for other datasets. General target measurement (`source_measurement`, `astrometric_fit`) stays unavailable.

**Existing code:** Observatory, Motion Lab, Evidence Notebook and Methods code are otherwise unchanged. Methods text updated. No BlinkIR code exists or was touched.

## Phase 6 — final validation
`cd backend && uv run python scripts/validate.py --live` → `validation/report.json`, 2026-11-16T02:01:33Z, current (not stale).

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| pytest (with live) | 187 | 2: the ESA live Gaia checks `test_live_gaia_field_query_matches_recorded` and `test_live_gaia_archive_propagation_agrees`. Both raised `ArchiveRequestFailed`: WinError 10060 (connection timed out) to gea.esac.esa.int after the bounded 6 attempts. They are recorded as failures, not as skips or passes. | 0 |
| vitest | 107 | 0 | 0 |
| Playwright | 28 (incl. the 2 new target-motion browser tests) | 0 | 0 |

New tests this stage:
- **API:** `/target-motion` serves the recorded study with fixed origins and a staleness flag, measured ≠ predicted, D6 not measured, 409 elsewhere.
- **vitest:** sky-plot orientation (east left) and the stamp stretch.
- **Playwright:** the van Maanen 2 tab shows both seasons, the measurement/model legend, statuses and 13 frames; the Barnard field has no tab.

## Remaining issues
- **Neighbour not in the nominal model:** it should become the nominal estimator for future targets. The 9.6σ figure is post hoc.
- **D1 local minimum:** a best-of-starts minimisation rule needs a decision; it is not applied here.
- **Few references:** D1 and D5 have 2–3; the tied result rests on two exposure pairs.
- **ESA check pending:** compare the ARI-served Gaia record with ESA's once the archive answers.
- **Not blind:** the stage-2 plan followed the first pass; a blind confirmation would need new data, e.g. later DR epochs.
