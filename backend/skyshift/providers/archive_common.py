"""Shared helpers for archive provider status records (no network code)."""

from __future__ import annotations

import re

from skyshift.contracts import IntegrationStatus, ProviderCapability

# Date of the requirements review recorded in planning/SkyShift_Claude_Code_Brief.md.
# It is a documentation review, not a live API, download, or calibration test.
BRIEF_REVIEW_UTC = "2026-11-14T00:00:00Z"
DOC_NOTE = (
    "Documented in the project brief's resource review (2026-11-14). Documentation retrieval is not a live API, "
    "download, calibration, or validation test; live checks have not been run."
)


# ArchiveRequestFailed messages for requests that never got an answer (connection, timeout) or only gateway errors.
_UNREACHABLE = re.compile(r"ArchiveRequestFailed: ((?:URLError|TimeoutError|timeout|IncompleteRead|RemoteDisconnected|ConnectionError|ConnectionResetError)[^\n(]{0,160}|HTTP 50[234][^\n(]{0,60})")


def cap(name: str, status: IntegrationStatus, detail: str) -> ProviderCapability:
    return ProviderCapability(name=name, status=status, detail=detail, checked_utc=None)


def live_status(test_name: str) -> tuple[str, str | None, str]:
    """(status, checked_utc, detail) of a live test as recorded in validation/report.json (never assumed).

    Notes recorded by the test (e.g. a changed archive row count) are appended to the detail.
    """
    from skyshift.validation.report import load_report

    report = load_report()
    hits = [r for r in report.results if r.suite == "pytest" and r.id.endswith(test_name)]
    if not hits:
        return "not_run", None, "no recorded run of the live test"
    r = hits[0]
    note = f" Notes: {'; '.join(r.notes)}" if r.notes else ""
    if r.status == "passed":
        return "tested", report.generated_utc, f"live test {test_name} passed (validation report {report.generated_utc}).{note}"
    if r.status in ("failed", "error"):
        unreachable = _UNREACHABLE.search(r.message or "")
        if unreachable:
            # The service did not answer: nothing about schema, provenance or pinned values was checked.
            return "unavailable", report.generated_utc, (f"live test {test_name} could not reach the service when run "
                                                        f"({unreachable.group(1)}); no schema/provenance/pinned-value result was obtained")
        return "failed", report.generated_utc, f"live test {test_name} {r.status}: {(r.message or '')[:200]}"
    return "not_run", report.generated_utc, f"live test {test_name} {r.status} in the latest report (run with --live)"
