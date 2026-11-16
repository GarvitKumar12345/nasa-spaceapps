"""Portable recorded evidence, deliberately separate from synthetic notebook records."""
import io
import json
import zipfile

from skyshift.pipeline.target_motion import LIMITATIONS, study_path
from skyshift.validation.report import REPO_ROOT
from skyshift.validation.study_seal import integrity_status, load_seal, seal_path


def evidence_zip(dataset_id: str) -> bytes:
    study = study_path(dataset_id)
    seal = load_seal(study)
    paths = [study.relative_to(REPO_ROOT).as_posix(), seal_path(study).relative_to(REPO_ROOT).as_posix(),
             "validation/vanmaanen2_motion_stage2_pairs.csv", "docs/reviews/2026-11-16-van-maanen-2-stage2.md",
             *[p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "validation/plots").glob("vanmaanen2_stage2_*.png")]]
    if seal:
        paths += [p for p in seal["files"] if p.startswith(("fixtures/", "validation/"))]
    status = integrity_status(study, REPO_ROOT)
    missing = [p for p in paths if not (REPO_ROOT / p).is_file()]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(set(paths)):
            if (REPO_ROOT / rel).is_file():
                z.write(REPO_ROOT / rel, rel)
        z.writestr("integrity.json", json.dumps({"schema": "skyshift.recorded-evidence/1", "origin": "derived_measurement",
            "integrity": status, "missing_package_files": missing, "limitations": LIMITATIONS}, indent=2))
        z.writestr("REPRODUCE.txt", "Recorded van Maanen 2 study; primary tied D2+D3 result, post-hoc analysis separate.\n"
            "Checkout the reference commit named in the seal. Dependencies: cd backend && uv sync.\n"
            "Retrieve the cutouts with python -m skyshift.providers.spherex.fetch --field spherex-dr1-vanmaanen2 --from-manifest.\n"
            "Only to independently reproduce the analysis in a separate checkout: python scripts/target_motion_stage2.py.\n"
            "This export never reruns fitting. Cutouts are not bundled; retrieval requires archive availability.\n"
            "See integrity.json for current verification and missing data. This package is not a synthetic notebook record.\n")
    return buffer.getvalue()
