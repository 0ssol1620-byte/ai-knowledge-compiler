"""The deterministic answer scorer. Frozen before the first model call.

Four classes, and only one of them is a success:

    CURRENT_ONLY     the answer carries the current value and not the superseded one
    SUPERSEDED_ONLY  the answer carries the stale value
    BOTH             the answer carries both, and so has selected neither
    NO_MATCH         the answer carries neither

``BOTH`` being a failure is the point worth stating out loud. A model that
recites every value it was shown has not answered the question, and an endpoint
that scored it as a success would report currency selection where none happened.

There is no human adjudication, no LLM judge, and no normalization rule may be
touched after any model output has been seen. The controls at the bottom exist
so that "the scorer works" is a claim with evidence rather than an assumption.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

CURRENT_ONLY = "CURRENT_ONLY"
SUPERSEDED_ONLY = "SUPERSEDED_ONLY"
BOTH = "BOTH"
NO_MATCH = "NO_MATCH"

CLASSES = (CURRENT_ONLY, SUPERSEDED_ONLY, BOTH, NO_MATCH)

#: Only CURRENT_ONLY counts for the primary endpoint.
PRIMARY_SUCCESS = CURRENT_ONLY

#: Value-like shapes. The endpoint is *current-value* accuracy, so a marker has
#: to look like a value — a number, date, version, percentage, amount or
#: identifier — rather than any word that happens to have changed. A question
#: whose revisions differ only in prose has no value to select and is excluded
#: before the run rather than scored on a coin flip.
_VALUE_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                       # ISO date
    re.compile(r"\b\d+(?:\.\d+){1,3}\b"),                       # version / decimal chain
    re.compile(r"\b\d[\d,]*\.?\d*\s?%"),                        # percentage
    re.compile(r"[$€£¥]\s?\d[\d,]*(?:\.\d+)?"),                 # currency
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\b"),                      # plain number
    re.compile(r"\b[A-Za-z]+[-_]?\d[\w.-]*\b"),                 # identifier with a digit
)

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "‘’‛′"), "'")
_DQUOTES = dict.fromkeys(map(ord, "“”‟″"), '"')
_WHITESPACE = re.compile("[ \t\r\n\f\v ]+")


def normalise(text: str) -> str:
    """Case, unicode form, dashes, quotes, thousands separators, whitespace.

    Thousands separators go because ``1,450`` and ``1450`` are the same value
    written twice, and an endpoint that called them different would be measuring
    typography.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(_DASHES).translate(_QUOTES).translate(_DQUOTES)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    return _WHITESPACE.sub(" ", text).strip().casefold()


def value_tokens(text: str) -> set[str]:
    """Every value-like string in the text, normalised."""
    normalised = normalise(text)
    found: set[str] = set()
    for pattern in _VALUE_PATTERNS:
        for match in pattern.finditer(normalised):
            token = match.group(0).strip()
            if token:
                found.add(token)
    return found


def markers(current_text: str, superseded_text: str) -> dict[str, Any]:
    """The values that distinguish the two revisions, in each direction."""
    current = value_tokens(current_text)
    superseded = value_tokens(superseded_text)
    only_current = sorted(current - superseded)
    only_superseded = sorted(superseded - current)
    reasons: list[str] = []
    if not only_current:
        reasons.append("NO_DISTINGUISHING_CURRENT_VALUE")
    if not only_superseded:
        reasons.append("NO_DISTINGUISHING_SUPERSEDED_VALUE")
    if set(only_current) & set(only_superseded):
        reasons.append("MARKER_SETS_OVERLAP")
    return {
        "current": only_current,
        "superseded": only_superseded,
        "distinguishable": not reasons,
        "reasons": reasons,
    }


def _contains(answer: str, marker: str) -> bool:
    """Whole-token containment, so 42 does not match inside 4200."""
    if not marker:
        return False
    return re.search(r"(?<![\w.])" + re.escape(marker) + r"(?![\w])", answer) is not None


def classify(answer: str, current: list[str], superseded: list[str]) -> dict[str, Any]:
    """One of the four classes, with the markers that decided it."""
    normalised = normalise(answer)
    hit_current = [m for m in current if _contains(normalised, m)]
    hit_superseded = [m for m in superseded if _contains(normalised, m)]
    if hit_current and hit_superseded:
        label = BOTH
    elif hit_current:
        label = CURRENT_ONLY
    elif hit_superseded:
        label = SUPERSEDED_ONLY
    else:
        label = NO_MATCH
    return {
        "class": label,
        "primary_success": label == PRIMARY_SUCCESS,
        "current_markers_hit": hit_current,
        "superseded_markers_hit": hit_superseded,
    }


# --- controls, frozen with the scorer ----------------------------------------

CONTROLS: tuple[dict[str, Any], ...] = (
    {
        "name": "positive_current_value",
        "current": ["50"],
        "superseded": ["35"],
        "answer": "The permitted limit is 50 parts per million.",
        "expect": CURRENT_ONLY,
        "guards": "the ordinary success case",
    },
    {
        "name": "negative_superseded_value",
        "current": ["50"],
        "superseded": ["35"],
        "answer": "The permitted limit is 35 parts per million.",
        "expect": SUPERSEDED_ONLY,
        "guards": "the stale answer must not score as a success",
    },
    {
        "name": "ambiguous_both_values",
        "current": ["50"],
        "superseded": ["35"],
        "answer": "It was 35 parts per million and is now 50.",
        "expect": BOTH,
        "guards": "reciting both is not selecting one",
    },
    {
        "name": "no_value_at_all",
        "current": ["50"],
        "superseded": ["35"],
        "answer": "The sources do not state a limit.",
        "expect": NO_MATCH,
        "guards": "a refusal is not a current-value success",
    },
    {
        "name": "thousands_separator_is_the_same_value",
        "current": ["1450"],
        "superseded": ["1200"],
        "answer": "The figure is 1,450 units.",
        "expect": CURRENT_ONLY,
        "guards": "typography must not decide the endpoint",
    },
    {
        "name": "substring_is_not_a_match",
        "current": ["42"],
        "superseded": ["35"],
        "answer": "The identifier is 4200.",
        "expect": NO_MATCH,
        "guards": "42 inside 4200 is not the value 42",
    },
    {
        "name": "unicode_dash_and_case_are_normalised",
        "current": ["2026-04-01"],
        "superseded": ["2019-04-01"],
        "answer": "Effective 2026‐04‐01.",
        "expect": CURRENT_ONLY,
        "guards": "a unicode dash must not hide a date",
    },
    {
        "name": "decimal_precision_is_not_collapsed",
        "current": ["42.50"],
        "superseded": ["42.05"],
        "answer": "The amount is 42.05 USD.",
        "expect": SUPERSEDED_ONLY,
        "guards": "normalisation must not merge two genuinely different values",
    },
)

POSITIVE_CONTROL = "positive_current_value"
NEGATIVE_CONTROL = "negative_superseded_value"
AMBIGUOUS_CONTROL = "ambiguous_both_values"


def run_controls() -> dict[str, Any]:
    results = []
    for control in CONTROLS:
        got = classify(control["answer"], control["current"], control["superseded"])
        results.append(
            {
                "name": control["name"],
                "expected": control["expect"],
                "observed": got["class"],
                "agrees": got["class"] == control["expect"],
                "guards": control["guards"],
            }
        )
    index = {r["name"]: r for r in results}
    return {
        "results": results,
        "all_agree": all(r["agrees"] for r in results),
        "three_directions": {
            "positive": index[POSITIVE_CONTROL]["agrees"],
            "negative": index[NEGATIVE_CONTROL]["agrees"],
            "ambiguous": index[AMBIGUOUS_CONTROL]["agrees"],
            "passed": all(
                index[name]["agrees"]
                for name in (POSITIVE_CONTROL, NEGATIVE_CONTROL, AMBIGUOUS_CONTROL)
            ),
        },
    }
