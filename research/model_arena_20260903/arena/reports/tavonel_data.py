"""Aggregate lane E1's per-variant outputs into report-ready numbers.

Every rate here prefers the frozen **replay manifest**
(``tavonel/adaptive_replay/<variant>/manifest.jsonl``) over the raw route
decisions, because the manifest is what actually resolved: it is the only
place ``unresolved`` (masterplan section 8 — no frozen output for the chosen
model) is recorded. When a variant has not been replayed yet, the frozen
route decisions themselves are the fallback source, and the rates that only
the manifest can answer (``unresolved_rate``) are ``n/a``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arena.reports.common import Cell, na_reason, to_cell
from arena.reports.loaders import ModelRunSource, VariantSource
from arena.reports.variant_ids import is_oracle

__all__ = ["VariantMetrics", "compute_variant_metrics", "recovery_report_rows"]


def _rows_for(source: VariantSource) -> tuple[list[dict[str, Any]], bool]:
    """Prefer the replay manifest; fall back to the frozen route decisions."""

    if source.replay_manifest:
        return source.replay_manifest, True
    return source.route_decisions, False


def _is_escalated(row: dict[str, Any]) -> bool:
    stage = row.get("escalation_stage")
    if isinstance(stage, int) and not isinstance(stage, bool) and stage > 0:
        return True
    decision = row.get("decision")
    return isinstance(decision, str) and "ESCALATE" in decision.upper()


def _final_model(row: dict[str, Any]) -> str | None:
    for key in ("chosen_model_key", "final_model", "target"):
        value = row.get(key)
        if isinstance(value, str):
            return value
    return None


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    variant: str
    variant_dir_name: str
    is_oracle: bool
    total_cases: int
    escalation_rate: Cell
    recovery_needed_rate: Cell
    opus_usage_rate: Cell
    unresolved_rate: Cell
    number_of_model_calls_mean: Cell
    cost_total_usd: Cell
    cost_per_1000_pages_usd: Cell
    all_models_contrast_usd: Cell
    cost_delta_vs_all_models_usd: Cell
    primary_model_key: Cell


def _rate(numerator: int, denominator: int, *, reason: str) -> Cell:
    if denominator == 0:
        return na_reason(reason)
    return to_cell(round(numerator / denominator, 6))


def compute_variant_metrics(variant: str, dir_name: str, source: VariantSource) -> VariantMetrics:
    rows, from_replay = _rows_for(source)
    total = len(rows)
    no_rows_reason = (
        "no frozen route decisions and no replay manifest found for this variant"
    )

    escalated = sum(1 for row in rows if _is_escalated(row))
    recovery_needed = sum(1 for row in rows if row.get("recovery_required") is True)
    opus_used = sum(1 for row in rows if _final_model(row) == "opus5_subscription")
    calls = [
        row["number_of_model_calls"]
        for row in rows
        if isinstance(row.get("number_of_model_calls"), int)
        and not isinstance(row.get("number_of_model_calls"), bool)
    ]

    if from_replay:
        unresolved = sum(1 for row in rows if row.get("unresolved") is True)
        unresolved_cell = _rate(unresolved, total, reason=no_rows_reason)
    else:
        unresolved_cell = na_reason(
            "variant has not been replayed yet (no adaptive_replay manifest); "
            "unresolved pages are only known after replay"
        )

    primaries: set[str] = set()
    for row in rows:
        candidate = row.get("primary_model_key") or row.get("primary")
        if isinstance(candidate, str):
            primaries.add(candidate)
    primary_cell = (
        to_cell(sorted(primaries)[0])
        if len(primaries) == 1
        else na_reason(
            "no single primary model across this variant's decisions"
            if primaries
            else no_rows_reason
        )
    )

    cost = source.cost or {}
    totals_raw = cost.get("totals")
    totals: dict[str, Any] = totals_raw if isinstance(totals_raw, dict) else {}
    total_usd = totals.get("total_usd")
    per_1000 = totals.get("usd_per_1000_pages")
    contrast = cost.get("all_models_full_run_usd_for_contrast_only")

    cost_total_cell = (
        to_cell(float(total_usd))
        if isinstance(total_usd, int | float) and not isinstance(total_usd, bool)
        else na_reason("no tavonel/cost/<variant>.json found or no priced pages in it")
    )
    per_1000_cell = (
        to_cell(float(per_1000))
        if isinstance(per_1000, int | float) and not isinstance(per_1000, bool)
        else na_reason("no tavonel/cost/<variant>.json found or no priced pages in it")
    )
    contrast_cell = (
        to_cell(float(contrast))
        if isinstance(contrast, int | float) and not isinstance(contrast, bool)
        else na_reason("all-models contrast cost not computable (see tavonel/cost/<variant>.json)")
    )
    delta_cell = (
        to_cell(round(float(total_usd) - float(contrast), 6))
        if isinstance(total_usd, int | float)
        and not isinstance(total_usd, bool)
        and isinstance(contrast, int | float)
        and not isinstance(contrast, bool)
        else na_reason("cost delta needs both the variant cost and the all-models contrast cost")
    )

    return VariantMetrics(
        variant=variant,
        variant_dir_name=dir_name,
        is_oracle=is_oracle(variant),
        total_cases=total,
        escalation_rate=_rate(escalated, total, reason=no_rows_reason),
        recovery_needed_rate=_rate(recovery_needed, total, reason=no_rows_reason),
        opus_usage_rate=_rate(opus_used, total, reason=no_rows_reason),
        unresolved_rate=unresolved_cell,
        number_of_model_calls_mean=(
            to_cell(round(sum(calls) / len(calls), 4))
            if calls
            else na_reason("no decision recorded number_of_model_calls")
        ),
        cost_total_usd=cost_total_cell,
        cost_per_1000_pages_usd=per_1000_cell,
        all_models_contrast_usd=contrast_cell,
        cost_delta_vs_all_models_usd=delta_cell,
        primary_model_key=primary_cell,
    )


def recovery_report_rows(
    recovery_plan: list[dict[str, Any]], runs: dict[str, ModelRunSource]
) -> list[dict[str, Any]]:
    """One row per planned recovery job, joined against any matching receipt.

    The join is best-effort by ``(model_key, case_key, job_kind="recovery")``
    because contract section 3.6 does not put ``recovery_job_id`` on the page
    receipt itself; an unmatched plan row is reported as not-yet-executed
    rather than guessed at.
    """

    receipts_by_model_case: dict[tuple[str, str], dict[str, Any]] = {}
    for model_key, run in runs.items():
        for receipt in run.receipts:
            if receipt.get("job_kind") != "recovery":
                continue
            case_key = receipt.get("case_key")
            if isinstance(case_key, str):
                receipts_by_model_case[(model_key, case_key)] = receipt

    rows: list[dict[str, Any]] = []
    for plan_row in recovery_plan:
        plan_model_key = plan_row.get("model_key")
        plan_case_key = plan_row.get("case_key")
        match = (
            receipts_by_model_case.get((plan_model_key, plan_case_key))
            if isinstance(plan_model_key, str) and isinstance(plan_case_key, str)
            else None
        )
        rows.append(
            {
                "recovery_job_id": plan_row.get("recovery_job_id"),
                "model_key": plan_model_key,
                "case_key": plan_case_key,
                "sample_id": plan_row.get("sample_id"),
                "recovery_type": plan_row.get("recovery_type"),
                "round": plan_row.get("round"),
                "executed": match is not None,
                "status": match.get("status") if match else None,
                "error_class": match.get("error_class") if match else None,
                "reason": None if match is not None else "not yet executed (planned only)",
            }
        )
    return rows
