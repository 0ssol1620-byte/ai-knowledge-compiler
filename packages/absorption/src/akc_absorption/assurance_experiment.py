"""Secret-free assurance experiment receipts and staged cost guardrails."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

__all__ = [
    "AssuranceMetrics",
    "ExperimentGuardrail",
    "ExperimentObservation",
    "ExperimentReceipt",
    "ExperimentStage",
    "ExperimentVariant",
    "GuardrailDecision",
    "summarize_experiment",
]


class ExperimentVariant(StrEnum):
    BASELINE = "baseline"
    CALIBRATED = "calibrated"
    ADAPTIVE_RECOVERY = "adaptive_recovery"
    MULTI_PARSER = "multi_parser"
    # An experiment variant whose name contains "TOKEN", not a credential:
    # this variant verifies critical tokens in the parsed text.
    CRITICAL_TOKEN_VERIFIER = "critical_token_verifier"  # noqa: S105


class ExperimentStage(StrEnum):
    CPU = "cpu"
    STAGE1_GPU = "stage1_gpu"
    STAGE2_GPU = "stage2_gpu"
    LARGE = "large"


@dataclass(frozen=True, slots=True)
class ExperimentObservation:
    sample_id: str
    expected_corrupted: bool
    detected_corruption: bool
    unresolved: bool = False
    recovered: bool = False
    latency_ms: float = 0.0
    gpu_seconds: float = 0.0
    api_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id is required")
        if self.latency_ms < 0 or self.gpu_seconds < 0 or self.api_cost_usd < 0:
            raise ValueError("experiment costs and latency cannot be negative")
        if self.recovered and not self.detected_corruption:
            raise ValueError("an observation cannot be recovered before it is detected")


@dataclass(frozen=True, slots=True)
class AssuranceMetrics:
    samples: int
    accuracy: float
    silent_corruption_precision: float
    silent_corruption_recall: float
    unresolved_rate: float
    recovery_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    gpu_seconds: float
    api_cost_usd: float


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def summarize_experiment(observations: Sequence[ExperimentObservation]) -> AssuranceMetrics:
    if not observations:
        raise ValueError("at least one experiment observation is required")
    tp = sum(item.expected_corrupted and item.detected_corruption for item in observations)
    tn = sum(not item.expected_corrupted and not item.detected_corruption for item in observations)
    fp = sum(not item.expected_corrupted and item.detected_corruption for item in observations)
    fn = sum(item.expected_corrupted and not item.detected_corruption for item in observations)
    unresolved = sum(item.unresolved for item in observations)
    recoverable = sum(item.expected_corrupted and item.detected_corruption for item in observations)
    recovered = sum(item.expected_corrupted and item.recovered for item in observations)
    latencies = [item.latency_ms for item in observations]
    return AssuranceMetrics(
        samples=len(observations),
        accuracy=_ratio(tp + tn, len(observations)),
        silent_corruption_precision=_ratio(tp, tp + fp),
        silent_corruption_recall=_ratio(tp, tp + fn),
        unresolved_rate=_ratio(unresolved, len(observations)),
        recovery_rate=_ratio(recovered, recoverable),
        latency_p50_ms=median(latencies),
        latency_p95_ms=_percentile(latencies, 0.95),
        gpu_seconds=sum(item.gpu_seconds for item in observations),
        api_cost_usd=sum(item.api_cost_usd for item in observations),
    )


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ExperimentGuardrail:
    """Hard staged-spend boundary, evaluated before external work starts."""

    stage1_max_samples: int = 300
    stage2_max_samples: int = 2000
    stage1_max_gpu_seconds: float = 18_000.0
    stage2_max_gpu_seconds: float = 72_000.0
    stage1_max_external_cost_usd: float = 30.0
    stage2_max_external_cost_usd: float = 120.0

    def authorize(
        self,
        stage: ExperimentStage,
        *,
        samples: int,
        estimated_gpu_seconds: float,
        estimated_external_cost_usd: float,
        cpu_gate_green: bool,
        prior_stage_green: bool = False,
    ) -> GuardrailDecision:
        if samples < 0 or estimated_gpu_seconds < 0 or estimated_external_cost_usd < 0:
            return GuardrailDecision(False, "negative workload/cost estimate is invalid")
        if stage is ExperimentStage.CPU:
            return GuardrailDecision(True, "CPU/synthetic validation is not externally billed")
        if not cpu_gate_green:
            return GuardrailDecision(
                False, "CPU/synthetic gate must be GREEN before external GPU/API work"
            )
        if stage is ExperimentStage.STAGE1_GPU:
            if samples > self.stage1_max_samples:
                return GuardrailDecision(False, "Stage 1 sample cap exceeded")
            if estimated_gpu_seconds > self.stage1_max_gpu_seconds:
                return GuardrailDecision(False, "Stage 1 GPU budget exceeded")
            if estimated_external_cost_usd > self.stage1_max_external_cost_usd:
                return GuardrailDecision(False, "Stage 1 external cost cap exceeded")
            return GuardrailDecision(True, "Stage 1 pilot is within hard guardrails")
        if not prior_stage_green:
            return GuardrailDecision(False, "the preceding external stage must be GREEN")
        if stage is ExperimentStage.STAGE2_GPU:
            if samples > self.stage2_max_samples:
                return GuardrailDecision(False, "Stage 2 sample cap exceeded")
            if estimated_gpu_seconds > self.stage2_max_gpu_seconds:
                return GuardrailDecision(False, "Stage 2 GPU budget exceeded")
            if estimated_external_cost_usd > self.stage2_max_external_cost_usd:
                return GuardrailDecision(False, "Stage 2 external cost cap exceeded")
            return GuardrailDecision(True, "Stage 2 ablation is within hard guardrails")
        return GuardrailDecision(
            False,
            "large benchmark requires an explicit higher-level budget/approval "
            "beyond automatic stages",
        )


_SECRET_FIELD_MARKERS = ("secret", "token", "password", "api_key", "apikey", "credential")


def _reject_secret_fields(metadata: dict[str, object]) -> None:
    for key in metadata:
        folded = key.casefold()
        if any(marker in folded for marker in _SECRET_FIELD_MARKERS):
            raise ValueError(
                f"secret-like field is forbidden in experiment receipt metadata: {key}"
            )


@dataclass(frozen=True, slots=True)
class ExperimentReceipt:
    variant: ExperimentVariant
    stage: ExperimentStage
    corpus_id: str
    metrics: AssuranceMetrics
    metadata: tuple[tuple[str, object], ...]
    receipt_id: str

    @classmethod
    def build(
        cls,
        *,
        variant: ExperimentVariant,
        stage: ExperimentStage,
        corpus_id: str,
        observations: Sequence[ExperimentObservation],
        metadata: dict[str, object] | None = None,
    ) -> ExperimentReceipt:
        if not corpus_id:
            raise ValueError("corpus_id is required")
        safe_metadata = dict(metadata or {})
        _reject_secret_fields(safe_metadata)
        metrics = summarize_experiment(observations)
        body = {
            "variant": variant.value,
            "stage": stage.value,
            "corpus_id": corpus_id,
            "metrics": metrics.__dict__ if hasattr(metrics, "__dict__") else {
                field: getattr(metrics, field)
                for field in AssuranceMetrics.__dataclass_fields__
            },
            "metadata": safe_metadata,
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            variant=variant,
            stage=stage,
            corpus_id=corpus_id,
            metrics=metrics,
            metadata=tuple(sorted(safe_metadata.items())),
            receipt_id=f"assurance_{digest[:32]}",
        )

    def as_record(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "variant": self.variant.value,
            "stage": self.stage.value,
            "corpus_id": self.corpus_id,
            "metrics": {
                field: getattr(self.metrics, field)
                for field in AssuranceMetrics.__dataclass_fields__
            },
            "metadata": dict(self.metadata),
        }