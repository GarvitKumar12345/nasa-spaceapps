"""Run SkyShift's checks and write validation/report.json (rendered by Methods).

Usage (from backend/):
    uv run python scripts/validate.py            # pytest + vitest + Playwright
    uv run python scripts/validate.py --no-e2e   # skip the browser suite (recorded as not run)
    uv run python scripts/validate.py --live     # also run live archive tests (-m live)

Raw runner outputs go to validation/results/ and are deleted before each run,
so a runner that fails to start can never leave an old "pass" behind.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from skyshift.contracts import SuiteRun, TestResult
from skyshift.validation.report import (
    REPO_ROOT,
    RESULTS_DIR,
    build_report,
    counts,
    playwright_results,
    pytest_results,
    vitest_results,
    write_report,
)
from skyshift.versions import software_versions


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, float, str]:
    started = _utc_now()
    t0 = time.perf_counter()
    print(f"\n$ {' '.join(cmd)}   (cwd={cwd})", flush=True)
    proc = subprocess.run(cmd, cwd=cwd, env=env, check=False)
    return proc.returncode, time.perf_counter() - t0, started


def _version(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-e2e", action="store_true", help="skip the Playwright browser suite")
    parser.add_argument("--live", action="store_true", help="include live archive tests (network)")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("pytest.json", "vitest.json", "playwright.json"):
        (RESULTS_DIR / name).unlink(missing_ok=True)

    npm = shutil.which("npm") or "npm"
    suites: list[SuiteRun] = []
    results: list[TestResult] = []

    # ---- pytest -------------------------------------------------------------
    py_json = RESULTS_DIR / "pytest.json"
    py_cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if args.live:
        py_cmd += ["-m", "live or not live"]
    env = {**os.environ, "SKYSHIFT_PYTEST_JSON": str(py_json)}
    code, duration, started = _run(py_cmd, REPO_ROOT / "backend", env)
    payload = _load(py_json)
    if payload is None:
        suites.append(SuiteRun(suite="pytest", ran=False, started_utc=started, duration_s=duration, command=" ".join(py_cmd[1:]), note=f"pytest produced no results (exit code {code})"))
    else:
        rs = pytest_results(payload)
        results += rs
        note = None if not args.live else "live archive tests requested"
        suites.append(SuiteRun(suite="pytest", ran=True, started_utc=started, duration_s=duration, counts=counts(rs), command="pytest -q", note=note))

    # ---- vitest -------------------------------------------------------------
    vi_json = RESULTS_DIR / "vitest.json"
    vi_cmd = [npm, "run", "test:json"]
    code, duration, started = _run(vi_cmd, REPO_ROOT / "frontend")
    payload = _load(vi_json)
    if payload is None:
        suites.append(SuiteRun(suite="vitest", ran=False, started_utc=started, duration_s=duration, command="vitest run", note=f"vitest produced no results (exit code {code})"))
    else:
        rs = vitest_results(payload)
        results += rs
        suites.append(SuiteRun(suite="vitest", ran=True, started_utc=started, duration_s=duration, counts=counts(rs), command="vitest run"))

    # ---- Playwright ---------------------------------------------------------
    pw_json = RESULTS_DIR / "playwright.json"
    if args.no_e2e:
        suites.append(SuiteRun(suite="playwright", ran=False, command="playwright test", note="skipped by --no-e2e"))
    else:
        code, duration, started = _run([npm, "run", "e2e"], REPO_ROOT / "frontend")
        payload = _load(pw_json)
        if payload is None:
            suites.append(SuiteRun(suite="playwright", ran=False, started_utc=started, duration_s=duration, command="playwright test", note=f"Playwright produced no results (exit code {code})"))
        else:
            rs = playwright_results(payload)
            results += rs
            suites.append(SuiteRun(suite="playwright", ran=True, started_utc=started, duration_s=duration, counts=counts(rs), command="playwright test"))

    environment = {v.name: v.version for v in software_versions()}
    environment.update(
        {
            "os": platform.platform(),
            "node": _version(["node", "--version"]),
            "npm": _version([npm, "--version"]),
            "uv": _version(["uv", "--version"]),
            "browser": "system Chrome via Playwright channel 'chrome'",
        }
    )
    report = build_report(generated_utc=_utc_now(), environment=environment, suites=suites, results=results)
    write_report(report)

    c = counts(results)
    print("\n=== SkyShift validation report ===")
    for s in suites:
        print(f"  {s.suite:<10} {'ran' if s.ran else 'NOT RUN':<8} {s.counts} {s.note or ''}")
    print(f"  total: {c}")
    print(f"  written: {REPO_ROOT / 'validation' / 'report.json'}")
    failed = c.get("failed", 0) + c.get("error", 0)
    unexpected_not_run = [s.suite for s in suites if not s.ran and s.note != "skipped by --no-e2e"]
    return 1 if failed or unexpected_not_run else 0


if __name__ == "__main__":
    sys.exit(main())
