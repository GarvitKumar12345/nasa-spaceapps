# SPHEREx (NASA/IPAC IRSA) — primary image provider

Status: **implemented as a read-only viewer** (`backend/skyshift/providers/spherex/`). Live discovery, byte-range
screening and cutout downloads were executed against IRSA on 2026-11-14; no SPHEREx measurement, registration, fit
or difference image exists in this build (each is declared unavailable by the dataset itself).

## Release and access route
- **Release: DR1, wide survey — SIA2 collection `spherex_dr1`** (selected explicitly; R7 pipeline, Year-1 reprocessing of
  surveys 1–2). QR3 (`spherex_qr3`, surveys 3–4, also R7) is supported by the code but not mixed in; QR1/QR2 are refused.
- Discovery: IRSA SIA2 with an explicit `COLLECTION`, a small cone (`POS=CIRCLE ra dec r`, r ≤ 0.05°), VOTable parsed by
  column name. Duplicate processing versions of one exposure/detector are resolved by a stated rule and reported.
- Screening (before any cutout): HTTP byte ranges of each full Spectral Image (the server must answer 206): PRIMARY + IMAGE
  headers from the start of the file and the `WCS-WAVE` table from its end (~75 kB per image) → query pixel, edge margin,
  local wavelength/bandwidth, `FINAST`, `L2DQAFLG`.
- Pixels: IBE cutout service, `access_url?center=ra,decdeg&size=0.1deg` (all HDUs cut; EPSF table copied whole, ~3.9 MB).
- Client: standard library, IRSA URLs only, ≤ 4 concurrent requests, 12 attempts for transient 429/502/503/504 (IRSA's proxy
  returned intermittent fast `502 Proxy Error` responses during this session), byte limits, every request recorded.
- The API never downloads: datasets are built from the committed manifest and the local cache (`backend/cache/spherex/`,
  not committed). A missing file → observation `missing`; a failed download/check → `failed`; nothing is substituted.

## Exact query and reproduction
```
https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1&POS=CIRCLE+269.4462800+4.7680300+0.000300&RESPONSEFORMAT=VOTABLE
```
```bash
cd backend
uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --from-manifest   # re-download the recorded selection (~70 MB)
uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard                   # new discovery + screening + selection
uv run python -m skyshift.providers.spherex.fetch --field spherex-dr1-barnard --dry-run         # discovery + screening only, writes nothing
uv run pytest tests/test_spherex.py -m live                                                    # live IRSA checks (3 tests)
uv run python scripts/make_spherex_fixture.py                                                  # rebuild the offline test fixture from the cache
```
Retrieval record (committed): `fixtures/spherex/spherex-dr1-barnard/manifest.json` (query URL, every row, every screening
result, selection rule, each download with URL, HTTP status, bytes, sha256, science-array hash and file checks) and
`sia_response.xml.gz` (the raw SIA2 response).

## Evidence of archive access (2026-11-14)
- SIA2 at 16:41:44 UTC: **239** DR1 Spectral Images contain the field centre (all six detectors; MJD 60902–61165,
  2025-08-15 → 2026-05-05; processing tag `l2b-v27-…`, pipeline VERSION 7.0.5; 0 duplicate products).
- Screening: 239/239 images read by byte ranges (478 range requests, all 206); 234 eligible (5 rejected: field centre
  7–31 px from a detector edge, so a 0.1° cutout would be clipped).
- Cutouts: 17/17 downloaded and validated (496 requests in total, 86.7 MB, 4 transient retries, 0 failures).
- Live tests (`-m live`, passed): a fresh SIA2 query returns the same 239 products; fresh byte-range reads reproduce the
  recorded wavelength to 1e-12 µm; a fresh cutout passes all checks (full 441-zone EPSF) and has the recorded science-array hash.

## Field: Barnard's Star (GJ 699), approximate 2025.9 position RA 269.44628°, Dec +4.76803°
Chosen from coverage: DR1 has two observing seasons there (Aug–Sep 2025, Mar–May 2026), ~18 images per detector per
season. The centre is only a query position: SkyShift does not identify, match or measure any source. In every selected
frame the pixels within 2.5 px of the centre carry OVERFLOW + SUR_ERROR (early onboard overflow) and BLOOM, i.e. they
are excluded from SPHEREx photometry by the documented rules.

## Observations displayed (local wavelength at the field-centre pixel, WCS-WAVE)
Compatibility rule: same detector **and** |λᵢ − λⱼ| ≤ 0.25 × min(bandwidth) at the field centre for every pair. 148
groups exist among the 234 eligible images (75 singletons, 60 pairs, 13 triples); per detector the largest group (ties:
longest baseline) was downloaded, plus one same-detector contrast frame.

| Group | Blink | Mid-exposure (UTC) | Observation ID | λ at centre (µm) | Bandwidth (µm) | Photometry-mask flags within 2.5 px |
|---|---|---|---|---|---|---|
| D1 · 0.904 µm | yes | 2025-08-30 22:47:30 | 2025W35_2A_0474_4 | 0.9038 | 0.0230 | SUR_ERROR, BLOOM |
| D1 · 0.904 µm | yes | 2025-09-05 02:35:19 | 2025W36_2B_0123_1 | 0.9037 | 0.0230 | SUR_ERROR, BLOOM |
| D1 · 0.904 µm | yes | 2026-03-11 13:34:41 | 2026W11_1A_0539_1 | 0.9040 | 0.0236 | SUR_ERROR, BLOOM |
| D2 · 1.591 µm | yes | 2025-08-25 17:13:37 | 2025W35_1A_0146_3 | 1.5909 | 0.0387 | SUR_ERROR, BLOOM |
| D2 · 1.591 µm | yes | 2026-03-15 07:18:51 | 2026W11_2A_0550_1 | 1.5911 | 0.0387 | SUR_ERROR, PERSIST, BLOOM |
| D3 · 2.153 µm | yes | 2025-08-25 00:56:58 | 2025W35_1A_0008_4 | 2.1492 | 0.0542 | SUR_ERROR, BLOOM |
| D3 · 2.153 µm | yes | 2026-03-22 08:45:17 | 2026W12_2A_0520_1 | 2.1553 | 0.0542 | SUR_ERROR, PERSIST, BLOOM |
| D3 · 2.153 µm | yes | 2026-05-04 14:35:12 | 2026W19_1A_0216_1 | 2.1549 | 0.0542 | SUR_ERROR, BLOOM |
| D4 · 2.437 µm | yes | 2025-08-27 05:07:00 | 2025W35_1A_0432_4 | 2.4411 | 0.0540 | SUR_ERROR, BLOOM |
| D4 · 2.437 µm | yes | 2025-09-30 14:03:50 | 2025W40_1A_0353_1 | 2.4410 | 0.0539 | SUR_ERROR, NONFUNC, BLOOM |
| D4 · 2.437 µm | yes | 2026-03-11 02:12:34 | 2026W11_1A_0430_2 | 2.4298 | 0.0467 | SUR_ERROR, BLOOM |
| D5 · 4.370 µm | yes | 2025-08-25 17:13:37 | 2025W35_1A_0146_3 | 4.3699 | 0.0378 | SUR_ERROR, BLOOM |
| D5 · 4.370 µm | yes | 2026-03-15 07:18:51 | 2026W11_2A_0550_1 | 4.3701 | 0.0379 | SUR_ERROR, BLOOM |
| D6 · 4.822 µm | yes | 2025-08-25 00:56:58 | 2025W35_1A_0008_4 | 4.8192 | 0.0357 | SUR_ERROR, BLOOM |
| D6 · 4.822 µm | yes | 2026-03-22 08:45:17 | 2026W12_2A_0520_1 | 4.8239 | 0.0378 | SUR_ERROR, NONFUNC, BLOOM, HALO |
| D6 · 4.822 µm | yes | 2026-05-04 14:35:12 | 2026W19_1A_0216_1 | 4.8236 | 0.0378 | SUR_ERROR, BLOOM |
| D1 · 0.883 µm (contrast) | no | 2025-08-30 22:45:21 | 2025W35_2A_0474_3 | 0.8830 | 0.0223 | SUR_ERROR, BLOOM |

The contrast frame is on detector D1 like the first group, but its local wavelength differs by 0.9 bandwidth: the viewer
shows it alone and refuses blink, because detector number alone does not establish wavelength compatibility.

## Verified on real DR1 files (checked by code on every download)
| Item | Found in the files | Documented source |
|---|---|---|
| Extensions (by EXTNAME) | PRIMARY, IMAGE, FLAGS, VARIANCE, ZODI, **EPSF**, WCS-WAVE (the earlier stub assumed `PSF`) | data-product docs; PSF tutorial (VERSION ≥ 7 → EPSF) |
| Units | IMAGE/ZODI `MJy / sr`; VARIANCE `MJy2 / sr2`; FLAGS dimensionless | data-product docs |
| Flags | 22 bits defined in each FLAGS header (MSKN/MSKM/MSKD), all equal to ES Table 16; bit 29 (SATELLITE_HALO) is documented but absent from these headers | ES v2.1 Table 16 |
| Variance | finite and ≥ 0 wherever IMAGE is finite; non-finite IMAGE pixels are flagged | data-product docs; ES 3.2.12 |
| Spatial WCS | `RA---TAN-SIP`, SIP order 3, `RADESYS=ICRS`, ~6.153″/px; alternate WCS `A` = 0-based detector pixels | ES 3.2.8 (FINAST); cutout tutorial |
| Spectral WCS | `WAVE-TAB` lookup (`W` keys) over a 9×9 control grid; astropy `-TAB` and an independent bilinear implementation agree to ~1e-16 µm; cutout and full-file lookups agree | data-product docs (visualization only, ~1 nm) |
| Timing | `TIMESYS=UTC`; `MJD-AVG` = midpoint of `MJD-BEG`/`MJD-END`; `XPOSURE` 113.58 s ≤ `TELAPSE`; SIA `t_min` = `MJD-BEG` (UTC) | ES Table A.35 |
| Quality | `FINAST=0`, `L1DQAFLG`/`L2DQAFLG='Pass'` on all 17 | ES 3.2.8, 3.2.12 |
| ePSF | 441 zones (21×21), 33×33 samples, `OVSMPX=OVSMPY=5`, unit sum; recognised and recorded, **not evaluated** | ES 4.2.3 |
| Background | ZODI model `KEL98_WAVESCL_V1`, not subtracted from IMAGE (and not by SkyShift) | data-product docs |
| Observer | header gives the geocentric spacecraft position (|r| ≈ 7000 km); recorded, geocentre bound 7100 km | header (X_SC…) |

## Mapping into contracts
`Dataset(origin='observed', provider='spherex', release='spherex_dr1', capabilities=[…unavailable…], archive_query=…)`;
`Band` = compatibility group (`CompatibilityGroup`: rule, detector, λ range, min bandwidth, members, blinkable, reason);
`Observation.archive` (`ArchiveObservationInfo`: ids, processing tag, pipeline version, URLs, sha256, DQA keywords,
calibration references from `HISTORY [CALIB]`, query pixel, local λ/bandwidth, flags within 2.5 px, file checks);
native `FrameProduct` (`kind='native'`, delivered arrays, uint32 flags, TAN-SIP header WCS, `unit_kind='surface_brightness'`,
`WavelengthInfo(determination='position_lookup_visualization')`, `PSFReference(model='effective_psf_product', oversampling=5,
includes_pixel_response=True)`, `BackgroundInfo(included_in_image=True, subtracted_by_skyshift=False)`); display product
`kind='archive_wcs_reprojection'`, `display_only=True`, 64×64 north-up grid, bilinear image, nearest-pixel flags,
`SKYSHIFT_NO_COVERAGE` (bit 31) outside the cutout.

## Gaia DR3 predictions and alignment diagnostics (session 3)
The archive WCS is fitted to Gaia DR3 positions propagated with proper motion (ES v2.1 §3.2.8). The per-frame residuals
confirm a catalogue-frame WCS: χ² 197 (30 dof), frame offsets ≤ 0.30″, against the 4.7–12.8″ that applied aberration would
produce. Gaia DR3 predictions (no aberration, geocentric parallax applied once) are therefore placed through the archive WCS
on every frame. Reference stars are fitted with each frame's own ePSF (validated by injection into the real pixels).
- **Usable frames:** 15 of 17 have 5–13 references.
- **Pooled residual before correction:** mean (+0.016″, −0.015″), RMS (0.210″, 0.228″), extra scatter 0.11″.
- **Constant offset:** justified in 5 frames (mean offsets 0.14–0.43″), evaluated on held-out stars and never applied.
- **Too few references:** two frames (PERSIST-dominated D3; D6 with 4).

Details, per-frame table and error budget: [gaia_dr3.md](gaia_dr3.md).

## Not done (scientific limitations)
- No SPHEREx photometry: flux calibration from MJy/sr (pixel solid angles) and the documented systematic floor are not
  implemented; pixel values are surface brightness including zodiacal light. The ePSF is evaluated only to fit positions
  of Gaia reference stars for the alignment diagnostics.
- No registration or correction by SkyShift: display alignment uses the archive TAN-SIP WCS, whose residuals against
  Gaia DR3 are measured (above) but not applied. Hence no difference images and no target motion fits on real data.
- Wavelengths: WCS-WAVE lookup at the field centre only (visualization-grade); CWAVE/CBAND products not retrieved.
  Across one 0.1° cutout the local wavelength changes by 11 nm (D1, ≈ 0.5 bandwidth) to 27 nm (D3), measured at the
  cutout corners, so frames that are compatible at the centre are not necessarily compatible near the cutout edges.
- The field-centre source is affected by early overflow/bloom in every frame; any future measurement there needs special treatment.
- Only one field and one release; QR3 data (2026 survey 3–4) are not combined with DR1.
