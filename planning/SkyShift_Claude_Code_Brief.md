# SkyShift Claude Code Implementation Brief

Updated November 14, 2026. Includes the user's complete Space Apps resource list and the agreed observatory design.

## First Claude Code session

Use this document as the full project reference. In the first session, complete repository inspection and the first working synthetic investigation across Observatory, Motion lab, Evidence notebook, and Methods. This first-session scope takes precedence over the longer project roadmap below. Implement and verify that milestone before starting live archive integrations.

Review the SPHEREx, Gaia DR3, WiseView, and NEOSSat/CADC requirements now so the contracts support them. Preserve clearly identified provider boundaries and availability states. Subsequent sessions will connect and verify actual archive data; do not represent an unimplemented integration as working.

Read any existing `CLAUDE.md` and repository instructions. Keep project guidance concise: record the run and test commands, important scientific conventions, and a pointer to this brief, while preserving existing applicable instructions. Keep detailed requirements here rather than duplicating the entire specification into `CLAUDE.md`.

Start with a brief plan, then implement. Do not stop after proposing an architecture. End the session with the local run commands, a working demonstration of the completed synthetic investigation, test results, and explicit remaining limitations. Keep deployment outside this task.

## Task

Implement SkyShift in the current project as a modern observatory for finding, explaining, and documenting changes in astronomical images. Build a working local application with a complete synthetic investigation, then a verified SPHEREx image sequence and Gaia DR3 reference overlay. Prepare WISE and NEOSSat as clearly scoped extensions. Treat this brief as the latest requirements, while respecting applicable repository instructions and preserving useful existing work.

Start by inspecting the repository, its instructions, dependencies, and current implementation. Read `planning/SkyShift_Project_Blueprint.md`, `SkyShift_Plan.md`, and `verify_physics.py` if present. These optional context files may be absent; use this brief and report their absence without inventing their contents. Summarize a short implementation plan, then implement and verify it. Continue through the current session milestone without asking for approval after each routine step. Keep this task local; deployment is a separate task.

The existing mockups and any old report of 32 successful mathematical checks are references. They do not prove the new application, its image processing, or its archive integration works. Run checks against the code actually implemented.

## Product and design

The story is observe, explain, document. Use four connected sections:

| Section | Required purpose |
| --- | --- |
| Observatory | Compare images, inspect sources, measure changes, and inspect wavelength, quality, and provenance |
| Motion lab | Explain orbital motion and observer-dependent sky motion with explicitly synthetic scenes |
| Evidence notebook | Preserve selected observations, measurements, assumptions, notes, and reproducible exports |
| Methods | Explain the science and show actual validation results and remaining limitations |

Observatory has two modes, Explore and Analyze. They share dataset, selected source, epoch, wavelength selection, field of view, pan, and zoom. Switching modes must preserve this state.

Explore is the default: one generous sky canvas; target/coordinate search; available dates; blink/play/step controls; zoom; concise source information including uncertainty and quality; save candidate. Analyze exposes registered comparison images, optional difference previews, measurement tables, appropriate model controls, fit residuals, catalog associations, and export. Keep heavy diagnostics out of the default view, while retaining meaningful uncertainty and data-quality warnings.

Use a coherent restrained visual system: dark sky canvas, neutral panels, legible typography, subtle coordinate grid, limited violet action accents and teal source selection. Avoid large marketing headlines, decorative planets, fake telemetry, decorative scientific charts, and unnecessary panels. Scientific plots must be rendered from actual model or measurement arrays in code. Make keyboard controls, focus states, labels, contrast, loading, empty, and error states usable. Prioritize desktop, with responsive layouts that keep the viewer usable on smaller screens.

Every scene and result must identify its origin: observed, simulated, model prediction, or derived measurement. A measured position is not the same as an injected simulation truth coordinate.

## Resource analysis and assigned roles

Documentation was inspected for this brief. Successful documentation retrieval is not a live API, download, calibration, or scientific validation test. Record and test those separately during implementation.

| Supplied resource | Role in SkyShift | Implementation decision |
| --- | --- | --- |
| [NASA/IPAC SPHEREx resources](https://irsa.ipac.caltech.edu/Missions/spherex.html) | Primary mission data and authoritative release/tool index | Build the main image provider around documented IRSA services; retain dataset and processing versions |
| [SPHEREx tutorial notebooks](https://caltech-ipac.github.io/irsa-tutorials/spherex/) | Working examples for discovery, cutouts, WCS, ePSF, and other products | Adapt the relevant query, FITS handling, and calibration patterns into tested backend modules; do not run whole notebooks on every browser action |
| [WiseView](http://byw.tools/wiseview) | Design precedent for inspecting faint-source motion and variability | Use blink, field-size, band, and display controls as inspiration; treat a future WISE/unWISE provider as a separate data integration |
| [Gaia mission resources at MAST](https://archive.stsci.edu/missions-and-data/gaia) | Reference stars and links to Gaia release documentation | Pin Gaia DR3 explicitly; implement catalog access through a documented DR3-capable service such as ESA TAP using Astroquery |
| [CSA NEOSSat mission overview](https://www.asc-csa.gc.ca/eng/satellites/neossat/) | Scientific context for the optional Canadian mission case study | Use in Methods and attribution; this information page is not an image API |
| [Canadian Astronomy Data Centre](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/) | Archive infrastructure for a NEOSSat extension | Discover the supported public search/download interfaces and archive metadata; avoid authenticated curation services |
| [CSA NEOSSat tutorial](https://github.com/asc-csa/NEOSSAT_Tutorial) | Examples of acquisition, FITS inspection, and preprocessing | Use as an educational implementation reference; inspect its license before code reuse and retain applicable attribution |
| [CSA NEOSSat dataset](https://data.asc-csa.gc.ca/dataset/neossat) | Dataset discovery and links to mission data and documentation | Resolve to verified archive products; do not assume that the portal page itself returns images |

WiseView's live site and the CSA dataset portal timed out during this research. The [WiseView repository](https://github.com/backyardworlds/wiseview) and the [CADC NEOSSat collection](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/neossat/) provided usable primary documentation. Verify live endpoints during implementation; do not hardcode an assumed response or mark an inaccessible service connected.

### SPHEREx integration

Start with these primary references:

- [Archive access documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/)
- [Data-product documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)
- [Spectral image introduction](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)
- [Spectral image cutout notebook](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/)
- [Effective PSF notebook](https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/)

Current notebook documentation recommends DR1/QR3 over QR2. Confirm current service capabilities and select an explicit collection/release. Do not silently combine duplicate processing versions of the same exposure. Keep release and processing metadata with each frame.

The introduction demonstrates IRSA SIA discovery with `astroquery.ipac.irsa.Irsa`, including collection enumeration. The cutout notebook demonstrates TAP access using `spherex.artifact` joined to `spherex.plane`, returning a cutout URI and observation-time metadata. Inspect the actual schema and service capabilities before relying on either route. Use small bounded queries and cutouts for the first real sequence. Cache results, calibration products, and files; cap request concurrency; report missing or failed frames explicitly.

Preserve observation ID, release/version, source URL, raw timing and time scale, exposure duration, detector, spatial WCS, wavelength/bandwidth information, units, variance, flags, background model, and PSF/ePSF references. Read extensions by name and documented format; do not assume old HDU positions or an unchanging PSF structure.

This is a material update to older assumptions: DR1/QR3 have newer effective PSF products. The current ePSF tutorial distinguishes formats using version information and describes subpixel sampling. Respect the correct spatial zone, oversampling, and subpixel position through the documented model interface. Do not use an oversampled array as if it were the native detector image or double-integrate a model that already handles pixel response. Legacy QR2 support requires its own tested handling; prefer the recommended current products for the first integration.

SPHEREx wavelength depends on detector position. Check compatibility at the relevant sky/source position, not just detector number. Use the documented wavelength lookup for visualization and the appropriate CWAVE/CBAND calibration products for quantitative work. Keep spectral and spatial distortion handling distinct. Preserve coverage gaps rather than inventing a regular set of bands at every date.

Keep original surface-brightness arrays and units separate from display stretches. Handle variance, flags, zodiacal/background information, and source blending according to release documentation. Do not subtract an already-accounted background twice or treat a surface-brightness pixel value as point-source flux.

Use exposure-resolved images for motion. All-sky cubes or other combined products can provide navigation or spectral context, but do not present an aggregate as independent time-series epochs without verifying how its contributing observations and times are represented.

### Gaia DR3 integration

Use [ESA Gaia DR3 documentation](https://gea.esac.esa.int/archive/documentation/GDR3/) and the [Astroquery Gaia TAP documentation](https://docs.astropy.org/projects/astroquery/en/stable/gaia/gaia.html). Select `gaiadr3.gaia_source` explicitly instead of relying on a changing default or confusing DR3 with EDR3.

Retrieve a bounded set of reference sources and retain source IDs, reference epochs, positions, proper motions, parallaxes, relevant errors/correlations and astrometric quality information. Radial velocity is optional and must remain missing where unavailable. Respect the distinction between two-parameter and fuller astrometric solutions.

Gaia DR3 positions refer to a catalog epoch, generally J2016.0. Propagate usable source astrometry to each observation epoch before matching. Preserve the catalog's time convention; do not relabel it as UTC. Account for the `pmra = dRA/dt * cos(dec)` convention. `apply_space_motion` propagates source space motion; observer parallax requires separate geometry. Document zero-radial-velocity or other approximations and their validity.

Use an appropriately padded search region for sources whose reference-epoch positions may move into the displayed field. Match using position uncertainties and image resolution, and preserve ambiguous/blended matches. A Gaia nondetection or unmatched infrared source is not evidence of a new planet. Do not turn a weak, negative, or poorly constrained parallax directly into a distance.

### WiseView and WISE

The project repository documents WiseView as an unWISE blink viewer. Learn from its inspection workflow and retain relevant citations if using its work. Do not scrape or embed the external interface as SkyShift's backend.

A WISE/unWISE extension must independently verify its archive products, epoch/coadd definitions, WCS, bandpasses, and access method. Keep its metadata and instrument identity distinct. Side-by-side comparison is appropriate; quantitative cross-mission subtraction or color/brightness interpretation requires a separate validated treatment of bandpass, resolution, calibration, and epoch differences. Do not imply that WISE and SPHEREx channels are interchangeable.

### NEOSSat and CADC

Use the CSA mission page for context, the CSA dataset record for discovery, the CSA tutorial for acquisition/preprocessing examples, and CADC for verified archive products. CADC documents public CAOM/TAP and DataLink capabilities; inspect the appropriate service instead of using the metadata-curation interface.

The [NEOSSat collection documentation](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/neossat/) distinguishes RAW, CLEAN, COR, and CORD products. These correspond to different correction stages. Track the chosen product level and applied corrections; do not assume a filename proves full scientific calibration or repeat dark/overscan corrections without checking.

NEOSSat has a moving-target tracking mode. Inspect pointing/tracking metadata, exposure times, WCS quality, and possible source/star trailing before reusing registration or measurement routines. It is a distinct observing system, not another SPHEREx infrared band. Its moving solar-system targets should not automatically receive the nearby-star proper-motion/parallax model. Choose a separate verified example only if actual coverage and suitable data exist; simultaneous coverage of a SPHEREx target is not assumed.

## Architecture and data contracts

Preserve a suitable existing stack. For a new project, prefer React with TypeScript for the browser and one Python FastAPI backend using Astropy, NumPy/SciPy, and the relevant documented archive clients. Add a scientific image-fitting or reprojection library only when needed. Avoid separate microservices and accounts for the first local version.

Separate interface/state, API/contracts, providers, coordinates/time, scientific models, image processing/measurement, notebook storage/export, and validation. Proposed provider roles are Synthetic, SPHEREx, Gaia DR3, and optional NEOSSat/WISE. Gaia returns catalog records, not image frames; use separate contracts for observations and reference sources. Share normalized contracts and provenance, not unsupported assumptions about different instruments.

At minimum define Observation, FrameProduct, CatalogSource, SourceMeasurement, ModelFit, and EvidenceRecord schemas. Include units, epochs/time scales, coordinate frames, data origin, method version, quality and uncertainty status, and provenance. Frame products need their output WCS and coverage mask. Distinguish measured values, catalog values, simulation truth, and predictions in the API and UI.

All quantitative processing uses original scientific arrays or explicitly documented derived arrays. Display PNGs and contrast-stretched pixels are not measurement inputs. Reprojection must preserve appropriate units, masks, and bookkeeping; assess introduced covariance before interpreting photometric errors. Missing data remain missing. Never silently replace failed archive data with synthetic frames.

## Scientific behavior

### Observatory

Provide target/coordinate/FOV/date queries, explicit release and wavelength choices, acquisition status, provenance, and quality inspection. Align the stationary background on a common sky grid; do not recenter each epoch on the moving candidate and erase its motion. Keep actual observation times visible and preserve irregular sampling. Playback does not fabricate measurements between epochs.

Measure an isolated source with a documented centroid or PSF-fitting method and uncertainty estimate. For a first benchmark, use a controlled synthetic source and verify recovery from generated image pixels rather than copying injected truth coordinates into a measurement table. Real-image extraction must meet its own quality gates. Leave results pending when requirements are not met.

Fit an appropriate model to measured positions using their uncertainties. For nearby stars/brown dwarfs, allow proper motion and observer-dependent parallax only when time sampling and geometry constrain the parameters. Report covariance and underconstrained fits. For identified solar-system bodies, add ephemeris comparisons after target, observer, frame, timing, and light-time conventions are verified. An Earth-center approximation must be explicit and have a quantified suitability assessment for the use case.

Plot measurements, predictions, error bars, and residuals from actual arrays. Treat a good fit as evidence about that model, not an automatic classification or discovery. A difference preview needs aligned, wavelength-compatible images; scientific residual significance additionally needs calibration, background, PSF, and noise validation. Do not add unsupported discovery confidence, mass, temperature, or hazard scores.

### Motion lab

Implement two clearly separate teaching experiments:

1. A bound two-body orbit and a moving observer. Require positive semimajor axis and `0 <= e < 1`; solve Kepler's equation with consistent units and radians; place the Sun at a focus; draw equal-time markers; update position from absolute simulation time. Show the orbital plane and the observer's sky direction as distinct views. The viewing vector is target position minus observer position in a common frame. Reject undefined geometry. Explain omitted perturbations, light-time, and other precision effects. Do not assign an assumed Planet X orbit as a measured fact.
2. A nearby source with independently switchable proper motion and annual parallax. Derive its sky path from declared source and observer geometry, not an arbitrary universal sine wave. Label a circular 1 AU observer orbit as an approximation when used. Show units, time scale, assumed distance, and explicit visual magnification if present.

Generate deterministic training scenes with a seed and declared generic instrument parameters. Toy pixel scale, PSF, and noise are not a SPHEREx sensitivity model. Controls must change calculations and derived views consistently. Changing eccentricity must preserve the correct period relationship for unchanged semimajor axis and central mass.

### Evidence notebook and Methods

Save candidates and investigations with source identity, selected image IDs/versions, dates, measurements with uncertainties, model assumptions/settings, quality flags, notes, and provenance. Include simulation seed and truth separately for synthetic investigations. Use browser-local persistence initially, with validated JSON import/export and CSV measurements. Exports must retain origin labels and enough settings to reproduce results; do not save only a screenshot.

Methods must show actual status for each integration and test: documented, implemented, tested, failed, unavailable, or not run, with context and dates. Separate mathematical checks, source-measurement checks, image-registration checks, and live-data integration checks. Include references, attribution, and limitations. Do not render a hardcoded all-passed dashboard.

## Execution sequence

1. Inspect the codebase and resources; document the selected releases, access route, scientific assumptions, and first test field. Preserve existing useful code.
2. Complete a coherent local synthetic investigation across all four sections. Implement shared Explore/Analyze state, image-derived source measurements, at least one justified fit, Motion lab controls, notebook persistence/export, and accurate Methods status.
3. Implement and test SPHEREx discovery, bounded cutout acquisition, version-aware FITS/calibration handling, and one real registered sequence. Use the current notebooks as references and retain a reproducible fixture or retrieval manifest. Choose a field based on actual coverage and quality. Previously discussed targets are candidates, not guaranteed detections. A tutorial field is acceptable for a registration fixture if its purpose is labelled correctly.
4. Add Gaia DR3 acquisition, epoch propagation, and a reference overlay/match for that sequence. Quantify geometry and matching behavior. Do not force a motion or parallax result if real sampling cannot support one.
5. After the core works, implement a bounded NEOSSat case study and/or WISE comparison when feasible. Otherwise retain clearly described provider boundaries and honest availability status; document the remaining task. Do not sacrifice the primary SPHEREx investigation to collect unrelated datasets.
6. Review, run the relevant checks, fix observed failures, and leave a reproducible local demonstration. If a required service is blocked, continue independent work, retain explicit unavailable status and a provenance-labelled cached fixture where available, and report the exact uncompleted integration.

## Acceptance criteria

- All four sections are functional; Explore/Analyze switches preserve the selected investigation and view state.
- One deterministic synthetic investigation completes image generation, measurement, a justified model fit, residual inspection, notebook save, reload, and reproducible export.
- Kepler calculations agree with an independent numerical method or authoritative fixture under matched assumptions; check conservation/limiting cases and equal-time behavior.
- Coordinate tests cover RA wrapping, declination conventions, pixel-origin conventions, poles, and actual supported WCS distortions. Distinguish numerical round-trip success from real registration accuracy.
- Proper-motion/parallax tests cover zero-motion limits, the RA cosine convention, observer geometry, and model identifiability. Test recovery of injected motion using independent image measurements and justified tolerances.
- SPHEREx tests preserve release/version, image units, wavelength information, uncertainty/masks and calibration references. Test the supported effective-PSF format and explicit behavior for unsupported legacy files.
- A live SPHEREx query and cutout download plus Gaia DR3 query are genuinely tested and recorded if available. Otherwise those checks are explicitly uncompleted; documentation or mocked responses do not count as live tests.
- A real image sequence has its registration residuals, wavelength compatibility, and limitations recorded. No comparison is claimed valid solely because it looks aligned.
- Cross-catalog matching propagates catalog epochs, preserves ambiguous/missing matches, and does not invent a counterpart.
- Export/reload preserves origins, units, measurements, uncertainty, assumptions, and provenance. Changed analysis inputs invalidate stale fits.
- Browser-level checks cover primary controls, failure states, source selection, switching views, persistence, exports, and responsive layout. Build/type checks and meaningful scientific tests pass. Do not add tests that merely restate the implementation.
- Methods and the completion report accurately distinguish completed work, measured results, untested assumptions, and unavailable services. Do not promise an astronomical discovery or production-grade precision.

## Deliverables

Provide the implemented local application, environment/dependency instructions suited to the actual operating system, a small documented example investigation, fixtures or reproducible retrieval manifests, scientific and integration checks, and an honest validation report. Include a short demonstration script: notice a change in Observatory, explain its cause in Motion lab, inspect evidence in Analyze, and export the notebook record. Use explicit synthetic labels whenever that demonstration uses generated data.

Finish with how to run the project, the changed components, the checks actually executed, and the remaining limitations. Do not claim any external API or scientific result was verified unless you have the corresponding evidence.

## Supporting references

The eight user-supplied resources are linked in the resource table. Also use these primary references when implementing the relevant modules:

- [JPL Keplerian position formulas](https://ssd.jpl.nasa.gov/planets/approx_pos.html)
- [JPL Horizons coordinate, observer, and timing conventions](https://ssd.jpl.nasa.gov/horizons/manual.html)
- [Astropy source space-motion propagation](https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html)
- [Astropy WCS](https://docs.astropy.org/en/stable/wcs/index.html)
- [Astropy time](https://docs.astropy.org/en/stable/time/)
- [Gaia DR3 documentation](https://gea.esac.esa.int/archive/documentation/GDR3/)
- [Gaia TAP access with Astroquery](https://docs.astropy.org/projects/astroquery/en/stable/gaia/gaia.html)
- [CADC public web-service descriptions](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/services/)
- [CADC NEOSSat products](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/neossat/)
- [WiseView source and citation information](https://github.com/backyardworlds/wiseview)

Consult live documentation when selecting APIs and package versions. Pin the chosen configuration and record it; never silently switch a data release during a saved investigation.
