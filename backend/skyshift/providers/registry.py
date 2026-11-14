"""Provider registry: statuses for Methods and dataset routing for the API."""

from __future__ import annotations

from functools import lru_cache

from skyshift.contracts import DatasetSummary, ProviderStatus
from skyshift.providers.base import DatasetBundle, ProviderUnavailable
from skyshift.providers.extensions import NeossatProvider, WiseProvider
from skyshift.providers.gaia_dr3 import GaiaDR3Provider
from skyshift.providers.spherex import SpherexProvider
from skyshift.providers.synthetic import SyntheticProvider


@lru_cache(maxsize=1)
def synthetic_provider() -> SyntheticProvider:
    return SyntheticProvider()


def image_providers() -> list:
    return [synthetic_provider(), SpherexProvider(), WiseProvider(), NeossatProvider()]


def provider_statuses() -> list[ProviderStatus]:
    """Order: synthetic, spherex, gaia_dr3, wise, neossat."""
    return [
        synthetic_provider().status(),
        SpherexProvider().status(),
        GaiaDR3Provider().status(),
        WiseProvider().status(),
        NeossatProvider().status(),
    ]


def list_datasets() -> list[DatasetSummary]:
    out: list[DatasetSummary] = []
    for provider in image_providers():
        try:
            out.extend(provider.list_datasets())
        except ProviderUnavailable:
            continue
    return out


def load_dataset(dataset_id: str, seed: int | None = None) -> DatasetBundle:
    """Load a dataset from the provider that lists it. Unknown ids raise KeyError.

    Archive datasets are never substituted by synthetic data: an archive
    provider that cannot serve a dataset raises ProviderUnavailable.
    """
    for summary in synthetic_provider().list_datasets():
        if summary.id == dataset_id:
            return synthetic_provider().load_dataset(dataset_id, seed)
    raise KeyError(dataset_id)
