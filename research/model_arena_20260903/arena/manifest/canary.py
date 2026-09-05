"""Canary selection (masterplan section 17, ``ARENA_CONTRACT.md`` section 1).

Deterministic, GT-blind: samples are ordered by ``sha256(sample_id + salt)``
ascending, never by anything derived from ground truth or an evaluator score.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

_SCHEMA = "tavonel.arena.canary-selection.v1"
_SELECTION_RULE = "sha256(sample_id + salt) hex ascending; first N per benchmark"


def _rank_key(sample_id: str, salt: str) -> str:
    return hashlib.sha256(f"{sample_id}{salt}".encode()).hexdigest()


def _selection_entry(row: Mapping[str, Any], rank: int) -> dict[str, Any]:
    return {
        "sample_id": row["sample_id"],
        "case_key": row["case_key"],
        "benchmark": row["benchmark"],
        "input_relative_path": row["input_relative_path"],
        "input_png_sha256": row["input_png_sha256"],
        "selection_rank": rank,
    }


def build_canary_selection(
    rows: Sequence[Mapping[str, Any]],
    *,
    campaign_id: str,
    salt: str,
    gpu_pages_per_benchmark: int,
    opus_canary_counts: Mapping[str, int],
) -> dict[str, Any]:
    if gpu_pages_per_benchmark <= 0:
        raise ValueError("gpu_pages_per_benchmark must be positive")

    by_benchmark: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_benchmark.setdefault(str(row["benchmark"]), []).append(row)

    gpu_samples: list[dict[str, Any]] = []
    opus_samples: list[dict[str, Any]] = []
    gpu_selected: dict[str, int] = {}
    opus_selected: dict[str, int] = {}

    for benchmark, benchmark_rows in sorted(by_benchmark.items()):
        ordered = sorted(benchmark_rows, key=lambda row: _rank_key(str(row["sample_id"]), salt))

        gpu_take = ordered[:gpu_pages_per_benchmark]
        gpu_selected[benchmark] = len(gpu_take)
        gpu_samples.extend(_selection_entry(row, rank) for rank, row in enumerate(gpu_take))

        opus_target = opus_canary_counts.get(benchmark)
        if opus_target is None:
            raise ValueError(f"no opus canary count configured for benchmark: {benchmark}")
        opus_take = ordered[:opus_target]
        opus_selected[benchmark] = len(opus_take)
        opus_samples.extend(_selection_entry(row, rank) for rank, row in enumerate(opus_take))

    return {
        "schema": _SCHEMA,
        "campaign_id": campaign_id,
        "salt": salt,
        "selection_rule": _SELECTION_RULE,
        "gpu_canary": {
            "pages_per_benchmark": gpu_pages_per_benchmark,
            "per_benchmark_selected": gpu_selected,
            "total_pages": len(gpu_samples),
            "samples": gpu_samples,
        },
        "opus_canary": {
            "per_benchmark_target": dict(opus_canary_counts),
            "per_benchmark_selected": opus_selected,
            "total_pages": len(opus_samples),
            "samples": opus_samples,
        },
    }


__all__ = ["build_canary_selection"]
