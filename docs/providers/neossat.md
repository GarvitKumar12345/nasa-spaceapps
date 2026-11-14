# NEOSSat (CSA) via CADC — optional case study (extension)

Status: **documented, not implemented** (`backend/skyshift/providers/extensions.py: NeossatProvider`). No request made.

- References: [CSA mission](https://www.asc-csa.gc.ca/eng/satellites/neossat/) (context; not an image API), [CADC NEOSSat collection](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/neossat/), [CADC services](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/services/) (public CAOM/TAP and DataLink; not the metadata-curation interface), [CSA tutorial](https://github.com/asc-csa/NEOSSAT_Tutorial) (inspect its licence before reusing code), [CSA dataset record](https://data.asc-csa.gc.ca/dataset/neossat) (timed out during the brief's review).
- Product levels RAW / CLEAN / COR / CORD are different correction stages: record the chosen level and applied corrections; a filename does not prove calibration; do not repeat dark/overscan corrections.
- Moving-target tracking mode: inspect pointing/tracking metadata, exposure, WCS quality and star trailing before reusing registration or PSF measurement.
- Solar-system targets must not receive the nearby-star proper-motion/parallax model; they need verified ephemerides (target, observer, frame, time scale, light-time). Simultaneous SPHEREx coverage is not assumed.
