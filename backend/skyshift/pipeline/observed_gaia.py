"""Gaia DR3 predictions and alignment diagnostics for an observed SPHEREx dataset.

Inputs: the dataset bundle (native arrays + the validated SpectralImage of each
native frame) and the recorded Gaia DR3 response for the same field. Nothing
here queries an archive. Outputs are contracts with explicit origins:

  * GaiaPrediction / PropagatedParameters - 'model_prediction' (catalogue values
    propagated to the exposure mid-time; observer parallax applied once; no
    aberration, no light deflection, matching the archive WCS convention);
  * ReferenceStarResidual - 'derived_measurement' (ePSF positions measured by
    SkyShift on the native arrays, minus the predictions);
  * CatalogSource - 'catalog' (values as published).

A Gaia source without a counterpart in an image is reported as such; it is
never a discovery. Photometry, target motion fits and difference imaging are
not derived here.
"""

from __future__ import annotations

import math
import threading

import astropy.units as u
import numpy as np
from astropy.coordinates import get_body_barycentric_posvel, solar_system_ephemeris
from astropy.time import Time

from skyshift._astropy_config import SOLAR_SYSTEM_EPHEMERIS
from skyshift.contracts import (
    AlignmentReport,
    ConventionAspect,
    ConventionTest,
    DetectorFrameOffsets,
    Epoch,
    ErrorBudgetTerm,
    EstimatorValidation,
    FrameAlignment,
    GaiaFrameOverlay,
    GaiaPrediction,
    GaiaSourceDetail,
    InjectionSummary,
    Observation,
    RadialInjectionBin,
    PredictionConvention,
    PropagatedParameters,
    Provenance,
    ReferenceStarResidual,
    ReportCache,
    ResidualStatistics,
    SharedSystematics,
    TranslationEvaluation,
    UncertaintyTerm,
)
from skyshift.coords.observer import AU_KM, observer_barycentric_au
from skyshift.coords.time import make_epoch
from skyshift.coords.wcs import description_to_wcs, sky_to_pixel
from skyshift.providers.base import DatasetBundle
from skyshift.providers.gaia_dr3 import RecordedField
from skyshift.providers.gaia_dr3 import reference as gref
from skyshift.providers.gaia_dr3.rows import gaia_row_to_catalog_source
from skyshift.providers.spherex import reference as sref
from skyshift.providers.spherex.http import utc_now
from skyshift.science.alignment import (
    ALIGNMENT_METHOD_VERSION,
    REASONS,
    AlignmentConfig,
    CatalogInputs,
    FrameDiagnosis,
    FrameInputs,
    aberration_displacement_arcsec,
    convention_test,
    diagnose_frame,
    evaluate_translation,
    injection_near_saturated,
    injection_recovery,
    residual_statistics,
    shared_systematics,
)
from skyshift.science.epoch_propagation import (
    AU_MAS_YR_KM_S,
    EPOCH_PROPAGATION_VERSION,
    RV_BOUND_KM_S,
    UNKNOWN_RV_SIGMA_KM_S,
    AstrometricArrays,
    ObservedPrediction,
    predict_observed,
)

CONVENTION_EVIDENCE_DOC = [
    "SPHEREx ES v2.1 Sect. 3.2.8: the fine-astrometry WCS is fitted (scamp) so that detected stars align with the Reference Catalog; "
    "Gaia DR3 is the astrometric reference and 'Proper motions provided by Gaia are used to propagate stellar positions to the current observation epoch'.",
    "SPHEREx ES v2.1 Table 17: input 'Proper-motion-corrected Gaia reference catalog'. No aberration, parallax, light-deflection or "
    "apparent-place step is described anywhere in the Supplement (searched 2026-11-14).",
    "Consequence: the archive WCS maps pixels to catalogue-frame (ICRS, Gaia) directions at the exposure epoch; the common stellar aberration "
    "(annual + orbital, up to ~26\") is absorbed by the fitted pointing, so SkyShift does not apply aberration to its predictions (applying it "
    "would displace every prediction by that amount).",
]


def _flt(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class ObservedGaia:
    """Gaia DR3 predictions and alignment diagnostics for one observed dataset (cached per process)."""

    def __init__(self, bundle: DatasetBundle, recorded: RecordedField, cfg: AlignmentConfig | None = None) -> None:
        if bundle.dataset.origin != "observed":
            raise ValueError("Gaia predictions on images are computed for observed datasets only")
        self.bundle = bundle
        self.dataset = bundle.dataset
        self.recorded = recorded
        self.cfg = cfg or AlignmentConfig()
        self.images = dict(bundle.extras.get("spectral_images", {}))  # type: ignore[arg-type]
        cat = recorded.catalog
        self.catalog = cat
        self.ref_epoch = make_epoch(gref.REFERENCE_EPOCH_JYEAR, "jyear", gref.REFERENCE_EPOCH_SCALE)
        self.astro = AstrometricArrays.from_columns(cat.columns, self.ref_epoch.mjd_tdb)
        self.obs_by_native: dict[str, Observation] = {}
        self.native_of: dict[str, str] = {}
        for o in self.dataset.observations:
            nat = next((f for f in o.frame_ids if f.endswith(":native")), None)
            if nat is None:
                continue
            self.obs_by_native[nat] = o
            for f in o.frame_ids:
                self.native_of[f] = nat
        self.grid_wcs = description_to_wcs(self.dataset.common_grid)
        self._lock = threading.RLock()
        self._pred: dict[str, ObservedPrediction] = {}
        self._diag: dict[str, tuple[FrameDiagnosis, dict]] = {}
        self._report: AlignmentReport | None = None

    # ------------------------------------------------------------------ predictions

    def native_frame_id(self, frame_id: str) -> str:
        if frame_id not in self.native_of:
            raise KeyError(f"unknown frame {frame_id!r}")
        return self.native_of[frame_id]

    def epoch_of(self, native_id: str) -> Epoch:
        return self.obs_by_native[native_id].timing.mid

    def prediction(self, native_id: str) -> ObservedPrediction:
        with self._lock:
            if native_id not in self._pred:
                mid = self.epoch_of(native_id)
                b = observer_barycentric_au(np.array([mid.mjd_tdb]))[0]
                self._pred[native_id] = predict_observed(self.astro, mid.mjd_tdb, b, unknown_rv_sigma_km_s=UNKNOWN_RV_SIGMA_KM_S)
            return self._pred[native_id]

    def _frame_inputs(self, native_id: str) -> FrameInputs:
        img = self.images[native_id]
        if img.epsf_library is None:
            raise ValueError(f"{native_id}: EPSF table unreadable")
        w = img.wcs

        def s2p(ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            xy = w.all_world2pix(np.column_stack([np.atleast_1d(ra), np.atleast_1d(dec)]), 0, tolerance=1e-9, maxiter=60, quiet=True)
            return xy[:, 0], xy[:, 1]

        def p2s(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            rd = w.all_pix2world(np.column_stack([np.atleast_1d(x), np.atleast_1d(y)]), 0)
            return rd[:, 0], rd[:, 1]

        return FrameInputs(
            frame_id=native_id, image=img.image, variance=img.variance, flags=img.flags,
            flag_masks={d.name: d.mask_value for d in img.flag_defs}, sky_to_pixel=s2p, pixel_to_sky=p2s,
            pixel_scale_arcsec=float(math.sqrt(abs(np.linalg.det(w.pixel_scale_matrix))) * 3600.0),
            detector_offset=img.detector_offset() or (0.0, 0.0), epsf=img.epsf_library,
        )

    def _catalog_inputs(self, pred: ObservedPrediction) -> CatalogInputs:
        c = self.catalog.columns
        return CatalogInputs(
            source_id=self.catalog.source_id, ra_deg=pred.ra_deg, dec_deg=pred.dec_deg,
            sigma_east_mas=pred.sigma_ra_cosdec_mas, sigma_north_mas=pred.sigma_dec_mas,
            g_mag=c["phot_g_mean_mag"], rp_mag=c["phot_rp_mean_mag"], params_solved=c["astrometric_params_solved"], ruwe=c["ruwe"],
            duplicated=np.asarray(c["duplicated_source"], dtype=bool), ipd_multi_peak=c["ipd_frac_multi_peak"], non_single_star=c["non_single_star"],
        )

    def diagnosis(self, native_id: str) -> tuple[FrameDiagnosis, dict]:
        with self._lock:
            if native_id not in self._diag:
                fi = self._frame_inputs(native_id)
                ci = self._catalog_inputs(self.prediction(native_id))
                diag = diagnose_frame(fi, ci, self.cfg)
                inj = injection_recovery(fi, ci, diag, self.cfg)
                inj["near_saturated"] = injection_near_saturated(fi, ci, diag, self.cfg)
                self._diag[native_id] = (diag, inj)
            return self._diag[native_id]

    def _service_notes(self) -> list[str]:
        """Which TAP service served the recorded response, and how a partner service was verified (never silent)."""
        s = self.recorded.manifest.get("service") or {}
        if not s or s.get("archive_of_record", True):
            return []
        v = s.get("verification") or {}
        c = s.get("crosscheck") or {}
        note = (f"Recorded from {s.get('name')} ({s.get('endpoint')}), a Gaia partner data centre, because the ESA archive was unreachable. "
                f"Verification {v.get('status')}: the ESA-recorded {v.get('reference_field')} query returned identical rows, values and NULLs "
                f"({(v.get('comparison') or {}).get('n_rows_other')} rows x {(v.get('comparison') or {}).get('n_columns_compared')} columns).")
        if c:
            note += f" Cross-check {c.get('status')}: {c.get('name')} returned an identical field response."
        return [note]

    def _source_flags(self, i: int, pred: ObservedPrediction) -> list[str]:
        c = self.catalog.columns
        flags: list[str] = []
        if not pred.propagation.propagated[i]:
            flags.append("NO_PROPER_MOTION")
        else:
            flags.append("RV_USED" if not pred.propagation.rv_assumed[i] else "RV_ASSUMED_ZERO")
            plx, sp = c["parallax"][i], c["parallax_error"][i]
            if not (np.isfinite(plx) and np.isfinite(sp) and sp > 0 and plx / sp >= 5.0):
                flags.append("PARALLAX_NOT_SIGNIFICANT")
            if math.hypot(c["pmra"][i], c["pmdec"][i]) >= 1000.0:
                flags.append("HIGH_PROPER_MOTION")
        if np.isfinite(c["ruwe"][i]) and c["ruwe"][i] > gref.RUWE_THRESHOLD:
            flags.append("RUWE_HIGH")
        if bool(c["duplicated_source"][i]):
            flags.append("DUPLICATED_SOURCE")
        return flags

    def overlay(self, frame_id: str) -> GaiaFrameOverlay:
        native_id = self.native_frame_id(frame_id)
        report = self.report()  # the convention status depends on the field-wide test; computed once (disk-cached)
        fa = self._frame_report(native_id)
        obs = self.obs_by_native[native_id]
        pred = self.prediction(native_id)
        fi = self._frame_inputs(native_id)
        xs, ys = fi.sky_to_pixel(pred.ra_deg, pred.dec_deg)
        ny, nx = fi.image.shape
        margin = 2.0
        inside = (xs >= -0.5) & (xs <= nx - 0.5) & (ys >= -0.5) & (ys <= ny - 0.5)
        near = (xs >= -margin - 0.5) & (xs <= nx - 0.5 + margin) & (ys >= -margin - 0.5) & (ys <= ny - 0.5 + margin)
        gx, gy = sky_to_pixel(self.grid_wcs, pred.ra_deg[near], pred.dec_deg[near])
        role = {r.source_id: r for r in fa.residuals} if fa else {}
        saturated = set(fa.saturated_source_ids) if fa else set()
        c = self.catalog.columns
        preds: list[GaiaPrediction] = []
        for k, i in enumerate(np.flatnonzero(near)):
            sid = self.catalog.source_id[i]
            r = role.get(sid)
            preds.append(GaiaPrediction(
                source_id=self.catalog.source_id[i], ra_deg=float(pred.ra_deg[i]) % 360.0, dec_deg=float(pred.dec_deg[i]),
                sigma_ra_cosdec_mas=_flt(pred.sigma_ra_cosdec_mas[i]), sigma_dec_mas=_flt(pred.sigma_dec_mas[i]), corr_ra_dec=_flt(pred.corr_ra_dec[i]),
                x_native=float(xs[i]), y_native=float(ys[i]), x_display=_flt(gx[k]), y_display=_flt(gy[k]),
                in_native=bool(inside[i]), g_mag=_flt(c["phot_g_mean_mag"][i]), bp_rp=_flt(c["bp_rp"][i]),
                solution=gref.SOLUTION_BY_PARAMS.get(int(c["astrometric_params_solved"][i]), "unknown") if np.isfinite(c["astrometric_params_solved"][i]) else "unknown",  # type: ignore[arg-type]
                flags=self._source_flags(int(i), pred) + (["SATURATED_IN_FRAME"] if sid in saturated else []),
                reference_status=r.status if r is not None else "not_candidate",
                reference_reason=r.reason if r is not None and r.status == "rejected" else None,
            ))
        m = self.recorded.manifest
        return GaiaFrameOverlay(
            dataset_id=self.dataset.id, frame_id=frame_id, native_frame_id=native_id, observation_id=obs.id, epoch=obs.timing.mid,
            catalog=gref.GAIA_TABLE, release=m["release"], retrieved_utc=m["retrieved_utc"], adql=m["field_query"]["adql"],
            n_catalog_rows=len(self.catalog), n_in_frame=int(inside.sum()), predictions=preds, convention=report.convention,
            label=f"Gaia DR3 predictions at {obs.timing.mid.iso_utc[:19]} UTC (model; archive-WCS frame)",
            notes=[
                "Positions are catalogue predictions (propagated from J2016.0 TCB to the exposure mid-time), not image measurements.",
                "Markers are placed through the archive WCS; its documented accuracy (RMS < 0.3\") dominates the placement uncertainty.",
                "A prediction without a visible counterpart is not evidence of a new or vanished object (depth, blending, flags).",
                gref.ACKNOWLEDGEMENT,
            ] + self._service_notes(),
            provenance=Provenance(origin="model_prediction", provider="skyshift", dataset_id=self.dataset.id, release=gref.GAIA_RELEASE,
                                  source_url=m.get("endpoint", gref.TAP_SYNC_URL), retrieved_utc=m["retrieved_utc"],
                                  method="skyshift.science.epoch_propagation.predict_observed", method_version=EPOCH_PROPAGATION_VERSION,
                                  parents=[f"{gref.GAIA_TABLE} (fixtures/gaia_dr3/{self.recorded.field_id})", native_id]),
        )

    # ------------------------------------------------------------------ source detail

    def source_detail(self, frame_id: str, source_id: str) -> GaiaSourceDetail:
        native_id = self.native_frame_id(frame_id)
        if source_id not in self.catalog.index:
            raise KeyError(f"Gaia source {source_id} is not in the recorded field response")
        i = self.catalog.index[source_id]
        m = self.recorded.manifest
        src = gaia_row_to_catalog_source(self.catalog.row(i), retrieved_utc=m["retrieved_utc"], source_url=m.get("endpoint", gref.TAP_SYNC_URL))
        ov = self.overlay(frame_id)
        prediction = next((p for p in ov.predictions if p.source_id == source_id), None)
        pred = self.prediction(native_id)
        prop = pred.propagation
        epoch = self.epoch_of(native_id)
        sig = {}
        for k, name in enumerate(("ra_cosdec", "dec", "parallax", "pmra", "pmdec", "mu_r")):
            v = prop.cov6[i, k, k]
            if np.isfinite(v) and v > 0:
                sig[name] = float(math.sqrt(v))
        sig["ra_cosdec"] = float(pred.sigma_ra_cosdec_mas[i])
        sig["dec"] = float(pred.sigma_dec_mas[i])
        propagated = PropagatedParameters(
            epoch=epoch, ra_deg=float(pred.ra_deg[i]) % 360.0, dec_deg=float(pred.dec_deg[i]),
            parallax_mas=_flt(prop.parallax_mas[i]), pmra_mas_yr=_flt(prop.pmra_mas_yr[i]), pmdec_mas_yr=_flt(prop.pmdec_mas_yr[i]),
            mu_r_mas_yr=_flt(prop.mu_r_mas_yr[i]), sigmas=sig, corr_ra_dec=_flt(pred.corr_ra_dec[i]),
            observer_parallax_offset_mas=(float(pred.parallax_offset_mas[i, 0]), float(pred.parallax_offset_mas[i, 1])),
            radial_velocity_used_km_s=float(prop.rv_used_km_s[i]), radial_velocity_assumed=bool(prop.rv_assumed[i]),
            perspective_bound_mas=float(prop.perspective_bound_mas[i]),
            method=(f"Uniform space motion (Gaia DR3 doc. Sect. 4.1.7 / ESA 1997) from J2016.0 TCB over {prop.dt_yr:.4f} yr, 6x6 covariance; "
                    "observer parallax for the geocentre (ERFA epv00) applied once; no aberration, no light deflection."),
        ) if prop.propagated[i] else None
        fa = self._frame_report(native_id)
        meas = next((r for r in fa.residuals if r.source_id == source_id), None) if fa else None
        return GaiaSourceDetail(dataset_id=self.dataset.id, frame_id=frame_id, source=src, prediction=prediction, propagated=propagated,
                                measurement=meas, limitations=self._limitations(i, pred))

    def _limitations(self, i: int, pred: ObservedPrediction) -> list[str]:
        c = self.catalog.columns
        prop = pred.propagation
        out = []
        if not prop.propagated[i]:
            out.append("2-parameter solution: no parallax or proper motion, so the position is shown at J2016.0 and its position at this epoch is unknown "
                       "(about 10 years of unknown motion). The source is never used as a reference.")
        else:
            if prop.rv_assumed[i]:
                out.append(f"No catalogued radial velocity: perspective acceleration neglected (v_r = 0); bound {prop.perspective_bound_mas[i]:.2g} mas for |v_r| <= {RV_BOUND_KM_S:g} km/s; "
                           f"the covariance includes an assumed {UNKNOWN_RV_SIGMA_KM_S:g} km/s dispersion.")
            else:
                out.append(f"Gaia radial velocity {c['radial_velocity'][i]:.2f} km/s used for the perspective term (published value; the DR3 faint-star "
                           "RV correction is not applied, which changes predicted positions by far less than 1 mas here).")
            plx, sp = c["parallax"][i], c["parallax_error"][i]
            if not (np.isfinite(plx) and sp > 0 and plx / sp >= 5.0):
                out.append(f"Parallax {plx:.3f} +/- {sp:.3f} mas is not significant: used only as a statistical value in the parallax term, never inverted into a distance.")
        if np.isfinite(c["ruwe"][i]) and c["ruwe"][i] > gref.RUWE_THRESHOLD:
            out.append(f"RUWE {c['ruwe'][i]:.2f} > {gref.RUWE_THRESHOLD}: poor single-star fit (possible binary); predictions may be off by more than the formal errors.")
        out.append("Placement in the image uses the archive WCS (documented RMS < 0.3\"); the catalogue uncertainty above is usually much smaller.")
        out.append("Aberration and light deflection are not applied: the archive WCS is fitted to catalogue-frame Gaia positions (see the convention).")
        return out

    # ------------------------------------------------------------------ alignment report

    def _residual_contract(self, native_id: str, r) -> ReferenceStarResidual:  # noqa: ANN001
        g = self.catalog.columns["phot_g_mean_mag"][r.index]
        return ReferenceStarResidual(
            source_id=self.catalog.source_id[r.index], frame_id=native_id, status=r.status, reason=r.reason, reason_text=REASONS.get(r.reason) if r.reason else None,
            detail=r.detail, g_mag=_flt(g), predicted_x=r.x_pred, predicted_y=r.y_pred, measured_x=r.x, measured_y=r.y, sigma_x_px=r.sigma_x, sigma_y_px=r.sigma_y,
            snr=r.snr, chi2_red=r.chi2_red, n_masked=r.n_masked, epsf_zone=r.zone, dist_saturated_px=r.dist_saturated_px,
            residual_east_arcsec=r.d_east_arcsec, residual_north_arcsec=r.d_north_arcsec, sigma_east_arcsec=r.s_east_arcsec, sigma_north_arcsec=r.s_north_arcsec,
        )

    def _observer_velocity_km_s(self, native_id: str) -> np.ndarray:
        mid = self.epoch_of(native_id)
        with solar_system_ephemeris.set(SOLAR_SYSTEM_EPHEMERIS):
            _, vel = get_body_barycentric_posvel("earth", Time(mid.mjd_tdb, format="mjd", scale="tdb"))
        v = vel.xyz.to_value(u.km / u.s)
        img = self.images.get(native_id)
        if img is not None and all(k in img.image_header for k in ("VX_SC", "VY_SC", "VZ_SC")):
            v = v + np.array([float(img.image_header[k]) for k in ("VX_SC", "VY_SC", "VZ_SC")])
        return np.asarray(v, dtype=float)

    def frame_alignment(self, native_id: str) -> FrameAlignment:
        obs = self.obs_by_native[native_id]
        diag, inj = self.diagnosis(native_id)
        used = diag.used
        e = np.array([r.d_east_arcsec for r in used], dtype=float)
        n = np.array([r.d_north_arcsec for r in used], dtype=float)
        se = np.array([r.s_east_arcsec for r in used], dtype=float)
        sn = np.array([r.s_north_arcsec for r in used], dtype=float)
        st = residual_statistics(e, n, se, sn)
        fi = self._frame_inputs(native_id)
        shared = shared_systematics(fi, used, self.cfg) if used else None
        tr = evaluate_translation(e, n, se, sn, min_refs=self.cfg.min_references, shared_sigma_arcsec=shared["total_arcsec"] if shared else 0.0)
        if shared and shared["missing_terms"] and tr["evaluated"]:
            tr["decision"] += " Shared terms not estimated for this frame (the significance is then optimistic): " + "; ".join(shared["missing_terms"]) + "."
        off_px = off_sig = None
        if len(used) >= 2 and st.get("wse_east_arcsec"):
            J = self._sky_jacobian(native_id)
            Ji = np.linalg.inv(J)
            d = Ji @ np.array([st["wmean_east_arcsec"], st["wmean_north_arcsec"]])
            c = Ji @ np.diag([st["wse_east_arcsec"] ** 2, st["wse_north_arcsec"] ** 2]) @ Ji.T
            off_px, off_sig = (float(d[0]), float(d[1])), (float(math.sqrt(c[0, 0])), float(math.sqrt(c[1, 1])))
        est = EstimatorValidation(
            method="Injection-recovery of ePSF point sources in this frame's real pixels (seeded by the frame id), refitted with the same estimator",
            passed=bool(inj["passed"]), criteria=inj["criteria"], pixel_noise_median=_flt(inj.get("pixel_noise_median")),
            per_target=[InjectionSummary(**{k: v for k, v in t.items()}) for t in inj["per_target"]],
            near_saturated=[RadialInjectionBin(**b) for b in inj.get("near_saturated", [])],
        )
        if len(used) < self.cfg.min_references:
            status, reason = "insufficient_reference_stars", (
                f"{len(used)} usable reference star(s); {self.cfg.min_references} are needed for frame statistics and the translation test.")
        elif not est.passed:
            status, reason = "estimator_not_validated", "The injection-recovery validation of the position estimator did not pass in this frame."
        else:
            status, reason = "ok", f"{len(used)} reference stars; estimator validated by injection-recovery."
        mid = obs.timing.mid
        centre = self.dataset.field.center
        ab = aberration_displacement_arcsec(centre.ra_deg, centre.dec_deg, self._observer_velocity_km_s(native_id))
        return FrameAlignment(
            frame_id=native_id, observation_id=obs.id, band_id=obs.band_id, detector=int(obs.archive.detector) if obs.archive else 0, epoch=mid,
            status=status, status_reason=reason, n_in_frame=diag.n_in_frame, n_used=len(used),
            n_fainter_than_limit=sum(1 for r in diag.results if r.reason == "too_faint"),
            n_candidates=sum(1 for r in diag.results if r.reason != "too_faint"),
            n_rejected=sum(1 for r in diag.results if r.status == "rejected" and r.reason != "too_faint"),
            rejected_by_reason={k: v for k, v in diag.rejected_counts().items() if k != "too_faint"},
            statistics=ResidualStatistics(**st) if st.get("n") else ResidualStatistics(n=0),
            translation=TranslationEvaluation(**tr), estimator=est, aberration_if_apparent_arcsec=ab,
            shared=SharedSystematics(**shared) if shared else None, offset_detector_px=off_px, offset_detector_sigma_px=off_sig,
            saturated_source_ids=[self.catalog.source_id[i] for i in diag.saturated],
            residuals=[self._residual_contract(native_id, r) for r in diag.results if r.reason != "too_faint"],
        )

    def _sky_jacobian(self, native_id: str) -> np.ndarray:
        """d(east, north arcsec)/d(x, y px) at the field centre of this native frame (full WCS incl. SIP)."""
        from skyshift.science.alignment import local_wcs_jacobian

        fi = self._frame_inputs(native_id)
        c = self.dataset.field.center
        x, y = fi.sky_to_pixel(np.array([c.ra_deg]), np.array([c.dec_deg]))
        return local_wcs_jacobian(fi.pixel_to_sky, float(x[0]), float(y[0]), c.ra_deg, c.dec_deg)

    def _frame_report(self, native_id: str) -> FrameAlignment | None:
        return next((f for f in self.report().frames if f.frame_id == native_id), None)

    def cache_key(self) -> str:
        """Hash of every input of the report: catalogue response, science arrays, configuration and the code."""
        import dataclasses
        import hashlib
        import inspect
        import json

        from skyshift.imaging import epsf
        from skyshift.science import alignment, epoch_propagation

        h = hashlib.sha256()
        h.update(json.dumps({
            "gaia": self.recorded.manifest["field_query"]["response_sha256_gz"],
            "frames": sorted((nid, img.sha256) for nid, img in self.images.items()),
            "cfg": dataclasses.asdict(self.cfg),
        }, sort_keys=True).encode())
        for mod in (alignment, epsf, epoch_propagation):
            h.update(inspect.getsource(mod).encode())
        h.update(inspect.getsource(ObservedGaia).encode())
        return h.hexdigest()[:24]

    def _cache_path(self):  # noqa: ANN202
        from skyshift.providers.spherex.paths import cache_root

        return cache_root().parent / "alignment" / self.dataset.id / f"report-{self.cache_key()}.json"

    def cached_report(self) -> AlignmentReport | None:
        """The report if already computed in this process or present in the disk cache under the current key (never computes)."""
        with self._lock:
            if self._report is not None:
                return self._report
            path = self._cache_path()
            if not path.exists():
                return None
            try:
                cached = AlignmentReport.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                path.unlink(missing_ok=True)  # unreadable: recomputed on the next report()
                return None
            if cached.cache is None or cached.cache.key != self.cache_key():
                return None  # written by other inputs or code: never served
            self._report = cached.model_copy(update={"cache": cached.cache.model_copy(update={"served_from_cache": True})})
            return self._report

    def report(self) -> AlignmentReport:
        with self._lock:
            if self.cached_report() is not None:
                return self._report  # type: ignore[return-value]
            path = self._cache_path()
            self._report = self.compute_report()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self._report.model_dump_json(), encoding="utf-8")
            except OSError:
                pass  # the cache is an optimisation only
            return self._report

    def compute_report(self) -> AlignmentReport:
        """Compute the report from the pixels and the catalogue (no cache)."""
        with self._lock:
            frames = [self.frame_alignment(nid) for nid in self.obs_by_native if nid in self.images]
            ok = [f for f in frames if f.status == "ok"]
            offsets, abers = [], []
            for f in ok:
                s = f.statistics
                if s and s.n >= self.cfg.min_references and s.wse_east_arcsec:
                    sh = f.shared.total_arcsec if f.shared else 0.0
                    offsets.append((s.wmean_east_arcsec, s.wmean_north_arcsec, math.hypot(s.wse_east_arcsec, sh), math.hypot(s.wse_north_arcsec, sh)))
                    abers.append(f.aberration_if_apparent_arcsec)
            ct = convention_test(offsets, abers)
            allres = [r for f in ok for r in f.residuals if r.status == "used"]
            pooled = residual_statistics(
                np.array([r.residual_east_arcsec for r in allres]), np.array([r.residual_north_arcsec for r in allres]),
                np.array([r.sigma_east_arcsec for r in allres]), np.array([r.sigma_north_arcsec for r in allres]),
            ) if allres else {"n": 0}
            n_ins = sum(1 for f in frames if f.status == "insufficient_reference_stars")
            n_nv = sum(1 for f in frames if f.status == "estimator_not_validated")
            convention = self.convention(ct)
            available = convention.status in ("resolved", "partially_resolved") and bool(ok)
            budget, det_off, reassess = self._budget(frames, ok)
            per_frame = [f.n_used for f in frames]
            assessment = (
                f"{len(ok)} of {len(frames)} frames have >= {self.cfg.min_references} usable reference stars with a validated estimator "
                f"(per frame {min(per_frame) if per_frame else 0}-{max(per_frame) if per_frame else 0}, median {int(np.median(per_frame)) if per_frame else 0}). "
                "This supports per-frame residual statistics and a constant-offset (translation) check; it is not enough for rotation, scale or "
                "distortion terms, which are therefore not estimated."
                + (f" {n_ins} frame(s) have too few references (reported, not used for conclusions)." if n_ins else "")
            )
            m = self.recorded.manifest
            return AlignmentReport(
                dataset_id=self.dataset.id, catalog=gref.GAIA_TABLE, release=m["release"], method="skyshift.science.alignment.diagnose_frame",
                method_version=f"alignment {ALIGNMENT_METHOD_VERSION}; propagation {EPOCH_PROPAGATION_VERSION}",
                status="available" if available else "unavailable",
                status_reason=(("Archive-WCS convention partially resolved: the data reject the full-aberration (apparent-place) hypothesis. "
                                "Calibrator parallax (<= 2.6 mas), light deflection (~4 mas) and time scale are bounded far below the residual scatter; "
                                "the undocumented centroid definition (<= 0.25\", comparable to the scatter) is carried as a shared term in every frame "
                                "offset's uncertainty (see the convention aspects). Residuals computed on frames with enough validated references.")
                               if available else "Quantitative alignment results withheld: " + ("WCS convention not resolved." if convention.status == "approximate" else "no frame passed.")),
                convention=convention, convention_test=ConventionTest(**ct), selection_criteria=self.cfg.criteria(), reason_texts=REASONS,
                frames=frames, pooled=ResidualStatistics(**pooled), n_frames_ok=len(ok), n_frames_insufficient=n_ins, n_frames_not_validated=n_nv,
                pooled_over=(f"references of the {len(ok)} frames with status 'ok' (>= {self.cfg.min_references} references, estimator validated); "
                             "per-frame offsets are not removed"),
                uncertainty_budget=budget, detector_frame_offsets=det_off, reassessment=reassess,
                cache=ReportCache(key=self.cache_key(), computed_utc=utc_now(), served_from_cache=False, inputs=self._cache_inputs()),
                field_assessment=assessment,
                limitations=[
                    "Residuals describe the archive WCS together with SkyShift's ePSF position estimator and the Gaia predictions; they are not corrected here.",
                    "Isolation uses Gaia G/RP as the flux proxy; sources bright in the infrared but faint or absent in Gaia can still contaminate a reference.",
                    "The isolation rule (2 px, 10 %) admits neighbours that shift a 7x7 ePSF fit: simulated from each reference's catalogued Gaia neighbours "
                    "(validation/estimator_review.json) the shift is typically < 0.01 px but reaches several hundredths of a pixel for some references; it is "
                    "part of the star-to-star scatter and is not corrected.",
                    "The ePSF of the zone containing each star is used without interpolation between zones. On D1-D4 references fit with chi2_red ~ 6-50, rising "
                    "with brightness. A brightness-independent part comes from structure fixed on the sky (faint sources, background) that VARIANCE does "
                    "not describe: high-pass pixels correlate between epochs on D1-D4, not on D5-D6. The stacked residual is flat to ~1 % of the flux per "
                    "pixel, so the brightness-dependent part is a star-to-star misfit of unresolved cause, not an average shape error. Uncertainties are "
                    "inflated by sqrt(chi2_red) and a shared PSF-mismatch term enters each frame offset.",
                    "A detector-fixed offset of ~+0.015 px in detector x appears in 14 of 15 frames; it is of the size of the difference between the ePSF "
                    "reference point and centroid-type estimators (pipeline centroid convention undocumented) and is not removed.",
                    "A translation is the only correction model evaluated; with 5-15 references per 6' cutout, rotation/scale/distortion are not constrained.",
                    "Photometry, target motion fits and difference imaging remain unavailable for SPHEREx data.",
                ],
                provenance=Provenance(origin="derived_measurement", provider="skyshift", dataset_id=self.dataset.id, release=gref.GAIA_RELEASE,
                                      retrieved_utc=m["retrieved_utc"], method="skyshift.pipeline.observed_gaia.ObservedGaia.report",
                                      method_version=ALIGNMENT_METHOD_VERSION, parents=[f"fixtures/gaia_dr3/{self.recorded.field_id}/manifest.json"]),
            )

    def _cache_inputs(self) -> dict[str, str]:
        import hashlib

        h = hashlib.sha256("".join(sorted(img.sha256 for img in self.images.values())).encode()).hexdigest()[:16]
        return {"gaia_response_sha256_gz": self.recorded.manifest["field_query"]["response_sha256_gz"],
                "gaia_retrieved_utc": self.recorded.manifest["retrieved_utc"], "spherex_cutouts_sha256_combined": h,
                "n_frames": str(len(self.images)), "method_version": ALIGNMENT_METHOD_VERSION}

    def _budget(self, frames: list[FrameAlignment], ok: list[FrameAlignment]) -> tuple[list[UncertaintyTerm], DetectorFrameOffsets | None, str]:
        used = [(f, r) for f in ok for r in f.residuals if r.status == "used"]
        scale = float(self.dataset.instrument.pixel_scale_arcsec or 6.15)
        cen = [math.sqrt(0.5 * (r.sigma_x_px**2 + r.sigma_y_px**2)) * scale for _, r in used if r.sigma_x_px is not None]
        gaia = []
        for f in ok:
            pred = self.prediction(f.frame_id)
            for r in f.residuals:
                if r.status == "used" and r.source_id in self.catalog.index:
                    i = self.catalog.index[r.source_id]
                    gaia.append(math.sqrt(0.5 * (pred.sigma_ra_cosdec_mas[i] ** 2 + pred.sigma_dec_mas[i] ** 2)) / 1000.0)
        xs = [f.statistics.extra_scatter_arcsec for f in ok if f.statistics and f.statistics.extra_scatter_arcsec is not None]
        psf = [f.shared.psf_mismatch_arcsec for f in ok if f.shared and f.shared.psf_mismatch_arcsec is not None]
        conv = [f.shared.convention_arcsec for f in ok if f.shared]

        def rng_of(v: list[float]) -> tuple[float, float] | None:
            return (float(np.min(v)), float(np.max(v))) if v else None

        def med(v: list[float]) -> float | None:
            return float(np.median(v)) if v else None

        budget = [
            UncertaintyTerm(term="ePSF centroid (fit sigma x sqrt(chi2_red) when > 1)", kind="random_per_star", typical_arcsec=med(cen), range_arcsec=rng_of(cen),
                            enters_as="per star; the frame offset's random part shrinks as 1/sqrt(N)", source="fit covariance; calibrated by injection (pulls 0.5-1.4)"),
            UncertaintyTerm(term="Gaia DR3 prediction (propagated 6x6 covariance + parallax term)", kind="random_per_star", typical_arcsec=med(gaia), range_arcsec=rng_of(gaia),
                            enters_as="per star", source="Gaia DR3 errors and correlations propagated to the exposure"),
            UncertaintyTerm(term="Unexplained star-to-star scatter (Paule-Mandel extra scatter)", kind="unexplained_per_star", typical_arcsec=med(xs), range_arcsec=rng_of(xs),
                            enters_as="added in quadrature per star (assumed independent between stars)", source="residuals about the weighted mean"),
            UncertaintyTerm(term="PSF-model mismatch common to the frame (half the zone-swap shift RMS)", kind="shared_per_frame", typical_arcsec=med(psf), range_arcsec=rng_of(psf),
                            enters_as="added to the frame-offset uncertainty without 1/sqrt(N)", source="refits of every reference with adjacent-zone ePSFs"),
            UncertaintyTerm(term="Centroid convention (ePSF reference point vs windowed / barycentre centroids)", kind="shared_per_frame", typical_arcsec=med(conv), range_arcsec=rng_of(conv),
                            enters_as="added to the frame-offset uncertainty without 1/sqrt(N)", source="computed from the frame's ePSFs only (Gaia-free); pipeline centroid definition undocumented"),
            UncertaintyTerm(term="Gaia DR3 reference-frame / magnitude systematics", kind="shared_all_frames", typical_arcsec=2e-5,
                            enters_as="added to the frame-offset uncertainty", source="Gaia EDR3/DR3 frame alignment ~0.02 mas"),
            UncertaintyTerm(term="Parallax convention of the pipeline's calibrators (undocumented)", kind="shared_all_frames", typical_arcsec=None,
                            range_arcsec=(0.0, next((t.bound_arcsec for t in self.convention().error_budget if t.term.startswith("Parallax treatment")), 0.0026) or 0.0026),
                            enters_as="bound only (not added): far below the shared terms above", source="99th-percentile calibrator parallax in the field"),
        ]
        rows = [f for f in ok if f.offset_detector_px is not None]
        det = None
        if len(rows) >= 3:
            dx = np.array([f.offset_detector_px[0] for f in rows])
            dy = np.array([f.offset_detector_px[1] for f in rows])
            det = DetectorFrameOffsets(
                n_frames=len(rows), mean_x_px=float(dx.mean()), mean_y_px=float(dy.mean()), se_x_px=float(dx.std(ddof=1) / math.sqrt(len(rows))),
                se_y_px=float(dy.std(ddof=1) / math.sqrt(len(rows))), std_x_px=float(dx.std(ddof=1)), std_y_px=float(dy.std(ddof=1)),
                n_positive_x=int((dx > 0).sum()),
                interpretation=("Frame offsets mapped to detector pixels. A common detector-x offset is consistent with an estimator or centroid-convention "
                                "effect, but detector-linked archive-WCS calibration can also contribute; the origin is not uniquely identified. "
                                "Its size is compared with the Gaia-free "
                                "centroid-convention term; it is reported, not removed."),
            )
        changed = [f for f in frames if f.translation.evaluated and f.translation.p_value_random_only is not None
                   and (f.translation.p_value_random_only < 0.0027) != (f.translation.p_value < 0.0027)]
        just = [f for f in frames if f.translation.justified]
        reassess = (f"With shared per-frame errors added to each offset's uncertainty (they do not shrink with N), {len(just)} frame(s) keep a justified "
                    f"translation; {len(changed)} frame(s) changed significance relative to random errors only"
                    + (": " + ", ".join(f"{f.observation_id.split(':')[1]} D{f.detector}" for f in changed) if changed else "") + ".")
        return budget, det, reassess

    # ------------------------------------------------------------------ convention and error budget

    def convention(self, test: dict | None = None) -> PredictionConvention:
        c = self.catalog.columns
        full = np.isfinite(c["parallax"])
        g = c["phot_g_mean_mag"]
        calib_like = full & np.isfinite(g) & (g < 17.0)
        plx_cal = np.abs(c["parallax"][calib_like])
        plx_bound = float(np.percentile(plx_cal, 99)) if plx_cal.size else float("nan")
        rv_known = np.isfinite(c["radial_velocity"])
        pm = np.hypot(np.nan_to_num(c["pmra"]), np.nan_to_num(c["pmdec"]))
        dt = max(p.propagation.dt_yr for p in self._pred.values()) if self._pred else 10.34
        persp = np.where(full & ~rv_known, pm * np.abs(np.nan_to_num(c["parallax"])) * RV_BOUND_KM_S * dt * dt / AU_MAS_YR_KM_S, 0.0)
        plx_max = float(np.nanmax(np.abs(c["parallax"]))) if np.any(full) else 0.0
        budget = [
            ErrorBudgetTerm(term="Gaia DR3 catalogue astrometry propagated to the exposure (6x6 covariance)", treatment="included",
                            typical_arcsec=float(np.nanmedian(c["pmra_error"][calib_like])) * dt / 1000.0 if np.any(calib_like) else None,
                            note=f"Typical value: median proper-motion error x {dt:.1f} yr for G < 17 stars; per source in the inspector.", source="Gaia DR3 data model"),
            ErrorBudgetTerm(term="Unknown radial velocity (perspective acceleration neglected)", treatment="neglected", bound_arcsec=float(persp.max()) / 1000.0,
                            note=f"Largest bound in the field for |v_r| <= {RV_BOUND_KM_S:g} km/s; sources with a catalogued Gaia RV use it.",
                            source="Gaia DR3 doc. Sect. 4.1.7"),
            ErrorBudgetTerm(term="Light-time effects in the propagation", treatment="neglected", bound_arcsec=1e-4,
                            note="Gaia DR3 doc. Sect. 4.1.4: <= ~10 micro-arcsec after 10 yr for normal stars; checked on Barnard's Star (10.4\"/yr): "
                                 "ERFA (with light time) and this model differ by 0.011 mas at 2025.65.", source="Gaia DR3 doc. Sect. 4.1.4"),
            ErrorBudgetTerm(term="Observer at the geocentre instead of SPHEREx (<= 7100 km)", treatment="neglected",
                            bound_arcsec=plx_max * 7100.0 / AU_KM / 1000.0, note="parallax x r/1 au for the largest parallax in the field."),
            ErrorBudgetTerm(term="Stellar aberration (annual + orbital, up to ~26\")", treatment="absorbed_by_wcs",
                            bound_arcsec=0.033,
                            note="Not applied: the archive WCS is fitted to catalogue-frame Gaia positions. Bound = differential aberration across the "
                                 "cutout radius if it were not absorbed by the plate scale ((v/c) x 0.073 deg).",
                            source="SPHEREx ES v2.1 Sect. 3.2.8; convention test"),
            ErrorBudgetTerm(term="Gravitational light deflection by the Sun (~4 mas at 90 deg elongation)", treatment="absorbed_by_wcs", bound_arcsec=0.004,
                            note="Nearly uniform over a 6' cutout and absorbed by the fitted pointing."),
            ErrorBudgetTerm(term="Parallax treatment of the pipeline's calibrators (undocumented)", treatment="absorbed_by_wcs",
                            bound_arcsec=plx_bound / 1000.0 if math.isfinite(plx_bound) else None,
                            note="99th percentile of |parallax| for G < 17 Gaia stars in the field: the largest frame offset if the pipeline ignored calibrator parallaxes."),
            ErrorBudgetTerm(term="Archive WCS accuracy", treatment="dominant_uncertainty", typical_arcsec=sref.DOCUMENTED_ASTROMETRIC_RMS_ARCSEC,
                            note="Documented RMS < 0.3\" vs Gaia/2MASS (detector 3); measured here per frame in the alignment diagnostics.", source="SPHEREx ES v2.1 Sect. 4.2.2"),
            ErrorBudgetTerm(term="Exposure duration (mid-exposure time used)", treatment="neglected", bound_arcsec=10.4 * 57.0 / (365.25 * 86400.0),
                            note="Fastest star (10.4\"/yr) x half of the 113.6 s exposure."),
            ErrorBudgetTerm(term="Gaia parallax zero-point (~ -0.02 mas)", treatment="neglected", bound_arcsec=4e-5,
                            note="Changes the parallax term by at most |Z| x 1.02 (parallax factor <= 1 au / r_observer)."),
            ErrorBudgetTerm(term="Pixel-to-sky mapping of the predictions (all_world2pix with SIP)", treatment="included", bound_arcsec=1e-5,
                            note="Inverse SIP solved iteratively to 1e-9 px."),
        ]
        evidence = list(CONVENTION_EVIDENCE_DOC)
        status = "approximate"
        computed = test is not None
        if test is None:
            rep = self.cached_report()
            if rep is not None:
                test, computed = rep.convention_test.model_dump(), True
        not_run = ("Empirical convention test not computed yet (it runs with the alignment report: Alignment tab or GET .../alignment); "
                   "until then the convention rests on the documentation only.")
        aberration_status, aberration_evidence = "untested_bounded", (
            "Convention test not available (no frame with enough validated references)." if computed else not_run)
        if test and test.get("n_frames"):
            evidence.append(
                f"Empirical test over {test['n_frames']} validated frames: chi2 = {test['chi2_catalog_frame']:.1f} for 'catalogue frame' vs "
                f"{test['chi2_apparent_frame']:.0f} for 'apparent frame' ({test['dof']} dof). Decision: {test['decision']}."
            )
            if test["decision"].startswith("catalogue frame"):
                status = "partially_resolved"
                aberration_status = "documented_and_tested"
                aberration_evidence = (f"A WCS in the apparent frame (annual + orbital aberration, {test.get('min_aberration_arcsec', 0):.1f}-{test['max_aberration_arcsec']:.1f}\" here) "
                                       f"is rejected: chi2 {test['chi2_catalog_frame']:.0f} vs {test['chi2_apparent_frame']:.0f} ({test['dof']} dof), frame offsets <= "
                                       f"{test.get('max_frame_offset_arcsec', float('nan')):.2f}\". This is evidence against FULL aberration; partial or smaller "
                                       "convention differences below the frame-offset scatter (~0.1-0.3\") are not tested.")
        elif computed:
            evidence.append("Empirical test not available (no frame with enough validated references): the convention rests on the documentation only.")
        else:
            evidence.append(not_run)
        aspects = [
            ConventionAspect(aspect="Reference catalogue and epoch (Gaia DR3 propagated with proper motion to the observation epoch)", status="documented",
                             evidence="SPHEREx ES v2.1 Sect. 3.2.8 and Table 17. The exact epoch (start/mid) and perspective handling are not stated.",
                             bound_arcsec=2e-5),
            ConventionAspect(aspect="Stellar aberration (apparent vs catalogue place)", status=aberration_status, evidence=aberration_evidence, bound_arcsec=0.033),
            ConventionAspect(aspect="Observer parallax of the pipeline's calibrators", status="undocumented_bounded",
                             evidence="Not mentioned in the Supplement; bounded by the 99th-percentile calibrator parallax in the field.",
                             bound_arcsec=plx_bound / 1000.0 if math.isfinite(plx_bound) else None),
            ConventionAspect(aspect="Gravitational light deflection", status="untested_bounded",
                             evidence="Not mentioned; ~4 mas and nearly uniform over a 6' cutout, so absorbed by the fitted pointing.", bound_arcsec=0.004),
            ConventionAspect(aspect="Centroid definition used to fit the WCS (SExtractor settings)", status="undocumented_bounded",
                             evidence="Not documented; differs from the ePSF reference point by 0.005-0.04 px depending on the definition (shared term in each frame's budget).",
                             bound_arcsec=0.25),
            ConventionAspect(aspect="Time scale and time of the WCS solution (UTC mid-exposure assumed)", status="untested_bounded",
                             evidence="A 57 s or 69 s (TT-UTC) difference moves the fastest star by < 0.03 mas.", bound_arcsec=3e-5),
        ]
        return PredictionConvention(
            frame="ICRS (Gaia DR3 catalogue frame) as seen from the geocentre at the exposure mid-time",
            includes=["proper motion and perspective acceleration (uniform space motion from J2016.0 TCB; radial velocity where catalogued)",
                      "observer parallax for the geocentre (ERFA epv00 barycentric Earth), applied once",
                      "exposure mid-time MJD-AVG (UTC) converted to TDB with astropy"],
            excludes=["stellar aberration (absorbed by the archive WCS fit)", "gravitational light deflection (absorbed)", "light-time effects (Gaia convention)",
                      "spacecraft orbit offset from the geocentre (bounded)"],
            wcs_convention=("The SPHEREx L2 WCS (TAN-SIP, RADESYS ICRS) is fitted to Gaia DR3 positions propagated with proper motion to the exposure "
                            "epoch, so it maps pixels to catalogue-frame directions; predictions are therefore placed with the same convention."),
            status=status, evidence=evidence, aspects=aspects, error_budget=budget,
        )


_sessions: dict[tuple[str, int, str], ObservedGaia] = {}
_sessions_lock = threading.Lock()


def field_config(dataset_id: str) -> AlignmentConfig:
    """Alignment configuration of a field: a study target (field preset) is never a reference star of its own frames."""
    from skyshift.providers.spherex.fields import PRESETS

    p = PRESETS.get(dataset_id)
    sid = p.study_target.gaia_dr3_source_id if p is not None and p.study_target is not None else None
    return AlignmentConfig(excluded_source_ids=(sid,)) if sid else AlignmentConfig()


def observed_gaia(bundle: DatasetBundle, recorded: RecordedField) -> ObservedGaia:
    key = (bundle.dataset.id, id(bundle), recorded.manifest["field_query"]["response_sha256_gz"])
    with _sessions_lock:
        if key not in _sessions:
            _sessions.clear()
            _sessions[key] = ObservedGaia(bundle, recorded, cfg=field_config(bundle.dataset.id))
        return _sessions[key]


__all__ = ["ObservedGaia", "observed_gaia"]
