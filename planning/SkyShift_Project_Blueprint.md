# SkyShift — project and visual blueprint

Prepared November 13, 2026. Planning and design stage.

**Product promise: See change. Understand motion. Preserve evidence.**

SkyShift should make a difficult scientific workflow understandable: compare compatible sky observations, inspect a change, understand possible causes, and save a reproducible record. The visual centerpiece is the sky itself. The simulator explains what the viewer sees.

This blueprint extends the supplied planning ZIP. The accompanying interactive sketch uses synthetic data only. It is not a SPHEREx connection, a validated astrometry tool, or a finished submission. “Submission quality” below is our proposed quality standard; it does not claim NASA certification or a verified current judging rubric.

## 1. The experience

The main journey is **observe → explain → document**. A newcomer should reach a useful comparison within a few actions. A technically experienced visitor should be able to inspect provenance and assumptions without leaving the investigation.

### Mission entrance

A concise introduction: “The sky changes. Learn to see it.” Use one annotated image comparison as the hero, with a short explanation of the question. Primary action: Explore observations. Secondary action: Open motion lab. When real data are unavailable, the primary action explicitly opens training data.

Keep this entrance brief. Lead into the instrument instead of placing a long marketing page between the visitor and the task. Use original SkyShift branding and accurate data attribution.

### Observatory — the main workspace

Desktop composition: compact navigation, investigation title, wide image canvas, source inspector to the right, time controls immediately below. Search and source/wavelength controls belong directly above the real-data canvas. The sketch begins with a fixed training fixture so its controls have meaningful behavior.

The image canvas offers blink, individual frame stepping, and side-by-side comparison. Images remain aligned to the stationary background. Coordinate grid, north/east orientation, angular scale, observation time, and coverage are readable without dominating the image. Missing frames remain gaps.

Selecting a source opens its coordinates, provenance, quality information, relevant wavelength, and any available measurements with uncertainty. Model positions use a dashed path; measured positions use explicit markers. Selecting “Save evidence” captures the current investigation state.

The real-data timeline displays discrete exposures at their actual spacing in time. It must not animate fabricated intermediate observations. The simulation timeline is continuous and says so.

### Motion lab — the signature interaction

Use a shared clock to connect physical geometry to what an observer sees. Provide two separate lessons:

1. **Keplerian orbit:** A Sun at an ellipse's focus, a moving target, and an observer. Equal-time markers demonstrate slower motion near aphelion. A swept sector demonstrates equal areas in equal times. A companion observer view shows the target direction calculated from the same states.
2. **Nearby-source motion:** A fixed sky field with independent proper-motion and observer-parallax toggles. Changing distance changes parallax amplitude; changing proper motion changes the secular track. This connects the teaching example back to the observational workflow.

The initial sketch includes both demonstrations across Observatory and Motion lab. It uses a two-dimensional orbital plane for clarity. An optional later 3D view should reveal inclination, line of sight, and reference planes, while keeping a readable planar view available. It is not needed for the first credible demonstration.

Use smooth playback only after an explicit Play action. Scrubbing, pausing, and step controls remain accessible. Body marker sizes are illustrative; distance scale stays linear unless a compressed scale is conspicuously labelled.

### Evidence notebook

One record contains the selected source, frames, dates, release, comparison settings, observation IDs, model parameters, provenance, notes, and measurements only when they exist. Export a machine-readable JSON manifest first. Add a human-readable report after the underlying record is reliable.

Observed records say “candidate for review.” Synthetic records retain their training label in the notebook and export. Saving a source is not an automated detection or discovery claim.

### Methods and validation

A compact methods screen makes the scientific contract inspectable: models used, assumptions, data transformations, software/data versions, completed checks, and outstanding limitations. Link it from every source inspector. Details should be available without making the first-time workflow intimidating.

## 2. Visual direction

The intended identity is a contemporary observatory: dark navy image fields, precise lines, large visual breathing room, warm neutral text, and a restrained cyan accent. Interface chrome also supports a readable light appearance. Amber identifies training or caution, paired with text and shapes.

Use strong editorial typography for the entrance and section titles; compact labels and tabular numbers inside the instrument. Keep a consistent spacing scale, quiet separators, and a small icon vocabulary. Allocate most of the main workspace to the image.

Observed intensity stays monochrome unless a clearly labelled composite is constructed from appropriate inputs. Color conveys overlay identity, selection, and scientific meaning. Movement should explain time or geometry. Avoid visual effects that resemble measurements without carrying information.

On smaller screens, the inspector moves below the viewer and navigation wraps. No essential action depends on hover. Support keyboard interaction, legible contrast, pausing, reduced-motion preferences, and touch targets.

The supplied sketch is a proposed direction, not a locked design. It demonstrates tabs, scrubbing, playback, proper-motion/parallax toggles, eccentricity, source saving, and a synthetic export preview.

## 3. Scientific rules

### Keplerian training model

Use consistent units and solve `M = E − e sin(E)` for each requested time. Compute orbital-plane coordinates as `x = a(cos(E) − e)` and `y = a sqrt(1 − e²) sin(E)`. The Sun lies at the focus. Never animate the target with constant true-anomaly speed. Support only elliptical orbits in this lesson and reject unsupported parameters. [JPL method](https://ssd.jpl.nasa.gov/planets/approx_pos.html)

The sketch uses `a = 1`, `μ = 1`, and `P = 2π` model units. Its observer follows a circular orbit with radius `0.2a` under the same μ. Markers show equal target-time intervals. It represents independent negligible-mass bodies around one central mass, with no mutual perturbations.

### Observer geometry and known objects

In a common frame, the geometric line of sight is `target position − observer position`. Physical orbit and apparent sky motion are different views of the same states. A real-image prediction needs a specified observer, epoch, frame, time scale, and correction convention. Match these against a frozen Horizons fixture before enabling precision overlays. Horizons astrometric coordinates include light-time; the teaching view does not. [Horizons manual](https://ssd.jpl.nasa.gov/horizons/manual.html)

Do not identify a geocentric observer with the SPHEREx spacecraft. Observer availability remains a prerequisite, and approximation status must travel with every prediction.

### Stellar motion

Propagate the source in Cartesian space, then subtract observer motion. Respect catalog `mu_alpha* = d(alpha)/dt cos(delta)`. Missing distance or radial velocity remains an explicit assumption. Straight-line space propagation alone does not supply observer parallax. [Astropy space-motion documentation](https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html)

The sketch uses a 10 pc source at the pole of a declared circular observer orbit, with 350 mas/year east and 120 mas/year north transverse motion, and zero radial velocity. Its reference stars and PSF are illustrative. This is a geometry lesson, not an example of SPHEREx angular resolution or source detectability.

### Image interpretation

Treat images as scientific products, not interchangeable photographs. Preserve original arrays, units, masks, timing, WCS, release identifiers, and processing history. Separate numerical arrays from display stretches.

The current documentation specifies release-dependent PSF/EPSF products and reserves WCS-WAVE for visualization; science wavelength analysis uses CWAVE/CBAND calibration. IMAGE is surface brightness and includes zodiacal background. The adapter must inspect actual release-specific products. [IRSA data products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)

A source's wavelength depends on its detector position. Comparisons need compatibility at the selected source, not merely a matching detector label. IRSA warns against mixing QR2 and QR3. [IRSA overview](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/overview.html)

Do not infer mass, temperature, distance, or planetary identity from a short track. Difference images, calibrated variability, and automatic detection each require additional validated methods.

## 4. Architecture and data flow

Use one React/TypeScript interface and one Python/FastAPI backend. Astropy handles astronomical coordinates, units, time, FITS, and WCS. Lock dependencies when implementation starts; the ZIP's NumPy/SciPy pins describe its reference run only.

Pipeline:

`provider → original observation record → validated image processing → display product → viewer → evidence record`

Prediction pipeline:

`declared model + time + observer → positions + assumptions → projection onto display WCS → labelled overlay`

Providers share an internal contract: synthetic fixtures, imported files, and a future IRSA adapter. A record includes identity, provenance, observed/synthetic status, original timing/time scale, observer, WCS, wavelength calibration, arrays/units/masks, display transform, and optional measurements. Model outputs carry their own provenance and assumptions.

Keep the browser responsible for interactions and rendering. Scientific transformations have a single tested implementation in the production system; any browser preview requires parity checks. Browser-local notebook persistence is sufficient initially. Cache stable fixtures so the demonstration remains usable when archive services are slow.

## 5. Build sequence and acceptance gates

| Stage | Deliverable | Evidence required to proceed |
|---|---|---|
| A — Design | Main screen, motion lab, notebook, design tokens, state map | Core journey is understandable; all mock data labelled; responsive layout checked |
| B — Training slice | Shared contract, synthetic frames, proper motion/parallax, Kepler lesson, export | Correct units, variable orbital speed, geometry/limiting-case checks, round-trip record reproduction |
| C — Real observations | One carefully selected, compatible SPHEREx sequence | Actual FITS parsed; units, masks, time, WCS, release and calibration preserved; source coverage verified |
| D — Image comparison | Registered playback, blink/split, selection, provenance | Reference WCS comparison; proposed valid-pixel numerical round-trip target < 0.001 pixel; separately measured registration residuals; injected-shift recovery |
| E — Prediction overlays | One known-object example, if observer support permits | Frozen Horizons agreement with identical target/observer/frame/time/corrections and justified tolerances |
| F — Submission | Rehearsed demo, documentation, sources, accessible interface, reproducibility package | Demo works from a clean start; exports reproduce state; claims match completed checks; current challenge requirements reviewed |

The first substantial implementation milestone is one complete training investigation through export. The next milestone is one real comparison through the same workflow. A small trustworthy end-to-end result is the scope target.

Candidate presets such as Barnard's Star are conditional on actual usable coverage, quality, wavelength compatibility, and visibility. Never promise a specific target before that check.

Keep automatic discovery, orbital fitting, calibrated light curves, mass/temperature estimates, and a full multi-body solar-system engine outside the first submission scope. Add these only when the core workflow and their own validation are complete.

## 6. Demonstration and submission package

Proposed 90-second story:

- **0–15 s:** “What changed in this patch of sky?” Open a verified sequence, or explicitly labelled training data if real integration is unfinished.
- **15–40 s:** Blink aligned frames. Inspect the source. Show dates, relevant wavelength, quality and provenance.
- **40–65 s:** Open the linked motion lesson. Scrub time and separate source motion from observer geometry.
- **65–90 s:** Save the evidence and show the reproducible record and its limitations.

Prepare a working demo, short recorded walkthrough, repository README, data/source attribution, architecture explanation, validation results, limitations, and a reproducible sample export. Verify the current official challenge's required deliverables before final packaging; the full 2026 rubric was not established in this planning pass.

The differentiator is the connection between **a visible change, an understandable physical explanation, and a traceable record**.

## 7. Status and decisions

- Supplied package read: five files; saved report says 32/32 reference checks passed. The ZIP script was not rerun in this task.
- Design direction: a wide scientific workspace with the image as the main focus.
- Sketch content: synthetic only; no named target's orbit or telescope detection is claimed.
- Open scientific dependency: release-specific real-data fixture and a suitable observer ephemeris.
- Open submission dependency: complete current challenge brief/rubric and final target selection.
- Next implementation task: establish the normalized contract and one tested training investigation, then attach a real-data fixture.
