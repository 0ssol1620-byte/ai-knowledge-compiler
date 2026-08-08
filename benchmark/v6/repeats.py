"""Adaptive same-environment repeat planning and isolation validation."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .contracts import ContractError, EnvironmentIdentity, canonical_sha256, require_sha256

EXACT_REPEAT_COUNT = 3
INITIAL_FULL_RUN_COUNT = 1
STRATIFIED_AUDIT_COUNT = 3
ADAPTIVE_EXPANSION_REASONS = frozenset(
    {"finalist", "prediction_drift", "score_drift", "runtime_failure"}
)


class RepeatScope(StrEnum):
    FULL = "full"
    STRATIFIED_AUDIT = "stratified_audit"


@dataclass(frozen=True, slots=True)
class RepeatObservation:
    """Content-bound evidence from one full or stratified benchmark pass."""

    run_id: str
    candidate_id: str
    benchmark_id: str
    environment_sha256: str
    scope: RepeatScope
    prediction_hashes: tuple[tuple[str, str], ...]
    score: float
    failure_count: int = 0

    def __post_init__(self) -> None:
        if not self.run_id or not self.candidate_id or not self.benchmark_id:
            raise ValueError("repeat observation identity is required")
        require_sha256(self.environment_sha256, "environment_sha256")
        if self.failure_count < 0:
            raise ValueError("failure_count cannot be negative")
        if not math.isfinite(self.score):
            raise ValueError("repeat score must be finite")
        item_ids = [item_id for item_id, _ in self.prediction_hashes]
        if not item_ids or len(item_ids) != len(set(item_ids)):
            raise ValueError("prediction hashes require unique item ids")
        for _, digest in self.prediction_hashes:
            require_sha256(digest, "prediction_sha256")


@dataclass(frozen=True, slots=True)
class AdaptiveRepeatDecision:
    required_full_runs: int
    required_audit_runs: int
    additional_full_runs: int
    additional_audit_runs: int
    deterministic: bool | None
    gate_complete: bool
    reason_codes: tuple[str, ...]


def evaluate_adaptive_repeats(
    observations: Sequence[RepeatObservation],
    *,
    finalist: bool,
    score_tolerance: float = 0.0,
) -> AdaptiveRepeatDecision:
    """Avoid unconditional full repeats while preserving a fail-closed release gate.

    Every candidate needs one full pass and three content-bound stratified audit
    passes. Finalists, failed runs, and candidates with any output or metric drift
    require three full passes.
    """

    if score_tolerance < 0 or not math.isfinite(score_tolerance):
        raise ValueError("score_tolerance must be non-negative and finite")
    if not observations:
        return AdaptiveRepeatDecision(1, 3, 1, 3, None, False, ("initial_full_run_required",))

    identities = {
        (item.candidate_id, item.benchmark_id, item.environment_sha256)
        for item in observations
    }
    if len(identities) != 1:
        raise ContractError("adaptive repeats must share candidate, benchmark, and environment")
    if len({item.run_id for item in observations}) != len(observations):
        raise ContractError("adaptive repeat run ids must be unique")

    full_attempts = tuple(item for item in observations if item.scope is RepeatScope.FULL)
    audit_attempts = tuple(
        item for item in observations if item.scope is RepeatScope.STRATIFIED_AUDIT
    )
    full = tuple(item for item in full_attempts if item.failure_count == 0)
    audit = tuple(item for item in audit_attempts if item.failure_count == 0)
    if len(full) > EXACT_REPEAT_COUNT or len(audit) > EXACT_REPEAT_COUNT:
        raise ContractError(
            "adaptive repeat evidence may contain at most three successful runs per scope"
        )
    reasons: set[str] = set()
    deterministic: bool | None = None
    if len(audit) >= EXACT_REPEAT_COUNT:
        deterministic = _runs_are_stable(audit, score_tolerance, "stratified audit")
        if not deterministic:
            reasons.add("determinism_audit_drift")
    else:
        reasons.add("stratified_determinism_audit_incomplete")

    if finalist:
        reasons.add("finalist_requires_three_full_runs")
    if any(item.failure_count for item in observations):
        reasons.add("runtime_failure_observed")

    required_full = (
        EXACT_REPEAT_COUNT
        if finalist or deterministic is False or any(item.failure_count for item in observations)
        else 1
    )
    if len(full) == EXACT_REPEAT_COUNT:
        full_stable = _runs_are_stable(full, score_tolerance, "full repeat")
        deterministic = full_stable
        if not full_stable:
            reasons.add("full_repeat_drift_observed")
    additional_full = max(required_full - len(full), 0)
    additional_audit = max(EXACT_REPEAT_COUNT - len(audit), 0)
    if not full:
        reasons.add("initial_full_run_required")
    if additional_full:
        reasons.add("additional_full_runs_required")
    gate_complete = (
        bool(full)
        and additional_full == 0
        and additional_audit == 0
        and deterministic is True
    )
    if gate_complete:
        reasons.add("adaptive_repeat_gate_satisfied")
    return AdaptiveRepeatDecision(
        required_full_runs=required_full,
        required_audit_runs=EXACT_REPEAT_COUNT,
        additional_full_runs=additional_full,
        additional_audit_runs=additional_audit,
        deterministic=deterministic,
        gate_complete=gate_complete,
        reason_codes=tuple(sorted(reasons)),
    )


def _runs_are_stable(
    runs: Sequence[RepeatObservation], score_tolerance: float, label: str
) -> bool:
    item_sets = {
        tuple(item_id for item_id, _ in item.prediction_hashes) for item in runs
    }
    if len(item_sets) != 1:
        raise ContractError(f"{label} runs must cover the same ordered items")
    hash_sets = {item.prediction_hashes for item in runs}
    score_span = max(item.score for item in runs) - min(item.score for item in runs)
    return len(hash_sets) == 1 and score_span <= score_tolerance


@dataclass(frozen=True, slots=True)
class RepeatRun:
    cohort_id: str
    run_id: str
    repeat_index: int
    candidate_id: str
    benchmark_id: str
    environment_sha256: str
    repeat_root: Path
    prediction_root: Path
    log_root: Path
    official_result_root: Path
    critical_result_root: Path
    scope: RepeatScope = RepeatScope.FULL

    def to_dict(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "run_id": self.run_id,
            "repeat_index": self.repeat_index,
            "scope": self.scope.value,
            "candidate_id": self.candidate_id,
            "benchmark_id": self.benchmark_id,
            "environment_sha256": self.environment_sha256,
            "repeat_root": self.repeat_root.as_posix(),
            "prediction_root": self.prediction_root.as_posix(),
            "log_root": self.log_root.as_posix(),
            "official_result_root": self.official_result_root.as_posix(),
            "critical_result_root": self.critical_result_root.as_posix(),
        }


def build_exact_repeat_plan(
    *,
    base_root: Path,
    benchmark_id: str,
    environment: EnvironmentIdentity,
    expansion_reason: str,
) -> tuple[RepeatRun, ...]:
    """Build the three-full-run expansion used only after adaptive escalation."""
    if not benchmark_id.strip():
        raise ContractError("benchmark_id is required")
    if expansion_reason not in ADAPTIVE_EXPANSION_REASONS:
        raise ContractError("exact-three full runs require an adaptive expansion reason")
    root = base_root.resolve(strict=False)
    cohort_seed = {
        "benchmark_id": benchmark_id,
        "candidate_id": environment.candidate_id,
        "environment_sha256": environment.environment_sha256,
        "adaptive_expansion_reason": expansion_reason,
    }
    cohort_id = "cohort-" + canonical_sha256(cohort_seed).split(":", 1)[1][:24]
    runs: list[RepeatRun] = []
    for repeat_index in range(1, EXACT_REPEAT_COUNT + 1):
        repeat_root = root / cohort_id / f"run-{repeat_index}"
        digest = hashlib.sha256(f"{cohort_id}\0{repeat_index}".encode()).hexdigest()[:24]
        runs.append(
            RepeatRun(
                cohort_id=cohort_id,
                run_id=f"run-{digest}",
                repeat_index=repeat_index,
                candidate_id=environment.candidate_id,
                benchmark_id=benchmark_id,
                environment_sha256=environment.environment_sha256,
                repeat_root=repeat_root,
                prediction_root=repeat_root / "predictions",
                log_root=repeat_root / "logs",
                official_result_root=repeat_root / "official-results",
                critical_result_root=repeat_root / "critical-results",
            )
        )
    validate_repeat_plan(runs)
    return tuple(runs)


def build_adaptive_repeat_plan(
    *,
    base_root: Path,
    benchmark_id: str,
    environment: EnvironmentIdentity,
    required_full_runs: int = INITIAL_FULL_RUN_COUNT,
) -> tuple[RepeatRun, ...]:
    """Build initial 1-full/3-audit work or its bounded 3-full expansion."""

    if not benchmark_id.strip():
        raise ContractError("benchmark_id is required")
    if required_full_runs not in {INITIAL_FULL_RUN_COUNT, EXACT_REPEAT_COUNT}:
        raise ContractError("adaptive plan full-run count must be one or three")
    root = base_root.resolve(strict=False)
    cohort_seed = {
        "policy": "adaptive-1-full-3-audit-max-3-full",
        "benchmark_id": benchmark_id,
        "candidate_id": environment.candidate_id,
        "environment_sha256": environment.environment_sha256,
    }
    cohort_id = "adaptive-" + canonical_sha256(cohort_seed).split(":", 1)[1][:24]
    runs = [
        _build_repeat_run(
            root=root,
            cohort_id=cohort_id,
            benchmark_id=benchmark_id,
            environment=environment,
            scope=RepeatScope.FULL,
            repeat_index=index,
        )
        for index in range(1, required_full_runs + 1)
    ]
    runs.extend(
        _build_repeat_run(
            root=root,
            cohort_id=cohort_id,
            benchmark_id=benchmark_id,
            environment=environment,
            scope=RepeatScope.STRATIFIED_AUDIT,
            repeat_index=index,
        )
        for index in range(1, STRATIFIED_AUDIT_COUNT + 1)
    )
    validate_adaptive_repeat_plan(runs, required_full_runs=required_full_runs)
    return tuple(runs)


def _build_repeat_run(
    *,
    root: Path,
    cohort_id: str,
    benchmark_id: str,
    environment: EnvironmentIdentity,
    scope: RepeatScope,
    repeat_index: int,
) -> RepeatRun:
    label = "full" if scope is RepeatScope.FULL else "audit"
    repeat_root = root / cohort_id / f"{label}-run-{repeat_index}"
    digest = hashlib.sha256(
        f"{cohort_id}\0{scope.value}\0{repeat_index}".encode()
    ).hexdigest()[:24]
    return RepeatRun(
        cohort_id=cohort_id,
        run_id=f"run-{digest}",
        repeat_index=repeat_index,
        candidate_id=environment.candidate_id,
        benchmark_id=benchmark_id,
        environment_sha256=environment.environment_sha256,
        repeat_root=repeat_root,
        prediction_root=repeat_root / "predictions",
        log_root=repeat_root / "logs",
        official_result_root=repeat_root / "official-results",
        critical_result_root=repeat_root / "critical-results",
        scope=scope,
    )


def materialize_repeat_plan(runs: Sequence[RepeatRun]) -> None:
    """Create isolated roots and an immutable contract sentinel for each run."""

    validate_repeat_plan(runs)
    _materialize_runs(runs)


def materialize_adaptive_repeat_plan(
    runs: Sequence[RepeatRun], *, required_full_runs: int
) -> None:
    validate_adaptive_repeat_plan(runs, required_full_runs=required_full_runs)
    _materialize_runs(runs)


def _materialize_runs(runs: Sequence[RepeatRun]) -> None:
    for run in runs:
        for path in (
            run.prediction_root,
            run.log_root,
            run.official_result_root,
            run.critical_result_root,
        ):
            path.mkdir(parents=True, exist_ok=False)
        sentinel = run.repeat_root / "repeat-contract.json"
        sentinel.write_text(
            _pretty_json({**run.to_dict(), "contract_sha256": canonical_sha256(run.to_dict())}),
            encoding="utf-8",
        )


def validate_repeat_plan(runs: Sequence[RepeatRun]) -> dict[str, object]:
    if len(runs) != EXACT_REPEAT_COUNT:
        raise ContractError("public-core cohorts require exactly three repeats")
    if {run.repeat_index for run in runs} != {1, 2, 3}:
        raise ContractError("repeat indexes must be exactly {1, 2, 3}")
    if any(run.scope is not RepeatScope.FULL for run in runs):
        raise ContractError("exact-three expansion may contain only full runs")
    for field in ("cohort_id", "candidate_id", "benchmark_id", "environment_sha256"):
        values = {getattr(run, field) for run in runs}
        if len(values) != 1:
            raise ContractError(f"all repeats must share {field}")
    require_sha256(runs[0].environment_sha256, "environment_sha256")
    if len({run.run_id for run in runs}) != EXACT_REPEAT_COUNT:
        raise ContractError("repeat run IDs must be unique")
    if len({run.repeat_root.resolve(strict=False) for run in runs}) != EXACT_REPEAT_COUNT:
        raise ContractError("repeat roots must be unique")

    all_artifact_roots: list[Path] = []
    for run in runs:
        repeat_root = run.repeat_root.resolve(strict=False)
        roots = (
            run.prediction_root,
            run.log_root,
            run.official_result_root,
            run.critical_result_root,
        )
        resolved = tuple(path.resolve(strict=False) for path in roots)
        if len(set(resolved)) != len(resolved):
            raise ContractError(f"artifact roots overlap within {run.run_id}")
        if any(repeat_root not in path.parents for path in resolved):
            raise ContractError(f"artifact root escapes repeat root for {run.run_id}")
        all_artifact_roots.extend(resolved)
    if len(set(all_artifact_roots)) != len(all_artifact_roots):
        raise ContractError("prediction/log/result roots may not be shared across repeats")

    return {
        "gate": "G2_REPEAT_ISOLATION",
        "passed": True,
        "repeat_count": EXACT_REPEAT_COUNT,
        "environment_sha256": runs[0].environment_sha256,
        "isolated_predictions": True,
        "isolated_logs": True,
        "plan_sha256": canonical_sha256([run.to_dict() for run in runs]),
    }


def validate_adaptive_repeat_plan(
    runs: Sequence[RepeatRun], *, required_full_runs: int
) -> dict[str, object]:
    if required_full_runs not in {INITIAL_FULL_RUN_COUNT, EXACT_REPEAT_COUNT}:
        raise ContractError("adaptive plan full-run count must be one or three")
    full = tuple(run for run in runs if run.scope is RepeatScope.FULL)
    audit = tuple(run for run in runs if run.scope is RepeatScope.STRATIFIED_AUDIT)
    if len(full) != required_full_runs or len(audit) != STRATIFIED_AUDIT_COUNT:
        raise ContractError("adaptive plan requires one-or-three full runs and three audits")
    if {run.repeat_index for run in full} != set(range(1, required_full_runs + 1)):
        raise ContractError("adaptive full-run indexes are invalid")
    if {run.repeat_index for run in audit} != {1, 2, 3}:
        raise ContractError("adaptive audit indexes must be exactly {1, 2, 3}")
    for field in ("cohort_id", "candidate_id", "benchmark_id", "environment_sha256"):
        if len({getattr(run, field) for run in runs}) != 1:
            raise ContractError(f"all adaptive runs must share {field}")
    require_sha256(runs[0].environment_sha256, "environment_sha256")
    if len({run.run_id for run in runs}) != len(runs):
        raise ContractError("adaptive run IDs must be unique")
    repeat_roots = {run.repeat_root.resolve(strict=False) for run in runs}
    if len(repeat_roots) != len(runs):
        raise ContractError("adaptive repeat roots must be unique")
    all_artifact_roots: list[Path] = []
    for run in runs:
        repeat_root = run.repeat_root.resolve(strict=False)
        resolved = tuple(
            path.resolve(strict=False)
            for path in (
                run.prediction_root,
                run.log_root,
                run.official_result_root,
                run.critical_result_root,
            )
        )
        if len(set(resolved)) != len(resolved):
            raise ContractError(f"artifact roots overlap within {run.run_id}")
        if any(repeat_root not in path.parents for path in resolved):
            raise ContractError(f"artifact root escapes adaptive repeat root for {run.run_id}")
        all_artifact_roots.extend(resolved)
    if len(set(all_artifact_roots)) != len(all_artifact_roots):
        raise ContractError("adaptive artifact roots may not be shared")
    return {
        "gate": "G2_ADAPTIVE_REPEAT_ISOLATION",
        "passed": True,
        "full_run_count": len(full),
        "audit_run_count": len(audit),
        "environment_sha256": runs[0].environment_sha256,
        "plan_sha256": canonical_sha256([run.to_dict() for run in runs]),
    }


def _pretty_json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
