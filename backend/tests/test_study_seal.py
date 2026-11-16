"""Recorded-study integrity is separate from current application test freshness."""
import json
import shutil
from pathlib import Path

import pytest

from skyshift.validation.report import REPO_ROOT, source_hash
from skyshift.validation.study_seal import CONTRACTS_FILE, integrity_status, load_seal, seal_path, verify_seal

STUDY = "validation/vanmaanen2_motion_stage2.json"


@pytest.fixture
def sealed_tree(tmp_path, monkeypatch):
    seal = load_seal(REPO_ROOT / STUDY)
    assert seal is not None
    for rel in [STUDY, CONTRACTS_FILE, *seal["files"], str(seal_path(Path(STUDY)))]:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, dst)
    monkeypatch.setenv("SKYSHIFT_SPHEREX_CACHE", str(tmp_path / "cache"))
    return tmp_path, seal


@pytest.mark.contracts
def test_unchanged_checkout_and_missing_cache_keep_recorded_integrity(sealed_tree):
    root, seal = sealed_tree
    assert verify_seal(seal, root) == []
    status = integrity_status(root / STUDY, root)
    assert status["status"] == "verified" and status["cache_status"] == "missing"
    assert len(status["cache_missing"]) == 13


@pytest.mark.contracts
def test_ui_changes_new_api_types_and_crlf_do_not_change_science(sealed_tree):
    root, seal = sealed_tree
    before = source_hash(root)
    (root / "frontend/src").mkdir(parents=True)
    (root / "frontend/src/theme.css").write_text("body { color: red }")
    assert source_hash(root) != before
    assert verify_seal(seal, root) == []
    with (root / CONTRACTS_FILE).open("a", encoding="utf-8") as f:
        f.write("\nclass PresentationOnly: pass\n")
    for rel in [STUDY, CONTRACTS_FILE, *seal["files"]]:
        p = root / rel
        if p.suffix in (".py", ".json", ".csv", ".toml", ".lock"):
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert verify_seal(seal, root) == []


@pytest.mark.contracts
@pytest.mark.parametrize("rel", [STUDY, "backend/skyshift/science/target_astrometry.py",
    "fixtures/spherex/spherex-dr1-vanmaanen2/manifest.json", "validation/vanmaanen2_motion_stage2_pairs.csv",
    "validation/plots/vanmaanen2_stage2_positions.png", "backend/uv.lock", CONTRACTS_FILE])
def test_changes_to_science_inputs_outputs_and_definitions_are_detected(sealed_tree, rel):
    root, seal = sealed_tree
    p = root / rel
    if rel == CONTRACTS_FILE:
        p.write_text(p.read_text().replace('class Epoch(Contract):', 'class Epoch(Contract):\n    changed: bool = True'), encoding="utf-8")
    else:
        p.write_bytes(p.read_bytes() + b"\nchanged\n")
    assert verify_seal(seal, root)


@pytest.mark.contracts
def test_missing_manifest_is_unavailable_and_modified_cutout_is_changed(sealed_tree):
    root, seal = sealed_tree
    name = next(iter(seal["cutouts"]))
    p = root / "cache/spherex-dr1-vanmaanen2/cutouts" / name
    p.parent.mkdir(parents=True)
    p.write_bytes(b"incorrect pixels")
    assert integrity_status(root / STUDY, root)["status"] == "changed"
    seal_path(root / STUDY).write_text("{invalid")
    assert integrity_status(root / STUDY, root)["status"] == "unavailable"


@pytest.mark.contracts
def test_original_results_and_primary_claim_are_unchanged():
    import hashlib
    raw = (REPO_ROOT / STUDY).read_bytes().replace(b"\r\n", b"\n")
    # Pinned canonical hash from the original reference commit; also works in source ZIPs without .git.
    assert hashlib.sha256(raw).hexdigest() == "c968132abbbd1342b95fa6fbea4793787bee316e2115b43e741e01771935bdb3"
    study = json.loads(raw)
    assert study["combined"]["tied"]["sigma_equiv_vs_zero"] == pytest.approx(5.77, abs=.02)
