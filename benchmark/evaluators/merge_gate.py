"""Deterministic section 22.8 merge-gate evaluation.

The gate compares records for the same immutable benchmark cases.  It does not
promote a model and it cannot close the licensed-corpus or production canary
gates; it only produces a local, reviewable decision.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MERGE_GATE_VERSION = "22.8-v1.0.0"

HIGHER_IS_BETTER = (
    "normalized_edit_similarity",
    "numeric_exact_match",
    "date_unit_exact_match",
    "reading_order_pair_accuracy",
    "table_teds",
    "table_cell_exactness",
    "formula_edit_score",
    "heading_tree_score",
    "provenance_coverage",
    "rag_recall_at_10",
    "rag_mrr",
    "rag_ndcg_at_10",
    "rag_answer_groundedness",
    "router_first_pass_acceptance_rate",
    "router_escalation_recall",
    "router_quality_after_escalation",
)

LOWER_IS_BETTER = (
    "cer",
    "wer",
    "unsupported_claim_rate",
    "unsupported_summary_claim_rate",
    "repetition_rate",
    "router_false_escalation_rate",
    "router_route_regret",
)

_INFRA_FAILURES = frozenset(
    {
        "crash",
        "oom",
        "timeout",
        "provider_crash",
        "gpu_oom",
        "provider_timeout",
    }
)


@dataclass(frozen=True)
class MergeGateDecision:
    gate_version: str
    passed: bool
    approval_required: bool
    compared_case_count: int
    reasons: tuple[str, ...]
    regressions: Mapping[str, float]
    candidate_cost_regression: float | None
    candidate_infra_failure_rate: float


def _finite_number(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return float(value)
    return None


def _records_by_case(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        case_id = record.get("benchmark_case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("every score record needs a benchmark_case_id")
        if case_id in result:
            raise ValueError(f"duplicate benchmark_case_id: {case_id}")
        result[case_id] = record
    return result


def _average(
    records: Sequence[Mapping[str, Any]],
    metric_name: str,
) -> float | None:
    values: list[float] = []
    for record in records:
        metrics = record.get("metrics")
        if not isinstance(metrics, Mapping):
            continue
        value = _finite_number(metrics.get(metric_name))
        if value is not None:
            values.append(value)
    return sum(values) / len(values) if values else None


def _infra_failure_rate(records: Sequence[Mapping[str, Any]]) -> float:
    if not records:
        return 1.0
    failed = 0
    for record in records:
        failures = record.get("hard_failures")
        failure_names = {str(item) for item in failures} if isinstance(failures, list) else set()
        failed += int(bool(failure_names & _INFRA_FAILURES))
    return failed / len(records)


def evaluate_merge_gate(
    baseline_records: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
    *,
    metric_tolerance: float = 0.0,
    max_infra_failure_rate: float = 0.0,
    approve_cost_regression: bool = False,
) -> MergeGateDecision:
    """Compare an immutable candidate run to its baseline.

    A cost increase above ten percent is not an automatic quality failure, but
    it requires an explicit approval.  Missing cases, schema-invalid records,
    critical-number regressions, unsupported-content growth, and infra failure
    rates above the caller's bound always fail closed.
    """

    if not 0.0 <= metric_tolerance <= 1.0:
        raise ValueError("metric_tolerance must be between zero and one")
    if not 0.0 <= max_infra_failure_rate <= 1.0:
        raise ValueError("max_infra_failure_rate must be between zero and one")
    baseline_by_case = _records_by_case(baseline_records)
    candidate_by_case = _records_by_case(candidate_records)
    if not baseline_by_case:
        raise ValueError("baseline records cannot be empty")

    reasons: list[str] = []
    regressions: dict[str, float] = {}
    missing_cases = sorted(set(baseline_by_case) - set(candidate_by_case))
    extra_cases = sorted(set(candidate_by_case) - set(baseline_by_case))
    if missing_cases:
        reasons.append("missing_candidate_cases:" + ",".join(missing_cases))
    if extra_cases:
        reasons.append("unexpected_candidate_cases:" + ",".join(extra_cases))
    common_ids = sorted(set(baseline_by_case) & set(candidate_by_case))
    baseline_common = [baseline_by_case[case_id] for case_id in common_ids]
    candidate_common = [candidate_by_case[case_id] for case_id in common_ids]

    for metric_name in HIGHER_IS_BETTER:
        baseline_value = _average(baseline_common, metric_name)
        candidate_value = _average(candidate_common, metric_name)
        if baseline_value is None or candidate_value is None:
            continue
        regression = baseline_value - candidate_value
        if regression > metric_tolerance:
            regressions[metric_name] = regression
            reasons.append(f"quality_regression:{metric_name}")
    for metric_name in LOWER_IS_BETTER:
        baseline_value = _average(baseline_common, metric_name)
        candidate_value = _average(candidate_common, metric_name)
        if baseline_value is None or candidate_value is None:
            continue
        regression = candidate_value - baseline_value
        if regression > metric_tolerance:
            regressions[metric_name] = regression
            reasons.append(f"quality_regression:{metric_name}")

    for case_id in common_ids:
        baseline_metrics = baseline_by_case[case_id].get("metrics")
        candidate_metrics = candidate_by_case[case_id].get("metrics")
        if not isinstance(baseline_metrics, Mapping) or not isinstance(candidate_metrics, Mapping):
            reasons.append(f"schema_invalid:{case_id}")
            continue
        schema_validity = _finite_number(candidate_metrics.get("schema_validity"))
        if schema_validity != 1.0:
            reasons.append(f"schema_invalid:{case_id}")
        baseline_number = _finite_number(baseline_metrics.get("numeric_exact_match"))
        candidate_number = _finite_number(candidate_metrics.get("numeric_exact_match"))
        if (
            baseline_number is not None
            and candidate_number is not None
            and candidate_number < baseline_number
        ):
            reasons.append(f"critical_number_regression:{case_id}")
        baseline_unsupported = _finite_number(baseline_metrics.get("unsupported_claim_rate"))
        candidate_unsupported = _finite_number(candidate_metrics.get("unsupported_claim_rate"))
        if (
            baseline_unsupported is not None
            and candidate_unsupported is not None
            and candidate_unsupported > baseline_unsupported
        ):
            reasons.append(f"unsupported_content_increase:{case_id}")

    candidate_failure_rate = _infra_failure_rate(candidate_common)
    if candidate_failure_rate > max_infra_failure_rate:
        reasons.append("infra_failure_rate_above_threshold")

    baseline_cost = _average(baseline_common, "estimated_cost_usd")
    candidate_cost = _average(candidate_common, "estimated_cost_usd")
    cost_regression = None
    approval_required = False
    if baseline_cost is not None and candidate_cost is not None:
        if baseline_cost == 0.0:
            cost_regression = 0.0 if candidate_cost == 0.0 else math.inf
        else:
            cost_regression = (candidate_cost - baseline_cost) / baseline_cost
        if cost_regression > 0.10:
            approval_required = not approve_cost_regression
            if approval_required:
                reasons.append("cost_regression_requires_approval")

    deduplicated_reasons = tuple(dict.fromkeys(reasons))
    return MergeGateDecision(
        gate_version=MERGE_GATE_VERSION,
        passed=not deduplicated_reasons,
        approval_required=approval_required,
        compared_case_count=len(common_ids),
        reasons=deduplicated_reasons,
        regressions=dict(sorted(regressions.items())),
        candidate_cost_regression=cost_regression,
        candidate_infra_failure_rate=candidate_failure_rate,
    )
