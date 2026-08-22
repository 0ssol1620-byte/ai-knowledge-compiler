"""Repeat-isolated deterministic benchmark execution contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .identity import canonical_sha256, require_sha256


@dataclass(frozen=True, slots=True)
class BenchmarkEnvironmentIdentity:
    runtime_image_digest: str
    model_revision: str
    gpu_class: str
    cuda_version: str
    prompt_sha256: str
    decoding_sha256: str
    dataset_sha256: str
    evaluator_revision: str
    evaluator_thread_safe: bool = True

    def __post_init__(self) -> None:
        for field_name in ("prompt_sha256", "decoding_sha256", "dataset_sha256"):
            require_sha256(getattr(self, field_name), field_name=field_name)
        if not all(
            (
                self.runtime_image_digest,
                self.model_revision,
                self.gpu_class,
                self.cuda_version,
                self.evaluator_revision,
            )
        ):
            raise ValueError("benchmark environment identity fields are required")

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class BenchmarkUnitResult:
    repeat_index: int
    unit_id: str
    environment_sha256: str
    prediction_sha256: str
    score: Decimal

    def __post_init__(self) -> None:
        if self.repeat_index not in {1, 2, 3}:
            raise ValueError("benchmark repeat index must be 1, 2, or 3")
        if (
            not self.unit_id
            or self.unit_id in {".", ".."}
            or any(separator in self.unit_id for separator in ("/", "\\"))
        ):
            raise ValueError("benchmark unit id must be a safe artifact path component")
        require_sha256(self.environment_sha256, field_name="environment_sha256")
        require_sha256(self.prediction_sha256, field_name="prediction_sha256")
        if not self.score.is_finite() or not 0 <= self.score <= 1:
            raise ValueError("benchmark score must be between zero and one")

    @property
    def artifact_namespace(self) -> str:
        return f"run-{self.repeat_index}/{self.unit_id}"


@dataclass(frozen=True, slots=True)
class BenchmarkAggregate:
    repeat_index: int
    environment_sha256: str
    unit_count: int
    mean_score: Decimal
    aggregate_sha256: str


def aggregate_repeat(
    results: tuple[BenchmarkUnitResult, ...],
    *,
    expected_environment: BenchmarkEnvironmentIdentity,
) -> BenchmarkAggregate:
    if not results:
        raise ValueError("cannot aggregate an empty benchmark repeat")
    if not expected_environment.evaluator_thread_safe:
        raise ValueError("parallel evaluator was not proven thread and process safe")
    repeat_indexes = {result.repeat_index for result in results}
    if len(repeat_indexes) != 1:
        raise ValueError("benchmark repeat artifacts cannot be mixed")
    if len({result.unit_id for result in results}) != len(results):
        raise ValueError("benchmark unit results must be unique within a repeat")
    if any(result.environment_sha256 != expected_environment.digest for result in results):
        raise ValueError("benchmark environment drift detected")
    ordered = tuple(sorted(results, key=lambda result: result.unit_id))
    mean = sum((result.score for result in ordered), Decimal("0")) / Decimal(len(ordered))
    mean = mean.quantize(Decimal("0.000000000001"))
    digest = canonical_sha256(
        {
            "repeat_index": ordered[0].repeat_index,
            "environment_sha256": expected_environment.digest,
            "results": ordered,
            "mean_score": mean,
        }
    )
    return BenchmarkAggregate(
        repeat_index=ordered[0].repeat_index,
        environment_sha256=expected_environment.digest,
        unit_count=len(ordered),
        mean_score=mean,
        aggregate_sha256=digest,
    )


def verify_repeat_environment_identity(
    environments: tuple[BenchmarkEnvironmentIdentity, ...],
) -> str:
    if len(environments) != 3:
        raise ValueError("production benchmark proof requires exactly three repeats")
    digests = {environment.digest for environment in environments}
    if len(digests) != 1:
        raise ValueError("benchmark repeats do not share an identical environment")
    return next(iter(digests))


__all__ = [
    "BenchmarkAggregate",
    "BenchmarkEnvironmentIdentity",
    "BenchmarkUnitResult",
    "aggregate_repeat",
    "verify_repeat_environment_identity",
]
