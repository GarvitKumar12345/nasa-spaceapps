"""Build an observed SPHEREx Dataset (contracts + arrays) from a manifest and cached cutouts.

* Native frames keep the delivered IMAGE / VARIANCE / FLAGS arrays unchanged (units MJy/sr,
  (MJy/sr)^2, uint32 bit mask). They are the only arrays any future measurement may use.
* Display frames are bilinear reprojections onto a north-up grid using the archive TAN-SIP
  WCS ('archive_wcs_reprojection', display_only); SkyShift has not registered them.
* A 'band' is a local-wavelength compatibility group (same detector, |dlambda| within the
  stated fraction of the bandwidth at the field centre). Blink is offered only for groups
  with at least two available, validated members.
* Missing cache files, failed downloads and failed checks become explicit observation
  statuses. Nothing is ever substituted.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.coordinates import BarycentricMeanEcliptic, SkyCoord
import astropy.units as u

from skyshift.contracts import (
    AnalysisCapability,
    ArchiveObservationInfo,
    ArchiveQuerySummary,
    BackgroundInfo,
    Band,
    CompatibilityGroup,
    Coverage,
    Dataset,
    DatasetSummary,
    FieldDescription,
    FileCheck,
    FrameProduct,
    InstrumentDescription,
    MaskBit,
    Observation,
    ObservationTiming,
    ObserverModel,
    Provenance,
    PSFReference,
    Quality,
    SkyPosition,
    WavelengthInfo,
)
from skyshift.coords.time import make_epoch
from skyshift.coords.wcs import footprint_icrs, make_tan_wcs, pixel_to_sky, wcs_to_description
from skyshift.imaging.reproject import COVARIANCE_NOTE, reproject_to_grid
from skyshift.providers.base import DatasetBundle, FrameArrays
from skyshift.providers.spherex import reference as ref
from skyshift.providers.spherex.discovery import DiscoveryRow
from skyshift.providers.spherex.fetch import data_sha256, row_key
from skyshift.providers.spherex.fields import FieldPreset
from skyshift.providers.spherex.fitsfile import SpectralImage, UnsupportedSpherexProduct, read_spectral_image
from skyshift.providers.spherex.paths import REPO_ROOT, cutout_path, manifest_path
from skyshift.providers.spherex.wavelength import WavelengthSample, pair_compatible

NO_COVERAGE_BIT = 31
FETCH_COMMAND = "cd backend && uv run python -m skyshift.providers.spherex.fetch --field {field} --from-manifest"

UNAVAILABLE: list[AnalysisCapability] = [
    AnalysisCapability(id="source_detection", status="unavailable",
                       reason="Blind source detection is not implemented for SPHEREx surface-brightness images; the only sources examined are Gaia DR3 predictions.",
                       requirements=["Background and zodiacal-light handling validated on SPHEREx data", "Detections checked against an independent catalog"]),
    AnalysisCapability(id="source_measurement", status="unavailable",
                       reason="ePSF positions are measured only for Gaia reference stars inside the alignment diagnostics; measuring a chosen (target) source "
                              "is not validated (the field-centre star is saturated in every frame).",
                       requirements=["Target-specific ePSF fitting with neighbour modelling", "Validation on unsaturated targets of known motion"]),
    AnalysisCapability(id="photometry", status="unavailable",
                       reason="Pixel values are surface brightness (MJy/sr, zodiacal light included); point-source fluxes need pixel solid angles, aperture/ePSF "
                              "flux calibration and the documented systematic floor, none of which is validated here.",
                       requirements=["Flux calibration from MJy/sr with pixel solid-angle maps", "Comparison with the SPHEREx spectrophotometry tool", "Flag handling per ES Sect. 3.3"]),
    AnalysisCapability(id="astrometric_fit", status="unavailable",
                       reason="Target motion/parallax fits need validated per-epoch positions of the target; only reference-star residuals are measured, and the "
                              "field-centre star is saturated in every frame.",
                       requirements=["Validated target positions with uncertainties at each epoch", "A correction model validated on held-out stars"]),
    AnalysisCapability(id="difference_imaging", status="unavailable",
                       reason="Difference imaging needs PSF matching, a validated registration and calibrated spectral compatibility (CWAVE/CBAND); frames that merely "
                              "look aligned are not sufficient.",
                       requirements=["PSF matching between epochs", "Registration validated on held-out stars", "CWAVE/CBAND spectral calibration at the source position"]),
    AnalysisCapability(id="registration", status="unavailable",
                       reason="SkyShift does not re-register or correct these frames: display alignment uses the archive TAN-SIP WCS. The alignment diagnostics "
                              "measure its residuals and test a translation on held-out stars, but no correction is applied to any product.",
                       requirements=["A correction model justified in every frame used", "Propagation of the correction uncertainty into downstream products"]),
    AnalysisCapability(id="evidence_record", status="unavailable",
                       reason="Evidence records need a target identity and measurements, which are not available for observed SPHEREx data in this build.",
                       requirements=["Target source measurement (see above)"]),
]


def capabilities_for(field_id: str, n_frames_available: int | None = None) -> list[AnalysisCapability]:
    """Analysis capabilities of an observed SPHEREx dataset.

    The Gaia items need a recorded Gaia DR3 response that passes its own checks (sha256 against the manifest,
    schema/provenance; the same loader the API uses) and at least one cached SPHEREx cutout to place it on.
    Anything else makes them unavailable with the reason - never a substitute."""
    from skyshift.providers.base import ProviderUnavailable
    from skyshift.providers.gaia_dr3 import load_recorded_field

    caps = list(UNAVAILABLE)
    fetch = f"cd backend && uv run python -m skyshift.providers.gaia_dr3.fetch --field {field_id}"
    reason, requirement = None, ""
    try:
        load_recorded_field(field_id)
    except ProviderUnavailable as exc:
        detail = exc.reason if "run:" in exc.reason else f"{exc.reason}; run: {fetch}"
        reason, requirement = f"Gaia DR3 response not usable: {detail}", "Recorded Gaia DR3 query for the field that passes its checks (fixtures/gaia_dr3/<field>/)"
    if reason is None and n_frames_available == 0:
        reason = f"No SPHEREx cutout of this field is in the local cache; run: {FETCH_COMMAND.format(field=field_id)}"
        requirement = "Cached SPHEREx cutouts (backend/cache/spherex/<field>/)"
    if reason is None:
        caps.insert(0, AnalysisCapability(
            id="catalog_overlay", status="available",
            reason="Gaia DR3 sources (recorded query) propagated to each exposure mid-time and placed through the archive WCS: model predictions, not measurements."))
        caps.insert(1, AnalysisCapability(
            id="alignment_diagnostics", status="available",
            reason="Image-minus-Gaia residuals of isolated, unsaturated reference stars (ePSF positions on native pixels) before any correction; "
                   "per-frame status, rejected-star reasons and estimator validation in the report."))
    else:
        for cid in ("alignment_diagnostics", "catalog_overlay"):
            caps.insert(0, AnalysisCapability(id=cid, status="unavailable", reason=reason, requirements=[requirement]))  # type: ignore[arg-type]
    from skyshift.pipeline.target_motion import study_available

    if reason is None and study_available(field_id):
        caps.append(AnalysisCapability(id="target_motion_study", status="available",
                                       reason="Recorded validation study of this field's named moving target (scripts/target_motion_stage2.py): measured vs predicted "
                                              "seasonal displacement with its error budget. Not a general target-measurement capability."))
    else:
        caps.append(AnalysisCapability(id="target_motion_study", status="unavailable",
                                       reason="No recorded target-motion study for this field" + ("" if reason is None else f" ({reason})") + ".",
                                       requirements=["A named, unsaturated moving target with verified Gaia DR3 astrometry", "A recorded stage-2 study (scripts/target_motion_stage2.py)"]))
    return caps


class _ArchiveWcsAdapter:
    """sky -> native pixel through the archive WCS including SIP (for reproject_to_grid)."""

    def __init__(self, img: SpectralImage) -> None:
        self.w = img.wcs

    def sky_to_pixel(self, ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xy = self.w.all_world2pix(np.column_stack([np.asarray(ra, float), np.asarray(dec, float)]), 0, tolerance=1e-8, maxiter=50, quiet=True)
        return xy[:, 0], xy[:, 1]


def reproject_display(img: SpectralImage, grid_wcs, grid_shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(image, flags, coverage) on the display grid: bilinear image, nearest-pixel flags, NO_COVERAGE bit outside."""
    adapter = _ArchiveWcsAdapter(img)
    image, coverage = reproject_to_grid(img.image, np.zeros(img.shape, dtype=np.uint16), adapter, grid_wcs, grid_shape, order=1, bad_bits=0)
    ny, nx = grid_shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    ra, dec = pixel_to_sky(grid_wcs, xx.ravel().astype(float), yy.ravel().astype(float))
    xi, yi = adapter.sky_to_pixel(ra, dec)
    ix = np.clip(np.rint(xi).astype(int), 0, img.shape[1] - 1)
    iy = np.clip(np.rint(yi).astype(int), 0, img.shape[0] - 1)
    flags = img.flags[iy, ix].reshape(grid_shape).astype(np.uint32)
    flags[~coverage] = np.uint32(1 << NO_COVERAGE_BIT)
    return image, flags, coverage


@dataclass
class _Member:
    key: str
    row: DiscoveryRow
    download: dict | None
    screening: dict | None
    band_id: str


def load_manifest(dataset_id: str) -> dict:
    path = manifest_path(dataset_id)
    if not path.exists():
        raise FileNotFoundError(f"no retrieval manifest at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _epoch_utc_mjd(mjd: float):
    return make_epoch(float(mjd), "mjd", "utc")


def _quality_for(img: SpectralImage, checks: list[FileCheck], flags_near: list[str]) -> Quality:
    flags, msgs = [], []
    for c in checks:
        if c.status != "pass":
            flags.append(f"CHECK_{c.id.upper()}_{c.status.upper()}")
            msgs.append(f"{c.id}: {c.detail}")
    hard = [n for n in flags_near if ref.flag_class(n) == "photometry_mask"]
    soft = [n for n in flags_near if ref.flag_class(n) == "caution"]
    if hard:
        flags.append("PHOTOMETRY_MASK_FLAGS_NEAR_CENTRE")
        msgs.append(f"Within {ref.FLAG_SUMMARY_RADIUS_PX} px of the field centre: {', '.join(hard)} (ES Sect. 3.3 masks these for photometry).")
    if soft:
        flags.append("CAUTION_FLAGS_NEAR_CENTRE")
        msgs.append(f"Within {ref.FLAG_SUMMARY_RADIUS_PX} px of the field centre: {', '.join(soft)} (warning flags, ES Sect. 3.3).")
    fails = any(c.status == "fail" for c in checks)
    return Quality(status="rejected" if fails else ("warning" if flags else "ok"), flags=flags, messages=msgs)


def build_bundle(preset: FieldPreset, manifest: dict | None = None) -> DatasetBundle:
    manifest = manifest or load_manifest(preset.id)
    if manifest.get("collection") != preset.collection:
        raise ValueError("manifest collection does not match the field preset")
    ds_id = preset.id
    rows = {row_key(r["obs_id"], r["detector"]): DiscoveryRow(**r) for r in manifest["discovery"]["rows"]}
    downloads = {d["key"]: d for d in manifest.get("downloads", [])}
    screening = {s["key"]: s for s in manifest.get("screening", [])}
    sel = manifest["selection"]
    centre = SkyPosition(ra_deg=preset.ra_deg % 360.0, dec_deg=preset.dec_deg)

    # Band (= compatibility group) layout from the recorded selection.
    group_specs: list[tuple[str, int, list[str], bool]] = []
    for i, g in enumerate(sel["selected_groups"], start=1):
        group_specs.append((f"D{g['detector']}-g{i}", int(g["detector"]), list(g["members"]), True))
    for j, c in enumerate(sel.get("contrast", []), start=1):
        group_specs.append((f"D{c['detector']}-single{j}", int(c["detector"]), [c["key"]], False))

    images: dict[str, SpectralImage] = {}
    load_errors: dict[str, tuple[str, str]] = {}
    for _, _, keys, _ in group_specs:
        for k in keys:
            d = downloads.get(k)
            if d is None:
                load_errors[k] = ("missing", "selected in the manifest but never downloaded")
                continue
            if d.get("status") != "downloaded":
                load_errors[k] = ("failed", f"download/validation failed when fetched: {d.get('error')}")
                continue
            path = cutout_path(ds_id, d["file_name"])
            if not path.exists():
                load_errors[k] = ("missing", "cutout not in the local cache; run: " + FETCH_COMMAND.format(field=ds_id))
                continue
            try:
                img = read_spectral_image(path.read_bytes())
            except (UnsupportedSpherexProduct, ValueError, OSError) as exc:
                load_errors[k] = ("failed", f"cached file unreadable: {exc}")
                continue
            if data_sha256(img) != d.get("data_sha256"):
                load_errors[k] = ("failed", "cached file does not match the manifest (science-array hash differs); re-fetch")
                continue
            images[k] = img

    scale = float(np.median([math.sqrt(abs(np.linalg.det(im.wcs.pixel_scale_matrix))) * 3600.0 for im in images.values()])) if images else ref.NOMINAL_PIXEL_SCALE_ARCSEC
    n = preset.display_grid_px
    grid_wcs = make_tan_wcs(centre.ra_deg, centre.dec_deg, scale, (n, n))
    grid_desc = wcs_to_description(grid_wcs, (n, n), "common_grid")

    bands: list[Band] = []
    observations: list[Observation] = []
    frames: list[FrameProduct] = []
    arrays: dict[str, FrameArrays] = {}
    psf_by_band: dict[str, PSFReference] = {}
    ref_frames: dict[str, str] = {}
    max_r_km = 0.0
    f = preset.max_delta_fraction

    for band_id, det, keys, is_group in group_specs:
        avail = [k for k in keys if k in images]
        # Re-check compatibility with the cutouts' own WCS-WAVE values (not only the screening values).
        samples = [WavelengthSample(k, det, float(downloads[k]["lambda_um"]), float(downloads[k]["bandwidth_um"]), rows[k].t_min_mjd) for k in avail]
        pair_ok = all(pair_compatible(a, b, f) for i, a in enumerate(samples) for b in samples[i + 1 :])
        lams = [s.lambda_um for s in samples] or [float(screening[k]["lambda_um"]) for k in keys if k in screening and screening[k].get("lambda_um")]
        bws = [s.bandwidth_um for s in samples] or [float(screening[k]["bandwidth_um"]) for k in keys if k in screening and screening[k].get("bandwidth_um")]
        blinkable = is_group and len(avail) >= 2 and pair_ok
        if blinkable:
            reason = f"{len(avail)} available observations on detector {det} with local wavelengths within {f:g} x bandwidth at the field centre."
        elif not is_group:
            reason = "Single observation: no wavelength-compatible repeat was selected for this detector position (shown for contrast; same detector as a blink group but a different local wavelength)."
        elif not pair_ok:
            reason = "Cutout wavelengths at the field centre are not pairwise compatible; blink disabled."
        else:
            reason = f"Only {len(avail)} of {len(keys)} selected observations are available; blink needs two."
        lam_mid = float(np.mean(lams)) if lams else None
        label = f"D{det} · {lam_mid:.3f} µm" + ("" if is_group else " · single") if lam_mid else f"D{det}"
        group = CompatibilityGroup(
            rule=sel["rule"], detector=det, reference_position=centre, max_delta_fraction=f,
            lambda_min_um=min(lams) if lams else None, lambda_max_um=max(lams) if lams else None, min_bandwidth_um=min(bws) if bws else None,
            wavelength_determination="position_lookup_visualization", member_observation_ids=[f"{ds_id}:{k}" for k in keys], blinkable=blinkable, reason=reason,
        )
        bands.append(Band(id=band_id, label=label, center_um=lam_mid, width_um=float(np.mean(bws)) if bws else None, wavelength_model="position_dependent",
                          notes=[ref.WAVELENGTH_VISUALIZATION_NOTE, f"Group defined at the field centre RA {centre.ra_deg:.5f}, Dec {centre.dec_deg:+.5f}; elsewhere in the cutout the local wavelength differs."],
                          compatibility=group))
        for k in keys:
            row = rows[k]
            d = downloads.get(k) or {}
            obs_id = f"{ds_id}:{k}"
            img = images.get(k)
            native_id, display_id = f"{obs_id}:native", f"{obs_id}:display"
            if img is not None:
                t = img.timing()
                start, mid = _epoch_utc_mjd(float(t["MJD-BEG"])), _epoch_utc_mjd(float(t["MJD-AVG"]))
                exposure = float(t["XPOSURE"])
                mid_derivation = "MJD-AVG header keyword (TIMESYS=UTC): midpoint of observation"
                raw = {k2: v for k2, v in t.items()}
                sc = img.spacecraft_km()
                if sc:
                    raw.update({"X_SC_km": sc[0], "Y_SC_km": sc[1], "Z_SC_km": sc[2], "SC_SYSTEM": "GEOCENTER (header)"})
                    max_r_km = max(max_r_km, math.sqrt(sum(v * v for v in sc)))
            else:
                start, mid = _epoch_utc_mjd(row.t_min_mjd), _epoch_utc_mjd(0.5 * (row.t_min_mjd + row.t_max_mjd))
                exposure = row.t_exptime_s
                mid_derivation = "midpoint of SIA t_min/t_max (UTC MJD); file not available"
                raw = {"t_min": row.t_min_mjd, "t_max": row.t_max_mjd, "source": "SIA2 discovery row"}
            timing = ObservationTiming(start=start, mid=mid, exposure_s=exposure, mid_derivation=mid_derivation, raw=raw)
            prov = Provenance(origin="observed", provider="spherex", dataset_id=ds_id, release=preset.collection,
                              processing_version=f"{row.processing_tag} (pipeline {img.pipeline_version})" if img else row.processing_tag,
                              source_url=d.get("url") or row.access_url, retrieved_utc=d.get("retrieved_utc"), method="IRSA IBE cutout service (Spectral Image MEF)",
                              parents=[row.obs_publisher_did], notes=[f"file sha256 {d['sha256']}" if d.get("sha256") else "not downloaded"])
            checks = [FileCheck(**c) for c in d.get("checks", [])]
            status, status_reason = ("available", None) if img is not None else load_errors.get(k, ("missing", "not downloaded"))
            if img is not None:
                xq, yq = img.sky_to_pixel(centre.ra_deg, centre.dec_deg)
                lam, bw, cross = img.wavelength_at(xq, yq)
                near = img.flags_near(xq, yq)
                off = img.detector_offset() or (0.0, 0.0)
                info = ArchiveObservationInfo(
                    collection=preset.collection, release=ref.COLLECTIONS[preset.collection].release, obs_id=row.obs_id, detector=det, bandpass_name=row.bandpass_name,
                    file_name=row.file_name, access_url=row.access_url, cutout_url=d.get("url"), obs_publisher_did=row.obs_publisher_did, processing_tag=row.processing_tag,
                    pipeline_version=img.pipeline_version, sha256=d.get("sha256"), bytes=d.get("bytes"), retrieved_utc=d.get("retrieved_utc"),
                    header_quality=img.header_quality(), calibration_refs=img.calibration_refs,
                    query_pixel_detector=(xq + off[0], yq + off[1]), query_pixel_cutout=(xq, yq), edge_margin_px=(screening.get(k) or {}).get("edge_margin_px"),
                    local_wavelength_um=lam, local_bandwidth_um=bw, wavelength_method="WCS-WAVE lookup at the field-centre pixel (astropy -TAB; independent bilinear cross-check); visualization-grade",
                    wavelength_crosscheck_um=cross, flags_near_query=near, validation=checks,
                )
                quality = _quality_for(img, checks, near)
            else:
                s = screening.get(k) or {}
                info = ArchiveObservationInfo(
                    collection=preset.collection, release=ref.COLLECTIONS[preset.collection].release, obs_id=row.obs_id, detector=det, bandpass_name=row.bandpass_name,
                    file_name=row.file_name, access_url=row.access_url, cutout_url=d.get("url"), obs_publisher_did=row.obs_publisher_did, processing_tag=row.processing_tag,
                    pipeline_version=s.get("pipeline_version"), sha256=d.get("sha256"), bytes=d.get("bytes"), retrieved_utc=d.get("retrieved_utc"),
                    header_quality={k2: v for k2, v in (s.get("header") or {}).items() if k2 in ("FINAST", "L1DQAFLG", "L2DQAFLG", "PSF_FWHM")},
                    query_pixel_detector=tuple(s["query_pixel_detector"]) if s.get("query_pixel_detector") else None, edge_margin_px=s.get("edge_margin_px"),
                    local_wavelength_um=s.get("lambda_um"), local_bandwidth_um=s.get("bandwidth_um"),
                    wavelength_method="WCS-WAVE lookup from byte-range screening of the full file (file not available)", validation=checks,
                )
                quality = Quality(status="unavailable", flags=[status.upper()], messages=[status_reason or ""])
            frame_ids: list[str] = []
            if img is not None:
                frame_ids = [native_id, display_id]
                mask_bits = [MaskBit(bit=fd.bit, name=fd.name, description=fd.description or ref.DOCUMENTED_FLAGS.get(fd.bit, "")) for fd in img.flag_defs]
                wl = WavelengthInfo(band_id=band_id, center_um=info.local_wavelength_um, width_um=info.local_bandwidth_um, determination="position_lookup_visualization",
                                    calibration_ref="Spectral WCS CWAVE/CBAND product (not retrieved; required for quantitative work)", position_dependent=True,
                                    notes=[ref.WAVELENGTH_VISUALIZATION_NOTE, f"Evaluated at the field-centre pixel ({xq:.2f}, {yq:.2f}) of this cutout."])
                psf = PSFReference(model="effective_psf_product", fwhm_arcsec=float(img.image_header.get("PSF_FWHM")) if img.image_header.get("PSF_FWHM") else None,
                                   product_ref=f"EPSF extension ({img.epsf['rows']} zones; {img.epsf.get('calibration_source') or 'source file not stated'})",
                                   product_format_version=f"R7 EPSF table, {img.epsf['sample_shape']} samples, oversampling {img.epsf['oversampling']}",
                                   oversampling=int(img.epsf["oversampling"][0]) if img.epsf["oversampling"][0] else None, includes_pixel_response=True,
                                   source=f"{ref.EXPLANATORY_SUPPLEMENT} Sect. 4.2.3 (format recognised; not evaluated by SkyShift)")
                psf_by_band.setdefault(band_id, psf)
                bg = BackgroundInfo(included_in_image=True, model_available=True, model_kind=f"ZODI extension ({img.zodi_model})", subtracted_by_skyshift=False,
                                    notes=["IMAGE includes zodiacal light; the ZODI model is delivered separately and not subtracted (documented). SkyShift does not subtract it either."])
                finite = np.isfinite(img.image)
                native = FrameProduct(
                    id=native_id, observation_id=obs_id, dataset_id=ds_id, kind="native", shape=img.shape, unit=ref.IMAGE_UNIT, unit_kind="surface_brightness",
                    variance_unit=ref.VARIANCE_UNIT, planes=["image", "variance", "mask"], mask_bits=mask_bits,
                    wcs=wcs_to_description(img.wcs, img.shape, "native_header"),
                    coverage=Coverage(valid_fraction=float(finite.mean()), nan_marks_no_coverage=True, footprint_icrs=footprint_icrs(img.wcs, img.shape)),
                    band_id=band_id, wavelength=wl, psf=psf, background=bg, registration=None, display_only=False, provenance=prov, quality=quality,
                )
                image_d, flags_d, cov = reproject_display(img, grid_wcs, (n, n))
                display = FrameProduct(
                    id=display_id, observation_id=obs_id, dataset_id=ds_id, kind="archive_wcs_reprojection", shape=(n, n), unit=ref.IMAGE_UNIT, unit_kind="surface_brightness",
                    variance_unit=None, planes=["image", "mask"],
                    mask_bits=mask_bits + [MaskBit(bit=NO_COVERAGE_BIT, name="SKYSHIFT_NO_COVERAGE", description="Display grid pixel outside this cutout")],
                    wcs=grid_desc, coverage=Coverage(valid_fraction=float(cov.mean()), nan_marks_no_coverage=True, footprint_icrs=footprint_icrs(img.wcs, img.shape)),
                    band_id=band_id, wavelength=wl, psf=psf, background=bg, registration=None, display_only=True, derived_covariance_note=COVARIANCE_NOTE,
                    provenance=Provenance(origin="derived_measurement", provider="skyshift", dataset_id=ds_id, release=preset.collection,
                                          processing_version=prov.processing_version, method="skyshift.providers.spherex.dataset.reproject_display",
                                          method_version="1", parents=[native_id],
                                          notes=["Display-only: bilinear resampling through the archive TAN-SIP WCS; flags by nearest pixel; not registered by SkyShift."]),
                    quality=quality,
                )
                frames += [native, display]
                arrays[native_id] = FrameArrays(image=img.image, variance=img.variance, mask=img.flags)
                arrays[display_id] = FrameArrays(image=image_d, variance=np.full((n, n), np.nan, dtype=np.float32), mask=flags_d)
                ref_frames.setdefault(band_id, display_id)
            observations.append(Observation(
                id=obs_id, dataset_id=ds_id, provider="spherex", instrument="SPHEREx", detector=f"D{det}", band_id=band_id, status=status, status_reason=status_reason,
                timing=timing, pointing=None,
                observer=ObserverModel(kind="geocenter", ephemeris="astropy builtin (ERFA epv00)",
                                       approximation_note="SPHEREx is in low Earth orbit; the header gives its geocentric position (X_SC/Y_SC/Z_SC, kept in timing.raw). "
                                                          "No astrometric model is fitted to these frames in this build.",
                                       max_position_error_km=None),
                frame_ids=frame_ids, provenance=prov, quality=quality, archive=info,
            ))
    if max_r_km:
        bound = float(math.ceil(max_r_km / 100.0) * 100.0)
        observations = [o.model_copy(update={"observer": o.observer.model_copy(update={"max_position_error_km": bound})}) for o in observations]

    ecl = SkyCoord(centre.ra_deg * u.deg, centre.dec_deg * u.deg, frame="icrs").transform_to(BarycentricMeanEcliptic())
    disc = manifest["discovery"]
    n_dl = sum(1 for d in manifest.get("downloads", []) if d.get("status") == "downloaded")
    summary = ArchiveQuerySummary(
        provider="spherex", collection=preset.collection, query_url=disc["url"], retrieved_utc=disc["retrieved_utc"], n_rows=int(disc["n_rows"]),
        n_superseded=len(disc.get("superseded", [])), n_screened=sum(1 for s in manifest["screening"] if s.get("status") == "screened"),
        n_screen_failed=sum(1 for s in manifest["screening"] if s.get("status") != "screened"),
        n_selected=sum(len(g[2]) for g in group_specs), n_downloaded=n_dl, n_failed=len(manifest.get("downloads", [])) - n_dl,
        selection_rule=sel["rule"], manifest_path=str(manifest_path(ds_id).relative_to(REPO_ROOT)).replace("\\", "/"),
        notes=[preset.purpose, preset.centre_note],
    )
    available = [o for o in observations if o.status == "available"]
    caps = capabilities_for(ds_id, n_frames_available=len(available))
    gaia_ok = all(c.status == "available" for c in caps if c.id in ("catalog_overlay", "alignment_diagnostics"))
    dataset = Dataset(
        id=ds_id, title=preset.title, provider="spherex", origin="observed", release=preset.collection,
        description=(f"Real SPHEREx {ref.COLLECTIONS[preset.collection].release} Spectral Image cutouts ({preset.cutout_size_deg:g} deg) containing the field centre, "
                     f"grouped by local wavelength at that position. Read-only: display alignment uses the archive WCS; "
                     + ("Gaia DR3 predictions and reference-star alignment diagnostics are available, target measurements are not."
                        if gaia_ok else "Gaia DR3 predictions and alignment diagnostics are unavailable for this field (see the capabilities); "
                                        "target measurements are not available.")),
        field=FieldDescription(center=centre, fov_arcsec=preset.cutout_size_deg * 3600.0, ecliptic_lat_deg=float(ecl.lat.deg)),
        instrument=InstrumentDescription(name="SPHEREx", kind="spherex", pixel_scale_arcsec=scale, detector_shape=ref.DETECTOR_SHAPE, psf_by_band=psf_by_band,
                                         notes=["Six 2040x2040 H2RG detectors behind linear variable filters: wavelength varies across each detector.",
                                                "Pixel scale is the median linear scale of the cutout WCSs."]),
        bands=bands, observations=observations, frames=frames, common_grid=grid_desc, reference_frame_ids=ref_frames,
        astrometric_calibration=None, seed=None, generator=None, generator_version=None, scenario_parameters=None,
        limitations=[
            "Archive pixels are never modified: no SkyShift source detection, photometry, registration, target fit or difference image.",
            "Gaia DR3 overlays are model predictions placed through the archive WCS; reference-star ePSF positions are used only for alignment diagnostics.",
            "Local wavelengths use the WCS-WAVE lookup (visualization-grade, ~1 nm); CWAVE/CBAND calibration products were not retrieved.",
            "Display frames are bilinear reprojections through the archive TAN-SIP WCS; alignment is not verified by SkyShift.",
            "IMAGE is surface brightness including zodiacal light (MJy/sr); pixel values are not point-source fluxes.",
            "Wavelength compatibility is evaluated only at the field centre; other positions in the cutout see different wavelengths.",
            "The ePSF of the zone containing a star is used without interpolation between zones (zone width ~97 px; ~50 px along the spectral direction on D3).",
        ],
        capabilities=caps, archive_query=summary,
        provenance=Provenance(origin="observed", provider="spherex", dataset_id=ds_id, release=preset.collection, source_url=disc["url"], retrieved_utc=disc["retrieved_utc"],
                              method="IRSA SIA2 discovery + byte-range screening + IBE cutouts (skyshift.providers.spherex.fetch)", notes=[preset.centre_note]),
        quality=Quality(status="warning" if available else "unavailable",
                        flags=["DISPLAY_ONLY_ALIGNMENT", "VISUALIZATION_WAVELENGTHS"] + ([] if len(available) == len(observations) else ["SOME_OBSERVATIONS_UNAVAILABLE"]),
                        messages=[f"{len(available)} of {len(observations)} selected observations available."]),
    )
    native_images = {f"{ds_id}:{k}:native": img for k, img in images.items()}
    return DatasetBundle(dataset=dataset, arrays=arrays, catalog=[], catalog_name=None, truth=None, extras={"spectral_images": native_images})


def dataset_summary(preset: FieldPreset) -> DatasetSummary | None:
    """Summary without reading FITS files (availability from manifest + cache presence)."""
    try:
        manifest = load_manifest(preset.id)
    except FileNotFoundError:
        return None
    sel = manifest["selection"]
    keys = [k for g in sel["selected_groups"] for k in g["members"]] + [c["key"] for c in sel.get("contrast", [])]
    downloads = {d["key"]: d for d in manifest.get("downloads", [])}
    present = [k for k in keys if downloads.get(k, {}).get("status") == "downloaded" and cutout_path(preset.id, downloads[k]["file_name"]).exists()]
    rows = {row_key(r["obs_id"], r["detector"]): r for r in manifest["discovery"]["rows"]}
    times = sorted(rows[k]["t_min_mjd"] for k in keys if k in rows)
    from astropy.time import Time

    trange = (Time(times[0], format="mjd", scale="utc").isot[:19] + "Z", Time(times[-1], format="mjd", scale="utc").isot[:19] + "Z") if times else None
    availability = "ready" if len(present) == len(keys) and keys else ("partial" if present else "not_fetched")
    note = None if availability == "ready" else f"{len(present)} of {len(keys)} cutouts in the local cache. Fetch: " + FETCH_COMMAND.format(field=preset.id)
    return DatasetSummary(
        id=preset.id, title=preset.title, provider="spherex", origin="observed", release=preset.collection, n_observations=len(keys), n_available_frames=len(present),
        bands=[f"D{g['detector']}" for g in sel["selected_groups"]], time_range_utc=trange,
        description=f"Real SPHEREx {ref.COLLECTIONS[preset.collection].release} cutouts; read-only viewer (no measurements).",
        availability=availability, availability_note=note,
    )


def cached_files(preset: FieldPreset) -> list[Path]:
    manifest = load_manifest(preset.id)
    return [cutout_path(preset.id, d["file_name"]) for d in manifest.get("downloads", []) if d.get("status") == "downloaded"]
