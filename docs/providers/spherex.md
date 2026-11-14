# SPHEREx (NASA/IPAC IRSA) — planned primary image provider

Status: **documented, not implemented** (`backend/skyshift/providers/spherex.py`). No IRSA request has been made.

## Documented (per the brief's review, 2026-11-14; to verify live)
- References: [IRSA SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html), [archive access](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/), [data products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/), tutorials: [intro](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/), [cutouts](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/), [ePSF](https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/).
- Release: the tutorials recommend DR1/QR3 over QR2; never mix processing versions of one exposure.
- Discovery: IRSA SIA via `astroquery.ipac.irsa.Irsa` (with collection enumeration). Cutouts: TAP `spherex.artifact` joined to `spherex.plane`, returning a cutout URI and observation-time metadata.
- Products: spectral images with extensions read **by name** (expected: IMAGE, FLAGS, VARIANCE, ZODI, PSF, WCS-WAVE — `SPHEREX_EXPECTED_EXTENSIONS`, to confirm on a real file). IMAGE is surface brightness including zodiacal light.
- Wavelength depends on detector position: WCS-WAVE for visualisation, CWAVE/CBAND calibration products for quantitative work; check compatibility at the source position, not by detector number.
- DR1/QR3 effective PSFs are version-dependent and sub-pixel sampled: respect zone, oversampling and sub-pixel position; never treat an oversampled array as the native image or integrate pixel response twice; QR2 needs separate tested handling.

## Planned mapping into contracts
Observation: obs ID, release + processing version, raw timing keywords and time scale, exposure, detector, observer = spacecraft (until a spacecraft ephemeris exists, geocentre with `geocenter_suitability`: ≤ parallax × 7100 km / 1 AU). FrameProduct: `unit = MJy / sr`, `unit_kind = surface_brightness` (flux becomes `pending` until a validated conversion exists), variance, flags → mask bits, `BackgroundInfo(included_in_image=True, model_available=True, model_kind='ZODI')`, `PSFReference(model='effective_psf_product', product_format_version, oversampling, includes_pixel_response=True)`, `WavelengthInfo(position_dependent=True, calibration_ref=CWAVE/CBAND)`.

## Live checks to implement next
1. Collection enumeration and an explicit release choice (recorded). 2. Bounded SIA/TAP query around a field with confirmed coverage. 3. One cutout download, FITS opened by extension name, units/variance/flags/WCS preserved. 4. ePSF format/version detection; explicit error for unsupported legacy files. 5. A small exposure-resolved sequence registered with residuals recorded (tutorial field acceptable as a labelled registration fixture). Cache responses; cap concurrency; report missing/failed frames.
