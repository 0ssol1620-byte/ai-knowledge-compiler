#!/usr/bin/env python3
"""Frozen, deterministic answer scorer for the GPU successor V2 worker.

The expected answer is never inferred from prompt text.  It must be carried as
an explicit typed value in the sealed input item.  Equality follows the
SOURCE_FACT_IR rule: JSON values compare through canonical JSON.  The only
text normalization outside JSON parsing is removal of surrounding whitespace.
"""

from __future__ import annotations

import json
from typing import Any

ANSWER_MATCHES_CURRENT = "ANSWER_MATCHES_CURRENT"
ANSWER_REFUSED = "ANSWER_REFUSED"
ANSWER_OTHER = "ANSWER_OTHER"
SCORER_CLASSES = (ANSWER_MATCHES_CURRENT, ANSWER_REFUSED, ANSWER_OTHER)

# The prompt mandates the first spelling.  The remaining exact, case-folded
# forms implement the protocol's predeclared semantic refusal class without a
# learned judge or an outcome-dependent synonym expansion.
REFUSAL_FORMS = frozenset(
    {
        "not stated",
        "not stated.",
        "cannot determine",
        "cannot determine.",
        "the information is not present",
        "the information is not present.",
        "i cannot determine the answer from the given context",
        "i cannot determine the answer from the given context.",
    }
)


class ScoringRefused(ValueError):
    """The sealed input does not contain an exact, scoreable target."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def expected_value(item: dict[str, Any]) -> Any:
    """Return the explicit current typed value; absence is a hard refusal."""
    if "current_expected_value" in item:
        value = item["current_expected_value"]
    elif "representation" in item:
        value = item["representation"]
    else:
        raise ScoringRefused(
            "materialized item has no current_expected_value or representation; "
            "the answer cannot be reconstructed from prompts"
        )
    if value is None:
        raise ScoringRefused("current expected value is null")
    # Prove JSON serializability now, rather than producing an unrepeatable
    # comparison later.
    canonical_json(value)
    return value


def _answer_value(text: str) -> tuple[bool, Any]:
    stripped = text.strip()
    try:
        return True, json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return False, stripped


def classify_answer(response_text: str, current_expected_value: Any) -> str:
    """Classify one raw answer using only the frozen three-way rule."""
    if not isinstance(response_text, str):
        raise TypeError("response_text must be a string")
    if current_expected_value is None:
        raise ScoringRefused("current expected value is null")
    canonical_json(current_expected_value)
    stripped = response_text.strip()
    if stripped.casefold() in REFUSAL_FORMS:
        return ANSWER_REFUSED

    parsed, answer = _answer_value(response_text)
    if parsed:
        matches = canonical_json(answer) == canonical_json(current_expected_value)
    elif isinstance(current_expected_value, str):
        matches = answer == current_expected_value
    else:
        matches = False
    return ANSWER_MATCHES_CURRENT if matches else ANSWER_OTHER


def score_item(item: dict[str, Any], responses_by_arm: dict[str, list[str]]) -> dict[str, Any]:
    """Score all repetitions while retaining the exact current value digest."""
    expected = expected_value(item)
    scored: dict[str, Any] = {}
    for arm in ("CURRENT_TYPED", "STALE_TYPED", "CURRENT_TEXT_ONLY"):
        responses = responses_by_arm.get(arm)
        if not isinstance(responses, list) or not responses:
            raise ScoringRefused(f"arm {arm} has no responses")
        classes = [classify_answer(text, expected) for text in responses]
        scored[arm] = {"classes": classes, "deterministic": len(set(classes)) == 1}
    return {
        "expected_value_sha256": _sha_text(canonical_json(expected)),
        "arms": scored,
    }


def _sha_text(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "ANSWER_MATCHES_CURRENT",
    "ANSWER_OTHER",
    "ANSWER_REFUSED",
    "REFUSAL_FORMS",
    "SCORER_CLASSES",
    "ScoringRefused",
    "canonical_json",
    "classify_answer",
    "expected_value",
    "score_item",
]
