"""Frozen model-adapter interface.

Every runtime under runtimes/<model_key>/adapter.py implements
``ArenaModelAdapter``; the worker server (arena/worker/server.py) is the only
caller. The adapter never sees ground truth, never reads the network for
anything but its own pinned weights, and never silently substitutes a model.

Rules that are contract, not style:

- ``load`` must verify that the checkpoint revision it actually loaded equals
  ``cfg.model_revision`` or raise ``AdapterError("MODEL_LOAD", ...)``.
- ``infer`` returns the model's native output verbatim in ``raw_text``. The
  canonical markdown conversion lives in runtimes/<model_key>/canonical.py and
  may never add content the model did not emit.
- Any failure is raised as ``AdapterError`` with an ``error_class`` taken from
  ``arena.constants.ERROR_CLASSES`` so the worker classifies without guessing.
- No retries inside the adapter. Retry policy belongs to the controller
  (masterplan section 15.9).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class AdapterError(RuntimeError):
    """Raised by adapters. ``error_class`` must be one of ERROR_CLASSES."""

    def __init__(self, error_class: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{error_class}: {message}")
        self.error_class = error_class
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    model_key: str
    model_repo: str
    model_revision: str
    weights_dir: Path
    prompt_id: str
    prompt_text: str
    # Official per-model settings (resolution, max_tokens, ...), already frozen.
    inference_config: Mapping[str, Any]
    inference_config_sha256: str
    max_concurrency: int = 1
    device: str = "cuda:0"
    # sha256 ("sha256:<hex>") of the registry prompt file the worker resolved for
    # prompt_id. Added 2026-09-03 (ARENA_CONTRACT 11.5 D34): a toolkit-kind adapter
    # hashes the prompt its toolkit builds and fails closed when it differs.
    prompt_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class PageInput:
    inference_job_id: str
    # Section 9.2 official id, e.g. "omnidoc:images/PPT_1001115_eng_page_003".
    sample_id: str
    # Filesystem-safe key (the staged case_id), e.g. "omnidocbench-58851882e7b39101a6f5756c".
    case_key: str
    benchmark: str  # parsebench | omnidoc | olmocr
    image_path: Path  # PNG page render, source-only
    source_sha256: str  # "sha256:<hex>" of the PNG bytes
    width: int
    height: int
    # Non-GT metadata only (page_index, media_type).
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawOutput:
    raw_text: str  # verbatim model response
    output_format: str  # "markdown" | "html" | "json" | "text" | model-specific label
    native_json: Mapping[str, Any] | None  # model-specific structured output, if any
    usage: Mapping[str, Any]  # e.g. {"input_tokens": .., "output_tokens": ..} when available
    timings_ms: Mapping[str, int]  # preprocess_ms, inference_ms, postprocess_ms at minimum
    peak_vram_mb: int | None = None
    first_token_at: str | None = None  # ISO-8601 UTC when the runtime exposes it
    warnings: tuple[str, ...] = ()
    # Semantic verdict the adapter itself can see (OUTPUT_EMPTY | OUTPUT_TRUNCATED |
    # OUTPUT_REPETITION | OUTPUT_MALFORMED) or None. Added 2026-09-03 in the
    # integration pass; adapters that still emit the 'arena.semantic_error_class='
    # warning prefix are mapped by the worker server (ARENA_CONTRACT section 4).
    semantic_error_class: str | None = None


@dataclass(frozen=True, slots=True)
class LoadReceipt:
    model_key: str
    model_repo: str
    model_revision: str  # the revision actually loaded, verified
    weights_sha256_manifest: str  # sha256 over sorted (relative_path, file_sha256) pairs
    load_ms: int
    cache_hit: bool
    # Section 38 fields: versions, cuda, torch, pip_freeze_sha256, ...
    runtime_provenance: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class WarmupReceipt:
    warmup_ms: int
    output_chars: int
    schema_valid: bool
    peak_vram_mb: int | None


@dataclass(frozen=True, slots=True)
class CanonicalOutput:
    markdown: str
    # Optional element list for evaluators that consume structure.
    elements: tuple[Mapping[str, Any], ...] | None
    conversion_notes: tuple[str, ...] = ()
    # True when the conversion could not preserve something the model emitted.
    lossy: bool = False


@runtime_checkable
class ArenaModelAdapter(Protocol):
    model_key: str

    def load(self, cfg: AdapterConfig) -> LoadReceipt: ...

    def warmup(self, synthetic_image: Path) -> WarmupReceipt: ...

    def infer(self, page: PageInput) -> RawOutput: ...

    def runtime_provenance(self) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


@runtime_checkable
class Canonicalizer(Protocol):
    """runtimes/<model_key>/canonical.py exposes ``canonicalize``.

    Deterministic representation conversion only. It may reorder, unwrap or
    relabel what the model emitted; it may never fill a gap, infer a cell, or
    drop a warning about truncation.
    """

    def canonicalize(self, raw: RawOutput) -> CanonicalOutput: ...


__all__ = [
    "AdapterConfig",
    "AdapterError",
    "ArenaModelAdapter",
    "CanonicalOutput",
    "Canonicalizer",
    "LoadReceipt",
    "PageInput",
    "RawOutput",
    "WarmupReceipt",
]
