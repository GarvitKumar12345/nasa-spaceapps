"""Synthetic provider: deterministic in-process generator (the only implemented provider)."""

from __future__ import annotations

import threading

from skyshift.contracts import DatasetSummary, ProviderCapability, ProviderStatus, Reference
from skyshift.providers.base import DatasetBundle
from skyshift.synthetic.generator import DEFAULT_SEED, GENERATOR_VERSION, generate
from skyshift.synthetic.scenario import Scenario, default_scenario

_SCENARIOS: dict[str, Scenario] = {"syn-nb-01": default_scenario()}


class SyntheticProvider:
    id = "synthetic"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], DatasetBundle] = {}
        self._lock = threading.Lock()

    def status(self) -> ProviderStatus:
        cap = lambda name, detail: ProviderCapability(name=name, status="implemented", detail=detail)  # noqa: E731
        return ProviderStatus(
            id="synthetic",
            name="Synthetic training scenes",
            role="image+catalog",
            status="implemented",
            release_policy=f"Pinned: synthetic-v1 / generator {GENERATOR_VERSION}; seed recorded with every dataset and evidence record.",
            access_route="In-process deterministic generator (no network).",
            capabilities=[
                cap("Deterministic scene generation", "Seeded numpy SeedSequence streams per purpose and per frame."),
                cap("Image, variance and mask planes", "Electrons per exposure; variance estimated from the data; hot pixels, cosmic rays, saturation flagged."),
                cap("Simulated reference catalog", "Gaia-like format at J2016.0 TCB with noisy astrometry; labelled simulated, not Gaia data."),
                cap("Simulation truth separation", "Truth served only by the /truth endpoint and the evidence 'simulation' section."),
            ],
            references=[Reference(title="SkyShift architecture: synthetic scenario", url="docs/architecture.md#3-synthetic-investigation-syn-nb-01-exact-definition")],
            notes=["Training data only: no real sky. Never used as a fallback for a failed archive request."],
            last_reviewed_utc=None,
        )

    def list_datasets(self) -> list[DatasetSummary]:
        out = []
        for ds_id, sc in _SCENARIOS.items():
            n_obs = sum(len(v.status) for v in sc.visits)
            n_avail = sum(1 for v in sc.visits for s in v.status.values() if s[0] == "available")
            out.append(
                DatasetSummary(
                    id=ds_id,
                    title=sc.title,
                    provider="synthetic",
                    origin="simulated",
                    release=sc.release,
                    n_observations=n_obs,
                    n_available_frames=n_avail,
                    bands=[b.id for b in sc.bands],
                    time_range_utc=(sc.visits[0].start_utc, sc.visits[-1].start_utc),
                    description="Synthetic nearby-source training field (proper motion + parallax, a variable star, a close pair).",
                )
            )
        return out

    def load_dataset(self, dataset_id: str, seed: int | None = None) -> DatasetBundle:
        if dataset_id not in _SCENARIOS:
            raise KeyError(dataset_id)
        key = (dataset_id, DEFAULT_SEED if seed is None else int(seed))
        with self._lock:
            if key not in self._cache:
                self._cache[key] = generate(_SCENARIOS[dataset_id], key[1])
            return self._cache[key]
