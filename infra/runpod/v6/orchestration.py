"""Dry-run-safe contracts for isolated pools, spend protection, and cleanup."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from benchmark.v6.contracts import ContractError, canonical_sha256, require_sha256

_SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_ATTEMPT_KINDS = {"primary", "retry", "speculative", "hedge", "straggler"}
_ANOMALOUS_COST_CAUSES = {"duplicate", "error", "idle", "retry_runaway"}
_BILLABLE_FINAL_STATES = {"verified", "authority_verified", "cross_model_verified", "auto_repaired"}
_NON_BILLABLE_FINAL_STATES = {"unresolved", "quarantined", "failed"}


class SpendState(StrEnum):
    HEALTHY = "healthy"
    SOFT_ALERT = "soft_alert"
    HARD_STOP_RUNAWAY = "hard_stop_runaway"


@dataclass(frozen=True, slots=True)
class SpendPolicy:
    expected_cost_usd: Decimal
    anomaly_multiplier: Decimal = Decimal("3")
    maximum_control_plane_retries: int = 2
    provider_retry_count: int = 0
    endpoint_idle_timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if self.expected_cost_usd <= 0:
            raise ContractError("expected_cost_usd must be positive")
        if self.anomaly_multiplier < 3:
            raise ContractError(
                "anomaly_multiplier may not be below the approved 3x runaway threshold"
            )
        if self.maximum_control_plane_retries < 0:
            raise ContractError("maximum_control_plane_retries cannot be negative")
        if self.provider_retry_count != 0:
            raise ContractError(
                "provider retries must remain disabled; the control plane owns idempotency"
            )
        if self.endpoint_idle_timeout_seconds < 30:
            raise ContractError("endpoint idle timeout below 30 seconds is invalid")


@dataclass(frozen=True, slots=True)
class DispatchRecord:
    idempotency_key: str
    logical_work_id: str
    provider_job_id: str
    attempt_kind: str
    retry_index: int


class SpendGuard:
    """Protect against duplicate/runaway work without using cost as a skip gate."""

    def __init__(self, *, run_id: str, policy: SpendPolicy) -> None:
        if not run_id.strip():
            raise ContractError("run_id is required")
        self.run_id = run_id
        self.policy = policy
        self.state = SpendState.HEALTHY
        self._dispatch_by_key: dict[str, DispatchRecord] = {}
        self._key_by_provider_job: dict[str, str] = {}
        self._retry_count: dict[str, int] = {}
        self._accepted_job_by_work: dict[str, str] = {}
        self._user_charge_by_work: dict[str, Decimal] = {}
        self._provider_cost_by_cause: dict[str, Decimal] = {}
        self._alerts: list[str] = []

    @property
    def provider_cost_usd(self) -> Decimal:
        return sum(self._provider_cost_by_cause.values(), Decimal("0"))

    @property
    def user_charge_usd(self) -> Decimal:
        return sum(self._user_charge_by_work.values(), Decimal("0"))

    @property
    def alerts(self) -> tuple[str, ...]:
        return tuple(self._alerts)

    def hard_stop(self, reason: str) -> SpendState:
        """Activate the irreversible duplicate/runaway safety stop.

        Coordinators use this when a provider write has an ambiguous outcome or
        when the evidence ledger reveals duplicate work before a provider cost
        can be attributed.
        """

        normalized = reason.strip().upper()
        if not normalized:
            raise ContractError("hard-stop reason is required")
        self._hard_stop(normalized)
        return self.state

    def dispatch(
        self,
        *,
        idempotency_key: str,
        logical_work_id: str,
        provider_job_id: str,
        attempt_kind: str,
        retry_index: int = 0,
    ) -> DispatchRecord:
        self._require_running()
        if not all(value.strip() for value in (idempotency_key, logical_work_id, provider_job_id)):
            raise ContractError("dispatch identities must be non-empty")
        if attempt_kind not in _ATTEMPT_KINDS:
            raise ContractError(f"unsupported attempt_kind: {attempt_kind}")
        if retry_index < 0:
            raise ContractError("retry_index cannot be negative")
        if attempt_kind == "retry":
            expected_index = self._retry_count.get(logical_work_id, 0) + 1
            if retry_index != expected_index:
                raise ContractError(
                    f"retry_index must be the next contiguous index ({expected_index})"
                )
            if retry_index > self.policy.maximum_control_plane_retries:
                self._hard_stop("MAXIMUM_RETRY_COUNT_EXCEEDED")
                raise ContractError("maximum control-plane retry count exceeded")

        previous = self._dispatch_by_key.get(idempotency_key)
        if previous is not None:
            if (
                previous.provider_job_id == provider_job_id
                and previous.logical_work_id == logical_work_id
            ):
                return previous
            self._hard_stop("IDEMPOTENCY_KEY_REUSED_FOR_DIFFERENT_JOB")
            raise ContractError("idempotency key maps to a different provider job")
        previous_key = self._key_by_provider_job.get(provider_job_id)
        if previous_key is not None and previous_key != idempotency_key:
            self._hard_stop("PROVIDER_JOB_REUSED_ACROSS_IDEMPOTENCY_KEYS")
            raise ContractError("provider job ID maps to multiple idempotency keys")

        record = DispatchRecord(
            idempotency_key=idempotency_key,
            logical_work_id=logical_work_id,
            provider_job_id=provider_job_id,
            attempt_kind=attempt_kind,
            retry_index=retry_index,
        )
        self._dispatch_by_key[idempotency_key] = record
        self._key_by_provider_job[provider_job_id] = idempotency_key
        if attempt_kind == "retry":
            self._retry_count[logical_work_id] = retry_index
        return record

    def accept_verified_result(self, *, logical_work_id: str, provider_job_id: str) -> None:
        self._require_running()
        key = self._key_by_provider_job.get(provider_job_id)
        if key is None or self._dispatch_by_key[key].logical_work_id != logical_work_id:
            raise ContractError("cannot accept an unknown provider job")
        previous = self._accepted_job_by_work.get(logical_work_id)
        if previous is None:
            self._accepted_job_by_work[logical_work_id] = provider_job_id
            return
        if previous != provider_job_id:
            self._hard_stop("DUPLICATE_ACCEPTANCE")
            raise ContractError("first verified result already won; duplicate acceptance forbidden")

    def settle_user_charge(
        self,
        *,
        logical_work_id: str,
        amount_usd: Decimal | str,
        final_integrity_state: str,
    ) -> None:
        self._require_running()
        amount = _money(amount_usd)
        if logical_work_id in self._user_charge_by_work:
            self._hard_stop("DUPLICATE_USER_CHARGE")
            raise ContractError("logical work may be charged at most once")
        if final_integrity_state in _NON_BILLABLE_FINAL_STATES:
            if amount != 0:
                self._hard_stop("NON_BILLABLE_RESULT_CHARGED")
                raise ContractError(
                    "unresolved, quarantined, and failed results must not be charged"
                )
        elif final_integrity_state in _BILLABLE_FINAL_STATES:
            if logical_work_id not in self._accepted_job_by_work:
                raise ContractError("verified work must be accepted before settlement")
            if amount <= 0:
                raise ContractError("billable verified work requires a positive settlement")
        else:
            raise ContractError(f"unknown final integrity state: {final_integrity_state}")
        self._user_charge_by_work[logical_work_id] = amount

    def record_provider_cost(self, *, amount_usd: Decimal | str, cause: str) -> SpendState:
        amount = _money(amount_usd)
        if amount < 0:
            raise ContractError("provider cost cannot be negative")
        if cause not in {"planned", "retry", "duplicate", "error", "idle", "retry_runaway"}:
            raise ContractError(f"unknown provider cost cause: {cause}")
        self._provider_cost_by_cause[cause] = (
            self._provider_cost_by_cause.get(cause, Decimal("0")) + amount
        )
        total = self.provider_cost_usd
        if total > self.policy.expected_cost_usd and self.state is SpendState.HEALTHY:
            self.state = SpendState.SOFT_ALERT
            self._alerts.append("EXPECTED_COST_EXCEEDED_SOFT_ALERT")
        threshold = self.policy.expected_cost_usd * self.policy.anomaly_multiplier
        if total > threshold and any(
            self._provider_cost_by_cause.get(item, 0) > 0 for item in _ANOMALOUS_COST_CAUSES
        ):
            self._hard_stop("ANOMALOUS_DUPLICATE_OR_ERROR_COST_ABOVE_3X")
        return self.state

    def report(self) -> dict[str, object]:
        report: dict[str, object] = {
            "schema_version": "6.0.0",
            "run_id": self.run_id,
            "state": self.state.value,
            "expected_cost_usd": str(self.policy.expected_cost_usd),
            "provider_cost_usd": str(self.provider_cost_usd),
            "provider_cost_by_cause": {
                key: str(value) for key, value in sorted(self._provider_cost_by_cause.items())
            },
            "user_charge_usd": str(self.user_charge_usd),
            "dispatch_count": len(self._dispatch_by_key),
            "accepted_count": len(self._accepted_job_by_work),
            "settled_work_count": len(self._user_charge_by_work),
            "alerts": list(self._alerts),
            "provider_retries": self.policy.provider_retry_count,
            "cost_used_as_mandatory_test_blocker": False,
        }
        report["report_sha256"] = canonical_sha256(report)
        return report

    def _require_running(self) -> None:
        if self.state is SpendState.HARD_STOP_RUNAWAY:
            raise ContractError(
                "runaway hard stop is active; no new work may be dispatched or settled"
            )

    def _hard_stop(self, reason: str) -> None:
        self.state = SpendState.HARD_STOP_RUNAWAY
        if reason not in self._alerts:
            self._alerts.append(reason)


class EndpointState(StrEnum):
    ABSENT = "absent"
    PROVISIONING = "provisioning"
    WARMING = "warming"
    READY = "ready"
    DRAINING = "draining"
    EVIDENCE_PENDING = "evidence_pending"
    DELETE_REQUESTED = "delete_requested"
    DELETED = "deleted"
    CLEANUP_FAILED = "cleanup_failed"
    ORPHANED = "orphaned"


_TRANSITIONS: Mapping[EndpointState, frozenset[EndpointState]] = MappingProxyType(
    {
        EndpointState.ABSENT: frozenset({EndpointState.PROVISIONING}),
        EndpointState.PROVISIONING: frozenset(
            {EndpointState.WARMING, EndpointState.DRAINING, EndpointState.ORPHANED}
        ),
        EndpointState.WARMING: frozenset(
            {EndpointState.READY, EndpointState.DRAINING, EndpointState.ORPHANED}
        ),
        EndpointState.READY: frozenset({EndpointState.DRAINING, EndpointState.ORPHANED}),
        EndpointState.DRAINING: frozenset({EndpointState.EVIDENCE_PENDING, EndpointState.ORPHANED}),
        EndpointState.EVIDENCE_PENDING: frozenset(
            {EndpointState.DELETE_REQUESTED, EndpointState.ORPHANED}
        ),
        EndpointState.DELETE_REQUESTED: frozenset(
            {EndpointState.DELETED, EndpointState.CLEANUP_FAILED}
        ),
        EndpointState.CLEANUP_FAILED: frozenset(
            {EndpointState.DELETE_REQUESTED, EndpointState.ORPHANED}
        ),
        EndpointState.ORPHANED: frozenset({EndpointState.DELETE_REQUESTED}),
        EndpointState.DELETED: frozenset(),
    }
)


@dataclass(frozen=True, slots=True)
class CleanupFacts:
    in_flight_jobs: int = 0
    queued_jobs: int = 0
    artifacts_uploaded: bool = False
    evidence_persisted: bool = False
    grace_window_elapsed: bool = False
    provider_endpoint_absent: bool = False

    def __post_init__(self) -> None:
        if self.in_flight_jobs < 0 or self.queued_jobs < 0:
            raise ContractError("job counts cannot be negative")


@dataclass(frozen=True, slots=True)
class EndpointEvent:
    sequence: int
    from_state: EndpointState
    to_state: EndpointState
    occurred_at: str
    reason: str
    facts_sha256: str


@dataclass(slots=True)
class EndpointLifecycle:
    endpoint_id: str
    run_id: str
    pool_id: str
    created_at: datetime
    state: EndpointState = EndpointState.ABSENT
    events: list[EndpointEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not all(item.strip() for item in (self.endpoint_id, self.run_id, self.pool_id)):
            raise ContractError("endpoint_id, run_id, and pool_id are required")
        if self.created_at.tzinfo is None:
            raise ContractError("created_at must be timezone-aware")

    def transition(
        self,
        target: EndpointState,
        *,
        facts: CleanupFacts,
        occurred_at: datetime,
        reason: str,
    ) -> EndpointEvent:
        if occurred_at.tzinfo is None:
            raise ContractError("occurred_at must be timezone-aware")
        if occurred_at < self.created_at:
            raise ContractError("endpoint events cannot precede endpoint creation")
        if self.events:
            previous_at = datetime.fromisoformat(
                self.events[-1].occurred_at.removesuffix("Z") + "+00:00"
            )
            if occurred_at < previous_at:
                raise ContractError("endpoint events must be chronological")
        if not reason.strip():
            raise ContractError("every endpoint transition requires a reason")
        if target not in _TRANSITIONS[self.state]:
            raise ContractError(
                f"illegal endpoint transition: {self.state.value} -> {target.value}"
            )
        self._validate_transition_preconditions(target, facts)
        event = EndpointEvent(
            sequence=len(self.events) + 1,
            from_state=self.state,
            to_state=target,
            occurred_at=occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            reason=reason,
            facts_sha256=canonical_sha256(
                {
                    "in_flight_jobs": facts.in_flight_jobs,
                    "queued_jobs": facts.queued_jobs,
                    "artifacts_uploaded": facts.artifacts_uploaded,
                    "evidence_persisted": facts.evidence_persisted,
                    "grace_window_elapsed": facts.grace_window_elapsed,
                    "provider_endpoint_absent": facts.provider_endpoint_absent,
                }
            ),
        )
        self.events.append(event)
        self.state = target
        return event

    def receipt(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": "6.0.0",
            "endpoint_id": self.endpoint_id,
            "run_id": self.run_id,
            "pool_id": self.pool_id,
            "created_at": self.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
            "events": [
                {
                    "sequence": event.sequence,
                    "from_state": event.from_state.value,
                    "to_state": event.to_state.value,
                    "occurred_at": event.occurred_at,
                    "reason": event.reason,
                    "facts_sha256": event.facts_sha256,
                }
                for event in self.events
            ],
        }
        value["receipt_sha256"] = canonical_sha256(value)
        return value

    def _validate_transition_preconditions(
        self, target: EndpointState, facts: CleanupFacts
    ) -> None:
        if target is EndpointState.EVIDENCE_PENDING and (facts.in_flight_jobs or facts.queued_jobs):
            raise ContractError("draining cannot complete while work remains")
        if target is EndpointState.DELETE_REQUESTED and not (
            facts.in_flight_jobs == 0
            and facts.queued_jobs == 0
            and facts.artifacts_uploaded
            and facts.evidence_persisted
            and facts.grace_window_elapsed
        ):
            raise ContractError(
                "delete requires empty work, uploaded artifacts, persisted evidence, and grace"
            )
        if target is EndpointState.DELETED and not facts.provider_endpoint_absent:
            raise ContractError("deleted state requires provider absence proof")


def audit_orphan_endpoints(
    endpoints: list[EndpointLifecycle],
    *,
    active_run_ids: set[str],
    now: datetime,
    orphan_after: timedelta,
) -> tuple[str, ...]:
    if now.tzinfo is None:
        raise ContractError("orphan audit time must be timezone-aware")
    if orphan_after <= timedelta(0):
        raise ContractError("orphan_after must be positive")
    return tuple(
        sorted(
            endpoint.endpoint_id
            for endpoint in endpoints
            if endpoint.state is not EndpointState.DELETED
            and endpoint.run_id not in active_run_ids
            and now - endpoint.created_at >= orphan_after
        )
    )


@dataclass(frozen=True, slots=True)
class PoolSpec:
    pool_id: str
    model_family: str
    candidate_ids: tuple[str, ...]
    enabled: bool
    image_digest: str | None
    identity_state: str
    gpu_classes: tuple[str, ...]
    min_workers: int
    max_workers: int
    provider_retry_count: int
    secret_names: tuple[str, ...]
    cache_namespace: str


class PoolRegistry:
    def __init__(self, pools: Mapping[str, PoolSpec]) -> None:
        self._pools = MappingProxyType(dict(pools))

    @classmethod
    def load(cls, path: Path) -> PoolRegistry:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ContractError(f"cannot load pool registry: {exc}") from exc
        if not isinstance(raw, Mapping) or raw.get("schema_version") != "6.0.0":
            raise ContractError("pool registry schema_version must be 6.0.0")
        rows = raw.get("pools")
        if not isinstance(rows, list) or not rows:
            raise ContractError("pool registry must contain model-isolated pools")
        pools: dict[str, PoolSpec] = {}
        candidate_owner: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ContractError("pool rows must be mappings")
            spec = _parse_pool(row)
            if spec.pool_id in pools:
                raise ContractError(f"duplicate pool id: {spec.pool_id}")
            for candidate_id in spec.candidate_ids:
                previous = candidate_owner.setdefault(candidate_id, spec.pool_id)
                if previous != spec.pool_id:
                    raise ContractError(
                        f"candidate {candidate_id} assigned to multiple model pools"
                    )
            pools[spec.pool_id] = spec
        return cls(pools)

    @property
    def pools(self) -> tuple[PoolSpec, ...]:
        return tuple(self._pools[key] for key in sorted(self._pools))

    def get(self, pool_id: str) -> PoolSpec:
        try:
            return self._pools[pool_id]
        except KeyError as exc:
            raise ContractError(f"unknown pool: {pool_id}") from exc


def _parse_pool(raw: Mapping[str, Any]) -> PoolSpec:
    pool_id = str(raw.get("id", "")).strip()
    model_family = str(raw.get("model_family", "")).strip()
    candidates_raw = raw.get("candidate_ids")
    gpu_raw = raw.get("gpu_classes")
    secrets_raw = raw.get("secret_names")
    if not pool_id or not model_family:
        raise ContractError("pool id and model_family are required")
    if (
        not isinstance(candidates_raw, list)
        or not candidates_raw
        or not all(isinstance(item, str) and item.strip() for item in candidates_raw)
    ):
        raise ContractError(f"pool {pool_id}: candidate_ids must be non-empty strings")
    if (
        not isinstance(gpu_raw, list)
        or not gpu_raw
        or not all(isinstance(item, str) and item.strip() for item in gpu_raw)
    ):
        raise ContractError(f"pool {pool_id}: gpu_classes must be non-empty strings")
    if not isinstance(secrets_raw, list) or not all(
        isinstance(item, str) and _SECRET_NAME_RE.fullmatch(item) for item in secrets_raw
    ):
        raise ContractError(f"pool {pool_id}: secret_names must contain names only")
    if any("=" in item for item in secrets_raw):
        raise ContractError(f"pool {pool_id}: secret values are forbidden")
    min_workers = int(raw.get("min_workers", 0))
    max_workers = int(raw.get("max_workers", 0))
    if min_workers < 0 or max_workers < 1 or min_workers > max_workers:
        raise ContractError(f"pool {pool_id}: invalid worker bounds")
    provider_retry_count = int(raw.get("provider_retry_count", -1))
    if provider_retry_count != 0:
        raise ContractError(f"pool {pool_id}: provider retries must be zero")
    identity_state = str(raw.get("identity_state", "")).strip()
    image_digest_raw = raw.get("image_digest")
    image_digest = str(image_digest_raw).strip() if image_digest_raw is not None else None
    enabled = bool(raw.get("enabled", False))
    if enabled or identity_state == "ready":
        if image_digest is None:
            raise ContractError(f"pool {pool_id}: enabled/ready pool requires an image digest")
        require_sha256(image_digest, f"pool {pool_id}.image_digest")
    if enabled and identity_state != "ready":
        raise ContractError(f"pool {pool_id}: enabled pool identity must be ready")
    cache_namespace = str(raw.get("cache_namespace", "")).strip()
    if not cache_namespace or cache_namespace.casefold() in {"shared", "default"}:
        raise ContractError(f"pool {pool_id}: model-isolated cache_namespace is required")
    return PoolSpec(
        pool_id=pool_id,
        model_family=model_family,
        candidate_ids=tuple(candidates_raw),
        enabled=enabled,
        image_digest=image_digest,
        identity_state=identity_state,
        gpu_classes=tuple(gpu_raw),
        min_workers=min_workers,
        max_workers=max_workers,
        provider_retry_count=provider_retry_count,
        secret_names=tuple(secrets_raw),
        cache_namespace=cache_namespace,
    )


def _money(value: Decimal | str) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("money value must be a finite decimal") from exc
    if not amount.is_finite():
        raise ContractError("money value must be finite")
    return amount
