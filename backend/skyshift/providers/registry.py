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


@lru_cache(maxsize=1)
def spherex_provider() -> SpherexProvider:
    return SpherexProvider()


def image_providers() -> list:
    return [synthetic_provider(), spherex_provider(), WiseProvider(), NeossatProvider()]


def provider_statuses() -> list[ProviderStatus]:
    """Order: synthetic, spherex, gaia_dr3, wise, neossat."""
    return [
        synthetic_provider().status(),
        spherex_provider().status(),
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


def dataset_provider(dataset_id: str) -> str:
    """'synthetic' or 'spherex' for a known dataset id; KeyError otherwise (no loading)."""
    if any(s.id == dataset_id for s in synthetic_provider().list_datasets()):
        return "synthetic"
    if spherex_provider().owns(dataset_id):
        return "spherex"
    raise KeyError(dataset_id)


def load_dataset(dataset_id: str, seed: int | None = None) -> DatasetBundle:
    """Load a dataset from the provider that owns it. Unknown ids raise KeyError.

    Archive datasets are never substituted by synthetic data: an archive
    provider that cannot serve a dataset raises ProviderUnavailable.
    """
    owner = dataset_provider(dataset_id)
    if owner == "synthetic":
        return synthetic_provider().load_dataset(dataset_id, seed)
    return spherex_provider().load_dataset(dataset_id)
