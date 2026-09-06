"""Does GT-free disagreement predict evaluator failure? (MP sections 27 and 46)

This is the only step in the lane that runs *after* official scoring, and it
exists to answer one question honestly. The 2026-08 FOLYNTA campaign already
published a negative result of exactly this shape: blind quality ranking never
beat ranking by length alone at finding the documents that failed. If that
happens again, this module writes it down as ``NOT_SUPPORTED`` — a failed
hypothesis is evidence, and deleting it would be the dishonest move.

Both support thresholds are named parameters with ``calibrated: false``. They
decide how the finding is *labelled*, never what the numbers are.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.tavonel import guards, jsonio
from arena.tavonel.errors import MissingInputError
from arena.tavonel.oracle import load_official_scores
from arena.tavonel.outputs import discover_output_models
from arena.tavonel.paths import ArenaPaths

CORRELATION_SCHEMA = "tavonel.arena.disagreement-correlation.v1"

MIN_ABS_SPEARMAN_FOR_SUPPORT: Final = 0.30
MIN_CAPTURE_RATIO_FOR_SUPPORT: Final = 0.50
FAILURE_SCORE_THRESHOLD: Final = 0.50
CAPTURE_BUDGET_FRACTION: Final = 0.10

SUPPORT_PARAMETERS: Final = (
    {
        "calibrated": False,
        "name": "min_abs_spearman_for_support",
        "rationale": (
            "weakest rank correlation still worth routing on; the sign must be negative, "
            "since the hypothesis is that more disagreement means a lower score"
        ),
        "value": MIN_ABS_SPEARMAN_FOR_SUPPORT,
    },
    {
        "calibrated": False,
        "name": "min_capture_ratio_for_support",
        "rationale": "share of the oracle's failure capture the blind ranking must reach",
        "value": MIN_CAPTURE_RATIO_FOR_SUPPORT,
    },
    {
        "calibrated": False,
        "name": "failure_score_threshold",
        "rationale": "official per-case score below which the page counts as a failure",
        "value": FAILURE_SCORE_THRESHOLD,
    },
    {
        "calibrated": False,
        "name": "capture_budget_fraction",
        "rationale": "share of pages a recovery budget could afford to re-run",
        "value": CAPTURE_BUDGET_FRACTION,
    },
)


@dataclass(frozen=True, slots=True)
class CorrelationReport:
    path: Path
    model_key: str
    cases_used: int
    finding: str
    best_metric: str | None
    best_spearman: float | None


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks, so ties do not invent an ordering."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = average
        position = end + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation, or ``None`` when it is undefined."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rank_x = _ranks(xs)
    rank_y = _ranks(ys)
    n = float(len(xs))
    mean_x = sum(rank_x) / n
    mean_y = sum(rank_y) / n
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(rank_x, rank_y, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rank_x)
    var_y = sum((b - mean_y) ** 2 for b in rank_y)
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    return round(covariance / math.sqrt(var_x * var_y), 6)


def _blind_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Per-case blind aggregates over every pair the target model appears in."""
    similarities: list[float] = []
    reading_order: list[float] = []
    numbers: list[float] = []
    one_empty = 0.0
    one_truncated = 0.0
    for row in rows:
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            continue
        value = metrics.get("text_similarity")
        if isinstance(value, int | float) and not isinstance(value, bool):
            similarities.append(float(value))
        value = metrics.get("reading_order_disagreement")
        if isinstance(value, int | float) and not isinstance(value, bool):
            reading_order.append(float(value))
        value = metrics.get("number_set_disagreement")
        if isinstance(value, int | float) and not isinstance(value, bool):
            numbers.append(float(value))
        one_empty = max(one_empty, float(bool(metrics.get("one_empty_one_nonempty"))))
        one_truncated = max(one_truncated, float(bool(metrics.get("one_truncated_one_complete"))))
    return {
        "max_number_set_disagreement": max(numbers) if numbers else 0.0,
        "max_reading_order_disagreement": max(reading_order) if reading_order else 0.0,
        "max_text_disagreement": (1.0 - min(similarities)) if similarities else 0.0,
        "one_empty_one_nonempty": one_empty,
        "one_truncated_one_complete": one_truncated,
    }


def _capture_at_budget(
    ranked: Sequence[tuple[float, str]], failures: Mapping[str, bool]
) -> dict[str, Any]:
    total_failures = sum(1 for failed in failures.values() if failed)
    budget = math.floor(len(ranked) * CAPTURE_BUDGET_FRACTION)
    if total_failures == 0 or budget == 0:
        return {
            "budget_pages": budget,
            "blind_capture": None,
            "oracle_capture": None,
            "ratio": None,
            "reason": (
                "no failing page in the scored set"
                if total_failures == 0
                else "the budget rounds down to zero pages"
            ),
        }
    ordered = sorted(ranked, key=lambda item: (-item[0], item[1]))
    blind_hits = sum(1 for _, case_key in ordered[:budget] if failures.get(case_key))
    oracle_hits = min(budget, total_failures)
    return {
        "budget_pages": budget,
        "blind_capture": round(blind_hits / total_failures, 6),
        "oracle_capture": round(oracle_hits / total_failures, 6),
        "ratio": round(blind_hits / oracle_hits, 6) if oracle_hits else None,
        "reason": None,
    }


def correlate(paths: ArenaPaths, *, model_key: str) -> CorrelationReport:
    """Join the disagreement matrix with official scores and record the finding."""
    pairs_path = paths.disagreement_pairs
    if not pairs_path.is_file():
        raise MissingInputError(
            f"{pairs_path} is absent; run `python -m arena.tavonel disagreement` first"
        )
    scores = load_official_scores(paths, discover_output_models(paths))

    by_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in guards.iter_jsonl_guarded(pairs_path, what="disagreement pairs"):
        if model_key not in (row.get("model_a"), row.get("model_b")):
            continue
        case_key = row.get("case_key")
        if isinstance(case_key, str):
            by_case.setdefault(case_key, []).append(row)

    case_keys = sorted(case_key for case_key in by_case if model_key in scores.get(case_key, {}))
    official = [float(scores[case_key][model_key]) for case_key in case_keys]
    failures = {
        case_key: scores[case_key][model_key] < FAILURE_SCORE_THRESHOLD for case_key in case_keys
    }
    blind = {case_key: _blind_metrics(by_case[case_key]) for case_key in case_keys}

    metric_names = sorted(
        {name for values in blind.values() for name in values}
    ) or ["max_text_disagreement"]
    per_metric: dict[str, Any] = {}
    best_metric: str | None = None
    best_spearman: float | None = None
    for name in metric_names:
        series = [blind[case_key].get(name, 0.0) for case_key in case_keys]
        rho = spearman(series, official)
        capture = _capture_at_budget(
            [(blind[case_key].get(name, 0.0), case_key) for case_key in case_keys], failures
        )
        per_metric[name] = {"spearman_vs_official_score": rho, "capture_at_budget": capture}
        # The hypothesis has a direction: more disagreement must mean a *lower*
        # official score. A positive correlation is not weak evidence for it,
        # it is evidence against it, so the best metric is the most negative.
        if rho is not None and (best_spearman is None or rho < best_spearman):
            best_spearman = rho
            best_metric = name

    best_ratio: float | None = None
    if best_metric is not None:
        ratio = per_metric[best_metric]["capture_at_budget"]["ratio"]
        best_ratio = float(ratio) if isinstance(ratio, int | float) else None

    # When the corpus is too small for the budget to contain a single page the
    # capture test cannot run. Claiming NOT_SUPPORTED on a test that never ran
    # would be as dishonest as claiming support: the rank correlation decides,
    # and the statement says the capture test was not evaluable.
    supported = (
        best_spearman is not None
        and best_spearman <= -MIN_ABS_SPEARMAN_FOR_SUPPORT
        and (best_ratio is None or best_ratio >= MIN_CAPTURE_RATIO_FOR_SUPPORT)
    )
    if not case_keys:
        finding = "NOT_EVALUABLE"
        statement = (
            f"no page has both a disagreement row and an official score for {model_key}; "
            "the hypothesis was not tested"
        )
    elif supported:
        finding = "SUPPORTED"
        capture_clause = (
            "the capture-at-budget test was not evaluable on this corpus"
            if best_ratio is None
            else f"it reaches {best_ratio} of the oracle's failure capture at the stated budget"
        )
        statement = (
            f"disagreement metric {best_metric} ranks pages against the official score with "
            f"Spearman {best_spearman}; {capture_clause}"
        )
    else:
        finding = "NOT_SUPPORTED"
        direction = (
            " Every metric correlated in the wrong direction: the pages the models disagreed "
            "on scored no worse than the pages they agreed on."
            if best_spearman is not None and best_spearman > 0
            else ""
        )
        statement = (
            "GT-free disagreement did not predict evaluator failure at the stated thresholds."
            f"{direction} This is a negative result and is preserved (masterplan section 46); "
            "it repeats the earlier finding that blind quality ranking did not beat length "
            "alone."
        )

    payload: dict[str, Any] = {
        "schema": CORRELATION_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "model_key": model_key,
        "cases_used": len(case_keys),
        "failing_cases": sum(1 for failed in failures.values() if failed),
        "parameters": list(SUPPORT_PARAMETERS),
        "per_metric": per_metric,
        "best_metric": best_metric,
        "best_spearman": best_spearman,
        "finding": finding,
        "finding_statement": statement,
    }
    jsonio.write_json_atomic(paths.disagreement_correlation, payload)
    return CorrelationReport(
        path=paths.disagreement_correlation,
        model_key=model_key,
        cases_used=len(case_keys),
        finding=finding,
        best_metric=best_metric,
        best_spearman=best_spearman,
    )


__all__ = [
    "CAPTURE_BUDGET_FRACTION",
    "CORRELATION_SCHEMA",
    "FAILURE_SCORE_THRESHOLD",
    "MIN_ABS_SPEARMAN_FOR_SUPPORT",
    "MIN_CAPTURE_RATIO_FOR_SUPPORT",
    "CorrelationReport",
    "correlate",
    "spearman",
]
