"""Checks for the validation-report merger that feeds the Methods page."""

from __future__ import annotations

import pytest

from skyshift.contracts import SuiteRun
from skyshift.validation.report import (
    build_report,
    counts,
    load_report,
    playwright_results,
    pytest_results,
    report_with_staleness,
    source_hash,
    vitest_results,
    write_report,
)

pytestmark = pytest.mark.contracts


def test_pytest_payload_maps_status_and_category():
    """pytest hook output keeps each test's real outcome and category marker."""
    payload = {
        "results": [
            {"id": "t.py::a", "name": "a", "category": "math", "status": "passed", "duration_s": 0.1, "file": "t.py"},
            {"id": "t.py::b", "name": "b", "category": "live", "status": "skipped", "message": "not run by default"},
            {"id": "t.py::c", "name": "c", "category": "measurement", "status": "failed", "message": "assert 1 == 2"},
        ]
    }
    rs = pytest_results(payload)
    assert [r.status for r in rs] == ["passed", "skipped", "failed"]
    assert [r.category for r in rs] == ["math", "live", "measurement"]
    assert counts(rs) == {"total": 3, "passed": 1, "skipped": 1, "failed": 1}


def test_vitest_payload_uses_bracket_category_tags():
    """Vitest results take their category from a [tag] in the describe/test title."""
    payload = {
        "testResults": [
            {
                "name": "C:/x/src/physics/kepler.test.ts",
                "assertionResults": [
                    {"ancestorTitles": ["[math] Kepler solver"], "title": "residual", "status": "passed", "duration": 3.0},
                    {"ancestorTitles": ["misc"], "title": "untagged", "status": "failed", "failureMessages": ["boom"]},
                ],
            }
        ]
    }
    rs = vitest_results(payload)
    assert rs[0].category == "math" and rs[0].status == "passed" and rs[0].file == "kepler.test.ts"
    assert rs[1].category == "uncategorized" and rs[1].status == "failed" and rs[1].message == "boom"


def test_playwright_payload_walks_nested_suites():
    """Playwright JSON is walked recursively; timeouts count as failures."""
    payload = {
        "suites": [
            {
                "title": "observatory.spec.ts",
                "file": "observatory.spec.ts",
                "specs": [{"title": "[browser] loads", "tests": [{"results": [{"status": "passed", "duration": 1200}]}]}],
                "suites": [
                    {"title": "persistence", "file": "observatory.spec.ts", "specs": [{"title": "reload", "tests": [{"results": [{"status": "timedOut", "duration": 60000, "error": {"message": "timeout"}}]}]}]}
                ],
            }
        ]
    }
    rs = playwright_results(payload)
    assert [r.status for r in rs] == ["passed", "failed"]
    assert all(r.suite == "playwright" for r in rs)
    assert rs[1].message == "timeout"


def test_missing_report_is_not_a_pass(tmp_path):
    """With no report file the API reports 'unavailable', never passed checks."""
    report = load_report(tmp_path / "missing.json")
    assert report.available is False and report.results == []


def test_staleness_detects_source_change(tmp_path):
    """A report generated before a source edit is flagged stale."""
    src = tmp_path / "backend" / "skyshift"
    src.mkdir(parents=True)
    (src / "mod.py").write_text("x = 1\n")
    report = build_report(generated_utc="2026-11-14T00:00:00Z", environment={}, suites=[SuiteRun(suite="pytest", ran=True)], results=[], root=tmp_path)
    path = tmp_path / "validation" / "report.json"
    write_report(report, path)
    assert report_with_staleness(path, tmp_path).stale is False
    (src / "mod.py").write_text("x = 2\n")
    assert report_with_staleness(path, tmp_path).stale is True
    assert source_hash(tmp_path) != report.source_hash
