"""Locations of SPHEREx manifests (committed) and downloaded files (local cache, not committed)."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "spherex"


def cache_root() -> Path:
    env = os.environ.get("SKYSHIFT_SPHEREX_CACHE")
    return Path(env) if env else REPO_ROOT / "backend" / "cache" / "spherex"


def manifest_path(dataset_id: str) -> Path:
    return FIXTURE_ROOT / dataset_id / "manifest.json"


def cutout_path(dataset_id: str, file_name: str) -> Path:
    if "/" in file_name or "\\" in file_name or file_name.startswith("."):
        raise ValueError(f"unsafe file name {file_name!r}")
    return cache_root() / dataset_id / "cutouts" / file_name
