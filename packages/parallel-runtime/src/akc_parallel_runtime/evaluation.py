"""Evidence-only Document Performance Map and router evaluation utilities."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .identity import canonical_sha256


class OutcomeStatus(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    SEMANTIC_FAILURE = "semantic_failure"
    PROVIDER_FAILURE = "provider_failure"
    OPERATIONAL_FAILURE = "operational_failure"


def _finite_nonnegative(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class MeasuredRouteOutcome:
    case_id: str
    family_id: str
    path_id: str
    permitted: bool
    status: OutcomeStatus
    quality: Decimal
    actual_cost: Decimal
    latency_seconds: Decimal
    catastrophic: bool = False
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id or not self.family_id or not self.path_id:
            raise ValueError("case, family, and path ids are required")
        if (
            not isinstance(self.quality, Decimal)
            or not self.quality.is_finite()
            or not 0 <= self.quality <= 1
        ):
            raise ValueError("quality must be finite and between zero and one")
        _finite_nonnegative(self.actual_cost, "actual_cost")
        _finite_nonnegative(self.latency_seconds, "latency_seconds")
        if self.status is OutcomeStatus.TRUSTED:
            if self.failure_code is not None or self.catastrophic:
                raise ValueError("trusted outcomes cannot carry failure accounting")
        elif not self.failure_code:
            raise ValueError("every non-trusted outcome requires an explicit failure code")

    @property
    def trusted(self) -> bool:
        return self.status is OutcomeStatus.TRUSTED


@dataclass(frozen=True, slots=True)
class UtilityPolicy:
    quality_reward: Decimal
    cost_penalty: Decimal
    latency_penalty: Decimal
    untrusted_penalty: Decimal
    catastrophic_penalty: Decimal

    def __post_init__(self) -> None:
        for field_name in (
            "quality_reward",
            "cost_penalty",
            "latency_penalty",
            "untrusted_penalty",
            "catastrophic_penalty",
        ):
            _finite_nonnegative(getattr(self, field_name), field_name)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


def measured_utility(row: MeasuredRouteOutcome, policy: UtilityPolicy) -> Decimal:
    return (
        policy.quality_reward * row.quality
        - policy.cost_penalty * row.actual_cost
        - policy.latency_penalty * row.latency_seconds
        - policy.untrusted_penalty * Decimal(not row.trusted)
        - policy.catastrophic_penalty * Decimal(row.catastrophic)
    )


@dataclass(frozen=True, slots=True)
class DpmPathSummary:
    path_id: str
    sample_count: int
    trusted_count: int
    semantic_failure_count: int
    provider_failure_count: int
    operational_failure_count: int
    untrusted_count: int
    catastrophic_count: int
    mean_quality: Decimal
    mean_actual_cost: Decimal
    mean_latency_seconds: Decimal


def _require_unique_measured_rows(rows: tuple[MeasuredRouteOutcome, ...]) -> None:
    if not rows:
        raise ValueError("measured outcome rows are required")
    identities = {(row.case_id, row.path_id) for row in rows}
    if len(identities) != len(rows):
        raise ValueError("each measured case/path row must be unique")


def document_performance_map(
    rows: tuple[MeasuredRouteOutcome, ...],
) -> tuple[DpmPathSummary, ...]:
    _require_unique_measured_rows(rows)
    summaries: list[DpmPathSummary] = []
    for path_id in sorted({row.path_id for row in rows}):
        group = tuple(row for row in rows if row.path_id == path_id)
        count = Decimal(len(group))
        statuses = {status: sum(row.status is status for row in group) for status in OutcomeStatus}
        summaries.append(
            DpmPathSummary(
                path_id=path_id,
                sample_count=len(group),
                trusted_count=statuses[OutcomeStatus.TRUSTED],
                semantic_failure_count=statuses[OutcomeStatus.SEMANTIC_FAILURE],
                provider_failure_count=statuses[OutcomeStatus.PROVIDER_FAILURE],
                operational_failure_count=statuses[OutcomeStatus.OPERATIONAL_FAILURE],
                untrusted_count=statuses[OutcomeStatus.UNTRUSTED],
                catastrophic_count=sum(row.catastrophic for row in group),
                mean_quality=sum((row.quality for row in group), Decimal()) / count,
                mean_actual_cost=sum((row.actual_cost for row in group), Decimal()) / count,
                mean_latency_seconds=sum((row.latency_seconds for row in group), Decimal()) / count,
            )
        )
    return tuple(summaries)


@dataclass(frozen=True, slots=True)
class OracleChoice:
    case_id: str
    path_id: str
    utility: Decimal


def allowed_oracle(
    rows: tuple[MeasuredRouteOutcome, ...], *, policy: UtilityPolicy
) -> tuple[OracleChoice, ...]:
    _require_unique_measured_rows(rows)
    choices: list[OracleChoice] = []
    for case_id in sorted({row.case_id for row in rows}):
        permitted = [row for row in rows if row.case_id == case_id and row.permitted]
        if not permitted:
            raise ValueError(f"case {case_id!r} has no measured permitted path")
        selected = min(
            permitted,
            key=lambda row: (-measured_utility(row, policy), row.path_id),
        )
        choices.append(OracleChoice(case_id, selected.path_id, measured_utility(selected, policy)))
    return tuple(choices)


@dataclass(frozen=True, slots=True)
class RegretResult:
    case_id: str
    selected_path_id: str
    oracle_path_id: str
    regret: Decimal


def oracle_regret(
    rows: tuple[MeasuredRouteOutcome, ...],
    *,
    selected_paths: dict[str, str],
    policy: UtilityPolicy,
) -> tuple[RegretResult, ...]:
    oracle = {item.case_id: item for item in allowed_oracle(rows, policy=policy)}
    if set(selected_paths) != set(oracle):
        raise ValueError("selected paths must account for every and only evaluated case")
    by_identity = {(row.case_id, row.path_id): row for row in rows}
    results: list[RegretResult] = []
    for case_id, oracle_choice in oracle.items():
        selected_path = selected_paths[case_id]
        selected = by_identity.get((case_id, selected_path))
        if selected is None:
            raise ValueError("selected path lacks a measured outcome")
        results.append(
            RegretResult(
                case_id,
                selected_path,
                oracle_choice.path_id,
                oracle_choice.utility - measured_utility(selected, policy),
            )
        )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class RecoveryUtility:
    base_failure_count: int
    incrementally_recovered_count: int
    incremental_recovery_yield: Decimal
    incremental_cost: Decimal
    cost_per_incremental_recovery: Decimal | None


def recovery_utility(
    *,
    base_rows: tuple[MeasuredRouteOutcome, ...],
    recovery_rows: tuple[MeasuredRouteOutcome, ...],
) -> RecoveryUtility:
    if len({row.case_id for row in base_rows}) != len(base_rows):
        raise ValueError("base rows must contain one measured path per case")
    if len({row.case_id for row in recovery_rows}) != len(recovery_rows):
        raise ValueError("recovery rows must contain one measured path per case")
    failed = {row.case_id for row in base_rows if not row.trusted}
    if not failed:
        raise ValueError("base failure set is empty")
    recovery_by_case = {row.case_id: row for row in recovery_rows}
    if not failed.issubset(recovery_by_case):
        raise ValueError("recovery rows must account for every base failure")
    relevant = tuple(recovery_by_case[case_id] for case_id in sorted(failed))
    recovered = sum(row.trusted for row in relevant)
    incremental_cost = sum((row.actual_cost for row in relevant), Decimal())
    return RecoveryUtility(
        base_failure_count=len(failed),
        incrementally_recovered_count=recovered,
        incremental_recovery_yield=Decimal(recovered) / Decimal(len(failed)),
        incremental_cost=incremental_cost,
        cost_per_incremental_recovery=(
            incremental_cost / Decimal(recovered) if recovered else None
        ),
    )


__all__ = [
    "DpmPathSummary",
    "MeasuredRouteOutcome",
    "OracleChoice",
    "OutcomeStatus",
    "RecoveryUtility",
    "RegretResult",
    "UtilityPolicy",
    "allowed_oracle",
    "document_performance_map",
    "measured_utility",
    "oracle_regret",
    "recovery_utility",
]
