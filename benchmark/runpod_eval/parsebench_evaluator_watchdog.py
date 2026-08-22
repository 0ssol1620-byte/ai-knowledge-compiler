#!/usr/bin/env python3
"""Deterministic guard for pathological public ParseBench formatting rules.

The frozen evaluator's markup-tolerant regular expression can catastrophically
backtrack when a rule asks whether ``*`` or ``**`` is formatted and a candidate
contains a long run of escaped asterisks. The campaign integration records the
entire affected document as a conservative evaluator failure instead of
silently dropping it, inflating its score, or waiting forever.
"""

from __future__ import annotations

from typing import Any

GUARDED_RULE_TYPES = frozenset({"is_title", "is_bold", "is_italic"})
WATCHDOG_FAILURE = (
    "Pathological punctuation-only formatting query rejected by deterministic "
    "evaluation watchdog"
)


def has_pathological_formatting_query(
    test_case: dict[str, Any], candidate_markdown: str
) -> bool:
    """Return whether a rule/output pair contains the regex pathology."""
    unescaped = candidate_markdown.replace(r"\*", "*").replace(r"\_", "_")
    if not any(marker * 64 in unescaped for marker in ("*", "_", "~", "#", "`")):
        return False
    for rule in test_case.get("test_rules", []):
        if not isinstance(rule, dict) or rule.get("type") not in GUARDED_RULE_TYPES:
            continue
        text = rule.get("text")
        if (
            isinstance(text, str)
            and 0 < len(text) <= 2
            and not any(character.isalnum() for character in text)
        ):
            return True
    return False


__all__ = [
    "GUARDED_RULE_TYPES",
    "WATCHDOG_FAILURE",
    "has_pathological_formatting_query",
]
