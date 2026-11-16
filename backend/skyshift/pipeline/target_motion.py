"""Recorded target-motion studies (scripts/target_motion_stage2.py), served as recorded with a staleness check.

The study is a validation of one named target; the API serves its recorded result (measurements and model predictions
kept apart) and never recomputes or extends it. Scientific integrity is verified against the committed reference seal independently of
whole-application test freshness. Changed or unverifiable scientific evidence is flagged stale.
"""

from __future__ import annotations

import json
from pathlib import Path

from skyshift.contracts import MotionBudgetValidation, MotionCombined, MotionFrame, MotionPair, TargetMotionStudy
from skyshift.validation.report import REPO_ROOT

LIMITATIONS = [
    "A validation study of one named target in one field, not a general target-measurement capability (source measurement and motion fits stay unavailable).",
    "Two epochs per detector give one displacement each: no proper motion or parallax is fitted from these data.",
    "The stage-2 analysis plan was defined after the first pass, whose results were known: the analysis is not blind.",
    "The Gaia DR3 record of this field comes from a partner data centre (ESA unreachable), verified row for row against an ESA-recorded response.",
    "Positions are tied to 5-7 reference stars per frame where available; D1 and D5 frames have too few references, D6 is excluded (S/N < 30).",
    "The nominal fit does not model the catalogued neighbour ~2.9 px away; its flux inflates chi2 and therefore the quoted errors (conservative).",
]


def study_path(dataset_id: str) -> Path:
    return REPO_ROOT / "validation" / f"{dataset_id.replace('spherex-dr1-', '')}_motion_stage2.json"


def study_available(dataset_id: str) -> bool:
    from skyshift.providers.spherex.fields import PRESETS

    p = PRESETS.get(dataset_id)
    return bool(p is not None and p.study_target is not None and study_path(dataset_id).exists())


def _pair(p: dict) -> MotionPair:
    if "p_vs_zero" not in p:
        return MotionPair(label=p["label"], approach=p["approach"], role=p["role"], detector=p["detector"], status="not measured", status_reason=p["reason"])
    return MotionPair(label=p["label"], approach=p["approach"], role=p["role"], detector=p["detector"], status=p["status"], status_reason=p["status_reason"],
                      observation_ids=p["observation_ids"], epochs_utc=p["epochs_utc"], predicted_arcsec=tuple(p["predicted_arcsec"]),
                      measured_arcsec=tuple(p["measured_arcsec"]), residual_arcsec=tuple(p["residual_arcsec"]), sigma_stat_arcsec=tuple(p["sigma_stat_arcsec"]),
                      sigma_sys_arcsec=tuple(p["sigma_sys_arcsec"]), along_ratio=p.get("along_ratio"), along_ratio_sigma=p.get("along_ratio_sigma"),
                      sigma_vs_zero=p["sigma_equiv_vs_zero"], p_vs_prediction=p["p_vs_prediction"])


def _frame(r: dict) -> MotionFrame:
    m = r.get("measured") or {}
    joint = ((r.get("variants") or {}).get("neighbours_modelled") or {}).get("joint_fit") or {}
    b = r.get("budgets") or {}
    tup = lambda v: tuple(v) if v is not None else None  # noqa: E731
    return MotionFrame(frame_id=r["frame_id"], observation_id=r["obs_id"], detector=r["detector"], season=r.get("season"), mid_utc=r["mid_utc"],
                       lambda_um=r.get("lambda_um"), stage1_snr=r.get("stage1_snr"), n_references=r["n_references"], status=r["status"], reason=r["reason"],
                       predicted_x_px=r["predicted"]["x_px"], predicted_y_px=r["predicted"]["y_px"], measured_x_px=m.get("x_px"), measured_y_px=m.get("y_px"),
                       sigma_x_px=m.get("sigma_x_px"), sigma_y_px=m.get("sigma_y_px"), chi2_red=m.get("chi2_red"), chi2_red_neighbour_modelled=joint.get("chi2_red"),
                       residual_untied_arcsec=tup(r.get("residual_untied_arcsec")), residual_tied_arcsec=tup(r.get("residual_tied_arcsec")),
                       sigma_total_untied_arcsec=tup((b.get("untied") or {}).get("total_arcsec")), sigma_total_tied_arcsec=tup((b.get("tied") or {}).get("total_arcsec")),
                       analysis_choice_rms_px=tup(r.get("analysis_choice_rms_px")))


def _combined(approach: str, c: dict) -> MotionCombined:
    return MotionCombined(approach=approach, pairs=c.get("pairs", []), along_ratio=c.get("along_ratio"), along_ratio_sigma=c.get("along_ratio_sigma"),
                          sigma_vs_zero=c.get("sigma_equiv_vs_zero"), p_vs_prediction=c.get("p_vs_prediction"), budget_validated=c.get("budget_validated"),
                          robust_across_variants=c.get("robust_across_variants"), recovered=c.get("recovered"))


def load_study(dataset_id: str) -> TargetMotionStudy:
    from skyshift.validation.study_seal import integrity_status

    raw = json.loads(study_path(dataset_id).read_text(encoding="utf-8"))
    v = raw["budget_validation"]
    integrity = integrity_status(study_path(dataset_id), REPO_ROOT)
    return TargetMotionStudy(
        dataset_id=dataset_id, target_name=raw["target"]["name"], gaia_source_id=str(raw["target"]["source_id"]), generated_utc=raw["generated_utc"],
        source_hash=raw["source_hash"], stale=integrity["status"] != "verified", integrity=integrity, recovered=bool(raw["conclusion"]["recovered"]),
        statement=raw["conclusion"]["statement"], plan_disclosure=raw["plan"]["disclosure"],
        combined=[_combined(a, c) for a, c in raw["combined"].items() if c.get("pairs")],
        budget_validation=[MotionBudgetValidation(approach=a, test=x["test"], chi2=x.get("chi2"), dof=x["dof"], p=x.get("p"), passed=bool(x["passed"])) for a, x in v.items()],
        pairs=[_pair(p) for p in raw["pairs"]], frames=[_frame(r) for r in raw["frames"]],
        post_hoc=[_combined(a, c) for a, c in (raw.get("post_hoc_neighbour_modelled") or {}).get("combined", {}).items()],
        post_hoc_note=(raw.get("post_hoc_neighbour_modelled") or {}).get("note", ""),
        gaia_service=raw["gaia_record"].get("service"), gaia_verification=raw["gaia_record"].get("verification"), gaia_crosscheck=raw["gaia_record"].get("crosscheck"),
        evidence_files=[str(study_path(dataset_id).relative_to(REPO_ROOT)).replace("\\", "/"), "validation/vanmaanen2_motion_stage2_pairs.csv",
                        "validation/plots/vanmaanen2_stage2_*.png", "docs/reviews/2026-11-16-van-maanen-2-stage2.md"],
        limitations=LIMITATIONS,
    )


__all__ = ["LIMITATIONS", "load_study", "study_available", "study_path"]
