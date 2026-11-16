"""Seal the original committed study without rerunning fitting or changing its results.

Run from backend: uv run python scripts/seal_recorded_study.py
Only the new .seal.json is written. Git archive supplies LF-normalized reference files.
"""
import datetime as dt
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from skyshift.validation.report import REPO_ROOT
from skyshift.validation.study_seal import make_seal, sha256_file

REFERENCE = "0c7f4ab5d391e256e12d0496690d0e619bac55eb"
STUDY = "validation/vanmaanen2_motion_stage2.json"
EXCLUDED = {
    "backend/skyshift/validation/report.py": "Application validation hashing is recorded metadata, not used to calculate positions.",
    "backend/skyshift/pipeline/target_motion.py": "Read-only application study presenter, imported for provider capability availability only.",
    "backend/skyshift/providers/archive_common.py": "Provider status presentation from the application validation report; no science computation.",
}


def main():
    commit = subprocess.check_output(["git", "rev-parse", REFERENCE], cwd=REPO_ROOT, text=True).strip()
    archive = subprocess.check_output(["git", "archive", commit], cwd=REPO_ROOT)
    with tempfile.TemporaryDirectory(prefix="skyshift-seal-") as tmp:
        root = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(root, filter="data")
        reference_hash = subprocess.check_output([sys.executable, "-c", "from skyshift.validation.report import source_hash; print(source_hash())"], cwd=root / "backend", text=True).strip()
        seal = make_seal(root, STUDY, ["backend/scripts/target_motion_stage2.py"], EXCLUDED,
                         commit, reference_hash, dt.datetime.now(dt.UTC).isoformat())
        evidence = ["validation/vanmaanen2_stage1.json", "validation/vanmaanen2_motion.json",
                    "validation/vanmaanen2_motion_stage2_pairs.csv", *[p.relative_to(root).as_posix() for p in (root / "validation/plots").glob("vanmaanen2_stage2_*.png")]]
        seal["files"].update({p: sha256_file(root / p) for p in evidence})
        # Imported shared declarations depend on these imports too.
        import ast
        source = (root / "backend/skyshift/contracts.py").read_text()
        seal["contracts_imports"] = [ast.get_source_segment(source, n) for n in ast.parse(source).body if isinstance(n, (ast.Import, ast.ImportFrom))]
        manifest = json.loads((root / "fixtures/spherex/spherex-dr1-vanmaanen2/manifest.json").read_text())
        seal["cutouts"] = {d["file_name"]: d["sha256"] for d in manifest["downloads"] if d["status"] == "downloaded"}
        target = REPO_ROOT / STUDY.replace(".json", ".seal.json")
        target.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Sealed {len(seal['files'])} files, {len(seal['contract_definitions'])} declarations, {len(seal['cutouts'])} cutouts at {commit}.")
        print(f"Legacy execution hash matches committed tree: {seal['execution_hash_matches_reference']} (both retained).")


if __name__ == "__main__":
    main()
