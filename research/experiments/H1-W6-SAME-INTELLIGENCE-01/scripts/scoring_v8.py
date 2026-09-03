#!/usr/bin/env python3
"""Scoring and paired statistics for W6 v8, defined before any arm is run.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §9, and PROTOCOL_V2 §8 and §9 which it
carries forward unchanged.

**Answer correctness and evidence correctness are separate outcomes.** An arm can
emit the right string from the superseded revision --- right answer, wrong
provenance --- and reporting that as a win would hide exactly the failure W6
exists to measure. `score_answer` therefore returns both, plus the explicit
`right_answer_stale_evidence` case, rather than one merged verdict.

**Abstention cannot be gamed in either direction.** Abstaining on an answerable
question is wrong; abstaining where the evidence genuinely does not determine an
answer is correct; answering confidently in that second case is an unsupported
assertion. An arm cannot win by refusing to answer and cannot win by guessing.

**No scipy.** The statistics are exact and written out: an exact binomial
McNemar over discordant pairs, and Newcombe's score interval for the difference
of paired proportions. A p-value is never reported alone --- every comparison
carries the absolute effect, the paired difference, its interval, and the
discordant counts that produced it, because `p < 0.05` on 4 discordant pairs and
on 400 are different findings that a p-value alone renders identical.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")
#: Thousands separators inside a number. Removed before tokenizing, because
#: `1,450` would otherwise tokenize to {"1", "450"} and `1450` to {"1450"}, and a
#: correct numeric answer would score wrong on formatting alone. The scorer's own
#: control caught this before any arm ran.
#: Built from code points so no ambiguous whitespace sits in the source.
_SEPARATORS = "," + chr(0x00A0) + chr(0x202F)
_THOUSANDS = re.compile(r"(?<=\d)[" + _SEPARATORS + r"](?=\d{3})")
MARKUP = {"br", "nbsp", "ref", "small", "sup", "sub", "nowrap", "flatlist", "plainlist"}


def normalize(text: str | None) -> frozenset[str]:
    """The shared answer normalizer. Every arm is scored through this one function.

    Markup tokens are dropped and numerals kept, the same rule the v8 generator
    uses to decide that a value changed. Using a different notion of equality in
    the scorer than in the generator would let a question be admitted as a value
    change and then scored as if it were not.
    """
    if not text:
        return frozenset()
    flattened = _THOUSANDS.sub("", text.lower())
    return frozenset(t for t in _WORD.findall(flattened) if t not in MARKUP)


@dataclass(frozen=True)
class Outcome:
    """One arm's result on one question. Every field is reported, none merged."""

    answer_correct: bool
    evidence_correct: bool
    right_answer_stale_evidence: bool
    temporal_correct: bool
    stale_answer: bool
    provenance_localized: bool
    unsupported_assertion: bool
    abstained: bool
    abstention_appropriate: bool

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def score_answer(*, response: dict[str, Any], gold_current: str, gold_as_of_before: str,
                 answerable: bool, cited_revision: str | None,
                 oracle_revision: str) -> Outcome:
    """Score one response.

    `cited_revision` is which revision the arm's evidence actually came from,
    supplied by the harness rather than parsed out of prose --- asking a model to
    self-report its provenance and then scoring that report would measure its
    candour, not its retrieval.
    """
    answer = normalize(response.get("answer"))
    current = normalize(gold_current)
    stale = normalize(gold_as_of_before)
    abstained = bool(response.get("abstained")) or not answer

    if abstained:
        appropriate = not answerable
        return Outcome(
            answer_correct=False, evidence_correct=False,
            right_answer_stale_evidence=False, temporal_correct=appropriate,
            stale_answer=False, provenance_localized=False,
            unsupported_assertion=False, abstained=True,
            abstention_appropriate=appropriate)

    answer_correct = bool(current) and answer == current
    # A value that changed is stale only when it matches the superseded value and
    # not the current one; when both revisions carry the same tokens the question
    # cannot separate them and calling it stale would be an unearned finding.
    stale_answer = bool(stale) and answer == stale and stale != current
    evidence_correct = cited_revision == oracle_revision

    return Outcome(
        answer_correct=answer_correct,
        evidence_correct=evidence_correct,
        right_answer_stale_evidence=answer_correct and not evidence_correct,
        temporal_correct=answer_correct and evidence_correct,
        stale_answer=stale_answer,
        provenance_localized=cited_revision is not None and evidence_correct,
        unsupported_assertion=not answerable,
        abstained=False,
        abstention_appropriate=False,
    )


# --- exact paired statistics, no dependency ---------------------------------

def _binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial test at p = 0.5. Used for McNemar."""
    if n == 0:
        return 1.0
    k = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def paired_comparison(a_name: str, b_name: str, a: list[bool],
                      b: list[bool]) -> dict[str, Any]:
    """Compare two arms paired by question.

    Newcombe's method for the interval: build Wilson intervals for each arm's
    rate and combine them with the paired correction. It is exact enough without
    scipy, it does not degenerate at 0 or 1 the way a Wald interval does, and it
    is deterministic --- a bootstrap would put a seed in the middle of a
    confirmatory endpoint.
    """
    if len(a) != len(b):
        raise ValueError("paired comparison requires equal-length outcome vectors")
    n = len(a)
    both = sum(1 for x, y in zip(a, b, strict=True) if x and y)
    only_a = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    only_b = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    neither = n - both - only_a - only_b
    discordant = only_a + only_b

    rate_a = sum(a) / n if n else 0.0
    rate_b = sum(b) / n if n else 0.0
    difference = rate_a - rate_b

    la, ua = _wilson(sum(a), n)
    lb, ub = _wilson(sum(b), n)
    # Newcombe's paired correction term.
    phi = 0.0
    if n and both + only_a and both + only_b and neither + only_a and neither + only_b:
        num = (both * neither - only_a * only_b) / n
        if num > 0:
            num -= 0.5
        den = math.sqrt((both + only_a) * (both + only_b)
                        * (neither + only_a) * (neither + only_b))
        phi = max(0.0, num) / den if den else 0.0
    lower = difference - math.sqrt(max(0.0, (rate_a - la) ** 2
                                       - 2 * phi * (rate_a - la) * (ub - rate_b)
                                       + (ub - rate_b) ** 2))
    upper = difference + math.sqrt(max(0.0, (ua - rate_a) ** 2
                                       - 2 * phi * (ua - rate_a) * (rate_b - lb)
                                       + (rate_b - lb) ** 2))

    return {
        "comparison": f"{a_name} vs {b_name}",
        "n_pairs": n,
        f"{a_name}_rate": round(rate_a, 4),
        f"{b_name}_rate": round(rate_b, 4),
        "absolute_effect": round(difference, 4),
        "paired_difference_ci95": [round(max(-1.0, lower), 4), round(min(1.0, upper), 4)],
        "ci_method": "Newcombe score interval for paired proportions",
        "discordant_pairs": {f"{a_name}_only": only_a, f"{b_name}_only": only_b,
                             "total": discordant},
        "concordant_pairs": {"both": both, "neither": neither},
        "mcnemar_exact_p": round(_binom_two_sided(only_a, discordant), 6),
        "mcnemar_method": "exact binomial on discordant pairs, p = 0.5",
        "reporting_rule": (
            "a p-value is never reported alone. p < 0.05 on 4 discordant pairs and on 400 "
            "are different findings, and the discordant counts above are what distinguishes "
            "them."
        ),
    }


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, Any]:
    """Holm-Bonferroni over the secondary endpoints. Frozen before the holdout."""
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    out: dict[str, Any] = {}
    rejected_so_far = True
    for i, (name, p) in enumerate(ordered):
        threshold = alpha / (m - i)
        rejected_so_far = rejected_so_far and p <= threshold
        out[name] = {"p": round(p, 6), "threshold": round(threshold, 6),
                     "significant": rejected_so_far}
    return {"alpha": alpha, "family_size": m, "results": out,
            "note": "step-down: once a hypothesis fails, every later one fails too"}


def scoring_control() -> dict[str, Any]:
    """The scorer must separate the cases it claims to separate, in this run."""
    base = {"gold_current": "1,450", "gold_as_of_before": "1,200", "answerable": True,
            "oracle_revision": "after"}
    right_right = score_answer(response={"answer": "1450"}, cited_revision="after", **base)
    right_stale = score_answer(response={"answer": "1,450"}, cited_revision="before", **base)
    stale_answer = score_answer(response={"answer": "1200"}, cited_revision="before", **base)
    abstain_bad = score_answer(response={"answer": None, "abstained": True},
                               cited_revision=None, **base)
    abstain_ok = score_answer(response={"answer": None, "abstained": True},
                              cited_revision=None,
                              **dict(base, answerable=False))
    guess_unanswerable = score_answer(response={"answer": "1450"}, cited_revision="after",
                                      **dict(base, answerable=False))
    markup = score_answer(response={"answer": "[[1,450]]<br />"}, cited_revision="after",
                          **base)

    checks = {
        "right_answer_right_evidence_is_temporally_correct": right_right.temporal_correct,
        "right_answer_stale_evidence_is_flagged": right_stale.right_answer_stale_evidence,
        "right_answer_stale_evidence_is_not_temporally_correct":
            not right_stale.temporal_correct,
        "stale_value_is_a_stale_answer": stale_answer.stale_answer,
        "stale_value_is_not_answer_correct": not stale_answer.answer_correct,
        "abstaining_on_an_answerable_question_is_wrong":
            not abstain_bad.answer_correct and not abstain_bad.abstention_appropriate,
        "abstaining_where_evidence_does_not_determine_is_correct":
            abstain_ok.abstention_appropriate,
        "answering_an_undetermined_question_is_an_unsupported_assertion":
            guess_unanswerable.unsupported_assertion,
        "markup_does_not_change_the_verdict": markup.answer_correct,
    }
    checks["separates"] = all(checks.values())
    return checks


def statistics_control() -> dict[str, Any]:
    """The test must find a real difference and must not invent one."""
    identical_a = [True] * 40 + [False] * 40
    identical_b = list(identical_a)
    same = paired_comparison("A", "B", identical_a, identical_b)

    better_a = [True] * 60 + [False] * 20
    better_b = [True] * 20 + [False] * 60
    differs = paired_comparison("A", "B", better_a, better_b)

    tiny_a = [True, False, False, False]
    tiny_b = [False, False, False, False]
    tiny = paired_comparison("A", "B", tiny_a, tiny_b)

    checks = {
        "identical_arms_have_no_discordant_pairs": same["discordant_pairs"]["total"] == 0,
        "identical_arms_are_not_significant": same["mcnemar_exact_p"] == 1.0,
        "identical_arms_have_zero_effect": same["absolute_effect"] == 0.0,
        "a_real_difference_is_detected": differs["mcnemar_exact_p"] < 0.05,
        "a_real_difference_has_nonzero_effect": differs["absolute_effect"] > 0.0,
        "one_discordant_pair_is_not_significant": tiny["mcnemar_exact_p"] > 0.05,
        "interval_covers_zero_when_arms_are_identical":
            same["paired_difference_ci95"][0] <= 0 <= same["paired_difference_ci95"][1],
    }
    checks["separates"] = all(checks.values())
    return checks
