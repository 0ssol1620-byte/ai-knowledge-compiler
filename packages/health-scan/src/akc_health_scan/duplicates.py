"""§5.2 (2) duplicates: exact sha256 clusters + trigram-Jaccard near pairs."""

from __future__ import annotations

import re
import unicodedata
from itertools import combinations
from typing import Any

from . import inventory
from .config import HealthScanConfig
from .inventory import FileRecord
from .models import HEURISTIC_LABEL

_WHITESPACE = re.compile(r"\s+")


def char_trigrams(text: str) -> frozenset[str]:
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().lower()
    if len(normalized) < 3:
        return frozenset()
    return frozenset(normalized[i : i + 3] for i in range(len(normalized) - 2))


def analyze(
    records: list[FileRecord],
    digests: dict[str, str],
    config: HealthScanConfig,
    skipped_hashing: list[dict[str, str]],
) -> dict[str, Any]:
    # --- exact duplicate clusters -----------------------------------------
    by_digest: dict[str, list[str]] = {}
    for rel_path, hex_digest in digests.items():
        by_digest.setdefault(hex_digest, []).append(rel_path)
    exact_clusters = [
        {
            "digest": f"sha256:{hex_digest}",
            "size_bytes": next(
                r.size_bytes
                for r in records
                if r.rel_path == sorted(paths)[0]
            ),
            "paths": sorted(paths),
        }
        for hex_digest, paths in sorted(by_digest.items())
        if len(paths) > 1
    ]

    # --- near duplicates (character-trigram Jaccard over source docs) ------
    universe = [
        r
        for r in records
        if r.suffix in config.source_suffixes and r.rel_path in digests
    ]
    skipped_large = [s["path"] for s in skipped_hashing if s["path"].endswith(
        tuple(config.source_suffixes)
    )]
    truncated_universe = len(universe) > config.max_near_dup_files
    if truncated_universe:
        universe = sorted(universe, key=lambda r: r.rel_path)[: config.max_near_dup_files]

    trigram_sets: dict[str, frozenset[str]] = {}
    for record in universe:
        text = inventory.read_text(record, config)
        grams = char_trigrams(text) if text is not None else frozenset()
        if grams:
            trigram_sets[record.rel_path] = grams

    raw_pairs: list[tuple[float, str, str]] = []
    for left, right in combinations(sorted(trigram_sets), 2):
        set_a, set_b = trigram_sets[left], trigram_sets[right]
        smaller, larger = sorted((len(set_a), len(set_b)))
        if smaller / larger < config.near_duplicate_threshold:
            continue  # jaccard <= min/max upper bound already below threshold
        intersection = len(set_a & set_b)
        jaccard = intersection / (smaller + larger - intersection)
        if jaccard >= config.near_duplicate_threshold:
            raw_pairs.append((jaccard, left, right))
    raw_pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    pairs_truncated = len(raw_pairs) > config.max_near_duplicate_pairs
    near_pairs = [
        {"a": a, "b": b, "jaccard": round(j, 4)}
        for j, a, b in raw_pairs[: config.max_near_duplicate_pairs]
    ]

    return {
        "label": HEURISTIC_LABEL,
        "exact_duplicate_clusters": exact_clusters,
        "near_duplicate_pairs": near_pairs,
        "threshold": config.near_duplicate_threshold,
        "compared_files": len(trigram_sets),
        "skipped_large_files": sorted(skipped_large),
        "truncated": {
            "universe_capped": truncated_universe,
            "pairs_capped": pairs_truncated,
        },
        "note": (
            "near-duplicate = character-trigram Jaccard >= threshold over "
            "NFKC/casefold/whitespace-normalized source-suffix text"
        ),
    }
