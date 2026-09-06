"""Canary protocol and projection — masterplan sections 17 and 18.

Section 17's last line is the whole design: **canary 성능 점수로 모델을 탈락시키지
않는다. Runtime correctness만 본다.** A model that is slow passes. A model whose
process starts, loads the pinned revision, emits non-empty schema-valid output
on every non-blank page and never hard-crashes passes. Speed becomes an ETA and
a cost projection, never a verdict.

The canary also produces the numbers the rest of the campaign depends on: the
warm sec/page median, the p95 that sets the dynamic stall threshold (section
15.5) and the projected GPU-hours, cost and wall time (section 18).
"""

from __future__ import annotations

import io
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from arena.constants import CAMPAIGN_ID, TOTAL_SAMPLES
from arena.controller.paths import CampaignPaths
from arena.core.receipts import validate
from arena.provider.safety import read_json, utc_now_iso, write_json_atomic

__all__ = [
    "BLANK_DARK_FRACTION",
    "CRITERION_NAMES",
    "DARK_PIXEL_VALUE",
    "NON_EMPTY_OUTPUT_MIN_RATIO",
    "OVERHEAD_FACTOR_HIGH",
    "OVERHEAD_FACTOR_LOW",
    "CanaryError",
    "CanaryPageResult",
    "CanaryReport",
    "Projection",
    "canary_receipt_document",
    "dark_pixel_fraction",
    "evaluate_canary",
    "load_canary_selection",
    "project",
    "results_from_receipts",
    "stage_percentiles",
    "write_canary_receipt",
    "write_registry_update",
]

# Masterplan section 18: start here, replace with measured values in flight.
OVERHEAD_FACTOR_LOW: Final = 1.10
OVERHEAD_FACTOR_HIGH: Final = 1.25

# Blankness is measured, not assumed. Until 2026-09-03 ``blank_source`` was
# never set by anything, so "non-empty on non-blank pages" silently meant "on
# every page" -- and the GLM-OCR canary of that day failed on one colourful
# textbook page (80% white, 1.9% dark) that returned 0 chars. A page is blank
# when almost nothing on it is ink.
DARK_PIXEL_VALUE: Final = 100  # 8-bit grey; below this counts as ink
BLANK_DARK_FRACTION: Final = 0.002  # under 0.2% ink -> blank
# Section 17 qualifies a runtime, it does not grade output. One model that
# returns nothing on one page out of fifteen is a semantic result for the
# recovery lane, not a broken runtime; a model that returns nothing on a tenth
# of the canary is broken.
NON_EMPTY_OUTPUT_MIN_RATIO: Final = 0.90


class CanaryError(RuntimeError):
    """The canary cannot be evaluated from what was recorded."""


@dataclass(frozen=True, slots=True)
class CanaryPageResult:
    case_key: str
    sample_id: str
    benchmark: str
    status: str
    error_class: str | None
    total_ms: int
    load_ms: int
    preprocess_ms: int
    inference_ms: int
    postprocess_ms: int
    output_chars: int
    peak_vram_mb: int | None
    model_revision: str
    schema_valid: bool
    blank_source: bool = False
    warm: bool = True
    # Measured share of ink pixels (see ``dark_pixel_fraction``). None when the
    # page bytes were not available to classify; the page then counts as
    # non-blank, which is the stricter reading.
    dark_fraction: float | None = None
    # Whole-GPU totals the worker measured, when it could (ARENA_CONTRACT
    # section 17's headroom is against a real device, not a rented floor).
    vram_total_mb: int | None = None
    vram_measurement_source: str | None = None

    @property
    def seconds(self) -> float:
        return self.total_ms / 1000.0


@dataclass(frozen=True, slots=True)
class Projection:
    warm_sec_per_page: float | None
    gpu_hours_projected: float | None
    raw_gpu_cost_projected_usd: float | None
    wall_time_hours_low: float | None
    wall_time_hours_high: float | None
    replica_count: int
    hourly_rate_usd: float | None
    price_row_sha256: str | None
    sample_count: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "warm_sec_per_page": _round(self.warm_sec_per_page, 4),
            "gpu_hours_projected": _round(self.gpu_hours_projected, 3),
            "raw_gpu_cost_projected_usd": _round(self.raw_gpu_cost_projected_usd, 3),
            "wall_time_hours_low": _round(self.wall_time_hours_low, 3),
            "wall_time_hours_high": _round(self.wall_time_hours_high, 3),
            "replica_count": self.replica_count,
            "hourly_rate_usd": self.hourly_rate_usd,
            "price_row_sha256": self.price_row_sha256,
            "projected_over_samples": self.sample_count,
            "overhead_factor_range": [OVERHEAD_FACTOR_LOW, OVERHEAD_FACTOR_HIGH],
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class CanaryReport:
    model_key: str
    passed: bool
    checks: Mapping[str, bool]
    failures: tuple[str, ...]
    page_count: int
    success_count: int
    stages: Mapping[str, Mapping[str, float | None]]
    warm_median_sec_per_page: float | None
    p95_sec_per_page: float | None
    peak_vram_mb: int | None
    vram_headroom_mb: int | None
    projection: Projection
    model_revision_observed: str | None
    evaluated_at: str = ""
    vram_total_mb: int | None = None
    vram_measurement_source: str | None = None
    # Every non-blank SUCCESS page the model returned nothing for. These do not
    # fail the canary below the threshold, but they are never dropped: the
    # recovery lane reads this list.
    empty_output_pages: tuple[Mapping[str, Any], ...] = ()
    non_empty_output_ratio: float | None = None
    non_blank_success_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.canary_report.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": self.model_key,
            "evaluated_at": self.evaluated_at or utc_now_iso(),
            "result": "PASS" if self.passed else "FAIL",
            "criteria": "runtime correctness only (masterplan section 17)",
            "checks": dict(self.checks),
            "failures": list(self.failures),
            "page_count": self.page_count,
            "success_count": self.success_count,
            "stage_percentiles_ms": {
                stage: dict(values) for stage, values in self.stages.items()
            },
            "warm_median_sec_per_page": _round(self.warm_median_sec_per_page, 4),
            "p95_sec_per_page": _round(self.p95_sec_per_page, 4),
            "peak_vram_mb": self.peak_vram_mb,
            "vram_headroom_mb": self.vram_headroom_mb,
            "vram_total_mb": self.vram_total_mb,
            "vram_measurement_source": self.vram_measurement_source,
            "empty_output_pages": [dict(page) for page in self.empty_output_pages],
            "non_empty_output_ratio": _round(self.non_empty_output_ratio, 4),
            "non_blank_success_count": self.non_blank_success_count,
            "model_revision_observed": self.model_revision_observed,
            "projection": self.projection.to_dict(),
        }


def load_canary_selection(path: Path, model_key: str) -> tuple[str, ...]:
    """Case keys lane A2 selected for this campaign's canary (section 17)."""

    if not path.is_file():
        raise CanaryError(
            f"{path.name} is absent; run `python -m arena.manifest build` (lane A2) first"
        )
    document = read_json(path)
    if isinstance(document, Mapping):
        per_model = document.get("per_model")
        if isinstance(per_model, Mapping):
            selected = per_model.get(model_key)
            if isinstance(selected, Sequence) and not isinstance(selected, str):
                return tuple(str(item) for item in selected)
        # Lane A2's shape: one GT-blind selection shared by every GPU model,
        # carried as sample objects under ``gpu_canary.samples``.
        gpu_canary = document.get("gpu_canary")
        if isinstance(gpu_canary, Mapping):
            samples = gpu_canary.get("samples")
            if isinstance(samples, Sequence) and not isinstance(samples, str):
                case_keys = tuple(
                    str(sample["case_key"])
                    for sample in samples
                    if isinstance(sample, Mapping) and sample.get("case_key")
                )
                if case_keys:
                    return case_keys
        shared = document.get("case_keys", document.get("selection"))
        if isinstance(shared, Sequence) and not isinstance(shared, str):
            return tuple(str(item) for item in shared)
    if isinstance(document, Sequence) and not isinstance(document, str):
        return tuple(str(item) for item in document)
    raise CanaryError(f"{path.name} does not carry a case-key selection for {model_key!r}")


def stage_percentiles(
    results: Sequence[CanaryPageResult],
) -> dict[str, dict[str, float | None]]:
    """p50 / p90 / p95 per stage, over successful pages (section 15.5)."""

    successes = [result for result in results if result.status == "SUCCESS"]
    stages = {
        "load_ms": [float(result.load_ms) for result in successes],
        "preprocess_ms": [float(result.preprocess_ms) for result in successes],
        "inference_ms": [float(result.inference_ms) for result in successes],
        "postprocess_ms": [float(result.postprocess_ms) for result in successes],
        "total_ms": [float(result.total_ms) for result in successes],
    }
    return {
        stage: {
            "p50": _percentile(values, 0.50),
            "p90": _percentile(values, 0.90),
            "p95": _percentile(values, 0.95),
        }
        for stage, values in stages.items()
    }


def project(
    results: Sequence[CanaryPageResult],
    *,
    hourly_rate_usd: float | None,
    price_row_sha256: str | None,
    replica_count: int = 1,
    sample_count: int = TOTAL_SAMPLES,
) -> Projection:
    """Masterplan section 18, with every gap named instead of filled."""

    if replica_count < 1:
        raise CanaryError("replica_count must be at least 1")
    warm = [
        result.seconds
        for result in results
        if result.status == "SUCCESS" and result.warm and result.total_ms > 0
    ]
    notes: list[str] = []
    if not warm:
        notes.append("no warm successful canary page; nothing can be projected")
        return Projection(
            warm_sec_per_page=None,
            gpu_hours_projected=None,
            raw_gpu_cost_projected_usd=None,
            wall_time_hours_low=None,
            wall_time_hours_high=None,
            replica_count=replica_count,
            hourly_rate_usd=hourly_rate_usd,
            price_row_sha256=price_row_sha256,
            sample_count=sample_count,
            notes=tuple(notes),
        )
    warm_median = statistics.median(warm)
    gpu_hours = warm_median * sample_count / 3600.0
    if hourly_rate_usd is None:
        notes.append(
            "no catalog price row for the selected GPU; the cost projection is not computable"
        )
        cost = None
    else:
        cost = gpu_hours * hourly_rate_usd
    wall_base = gpu_hours / replica_count
    return Projection(
        warm_sec_per_page=warm_median,
        gpu_hours_projected=gpu_hours,
        raw_gpu_cost_projected_usd=cost,
        wall_time_hours_low=wall_base * OVERHEAD_FACTOR_LOW,
        wall_time_hours_high=wall_base * OVERHEAD_FACTOR_HIGH,
        replica_count=replica_count,
        hourly_rate_usd=hourly_rate_usd,
        price_row_sha256=price_row_sha256,
        sample_count=sample_count,
        notes=tuple(notes),
    )


def evaluate_canary(
    model_key: str,
    results: Sequence[CanaryPageResult],
    *,
    expected_model_revision: str,
    gpu_vram_mb: int | None = None,
    hourly_rate_usd: float | None = None,
    price_row_sha256: str | None = None,
    replica_count: int = 1,
    evaluator_accepts_output: bool = True,
    hard_crashes: int = 0,
    deterministic_runtime_bugs: int = 0,
) -> CanaryReport:
    """PASS/FAIL on runtime correctness only (masterplan section 17)."""

    if not results:
        raise CanaryError(f"canary for {model_key} produced no page results")

    successes = [result for result in results if result.status == "SUCCESS"]
    revisions = {result.model_revision for result in results if result.model_revision}
    observed = next(iter(revisions), None) if len(revisions) == 1 else None

    projection = project(
        results,
        hourly_rate_usd=hourly_rate_usd,
        price_row_sha256=price_row_sha256,
        replica_count=replica_count,
    )

    # The headroom denominator: what the GPU actually has, when the worker
    # measured it, and only otherwise the runtime's declared floor. They are
    # different numbers -- a 4090 rented against a 24 GB floor reports 24564
    # MiB, not 24576 -- and the measured one is the true one.
    measured_totals = [
        result.vram_total_mb for result in results if result.vram_total_mb is not None
    ]
    vram_total_mb = max(measured_totals) if measured_totals else None
    sources = {
        result.vram_measurement_source
        for result in results
        if result.vram_measurement_source is not None
    }
    vram_source = sources.pop() if len(sources) == 1 else None
    headroom_basis = vram_total_mb if vram_total_mb is not None else gpu_vram_mb

    non_blank_successes = [result for result in successes if not result.blank_source]
    empty_output_pages = tuple(
        {
            "case_key": result.case_key,
            "sample_id": result.sample_id,
            "dark_fraction": _round(result.dark_fraction, 6),
            "total_ms": result.total_ms,
            # The vocabulary arena/core/schemas/page-receipt.schema.json already
            # uses for "the model was wrong, not the run" (D3), so the recovery
            # lane matches on the same string it matches on everywhere else.
            "semantic_error_class": "OUTPUT_EMPTY",
        }
        for result in non_blank_successes
        if result.output_chars <= 0
    )
    non_empty_ratio = (
        None
        if not non_blank_successes
        else (len(non_blank_successes) - len(empty_output_pages)) / len(non_blank_successes)
    )

    checks: dict[str, bool] = {
        "process_started": bool(results),
        "correct_model_revision": revisions == {expected_model_revision},
        # Section 17 qualifies the runtime. A model that answered on at least
        # 90% of the non-blank pages has a working runtime; the pages it left
        # empty are a semantic result, listed in the receipt and handed to the
        # recovery lane rather than used to fail the pod.
        "output_non_empty_on_non_blank": (
            non_empty_ratio is None or non_empty_ratio >= NON_EMPTY_OUTPUT_MIN_RATIO
        ),
        "output_schema_valid": all(result.schema_valid for result in successes),
        "evaluator_adapter_accepts": evaluator_accepts_output,
        "no_hard_crash": hard_crashes == 0,
        "no_deterministic_runtime_bug": deterministic_runtime_bugs == 0,
        "sec_per_page_measured": bool(successes),
        # A whole-GPU peak from nvidia-smi is a measurement: most runtimes here
        # serve the model from a process the worker does not own, so a
        # per-process figure does not exist and demanding one failed every
        # canary (GLM-OCR, 2026-09-03, 15/15 pages with peak_vram_mb null).
        "vram_headroom_measured": headroom_basis is not None
        and any(result.peak_vram_mb is not None for result in successes),
        # A price alone does not make a projection. Section 18 projects from
        # the *warm* median, so a canary with no warm successful page has
        # nothing to project from -- and a PASS whose receipt carries null
        # GPU-hours would be a canary that measured nothing calling itself a
        # measurement.
        "cost_projection_computable": (
            hourly_rate_usd is not None
            and bool(successes)
            and projection.gpu_hours_projected is not None
            and projection.raw_gpu_cost_projected_usd is not None
        ),
    }
    failures = tuple(
        _failure_message(
            name,
            model_key,
            expected_model_revision,
            observed,
            non_empty_ratio=non_empty_ratio,
            empty_count=len(empty_output_pages),
            non_blank_count=len(non_blank_successes),
        )
        for name, ok in checks.items()
        if not ok
    )

    peaks = [result.peak_vram_mb for result in successes if result.peak_vram_mb is not None]
    peak = max(peaks) if peaks else None
    headroom = None if (peak is None or headroom_basis is None) else headroom_basis - peak

    warm_seconds = [result.seconds for result in successes if result.warm]

    return CanaryReport(
        model_key=model_key,
        passed=not failures,
        checks=checks,
        failures=failures,
        page_count=len(results),
        success_count=len(successes),
        stages=stage_percentiles(results),
        warm_median_sec_per_page=(statistics.median(warm_seconds) if warm_seconds else None),
        p95_sec_per_page=_percentile([result.seconds for result in successes], 0.95),
        peak_vram_mb=peak,
        vram_headroom_mb=headroom,
        vram_total_mb=vram_total_mb,
        vram_measurement_source=vram_source,
        empty_output_pages=empty_output_pages,
        non_empty_output_ratio=non_empty_ratio,
        non_blank_success_count=len(non_blank_successes),
        projection=projection,
        model_revision_observed=observed,
        evaluated_at=utc_now_iso(),
    )


# ARENA_CONTRACT 11.5 D26: the receipt this lane writes must satisfy
# arena/core/schemas/canary-receipt.schema.json, whose criterion names are
# lane A1's (``arena.core.receipts.CANARY_CRITERIA``). The section 17 checks
# above are this module's own vocabulary; this is the one place the two are
# joined, so a rename on either side breaks a test rather than a receipt.
CRITERION_NAMES: Final = MappingProxyType(
    {
        "process_started": "process_start",
        "correct_model_revision": "correct_model_revision",
        "output_non_empty_on_non_blank": "output_non_empty_on_nonblank",
        "output_schema_valid": "output_schema_valid",
        "evaluator_adapter_accepts": "evaluator_adapter_accepts_output",
        "no_hard_crash": "zero_hard_crash",
        "no_deterministic_runtime_bug": "zero_deterministic_runtime_bug",
        "sec_per_page_measured": "measured_sec_per_page",
        "vram_headroom_measured": "vram_headroom",
        "cost_projection_computable": "full_run_projection_computable",
    }
)


def canary_receipt_document(
    report: CanaryReport,
    *,
    model_revision: str,
    runtime_image_digest: str,
    runtime_mode: str,
    gpu_type: str,
    started_at: str,
    finished_at: str,
    base_image: str | None = None,
    gpu_compute_capability: str | None = None,
    pod_id: str | None = None,
    authorization_receipt_path: str | None = None,
    authorization_receipt_sha256: str | None = None,
    pod_ledger_path: str | None = None,
    gpu_total_vram_mb: int | None = None,
    campaign_id: str = CAMPAIGN_ID,
) -> dict[str, object]:
    """Build the schema-shaped canary receipt (D26).

    Every metric that was not measured stays ``null``. The schema refuses a
    PASS that carries no projection, which is the point: "we could not measure
    it" is not a pass, and a receipt that filled the gap with a zero would let
    one through.
    """

    projection = report.projection
    stages: dict[str, dict[str, float]] = {}
    for stage, values in report.stages.items():
        p50, p90, p95 = values.get("p50"), values.get("p90"), values.get("p95")
        if p50 is None or p90 is None or p95 is None:
            # A stage with no successful page has no quantiles. The schema's
            # quantile object requires all three, so the stage is omitted
            # rather than zero-filled.
            continue
        stages[stage] = {"p50_ms": p50, "p90_ms": p90, "p95_ms": p95}

    criteria = [
        {
            "criterion": CRITERION_NAMES[name],
            "passed": bool(passed),
            "detail": (
                f"section 17 check {name} passed"
                if passed
                else _failure_message(
                    name,
                    report.model_key,
                    model_revision,
                    report.model_revision_observed,
                    non_empty_ratio=report.non_empty_output_ratio,
                    empty_count=len(report.empty_output_pages),
                    non_blank_count=report.non_blank_success_count,
                )
            ),
        }
        for name, passed in report.checks.items()
        if name in CRITERION_NAMES
    ]
    missing = sorted(set(CRITERION_NAMES.values()) - {item["criterion"] for item in criteria})
    if missing:
        raise CanaryError(
            f"canary report for {report.model_key} produced no verdict for {missing}; "
            "the receipt would claim a check that never ran"
        )

    wall_time = (
        None
        if projection.gpu_hours_projected is None
        else projection.gpu_hours_projected
        / projection.replica_count
        * OVERHEAD_FACTOR_HIGH
    )
    document: dict[str, object] = {
        "schema": "tavonel.arena.canary-receipt.v1",
        "campaign_id": campaign_id,
        "model_key": report.model_key,
        "model_revision": model_revision,
        "runtime_image_digest": runtime_image_digest,
        "runtime_mode": runtime_mode,
        "base_image": base_image,
        "gpu_type": gpu_type,
        "gpu_compute_capability": gpu_compute_capability,
        "pod_id": pod_id,
        "authorization_receipt_path": authorization_receipt_path,
        "authorization_receipt_sha256": authorization_receipt_sha256,
        "pod_ledger_path": pod_ledger_path,
        "started_at": started_at,
        "finished_at": finished_at,
        "page_count": report.page_count,
        "success_count": report.success_count,
        "failed_count": report.page_count - report.success_count,
        "stage_latency_ms": stages,
        "peak_vram_mb": report.peak_vram_mb,
        # The measured device total wins over the runtime's declared floor:
        # gpu_total_vram_mb is what the pod was rented against, report.
        # vram_total_mb is what nvidia-smi found on the card.
        "gpu_total_vram_mb": (
            report.vram_total_mb if report.vram_total_mb is not None else gpu_total_vram_mb
        ),
        "vram_headroom_mb": report.vram_headroom_mb,
        "vram_measurement_source": report.vram_measurement_source,
        # Extension keys (the schema root is additionalProperties:true, D26):
        # a page the model returned nothing for is a semantic result, and it is
        # named here so the recovery lane can pick it up whether or not the
        # canary passed.
        "empty_output_pages": [dict(page) for page in report.empty_output_pages],
        "non_empty_output_ratio": _round(report.non_empty_output_ratio, 4),
        "non_blank_success_count": report.non_blank_success_count,
        "warm_sec_per_page": _round(projection.warm_sec_per_page, 4),
        "total_samples": projection.sample_count,
        "replica_count": projection.replica_count,
        # The conservative end of the section 18 band. The optimistic end is
        # carried alongside as an extension so neither is lost.
        "overhead_factor": OVERHEAD_FACTOR_HIGH,
        "wall_time_hours_low": _round(projection.wall_time_hours_low, 3),
        "wall_time_hours_high": _round(projection.wall_time_hours_high, 3),
        "selected_gpu_hourly_rate_usd": projection.hourly_rate_usd,
        "price_snapshot_sha256": _sha256_ref(projection.price_row_sha256),
        "gpu_hours_projected": _round(projection.gpu_hours_projected, 3),
        "raw_gpu_cost_projected_usd": _round(projection.raw_gpu_cost_projected_usd, 3),
        "wall_time_hours_projected": _round(wall_time, 3),
        "status": "PASS" if report.passed else "FAIL",
        "criteria": criteria,
        "fail_reasons": list(report.failures),
        # Extension detail (the schema is additionalProperties: true, D26).
        "criteria_basis": "runtime correctness only (masterplan section 17)",
        "p50_sec_per_page": _round(_percentile_of(stages, "p50_ms"), 4),
        "p90_sec_per_page": _round(_percentile_of(stages, "p90_ms"), 4),
        "p95_sec_per_page": _round(report.p95_sec_per_page, 4),
        "projection_notes": list(projection.notes),
    }
    return document


def write_canary_receipt(
    report: CanaryReport,
    paths: CampaignPaths,
    *,
    model_revision: str | None = None,
    runtime_image_digest: str | None = None,
    runtime_mode: str = "bootstrap",
    gpu_type: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    **extra: object,
) -> Path:
    """Validate against ``canary-receipt.schema.json``, then write it (D26).

    Validation happens **before** any byte is written, so a receipt that would
    not satisfy the contract never reaches disk at all.
    """

    revision = model_revision or report.model_revision_observed
    if not revision:
        raise CanaryError(
            f"canary receipt for {report.model_key} has no model_revision to record; "
            "the worker reported none and the caller supplied none"
        )
    if not runtime_image_digest:
        raise CanaryError(
            f"canary receipt for {report.model_key} needs a runtime_image_digest "
            "(bootstrap:<bundle sha256> for a bootstrap canary, ARENA_CONTRACT 11.5 D15)"
        )
    if not gpu_type:
        raise CanaryError(
            f"canary receipt for {report.model_key} needs the GPU the pod actually ran on"
        )
    document = canary_receipt_document(
        report,
        model_revision=revision,
        runtime_image_digest=runtime_image_digest,
        runtime_mode=runtime_mode,
        gpu_type=gpu_type,
        started_at=started_at or report.evaluated_at or utc_now_iso(),
        finished_at=finished_at or report.evaluated_at or utc_now_iso(),
        **extra,  # type: ignore[arg-type]
    )
    validate(document, "canary-receipt")
    path = paths.canary_receipt(report.model_key)
    write_json_atomic(path, document, context="canary receipt")
    return path


def _percentile_of(stages: Mapping[str, Mapping[str, float]], key: str) -> float | None:
    total = stages.get("total_ms")
    if total is None:
        return None
    value = total.get(key)
    return None if value is None else value / 1000.0


def _sha256_ref(value: str | None) -> str | None:
    """The canary schema wants ``sha256:<hex>``; row hashes are bare hex."""

    if value is None:
        return None
    return value if value.startswith("sha256:") else f"sha256:{value}"


def write_registry_update(report: CanaryReport, paths: CampaignPaths) -> Path:
    """Record the registry change the canary implies, without editing A3's file.

    ``model_registry.json`` belongs to lane A3 and is never edited in place by
    the controller. The intended field change is written here instead, and the
    orchestrator reconciles it.
    """

    path = paths.registry_update(report.model_key)
    write_json_atomic(
        path,
        {
            "schema": "tavonel.arena.registry_update.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": report.model_key,
            "proposed_at": utc_now_iso(),
            "source": f"receipts/canary-{report.model_key}.json",
            "fields": {
                "canary_status": "PASS" if report.passed else "FAIL",
                "full_run_eligible": report.passed,
                "canary_warm_sec_per_page": _round(report.warm_median_sec_per_page, 4),
                "canary_p95_sec_per_page": _round(report.p95_sec_per_page, 4),
                "canary_peak_vram_mb": report.peak_vram_mb,
                "canary_empty_output_pages": [
                    dict(page) for page in report.empty_output_pages
                ],
            },
            "note": (
                "full_run_eligible still requires a baked runtime image or a founder "
                "waiver receipt; a canary PASS alone does not authorize a Full Run"
                + (
                    ""
                    if not report.empty_output_pages
                    else (
                        f"; {len(report.empty_output_pages)} non-blank page(s) returned no "
                        "output and are labelled semantic_error_class=OUTPUT_EMPTY in "
                        "canary_empty_output_pages for the recovery lane"
                    )
                )
            ),
        },
        context="registry update",
    )
    return path


def dark_pixel_fraction(png: bytes) -> float:
    """Share of pixels darker than :data:`DARK_PIXEL_VALUE`, i.e. ink.

    Greyscale, not colour: a page can be 80% white and still be dense with
    text, and a saturated illustration is not blankness. The measure is the
    one thing that separates "the model had nothing to read" from "the model
    read nothing".
    """

    from PIL import Image  # pillow is the only non-stdlib dependency in this plane

    with Image.open(io.BytesIO(png)) as image:
        histogram = image.convert("L").histogram()
    total = sum(histogram)
    if total == 0:  # pragma: no cover - a zero-pixel PNG is not a page
        raise CanaryError("page image has no pixels; it cannot be classified as blank or not")
    return sum(histogram[:DARK_PIXEL_VALUE]) / total


def results_from_receipts(
    receipts: Sequence[Mapping[str, Any]],
    *,
    warm_after: int = 1,
    page_bytes: Callable[[str], bytes] | None = None,
) -> tuple[CanaryPageResult, ...]:
    """Turn page receipts into canary results; the first page is cold.

    ``page_bytes`` resolves a ``case_key`` to the PNG the model was sent, and
    is what makes ``blank_source`` a measurement instead of a default nobody
    set. Without it every page counts as non-blank -- the stricter reading,
    and the behaviour before 2026-09-03.
    """

    ordered = sorted(receipts, key=lambda receipt: str(receipt.get("started_at", "")))
    results: list[CanaryPageResult] = []
    for index, receipt in enumerate(ordered):
        case_key = str(receipt.get("case_key", ""))
        dark_fraction = _dark_fraction_for(case_key, page_bytes)
        results.append(
            CanaryPageResult(
                case_key=case_key,
                sample_id=str(receipt.get("sample_id", "")),
                benchmark=str(receipt.get("benchmark", "")),
                status=str(receipt.get("status", "FAILED")),
                error_class=_optional_str(receipt.get("error_class")),
                total_ms=_int(receipt.get("total_ms")),
                load_ms=_int(receipt.get("load_ms")),
                preprocess_ms=_int(receipt.get("preprocess_ms")),
                inference_ms=_int(receipt.get("inference_ms")),
                postprocess_ms=_int(receipt.get("postprocess_ms")),
                output_chars=_int(receipt.get("output_chars")),
                peak_vram_mb=(
                    _int(receipt.get("peak_vram_mb"))
                    if receipt.get("peak_vram_mb") is not None
                    else None
                ),
                model_revision=str(receipt.get("model_revision", "")),
                schema_valid=bool(receipt.get("status") == "SUCCESS"),
                warm=index >= warm_after,
                dark_fraction=dark_fraction,
                blank_source=(
                    dark_fraction is not None and dark_fraction < BLANK_DARK_FRACTION
                ),
                vram_total_mb=(
                    _int(receipt.get("vram_total_mb"))
                    if receipt.get("vram_total_mb") is not None
                    else None
                ),
                vram_measurement_source=_optional_str(receipt.get("vram_measurement_source")),
            )
        )
    return tuple(results)


def _dark_fraction_for(
    case_key: str, page_bytes: Callable[[str], bytes] | None
) -> float | None:
    """The page's ink fraction, or None when it could not be measured.

    A page the controller cannot re-read is left unclassified rather than
    guessed blank: calling an unreadable page blank would excuse the model
    from answering it.
    """

    if page_bytes is None or not case_key:
        return None
    try:
        return dark_pixel_fraction(page_bytes(case_key))
    except Exception:
        return None


def _failure_message(
    check: str,
    model_key: str,
    expected_revision: str,
    observed: str | None,
    *,
    non_empty_ratio: float | None = None,
    empty_count: int = 0,
    non_blank_count: int = 0,
) -> str:
    if check == "output_non_empty_on_non_blank":
        share = "unknown" if non_empty_ratio is None else f"{non_empty_ratio:.1%}"
        return (
            f"{model_key} answered on {share} of its non-blank pages "
            f"({empty_count} of {non_blank_count} returned nothing), below the "
            f"{NON_EMPTY_OUTPUT_MIN_RATIO:.0%} section 17 floor; see empty_output_pages"
        )
    if check == "correct_model_revision":
        return (
            f"{model_key} loaded revision {observed or '<mixed or unreported>'}, "
            f"not the pinned {expected_revision}"
        )
    if check == "cost_projection_computable":
        return (
            f"{model_key}: section 18 projects from the warm median, and this canary has no "
            "warm successful page (or no catalog price row) to project from. A PASS whose "
            "GPU-hours are null would report a measurement nobody made."
        )
    return f"{model_key} failed the section 17 check {check!r}"


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
