"""Provider boundaries.

Image providers return observations and frame products; catalog providers
return CatalogSource records (Gaia is a catalog, not an image provider).
A provider that is not implemented or not reachable raises
ProviderUnavailable. Callers must surface that state; they must never
substitute synthetic data for a failed archive request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from skyshift.contracts import (
    CatalogSource,
    Dataset,
    DatasetSummary,
    Epoch,
    ProviderId,
    ProviderStatus,
    SimulationTruth,
    SkyPosition,
)


class ProviderUnavailable(RuntimeError):
    """Raised when a provider capability is not implemented or not reachable."""

    def __init__(self, provider: ProviderId, capability: str, reason: str) -> None:
        super().__init__(f"{provider}: {capability} unavailable - {reason}")
        self.provider = provider
        self.capability = capability
        self.reason = reason


@dataclass
class FrameArrays:
    """Original scientific arrays of one native frame (never display-stretched)."""

    image: np.ndarray  # float32 (ny, nx), unit = FrameProduct.unit
    variance: np.ndarray  # float32 (ny, nx), unit = FrameProduct.variance_unit
    mask: np.ndarray  # uint16 (ny, nx), bits = FrameProduct.mask_bits

    def __post_init__(self) -> None:
        if not (self.image.shape == self.variance.shape == self.mask.shape):
            raise ValueError("image, variance and mask must share a shape")


@dataclass
class DatasetBundle:
    """Everything a provider returns for one dataset.

    `arrays` is keyed by native FrameProduct.id. `catalog` holds reference
    sources (simulated for synthetic datasets). `truth` is only set for
    simulated datasets and must never be used as a measurement.
    """

    dataset: Dataset
    arrays: dict[str, FrameArrays]
    catalog: list[CatalogSource] = field(default_factory=list)
    catalog_name: str | None = None
    truth: SimulationTruth | None = None
    # Provider-specific objects needed by analyses (e.g. the validated SPHEREx SpectralImage per native frame id).
    extras: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class ImageProvider(Protocol):
    id: ProviderId

    def status(self) -> ProviderStatus: ...

    def list_datasets(self) -> list[DatasetSummary]: ...

    def load_dataset(self, dataset_id: str) -> DatasetBundle: ...


@runtime_checkable
class CatalogProvider(Protocol):
    id: ProviderId

    def status(self) -> ProviderStatus: ...

    def query_region(
        self, center: SkyPosition, radius_deg: float, observation_epochs: list[Epoch]
    ) -> list[CatalogSource]:
        """Return sources whose positions may fall in the field at any of the
        observation epochs (the caller pads `radius_deg` for proper motion)."""
        ...
