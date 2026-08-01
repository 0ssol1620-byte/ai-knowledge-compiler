"""Deterministic collection preflight sampling and quantile estimates.

The estimator is intentionally provider-neutral.  It supplies the production
contract and a conservative rules-based baseline while keeping learned
quantile models behind a separately calibrated adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Annotated, Literal

from akc_cir import ContractModel
from pydantic import Field, field_validator, model_validator

from .models import Route


class EstimateConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GpuThermalState(StrEnum):
    WARM = "warm"
    COLD = "cold"
    UNKNOWN = "unknown"


class GpuClass(StrEnum):
    CPU_ONLY = "cpu_only"
    T4 = "t4"
    L4 = "l4"
    A10 = "a10"
    A100 = "a100"
    H100 = "h100"
    UNKNOWN = "unknown"


class DimensionUnit(StrEnum):
    POINTS = "points"
    PIXELS = "pixels"
    UNKNOWN = "unknown"


class StaticDocumentFeatures(ContractModel):
    """Content-free static signals used for clustering and route estimation."""

    file_type: Annotated[str, Field(min_length=1, max_length=80)]
    page_count: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    native_text_presence: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    producer: Annotated[str, Field(max_length=160)] = ""
    font_profile: Annotated[str, Field(max_length=128)] = ""
    image_coverage: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    page_width: Annotated[int, Field(gt=0, le=100_000)] | None = None
    page_height: Annotated[int, Field(gt=0, le=100_000)] | None = None
    dimension_unit: DimensionUnit = DimensionUnit.UNKNOWN
    resolution_dpi: Annotated[float, Field(gt=0.0, le=10_000.0)] | None = None
    table_line_candidates: Annotated[int, Field(ge=0)] | None = None
    column_count: Annotated[int, Field(ge=0, le=100)] | None = None
    numeric_density: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    language_script: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    rotation_degrees: Annotated[int, Field(ge=0, le=359)] | None = None
    skew_degrees: Annotated[float, Field(ge=-45.0, le=45.0)] | None = None
    blur_score: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    compression_artifacts: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    archive_expansion_ratio: Annotated[float, Field(ge=0.0, le=10_000.0)] | None = None
    layout_fingerprint: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    document_style_signature: Annotated[str, Field(max_length=128)] = ""
    theme_master_signature: Annotated[str, Field(max_length=128)] = ""
    scan_device_signature: Annotated[str, Field(max_length=128)] = ""
    folder_context_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def build_cluster_identity(features: StaticDocumentFeatures) -> str:
    """Build a stable cluster key without retaining customer path or content."""
    identity = {
        "file_type": features.file_type.casefold(),
        "producer": features.producer.casefold(),
        "page_size": [
            features.page_width,
            features.page_height,
            features.dimension_unit.value,
        ],
        "font_profile": features.font_profile,
        "layout_fingerprint": features.layout_fingerprint,
        "document_style_signature": features.document_style_signature,
        "theme_master_signature": features.theme_master_signature,
        "scan_device_signature": features.scan_device_signature,
        "dpi_bucket": (
            round(features.resolution_dpi / 25) * 25
            if features.resolution_dpi is not None
            else None
        ),
        "folder_context_hash": features.folder_context_hash,
    }
    payload = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
    return "cluster_" + hashlib.sha256(payload).hexdigest()


class PreflightObservation(ContractModel):
    """One static page observation; no document content is retained."""

    page_id: Annotated[str, Field(min_length=1, max_length=240)]
    cluster_id: Annotated[str, Field(min_length=1, max_length=240)]
    page_index0: Annotated[int, Field(ge=0)]
    difficulty: Annotated[float, Field(ge=0.0, le=100.0)]
    native_quality: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    table_density: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    image_density: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    numeric_density: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    width: Annotated[int, Field(gt=0)] | None = None
    height: Annotated[int, Field(gt=0)] | None = None


class ClusterSamplePlan(ContractModel):
    cluster_id: str
    population: Annotated[int, Field(ge=1)]
    selected_page_ids: tuple[str, ...]
    selection_reasons: dict[str, tuple[str, ...]]
    dispersion: Annotated[float, Field(ge=0.0, le=1.0)]
    expansion_limit: Annotated[int, Field(ge=3, le=20)]

    @field_validator("selected_page_ids")
    @classmethod
    def unique_selected_pages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("selected page ids must be non-empty and unique")
        return value


class RoutePopulation(ContractModel):
    route: Route
    pages: Annotated[int, Field(ge=0)]
    sampled_pages: Annotated[int, Field(ge=0)] = 0
    sample_runtime_seconds_p50: Annotated[float, Field(ge=0.0)] | None = None
    sample_runtime_seconds_p95: Annotated[float, Field(ge=0.0)] | None = None
    recovery_probability: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0

    @model_validator(mode="after")
    def validate_samples(self) -> RoutePopulation:
        if self.sampled_pages > self.pages:
            raise ValueError("sampled pages cannot exceed route population")
        if (
            self.sample_runtime_seconds_p50 is not None
            and self.sample_runtime_seconds_p95 is not None
            and self.sample_runtime_seconds_p95 < self.sample_runtime_seconds_p50
        ):
            raise ValueError("sample runtime p95 cannot be below p50")
        return self


class CollectionEstimateInput(ContractModel):
    route_populations: tuple[RoutePopulation, ...]
    duplicate_pages: Annotated[int, Field(ge=0)] = 0
    knowledge_note_count: Annotated[int, Field(ge=0)] = 0
    entity_relation_candidates: Annotated[int, Field(ge=0)] = 0
    export_profile_count: Annotated[int, Field(ge=1, le=8)] = 1
    queue_delay_p50_seconds: Annotated[float, Field(ge=0.0)] | None = None
    queue_delay_p95_seconds: Annotated[float, Field(ge=0.0)] | None = None
    gpu_state: GpuThermalState = GpuThermalState.UNKNOWN
    gpu_class: GpuClass = GpuClass.UNKNOWN
    sample_output_tokens: Annotated[int, Field(ge=0)] = 0
    static_complexity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    max_parallel_pages: Annotated[int, Field(ge=1, le=64)] = 8
    predictor_revision: Annotated[str, Field(min_length=1, max_length=120)] = (
        "rules-quantile-2026-07-31.1"
    )
    evidence_revision: Annotated[str, Field(min_length=1, max_length=120)] = "unbound"
    evidence_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    measured_signal_fields: tuple[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")], ...
    ] = ()

    @model_validator(mode="after")
    def validate_input(self) -> CollectionEstimateInput:
        if not self.route_populations:
            raise ValueError("at least one route population is required")
        routes = [population.route for population in self.route_populations]
        if len(routes) != len(set(routes)):
            raise ValueError("route populations must be unique")
        if (self.queue_delay_p50_seconds is None) != (self.queue_delay_p95_seconds is None):
            raise ValueError("queue delay quantiles must be supplied together")
        if (
            self.queue_delay_p50_seconds is not None
            and self.queue_delay_p95_seconds is not None
            and self.queue_delay_p95_seconds < self.queue_delay_p50_seconds
        ):
            raise ValueError("queue delay p95 cannot be below p50")
        if len(self.measured_signal_fields) != len(set(self.measured_signal_fields)):
            raise ValueError("measured signal fields must be unique")
        total_pages = sum(population.pages for population in self.route_populations)
        if self.duplicate_pages > total_pages:
            raise ValueError("duplicate pages cannot exceed total pages")
        terminal_pages = sum(
            population.pages
            for population in self.route_populations
            if population.route in {Route.UNRESOLVED, Route.QUARANTINE}
        )
        if self.duplicate_pages > total_pages - terminal_pages:
            raise ValueError("duplicate pages and terminal pages must be disjoint")
        return self


class CollectionEstimate(ContractModel):
    credit_p50: Annotated[float, Field(ge=0.0)]
    credit_p95: Annotated[float, Field(ge=0.0)]
    reserve_ceiling: Annotated[float, Field(ge=0.0)]
    duration_p50_seconds: Annotated[float, Field(ge=0.0)]
    duration_p95_seconds: Annotated[float, Field(ge=0.0)]
    route_mix: dict[str, Annotated[float, Field(ge=0.0, le=1.0)]]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence_band: EstimateConfidence
    sampled_pages: Annotated[int, Field(ge=0)]
    billable_pages: Annotated[int, Field(ge=0)]
    duplicate_pages: Annotated[int, Field(ge=0)]
    unbillable_pages: Annotated[int, Field(ge=0)]
    predictor_revision: str
    evidence_revision: str
    evidence_sha256: str | None
    measured_signal_fields: tuple[str, ...]
    calibration_required: bool

    @model_validator(mode="after")
    def validate_quantiles(self) -> CollectionEstimate:
        if self.credit_p95 < self.credit_p50:
            raise ValueError("credit p95 cannot be below p50")
        if self.reserve_ceiling < self.credit_p95:
            raise ValueError("reserve ceiling cannot be below credit p95")
        if self.duration_p95_seconds < self.duration_p50_seconds:
            raise ValueError("duration p95 cannot be below p50")
        if self.route_mix and not math.isclose(sum(self.route_mix.values()), 1.0, abs_tol=1e-6):
            raise ValueError("route mix must sum to one")
        return self


class EstimateCalibration(ContractModel):
    estimate_error_ratio: Annotated[float, Field(ge=0.0)]
    duration_error_ratio: Annotated[float, Field(ge=0.0)]
    p95_credit_covered: bool
    p95_duration_covered: bool


class LearnedRouterShadowRecord(ContractModel):
    """A challenger observation that can never influence production routing."""

    schema_version: Literal["1.0"] = "1.0"
    shadow_revision: Annotated[str, Field(min_length=1, max_length=120)]
    champion_revision: Annotated[str, Field(min_length=1, max_length=120)]
    challenger_revision: Annotated[str, Field(min_length=1, max_length=120)]
    evidence_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    authority: Literal["zero"] = "zero"
    production_route_source: Literal["deterministic_fallback"] = "deterministic_fallback"
    champion_route_mix: dict[str, Annotated[float, Field(ge=0.0, le=1.0)]]
    challenger_route_mix: dict[str, Annotated[float, Field(ge=0.0, le=1.0)]] = Field(
        default_factory=dict
    )
    calibration_observations: Annotated[int, Field(ge=0)] = 0
    calibration_status: Literal["awaiting_outcomes", "insufficient", "eligible_for_review"] = (
        "awaiting_outcomes"
    )
    promotion_eligible: Literal[False] = False
    reason_codes: tuple[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,119}$")], ...]

    @model_validator(mode="after")
    def validate_route_mixes(self) -> LearnedRouterShadowRecord:
        for label, route_mix in (
            ("champion", self.champion_route_mix),
            ("challenger", self.challenger_route_mix),
        ):
            if route_mix and not math.isclose(sum(route_mix.values()), 1.0, abs_tol=1e-6):
                raise ValueError(f"{label} route mix must sum to one")
        return self


_CREDIT_QUANTILES: Mapping[Route, tuple[float, float]] = {
    Route.NATIVE: (0.25, 0.35),
    Route.PADDLE_FAST: (0.85, 1.20),
    Route.HPD_FAST: (0.90, 1.25),
    Route.PADDLE_VL: (1.25, 1.80),
    Route.UNLIMITED_LONG: (1.45, 2.10),
    Route.MISTRAL_FALLBACK: (1.75, 2.60),
    # Recovery routes are real billable work.  They must never inherit the
    # terminal-state zero-cost default used by unresolved/quarantine.
    Route.REGION_RECOVERY: (2.20, 3.40),
    Route.AUTHORITY_RECONSTRUCTION: (0.75, 1.50),
}
_SECONDS_QUANTILES: Mapping[Route, tuple[float, float]] = {
    Route.NATIVE: (0.06, 0.18),
    Route.PADDLE_FAST: (0.65, 1.50),
    Route.HPD_FAST: (0.75, 1.70),
    Route.PADDLE_VL: (1.80, 4.20),
    Route.UNLIMITED_LONG: (2.40, 6.50),
    Route.MISTRAL_FALLBACK: (2.10, 5.50),
    Route.REGION_RECOVERY: (4.00, 12.00),
    Route.AUTHORITY_RECONSTRUCTION: (1.00, 5.00),
}

_TERMINAL_UNBILLABLE_ROUTES = {Route.UNRESOLVED, Route.QUARANTINE}


def _normalized_dispersion(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return min(1.0, math.sqrt(variance) / 50.0)


def _metric_extreme(
    rows: list[PreflightObservation],
    field: Literal[
        "native_quality",
        "table_density",
        "image_density",
        "numeric_density",
    ],
    *,
    highest: bool,
) -> PreflightObservation | None:
    measured = [row for row in rows if getattr(row, field) is not None]
    if not measured:
        return None
    return sorted(
        measured,
        key=lambda row: (
            -float(getattr(row, field)) if highest else float(getattr(row, field)),
            row.page_index0,
            row.page_id,
        ),
    )[0]


def _unusual_dimension(rows: list[PreflightObservation]) -> PreflightObservation | None:
    measured = [row for row in rows if row.width is not None and row.height is not None]
    if len(measured) < 2:
        return None
    widths = sorted(float(row.width) for row in measured if row.width is not None)
    heights = sorted(float(row.height) for row in measured if row.height is not None)
    median_width = widths[len(widths) // 2]
    median_height = heights[len(heights) // 2]

    def deviation(row: PreflightObservation) -> float:
        assert row.width is not None and row.height is not None
        width_delta = abs(row.width - median_width) / max(1.0, median_width)
        height_delta = abs(row.height - median_height) / max(1.0, median_height)
        return width_delta + height_delta

    candidate = sorted(
        measured,
        key=lambda row: (-deviation(row), row.page_index0, row.page_id),
    )[0]
    return candidate if deviation(candidate) > 0 else None


def select_adaptive_samples(
    observations: Iterable[PreflightObservation],
) -> tuple[ClusterSamplePlan, ...]:
    """Choose deterministic representatives and outliers for every cluster."""

    grouped: dict[str, list[PreflightObservation]] = defaultdict(list)
    seen_pages: set[str] = set()
    for observation in observations:
        if observation.page_id in seen_pages:
            raise ValueError("page ids must be globally unique")
        seen_pages.add(observation.page_id)
        grouped[observation.cluster_id].append(observation)
    plans: list[ClusterSamplePlan] = []
    for cluster_id, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: (row.page_index0, row.page_id))
        dispersion = _normalized_dispersion([row.difficulty for row in ordered])
        base_expansion_limit = 3 if dispersion < 0.12 else 5 if dispersion < 0.25 else 10
        if dispersion >= 0.50:
            base_expansion_limit = 20
        by_difficulty = sorted(ordered, key=lambda row: (row.difficulty, row.page_id))
        candidates: list[tuple[PreflightObservation | None, str]] = [
            (by_difficulty[len(by_difficulty) // 2], "MEDIAN_DIFFICULTY"),
            (ordered[0], "FIRST_PAGE"),
            (ordered[-1], "LAST_PAGE"),
            (_metric_extreme(ordered, "table_density", highest=True), "HIGHEST_TABLE"),
            (_metric_extreme(ordered, "image_density", highest=True), "HIGHEST_IMAGE"),
            (_metric_extreme(ordered, "numeric_density", highest=True), "HIGHEST_NUMERIC"),
            (_metric_extreme(ordered, "native_quality", highest=False), "LOWEST_NATIVE_QUALITY"),
            (_unusual_dimension(ordered), "UNUSUAL_DIMENSION"),
        ]
        selected: list[str] = []
        selection_reasons: dict[str, list[str]] = {}
        for candidate, reason in candidates:
            if candidate is None:
                continue
            if candidate.page_id not in selected:
                selected.append(candidate.page_id)
            selection_reasons.setdefault(candidate.page_id, []).append(reason)
        required = min(len(ordered), len(selected))
        expansion_limit = next(
            tier
            for tier in (3, 5, 10, 20)
            if tier >= max(base_expansion_limit, required)
        )
        if len(selected) < min(3, len(ordered)):
            for candidate in by_difficulty:
                if candidate.page_id not in selected:
                    selected.append(candidate.page_id)
                    selection_reasons.setdefault(candidate.page_id, []).append(
                        "DISPERSION_FILL"
                    )
                if len(selected) >= min(3, len(ordered)):
                    break
        plans.append(
            ClusterSamplePlan(
                cluster_id=cluster_id,
                population=len(ordered),
                selected_page_ids=tuple(selected),
                selection_reasons={
                    page_id: tuple(selection_reasons[page_id]) for page_id in selected
                },
                dispersion=dispersion,
                expansion_limit=expansion_limit,
            )
        )
    return tuple(plans)


def _route_quantiles(population: RoutePopulation) -> tuple[float, float, float, float]:
    credit_p50, credit_p95 = _CREDIT_QUANTILES.get(population.route, (0.0, 0.0))
    seconds_p50, seconds_p95 = _SECONDS_QUANTILES.get(population.route, (0.0, 0.0))
    if population.sample_runtime_seconds_p50 is not None:
        seconds_p50 = population.sample_runtime_seconds_p50
    if population.sample_runtime_seconds_p95 is not None:
        seconds_p95 = population.sample_runtime_seconds_p95
    recovery = population.recovery_probability
    return (
        credit_p50 * (1.0 + 0.20 * recovery),
        credit_p95 * (1.0 + 0.45 * recovery),
        seconds_p50 * (1.0 + 0.35 * recovery),
        seconds_p95 * (1.0 + 0.80 * recovery),
    )


def estimate_collection(value: CollectionEstimateInput) -> CollectionEstimate:
    """Return a conservative P50/P95 estimate and hard reservation ceiling."""

    total_pages = sum(population.pages for population in value.route_populations)
    terminal_pages = sum(
        population.pages
        for population in value.route_populations
        if population.route in _TERMINAL_UNBILLABLE_ROUTES
    )
    billable_pages = max(0, total_pages - value.duplicate_pages - terminal_pages)
    duplicate_remaining = value.duplicate_pages
    credit_p50 = 0.0
    credit_p95 = 0.0
    work_p50 = 0.0
    work_p95 = 0.0
    sampled_pages = 0
    billed_by_route: Counter[Route] = Counter()
    for population in value.route_populations:
        if population.route in _TERMINAL_UNBILLABLE_ROUTES:
            sampled_pages += population.sampled_pages
            continue
        deduped = min(population.pages, duplicate_remaining)
        duplicate_remaining -= deduped
        pages = population.pages - deduped
        billed_by_route[population.route] += pages
        sampled_pages += population.sampled_pages
        route_credit_p50, route_credit_p95, seconds_p50, seconds_p95 = _route_quantiles(population)
        credit_p50 += pages * route_credit_p50
        credit_p95 += pages * route_credit_p95
        work_p50 += pages * seconds_p50
        work_p95 += pages * seconds_p95
    complexity_multiplier = 1.0 + 0.15 * value.static_complexity
    knowledge_p50 = (
        value.knowledge_note_count * 0.08
        + value.entity_relation_candidates * 0.025
        + value.sample_output_tokens * 0.00002
    )
    knowledge_p95 = (
        value.knowledge_note_count * 0.12
        + value.entity_relation_candidates * 0.04
        + value.sample_output_tokens * 0.00004
    )
    export_p50 = billable_pages * 0.01 * value.export_profile_count
    export_p95 = billable_pages * 0.02 * value.export_profile_count
    credit_p50 = credit_p50 * complexity_multiplier + knowledge_p50 + export_p50
    credit_p95 = credit_p95 * complexity_multiplier + knowledge_p95 + export_p95
    gpu_capacity = {
        GpuClass.CPU_ONLY: 0.25,
        GpuClass.T4: 0.50,
        GpuClass.L4: 0.75,
        GpuClass.A10: 0.80,
        GpuClass.A100: 1.25,
        GpuClass.H100: 1.50,
        GpuClass.UNKNOWN: 1.0,
    }[value.gpu_class]
    work_p50 /= gpu_capacity
    work_p95 /= gpu_capacity
    cold_p50 = 8.0 if value.gpu_state == GpuThermalState.COLD else 0.0
    cold_p95 = 30.0 if value.gpu_state != GpuThermalState.WARM else 2.0
    queue_p50 = value.queue_delay_p50_seconds or 0.0
    queue_p95 = value.queue_delay_p95_seconds or 0.0
    duration_p50 = (
        work_p50 / value.max_parallel_pages
        + queue_p50
        + cold_p50
        + value.knowledge_note_count * 0.03
    )
    duration_p95 = (
        work_p95 / max(1, value.max_parallel_pages // 2)
        + queue_p95
        + cold_p95
        + value.knowledge_note_count * 0.08
    )
    sampled_ratio = sampled_pages / max(1, billable_pages)
    route_coverage = sum(
        1 for population in value.route_populations if population.sampled_pages > 0
    ) / len(value.route_populations)
    recovery_uncertainty = sum(
        population.recovery_probability * population.pages for population in value.route_populations
    ) / max(1, total_pages)
    evidence_coverage = min(1.0, len(value.measured_signal_fields) / 12.0)
    confidence = min(
        0.97,
        max(0.20, 0.34 + 0.36 * route_coverage + 0.35 * min(1.0, sampled_ratio * 20))
        - 0.20 * recovery_uncertainty,
    )
    if value.queue_delay_p50_seconds is None:
        confidence -= 0.05
    if value.gpu_class == GpuClass.UNKNOWN or value.gpu_state == GpuThermalState.UNKNOWN:
        confidence -= 0.05
    confidence = max(0.20, confidence - 0.08 * (1.0 - evidence_coverage))
    confidence_band = (
        EstimateConfidence.HIGH
        if confidence >= 0.80
        else EstimateConfidence.MEDIUM
        if confidence >= 0.55
        else EstimateConfidence.LOW
    )
    route_mix = (
        {
            route.value: count / billable_pages
            for route, count in sorted(billed_by_route.items(), key=lambda item: item[0].value)
            if count
        }
        if billable_pages
        else {}
    )
    reserve_ceiling = credit_p95 * 1.025
    return CollectionEstimate(
        credit_p50=round(credit_p50, 3),
        credit_p95=round(credit_p95, 3),
        reserve_ceiling=round(reserve_ceiling, 3),
        duration_p50_seconds=round(duration_p50, 3),
        duration_p95_seconds=round(max(duration_p50, duration_p95), 3),
        route_mix=route_mix,
        confidence=round(confidence, 4),
        confidence_band=confidence_band,
        sampled_pages=sampled_pages,
        billable_pages=billable_pages,
        duplicate_pages=value.duplicate_pages,
        unbillable_pages=terminal_pages,
        predictor_revision=value.predictor_revision,
        evidence_revision=value.evidence_revision,
        evidence_sha256=value.evidence_sha256,
        measured_signal_fields=value.measured_signal_fields,
        calibration_required=confidence_band != EstimateConfidence.HIGH,
    )


def build_zero_authority_learned_router_shadow(
    *,
    champion_revision: str,
    challenger_revision: str,
    evidence_sha256: str,
    champion_route_mix: Mapping[str, float],
    challenger_route_mix: Mapping[str, float] | None = None,
    calibration_observations: int = 0,
) -> LearnedRouterShadowRecord:
    """Record challenger output without granting it routing or billing authority."""

    if calibration_observations < 0:
        raise ValueError("calibration observations cannot be negative")
    challenger = dict(challenger_route_mix or {})
    status: Literal["awaiting_outcomes", "insufficient", "eligible_for_review"]
    if calibration_observations == 0:
        status = "awaiting_outcomes"
    elif calibration_observations < 100:
        status = "insufficient"
    else:
        status = "eligible_for_review"
    reasons = ["ZERO_AUTHORITY", "DETERMINISTIC_FALLBACK_ONLY"]
    if not challenger:
        reasons.append("NO_LEARNED_SNAPSHOT")
    if calibration_observations < 100:
        reasons.append("INSUFFICIENT_CALIBRATION_OBSERVATIONS")
    shadow_revision = hashlib.sha256(
        json.dumps(
            {
                "champion_revision": champion_revision,
                "challenger_revision": challenger_revision,
                "evidence_sha256": evidence_sha256,
                "champion_route_mix": dict(champion_route_mix),
                "challenger_route_mix": challenger,
                "calibration_observations": calibration_observations,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return LearnedRouterShadowRecord(
        shadow_revision=f"shadow-{shadow_revision[:24]}",
        champion_revision=champion_revision,
        challenger_revision=challenger_revision,
        evidence_sha256=evidence_sha256,
        champion_route_mix=dict(champion_route_mix),
        challenger_route_mix=challenger,
        calibration_observations=calibration_observations,
        calibration_status=status,
        reason_codes=tuple(reasons),
    )


def calibrate_estimate(
    estimate: CollectionEstimate,
    *,
    actual_credits: float,
    actual_duration_seconds: float,
) -> EstimateCalibration:
    if actual_credits < 0 or actual_duration_seconds < 0:
        raise ValueError("actual values cannot be negative")
    credit_denominator = max(1.0, actual_credits)
    duration_denominator = max(1.0, actual_duration_seconds)
    return EstimateCalibration(
        estimate_error_ratio=abs(estimate.credit_p50 - actual_credits) / credit_denominator,
        duration_error_ratio=(
            abs(estimate.duration_p50_seconds - actual_duration_seconds) / duration_denominator
        ),
        p95_credit_covered=actual_credits <= estimate.credit_p95,
        p95_duration_covered=actual_duration_seconds <= estimate.duration_p95_seconds,
    )


__all__ = [
    "ClusterSamplePlan",
    "CollectionEstimate",
    "CollectionEstimateInput",
    "DimensionUnit",
    "EstimateCalibration",
    "EstimateConfidence",
    "GpuClass",
    "GpuThermalState",
    "LearnedRouterShadowRecord",
    "PreflightObservation",
    "RoutePopulation",
    "StaticDocumentFeatures",
    "build_cluster_identity",
    "build_zero_authority_learned_router_shadow",
    "calibrate_estimate",
    "estimate_collection",
    "select_adaptive_samples",
]
