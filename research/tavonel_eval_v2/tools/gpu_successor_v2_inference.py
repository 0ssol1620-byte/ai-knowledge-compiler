#!/usr/bin/env python3
"""Paired inferential reducer for the prospective GPU successor V2 study."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

MATCH = "ANSWER_MATCHES_CURRENT"
TARGET_LINEAGES = 450


class InferenceRefused(RuntimeError):
    """The output cannot support one independent paired row per lineage."""


def exact_mcnemar_p_value(b: int, c: int) -> float:
    """Two-sided exact conditional McNemar p-value for discordant counts."""

    if min(b, c) < 0:
        raise InferenceRefused("discordant counts cannot be negative")
    discordant = b + c
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(b, c) + 1)) / (2**discordant)
    return min(1.0, 2.0 * tail)


def deterministic_paired_bootstrap_risk_difference_ci(
    *, b: int, c: int, n: int, alpha: float = 0.05
) -> tuple[float, float]:
    """Deterministic empirical paired-bootstrap percentile CI for risk difference.

    Each lineage contributes one value in ``{-1, 0, +1}``.  Dynamic
    programming enumerates the bootstrap distribution exactly; no Monte Carlo
    seed, model repeat, or unpaired approximation enters the interval.
    """

    if n < 1 or min(b, c) < 0 or b + c > n or not 0 < alpha < 1:
        raise InferenceRefused("invalid paired CI counts or alpha")
    probabilities = {-1: c / n, 0: (n - b - c) / n, 1: b / n}
    distribution: dict[int, float] = {0: 1.0}
    for _ in range(n):
        updated: defaultdict[int, float] = defaultdict(float)
        for total, mass in distribution.items():
            for value, probability in probabilities.items():
                if probability:
                    updated[total + value] += mass * probability
        distribution = dict(updated)

    def quantile(target: float) -> float:
        cumulative = 0.0
        for total in sorted(distribution):
            cumulative += distribution[total]
            if cumulative + 1e-15 >= target:
                return total / n
        return max(distribution) / n

    return quantile(alpha / 2), quantile(1 - alpha / 2)


def _primary_success(arm: dict[str, Any]) -> tuple[bool, bool]:
    repetitions = arm.get("repetitions")
    if not isinstance(repetitions, list) or not repetitions:
        raise InferenceRefused("arm has no deterministic repetition records")
    classes = [record.get("class") for record in repetitions if isinstance(record, dict)]
    if len(classes) != len(repetitions):
        raise InferenceRefused("arm repetition record is malformed")
    return classes[0] == MATCH, len(set(classes)) == 1


def paired_comparison(items: list[dict[str, Any]], *, arm_a: str, arm_b: str) -> dict[str, Any]:
    """Reduce exactly one preselected question per unique lineage."""

    seen: set[str] = set()
    b = c = both_success = both_failure = unstable = 0
    for item in items:
        lineage = item.get("lineage_id")
        if not isinstance(lineage, str) or not lineage or lineage in seen:
            raise InferenceRefused("lineage ids must be non-empty and unique")
        seen.add(lineage)
        arms = item.get("arms")
        if not isinstance(arms, dict) or arm_a not in arms or arm_b not in arms:
            raise InferenceRefused("paired arm result is absent")
        success_a, stable_a = _primary_success(arms[arm_a])
        success_b, stable_b = _primary_success(arms[arm_b])
        unstable += int(not stable_a or not stable_b)
        if success_a and not success_b:
            b += 1
        elif success_b and not success_a:
            c += 1
        elif success_a:
            both_success += 1
        else:
            both_failure += 1
    n = len(items)
    if n < TARGET_LINEAGES:
        raise InferenceRefused(f"{n} lineages do not meet the prospective target 450")
    estimate = (b - c) / n
    lower, upper = deterministic_paired_bootstrap_risk_difference_ci(b=b, c=c, n=n)
    return {
        "unit": "lineage",
        "n": n,
        "arm_a": arm_a,
        "arm_b": arm_b,
        "discordant_a_success": b,
        "discordant_b_success": c,
        "both_success": both_success,
        "both_failure": both_failure,
        "risk_difference": estimate,
        "risk_difference_ci_95": [lower, upper],
        "risk_difference_ci_method": "deterministic paired-bootstrap percentile",
        "mcnemar_exact_two_sided_p": exact_mcnemar_p_value(b, c),
        "unstable_lineages": unstable,
        "primary_generation": "repetition 0",
        "deterministic_repeats_counted_as_independent": False,
    }


def analyze(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "tavonel.v2.gpu_successor_inference.v2",
        "target_lineages": TARGET_LINEAGES,
        "currency": paired_comparison(items, arm_a="CURRENT_TYPED", arm_b="STALE_TYPED"),
        "representation_superiority": paired_comparison(
            items, arm_a="CURRENT_TYPED", arm_b="CURRENT_TEXT_ONLY"
        ),
    }


__all__ = [
    "TARGET_LINEAGES",
    "InferenceRefused",
    "analyze",
    "deterministic_paired_bootstrap_risk_difference_ci",
    "exact_mcnemar_p_value",
    "paired_comparison",
]
