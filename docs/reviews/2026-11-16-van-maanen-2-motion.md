# van Maanen 2 — Gaia DR3 reference validation and measured motion (2026-11-16)

**Scope.** This milestone completes the pending Gaia DR3 step for the van Maanen 2 field and attempts to measure the target's motion between the two DR1 seasons from SPHEREx pixels.
- It follows [stage 1](2026-11-16-van-maanen-2-stage1.md).
- It is an offline validation study (`scripts/target_astrometry.py`). Target measurement is **not** enabled as an app capability; the API still answers 409.
- Measured positions are `derived_measurement`s from native pixels. Gaia propagations are `model_prediction`s. A prediction only selects the pixels to search, and is never substituted for a measurement.

**Evidence:**
- `validation/vanmaanen2_motion.json` (everything below);
- `validation/vanmaanen2_motion_table.csv` (one row per frame);
- `validation/plots/vanmaanen2_*.png`;
- `fixtures/gaia_dr3/spherex-dr1-vanmaanen2/` (Gaia record).

**Reproduce:**
```
cd backend
uv run python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-vanmaanen2 --service ari --crosscheck aip   # live, recorded
uv run python scripts/target_astrometry.py --field spherex-dr1-vanmaanen2                                         # offline
```

## 1. Gaia DR3 reference status
- **ESA unreachable:** the ESA Gaia archive (archive of record) has not answered since 2026-11-15. The latest probe was 2026-11-16 00:31Z, HTTP 000 after 3 × 20 s. Its live checks stay **unavailable**, never "passed".
- **Partner data centre, verified before use.** Gaia@ARI Heidelberg was queried with the exact ADQL of the ESA-recorded Barnard's Star field response. ARI returned an **identical** result: 3180 rows × 41 columns, every value, NULL and source_id equal. Only then was the van Maanen 2 field queried.
- **Independent cross-check.** Gaia@AIP Potsdam returned an identical van Maanen 2 response.
- **Record:**
  - 130 sources, matching an independent COUNT(*) of 130, `QUERY_STATUS` OK;
  - circle of 0.11346° (footprint + 10.5″/yr × 10 yr proper-motion margin + 6 px neighbour margin);
  - explicit `gaiadr3.gaia_source`, source_ids as decimal strings, `ref_epoch` = 2016.0 on every row;
  - retrieved 2026-11-16T00:37:30Z, response sha256 recorded.
- **Stated warnings (not silent passes):**
  - ARI declares no RELEASE parameter. DR3 identity rests on the table name plus the verification.
  - ARI delivers `duplicated_source` as 0/1 integers. These are read as boolean only because every value is 0 or 1.
- **Not done:** ESA's archive-side `EPOCH_PROP` check is an ESA function and unavailable on partners. The 5-row truncation probe on ARI timed out after its bounded 6 attempts; COUNT = rows still guards against truncation.
- **Loader enforcement:** a partner record loads only with a passing verification against the ESA reference that is committed now.
- **High proper motion.** The target was identified by propagating every Gaia source to each of the 13 exposure mid-times (rigorous space motion plus geocentric parallax), never by catalogue-epoch coordinates.
  - The target moves 28–30″ between J2016.0 and the DR1 epochs (|μ| = 2.978″/yr × 9.5–10 yr).
  - Result: Gaia DR3 **2552928187080872832**, the unique source within 0.24″ of the literature-propagated position at all 13 epochs with |μ| > 1″/yr.
  - Its astrometry: 5-parameter, RUWE 1.21, ϖ = 231.780 ± 0.018 mas, μ = (+1231.40, −2711.88) ± 0.02 mas/yr, G 12.30, RP 11.93, no radial velocity.
  - It is excluded from the reference stars of its own frames (reason `study_target`).

## 2. WCS alignment with background reference stars (target excluded)
- **Frames:** 6 of 13 frames have ≥ 5 usable references (D2 ×2, D3 ×2, D4 ×2, with 5–7 each); estimator injection validation passed in all.
- **Too few references:** D1 frames have 2–3, D5 frames 2, D6 frames 0. This high-latitude field (b ≈ −58°) is sparse in G ≤ 18.5 stars.
- **Translation:** none justified (total p = 0.10–0.93). Convention test: catalogue frame.
- **Pooled residuals before correction:** RMS east 0.296″, north 0.322″, 2-D 0.437″.
- **Not independent of Gaia:** agreement with Gaia does not validate every component of SPHEREx astrometry. Errors common to reference stars and target are not tested by this comparison.

## 3. Target measurement and predefined rules
- **Fit:** ePSF of the zone containing the target (spatially varying, per zone), a plane background, flags as masks, VARIANCE weights.
- **Start point:** the fit starts at the brightest pixel within 2 px of the prediction, and must give the same answer from four starts offset by 0.4 px. A test shows a prediction wrong by 1.4 px yields an identical measurement.
- **Per-epoch budget:**

  | Term | Kind |
  |---|---|
  | Fit σ × √χ²_red | random |
  | Frame tie, from the references' random error | random |
  | Frame's extra scatter | random |
  | Target-zone minus reference-zone centroid convention | systematic, does not cancel |
  | Target's adjacent-zone PSF sensitivity | systematic |
  | Simulated shift from catalogued Gaia neighbours | systematic |

- **Predefined rules** (`TargetConfig`, fixed before the run):
  - usable frames per stage 1; fit σ ≤ 0.25 px; start spread ≤ 0.002 px; ≥ 5 references for the frame tie;
  - D1–D3 primary, D4–D5 secondary, D6 excluded;
  - a detection needs p(vs 0) < 5.7e-7, and only if zero-displacement tests support the budget (p ≥ 0.0027).

## 4. Results

**Primary result, per the predefined rules: positions tied to reference stars.**

| Pair | Interval | Predicted Δ (E, N) ″ | Measured Δ (E, N) ″ | σ total (E, N) ″ | \|Δ\| measured / predicted ″ | Along-track ratio | Perpendicular ″ | p vs prediction |
|---|---|---|---|---|---|---|---|---|
| D2 (1.115 µm) | 182 d | +0.187, −1.532 | +0.353, −1.488 | 0.247, 0.287 | 1.529 / 1.543 | 0.985 ± 0.185 | +0.17 ± 0.25 | 0.79 |
| D3 (1.683 µm) | 178 d | +0.174, −1.502 | +0.040, −1.320 | 0.350, 0.331 | 1.321 / 1.512 | 0.870 ± 0.219 | −0.11 ± 0.35 | 0.80 |
| **D2 + D3** | | | | | | **0.94 ± 0.14** | | 0.92 (χ² 0.92, 4 dof) |

- **D1:** not tied; only 2–3 references.
- **D4, D5:** rejected by the start-spread rule (0.0024–0.0056 px > 0.002 px).
- **D6:** excluded (stage-1 S/N 23–25 < 30).
- **Significance not claimed.** The measured displacements agree with the Gaia prediction and are far from zero under the budget (χ² 44.9 for 4 dof). However, **no zero-displacement test was possible** under the predefined rules:
  - the same-instant pairs (D1/D4, D2/D5, D3/D6) each have one member without a frame tie or excluded;
  - so the rules forbid quoting a significance.

**Post-hoc analyses** (defined after the primary run; they do not change the decision above).
- **(a) D4/D5 rejections were caused by the fit window, not the start.**
  - Inside one fixed window, the fits from all starts agree to 10⁻⁷–10⁻⁸ px.
  - The 0.0024–0.0056 px spread came from `fit_position` re-centring its 7×7 window on each rounded start.
  - The resulting window-choice RMS is 0.0002–0.0025 px, against fit σ ≈ 0.03 px.
  - So the predefined start rule conflated window choice with start dependence.
- **(b) Untied positions (archive WCS, no reference tie).** This allows zero-displacement tests and the D1 pair.
  - **Per-epoch budget:** adds the field's frame-offset RMS (0.103″ E, 0.151″ N; conservative, it includes its own noise), the target zone's full convention term and the window-choice term.
  - **Zero-displacement tests:** two detectors at the same instant (D1/D4 and D2/D5, both seasons), and D1 two minutes apart (two exposures). Result **χ² = 2.21 for 10 dof (p = 0.99)**: the budget is not underestimated and is probably about 2× conservative.
  - **Untied displacements:**

    | Pair | Role | \|Δ\| measured / predicted ″ | Along-track ratio | p vs prediction |
    |---|---|---|---|---|
    | D1 | primary | 1.424 / 1.612 | 0.878 ± 0.205 | 0.75 |
    | D2 | primary | 1.471 / 1.543 | 0.950 ± 0.254 | 0.92 |
    | D3 | primary | 1.405 / 1.512 | 0.922 ± 0.270 | 0.89 |
    | D4 | secondary | 1.422 / 1.612 | 0.880 ± 0.252 | 0.87 |
    | D5 | secondary | 1.153 / 1.543 | 0.707 ± 0.302 | 0.47 |
  - **D1–D3 combined:** **0.91 ± 0.14** of the predicted displacement. Against zero, χ² 44.6 for 6 dof (p = 5.6e-8, about 5.4σ). Against the prediction, χ² 0.97.

**Reading.** All measured displacements point along the Gaia-predicted direction, with lengths 0.71–0.99 of the prediction, each within 1σ of 1.
- Under the predefined rules this is a **measured motion consistent with Gaia whose significance is not certified**.
- Under the post-hoc untied budget, which the zero-displacement tests support, the displacement is detected at about 5.4σ.
- Only two epochs per detector exist, so no independent parallax or orbit is inferred.

## 5. Detector-by-detector confidence
| Detector | S/N (stage 1) | Fit χ²_red | Tied result | Untied (post hoc) | Confidence |
|---|---|---|---|---|---|
| D1 | 176–183 | 39 | not tied (2–3 references) | 0.88 ± 0.21 | moderate; frame error from field RMS only |
| D2 | 151–169 | 52–57 | 0.99 ± 0.19 | 0.95 ± 0.25 | best tied pair |
| D3 | 136–137 | 65–70 | 0.87 ± 0.22 | 0.92 ± 0.27 | good; worst χ² (PSF misfit) |
| D4 | 106–109 | 27–29 | rejected (start rule) | 0.88 ± 0.25 | secondary; post hoc only |
| D5 | 38–39 | 3.6–4.9 | rejected (start rule; 2 references) | 0.71 ± 0.30 | weak |
| D6 | 23–25 | — | excluded (S/N) | — | excluded by design |

## 6. Evidence plots
- `validation/plots/vanmaanen2_displacement_vectors.png`: predicted vs measured vectors, east left; tied row and post-hoc untied row.
- `validation/plots/vanmaanen2_residuals_per_frame.png`: tied measured − predicted per frame with the full budget.
- `validation/plots/vanmaanen2_zero_displacement_tests.png`: post-hoc normalised differences, expected 0 ± 1.
- `validation/plots/vanmaanen2_stamps.png`: native pixels, predicted (+) and measured (×) positions.

## 7. Remaining issues
- **Error inflation dominates.** The target fits poorly on D1–D4 (χ²_red 27–70), as the estimator review found for bright stars, so the error budget is dominated by √χ² inflation. The zero-displacement tests suggest this is conservative. The misfit's cause is unresolved.
- **Few references.** The sparse field leaves D1 and D5 without frame ties. The tied result rests on two pairs.
- **Start rule wording.** The predefined start rule should test start dependence inside a fixed window and treat the window choice as a systematic term. This change was **not** applied to the primary result and needs a decision before reuse.
- **Partner-service checks.** ESA's live checks remain unavailable. Retry when the archive answers, and compare the ARI-served record with ESA's.
- **Correlated exposures.** Same-instant zero-displacement pairs share an exposure, so pointing errors common to the detectors cancel in them. Only the two-minute D1 pair tests the frame-WCS term across exposures.
- **No proper-motion fit.** Two epochs per detector support a displacement only.

## 8. Files and tests
**New:**
- `backend/skyshift/science/target_astrometry.py`
- `backend/scripts/target_astrometry.py`, `backend/scripts/plots_target.py`
- `backend/tests/test_target_astrometry.py`
- `fixtures/gaia_dr3/spherex-dr1-vanmaanen2/` (manifest, response)
- `validation/vanmaanen2_motion.json`, `validation/vanmaanen2_motion_table.csv`, `validation/plots/`
- this document

**Modified:**
- Gaia provider (`reference.py`, `catalog.py`, `fetch.py`, `__init__.py`): partner services, verification, cross-check and service-aware checks.
- `science/alignment.py`: `excluded_source_ids`, reason `study_target`.
- `imaging/epsf.py`: optional `window_center`, backward compatible.
- `pipeline/observed_gaia.py`: per-field config, recorded endpoint in provenance, service notes.
- `providers/spherex/fields.py`: `StudyTarget`.
- `scripts/target_stage1.py`: reads the preset.
- Tests: `test_gaia_dr3.py`, `test_target_stage1.py`.
- `backend/pyproject.toml` / `uv.lock`: matplotlib as a dev dependency.
- Docs: Methods, `CLAUDE.md`, provider docs.

**Tests.** `cd backend && uv run python scripts/validate.py --live` → `validation/report.json`, 2026-11-16T01:23:34Z, current (not stale).

| Suite | Result |
|---|---|
| pytest (with live) | 186 / 188 passed. The 2 failures are the ESA live Gaia checks (WinError 10060 after the bounded 6 attempts), reported `unavailable`. SPHEREx live 3 / 3 passed. |
| vitest | 105 / 105 |
| Playwright | 26 / 26 |

New tests:
- `test_target_astrometry.py` (7):
  - a wrong prediction does not move the measurement;
  - simulated neighbour shifts equal injected ones (3 geometries, photutils rendering);
  - quadrature mapping of the budget;
  - displacement geometry;
  - the recorded results keep measurements and predictions apart.
- `test_gaia_dr3.py` (+2):
  - exact-identity comparison, service-aware checks and refusal of unverified partner records;
  - the van Maanen 2 record's verification and cross-check.
- `test_target_stage1.py`, rewritten for the recorded state: Gaia features available, the study target never a reference, measurement capabilities 409.
