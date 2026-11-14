"""WISE/unWISE and NEOSSat/CADC provider boundaries — documented extensions, not implemented."""

from __future__ import annotations

from skyshift.contracts import DatasetSummary, ProviderStatus, Reference
from skyshift.providers.archive_common import BRIEF_REVIEW_UTC, DOC_NOTE, cap
from skyshift.providers.base import DatasetBundle, ProviderUnavailable

NEOSSAT_PRODUCT_LEVELS = ("RAW", "CLEAN", "COR", "CORD")


class WiseProvider:
    id = "wise"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            id="wise",
            name="WISE / unWISE comparison (extension)",
            role="image",
            status="documented",
            release_policy="Not selected. Verify archive products, epoch/coadd definitions, WCS, bandpasses and access before any use.",
            access_route="Not chosen. WiseView (an unWISE blink viewer) is a design precedent only; SkyShift will not scrape or embed it.",
            capabilities=[
                cap("Archive product verification", "not_implemented", "unWISE epochs/coadds, WCS and bandpasses to be verified independently."),
                cap("Side-by-side comparison", "not_implemented", "Instrument identity kept distinct; WISE and SPHEREx channels are not interchangeable."),
                cap("Cross-mission subtraction / colours", "not_implemented", "Requires a separate validated treatment of bandpass, resolution, calibration and epoch."),
                cap("Live access check", "not_run", "No request has been made from this build."),
            ],
            references=[
                Reference(title="WiseView repository (source, citation)", url="https://github.com/backyardworlds/wiseview"),
                Reference(title="WiseView (live site; timed out during the brief's review)", url="http://byw.tools/wiseview"),
            ],
            notes=[DOC_NOTE, "Retain WiseView citation information if its workflow ideas are reused."],
            last_reviewed_utc=BRIEF_REVIEW_UTC,
        )

    def list_datasets(self) -> list[DatasetSummary]:
        return []

    def load_dataset(self, dataset_id: str, seed: int | None = None) -> DatasetBundle:
        raise ProviderUnavailable("wise", "load_dataset", "not implemented in this build; see docs/providers/wise.md")


class NeossatProvider:
    id = "neossat"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            id="neossat",
            name="NEOSSat case study via CADC (extension)",
            role="image",
            status="documented",
            release_policy=f"Not selected. Track the product level ({'/'.join(NEOSSAT_PRODUCT_LEVELS)}) and applied corrections per frame.",
            access_route="Planned: CADC public CAOM/TAP and DataLink services (not the metadata-curation interface).",
            capabilities=[
                cap("Discovery via CADC TAP", "not_implemented", "Public CAOM/TAP search of the NEOSSat collection."),
                cap("Download via DataLink", "not_implemented", "Product level recorded; no assumption that a filename proves calibration."),
                cap("Tracking-mode / trailing checks", "not_implemented", "Inspect pointing/tracking metadata, exposure, WCS quality, trailing before registration."),
                cap("Solar-system target model", "not_implemented", "Moving targets do not receive the nearby-star pm/parallax model; needs verified ephemerides."),
                cap("Live access check", "not_run", "No request has been made from this build."),
            ],
            references=[
                Reference(title="CADC NEOSSat collection", url="https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/neossat/"),
                Reference(title="CADC public web services", url="https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/services/"),
                Reference(title="CSA NEOSSat mission overview", url="https://www.asc-csa.gc.ca/eng/satellites/neossat/"),
                Reference(title="CSA NEOSSat tutorial (check licence before reuse)", url="https://github.com/asc-csa/NEOSSAT_Tutorial"),
                Reference(title="CSA NEOSSat dataset record (timed out during the brief's review)", url="https://data.asc-csa.gc.ca/dataset/neossat"),
            ],
            notes=[DOC_NOTE, "A distinct observing system, not another SPHEREx band; simultaneous SPHEREx coverage is not assumed."],
            last_reviewed_utc=BRIEF_REVIEW_UTC,
        )

    def list_datasets(self) -> list[DatasetSummary]:
        return []

    def load_dataset(self, dataset_id: str, seed: int | None = None) -> DatasetBundle:
        raise ProviderUnavailable("neossat", "load_dataset", "not implemented in this build; see docs/providers/neossat.md")
