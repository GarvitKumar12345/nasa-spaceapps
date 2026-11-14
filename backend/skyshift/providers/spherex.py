"""SPHEREx (NASA/IPAC IRSA) image provider boundary — documented, not implemented.

Planned route (docs/providers/spherex.md): IRSA SIA discovery with
astroquery.ipac.irsa.Irsa and TAP cutouts (spherex.artifact joined to
spherex.plane), an explicitly selected release (the tutorials recommend
DR1/QR3 over QR2; confirm live), FITS extensions read by name, version-aware
ePSF handling, and CWAVE/CBAND for quantitative wavelengths. Nothing here
contacts IRSA; every data method raises ProviderUnavailable.
"""

from __future__ import annotations

from skyshift.contracts import DatasetSummary, ProviderStatus, Reference
from skyshift.providers.archive_common import BRIEF_REVIEW_UTC, DOC_NOTE, cap
from skyshift.providers.base import DatasetBundle, ProviderUnavailable

# Extension names of a SPHEREx spectral-image file as described in the IRSA data-product
# documentation reviewed for the brief. To be verified against a real file before use.
SPHEREX_EXPECTED_EXTENSIONS: tuple[str, ...] = ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "PSF", "WCS-WAVE")
RELEASE_POLICY = (
    "Not selected. Select one collection/release explicitly after a live capability check (tutorials recommend DR1/QR3 "
    "over QR2); never mix processing versions of the same exposure; store release and processing version per frame."
)
REFERENCES = [
    Reference(title="NASA/IPAC IRSA SPHEREx resources", url="https://irsa.ipac.caltech.edu/Missions/spherex.html"),
    Reference(title="SPHEREx archive access documentation", url="https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/"),
    Reference(title="SPHEREx data-product documentation", url="https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/"),
    Reference(title="IRSA tutorial: SPHEREx spectral image introduction", url="https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/"),
    Reference(title="IRSA tutorial: SPHEREx spectral image cutouts", url="https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/"),
    Reference(title="IRSA tutorial: SPHEREx effective PSF", url="https://caltech-ipac.github.io/irsa-tutorials/spherex-psf/"),
]


def check_extension_names(names: list[str]) -> list[str]:
    """Expected extensions missing from a file's HDU names (case-insensitive). Read by name, never by position."""
    present = {n.strip().upper() for n in names}
    return [e for e in SPHEREX_EXPECTED_EXTENSIONS if e not in present]


class SpherexProvider:
    id = "spherex"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            id="spherex",
            name="SPHEREx spectral images (NASA/IPAC IRSA)",
            role="image",
            status="documented",
            release_policy=RELEASE_POLICY,
            access_route="Planned: IRSA SIA (astroquery.ipac.irsa.Irsa) for discovery; IRSA TAP spherex.artifact JOIN spherex.plane for cutout URIs and timing.",
            capabilities=[
                cap("Discovery (SIA, bounded cone)", "not_implemented", "Small bounded queries with collection enumeration; cache results; cap concurrency."),
                cap("Cutout acquisition (TAP)", "not_implemented", "Cutout URI and observation-time metadata via spherex.artifact/spherex.plane; inspect the schema live first."),
                cap("Release/version selection", "not_implemented", "Explicit collection; keep release + processing version with each frame; no silent mixing."),
                cap("FITS parsing by extension name", "not_implemented", f"Expected extensions {', '.join(SPHEREX_EXPECTED_EXTENSIONS)} (to verify on a real file)."),
                cap("Surface-brightness units and zodiacal background", "not_implemented", "IMAGE is surface brightness including zodiacal light; never treat as point-source flux or subtract background twice."),
                cap("Effective PSF (version-aware)", "not_implemented", "Respect spatial zone, oversampling and sub-pixel position; do not double-integrate pixel response; QR2 legacy needs separate tested handling."),
                cap("Wavelength at source position", "not_implemented", "WCS-WAVE for visualisation; CWAVE/CBAND for quantitative work; compatibility checked at the source position."),
                cap("Live query + cutout download check", "not_run", "No live request has been made from this build."),
            ],
            references=REFERENCES,
            notes=[DOC_NOTE, "Not connected: the Observatory cannot load SPHEREx data in this build."],
            last_reviewed_utc=BRIEF_REVIEW_UTC,
        )

    def list_datasets(self) -> list[DatasetSummary]:
        return []

    def load_dataset(self, dataset_id: str, seed: int | None = None) -> DatasetBundle:
        raise ProviderUnavailable("spherex", "load_dataset", "not implemented in this build; see docs/providers/spherex.md")

    def discover(self, *args: object, **kwargs: object) -> list:
        raise ProviderUnavailable("spherex", "discover", "not implemented in this build; see docs/providers/spherex.md")
