"""Per-system tables: leaderboard, breakdowns, latency, GPU, cost, reliability, failures.

Every function takes already-loaded data (never a path) and returns a
:class:`~arena.reports.common.TableSpec`, so a test can hand it a handful of
synthetic :class:`~arena.reports.metrics.ModelMetrics` without touching disk.
"""

from __future__ import annotations

from typing import Any

from arena.reports.common import Cell, TableSpec, na_reason, to_cell
from arena.reports.loaders import CampaignSources
from arena.reports.metrics import (
    aggregate_pod_costs,
    compute_model_metrics,
    cost_usd_per_1000_pages,
)
from arena.reports.scoring import document_type_family, headline_metric, metric_rows

__all__ = [
    "LEADERBOARD_HEADER",
    "build_benchmark_breakdown",
    "build_cost_report",
    "build_document_type_breakdown",
    "build_failure_taxonomy",
    "build_gpu_resource_report",
    "build_latency_report",
    "build_leaderboard",
    "build_reliability_report",
    "build_runtime_failures",
    "leaderboard_markdown",
]

LEADERBOARD_HEADER = (
    "System",
    "ParseBench",
    "OmniDoc",
    "olmOCR",
    "completion",
    "sec_per_page",
    "gpu_or_api_equivalent_cost_usd_per_1000_pages",
    "retry_pct",
    "stall_pct",
    "unresolved_pct",
    "data_gaps",
)


def _display_name(model_key: str, model_registry: dict[str, Any] | None) -> str:
    if isinstance(model_registry, dict):
        models = model_registry.get("models")
        if isinstance(models, dict):
            record = models.get(model_key)
            if isinstance(record, dict) and isinstance(record.get("display_name"), str):
                return str(record["display_name"])
    return model_key


def build_leaderboard(sources: CampaignSources, models: tuple[str, ...]) -> TableSpec:
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        run = sources.runs.get(model_key)
        metrics = compute_model_metrics(model_key, run) if run else None
        pod = aggregate_pod_costs(model_key, sources.pod_ledger)
        gaps: list[str] = []

        benchmark_cells: dict[str, Cell] = {}
        for benchmark, column in (
            ("parsebench", "ParseBench"),
            ("omnidoc", "OmniDoc"),
            ("olmocr", "olmOCR"),
        ):
            score = sources.scores.get((model_key, benchmark))
            cell, _ = headline_metric(
                score.summary if score else None, score.summary_reason if score else None
            )
            benchmark_cells[column] = cell
            if cell.value is None:
                gaps.append(f"{column}: {cell.reason}")

        if metrics is None:
            completion = na_reason("no runs/<model_key>/receipts directory found")
            sec_per_page = na_reason("no runs/<model_key>/receipts directory found")
            retry_pct = na_reason("no runs/<model_key>/receipts directory found")
            stall_pct = na_reason("no runs/<model_key>/receipts directory found")
            unresolved_pct = na_reason("no runs/<model_key>/receipts directory found")
            cost_cell = na_reason("no runs/<model_key>/receipts directory found")
        else:
            completion = metrics.completion_rate
            sec_per_page = metrics.sec_per_page_mean
            retry_pct = metrics.retry_rate
            stall_pct = metrics.stall_rate
            unresolved_pct = metrics.unresolved_rate
            cost_cell = cost_usd_per_1000_pages(metrics, pod)
            for cell, label in (
                (completion, "completion"),
                (sec_per_page, "sec_per_page"),
                (cost_cell, "cost"),
            ):
                if cell.value is None:
                    gaps.append(f"{label}: {cell.reason}")

        rows.append(
            {
                "System": to_cell(_display_name(model_key, sources.model_registry)),
                "ParseBench": benchmark_cells["ParseBench"],
                "OmniDoc": benchmark_cells["OmniDoc"],
                "olmOCR": benchmark_cells["olmOCR"],
                "completion": completion,
                "sec_per_page": sec_per_page,
                "gpu_or_api_equivalent_cost_usd_per_1000_pages": cost_cell,
                "retry_pct": retry_pct,
                "stall_pct": stall_pct,
                "unresolved_pct": unresolved_pct,
                "data_gaps": to_cell("; ".join(gaps)) if gaps else to_cell("none"),
            }
        )
    return TableSpec(header=LEADERBOARD_HEADER, rows=rows)


def _render_markdown_cell(value: Cell | Any) -> str:
    if isinstance(value, Cell):
        return value.rendered()
    return str(value) if value is not None else "n/a"


def leaderboard_markdown(spec: TableSpec, *, title: str = "TAVONEL Model Arena Leaderboard") -> str:
    lines = [f"# {title}", ""]
    lines.append("| " + " | ".join(spec.header) + " |")
    lines.append("|" + "|".join("---" for _ in spec.header) + "|")
    for row in spec.rows:
        cells = [_render_markdown_cell(row.get(column)) for column in spec.header]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        "Benchmarks are kept separate on purpose (masterplan section 28): no blended "
        "overall score is computed across ParseBench, OmniDocBench and olmOCR-Bench."
    )
    return "\n".join(lines)


def build_benchmark_breakdown(
    sources: CampaignSources, models: tuple[str, ...], benchmarks: tuple[str, ...]
) -> TableSpec:
    header = ("model_key", "benchmark", "metric", "value", "reason")
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        for benchmark in benchmarks:
            score = sources.scores.get((model_key, benchmark))
            if score is None or score.summary is None:
                rows.append(
                    {
                        "model_key": to_cell(model_key),
                        "benchmark": to_cell(benchmark),
                        "metric": na_reason("no metrics"),
                        "value": na_reason(
                            (score.summary_reason if score else None) or "no scores entry"
                        ),
                        "reason": to_cell(
                            (score.summary_reason if score else None) or "no scores entry loaded"
                        ),
                    }
                )
                continue
            for metric_name, value in metric_rows(score.summary):
                rows.append(
                    {
                        "model_key": to_cell(model_key),
                        "benchmark": to_cell(benchmark),
                        "metric": to_cell(metric_name),
                        "value": (
                            to_cell(value)
                            if value is not None
                            else na_reason("null in summary.json")
                        ),
                        "reason": to_cell("ok"),
                    }
                )
    return TableSpec(header=header, rows=rows)


def build_document_type_breakdown(
    sources: CampaignSources, models: tuple[str, ...], benchmarks: tuple[str, ...]
) -> TableSpec:
    header = ("model_key", "benchmark", "document_type", "mean_metric", "sample_count", "reason")
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        for benchmark in benchmarks:
            score = sources.scores.get((model_key, benchmark))
            if score is None or not score.per_case:
                rows.append(
                    {
                        "model_key": to_cell(model_key),
                        "benchmark": to_cell(benchmark),
                        "document_type": na_reason("no per-category breakdown"),
                        "mean_metric": na_reason(
                            (score.per_case_reason if score else None) or "no scores entry"
                        ),
                        "sample_count": to_cell(0),
                        "reason": to_cell(
                            score.per_case_reason if score else "no scores entry loaded"
                        ),
                    }
                )
                continue
            buckets: dict[str, list[float]] = {}
            unmatched = 0
            for case_row in score.per_case:
                raw_category = None
                for key in ("document_type", "category", "doc_type", "type"):
                    value = case_row.get(key)
                    if isinstance(value, str):
                        raw_category = value
                        break
                family = document_type_family(raw_category) if raw_category else None
                metric_value = None
                for key in ("score", "metric_value", "value", "overall"):
                    candidate = case_row.get(key)
                    if isinstance(candidate, int | float) and not isinstance(candidate, bool):
                        metric_value = float(candidate)
                        break
                if family is None or metric_value is None:
                    unmatched += 1
                    continue
                buckets.setdefault(family, []).append(metric_value)
            if not buckets:
                rows.append(
                    {
                        "model_key": to_cell(model_key),
                        "benchmark": to_cell(benchmark),
                        "document_type": na_reason("no matching document-type field/metric"),
                        "mean_metric": na_reason(
                            f"{unmatched} per_case rows had no recognised category/metric field"
                        ),
                        "sample_count": to_cell(0),
                        "reason": to_cell("per_case.jsonl present but no category matched"),
                    }
                )
                continue
            for family, values in sorted(buckets.items()):
                rows.append(
                    {
                        "model_key": to_cell(model_key),
                        "benchmark": to_cell(benchmark),
                        "document_type": to_cell(family),
                        "mean_metric": to_cell(round(sum(values) / len(values), 6)),
                        "sample_count": to_cell(len(values)),
                        "reason": to_cell("ok"),
                    }
                )
    return TableSpec(header=header, rows=rows)


def build_latency_report(sources: CampaignSources, models: tuple[str, ...]) -> TableSpec:
    header = (
        "model_key",
        "p50_sec_per_page",
        "p90_sec_per_page",
        "p95_sec_per_page",
        "cold_start_p50_sec",
        "model_load_p50_sec",
        "warmup_p50_sec",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        run = sources.runs.get(model_key)
        metrics = compute_model_metrics(model_key, run) if run else None
        canary = run.canary_receipt if run else None
        stage_latency = canary.get("stage_latency_ms") if isinstance(canary, dict) else None

        def _stage_p50(name: str, *, _stage_latency: dict[str, Any] | None = stage_latency) -> Cell:
            if not isinstance(_stage_latency, dict):
                return na_reason("no canary receipt (receipts/canary-<model_key>.json) found")
            stage = _stage_latency.get(name)
            if not isinstance(stage, dict) or "p50_ms" not in stage:
                return na_reason(f"canary receipt has no stage_latency_ms.{name}")
            return to_cell(round(float(stage["p50_ms"]) / 1000.0, 4))

        rows.append(
            {
                "model_key": to_cell(model_key),
                "p50_sec_per_page": (
                    metrics.sec_per_page_quantile(0.5)
                    if metrics
                    else na_reason("no receipts directory")
                ),
                "p90_sec_per_page": (
                    metrics.sec_per_page_quantile(0.9)
                    if metrics
                    else na_reason("no receipts directory")
                ),
                "p95_sec_per_page": (
                    metrics.sec_per_page_quantile(0.95)
                    if metrics
                    else na_reason("no receipts directory")
                ),
                "cold_start_p50_sec": _stage_p50("cold_start"),
                "model_load_p50_sec": _stage_p50("model_loading"),
                "warmup_p50_sec": _stage_p50("warm_up"),
                "reason": to_cell("ok" if metrics and metrics.success_total_ms else "see columns"),
            }
        )
    return TableSpec(header=header, rows=rows)


def build_gpu_resource_report(sources: CampaignSources, models: tuple[str, ...]) -> TableSpec:
    header = (
        "model_key",
        "peak_vram_mb_mean",
        "peak_vram_mb_max",
        "gpu_types_seen",
        "gpu_util_mean",
        "gpu_util_p95",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        run = sources.runs.get(model_key)
        metrics = compute_model_metrics(model_key, run) if run else None
        no_receipts = na_reason("no receipts")
        gpu_types_cell = (
            to_cell(",".join(metrics.gpu_types))
            if metrics and metrics.gpu_types
            else na_reason("no receipts recorded a gpu_type")
        )
        rows.append(
            {
                "model_key": to_cell(model_key),
                "peak_vram_mb_mean": metrics.peak_vram_mb_mean if metrics else no_receipts,
                "peak_vram_mb_max": metrics.peak_vram_mb_max if metrics else no_receipts,
                "gpu_types_seen": gpu_types_cell,
                "gpu_util_mean": na_reason(
                    "GPU utilization is not captured by the page-receipt or pod-ledger schema"
                ),
                "gpu_util_p95": na_reason(
                    "GPU utilization is not captured by the page-receipt or pod-ledger schema"
                ),
                "reason": to_cell("ok"),
            }
        )
    return TableSpec(header=header, rows=rows)


def build_cost_report(sources: CampaignSources, models: tuple[str, ...]) -> TableSpec:
    header = (
        "model_key",
        "useful_inference_seconds",
        "model_loading_seconds",
        "retry_seconds",
        "idle_seconds",
        "billed_seconds",
        "estimated_provider_cost_usd",
        "useful_cost_usd",
        "wasted_cost_usd",
        "usd_per_1000_pages",
        "usd_per_successful_page",
        "usd_per_accepted_page",
        "gpu_seconds_per_page",
        "idle_overhead_ratio",
        "retry_overhead_ratio",
        "startup_overhead_ratio",
        "operational_efficiency",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        pod = aggregate_pod_costs(model_key, sources.pod_ledger)
        run = sources.runs.get(model_key)
        metrics = compute_model_metrics(model_key, run) if run else None

        if pod is None and (metrics is None or not metrics.api_equivalent_usd):
            rows.append(
                {
                    "model_key": to_cell(model_key),
                    "reason": na_reason(
                        "no cost/pod_ledger.jsonl rows and no subscription api_equivalent cost"
                    ),
                }
            )
            continue

        if metrics is not None and metrics.api_equivalent_usd:
            total_usd = sum(metrics.api_equivalent_usd)
            per_page = total_usd / len(metrics.api_equivalent_usd)
            rows.append(
                {
                    "model_key": to_cell(model_key),
                    "useful_inference_seconds": na_reason("subscription lane has no GPU seconds"),
                    "model_loading_seconds": na_reason("subscription lane has no GPU seconds"),
                    "retry_seconds": na_reason("subscription lane has no GPU seconds"),
                    "idle_seconds": na_reason("subscription lane has no GPU seconds"),
                    "billed_seconds": na_reason("subscription lane has no GPU seconds"),
                    "estimated_provider_cost_usd": na_reason(
                        "subscription cost is api-equivalent, not provider-billed"
                    ),
                    "useful_cost_usd": to_cell(round(total_usd, 6)),
                    "wasted_cost_usd": to_cell(0.0),
                    "usd_per_1000_pages": to_cell(round(per_page * 1000.0, 6)),
                    "usd_per_successful_page": to_cell(round(per_page, 6)),
                    "usd_per_accepted_page": to_cell(round(per_page, 6)),
                    "gpu_seconds_per_page": na_reason("subscription lane has no GPU seconds"),
                    "idle_overhead_ratio": na_reason("subscription lane has no billed seconds"),
                    "retry_overhead_ratio": na_reason("subscription lane has no billed seconds"),
                    "startup_overhead_ratio": na_reason("subscription lane has no billed seconds"),
                    "operational_efficiency": na_reason("subscription lane has no billed seconds"),
                    "reason": to_cell("api_equivalent_list_price_usd - never $0/page"),
                }
            )
            continue

        assert pod is not None  # narrowed above
        success = metrics.success if metrics else 0
        gpu_sec_per_page = (
            to_cell(round(pod.useful_inference_seconds / success, 6))
            if success
            else na_reason("no SUCCESS pages to divide useful_inference_seconds by")
        )
        usd_per_1000 = (
            to_cell(round(pod.estimated_provider_cost_usd / success * 1000.0, 6))
            if success
            else na_reason("no SUCCESS pages to divide provider cost by")
        )
        usd_per_page = (
            to_cell(round(pod.estimated_provider_cost_usd / success, 6))
            if success
            else na_reason("no SUCCESS pages to divide provider cost by")
        )
        rows.append(
            {
                "model_key": to_cell(model_key),
                "useful_inference_seconds": to_cell(round(pod.useful_inference_seconds, 3)),
                "model_loading_seconds": to_cell(round(pod.model_loading_seconds, 3)),
                "retry_seconds": to_cell(round(pod.retry_seconds, 3)),
                "idle_seconds": to_cell(round(pod.idle_seconds, 3)),
                "billed_seconds": to_cell(round(pod.billed_seconds, 3)),
                "estimated_provider_cost_usd": to_cell(round(pod.estimated_provider_cost_usd, 6)),
                "useful_cost_usd": to_cell(round(pod.useful_cost_usd, 6)),
                "wasted_cost_usd": to_cell(round(pod.wasted_cost_usd, 6)),
                "usd_per_1000_pages": usd_per_1000,
                "usd_per_successful_page": usd_per_page,
                "usd_per_accepted_page": usd_per_page,
                "gpu_seconds_per_page": gpu_sec_per_page,
                "idle_overhead_ratio": pod.idle_overhead_ratio,
                "retry_overhead_ratio": pod.retry_overhead_ratio,
                "startup_overhead_ratio": pod.startup_overhead_ratio,
                "operational_efficiency": pod.operational_efficiency,
                "reason": to_cell("ok"),
            }
        )
    return TableSpec(header=header, rows=rows)


def build_reliability_report(sources: CampaignSources, models: tuple[str, ...]) -> TableSpec:
    header = (
        "model_key",
        "attempted",
        "success",
        "completion_rate",
        "first_attempt_success",
        "first_attempt_success_rate",
        "retryable_pages",
        "retry_rate",
        "stall_pages",
        "stall_rate",
        "oom_pages",
        "oom_rate",
        "crash_pages",
        "crash_rate",
        "malformed_pages",
        "malformed_rate",
        "timeout_pages",
        "timeout_rate",
        "rate_limit_pages",
        "rate_limit_rate",
        "worker_replacement_count",
        "manual_intervention_count",
        "reason",
    )
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        run = sources.runs.get(model_key)
        if run is None or not run.receipts:
            rows.append(
                {
                    "model_key": to_cell(model_key),
                    "attempted": to_cell(0),
                    "reason": na_reason("no runs/<model_key>/receipts directory found"),
                }
            )
            continue
        metrics = compute_model_metrics(model_key, run)
        rows.append(
            {
                "model_key": to_cell(model_key),
                "attempted": to_cell(metrics.attempted),
                "success": to_cell(metrics.success),
                "completion_rate": metrics.completion_rate,
                "first_attempt_success": to_cell(metrics.first_attempt_success),
                "first_attempt_success_rate": metrics.first_attempt_success_rate,
                "retryable_pages": to_cell(metrics.retryable_pages),
                "retry_rate": metrics.retry_rate,
                "stall_pages": to_cell(metrics.stall_pages),
                "stall_rate": metrics.stall_rate,
                "oom_pages": to_cell(metrics.oom_pages),
                "oom_rate": metrics.oom_rate,
                "crash_pages": to_cell(metrics.crash_pages),
                "crash_rate": metrics.crash_rate,
                "malformed_pages": to_cell(metrics.malformed_pages),
                "malformed_rate": metrics.malformed_rate,
                "timeout_pages": to_cell(metrics.timeout_pages),
                "timeout_rate": metrics.timeout_rate,
                "rate_limit_pages": to_cell(metrics.rate_limit_pages),
                "rate_limit_rate": metrics.rate_limit_rate,
                "worker_replacement_count": na_reason(
                    "worker replacement is controller queue state, not one of this lane's inputs"
                ),
                "manual_intervention_count": na_reason(
                    "manual intervention is not recorded on any input this lane reads"
                ),
                "reason": to_cell("ok"),
            }
        )
    return TableSpec(header=header, rows=rows)


def build_failure_taxonomy(sources: CampaignSources) -> TableSpec:
    header = (
        "error_class",
        "affected_model",
        "first_seen",
        "last_seen",
        "count",
        "retryability",
        "root_cause",
        "resolution",
        "wasted_gpu_seconds",
    )
    rows: list[dict[str, Cell]] = []
    if not sources.errors:
        return TableSpec(
            header=(*header, "reason"),
            rows=[{"reason": na_reason("no failures/errors.jsonl found")}],
        )
    not_yet_determined = na_reason("not yet determined")
    for record in sources.errors:
        affected_model = record.get("affected_model")
        root_cause = record.get("root_cause")
        resolution = record.get("resolution")
        rows.append(
            {
                "error_class": to_cell(record.get("error_class")),
                "affected_model": (
                    to_cell(affected_model)
                    if affected_model
                    else na_reason("not attributed to one model")
                ),
                "first_seen": to_cell(record.get("first_seen")),
                "last_seen": to_cell(record.get("last_seen")),
                "count": to_cell(record.get("count")),
                "retryability": to_cell(record.get("retryability")),
                "root_cause": to_cell(root_cause) if root_cause else not_yet_determined,
                "resolution": to_cell(resolution) if resolution else not_yet_determined,
                "wasted_gpu_seconds": to_cell(record.get("wasted_gpu_seconds")),
            }
        )
    return TableSpec(header=(*header, "reason"), rows=rows)


def build_runtime_failures(sources: CampaignSources, models: tuple[str, ...]) -> TableSpec:
    header = (
        "model_key",
        "case_key",
        "sample_id",
        "status",
        "error_class",
        "error_message",
        "attempt",
        "retry_count",
        "worker_id",
        "pod_id",
        "finished_at",
    )
    rows: list[dict[str, Cell]] = []
    for model_key in models:
        run = sources.runs.get(model_key)
        if run is None:
            continue
        for receipt in run.receipts:
            if receipt.get("status") not in ("FAILED", "QUARANTINED", "PAUSED"):
                continue
            rows.append(
                {
                    "model_key": to_cell(model_key),
                    "case_key": to_cell(receipt.get("case_key")),
                    "sample_id": to_cell(receipt.get("sample_id")),
                    "status": to_cell(receipt.get("status")),
                    "error_class": to_cell(receipt.get("error_class")),
                    "error_message": to_cell(receipt.get("error_message")),
                    "attempt": to_cell(receipt.get("attempt")),
                    "retry_count": to_cell(receipt.get("retry_count")),
                    "worker_id": to_cell(receipt.get("worker_id")),
                    "pod_id": to_cell(receipt.get("pod_id")),
                    "finished_at": to_cell(receipt.get("finished_at")),
                }
            )
    if not rows:
        return TableSpec(
            header=(*header, "reason"),
            rows=[{"reason": na_reason("no non-SUCCESS page receipts found across any model")}],
        )
    ok_rows = [{**row, "reason": to_cell("ok")} for row in rows]
    return TableSpec(header=(*header, "reason"), rows=ok_rows)
