"""§5.2 (3) identity collisions: normalized-title collisions."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from .inventory import FileRecord
from .models import HEURISTIC_LABEL

_STRIP = re.compile(r"[\W_]+", re.UNICODE)


def normalize_title(stem: str) -> str:
    """NFKC + casefold + strip punctuation/separators (hangul preserved)."""
    return _STRIP.sub("", unicodedata.normalize("NFKC", stem).casefold())


def stem_of(rel_path: str) -> str:
    return PurePosixPath(rel_path).stem


def analyze(records: list[FileRecord]) -> dict:
    grouped: dict[str, set[str]] = {}
    for record in records:
        key = normalize_title(stem_of(record.rel_path))
        if not key:
            continue
        grouped.setdefault(key, set()).add(record.rel_path)
    collisions = [
        {"normalized_title": title, "paths": sorted(paths)}
        for title, paths in sorted(grouped.items())
        if len(paths) > 1
    ]
    return {
        "label": HEURISTIC_LABEL,
        "normalization": "NFKC + casefold + remove punctuation/separators",
        "collisions": collisions,
    }
