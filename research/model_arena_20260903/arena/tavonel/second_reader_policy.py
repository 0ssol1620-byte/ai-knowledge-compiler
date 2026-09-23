"""Second-reader agreement / abstention policy, SRP-1 (ADR-007 §Pre-registration).

A pure function over two transcriptions of the same page. It opens no file,
reads no score and cannot see an answer key: every input is something a
production caller already holds after both readers have run.

The rule has exactly two outcomes, and neither of them picks a winner:

* ``ACCEPT_PRIMARY_ON_AGREEMENT`` — the primary's output proceeds, recorded as
  having been independently re-read within the agreement bound.
* ``ABSTAIN`` — the page is not auto-accepted. Which reader was right is not
  knowable here, so this module never substitutes the second reader's text.

What agreement is **not**: evidence that either reader is right. Two readers
can agree on the same mistake, and the 2026-09-06 study measured that they do
(both wrong on 11.4% of text pages and 44.7% of formula pages). Whatever the
metric properties of the distance below, bounding a reader's error from
agreement would need the other reader's error, which is unobservable when the
decision is made. ``AGREEMENT_THRESHOLD`` is therefore an uncalibrated
heuristic; no guarantee is derived from it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final, Literal

from arena.tavonel import features
from arena.tavonel.policies import Threshold

POLICY_VERSION: Final = "tavonel-second-reader-policy.srp1.v1"

ACCEPT: Final = "ACCEPT_PRIMARY_ON_AGREEMENT"
ABSTAIN: Final = "ABSTAIN"
Decision = Literal["ACCEPT_PRIMARY_ON_AGREEMENT", "ABSTAIN"]

# Exact rational, so ``edit / max_len <= 1/10`` is decided in integers and no
# float rounding can move a page across the line.
_THRESHOLD_FRACTION: Final = Fraction(1, 10)
AGREEMENT_THRESHOLD: Final = Threshold(
    name="second_reader_max_normalized_edit",
    value=float(_THRESHOLD_FRACTION),
    rationale=(
        "Twice the study's tau=0.05 wrong-page line, so two readers each within "
        "tau of the same text are not forced to abstain. A heuristic: no "
        "triangle-inequality or error-bound argument is claimed for it."
    ),
)

# Above this the comparison is refused rather than truncated: agreement on a
# prefix is not agreement on the page. Same order as disagreement.py's cap.
MAX_COMPARE_CHARS: Final = 20_000

# Only structural truncation signals abstain. ``ends_mid_sentence`` is left out
# on purpose: pages legitimately end on a heading, a caption or a table cell.
STRONG_TRUNCATION_SIGNALS: Final = frozenset(
    {"unclosed_code_fence", "unclosed_html_table", "ends_mid_table_row", "output_tokens_at_max"}
)


@dataclass(frozen=True, slots=True)
class ReaderOutput:
    """One reader's canonical text for a page, with its exact pinned identity."""

    reader_id: str
    revision: str
    text: str
    output_tokens_at_max: bool | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return (self.reader_id, self.revision)


@dataclass(frozen=True, slots=True)
class SecondReaderVerdict:
    decision: Decision
    reasons: tuple[str, ...]
    # Exact Levenshtein distance when it was computed and within ``edit_bound``;
    # ``None`` when a gate fired first or the distance exceeded the bound.
    edit_distance: int | None
    edit_bound: int | None
    compared_chars: tuple[int, int]
    primary: tuple[str, str]
    second: tuple[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "compared_chars": list(self.compared_chars),
            "decision": self.decision,
            "edit_bound": self.edit_bound,
            "edit_distance": self.edit_distance,
            "policy_version": POLICY_VERSION,
            "primary": list(self.primary),
            "reasons": list(self.reasons),
            "second": list(self.second),
            "threshold": AGREEMENT_THRESHOLD.as_dict(),
        }


def bounded_levenshtein(left: str, right: str, bound: int) -> int:
    """Levenshtein distance if it is ``<= bound``, otherwise ``bound + 1``.

    Ukkonen's diagonal band: O(bound * len) instead of O(len * len), which is
    what keeps a 20,000-character page affordable in pure Python.
    """
    if bound < 0:
        raise ValueError("bound must be non-negative")
    over = bound + 1
    n, m = len(left), len(right)
    if abs(n - m) > bound:
        return over
    prev = [j if j <= bound else over for j in range(m + 1)]
    cur = [over] * (m + 1)
    for i in range(1, n + 1):
        lo = max(1, i - bound)
        hi = min(m, i + bound)
        cur[lo - 1] = i if lo == 1 and i <= bound else over
        row_min = cur[lo - 1]
        char = left[i - 1]
        for j in range(lo, hi + 1):
            value = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (char != right[j - 1]))
            if value > over:
                value = over
            cur[j] = value
            if value < row_min:
                row_min = value
        # The next row reads prev[hi + 1]; it must not be a stale value.
        if hi + 1 <= m:
            cur[hi + 1] = over
        if row_min > bound:
            return over
        prev, cur = cur, prev
    return min(prev[m], over)


def _gate_reasons(side: str, output: ReaderOutput, normalized: str) -> list[str]:
    reasons: list[str] = []
    if not normalized:
        reasons.append(f"{side}_empty_output")
        return reasons
    truncation = features.truncation_evidence(
        output.text, output_tokens_at_max=output.output_tokens_at_max
    )
    if STRONG_TRUNCATION_SIGNALS.intersection(truncation):
        reasons.append(f"{side}_truncation_suspected")
    if features.matched_boilerplate(output.text):
        reasons.append(f"{side}_hallucinated_boilerplate")
    if len(normalized) > MAX_COMPARE_CHARS:
        reasons.append(f"{side}_too_long_to_compare")
    return reasons


def decide(primary: ReaderOutput, second: ReaderOutput) -> SecondReaderVerdict:
    """Apply SRP-1 to one page. Fails closed: any doubt is ``ABSTAIN``."""
    for output in (primary, second):
        if not output.reader_id or not output.revision:
            raise ValueError("a reader without a pinned id and revision cannot be compared")
    if primary.reader_id == second.reader_id:
        # A new revision of the same model is still the same reader family.
        # SRP-1 measures agreement between distinct model choices.
        raise ValueError(f"primary and second reader are the same model {primary.reader_id}")

    left = features.normalize_text(primary.text)
    right = features.normalize_text(second.text)
    compared = (len(left), len(right))
    reasons = _gate_reasons("primary", primary, left) + _gate_reasons("second", second, right)
    if reasons:
        return SecondReaderVerdict(
            ABSTAIN, tuple(reasons), None, None, compared, primary.identity, second.identity
        )

    bound = math.floor(max(compared) * _THRESHOLD_FRACTION)
    distance = bounded_levenshtein(left, right, bound)
    if distance > bound:
        return SecondReaderVerdict(
            ABSTAIN,
            ("readers_disagree",),
            None,
            bound,
            compared,
            primary.identity,
            second.identity,
        )
    return SecondReaderVerdict(
        ACCEPT, ("readers_agree",), distance, bound, compared, primary.identity, second.identity
    )


def policy_parameters() -> dict[str, Any]:
    """Everything the decision depends on, for freezing beside the decisions."""
    return {
        "distance": "levenshtein(normalize_text(a), normalize_text(b)) / max(len)",
        "feature_set_version": features.FEATURE_SET_VERSION,
        "max_compare_chars": MAX_COMPARE_CHARS,
        "policy_version": POLICY_VERSION,
        "strong_truncation_signals": sorted(STRONG_TRUNCATION_SIGNALS),
        "threshold": AGREEMENT_THRESHOLD.as_dict(),
    }


__all__ = [
    "ABSTAIN",
    "ACCEPT",
    "AGREEMENT_THRESHOLD",
    "MAX_COMPARE_CHARS",
    "POLICY_VERSION",
    "STRONG_TRUNCATION_SIGNALS",
    "ReaderOutput",
    "SecondReaderVerdict",
    "bounded_levenshtein",
    "decide",
    "policy_parameters",
]
