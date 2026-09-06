"""TAVONEL-specific tables: routes, ablation, recovery, Opus, disagreement, Pareto.

These consume :class:`~arena.reports.loaders.CampaignSources` directly (rather
than a narrower per-variant type) because several columns here - quality
delta against the primary model, latency derived from the chosen model's own
receipts - need to cross-reference the base per-model data lane E1's variant
outputs do not repeat.
"""

from __future__ import annotations

import statistics
from typing import Any

from arena.constants import OPUS_DISPLAY_NAME
from arena.reports.common import Cell, TableSpec, na_reason, to_cell
from arena.reports.loaders import CampaignSources
from arena.reports.metrics import (
    aggregate_pod_costs,
    compute_model_metrics,
    cost_usd_per_1000_pages,
)
from arena.reports.pareto import ParetoPoint, non_dominated
from arena.reports.scoring import headline_metric
from arena.reports.tavonel_data import compute_variant_metrics, recovery_report_rows
from arena.reports.variant_ids import VARIANT_IDS, is_oracle, variant_dir_name

__all__ = [
    "build_model_disagreement",
    "build_opus_subscription_report",
    "build_pareto_frontier",
    "build_recovery_report",
    "build_tavonel_ablation",
    "build_tavonel_routes",
]


def _chosen_receipt_ms(sources: CampaignSources, model_key: str, case_key: str) -> float | None:
    run = sources.runs.get(model_key)
    if run is None:
        return None
    for receipt in run.receipts:
        if receipt.get("case_key") == case_key and receipt.get("status") == "SUCCESS":
            value = receipt.get("total_ms")
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
    return None


def _variant_benchmark_headline(
    sources: CampaignSources, variant: str, dir_name: str, benchmark: str
) -> Cell:
    for candidate_key in (variant, dir_name):
        score = sources.scores.get((candidate_key, benchmark))
        if score is not None and score.summary is not None:
            cell, _ = headline_metric(score.summary, score.summary_reason)
            return cell
    return na_reason(
        f"no scores/<variant>/{benchmark}/summary.json found for this variant "
        "(variant outputs are not scored until lane E2 scores the composite)"
    )


def build_tavonel_routes(sources: CampaignSources) -> TableSpec:
    header = (
        "variant",
        "variant_dir_name",
        "is_oracle",
        "primary_model_key",
        "ParseBench",
        "OmniDoc",
        "olmOCR",
        "completion",
        "sec_per_page",
        "cost_usd_per_1000_pages",
        "unresolved_pct",
        "escalation_pct",
        "recovery_needed_pct",
        "recovery_yield",
        "opus_usage_pct",
        "cost_delta_vs_all_models_usd",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for variant in VARIANT_IDS:
        dir_name = variant_dir_name(variant)
        source = sources.variants.get(variant)
        metrics = compute_variant_metrics(variant, dir_name, source) if source else None
        if metrics is None or metrics.total_cases == 0:
            rows.append(
                {
                    "variant": to_cell(variant),
                    "variant_dir_name": to_cell(dir_name),
                    "is_oracle": to_cell(is_oracle(variant)),
                    "reason": na_reason(
                        "no tavonel/route_decisions or tavonel/adaptive_replay found for "
                        "this variant"
                    ),
                }
            )
            continue

        latencies = []
        if source is not None:
            for row in source.replay_manifest:
                if row.get("unresolved"):
                    continue
                model_key = row.get("chosen_model_key")
                case_key = row.get("case_key")
                if isinstance(model_key, str) and isinstance(case_key, str):
                    ms = _chosen_receipt_ms(sources, model_key, case_key)
                    if ms is not None:
                        latencies.append(ms)
        sec_per_page = (
            to_cell(round(statistics.mean(latencies) / 1000.0, 4))
            if latencies
            else na_reason("no resolved case in the replay manifest has a matching SUCCESS receipt")
        )
        completion = (
            to_cell(round(1.0 - metrics.unresolved_rate.value, 6))
            if metrics.unresolved_rate.value is not None
            else na_reason(metrics.unresolved_rate.reason or "unresolved rate not computed")
        )

        rows.append(
            {
                "variant": to_cell(variant),
                "variant_dir_name": to_cell(dir_name),
                "is_oracle": to_cell(is_oracle(variant)),
                "primary_model_key": metrics.primary_model_key,
                "ParseBench": _variant_benchmark_headline(
                    sources, variant, dir_name, "parsebench"
                ),
                "OmniDoc": _variant_benchmark_headline(sources, variant, dir_name, "omnidoc"),
                "olmOCR": _variant_benchmark_headline(sources, variant, dir_name, "olmocr"),
                "completion": completion,
                "sec_per_page": sec_per_page,
                "cost_usd_per_1000_pages": metrics.cost_per_1000_pages_usd,
                "unresolved_pct": metrics.unresolved_rate,
                "escalation_pct": metrics.escalation_rate,
                "recovery_needed_pct": metrics.recovery_needed_rate,
                "recovery_yield": na_reason(
                    "recovery yield needs a before/after official score per recovered case, "
                    "which lane E2 has not produced for these inputs"
                ),
                "opus_usage_pct": metrics.opus_usage_rate,
                "cost_delta_vs_all_models_usd": metrics.cost_delta_vs_all_models_usd,
                "reason": to_cell("ok"),
            }
        )
    return TableSpec(header=header, rows=rows)


def build_tavonel_ablation(sources: CampaignSources) -> TableSpec:
    header = (
        "variant",
        "benchmark",
        "primary_model_key",
        "before_score",
        "after_score",
        "quality_delta",
        "final_cost_usd",
        "all_models_contrast_usd",
        "cost_delta_vs_all_models_usd",
        "recovery_planned_jobs",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for variant in VARIANT_IDS:
        dir_name = variant_dir_name(variant)
        source = sources.variants.get(variant)
        metrics = compute_variant_metrics(variant, dir_name, source) if source else None
        recovery_planned = to_cell(0)
        if source is not None and isinstance(source.cost, dict):
            recovery_block = source.cost.get("recovery")
            if isinstance(recovery_block, dict) and isinstance(
                recovery_block.get("planned_jobs"), int
            ):
                recovery_planned = to_cell(recovery_block["planned_jobs"])
        for benchmark, column in (
            ("parsebench", "ParseBench"),
            ("omnidoc", "OmniDoc"),
            ("olmocr", "olmOCR"),
        ):
            primary_key = metrics.primary_model_key.value if metrics else None
            before = na_reason("no single primary model known for this variant")
            if isinstance(primary_key, str):
                base_score = sources.scores.get((primary_key, benchmark))
                before, _ = headline_metric(
                    base_score.summary if base_score else None,
                    base_score.summary_reason if base_score else None,
                )
            after = (
                _variant_benchmark_headline(sources, variant, dir_name, benchmark)
                if metrics is not None
                else na_reason("variant has no route decisions or replay output")
            )
            delta = (
                to_cell(round(after.value - before.value, 6))
                if before.value is not None and after.value is not None
                else na_reason("needs both a before (primary model) and after (variant) score")
            )
            no_variant_data = na_reason("no variant data found")
            rows.append(
                {
                    "variant": to_cell(variant),
                    "benchmark": to_cell(column),
                    "primary_model_key": (
                        to_cell(primary_key) if primary_key else na_reason("unknown")
                    ),
                    "before_score": before,
                    "after_score": after,
                    "quality_delta": delta,
                    "final_cost_usd": metrics.cost_total_usd if metrics else no_variant_data,
                    "all_models_contrast_usd": (
                        metrics.all_models_contrast_usd if metrics else no_variant_data
                    ),
                    "cost_delta_vs_all_models_usd": (
                        metrics.cost_delta_vs_all_models_usd if metrics else no_variant_data
                    ),
                    "recovery_planned_jobs": recovery_planned,
                    "reason": to_cell("ok") if metrics else no_variant_data,
                }
            )
    return TableSpec(header=header, rows=rows)


def build_recovery_report(sources: CampaignSources) -> TableSpec:
    header = (
        "recovery_job_id",
        "model_key",
        "case_key",
        "sample_id",
        "recovery_type",
        "round",
        "executed",
        "status",
        "error_class",
        "reason",
    )
    rows_raw = recovery_report_rows(sources.recovery_plan, sources.runs)
    if not rows_raw:
        return TableSpec(
            header=header,
            rows=[
                {
                    "reason": na_reason(
                        sources.recovery_plan_reason or "no recovery jobs planned"
                    )
                }
            ],
        )
    rows: list[dict[str, Cell]] = []
    for row in rows_raw:
        not_executed = na_reason("not executed")
        rows.append(
            {
                "recovery_job_id": to_cell(row["recovery_job_id"]),
                "model_key": to_cell(row["model_key"]),
                "case_key": to_cell(row["case_key"]),
                "sample_id": to_cell(row["sample_id"]),
                "recovery_type": to_cell(row["recovery_type"]),
                "round": to_cell(row["round"]),
                "executed": to_cell(row["executed"]),
                "status": to_cell(row["status"]) if row["status"] else not_executed,
                "error_class": (
                    to_cell(row["error_class"]) if row["error_class"] else na_reason("n/a")
                ),
                "reason": to_cell(row["reason"]) if row["reason"] else to_cell("ok"),
            }
        )
    return TableSpec(header=header, rows=rows)


def build_opus_subscription_report(sources: CampaignSources) -> TableSpec:
    header = (
        "experiment_name",
        "receipt_file",
        "pages_attempted",
        "pages_success",
        "pages_failed",
        "api_equivalent_list_price_usd_total",
        "api_equivalent_list_price_usd_per_page",
        "subscription_included_usage",
        "actual_marginal_api_cost",
        "stopped",
        "stop_reason",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for payload in sources.opus_receipts:
        counts_raw = payload.get("counts")
        counts: dict[str, Any] = counts_raw if isinstance(counts_raw, dict) else {}
        attempted = counts.get("attempted")
        success = counts.get("success")
        total_price = payload.get("api_equivalent_list_price_usd_total")
        per_page = (
            round(float(total_price) / int(attempted), 6)
            if isinstance(total_price, int | float)
            and not isinstance(total_price, bool)
            and isinstance(attempted, int)
            and attempted > 0
            else None
        )
        failed = counts.get("failed")
        rows.append(
            {
                "experiment_name": to_cell(OPUS_DISPLAY_NAME),
                "receipt_file": to_cell(payload.get("schema")),
                "pages_attempted": (
                    to_cell(attempted)
                    if attempted is not None
                    else na_reason("no counts.attempted")
                ),
                "pages_success": (
                    to_cell(success) if success is not None else na_reason("no counts.success")
                ),
                "pages_failed": (
                    to_cell(failed) if failed is not None else na_reason("no counts.failed")
                ),
                "api_equivalent_list_price_usd_total": (
                    to_cell(round(float(total_price), 6))
                    if isinstance(total_price, int | float) and not isinstance(total_price, bool)
                    else na_reason(
                        "no api_equivalent_list_price_usd_total on this receipt "
                        "(never reported as $0/page)"
                    )
                ),
                "api_equivalent_list_price_usd_per_page": (
                    to_cell(per_page) if per_page is not None else na_reason("cannot divide")
                ),
                "subscription_included_usage": to_cell(
                    payload.get("subscription_included_usage", True)
                ),
                "actual_marginal_api_cost": to_cell(payload.get("actual_marginal_api_cost", "N/A")),
                "stopped": to_cell(payload.get("stopped", False)),
                "stop_reason": (
                    to_cell(payload.get("stop_reason"))
                    if payload.get("stop_reason")
                    else na_reason("not stopped")
                ),
                "reason": to_cell("ok"),
            }
        )
    if not rows:
        return TableSpec(
            header=header,
            rows=[
                {
                    "experiment_name": to_cell(OPUS_DISPLAY_NAME),
                    "reason": na_reason("no receipts/opus-*.json files found"),
                }
            ],
        )
    return TableSpec(header=header, rows=rows)


def build_model_disagreement(sources: CampaignSources) -> TableSpec:
    header = (
        "model_a",
        "model_b",
        "case_key",
        "sample_id",
        "benchmark",
        "text_similarity",
        "number_set_disagreement",
        "table_row_count_difference",
        "heading_count_difference",
        "formula_count_difference",
        "reading_order_disagreement",
        "output_length_ratio",
        "one_empty_one_nonempty",
        "one_truncated_one_complete",
        "reason",
    )
    if not sources.disagreement_pairs:
        return TableSpec(
            header=header,
            rows=[
                {
                    "reason": na_reason(
                        sources.disagreement_pairs_reason
                        or "no tavonel/disagreement/pairs.jsonl found"
                    )
                }
            ],
        )
    rows: list[dict[str, Cell]] = []
    for row in sources.disagreement_pairs:
        metrics_raw = row.get("metrics")
        metrics: dict[str, Any] = metrics_raw if isinstance(metrics_raw, dict) else {}
        rows.append(
            {
                "model_a": to_cell(row.get("model_a")),
                "model_b": to_cell(row.get("model_b")),
                "case_key": to_cell(row.get("case_key")),
                "sample_id": to_cell(row.get("sample_id")),
                "benchmark": to_cell(row.get("benchmark")),
                "text_similarity": to_cell(metrics.get("text_similarity")),
                "number_set_disagreement": to_cell(metrics.get("number_set_disagreement")),
                "table_row_count_difference": to_cell(metrics.get("table_row_count_difference")),
                "heading_count_difference": to_cell(metrics.get("heading_count_difference")),
                "formula_count_difference": to_cell(metrics.get("formula_count_difference")),
                "reading_order_disagreement": to_cell(metrics.get("reading_order_disagreement")),
                "output_length_ratio": to_cell(metrics.get("output_length_ratio")),
                "one_empty_one_nonempty": to_cell(metrics.get("one_empty_one_nonempty")),
                "one_truncated_one_complete": to_cell(metrics.get("one_truncated_one_complete")),
                "reason": to_cell("ok"),
            }
        )
    return TableSpec(header=header, rows=rows)


def build_pareto_frontier(
    sources: CampaignSources, models: tuple[str, ...], benchmarks: tuple[str, ...]
) -> TableSpec:
    """One frontier per benchmark; ``x`` is ``$/1,000 pages`` when priced, else GPU sec/page."""

    header = (
        "benchmark",
        "system",
        "x_axis",
        "x_value",
        "y_quality",
        "pareto_non_dominated",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for benchmark, column in (
        ("parsebench", "ParseBench"),
        ("omnidoc", "OmniDoc"),
        ("olmocr", "olmOCR"),
    ):
        points: list[ParetoPoint] = []
        skipped: list[tuple[str, str]] = []
        for model_key in models:
            score = sources.scores.get((model_key, benchmark))
            quality, _ = headline_metric(
                score.summary if score else None, score.summary_reason if score else None
            )
            run = sources.runs.get(model_key)
            metrics = compute_model_metrics(model_key, run) if run else None
            pod = aggregate_pod_costs(model_key, sources.pod_ledger)
            cost = (
                cost_usd_per_1000_pages(metrics, pod)
                if metrics is not None
                else na_reason("no run data for this model")
            )
            if quality.value is None or cost.value is None:
                skip_reason = (
                    (quality.reason or "no quality score")
                    if quality.value is None
                    else (cost.reason or "no cost")
                )
                skipped.append((model_key, skip_reason))
                continue
            points.append(
                ParetoPoint(
                    system=model_key, x_cost=float(cost.value), y_quality=float(quality.value)
                )
            )

        dominance = non_dominated(points)
        for point in points:
            rows.append(
                {
                    "benchmark": to_cell(column),
                    "system": to_cell(point.system),
                    "x_axis": to_cell("usd_per_1000_pages"),
                    "x_value": to_cell(point.x_cost),
                    "y_quality": to_cell(point.y_quality),
                    "pareto_non_dominated": to_cell(dominance[point.system]),
                    "reason": to_cell("ok"),
                }
            )
        for model_key, reason in skipped:
            rows.append(
                {
                    "benchmark": to_cell(column),
                    "system": to_cell(model_key),
                    "x_axis": na_reason("insufficient data"),
                    "x_value": na_reason(reason),
                    "y_quality": na_reason(reason),
                    "pareto_non_dominated": na_reason("cannot place on the frontier"),
                    "reason": to_cell(reason),
                }
            )
    return TableSpec(header=header, rows=rows)
