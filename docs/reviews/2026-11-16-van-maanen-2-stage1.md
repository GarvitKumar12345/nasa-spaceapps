# van Maanen 2 — stage 1: data acquisition and checks (2026-11-16)

**Purpose.** This stage verifies whether van Maanen 2 (WD 0046+051) is usable for a later known-mover demonstration. It was recommended in the [estimator review](2026-11-15-estimator-api-tests-review.md).

**What is not done.** Nothing is measured on the target, and no capability is enabled. Target position, motion, flux and difference imaging stay unavailable. Gaia DR3 predictions for this field stay unavailable until a Gaia query is recorded.

**Evidence:**
- `fixtures/spherex/spherex-dr1-vanmaanen2/manifest.json` (retrieval record);
- `validation/vanmaanen2_stage1.json` (`cd backend && uv run python scripts/target_stage1.py --field spherex-dr1-vanmaanen2`).

## Data acquired (SPHEREx DR1, IRSA)
`uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-vanmaanen2`, run 2026-11-16 00:05–00:08Z.

- **Discovery:** SIA2 on `spherex_dr1`, cone 0.0003° at (12.30010°, +5.36918°). This is the approximate 2025.8 position from literature astrometry, used only to centre the query.
  - 216 Spectral Images on all six detectors.
  - One processing version (v27), no superseded duplicates.
- **Screening:** byte-range reads of all 216 files; 216 screened, 203 eligible. The 13 others put the target < 32 px from a detector edge, so their cutouts would be clipped.
- **Selection:** the existing rule (same detector, |Δλ| ≤ 0.25 × bandwidth at the field centre; largest group per detector; plus one contrast frame).
  - Each detector yields one compatible pair, spanning both seasons, with baselines of 178–191 d.
  - Contrast frame: `2025W26_2A_0530_3:D1`, Δλ = +0.018 µm from the D1 pair.
- **Cutouts:** 13 of size 0.1°, all downloaded and passing the file checks (R7 format, units, flags, WCS, cutout-vs-screening agreement).
  - 446 requests, 68.8 MB, 3 retried, 0 failed.
  - The cutouts are cached locally (50 MB, not committed).
- **Shared exposures:** D1/D4, D2/D5 and D3/D6 share exposures. There are 3 distinct epoch pairs, each seen at two wavelengths.

## Criteria (fixed in `scripts/target_stage1.py` before the data were read)
- **Usable frame:**
  - no saturation-type flag (OVERFLOW, SUR_ERROR, NONLINEAR, BLOOM) within 2.5 px of the target;
  - no excluded flag in the 3×3 core;
  - diagnostic S/N ≥ 30.
- **Diagnostic S/N:**
  - It is computed as Σ(IMAGE − annulus median) over the 3×3 box, divided by √(Σ VARIANCE + 81 var(median)).
  - IMAGE is surface brightness, so this is a detectability check: not a flux, an ePSF fit or a position.
  - The target pixel comes from the literature astrometry (an error of 1″ moves it by 0.16 px).
- **SPHEREx go:** ≥ 2 compatibility groups with a usable frame in each season.

## Results
| Detector | λ (µm) | Season 1 (UTC) | Season 2 (UTC) | Diagnostic S/N (S1, S2) | Saturation flags ≤ 2.5 px | Usable |
|---|---|---|---|---|---|---|
| D1 | 0.755–0.757 | 2025-06-29 03:39 | 2026-01-06 02:22 | 177, 183 | none | both |
| D2 | 1.114–1.118 | 2025-07-06 11:44 | 2026-01-04 12:52 | 169, 151 | none | both |
| D3 | 1.680–1.685 | 2025-07-07 13:50 | 2026-01-01 16:28 | 137, 136 | none (HALO flag within 2.5 px in S1, outside the core) | both |
| D4 | 2.453–2.459 | 2025-06-29 03:39 | 2026-01-06 02:22 | 109, 106 | none | both |
| D5 | 3.839–3.843 | 2025-07-06 11:44 | 2026-01-04 12:52 | 38, 39 | none | both |
| D6 | 4.459–4.463 | 2025-07-07 13:50 | 2026-01-01 16:28 | 25, 23 | none | neither (S/N < 30) |

The contrast frame (D1, 2025-06-29 03:41) has S/N 176 and no saturation flags. It has no partner, so it is not a pair.

- **Verdict, SPHEREx part: GO.** Five compatibility groups (D1–D5) have a usable frame in each season, against a criterion of 2. The target is unsaturated in all 13 frames: no saturation-type flag within 2.5 px.
- **Noise check:** the annulus pixel scatter is 0.9–1.3 × √VARIANCE. Adding the excess to the noise changes no S/N by more than 2 %.
  - In the Barnard's Star field (b ≈ +14°), D1–D4 showed 1.3–1.8 × with sky-fixed structure.
  - This high-latitude field (b ≈ −58°) is consistent with that structure being faint sources.
- **Expected displacement:** each pair's model prediction (`origin: model_prediction`) uses the project's validated propagation, the observer parallax at the actual mid-times, and the literature astrometry (μ = (+1.231, −2.712)″/yr, ϖ = 231.7 mas, RV unknown → 0).
  - **1.51–1.61″** per pair (E +0.17…+0.22″, N −1.50…−1.60″).
  - Proper motion contributes 1.45–1.56″. The parallax change between the seasons contributes (−0.43″ E, −0.18″ N), partly cancelling the eastward motion.
  - The estimator review's illustrative single-pair thresholds are ≈ 1.0–1.3″ at S/N ≥ 150 and ≈ 2″ at S/N 50.
  - The D1–D3 pairs (S/N 136–183) therefore sit above the illustrative threshold. The D5 pair (S/N ≈ 38) does not.
  - These are planning numbers, not a detection: per-epoch errors for this target must be measured in stage 2.

## Gaia part: pending
**Status:** the ESA Gaia archive has not answered since 2026-11-15:
- probes at 20:43–20:46Z;
- two `validate.py --live` runs (~21:00Z and 22:05Z), 6 attempts each;
- a probe at 2026-11-16 00:02Z.

Nothing from IRSA's Gaia copy was substituted. The planned query, from `python -m skyshift.providers.gaia_dr3.fetch --field spherex-dr1-vanmaanen2 --dry-run`:
- radius 0.1134620° (408.5″) = footprint 266.1″ + proper-motion margin 105.1″ + neighbour margin 37.2″;
- explicit ADQL on `gaiadr3.gaia_source` with an independent COUNT;
- archive-side EPOCH_PROP for pinned sources.

**Checks to run once it is recorded (criteria already listed in the stage-1 JSON):**
1. Gaia DR3 astrometry of the target: solution type, RUWE, parallax and proper motion. These replace the literature values.
2. Neighbours: none within 2 px brighter than 10 % (RP), and a simulated neighbour shift < 0.02 px, as in the estimator review.
3. ≥ 5 usable reference stars per frame for the alignment diagnostics, with the target excluded from its own reference set.
4. The predicted pair displacements recomputed from the Gaia values.

## Validation of this state
`cd backend && uv run python scripts/validate.py --live` → `validation/report.json`, 2026-11-16T00:28:10Z, current (not stale).

| Suite | Result |
|---|---|
| pytest | 177 / 179 passed. The 2 failures are the live Gaia checks (ESA unreachable, WinError 10060 after the bounded 6 attempts), reported as `unavailable`, never as passed. SPHEREx live 3 / 3 passed. |
| vitest | 105 / 105 passed |
| Playwright | 26 / 26 passed |

New tests in `tests/test_target_stage1.py`:
- the diagnostic S/N against its analytic expectation on a constructed frame, plus flag handling;
- the new field keeps the Gaia features and target measurements unavailable in the dataset, its description and the API (409).

## Next (stage 2, only with go-ahead)
- **Gaia step:** record the Gaia query and run the checks above.
- **If they pass, design target astrometry as its own validated capability:**
  - the target is excluded from the reference stars;
  - an ePSF fit with modelled neighbours;
  - per-epoch errors combining the target's centroid and the frame's shared terms;
  - a comparison with the Gaia-predicted displacement that is never tuned to agree.
- **Capability gate:** the capability stays unavailable until injection tests and held-out checks support it.
