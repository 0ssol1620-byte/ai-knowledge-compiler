"""Source adapters: turn upstream systems into resumable change-event streams.

Public surface:

* :class:`SourceAdapter` — the protocol every connector implements
  (``discover`` / ``fetch_changes`` / ``checkpoint``).
* :class:`ChangeEvent` — the deterministic, hashable envelope every event uses.
* :class:`Cursor` / :class:`FetchResult` — resume tokens and poll outputs.
* :class:`GitAdapter` — commit history via ``git log``, sha-addressed.
* :class:`ObsidianVaultAdapter` — polled notes, content-hash addressed.
* :class:`Freshness` — F0-F3 tiers with SLO constants and evaluation helpers.
"""

from __future__ import annotations

from akc_source_adapters.envelope import (
    CANONICAL_JSON_SEPARATORS,
    EVENT_HASH_PREFIX,
    ChangeEvent,
    Cursor,
    FetchResult,
    SourceAdapter,
    canonical_json,
    stable_hash,
    utc_now,
)
from akc_source_adapters.freshness import (
    FRESHNESS_DESCRIPTIONS,
    FRESHNESS_SLO_SECONDS,
    PROVIDER_DEFAULT_FRESHNESS,
    Freshness,
    FreshnessReport,
    classify_lag,
    evaluate_freshness,
)
from akc_source_adapters.git_adapter import (
    GitAdapter,
    GitAdapterError,
    GitCursorInvalid,
)
from akc_source_adapters.obsidian_adapter import (
    KIND_NOTE_ADDED,
    KIND_NOTE_CHANGED,
    KIND_NOTE_DELETED,
    NOTE_GLOB,
    NoteState,
    ObsidianVaultAdapter,
)

__version__ = "0.1.0"

__all__ = [
    "CANONICAL_JSON_SEPARATORS",
    "EVENT_HASH_PREFIX",
    "FRESHNESS_DESCRIPTIONS",
    "FRESHNESS_SLO_SECONDS",
    "KIND_NOTE_ADDED",
    "KIND_NOTE_CHANGED",
    "KIND_NOTE_DELETED",
    "NOTE_GLOB",
    "PROVIDER_DEFAULT_FRESHNESS",
    "ChangeEvent",
    "Cursor",
    "FetchResult",
    "Freshness",
    "FreshnessReport",
    "GitAdapter",
    "GitAdapterError",
    "GitCursorInvalid",
    "NoteState",
    "ObsidianVaultAdapter",
    "SourceAdapter",
    "canonical_json",
    "classify_lag",
    "evaluate_freshness",
    "stable_hash",
    "utc_now",
]
