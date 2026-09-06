"""Turn raw page receipts, pod-ledger rows and error records into per-model numbers.

Every rate computed here carries its own numerator and denominator as public
fields on :class:`ModelMetrics` — never just a bare percentage — because a
percentage with no denominator is exactly the kind of number ``CLAUDE.md``
forbids ("every rate carries its denominator").

The error-class buckets below (stall / OOM / crash / malformed / timeout /
rate-limit) are this lane's own grouping of ``arena.constants.ERROR_CLASSES``
for the MP section 12.4 named rates; a page receipt does not carry a field
called "crash", so the grouping is documented here rather than asserted as
official taxonomy.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from arena.reports.common import Cell, na_reason, to_cell
from arena.reports.loaders import ModelRunSource

__all__ = [
    "CRASH_CLASSES",
    "MALFORMED_CLASSES",
    "OOM_CLASSES",
    "RATE_LIMIT_CLASSES",
    "STALL_CLASSES",
    "TIMEOUT_CLASSES",
    "ModelMetrics",
    "PodCostAgg",
    "aggregate_pod_costs",
    "compute_model_metrics",
    "cost_usd_per_1000_pages",
    "quantile",
]

STALL_CLASSES = frozenset({"INFERENCE_STALL"})
OOM_CLASSES = frozenset({"CUDA_OOM"})
CRASH_CLASSES = frozenset({"CUDA_INIT", "GPU_KERNEL", "DEPENDENCY", "MODEL_LOAD", "TENSOR_SHAPE"})
MALFORMED_CLASSES = frozenset(
    {"OUTPUT_MALFORMED", "OUTPUT_TRUNCATED", "OUTPUT_REPETITION", "OUTPUT_EMPTY"}
)
TIMEOUT_CLASSES = frozenset({"INFERENCE_TIMEOUT"})
RATE_LIMIT_CLASSES = frozenset({"RATE_LIMIT", "SUBSCRIPTION_LIMIT"})


def quantile(values: list[float], q: float) -> float | None:
    """Nearest-rank quantile. ``None`` for an empty sample rather than 0."""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    return statistics.quantiles(ordered, n=100, method="inclusive")[round(q * 100) - 1]


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    model_key: str
    attempted: int
    success: int
    failed: int
    quarantined: int
    paused: int
    first_attempt_success: int
    retryable_pages: int
    stall_pages: int
    oom_pages: int
    crash_pages: int
    malformed_pages: int
    timeout_pages: int
    rate_limit_pages: int
    wasted_gpu_seconds: float
    success_total_ms: list[float] = field(default_factory=list, repr=False)
    peak_vram_mb: list[float] = field(default_factory=list, repr=False)
    gpu_types: tuple[str, ...] = ()
    api_equivalent_usd: list[float] = field(default_factory=list, repr=False)

    # ---- derived rate cells (numerator/denominator both explicit) ----

    def _rate(self, numerator: int) -> Cell:
        if self.attempted == 0:
            return na_reason("no page receipts found for this model")
        return to_cell(round(numerator / self.attempted, 6))

    @property
    def completion_rate(self) -> Cell:
        return self._rate(self.success)

    @property
    def first_attempt_success_rate(self) -> Cell:
        return self._rate(self.first_attempt_success)

    @property
    def retry_rate(self) -> Cell:
        return self._rate(self.retryable_pages)

    @property
    def stall_rate(self) -> Cell:
        return self._rate(self.stall_pages)

    @property
    def oom_rate(self) -> Cell:
        return self._rate(self.oom_pages)

    @property
    def crash_rate(self) -> Cell:
        return self._rate(self.crash_pages)

    @property
    def malformed_rate(self) -> Cell:
        return self._rate(self.malformed_pages)

    @property
    def timeout_rate(self) -> Cell:
        return self._rate(self.timeout_pages)

    @property
    def rate_limit_rate(self) -> Cell:
        return self._rate(self.rate_limit_pages)

    @property
    def unresolved_rate(self) -> Cell:
        return self._rate(self.failed + self.quarantined)

    @property
    def sec_per_page_mean(self) -> Cell:
        if not self.success_total_ms:
            return na_reason("no SUCCESS receipts to measure latency from")
        return to_cell(round(statistics.mean(self.success_total_ms) / 1000.0, 4))

    def sec_per_page_quantile(self, q: float) -> Cell:
        value = quantile([v / 1000.0 for v in self.success_total_ms], q)
        if value is None:
            return na_reason("no SUCCESS receipts to measure latency from")
        return to_cell(round(value, 4))

    @property
    def peak_vram_mb_mean(self) -> Cell:
        if not self.peak_vram_mb:
            return na_reason("no receipt in this run recorded peak_vram_mb")
        return to_cell(round(statistics.mean(self.peak_vram_mb), 1))

    @property
    def peak_vram_mb_max(self) -> Cell:
        if not self.peak_vram_mb:
            return na_reason("no receipt in this run recorded peak_vram_mb")
        return to_cell(round(max(self.peak_vram_mb), 1))

    @property
    def api_equivalent_usd_total(self) -> Cell:
        if not self.api_equivalent_usd:
            return na_reason("no subscription-lane receipt carried api_equivalent_list_price_usd")
        return to_cell(round(sum(self.api_equivalent_usd), 6))

    @property
    def api_equivalent_usd_per_page(self) -> Cell:
        if not self.api_equivalent_usd:
            return na_reason("no subscription-lane receipt carried api_equivalent_list_price_usd")
        return to_cell(round(sum(self.api_equivalent_usd) / len(self.api_equivalent_usd), 6))


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def compute_model_metrics(model_key: str, run: ModelRunSource) -> ModelMetrics:
    """Fold a model's page receipts into one :class:`ModelMetrics`."""

    success = failed = quarantined = paused = 0
    first_attempt_success = 0
    retryable = stall = oom = crash = malformed = timeout = rate_limited = 0
    wasted = 0.0
    success_ms: list[float] = []
    vram: list[float] = []
    gpu_types: set[str] = set()
    api_equivalent: list[float] = []

    for receipt in run.receipts:
        if "_load_error" in receipt:
            continue
        status = receipt.get("status")
        if status == "SUCCESS":
            success += 1
            if receipt.get("attempt") == 1:
                first_attempt_success += 1
            total_ms = _as_number(receipt.get("total_ms"))
            if total_ms is not None:
                success_ms.append(total_ms)
        elif status == "FAILED":
            failed += 1
        elif status == "QUARANTINED":
            quarantined += 1
        elif status == "PAUSED":
            paused += 1

        retry_count = receipt.get("retry_count")
        if isinstance(retry_count, int) and retry_count > 0:
            retryable += 1

        error_class = receipt.get("error_class")
        if isinstance(error_class, str):
            if error_class in STALL_CLASSES:
                stall += 1
            if error_class in OOM_CLASSES:
                oom += 1
            if error_class in CRASH_CLASSES:
                crash += 1
            if error_class in MALFORMED_CLASSES:
                malformed += 1
            if error_class in TIMEOUT_CLASSES:
                timeout += 1
            if error_class in RATE_LIMIT_CLASSES:
                rate_limited += 1

        wasted_value = _as_number(receipt.get("wasted_gpu_seconds"))
        if wasted_value is not None:
            wasted += wasted_value

        vram_value = _as_number(receipt.get("peak_vram_mb"))
        if vram_value is not None:
            vram.append(vram_value)

        gpu_type = receipt.get("gpu_type")
        if isinstance(gpu_type, str):
            gpu_types.add(gpu_type)

        api_price = _as_number(receipt.get("api_equivalent_list_price_usd"))
        if api_price is not None:
            api_equivalent.append(api_price)

    valid_receipts = [r for r in run.receipts if "_load_error" not in r]

    return ModelMetrics(
        model_key=model_key,
        attempted=len(valid_receipts),
        success=success,
        failed=failed,
        quarantined=quarantined,
        paused=paused,
        first_attempt_success=first_attempt_success,
        retryable_pages=retryable,
        stall_pages=stall,
        oom_pages=oom,
        crash_pages=crash,
        malformed_pages=malformed,
        timeout_pages=timeout,
        rate_limit_pages=rate_limited,
        wasted_gpu_seconds=wasted,
        success_total_ms=success_ms,
        peak_vram_mb=vram,
        gpu_types=tuple(sorted(gpu_types)),
        api_equivalent_usd=api_equivalent,
    )


@dataclass(frozen=True, slots=True)
class PodCostAgg:
    model_key: str
    pod_count: int
    billed_seconds: float
    model_loading_seconds: float
    useful_inference_seconds: float
    retry_seconds: float
    idle_seconds: float
    estimated_provider_cost_usd: float
    useful_cost_usd: float
    wasted_cost_usd: float
    gpu_types: tuple[str, ...]

    @property
    def operational_efficiency(self) -> Cell:
        if self.billed_seconds <= 0:
            return na_reason("no billed_seconds recorded in the pod ledger for this model")
        return to_cell(round(self.useful_inference_seconds / self.billed_seconds, 6))

    @property
    def idle_overhead_ratio(self) -> Cell:
        if self.billed_seconds <= 0:
            return na_reason("no billed_seconds recorded in the pod ledger for this model")
        return to_cell(round(self.idle_seconds / self.billed_seconds, 6))

    @property
    def retry_overhead_ratio(self) -> Cell:
        if self.billed_seconds <= 0:
            return na_reason("no billed_seconds recorded in the pod ledger for this model")
        return to_cell(round(self.retry_seconds / self.billed_seconds, 6))

    @property
    def startup_overhead_ratio(self) -> Cell:
        if self.billed_seconds <= 0:
            return na_reason("no billed_seconds recorded in the pod ledger for this model")
        return to_cell(round(self.model_loading_seconds / self.billed_seconds, 6))


def aggregate_pod_costs(model_key: str, rows: list[dict[str, Any]]) -> PodCostAgg | None:
    """Sum every pod-ledger row for one model. ``None`` when there are none."""

    mine = [row for row in rows if row.get("model_key") == model_key]
    if not mine:
        return None
    gpu_types = sorted({row["gpu_type"] for row in mine if isinstance(row.get("gpu_type"), str)})

    def total(field_name: str) -> float:
        return sum(_as_number(row.get(field_name)) or 0.0 for row in mine)

    return PodCostAgg(
        model_key=model_key,
        pod_count=len(mine),
        billed_seconds=total("billed_seconds"),
        model_loading_seconds=total("model_loading_seconds"),
        useful_inference_seconds=total("useful_inference_seconds"),
        retry_seconds=total("retry_seconds"),
        idle_seconds=total("idle_seconds"),
        estimated_provider_cost_usd=total("estimated_provider_cost_usd"),
        useful_cost_usd=total("useful_cost_usd"),
        wasted_cost_usd=total("wasted_cost_usd"),
        gpu_types=tuple(gpu_types),
    )


def cost_usd_per_1000_pages(metrics: ModelMetrics, pod: PodCostAgg | None) -> Cell:
    """``$/1,000 pages`` for one model: subscription api-equivalent, else pod-ledger rate.

    Never ``$0/page`` for the subscription lane (masterplan section 21): a
    model with receipts carrying ``api_equivalent_list_price_usd`` always
    prices from that, even if no pod ledger entry could ever exist for it.
    """

    if metrics.api_equivalent_usd:
        return to_cell(
            round(sum(metrics.api_equivalent_usd) / len(metrics.api_equivalent_usd) * 1000.0, 4)
        )
    if pod is not None and metrics.success > 0:
        return to_cell(round(pod.estimated_provider_cost_usd / metrics.success * 1000.0, 4))
    return na_reason(
        "no cost/pod_ledger.jsonl rows for this model and no api_equivalent_list_price_usd "
        "on its receipts"
    )
