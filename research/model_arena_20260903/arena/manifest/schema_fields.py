"""The frozen field whitelist for a ``source_manifest.jsonl`` row.

Ground Truth leakage is masterplan section 2.1's core failure mode. This
whitelist is the single place both the builder (constructs rows) and the
isolation audit (independently re-parses the written file) check against, so
a row can never silently grow a GT-shaped field (``expected_text``, ``rules``,
``labels``, ``scores``, ...).
"""

from __future__ import annotations

from typing import Final

SOURCE_ROW_SCHEMA: Final = "tavonel.arena.source-row.v1"

SOURCE_ROW_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "campaign_id",
        "benchmark",
        "staged_benchmark_id",
        "dataset_revision",
        "sample_id",
        "case_key",
        "original_source_relative_path",
        "original_source_sha256",
        "media_type",
        "page_index",
        "input_relative_path",
        "input_png_sha256",
        "width",
        "height",
        "bytes",
        "preflight",
    }
)

__all__ = ["SOURCE_ROW_FIELDS", "SOURCE_ROW_SCHEMA"]
