"""Validation report: merge real test-runner output into validation/report.json.

The Methods page renders this file. Nothing here invents a result: a suite
that was not executed is recorded with `ran = False`, and its tests do not
appear as passed. A source hash lets the API flag a report as stale when code
changed after the report was generated.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from skyshift.contracts import SuiteRun, TestResult, ValidationReport

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = REPO_ROOT / "validation" / "report.json"
RESULTS_DIR = REPO_ROOT / "validation" / "results"

# Files whose content defines the behaviour under test.
_HASH_GLOBS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("backend/skyshift", (".py",)),
    ("backend/tests", (".py",)),
    ("backend/scripts", (".py",)),
    ("frontend/src", (".ts", ".tsx", ".css")),
    ("frontend/e2e", (".ts",)),
    ("fixtures", (".json",)),
)

_TAG = re.compile(r"\[(math|coords|measurement|registration|catalog|pipeline|contracts|api|ui|browser|live|archive)\]", re.I)


def source_hash(root: Path = REPO_ROOT) -> str:
    """sha256 over (relative path, content hash) of all source/test/fixture files."""
    digest = hashlib.sha256()
    files: list[Path] = []
    for rel, suffixes in _HASH_GLOBS:
        base = root / rel
        if not base.exists():
            continue
        files.extend(p for p in base.rglob("*") if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts)
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _category_from_name(*names: str, default: str) -> str:
    for name in names:
        match = _TAG.search(name or "")
        if match:
            return match.group(1).lower()
    return default


def pytest_results(payload: dict[str, Any]) -> list[TestResult]:
    out: list[TestResult] = []
    for r in payload.get("results", []):
        status = r.get("status", "error")
        if status not in ("passed", "failed", "skipped", "error"):
            status = "error"
        out.append(
            TestResult(
                id=r["id"],
                name=r.get("name") or r["id"],
                suite="pytest",
                category=r.get("category") or "uncategorized",
                status=status,
                duration_s=r.get("duration_s"),
                message=r.get("message"),
                file=r.get("file"),
            )
        )
    return out


def vitest_results(payload: dict[str, Any]) -> list[TestResult]:
    out: list[TestResult] = []
    for file_result in payload.get("testResults", []):
        file_name = Path(file_result.get("name", "")).name
        for a in file_result.get("assertionResults", []):
            raw = a.get("status", "failed")
            status = {"passed": "passed", "failed": "failed", "skipped": "skipped", "pending": "skipped", "todo": "skipped"}.get(raw, "error")
            titles = [*a.get("ancestorTitles", []), a.get("title", "")]
            full = " › ".join(t for t in titles if t)
            failure = "\n".join(a.get("failureMessages") or [])[-1200:] or None
            duration = a.get("duration")
            out.append(
                TestResult(
                    id=f"{file_name}::{full}",
                    name=full,
                    suite="vitest",
                    category=_category_from_name(*titles, default="uncategorized"),
                    status=status,
                    duration_s=(duration / 1000.0) if isinstance(duration, (int, float)) else None,
                    message=failure,
                    file=file_name,
                )
            )
    return out


def _walk_playwright(suites: Iterable[dict[str, Any]], parents: list[str]) -> Iterable[tuple[list[str], dict[str, Any], str]]:
    for suite in suites:
        title = suite.get("title", "")
        here = [*parents, title] if title else parents
        for spec in suite.get("specs", []):
            yield here, spec, suite.get("file", "")
        yield from _walk_playwright(suite.get("suites", []), here)


def playwright_results(payload: dict[str, Any]) -> list[TestResult]:
    out: list[TestResult] = []
    for parents, spec, file_name in _walk_playwright(payload.get("suites", []), []):
        tests = spec.get("tests", [])
        results = [res for t in tests for res in t.get("results", [])]
        last = results[-1] if results else {}
        raw = last.get("status", "skipped" if not results else "failed")
        status = {"passed": "passed", "failed": "failed", "timedOut": "failed", "interrupted": "error", "skipped": "skipped"}.get(raw, "error")
        error = last.get("error") or {}
        message = (error.get("message") or "")[-1200:] or None
        names = [p for p in parents if p and not p.endswith(".ts")] + [spec.get("title", "")]
        full = " › ".join(names)
        out.append(
            TestResult(
                id=f"{Path(file_name).name}::{full}",
                name=full,
                suite="playwright",
                category=_category_from_name(*names, default="browser"),
                status=status,
                duration_s=(last.get("duration", 0) / 1000.0) if results else None,
                message=message,
                file=Path(file_name).name or None,
            )
        )
    return out


def counts(results: list[TestResult]) -> dict[str, int]:
    c: dict[str, int] = {"total": len(results)}
    for r in results:
        c[r.status] = c.get(r.status, 0) + 1
    return c


def load_report(path: Path = REPORT_PATH) -> ValidationReport:
    """Read the merged report; an absent/unreadable file yields available=False."""
    if not path.exists():
        return ValidationReport(generated_utc=None, source_hash=None, available=False)
    try:
        return ValidationReport.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupted report must not look like a pass
        return ValidationReport(
            generated_utc=None,
            source_hash=None,
            available=False,
            environment={"error": f"validation report unreadable: {exc}"},
        )


def report_with_staleness(path: Path = REPORT_PATH, root: Path = REPO_ROOT) -> ValidationReport:
    report = load_report(path)
    current = source_hash(root)
    stale = None if report.source_hash is None else report.source_hash != current
    return report.model_copy(update={"current_source_hash": current, "stale": stale})


def build_report(
    *,
    generated_utc: str,
    environment: dict[str, str],
    suites: list[SuiteRun],
    results: list[TestResult],
    root: Path = REPO_ROOT,
) -> ValidationReport:
    return ValidationReport(
        generated_utc=generated_utc,
        source_hash=source_hash(root),
        environment=environment,
        suites=suites,
        results=results,
        available=True,
    )


def write_report(report: ValidationReport, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(mode="json"), indent=1) + "\n", encoding="utf-8")
