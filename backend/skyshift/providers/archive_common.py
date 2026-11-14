"""Shared helpers for archive provider stubs (status records only; no network code)."""

from __future__ import annotations

from skyshift.contracts import IntegrationStatus, ProviderCapability

# Date of the requirements review recorded in planning/SkyShift_Claude_Code_Brief.md.
# It is a documentation review, not a live API, download, or calibration test.
BRIEF_REVIEW_UTC = "2026-11-14T00:00:00Z"
DOC_NOTE = (
    "Documented in the project brief's resource review (2026-11-14). Documentation retrieval is not a live API, "
    "download, calibration, or validation test; live checks have not been run."
)


def cap(name: str, status: IntegrationStatus, detail: str) -> ProviderCapability:
    return ProviderCapability(name=name, status=status, detail=detail, checked_utc=None)
