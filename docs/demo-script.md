# SkyShift five-minute submission demonstration

SkyShift Discover comprises Observatory, Motion lab, Evidence notebook and Methods. BlinkIR Explore is the fifth navigation section, **BlinkIR**. Both products share one application.

## Prepare before recording

1. Keep `npm run dev` running from the repository root; open http://127.0.0.1:5173. The already-built local preview is also running at http://127.0.0.1:4173 with the API on 8000.
2. Confirm both observed fields are ready. A fresh checkout lacks 30 cutouts: restore them using `docs/final-submission.md`. Do not fetch during recording.
3. Preload Observatory → Data → van Maanen 2 → Analyze → Target motion. Wait for the native stamps and verified integrity status. Visit D2 tied and D3 tied once.
4. In another browser tab, prepare a **synthetic training record**: Training field 01, select S003, Analyze → Motion fit, run the fit and save the investigation. Check that Evidence notebook can validate and reproduce it.
5. Preload Motion lab, Methods and BlinkIR. Start BlinkIR on WISE 0855, Side by side. Confirm **Synthetic simulation** and **Illustrative model spectrum**. Pause playback.
6. Close unrelated windows and notifications. Keep the evidence ZIP ready as a fallback. Do not rerun scientific fitting scripts or live archive checks before the deadline.

## Exactly five minutes

| Time | Screen and actions | Suggested narration |
|---|---|---|
| 0:00–0:25 | Show navigation and the two product identities. | “SkyShift connects astronomical evidence with accessible infrared exploration. Discover investigates recorded observations; BlinkIR Explore teaches through labelled simulations. Observations, predictions and simulations stay distinct.” |
| 0:25–1:55 | Observatory → van Maanen 2 → Analyze → Target motion. Show seasonal dates and detector IDs; switch D2 tied to D3 tied. Point to prediction +, measurement ×, vectors and uncertainties. | “These are genuine SPHEREx DR1 pixels from two seasons. We found 216 image products and validated 13 cutouts. The primary reference-tied D2 and D3 analysis recovered 0.94 ± 0.14 of the Gaia-predicted seasonal displacement, at 5.8σ against zero and p = 0.93 agreement with the prediction. No individual pair reaches 5σ; D2 is 4.98σ. This is a recorded, non-blind displacement study, without an independent proper-motion or parallax fit. The separate 9.6σ neighbour-modelled analysis is exploratory.” |
| 1:55–2:30 | Show integrity/cache status, expand recorded figures, click **Export evidence ZIP**. | “The package preserves original JSON, CSV, six figures, input records, provenance and limitations. Scientific integrity is checked against the original reference commit independently of application test freshness. Missing images are reported honestly. The historical execution-hash mismatch remains documented.” |
| 2:30–3:15 | Motion lab: toggle proper motion and parallax. Evidence notebook: open the prepared synthetic record and show Validate/Reproduce and JSON/CSV export. | “The Motion lab explains drift and observer geometry. The notebook preserves reproducible synthetic investigations. Training records remain separate from the real study’s evidence ZIP.” |
| 3:15–4:35 | BlinkIR: WISE 0855, blink A/B, pause, inspect Difference B − A, select a pixel, change detector context, inspect a model sample, export a lesson. | “BlinkIR is educational simulation. Its scenes illustrate motion and variability; its graph contains 102 model samples in arbitrary units, not measured channels. Pixel selection reports simulated intensity, not spectral extraction. Water and methane markers do not establish an atmosphere. The exported lesson is explicitly simulated.” |
| 4:35–5:00 | Methods → Refresh status. Show counts and live checks marked not run. End on both products. | “The release passed 203 backend tests, 107 frontend unit tests and 30 browser checks; five live checks were skipped. Production build and typecheck passed. Discover preserves evidence; Explore makes the ideas approachable.” |

## Fallbacks and claims

- Use preloaded D2/D3 stamps and committed figures if a step is slow. Do not improvise a new fit.
- Archive unavailability must not become simulated observations.
- Keep the primary claim at **5.8σ**; **9.6σ** is post-hoc.
- Synthetic lesson dates are simulated timesteps, not observed visits.
- A local recording does not establish public deployment.

Push, public-access verification, optional temporary sharing, cache restoration and the final checklist are in `docs/final-submission.md`.
