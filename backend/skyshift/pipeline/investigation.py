"""Synthetic investigation pipeline: detect -> register -> reproject -> track -> measure.

Registration uses reference stars from the dataset's catalog propagated to each
frame's epoch (space motion + observer parallax). Only stationary-consistent
catalog stars (|pm| < 20 mas/yr, parallax < 5 mas, or 2-parameter solutions)
define the frame solution, so a moving source's catalog values never shape the
registration that its own measurements depend on. Without a catalog the frames
are registered to the reference frame's detections and the absolute zero point
is flagged as uncalibrated.

Measurements are made on native arrays only. Reprojected (registered) frames
are display products for blink and difference previews.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np
from astropy.wcs import WCS

from skyshift.contracts import (
    AstrometricCalibration,
    CatalogAssociation,
    CatalogOverlay,
    ChangeIndicator,
    Coverage,
    Dataset,
    DetectedSource,
    DifferenceInfo,
    FrameProduct,
    MeasurementSet,
    Observation,
    Provenance,
    Quality,
    SkyPosition,
    SourceMeasurement,
    TrackPoint,
)
from skyshift.coords.tangent import angular_separation_deg, apply_offsets_mas, offsets_mas
from skyshift.coords.wcs import description_to_wcs, footprint_icrs, local_jacobian_mas_per_px
from skyshift.imaging.detect import Detection, detect_sources
from skyshift.imaging.psf import PSF_METHOD_VERSION, fwhm_to_sigma, windowed_centroid
from skyshift.imaging.registration import RegistrationResult, register_frame, registration_cov_mas
from skyshift.imaging.reproject import COVARIANCE_NOTE, difference, reproject_to_grid
from skyshift.providers.base import DatasetBundle, FrameArrays
from skyshift.science.catalog import ImagePoint, associate, has_full_astrometry, padded_search_radius_deg, propagate_catalog_source
from skyshift.versions import software_versions

PIPELINE_METHOD_VERSION = "1.0.0"
REF_MAX_PM_MAS_YR = 20.0
REF_MAX_PARALLAX_MAS = 5.0
REF_ISOLATION_FWHM = 2.5
SOURCE_MIN_SNR = 5.0
TRACK_MIN_RADIUS_ARCSEC = 1.5
TRACK_SIGMA_MULT = 5.0
AMBIGUITY_RATIO = 1.5
CHANGE_THRESHOLD = 5.0
COVERAGE_EDGE_PX = 3.0
TRACKING_METHOD = (
    "Linked from the reference-frame detection through all frames in time order: predicted position = last link "
    f"(one link) or a linear fit of the links; search radius max({TRACK_MIN_RADIUS_ARCSEC}\", {TRACK_SIGMA_MULT:g} x "
    f"link-residual rms); the nearest detection is linked unless a second lies within {AMBIGUITY_RATIO}x its distance "
    "(then 'ambiguous', not linked)."
)


@dataclass
class FrameState:
    product: FrameProduct
    observation: Observation
    arrays: FrameArrays
    sigma_px: float
    fwhm_arcsec: float
    mjd_tdb: float
    detections: list[Detection]
    registration: RegistrationResult
    registered_wcs_astropy: WCS | None
    det_ra: np.ndarray = field(default_factory=lambda: np.zeros(0))
    det_dec: np.ndarray = field(default_factory=lambda: np.zeros(0))
    det_cov_mas: np.ndarray = field(default_factory=lambda: np.zeros((0, 2, 2)))
    registered_product: FrameProduct | None = None
    registered_image: np.ndarray | None = None
    coverage: np.ndarray | None = None

    @property
    def registered_ok(self) -> bool:
        return self.registration.summary.quality.status != "rejected"


@dataclass
class _Track:
    points: dict[str, tuple[int | None, str]]  # native frame id -> (detection index, status)


def _det_sky(state: FrameState) -> None:
    if not state.detections:
        return
    xy = np.array([[d.x, d.y] for d in state.detections])
    state.det_ra, state.det_dec = state.registration.wcs.pixel_to_sky(xy[:, 0], xy[:, 1])
    covs = []
    w = state.registered_wcs_astropy
    for d in state.detections:
        jac = local_jacobian_mas_per_px(w, d.x, d.y) if w is not None else np.eye(2) * 400.0
        covs.append(jac @ d.cov_xy @ jac.T + registration_cov_mas(state.registration, d.x, d.y))
    state.det_cov_mas = np.array(covs)


class Investigation:
    """All derived products of one dataset; built once and cached."""

    def __init__(self, bundle: DatasetBundle) -> None:
        self.bundle = bundle
        ds = bundle.dataset
        self.dataset_id = ds.id
        self.grid_wcs = description_to_wcs(ds.common_grid)
        self.grid_shape = tuple(ds.common_grid.shape)
        self.center = ds.field.center
        self.observations = sorted(ds.observations, key=lambda o: o.timing.mid.mjd_tdb)
        self.catalog = bundle.catalog
        self.catalog_name = bundle.catalog_name
        products = {f.id: f for f in ds.frames}
        obs_by_id = {o.id: o for o in ds.observations}
        self.frames: dict[str, FrameState] = {}
        for obs in self.observations:
            if obs.status != "available":
                continue
            for fid in obs.frame_ids:
                prod = products[fid]
                fwhm = prod.psf.fwhm_arcsec or 1.0
                self.frames[fid] = FrameState(
                    product=prod, observation=obs_by_id[prod.observation_id], arrays=bundle.arrays[fid],
                    sigma_px=fwhm_to_sigma(fwhm / ds.instrument.pixel_scale_arcsec), fwhm_arcsec=fwhm,
                    mjd_tdb=obs.timing.mid.mjd_tdb, detections=[], registration=None,  # type: ignore[arg-type]
                    registered_wcs_astropy=None,
                )
        self.reference_frame_id = next(iter(ds.reference_frame_ids.values()))
        for st in self.frames.values():
            a = st.arrays
            st.detections = detect_sources(a.image, a.variance, a.mask, st.sigma_px)
        self._register_all()
        self._reproject_all()
        self.dataset = self._processed_dataset()
        self.sources, self._tracks = self._build_sources()
        self._measure_cache: dict[tuple[str, str], MeasurementSet] = {}
        self._lock = threading.Lock()
        self._add_change_indicators()

    # ------------------------------------------------------------------ registration
    def _catalog_refs(self) -> list:
        """Stationary-consistent, isolated catalog stars (no catalog neighbour within REF_ISOLATION_FWHM x the widest PSF)."""
        stationary = [
            s for s in self.catalog
            if not has_full_astrometry(s)
            or (math.hypot(s.pmra_mas_yr, s.pmdec_mas_yr) < REF_MAX_PM_MAS_YR and s.parallax_mas < REF_MAX_PARALLAX_MAS)  # type: ignore[arg-type]
        ]
        widest = max((st.fwhm_arcsec for st in self.frames.values()), default=1.0)
        isolation_deg = REF_ISOLATION_FWHM * widest / 3600.0
        ra = np.array([s.ra_deg for s in self.catalog])
        dec = np.array([s.dec_deg for s in self.catalog])
        out = []
        for s in stationary:
            sep = angular_separation_deg(s.ra_deg, s.dec_deg, ra, dec)
            if int(np.sum(sep < isolation_deg)) <= 1:  # only itself
                out.append(s)
        return out

    def _register_all(self) -> None:
        refs = self._catalog_refs()
        use_catalog = len(refs) >= 6
        ref_state = self.frames.get(self.reference_frame_id)
        for st in self.frames.values():
            nominal = description_to_wcs(st.product.wcs)
            det_xy = np.array([[d.x, d.y] for d in st.detections]) if st.detections else np.zeros((0, 2))
            det_cov = np.array([d.cov_xy for d in st.detections]) if st.detections else np.zeros((0, 2, 2))
            if use_catalog:
                props = [propagate_catalog_source(s, st.observation.timing.mid) for s in refs]
                ra = np.array([p.ra_deg for p in props])
                dec = np.array([p.dec_deg for p in props])
                cov = np.array([np.diag([p.sigma_ra_cosdec_mas**2, p.sigma_dec_mas**2]) for p in props])
                label = f"catalog:{self.catalog_name} (propagated to the frame epoch; stationary-consistent stars only)"
                ids = [s.id for s in refs]
            else:
                assert ref_state is not None
                rw = description_to_wcs(ref_state.product.wcs)
                rx = np.array([d.x for d in ref_state.detections])
                ry = np.array([d.y for d in ref_state.detections])
                ra, dec = rw.all_pix2world(rx, ry, 0)
                cov = np.array([d.cov_xy * 400.0**2 for d in ref_state.detections])
                label = f"frame:{self.reference_frame_id} (relative registration; absolute zero point uncalibrated)"
                ids = [f"ref{k}" for k in range(len(rx))]
            st.registration = register_frame(det_xy, det_cov, nominal, np.asarray(ra), np.asarray(dec), cov, ids, label)
            st.registered_wcs_astropy = st.registration.wcs.as_astropy() if st.registered_ok else nominal
            _det_sky(st)
        self.registration_reference = "catalog" if use_catalog else "frame"

    def _reproject_all(self) -> None:
        for st in self.frames.values():
            img, cov = reproject_to_grid(st.arrays.image, st.arrays.mask, st.registration.wcs, self.grid_wcs, self.grid_shape)
            st.registered_image, st.coverage = img, cov
            reg_id = f"{st.observation.id}:registered"
            summary = st.registration.summary
            st.registered_product = st.product.model_copy(
                update={
                    "id": reg_id,
                    "kind": "registered",
                    "shape": self.grid_shape,
                    "variance_unit": None,
                    "planes": ["image", "mask"],
                    "wcs": self.bundle.dataset.common_grid,
                    "coverage": Coverage(valid_fraction=float(np.mean(np.isfinite(img))), nan_marks_no_coverage=True, mask_plane="mask",
                                         footprint_icrs=footprint_icrs(st.registration.wcs.as_astropy() if st.registered_ok else description_to_wcs(st.product.wcs), st.product.shape)),
                    "registration": summary,
                    "display_only": True,
                    "derived_covariance_note": COVARIANCE_NOTE,
                    "provenance": Provenance(origin="derived_measurement", provider="skyshift", dataset_id=self.dataset_id, release=st.product.provenance.release,
                                             method="skyshift.imaging.reproject.reproject_to_grid (bilinear)", method_version=PIPELINE_METHOD_VERSION,
                                             parents=[st.product.id], software=software_versions(),
                                             notes=["Display product on the common grid; NaN = no coverage or masked input pixel."]),
                    "quality": Quality(status="ok" if summary.quality.status == "ok" else "warning", flags=summary.quality.flags, messages=summary.quality.messages),
                }
            )

    def _processed_dataset(self) -> Dataset:
        ds = self.bundle.dataset
        frames: list[FrameProduct] = []
        obs_out: list[Observation] = []
        for obs in ds.observations:
            ids = list(obs.frame_ids)
            for fid in obs.frame_ids:
                st = self.frames.get(fid)
                if st is None:
                    continue
                frames.append(st.product.model_copy(update={"registration": st.registration.summary}))
                if st.registered_product is not None:
                    frames.append(st.registered_product)
                    ids.append(st.registered_product.id)
            obs_out.append(obs.model_copy(update={"frame_ids": ids}))
        ref = self.frames.get(self.reference_frame_id)
        calib = None
        if ref is not None:
            summaries = [st.registration.summary for st in self.frames.values() if st.registered_ok]
            rms = [s.rms_residual_mas for s in summaries if s.rms_residual_mas is not None]
            nominal = description_to_wcs(ref.product.wcs)
            cy, cx = (ref.product.shape[0] - 1) / 2.0, (ref.product.shape[1] - 1) / 2.0
            r_ra, r_dec = ref.registration.wcs.pixel_to_sky(np.array(cx), np.array(cy))
            n_ra, n_dec = nominal.all_pix2world(cx, cy, 0)
            de, dn = offsets_mas(float(r_ra), float(r_dec), float(n_ra), float(n_dec))
            catalog_mode = self.registration_reference == "catalog"
            calib = AstrometricCalibration(
                reference_frame_id=self.reference_frame_id,
                catalog=self.catalog_name if catalog_mode else None,
                catalog_origin=("simulated" if self.bundle.dataset.origin == "simulated" else "catalog") if catalog_mode else None,
                method=(
                    "Each frame registered to catalog positions propagated to its own epoch; absolute frame = catalog frame."
                    if catalog_mode else "Frames registered to the reference frame's detections; zero point = reference header WCS (uncalibrated)."
                ),
                method_version=PIPELINE_METHOD_VERSION,
                n_used=int(np.median([s.n_used for s in summaries])) if summaries else 0,
                rms_residual_mas=float(np.median(rms)) if rms else None,
                offset_east_mas=float(de),
                offset_north_mas=float(dn),
                rotation_deg=ref.registration.summary.transform.get("rotation_deg"),
                quality=Quality(status="ok" if catalog_mode else "warning",
                                flags=[] if catalog_mode else ["ZERO_POINT_UNCALIBRATED"],
                                messages=[f"Reference-frame header WCS offset from the solution: {de:+.0f} mas east, {dn:+.0f} mas north."]),
                notes=[
                    "Per-epoch measurement uncertainties include the frame-registration term; the common catalog zero-point uncertainty "
                    "(sub-mas for the simulated catalog) is shared by all epochs and is not added per epoch.",
                ],
            )
        return ds.model_copy(update={"frames": frames, "observations": obs_out, "astrometric_calibration": calib})

    # ------------------------------------------------------------------ sources and tracking
    def _build_sources(self) -> tuple[list[DetectedSource], dict[str, _Track]]:
        ref = self.frames.get(self.reference_frame_id)
        if ref is None:
            return [], {}
        order = [k for k, d in sorted(enumerate(ref.detections), key=lambda kd: -kd[1].flux) if ref.detections[k].snr >= SOURCE_MIN_SNR]
        frames_by_time = sorted(self.frames.values(), key=lambda s: s.mjd_tdb)
        sources: list[DetectedSource] = []
        tracks: dict[str, _Track] = {}
        for n, k in enumerate(order, start=1):
            sid = f"S{n:03d}"
            det = ref.detections[k]
            cov = ref.det_cov_mas[k]
            sources.append(
                DetectedSource(
                    id=sid, dataset_id=self.dataset_id, label=sid, detected_in_frame_id=ref.product.id, band_id=ref.product.band_id,
                    x_px=det.x, y_px=det.y, position=SkyPosition(ra_deg=float(ref.det_ra[k]), dec_deg=float(ref.det_dec[k])),
                    sigma_ra_cosdec_mas=float(math.sqrt(cov[0, 0])), sigma_dec_mas=float(math.sqrt(cov[1, 1])),
                    flux=det.flux, flux_err=det.flux_err, flux_unit=ref.product.unit, snr=det.snr,
                    quality=Quality(status="ok" if det.psf_status == "ok" else "warning", flags=det.flags),
                )
            )
            tracks[sid] = self._track(ref, k, frames_by_time)
        for src in sources:
            pts = []
            for st in frames_by_time:
                idx, status = tracks[src.id].points[st.product.id]
                ra = float(st.det_ra[idx]) if idx is not None else None
                dec = float(st.det_dec[idx]) if idx is not None else None
                pts.append(TrackPoint(frame_id=st.product.id, status=status, ra_deg=ra, dec_deg=dec))  # type: ignore[arg-type]
            src.track = pts
        return sources, tracks

    def _track(self, ref: FrameState, k: int, frames_by_time: list[FrameState]) -> _Track:
        ra0, dec0 = self.center.ra_deg, self.center.dec_deg
        points: dict[str, tuple[int | None, str]] = {ref.product.id: (k, "measured")}
        e0, n0 = offsets_mas(float(ref.det_ra[k]), float(ref.det_dec[k]), ra0, dec0)
        links: list[tuple[float, float, float]] = [(ref.mjd_tdb, float(e0), float(n0))]
        start = next(i for i, s in enumerate(frames_by_time) if s.product.id == ref.product.id)
        # Forward in time from the reference, then backward (the reference is usually first).
        for direction in (frames_by_time[start + 1 :], list(reversed(frames_by_time[:start]))):
            for st in direction:
                pe, pn, rms = _predict(links, st.mjd_tdb)
                radius_mas = max(TRACK_MIN_RADIUS_ARCSEC * 1000.0, TRACK_SIGMA_MULT * rms)
                if not st.registered_ok:
                    points[st.product.id] = (None, "rejected")
                    continue
                pra, pdec = apply_offsets_mas(pe, pn, ra0, dec0)
                px, py = st.registration.wcs.sky_to_pixel(np.array(float(pra)), np.array(float(pdec)))
                ny, nx = st.product.shape
                if not (COVERAGE_EDGE_PX <= float(px) <= nx - 1 - COVERAGE_EDGE_PX and COVERAGE_EDGE_PX <= float(py) <= ny - 1 - COVERAGE_EDGE_PX):
                    points[st.product.id] = (None, "outside_coverage")
                    continue
                if len(st.det_ra) == 0:
                    points[st.product.id] = (None, "not_detected")
                    continue
                sep = angular_separation_deg(float(pra), float(pdec), st.det_ra, st.det_dec) * 3.6e6
                order = np.argsort(sep)
                if sep[order[0]] > radius_mas:
                    points[st.product.id] = (None, "not_detected")
                    continue
                if len(order) > 1 and sep[order[1]] <= radius_mas and sep[order[1]] < AMBIGUITY_RATIO * sep[order[0]]:
                    points[st.product.id] = (None, "ambiguous")
                    continue
                j = int(order[0])
                points[st.product.id] = (j, "measured")
                e, n = offsets_mas(float(st.det_ra[j]), float(st.det_dec[j]), ra0, dec0)
                links.append((st.mjd_tdb, float(e), float(n)))
        return _Track(points)

    # ------------------------------------------------------------------ measurements
    def source(self, source_id: str) -> DetectedSource:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(source_id)

    def measure(self, source_id: str, method: str = "psf_gaussian_fit") -> MeasurementSet:
        if method not in ("psf_gaussian_fit", "windowed_centroid"):
            raise ValueError(f"unknown method {method!r}")
        self.source(source_id)
        key = (source_id, method)
        with self._lock:
            if key not in self._measure_cache:
                self._measure_cache[key] = self._measure(source_id, method)
            return self._measure_cache[key]

    def _measure(self, source_id: str, method: str) -> MeasurementSet:
        track = self._tracks[source_id]
        out: list[SourceMeasurement] = []
        for obs in self.observations:
            prov = Provenance(origin="derived_measurement", provider="skyshift", dataset_id=self.dataset_id, release=obs.provenance.release,
                              method=f"skyshift.imaging.psf.{'fit_psf' if method == 'psf_gaussian_fit' else 'windowed_centroid'}",
                              method_version=PSF_METHOD_VERSION, software=software_versions())
            base = dict(source_id=source_id, dataset_id=self.dataset_id, observation_id=obs.id, band_id=obs.band_id, epoch=obs.timing.mid,
                        method=method, method_version=PSF_METHOD_VERSION, uncertainty_status="not_available")
            if obs.status != "available":
                out.append(SourceMeasurement(id=f"{self.dataset_id}:{source_id}:{obs.id}:{method}", frame_id=obs.id, status="missing_frame",
                                             status_reason=f"No frame: observation {obs.status} ({obs.status_reason})",
                                             quality=Quality(status="unavailable", flags=[obs.status.upper()]), provenance=prov, **base))  # type: ignore[arg-type]
                continue
            fid = obs.frame_ids[0]
            st = self.frames[fid]
            mid = f"{self.dataset_id}:{source_id}:{fid}:{method}"
            idx, status = track.points.get(fid, (None, "not_detected"))
            if idx is None:
                reason = {
                    "not_detected": "No detection within the tracking search radius.",
                    "ambiguous": "Two detections within the search radius; association left unresolved.",
                    "outside_coverage": "Predicted position falls outside this frame.",
                    "rejected": "Frame registration failed; positions would not be on the common sky frame.",
                }.get(status, status)
                out.append(SourceMeasurement(id=mid, frame_id=fid, status=status, status_reason=reason,  # type: ignore[arg-type]
                                             quality=Quality(status="pending" if status != "outside_coverage" else "unavailable", flags=[status.upper()]),
                                             provenance=prov, association_note=TRACKING_METHOD, **base))
                continue
            det = st.detections[idx]
            fit = det.fit
            if method == "windowed_centroid":
                a = st.arrays
                fit = windowed_centroid(a.image, a.variance, a.mask, det.x, det.y, st.sigma_px)
            assert fit is not None
            if fit.status == "rejected":
                out.append(SourceMeasurement(id=mid, frame_id=fid, status="rejected", status_reason=f"Measurement rejected: {', '.join(fit.flags)} {fit.message}".strip(),
                                             quality=Quality(status="rejected", flags=fit.flags), provenance=prov, **base))
                continue
            ra, dec = st.registration.wcs.pixel_to_sky(np.array(fit.x), np.array(fit.y))
            jac = local_jacobian_mas_per_px(st.registered_wcs_astropy, fit.x, fit.y)
            c_cen = jac @ fit.cov_xy @ jac.T
            c_reg = registration_cov_mas(st.registration, fit.x, fit.y)
            c = c_cen + c_reg
            s_e, s_n = math.sqrt(c[0, 0]), math.sqrt(c[1, 1])
            flags = list(fit.flags)
            q_status = "ok" if not flags else "warning"
            m_status = "measured"
            reason = None
            if "LOW_SNR" in flags:
                m_status, q_status, reason = "pending", "pending", f"S/N {fit.snr:.1f} below the quality gate of 5."
            if st.registration.summary.quality.status == "warning":
                flags.append("REGISTRATION_WARNING")
                q_status = "warning" if q_status == "ok" else q_status
            out.append(
                SourceMeasurement(
                    **{**base, "uncertainty_status": "estimated"},
                    id=mid, frame_id=fid, status=m_status, status_reason=reason,  # type: ignore[arg-type]
                    x_px=fit.x, y_px=fit.y, cov_xy_px=((float(fit.cov_xy[0, 0]), float(fit.cov_xy[0, 1])), (float(fit.cov_xy[1, 0]), float(fit.cov_xy[1, 1]))),
                    ra_deg=float(ra), dec_deg=float(dec), sigma_ra_cosdec_mas=s_e, sigma_dec_mas=s_n, corr_ra_dec=float(c[0, 1] / (s_e * s_n)),
                    sigma_components_mas={"centroid": float(math.sqrt(0.5 * np.trace(c_cen))), "registration": float(math.sqrt(0.5 * np.trace(c_reg)))},
                    wcs_used=f"registered:{fid}", flux=fit.flux, flux_err=fit.flux_err, flux_unit=st.product.unit, snr=fit.snr,
                    fit_chi2_reduced=fit.chi2_red, n_pixels=fit.n_pixels, psf_fwhm_arcsec=st.fwhm_arcsec,
                    association_note=TRACKING_METHOD if fid != self.reference_frame_id else "Reference-frame detection (defines the source).",
                    quality=Quality(status=q_status, flags=flags),  # type: ignore[arg-type]
                    provenance=prov,
                )
            )
        return MeasurementSet(
            dataset_id=self.dataset_id, source_id=source_id, band_ids=sorted({o.band_id for o in self.observations}), method=method,  # type: ignore[arg-type]
            method_version=PSF_METHOD_VERSION, measurements=out, association_method=TRACKING_METHOD,
            notes=[
                "Positions and fluxes are measured on the native original arrays (image, variance, mask); reprojected frames are display-only.",
                "Sky positions use each frame's registered WCS; sigma = centroid term (+) frame-registration term.",
                "The catalog zero-point uncertainty is common to all epochs and is not added per epoch.",
                "Fluxes are uncalibrated synthetic electrons per exposure (PSF-fit flux), not physical flux densities.",
            ],
        )

    # ------------------------------------------------------------------ change indicators
    def _add_change_indicators(self) -> None:
        for src in self.sources:
            ms = [m for m in self.measure(src.id).measurements if m.status == "measured"]
            inds: list[ChangeIndicator] = []
            if len(ms) >= 3:
                e, n = offsets_mas(np.array([m.ra_deg for m in ms]), np.array([m.dec_deg for m in ms]), self.center.ra_deg, self.center.dec_deg)
                we = 1.0 / np.array([m.sigma_ra_cosdec_mas for m in ms]) ** 2
                wn = 1.0 / np.array([m.sigma_dec_mas for m in ms]) ** 2
                chi2 = float(np.sum(we * (e - np.sum(we * e) / we.sum()) ** 2) + np.sum(wn * (n - np.sum(wn * n) / wn.sum()) ** 2))
                stat = chi2 / (2 * len(ms) - 2)
                inds.append(ChangeIndicator(kind="displacement", statistic=stat, n_epochs=len(ms), significant=stat > CHANGE_THRESHOLD, threshold=CHANGE_THRESHOLD,
                                            description="Reduced chi2 of measured positions about their weighted mean (static-position test). Derived statistic; not a classification."))
            else:
                inds.append(ChangeIndicator(kind="displacement", statistic=None, n_epochs=len(ms), significant=None, threshold=CHANGE_THRESHOLD,
                                            description="Fewer than 3 measured epochs: not evaluated."))
            best: float | None = None
            n_used = 0
            for band in sorted({m.band_id for m in ms}):
                bm = [m for m in ms if m.band_id == band and m.flux is not None and m.flux_err]
                if len(bm) < 3:
                    continue
                f = np.array([m.flux for m in bm])
                w = 1.0 / np.array([m.flux_err for m in bm]) ** 2
                stat = float(np.sum(w * (f - np.sum(w * f) / w.sum()) ** 2) / (len(bm) - 1))
                if best is None or stat > best:
                    best, n_used = stat, len(bm)
            inds.append(ChangeIndicator(kind="flux_variation", statistic=best, n_epochs=n_used, significant=None if best is None else best > CHANGE_THRESHOLD,
                                        threshold=CHANGE_THRESHOLD,
                                        description="Largest per-band reduced chi2 of PSF fluxes about their weighted mean. Derived statistic on uncalibrated counts; not a classification."))
            src.change_indicators = inds

    # ------------------------------------------------------------------ catalog
    def associations(self, source_id: str) -> list[CatalogAssociation]:
        ms = [m for m in self.measure(source_id).measurements if m.status == "measured"]
        out: list[CatalogAssociation] = []
        for m in ms:
            st = self.frames[m.frame_id]
            points = [
                ImagePoint(source_id=source_id if j == self._tracks[source_id].points[m.frame_id][0] else f"det{j}",
                           measurement_id=m.id if j == self._tracks[source_id].points[m.frame_id][0] else None,
                           ra_deg=float(st.det_ra[j]), dec_deg=float(st.det_dec[j]),
                           sigma_ra_cosdec_mas=float(math.sqrt(st.det_cov_mas[j][0, 0])), sigma_dec_mas=float(math.sqrt(st.det_cov_mas[j][1, 1])))
                for j in range(len(st.detections))
            ]
            assoc = associate(points, self.catalog, m.epoch, resolution_arcsec=st.fwhm_arcsec)
            out.extend(a for a in assoc if a.image_source_id == source_id)
        return out

    def catalog_overlay(self, frame_id: str) -> CatalogOverlay:
        st = self._state(frame_id)
        epochs = [o.timing.mid for o in self.observations if o.status == "available"]
        ref_epoch = self.catalog[0].reference_epoch if self.catalog else st.observation.timing.mid
        half = 0.5 * math.hypot(*self.grid_shape) * self.bundle.dataset.instrument.pixel_scale_arcsec / 3600.0
        radius = padded_search_radius_deg(half, ref_epoch, epochs)
        props = []
        srcs = []
        for s in self.catalog:
            if angular_separation_deg(s.ra_deg, s.dec_deg, self.center.ra_deg, self.center.dec_deg) <= radius:
                srcs.append(s)
                props.append(propagate_catalog_source(s, st.observation.timing.mid))
        return CatalogOverlay(
            dataset_id=self.dataset_id, frame_id=st.product.id, epoch=st.observation.timing.mid,
            catalog=self.catalog_name or "none", catalog_origin="simulated" if self.bundle.dataset.origin == "simulated" else "catalog",
            search_center=self.center, search_radius_deg=radius,
            padding_note="Search radius = field half-diagonal + 5\"/yr x max |observation - catalog epoch| + 2\" margin, so sources that move into the field are included.",
            sources=srcs, propagated=props,
            notes=["Propagated positions are model predictions (space motion + observer parallax at the frame epoch), not measurements."],
        )

    # ------------------------------------------------------------------ pixels / difference
    def _state(self, frame_id: str) -> FrameState:
        if frame_id in self.frames:
            return self.frames[frame_id]
        if frame_id.endswith(":registered"):
            native = frame_id[: -len(":registered")] + ":native"
            if native in self.frames:
                return self.frames[native]
        raise KeyError(frame_id)

    def pixels(self, frame_id: str, plane: str) -> tuple[np.ndarray, FrameProduct]:
        st = self._state(frame_id)
        if frame_id.endswith(":registered"):
            prod = st.registered_product
            assert prod is not None and st.registered_image is not None and st.coverage is not None
            if plane == "image":
                return st.registered_image, prod
            if plane == "mask":
                m = np.where(st.coverage & np.isfinite(st.registered_image), 0, 8).astype(np.uint16)
                return m, prod
            raise ValueError("registered products provide the 'image' and 'mask' planes only (display products)")
        arr = {"image": st.arrays.image, "variance": st.arrays.variance, "mask": st.arrays.mask}.get(plane)
        if arr is None:
            raise ValueError(f"unknown plane {plane!r}")
        return arr, st.product

    def difference(self, a: str, b: str) -> tuple[DifferenceInfo, np.ndarray | None]:
        sa, sb = self._state(a), self._state(b)
        ida, idb = f"{sa.observation.id}:registered", f"{sb.observation.id}:registered"
        reasons: list[str] = []
        same_band = sa.product.band_id == sb.product.band_id
        if not same_band:
            reasons.append(f"Different bands ({sa.product.band_id} vs {sb.product.band_id}): wavelength-incompatible.")
        if not (sa.registered_ok and sb.registered_ok):
            reasons.append("At least one frame failed registration.")
        if ida == idb:
            reasons.append("Frames A and B are the same frame.")
        both = np.isfinite(sa.registered_image) & np.isfinite(sb.registered_image)  # type: ignore[arg-type]
        overlap = float(np.mean(both))
        if overlap < 0.5:
            reasons.append(f"Common coverage {overlap:.0%} < 50%.")
        info = DifferenceInfo(
            frame_a=ida, frame_b=idb, compatible=not reasons, reasons=reasons,
            checks={
                "same_band": same_band, "both_registered": sa.registered_ok and sb.registered_ok, "overlap_fraction": overlap,
                "time_separation_days": abs(sb.mjd_tdb - sa.mjd_tdb), "fwhm_a_arcsec": sa.fwhm_arcsec, "fwhm_b_arcsec": sb.fwhm_arcsec,
                "registration_rms_a_mas": sa.registration.summary.rms_residual_mas or -1.0, "registration_rms_b_mas": sb.registration.summary.rms_residual_mas or -1.0,
            },
            label=(
                "Display-only difference preview (B - A) of reprojected frames in the same band. PSFs and backgrounds are not matched "
                "and noise is correlated by interpolation: residuals show where something changed, not their significance."
            ),
        )
        if reasons:
            return info, None
        return info, difference(sa.registered_image, sb.registered_image)  # type: ignore[arg-type]

    def frame_epoch_list(self) -> list[tuple[str, float]]:
        return [(fid, st.mjd_tdb) for fid, st in self.frames.items()]


MIN_VELOCITY_BASELINE_DAYS = 30.0


def _predict(links: list[tuple[float, float, float]], t: float) -> tuple[float, float, float]:
    """Linear prediction of (east, north) at t from the links, plus residual rms (mas).

    Until the links span MIN_VELOCITY_BASELINE_DAYS (e.g. only the two bands of
    one visit), no velocity is extrapolated: the prediction is their mean.
    """
    arr = np.array(links)
    if len(links) < 2 or np.ptp(arr[:, 0]) < MIN_VELOCITY_BASELINE_DAYS:
        return float(arr[:, 1].mean()), float(arr[:, 2].mean()), 0.0
    tt = (arr[:, 0] - arr[:, 0].mean()) / 365.25
    a = np.column_stack([np.ones_like(tt), tt])
    ce, *_ = np.linalg.lstsq(a, arr[:, 1], rcond=None)
    cn, *_ = np.linalg.lstsq(a, arr[:, 2], rcond=None)
    tq = (t - arr[:, 0].mean()) / 365.25
    rms = 0.0
    if len(links) > 2:
        re = arr[:, 1] - a @ ce
        rn = arr[:, 2] - a @ cn
        rms = float(np.sqrt(np.mean(re**2 + rn**2)))
    return float(ce[0] + ce[1] * tq), float(cn[0] + cn[1] * tq), rms


_cache: dict[tuple[str, int], Investigation] = {}
_cache_lock = threading.Lock()
_build_locks: dict[tuple[str, int], threading.Lock] = {}


def get_investigation(dataset_id: str, seed: int | None = None) -> Investigation:
    """Build (once) and return the investigation for a dataset; thread-safe."""
    from skyshift.providers.registry import load_dataset
    from skyshift.synthetic.generator import DEFAULT_SEED

    from skyshift.providers.registry import dataset_provider

    if dataset_provider(dataset_id) != "synthetic":
        raise ValueError(f"{dataset_id} is an observed dataset; the synthetic investigation pipeline is never run on archive data")
    key = (dataset_id, DEFAULT_SEED if seed is None else int(seed))
    with _cache_lock:
        if key in _cache:
            return _cache[key]
        lock = _build_locks.setdefault(key, threading.Lock())
    with lock:
        with _cache_lock:
            if key in _cache:
                return _cache[key]
        inv = Investigation(load_dataset(dataset_id, key[1]))
        with _cache_lock:
            _cache[key] = inv
        return inv

