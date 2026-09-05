"""Model and evaluator registry resolution for the public model arena.

`python -m arena.registry resolve` writes `model_registry.json` (ARENA_CONTRACT
section 3.7) and `evaluator_registry.json` (section 3.8) from the official
Hugging Face / GitHub APIs plus the frozen candidate specification in
``arena.registry.candidates``.

`python -m arena.registry validate` re-validates both files against the
`arena/core/schemas/*.schema.json` written by lane A1 when they exist, and
against the fallback schemas shipped here when they do not.

Nothing in this package invents data. A field the official source does not
document is written as ``null`` next to a ``*_unresolved_reason`` string.
"""

from __future__ import annotations

from arena.registry.candidates import CANDIDATES, CandidateSpec
from arena.registry.catalog import RUNPOD_GPU_CATALOG, RunPodGpu
from arena.registry.errors import RegistryError
from arena.registry.http import (
    CachedFetcher,
    FixtureStore,
    HttpFetcher,
    JsonFetcher,
    OfflineFetcher,
)

__all__ = [
    "CANDIDATES",
    "RUNPOD_GPU_CATALOG",
    "CachedFetcher",
    "CandidateSpec",
    "FixtureStore",
    "HttpFetcher",
    "JsonFetcher",
    "OfflineFetcher",
    "RegistryError",
    "RunPodGpu",
]
