"""Locations of the recorded Gaia DR3 responses and their manifests (committed fixtures)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "gaia_dr3"
RESPONSE_NAME = "gaia_dr3_response.vot.gz"
EPOCH_PROP_NAME = "gaia_dr3_epoch_prop.vot.gz"
OVERFLOW_PROBE_NAME = "gaia_dr3_overflow_probe.vot.gz"


def field_dir(field_id: str) -> Path:
    if not field_id or "/" in field_id or "\\" in field_id or field_id.startswith("."):
        raise ValueError(f"unsafe field id {field_id!r}")
    return FIXTURE_ROOT / field_id


def manifest_path(field_id: str) -> Path:
    return field_dir(field_id) / "manifest.json"


def response_path(field_id: str) -> Path:
    return field_dir(field_id) / RESPONSE_NAME


def epoch_prop_path(field_id: str) -> Path:
    return field_dir(field_id) / EPOCH_PROP_NAME
