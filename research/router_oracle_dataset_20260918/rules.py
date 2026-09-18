"""Deterministic feature, family and split rules for the Router Oracle Dataset (ROD-v1).

Kept apart from the builder so the rules can be tested without opening any Arena file.
The page class is derived from OmniDocBench ground-truth attributes and therefore stands in
for a PERFECT page classifier; a production preflight can only do worse.
"""

from __future__ import annotations

import hashlib
import re

SPLIT_SEED = "ROD-v1-split-2026-09-18"
SPLIT_BOUNDS = (("ROUTER_TRAIN", 60), ("ROUTER_CALIBRATION", 80), ("ROUTER_HOLDOUT", 100))
FAMILY_RE = re.compile(r"^(.*?)(?:_page_\d+|\.pdf_\d+)$")
DEGRADED_ISSUES = frozenset({"fuzzy_scan", "fuzzy_content", "geometric_deformation", "handwriting"})
MULTI_COLUMN_LAYOUTS = frozenset(
    {"double_column", "three_column", "1andmore_column", "other_layout"}
)
SCRIPT_FAMILY = {
    "english": "latin",
    "simplified_chinese": "han",
    "traditional_chinese": "han",
    "en_ch_mixed": "mixed",
}


def page_class(attribute: dict[str, object]) -> str:
    """DEGRADED > TABLE > FORMULA > MULTI_COLUMN > SIMPLE, in that priority."""
    issues = set(attribute.get("special_issue") or [])  # type: ignore[arg-type]
    subset = attribute.get("subset")
    if issues & DEGRADED_ISSUES:
        return "DEGRADED"
    if subset == "table_hard" or any(str(issue).startswith("table_") for issue in issues):
        return "TABLE"
    if subset == "equation_hard":
        return "FORMULA"
    if attribute.get("layout") in MULTI_COLUMN_LAYOUTS:
        return "MULTI_COLUMN"
    return "SIMPLE"


def script_family(language: object) -> str:
    return SCRIPT_FAMILY.get(str(language or ""), "other")


def family_of(image_name: str) -> str:
    """Pages of one source document share a family; a lone page is its own family."""
    stem = image_name.rsplit(".", 1)[0]
    match = FAMILY_RE.match(stem)
    return match.group(1) if match else stem


def split_of(family_id: str, *, seed: str = SPLIT_SEED) -> str:
    digest = hashlib.sha256(f"{seed}|{family_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    for name, upper in SPLIT_BOUNDS:
        if bucket < upper:
            return name
    raise AssertionError("unreachable: bucket is always below 100")


__all__ = ["SPLIT_SEED", "family_of", "page_class", "script_family", "split_of"]
