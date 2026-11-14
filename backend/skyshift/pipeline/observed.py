"""Read-only session for observed (archive) datasets.

Serves the dataset contract and the original or display arrays. It runs no
detection, measurement, registration or differencing: those analyses are
declared unavailable by the dataset itself (`Dataset.capabilities`).
"""

from __future__ import annotations

import numpy as np

from skyshift.contracts import AnalysisCapability, FrameProduct
from skyshift.providers.base import DatasetBundle


class ObservedSession:
    def __init__(self, bundle: DatasetBundle) -> None:
        if bundle.dataset.origin != "observed":
            raise ValueError("ObservedSession is only for observed datasets")
        if bundle.truth is not None:
            raise ValueError("observed datasets never carry simulation truth")
        self.bundle = bundle
        self.dataset = bundle.dataset
        self.dataset_id = bundle.dataset.id
        self._products = {f.id: f for f in self.dataset.frames}

    def capability(self, cap_id: str) -> AnalysisCapability:
        for c in self.dataset.capabilities:
            if c.id == cap_id:
                return c
        return AnalysisCapability(id=cap_id, status="unavailable", reason=f"{cap_id} is not implemented for observed data in this build.")  # type: ignore[arg-type]

    def pixels(self, frame_id: str, plane: str) -> tuple[np.ndarray, FrameProduct]:
        prod = self._products[frame_id]
        if plane not in prod.planes:
            raise ValueError(f"{frame_id} provides the planes {prod.planes} only")
        arrays = self.bundle.arrays[frame_id]
        return {"image": arrays.image, "variance": arrays.variance, "mask": arrays.mask}[plane], prod
