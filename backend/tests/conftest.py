"""Shared pytest configuration.

Result recording for the Methods validation report: when the environment
variable SKYSHIFT_PYTEST_JSON is set to a path, every test outcome is written
there as JSON with its category (first matching marker). scripts/validate.py
sets it; normal `uv run pytest` runs do not write anything.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

CATEGORY_MARKERS = ("live", "archive", "math", "coords", "measurement", "registration", "catalog", "pipeline", "contracts", "api")

_results: list[dict] = []
_started = time.time()


def _category(item: pytest.Item) -> str:
    names = {m.name for m in item.iter_markers()}
    for marker in CATEGORY_MARKERS:
        if marker in names:
            return marker
    return "uncategorized"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Live archive tests run only when explicitly requested (-m live).
    markexpr = config.getoption("-m") or ""
    if "live" in markexpr:
        return
    skip_live = pytest.mark.skip(reason="live archive test: not run by default (use -m live)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):  # noqa: ANN001
    outcome = yield
    report = outcome.get_result()
    if not os.environ.get("SKYSHIFT_PYTEST_JSON"):
        return
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        status = report.outcome
        if report.when == "setup" and report.outcome == "failed":
            status = "error"
        message = None
        if report.outcome != "passed":
            message = str(report.longrepr)[-1200:] if report.longrepr else None
            if report.skipped and isinstance(report.longrepr, tuple):
                message = str(report.longrepr[2])
        doc = (item.obj.__doc__ or "").strip().splitlines()[0] if getattr(item, "obj", None) and item.obj.__doc__ else None
        _results.append(
            {
                "id": item.nodeid,
                "name": doc or item.name,
                "suite": "pytest",
                "category": _category(item),
                "status": status,
                "duration_s": round(report.duration, 4),
                "message": message,
                "file": str(Path(item.fspath).name),
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    path = os.environ.get("SKYSHIFT_PYTEST_JSON")
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps({"started": _started, "duration_s": time.time() - _started, "exitstatus": int(exitstatus), "results": _results}, indent=1),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Shared fixtures (built once per session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def investigation():
    """The default synthetic investigation (syn-nb-01, default seed)."""
    from skyshift.pipeline.investigation import get_investigation

    return get_investigation("syn-nb-01")


def nearest_source_to_truth(inv, truth_id: str) -> str:
    """Validation helper: the detected source nearest a truth source in the reference frame.

    Truth is used ONLY to choose which detection to evaluate; measurements never read truth.
    """
    from skyshift.coords.tangent import angular_separation_deg

    tp = next(p for p in inv.bundle.truth.positions if p.truth_id == truth_id and p.frame_id == inv.reference_frame_id)
    return min(inv.sources, key=lambda s: float(angular_separation_deg(s.position.ra_deg, s.position.dec_deg, tp.ra_deg, tp.dec_deg))).id


@pytest.fixture(scope="session")
def c1_id(investigation) -> str:
    return nearest_source_to_truth(investigation, "truth:C1")


@pytest.fixture(scope="session")
def v1_id(investigation) -> str:
    return nearest_source_to_truth(investigation, "truth:V1")


# ---------------------------------------------------------------- SPHEREx (observed data)

SPHEREX_DATASET = "spherex-dr1-barnard"


@pytest.fixture(scope="session")
def spherex_manifest() -> dict:
    from skyshift.providers.spherex.paths import manifest_path

    return json.loads(manifest_path(SPHEREX_DATASET).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def spherex_bundle(spherex_manifest):
    """The observed dataset built from the committed manifest + local cache (skipped if the cache is absent)."""
    from skyshift.providers.spherex.paths import cutout_path

    missing = [d["file_name"] for d in spherex_manifest["downloads"] if d["status"] == "downloaded" and not cutout_path(SPHEREX_DATASET, d["file_name"]).exists()]
    if missing:
        pytest.skip(f"SPHEREx cutouts not in the local cache ({len(missing)} missing); run: cd backend && uv run python -m skyshift.providers.spherex.fetch --from-manifest")
    from skyshift.providers.spherex import SpherexProvider

    return SpherexProvider().load_dataset(SPHEREX_DATASET)
