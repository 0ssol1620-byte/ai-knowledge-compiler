"""Scan configuration. Every tunable and estimate coefficient is explicit."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_EXCLUDED_DIRS = (
    ".git", ".hg", ".svn", ".tox", ".eggs", ".idea", ".vscode",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "node_modules", "bower_components", "vendor",
    "venv", ".venv", "env",
    "dist", "build", "target", "coverage", ".next", ".nuxt",
)

DEFAULT_SOURCE_SUFFIXES = (".md", ".markdown", ".mdx", ".txt", ".rst")


@dataclass(frozen=True)
class HealthScanConfig:
    """All knobs in one place; echoed verbatim into the report."""

    # directory names never descended into (inventory-wide)
    excluded_dir_names: frozenset[str] = frozenset(DEFAULT_EXCLUDED_DIRS)
    # extensions treated as knowledge-source candidates
    source_suffixes: frozenset[str] = frozenset(DEFAULT_SOURCE_SUFFIXES)
    # near-duplicate Jaccard threshold (character trigrams over normalized text)
    near_duplicate_threshold: float = 0.85
    # reporting caps (truncation is always noted in the section output)
    max_near_duplicate_pairs: int = 20
    max_near_dup_files: int = 2000
    # content reads above this size are skipped (bytes)
    max_content_bytes: int = 2_000_000
    # hashing above this size is skipped and recorded (bytes)
    max_hash_bytes: int = 64 * 1024 * 1024
    # --- estimated compile work coefficients ---
    # tokens ~= markdown_bytes / bytes_per_token * compile_overhead_factor
    # 3.6 B/token is a mixed Korean/English heuristic average
    bytes_per_token: float = 3.6
    chunk_target_tokens: int = 800
    compile_overhead_factor: float = 1.15

    def echo(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("excluded_dir_names", "source_suffixes"):
            data[key] = sorted(data[key])
        return data
