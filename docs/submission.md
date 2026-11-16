# SkyShift — observe change, explain motion, preserve evidence

Submission draft for NASA Space Apps. Team registration, selected challenge wording, public repository access and a hosted/video demonstration must be confirmed before submission. No hosting or publication was performed.

## Project description

SkyShift connects astronomical image exploration with reproducible scientific evidence and approachable infrared learning. SkyShift Discover presents genuine SPHEREx DR1 observations, Gaia DR3 position predictions, reference-star alignment diagnostics and a recorded recovery of van Maanen 2's seasonal displacement. BlinkIR Explore provides a separate educational studio for synthetic image comparison and illustrative infrared model spectra.

The distinction is visible throughout: observed pixels, catalog predictions, derived measurements, synthetic scenes and model curves have explicit identities. Failed or missing observations remain visible. Synthetic values never become additional observed epochs or scientific discovery records.

## Demonstrated scientific result

The committed van Maanen 2 study found 216 archive image products and validated 13 cutouts. Its primary reference-tied D2 + D3 analysis measured **0.94 ± 0.14** of the Gaia-predicted seasonal displacement, with **5.8σ** against zero displacement and **p = 0.93** agreement with the prediction. The primary prediction is approximately 1.51–1.54 arcseconds. The recorded JSON, CSV and six scientific figures are exported with data provenance, limitations, an integrity manifest and reproduction instructions.

This was **not blind**. No individual pair reaches 5σ. The study does not independently fit proper motion or parallax. D1 failed a start-dependence test; D5 lacked tied reference stars; D6 failed the predefined S/N rule. The separate 9.6σ neighbour-modelled analysis is post-hoc and exploratory. The scientific record remains unchanged at `docs/reviews/2026-11-16-van-maanen-2-stage2.md`.

## What is interactive

- Observatory: observed seasonal images, predictions, recorded target displacements, uncertainty components, detector results, provenance and evidence export; full synthetic investigation controls remain available.
- Motion lab: Keplerian orbital geometry, a moving observer, proper motion and parallax lessons.
- Evidence notebook: browser-local synthetic investigation records, validation, reproduction and JSON/CSV exports.
- Methods: genuine application validation results, source freshness, provider statuses and limitations.
- BlinkIR: five supplied educational presets, A/B comparison, blinking, simulated differences, pixel intensity inspection, detector wavelength context, model curves, molecular reference markers and separate simulation lesson export.

BlinkIR does not offer calibrated observed spectra, arbitrary archive target search, verified artifact flags, new-planet discovery or atmospheric confirmation. Its 102 samples are model samples in arbitrary units, and its detector selector provides wavelength context rather than a calibrated instrument response.

## Data and reproducibility

SPHEREx DR1 data come from NASA/IPAC IRSA, pinned by retrieval manifests and checksums. Gaia DR3 records include explicit ADQL, exact decimal-string source IDs and exposure-dependent predictions. The van Maanen 2 field uses an ARI partner response verified against ESA-recorded data, with the AIP cross-check recorded; ESA live connectivity was unavailable in the recorded validation. See provider documentation for attribution and scientific conventions.

The science manifest compares code, inputs and recorded outputs with the original reference commit `0c7f4ab`. Text hashes normalize Windows LF/CRLF differences. Missing downloaded cutouts are reported separately from evidence integrity. The old execution hash is retained; equality to the committed reference does not retrospectively prove the exact historical execution tree. Full application test freshness is a separate check.

## Five-minute demonstration

Use the timed script in `docs/demo-script.md`: 25 seconds introduction, 90 seconds observed motion, 35 seconds evidence and integrity, 45 seconds Motion lab and synthetic notebook, 80 seconds BlinkIR, and 25 seconds Methods and conclusion. Preload the observed stamps and a synthetic notebook record before recording.

Final audit, exact push and access-verification commands, temporary sharing instructions and fresh-checkout cache requirements are in `docs/final-submission.md`. No public deployment or repository accessibility is claimed. Submission-mode corrections affect documentation only.
