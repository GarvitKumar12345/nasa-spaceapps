"""SPHEREx (NASA/IPAC IRSA) image provider: discovery, bounded cutouts, R7 FITS validation,
and a read-only observed dataset built from a committed retrieval manifest.

Live access happens only in `skyshift.providers.spherex.fetch` (explicit command). The API
serves datasets from the manifest + local cache and never downloads during a browser action.
Quantitative analysis of SPHEREx pixels is not implemented; datasets declare it unavailable.
"""

from __future__ import annotations

import threading

from skyshift.contracts import DatasetSummary, ProviderCapability, ProviderStatus
from skyshift.providers.base import DatasetBundle, ProviderUnavailable
from skyshift.providers.spherex.fields import PRESETS
from skyshift.providers.spherex.reference import DOC_REVIEW_UTC, EXPECTED_EXTENSIONS_R7, REFERENCES

SPHEREX_EXPECTED_EXTENSIONS = EXPECTED_EXTENSIONS_R7

# Live tests whose recorded result (validation/report.json) sets the live capability status.
LIVE_TESTS = {
    "discovery": "test_live_sia_discovery_matches_manifest",
    "screening": "test_live_range_screening_matches_manifest",
    "cutout": "test_live_cutout_download_validates",
}


def check_extension_names(names: list[str]) -> list[str]:
    """Documented R7 extensions missing from a file's HDU names (case-insensitive). Read by name, never by position."""
    present = {n.strip().upper() for n in names}
    return [e for e in SPHEREX_EXPECTED_EXTENSIONS if e not in present]


def _live_status(test_name: str) -> tuple[str, str | None, str]:
    from skyshift.validation.report import load_report

    report = load_report()
    hits = [r for r in report.results if r.suite == "pytest" and r.id.endswith(test_name)]
    if not hits:
        return "not_run", None, "no recorded run of the live test"
    r = hits[0]
    if r.status == "passed":
        return "tested", report.generated_utc, f"live test {test_name} passed (validation report {report.generated_utc})"
    if r.status in ("failed", "error"):
        return "failed", report.generated_utc, f"live test {test_name} {r.status}: {(r.message or '')[:200]}"
    return "not_run", report.generated_utc, f"live test {test_name} {r.status} in the latest report (run with --live)"


def _cap(name: str, status: str, detail: str, checked: str | None = None) -> ProviderCapability:
    return ProviderCapability(name=name, status=status, detail=detail, checked_utc=checked)  # type: ignore[arg-type]


class SpherexProvider:
    id = "spherex"
    _lock = threading.Lock()
    _cache: dict[tuple[str, float], DatasetBundle] = {}

    def status(self) -> ProviderStatus:
        live = {k: _live_status(v) for k, v in LIVE_TESTS.items()}
        manifests = []
        from skyshift.providers.spherex.dataset import dataset_summary

        for p in PRESETS.values():
            s = dataset_summary(p)
            if s is not None:
                manifests.append(f"{p.id}: {s.n_available_frames}/{s.n_observations} cutouts cached ({s.availability})")
        return ProviderStatus(
            id="spherex",
            name="SPHEREx spectral images (NASA/IPAC IRSA)",
            role="image",
            status="implemented",
            release_policy="Explicit collection per dataset (this build: spherex_dr1 = DR1, R7 pipeline); release and processing tag kept per frame; "
                            "duplicate processing versions of one exposure are resolved by a stated rule and reported; QR1/QR2 refused.",
            access_route="IRSA SIA2 (COLLECTION=..., POS=CIRCLE) for discovery; HTTP byte ranges of the full files for screening; IBE cutout service for pixels. "
                         "Live access only through `python -m skyshift.providers.spherex.fetch`; the API reads the manifest + local cache.",
            capabilities=[
                _cap("Discovery (SIA2, explicit collection, bounded cone)", live["discovery"][0], live["discovery"][2], live["discovery"][1]),
                _cap("Pre-download screening (byte ranges: headers + WCS-WAVE)", live["screening"][0], live["screening"][2], live["screening"][1]),
                _cap("Cutout acquisition (IBE; cached; concurrency <= 4; retries)", live["cutout"][0], live["cutout"][2], live["cutout"][1]),
                _cap("FITS read by EXTNAME + R7 format validation", "implemented", "Units, flags (MSKN/MSKM vs ES Table 16), variance, TAN-SIP WCS, WCS-WAVE, timing, DQA keywords, EPSF format; offline tests on a real-file fixture."),
                _cap("Legacy QR1/QR2 products (PSF cube)", "implemented", "Explicitly refused (UnsupportedSpherexProduct); no separately tested handling exists."),
                _cap("Local wavelength at the field centre (WCS-WAVE)", "implemented", "Visualization-grade lookup with an independent bilinear cross-check; used for compatibility groups."),
                _cap("Spectral calibration products (CWAVE/CBAND)", "not_implemented", "Required before quantitative wavelength-dependent work."),
                _cap("Effective PSF evaluation", "not_implemented", "EPSF table recognised and recorded (zones, 5x oversampling); not evaluated."),
                _cap("Photometry / astrometry / registration / difference imaging", "not_implemented", "Unavailable for observed data; each dataset lists the requirements."),
            ],
            references=REFERENCES,
            notes=["Read-only viewer. Never substituted by synthetic data."] + manifests,
            last_reviewed_utc=DOC_REVIEW_UTC,
        )

    def list_datasets(self) -> list[DatasetSummary]:
        from skyshift.providers.spherex.dataset import dataset_summary

        return [s for s in (dataset_summary(p) for p in PRESETS.values()) if s is not None]

    def owns(self, dataset_id: str) -> bool:
        return dataset_id in PRESETS

    def load_dataset(self, dataset_id: str, seed: int | None = None) -> DatasetBundle:
        from skyshift.providers.spherex.dataset import build_bundle
        from skyshift.providers.spherex.paths import manifest_path

        preset = PRESETS.get(dataset_id)
        if preset is None:
            raise ProviderUnavailable("spherex", "load_dataset", f"unknown SPHEREx dataset {dataset_id!r}")
        path = manifest_path(dataset_id)
        if not path.exists():
            raise ProviderUnavailable("spherex", "load_dataset", f"no retrieval manifest for {dataset_id}; run the fetch command (docs/providers/spherex.md)")
        key = (dataset_id, path.stat().st_mtime)
        with self._lock:
            if key not in self._cache:
                self._cache.clear()
                self._cache[key] = build_bundle(preset)
            return self._cache[key]
