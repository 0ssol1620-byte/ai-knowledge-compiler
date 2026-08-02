"""Transactional v6 parallel-runtime persistence and exactly-once guards."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from akc_cir import validate_collection_event_payload
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import Collection, CollectionEvent, Document, utcnow
from akc_api.parallel_models import (
    AcceptedBlock,
    AcceptedBlockInvalidation,
    ArbitrationDecision,
    AttemptValidation,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
    SemanticHealthEvent,
    WorkerHealth,
)

_ATTEMPT_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "CREATED": frozenset({"QUEUED", "TERMINAL_FAILED"}),
    "QUEUED": frozenset({"RUNNING", "RETRYABLE_FAILED", "TERMINAL_FAILED"}),
    "RUNNING": frozenset({"OUTPUT_RECEIVED", "RETRYABLE_FAILED", "TERMINAL_FAILED", "SUPERSEDED"}),
    "OUTPUT_RECEIVED": frozenset({"VALIDATING", "REJECTED", "QUARANTINED"}),
    "VALIDATING": frozenset(
        {
            "ACCEPTED",
            "REJECTED",
            "RETRYABLE_FAILED",
            "TERMINAL_FAILED",
            "SUPERSEDED",
            "QUARANTINED",
        }
    ),
}
_TERMINAL_ATTEMPT_STATES = frozenset(
    {"ACCEPTED", "REJECTED", "RETRYABLE_FAILED", "TERMINAL_FAILED", "SUPERSEDED", "QUARANTINED"}
)
_BILLABLE_FINAL_STATES = frozenset(
    {"verified", "authority_verified", "cross_model_verified", "auto_repaired"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WORKER_STATE_SEVERITY: Mapping[str, int] = {
    "HEALTHY": 0,
    "DEGRADED": 1,
    "DRAINING": 2,
    "QUARANTINED": 3,
    "TERMINATED": 4,
}


class ParallelRuntimeConflict(ValueError):
    """A requested mutation conflicts with immutable v6 evidence."""


def canonical_sha256(value: object) -> str:
    """Hash a JSON-safe value with stable Unicode and key ordering."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_identifier(value: str, *, field: str, maximum: int = 160) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be a bounded identifier")
    if any(character.isspace() for character in normalized):
        raise ValueError(f"{field} cannot contain whitespace")
    return normalized


def _exact_sha256(value: str, *, field: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _required_validator_levels(shard: ParallelParseShard) -> frozenset[int]:
    context = shard.context if isinstance(shard.context, dict) else {}
    configured = context.get("required_validation_levels", [0, 1])
    if not isinstance(configured, list) or any(
        not isinstance(level, int) or isinstance(level, bool) or level < 0 or level > 6
        for level in configured
    ):
        raise ParallelRuntimeConflict("shard validator policy is malformed")
    required = {0, 1, *configured}
    route = shard.route_class.casefold()
    if context.get("native_comparison_required") is True:
        required.add(2)
    if context.get("authority_required") is True or any(
        marker in route for marker in ("authority", "financial", "numeric")
    ):
        required.add(3)
    if context.get("differential_required") is True:
        required.add(4)
    if context.get("multimodal_required") is True:
        required.add(5)
    if context.get("downstream_required") is True or "cross_page" in route:
        required.add(6)
    return frozenset(required)


def _required_validator_revision(
    shard: ParallelParseShard,
    level: int,
) -> tuple[str, str]:
    context = shard.context if isinstance(shard.context, dict) else {}
    configured = context.get("required_validator_revisions", {})
    if not isinstance(configured, dict):
        raise ParallelRuntimeConflict("shard validator revision policy is malformed")
    value = configured.get(str(level))
    if value is None:
        raise ParallelRuntimeConflict(
            f"required validator level L{level} has no pinned revision policy"
        )
    if not isinstance(value, dict):
        raise ParallelRuntimeConflict("shard validator revision policy is malformed")
    validator_key = value.get("validator_key")
    validator_revision = value.get("validator_revision")
    if not isinstance(validator_key, str) or not isinstance(validator_revision, str):
        raise ParallelRuntimeConflict("shard validator revision policy is malformed")
    return (
        _bounded_identifier(validator_key, field="validator_key", maximum=120),
        _bounded_identifier(validator_revision, field="validator_revision"),
    )


def _unbillable_disposition(attempt: ParallelParseAttempt, target: str) -> str:
    if target == "QUARANTINED":
        return "quarantine_unbillable"
    if attempt.attempt_kind == "hedge":
        return "speculative_unbillable"
    if attempt.attempt_kind == "straggler":
        return "straggler_unbillable"
    if attempt.attempt_kind == "shadow":
        return "shadow_unbillable"
    if attempt.attempt_kind in {"retry", "recovery"}:
        return "retry_unbillable"
    return "unresolved_unbillable"


def _authoritative_worker_state(
    *,
    claimed_state: str,
    infrastructure_status: str,
    semantic_status: str,
    consecutive_semantic_failures: int,
) -> str:
    """Never let a caller weaken the state implied by observed health evidence."""

    if claimed_state not in _WORKER_STATE_SEVERITY:
        raise ValueError("unsupported worker state")
    if infrastructure_status == "terminated":
        derived = "TERMINATED"
    elif infrastructure_status == "unreachable" or semantic_status == "failing":
        derived = "QUARANTINED"
    elif (
        infrastructure_status == "degraded"
        or semantic_status == "degraded"
        or consecutive_semantic_failures > 0
    ):
        derived = "DEGRADED"
    else:
        derived = "HEALTHY"
    return max(
        (claimed_state, derived),
        key=lambda candidate: _WORKER_STATE_SEVERITY[candidate],
    )


async def emit_parallel_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    job_id: uuid.UUID | None,
    event_type: str,
    payload: Mapping[str, Any],
) -> CollectionEvent:
    """Append a canonical event while serializing the collection sequence."""

    collection = await session.scalar(
        select(Collection)
        .where(
            Collection.tenant_id == tenant_id,
            Collection.id == collection_id,
        )
        .with_for_update()
    )
    if collection is None:
        raise ParallelRuntimeConflict("collection does not exist in the tenant")
    safe = validate_collection_event_payload(
        event_type,
        payload,
        collection_id=collection.id,
        job_id=job_id,
    )
    collection.event_sequence += 1
    collection.updated_at = utcnow()
    event = CollectionEvent(
        tenant_id=tenant_id,
        collection_id=collection.id,
        job_id=job_id,
        sequence=collection.event_sequence,
        event_type=event_type,
        schema_version="1.0",
        payload=safe,
    )
    session.add(event)
    await session.flush()
    return event


async def create_parse_shard(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID | None,
    document_id: uuid.UUID,
    processing_job_id: uuid.UUID,
    document_version_id: str,
    parent_shard_id: uuid.UUID | None,
    shard_key: str,
    shard_kind: str,
    ordinal: int,
    page_start: int,
    page_end: int,
    region: Mapping[str, Any],
    context: Mapping[str, Any],
    overlap: Mapping[str, Any],
    ownership: Mapping[str, Any],
    route_class: str,
    priority: int,
    size_units: int,
    plan_version: str,
    input_sha256: str,
    dispatch_idempotency_key: str,
) -> tuple[ParallelParseShard, bool]:
    """Create a deterministic shard, returning ``(row, replayed)``."""

    idempotency_key = _bounded_identifier(
        dispatch_idempotency_key,
        field="dispatch_idempotency_key",
    )
    document = await session.scalar(
        select(Document)
        .where(Document.tenant_id == tenant_id, Document.id == document_id)
        .with_for_update()
    )
    if document is None:
        raise ParallelRuntimeConflict("parse shard document does not exist in the tenant")
    existing = await session.scalar(
        select(ParallelParseShard).where(
            ParallelParseShard.tenant_id == tenant_id,
            ParallelParseShard.dispatch_idempotency_key == idempotency_key,
        )
    )
    collection_value = str(collection_id) if collection_id else None
    job_value = str(processing_job_id)
    version_value = _bounded_identifier(
        document_version_id,
        field="document_version_id",
    )
    input_sha256_value = _exact_sha256(input_sha256, field="input_sha256")
    immutable = {
        "collection_id": collection_value,
        "document_id": str(document_id),
        "processing_job_id": job_value,
        "document_version_id": version_value,
        "parent_shard_id": str(parent_shard_id) if parent_shard_id else None,
        "shard_key": shard_key,
        "shard_kind": shard_kind,
        "ordinal": ordinal,
        "page_start": page_start,
        "page_end": page_end,
        "region": dict(region),
        "context": dict(context),
        "overlap": dict(overlap),
        "ownership": dict(ownership),
        "route_class": route_class,
        "priority": priority,
        "size_units": size_units,
        "plan_version": plan_version,
        "input_sha256": input_sha256_value,
    }
    if existing is not None:
        persisted = {
            "collection_id": str(existing.collection_id) if existing.collection_id else None,
            "document_id": str(existing.document_id),
            "processing_job_id": (
                str(existing.processing_job_id) if existing.processing_job_id else None
            ),
            "document_version_id": existing.document_version_id,
            "parent_shard_id": str(existing.parent_shard_id) if existing.parent_shard_id else None,
            "shard_key": existing.shard_key,
            "shard_kind": existing.shard_kind,
            "ordinal": existing.ordinal,
            "page_start": existing.page_start,
            "page_end": existing.page_end,
            "region": existing.region,
            "context": existing.context,
            "overlap": existing.overlap,
            "ownership": existing.ownership,
            "route_class": existing.route_class,
            "priority": existing.priority,
            "size_units": existing.size_units,
            "plan_version": existing.plan_version,
            "input_sha256": existing.input_sha256,
        }
        if canonical_sha256(persisted) != canonical_sha256(immutable):
            raise ParallelRuntimeConflict("shard idempotency key was reused with different input")
        return existing, True
    shard = ParallelParseShard(
        tenant_id=tenant_id,
        collection_id=collection_id,
        document_id=document_id,
        processing_job_id=processing_job_id,
        document_version_id=version_value,
        parent_shard_id=parent_shard_id,
        shard_key=_bounded_identifier(shard_key, field="shard_key"),
        shard_kind=shard_kind,
        ordinal=ordinal,
        page_start=page_start,
        page_end=page_end,
        region=dict(region),
        context=dict(context),
        overlap=dict(overlap),
        ownership=dict(ownership),
        route_class=_bounded_identifier(route_class, field="route_class", maximum=80),
        priority=priority,
        size_units=size_units,
        plan_version=_bounded_identifier(plan_version, field="plan_version", maximum=120),
        input_sha256=input_sha256_value,
        status="PLANNED",
        dispatch_idempotency_key=idempotency_key,
    )
    session.add(shard)
    await session.flush()
    return shard, False


async def create_parse_attempt(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    shard_id: uuid.UUID,
    attempt_kind: str,
    pool_key: str,
    model_id: str,
    model_revision: str,
    runtime_identity: str,
    route_policy_version: str,
    idempotency_key: str,
    request_sha256: str,
    parent_attempt_id: uuid.UUID | None = None,
    provider_invocation_id: uuid.UUID | None = None,
) -> tuple[ParallelParseAttempt, bool]:
    """Create one lineage child; retries, hedges, and replicas never overwrite."""

    key = _bounded_identifier(idempotency_key, field="idempotency_key")
    shard = await session.scalar(
        select(ParallelParseShard)
        .where(
            ParallelParseShard.tenant_id == tenant_id,
            ParallelParseShard.id == shard_id,
        )
        .with_for_update()
    )
    if shard is None:
        raise ParallelRuntimeConflict("parse shard does not exist in the tenant")
    existing = await session.scalar(
        select(ParallelParseAttempt).where(
            ParallelParseAttempt.tenant_id == tenant_id,
            ParallelParseAttempt.idempotency_key == key,
        )
    )
    if existing is not None:
        identity = (
            existing.shard_id,
            existing.parent_attempt_id,
            existing.attempt_kind,
            existing.pool_key,
            existing.model_id,
            existing.model_revision,
            existing.runtime_identity,
            existing.route_policy_version,
            existing.request_sha256,
            existing.provider_invocation_id,
        )
        requested = (
            shard_id,
            parent_attempt_id,
            attempt_kind,
            pool_key,
            model_id,
            model_revision,
            runtime_identity,
            route_policy_version,
            request_sha256,
            provider_invocation_id,
        )
        if identity != requested:
            raise ParallelRuntimeConflict("attempt idempotency key was reused with different input")
        return existing, True
    if parent_attempt_id is not None:
        parent = await session.scalar(
            select(ParallelParseAttempt).where(
                ParallelParseAttempt.tenant_id == tenant_id,
                ParallelParseAttempt.id == parent_attempt_id,
            )
        )
        if parent is None or parent.shard_id != shard_id:
            raise ParallelRuntimeConflict("parent attempt is outside the shard lineage")
    latest = await session.scalar(
        select(func.max(ParallelParseAttempt.attempt_number)).where(
            ParallelParseAttempt.tenant_id == tenant_id,
            ParallelParseAttempt.shard_id == shard_id,
        )
    )
    attempt = ParallelParseAttempt(
        tenant_id=tenant_id,
        shard_id=shard_id,
        parent_attempt_id=parent_attempt_id,
        provider_invocation_id=provider_invocation_id,
        attempt_number=int(latest or 0) + 1,
        attempt_kind=attempt_kind,
        state="CREATED",
        pool_key=_bounded_identifier(pool_key, field="pool_key", maximum=120),
        model_id=_bounded_identifier(model_id, field="model_id"),
        model_revision=_bounded_identifier(model_revision, field="model_revision"),
        runtime_identity=_bounded_identifier(runtime_identity, field="runtime_identity"),
        route_policy_version=_bounded_identifier(
            route_policy_version,
            field="route_policy_version",
            maximum=120,
        ),
        idempotency_key=key,
        request_sha256=_exact_sha256(request_sha256, field="request_sha256"),
        billing_disposition=(
            "speculative_unbillable"
            if attempt_kind == "hedge"
            else "straggler_unbillable"
            if attempt_kind == "straggler"
            else "shadow_unbillable"
            if attempt_kind == "shadow"
            else "retry_unbillable"
            if attempt_kind in {"retry", "recovery"}
            else "pending"
        ),
    )
    session.add(attempt)
    await session.flush()
    return attempt, False


async def transition_parse_attempt(
    session: AsyncSession,
    attempt: ParallelParseAttempt,
    target: str,
    *,
    now: datetime | None = None,
) -> None:
    """Advance only through the canonical v6 attempt state machine."""

    if attempt.state == target:
        return
    if attempt.state in _TERMINAL_ATTEMPT_STATES:
        raise ParallelRuntimeConflict(f"terminal parse attempt is immutable: {attempt.state}")
    if target not in _ATTEMPT_TRANSITIONS.get(attempt.state, frozenset()):
        raise ParallelRuntimeConflict(
            f"illegal parse attempt transition: {attempt.state}->{target}"
        )
    occurred_at = now or utcnow()
    attempt.state = target
    if target == "RUNNING" and attempt.started_at is None:
        attempt.started_at = occurred_at
    if target in _TERMINAL_ATTEMPT_STATES:
        attempt.completed_at = occurred_at
        if target != "ACCEPTED":
            attempt.billing_disposition = _unbillable_disposition(attempt, target)
    await session.flush()


async def record_attempt_output(
    session: AsyncSession,
    attempt: ParallelParseAttempt,
    *,
    artifact_key: str,
    output_sha256: str,
    output_summary: Mapping[str, Any],
    gpu_milliseconds: int,
    cost_usd: Decimal,
    now: datetime | None = None,
) -> None:
    """Attach a provider output exactly once, regardless of HTTP status."""

    locked_attempt = await session.scalar(
        select(ParallelParseAttempt)
        .where(
            ParallelParseAttempt.tenant_id == attempt.tenant_id,
            ParallelParseAttempt.id == attempt.id,
        )
        .with_for_update()
    )
    if locked_attempt is None:
        raise ParallelRuntimeConflict("parse attempt no longer exists")
    attempt = locked_attempt
    if attempt.output_sha256 is not None:
        if (
            attempt.output_sha256 == output_sha256
            and attempt.output_artifact_key == artifact_key
            and attempt.output_summary == dict(output_summary)
            and attempt.gpu_milliseconds == gpu_milliseconds
            and attempt.cost_usd == cost_usd
        ):
            return
        raise ParallelRuntimeConflict("parse attempt output is immutable")
    if attempt.state != "RUNNING":
        raise ParallelRuntimeConflict("output can only attach to a running attempt")
    _exact_sha256(output_sha256, field="output_sha256")
    if gpu_milliseconds < 0 or cost_usd < 0:
        raise ValueError("attempt usage cannot be negative")
    occurred_at = now or utcnow()
    attempt.output_artifact_key = artifact_key
    attempt.output_sha256 = output_sha256
    attempt.output_summary = dict(output_summary)
    attempt.gpu_milliseconds = gpu_milliseconds
    attempt.cost_usd = cost_usd
    attempt.output_received_at = occurred_at
    await transition_parse_attempt(session, attempt, "OUTPUT_RECEIVED", now=occurred_at)


async def record_attempt_validation(
    session: AsyncSession,
    *,
    attempt: ParallelParseAttempt,
    level: int,
    validator_key: str,
    validator_revision: str,
    status: str,
    score: Decimal | None,
    hard_fail: bool,
    reason_codes: Iterable[str],
    findings: Iterable[Mapping[str, Any]],
    evidence: Mapping[str, Any],
) -> tuple[AttemptValidation, bool]:
    """Append idempotent, content-addressed validator evidence."""

    locked_attempt = await session.scalar(
        select(ParallelParseAttempt)
        .where(
            ParallelParseAttempt.tenant_id == attempt.tenant_id,
            ParallelParseAttempt.id == attempt.id,
        )
        .with_for_update()
    )
    if locked_attempt is None:
        raise ParallelRuntimeConflict("validation attempt no longer exists")
    attempt = locked_attempt
    evidence_value = dict(evidence)
    reason_codes_value = list(reason_codes)
    findings_value = [dict(finding) for finding in findings]
    evidence_sha256 = canonical_sha256(evidence_value)
    existing = await session.scalar(
        select(AttemptValidation).where(
            AttemptValidation.tenant_id == attempt.tenant_id,
            AttemptValidation.attempt_id == attempt.id,
            AttemptValidation.level == level,
            AttemptValidation.validator_key == validator_key,
            AttemptValidation.validator_revision == validator_revision,
        )
    )
    if existing is not None:
        immutable = (
            existing.evidence_sha256,
            existing.status,
            existing.score,
            existing.hard_fail,
            existing.reason_codes,
            existing.findings,
        )
        requested = (
            evidence_sha256,
            status,
            score,
            hard_fail,
            reason_codes_value,
            findings_value,
        )
        if immutable != requested:
            raise ParallelRuntimeConflict("validator identity was reused with different evidence")
        return existing, True
    if attempt.state == "OUTPUT_RECEIVED":
        await transition_parse_attempt(session, attempt, "VALIDATING")
    if attempt.state != "VALIDATING":
        raise ParallelRuntimeConflict("validation requires an output in VALIDATING state")
    row = AttemptValidation(
        tenant_id=attempt.tenant_id,
        attempt_id=attempt.id,
        level=level,
        validator_key=_bounded_identifier(
            validator_key,
            field="validator_key",
            maximum=120,
        ),
        validator_revision=_bounded_identifier(
            validator_revision,
            field="validator_revision",
        ),
        status=status,
        score=score,
        hard_fail=hard_fail,
        reason_codes=reason_codes_value,
        findings=findings_value,
        evidence=evidence_value,
        evidence_sha256=evidence_sha256,
    )
    session.add(row)
    await session.flush()
    return row, False


async def accept_verified_block(
    session: AsyncSession,
    *,
    attempt: ParallelParseAttempt,
    document_id: uuid.UUID,
    processing_job_id: uuid.UUID,
    document_version_id: str,
    arbitration_id: uuid.UUID,
    logical_block_key: str,
    final_state: str,
    artifact_key: str,
    artifact_sha256: str,
    provenance: Mapping[str, Any],
    acceptance_idempotency_key: str,
    credit_settlement_key: str | None,
    credit_amount: Decimal,
) -> tuple[AcceptedBlock, bool]:
    """Select a first verified winner and bind its only billable credit entry."""

    key = _bounded_identifier(
        acceptance_idempotency_key,
        field="acceptance_idempotency_key",
    )
    logical_key = _bounded_identifier(
        logical_block_key,
        field="logical_block_key",
        maximum=200,
    )
    artifact_key_value = _bounded_identifier(
        artifact_key,
        field="artifact_key",
        maximum=500,
    )
    artifact_sha256_value = _exact_sha256(
        artifact_sha256,
        field="artifact_sha256",
    )
    provenance_value = dict(provenance)
    version_value = _bounded_identifier(
        document_version_id,
        field="document_version_id",
    )
    credit_key = (
        _bounded_identifier(credit_settlement_key, field="credit_settlement_key")
        if credit_settlement_key is not None
        else None
    )
    expected_acceptance_key = (
        f"accept:{canonical_sha256({'key': str(arbitration_id), 'parts': ()})}"
    )
    expected_credit_key = f"credit:{canonical_sha256({'key': str(arbitration_id), 'parts': ()})}"
    if key != expected_acceptance_key or credit_key != expected_credit_key:
        raise ParallelRuntimeConflict(
            "acceptance and credit settlement keys must be server-derived from arbitration"
        )
    shard = await session.scalar(
        select(ParallelParseShard)
        .where(
            ParallelParseShard.tenant_id == attempt.tenant_id,
            ParallelParseShard.id == attempt.shard_id,
        )
        .with_for_update()
    )
    if shard is None:
        raise ParallelRuntimeConflict("accepted attempt lost its shard")
    if (
        shard.document_id != document_id
        or shard.processing_job_id != processing_job_id
        or shard.document_version_id != version_value
    ):
        raise ParallelRuntimeConflict("accepted output is outside the shard document lineage")
    arbitration = await session.scalar(
        select(ArbitrationDecision)
        .where(
            ArbitrationDecision.tenant_id == attempt.tenant_id,
            ArbitrationDecision.id == arbitration_id,
        )
        .with_for_update()
    )
    if (
        arbitration is None
        or arbitration.document_id != document_id
        or arbitration.shard_id != shard.id
        or arbitration.selected_attempt_id != attempt.id
        or arbitration.decision != "selected"
        or arbitration.logical_unit_key != logical_key
        or arbitration.logical_unit_sha256 != canonical_sha256({"logical_unit_key": logical_key})
        or Decimal(arbitration.priced_credit_amount) != credit_amount
    ):
        raise ParallelRuntimeConflict("accepted output differs from its content-bound arbitration")
    existing = await session.scalar(
        select(AcceptedBlock).where(
            AcceptedBlock.tenant_id == attempt.tenant_id,
            AcceptedBlock.arbitration_id == arbitration_id,
        )
    )
    if existing is None:
        existing = await session.scalar(
            select(AcceptedBlock).where(
                AcceptedBlock.tenant_id == attempt.tenant_id,
                AcceptedBlock.acceptance_idempotency_key == key,
            )
        )
    if existing is not None:
        immutable = (
            existing.attempt_id,
            existing.document_id,
            existing.processing_job_id,
            existing.document_version_id,
            existing.arbitration_id,
            existing.logical_block_key,
            existing.final_state,
            existing.artifact_key,
            existing.artifact_sha256,
            existing.provenance,
            existing.acceptance_idempotency_key,
            existing.credit_settlement_key,
            existing.credit_amount,
        )
        requested = (
            attempt.id,
            document_id,
            processing_job_id,
            version_value,
            arbitration_id,
            logical_key,
            final_state,
            artifact_key_value,
            artifact_sha256_value,
            provenance_value,
            key,
            credit_key,
            credit_amount,
        )
        if immutable != requested:
            raise ParallelRuntimeConflict("acceptance idempotency key was reused")
        return existing, True
    competing = await session.scalar(
        select(AcceptedBlock).where(
            AcceptedBlock.tenant_id == attempt.tenant_id,
            AcceptedBlock.document_id == document_id,
            AcceptedBlock.processing_job_id == processing_job_id,
            AcceptedBlock.document_version_id == version_value,
            AcceptedBlock.logical_block_key == logical_key,
            ~AcceptedBlock.id.in_(
                select(AcceptedBlockInvalidation.accepted_block_id).where(
                    AcceptedBlockInvalidation.tenant_id == attempt.tenant_id,
                    AcceptedBlockInvalidation.processing_job_id == processing_job_id,
                    AcceptedBlockInvalidation.document_version_id == version_value,
                )
            ),
        )
    )
    if competing is not None:
        raise ParallelRuntimeConflict("a verified winner already owns this logical output")
    if attempt.state not in {"VALIDATING", "ACCEPTED"} or attempt.output_sha256 is None:
        raise ParallelRuntimeConflict("only a validated provider output can be accepted")
    if artifact_sha256_value != attempt.output_sha256:
        raise ParallelRuntimeConflict(
            "accepted artifact differs from the selected provider prediction"
        )
    validation_rows = list(
        (
            await session.scalars(
                select(AttemptValidation).where(
                    AttemptValidation.tenant_id == attempt.tenant_id,
                    AttemptValidation.attempt_id == attempt.id,
                )
            )
        ).all()
    )
    if any(row.hard_fail or row.status == "failed" for row in validation_rows):
        raise ParallelRuntimeConflict("hard-failed output cannot be accepted")
    required_levels = _required_validator_levels(shard)
    for level in required_levels:
        required_revision = _required_validator_revision(shard, level)
        matching = [
            row
            for row in validation_rows
            if row.level == level
            and row.status == "passed"
            and not row.hard_fail
            and (row.validator_key, row.validator_revision) == required_revision
        ]
        if not matching:
            raise ParallelRuntimeConflict(
                f"required validator level L{level} has no pinned passing receipt"
            )
    if final_state not in _BILLABLE_FINAL_STATES:
        raise ParallelRuntimeConflict(
            "only a verified, accepted final integrity state can settle credit"
        )
    if credit_key is None or credit_amount <= 0:
        raise ParallelRuntimeConflict(
            "an accepted final integrity state requires positive credit settlement"
        )
    latest_generation = await session.scalar(
        select(func.max(AcceptedBlock.generation)).where(
            AcceptedBlock.tenant_id == attempt.tenant_id,
            AcceptedBlock.document_id == document_id,
            AcceptedBlock.processing_job_id == processing_job_id,
            AcceptedBlock.document_version_id == version_value,
            AcceptedBlock.logical_block_key == logical_key,
        )
    )
    block = AcceptedBlock(
        tenant_id=attempt.tenant_id,
        document_id=document_id,
        processing_job_id=processing_job_id,
        document_version_id=version_value,
        generation=int(latest_generation or 0) + 1,
        shard_id=attempt.shard_id,
        attempt_id=attempt.id,
        arbitration_id=arbitration_id,
        logical_block_key=logical_key,
        final_state=final_state,
        artifact_key=artifact_key_value,
        artifact_sha256=artifact_sha256_value,
        provenance=provenance_value,
        acceptance_idempotency_key=key,
        credit_settlement_key=credit_key,
        billable=True,
        credit_amount=credit_amount,
    )
    session.add(block)
    attempt.billing_disposition = "accepted_billable"
    await transition_parse_attempt(session, attempt, "ACCEPTED")
    shard.status = "ACCEPTED"
    shard.updated_at = utcnow()
    await session.flush()
    return block, False


async def request_recovery(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    shard_id: uuid.UUID,
    source_attempt_id: uuid.UUID,
    recovery_level: str,
    reason_code: str,
    target: Mapping[str, Any],
    preprocessing_variants: Iterable[str],
    route_candidates: Iterable[str],
    idempotency_key: str,
) -> tuple[RecoveryTask, bool]:
    """Create the smallest selective recovery task, never a mutation in place."""

    key = _bounded_identifier(idempotency_key, field="idempotency_key")
    reason_code_value = _bounded_identifier(reason_code, field="reason_code", maximum=120)
    target_value = dict(target)
    preprocessing_values = list(preprocessing_variants)
    route_values = list(route_candidates)
    shard = await session.scalar(
        select(ParallelParseShard)
        .where(
            ParallelParseShard.tenant_id == tenant_id,
            ParallelParseShard.id == shard_id,
        )
        .with_for_update()
    )
    if shard is None:
        raise ParallelRuntimeConflict("recovery shard does not exist")
    if shard.document_id != document_id:
        raise ParallelRuntimeConflict("recovery request is outside the shard document lineage")
    existing = await session.scalar(
        select(RecoveryTask).where(
            RecoveryTask.tenant_id == tenant_id,
            RecoveryTask.idempotency_key == key,
        )
    )
    if existing is not None:
        immutable = (
            existing.document_id,
            existing.shard_id,
            existing.source_attempt_id,
            existing.recovery_level,
            existing.reason_code,
            existing.target,
            existing.preprocessing_variants,
            existing.route_candidates,
        )
        requested = (
            document_id,
            shard_id,
            source_attempt_id,
            recovery_level,
            reason_code_value,
            target_value,
            preprocessing_values,
            route_values,
        )
        if immutable != requested:
            raise ParallelRuntimeConflict("recovery idempotency key was reused")
        return existing, True
    source_attempt = await session.scalar(
        select(ParallelParseAttempt).where(
            ParallelParseAttempt.tenant_id == tenant_id,
            ParallelParseAttempt.id == source_attempt_id,
        )
    )
    if source_attempt is None or source_attempt.shard_id != shard_id:
        raise ParallelRuntimeConflict("recovery source is outside the shard attempt lineage")
    task = RecoveryTask(
        tenant_id=tenant_id,
        document_id=document_id,
        shard_id=shard_id,
        source_attempt_id=source_attempt_id,
        recovery_level=recovery_level,
        reason_code=reason_code_value,
        target=target_value,
        preprocessing_variants=preprocessing_values,
        route_candidates=route_values,
        state="REQUESTED",
        idempotency_key=key,
    )
    session.add(task)
    shard.status = "RECOVERY_PENDING"
    shard.updated_at = utcnow()
    await session.flush()
    return task, False


async def update_worker_health(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    worker_id: str,
    pool_key: str,
    model_id: str,
    runtime_identity: str,
    region: str,
    state: str,
    infrastructure_status: str,
    semantic_status: str,
    infrastructure_score: Decimal,
    semantic_score: Decimal,
    inflight: int,
    capacity: int,
    consecutive_semantic_failures: int,
    metrics: Mapping[str, Any],
    reason_codes: Iterable[str] = (),
    impacted_attempt_ids: Iterable[uuid.UUID] = (),
    observed_at: datetime | None = None,
) -> tuple[WorkerHealth, SemanticHealthEvent | None]:
    """Update the health projection and append every semantic state change."""

    timestamp = observed_at or utcnow()
    if inflight < 0 or capacity < 1 or inflight > capacity:
        raise ValueError("worker inflight must be between zero and capacity")
    if consecutive_semantic_failures < 0:
        raise ValueError("worker semantic failure count cannot be negative")
    reason_values = list(reason_codes)
    impacted_values = [str(item) for item in impacted_attempt_ids]
    effective_state = _authoritative_worker_state(
        claimed_state=state,
        infrastructure_status=infrastructure_status,
        semantic_status=semantic_status,
        consecutive_semantic_failures=consecutive_semantic_failures,
    )
    row = await session.scalar(
        select(WorkerHealth)
        .where(
            WorkerHealth.tenant_id == tenant_id,
            WorkerHealth.worker_id == worker_id,
        )
        .with_for_update()
    )
    previous = row.state if row is not None else "HEALTHY"
    previous_semantic = row.semantic_status if row is not None else "unknown"
    if row is not None and timestamp < row.last_heartbeat_at:
        raise ParallelRuntimeConflict("stale worker health observation")
    if row is None:
        row = WorkerHealth(
            tenant_id=tenant_id,
            worker_id=_bounded_identifier(worker_id, field="worker_id"),
            pool_key=_bounded_identifier(pool_key, field="pool_key", maximum=120),
            model_id=_bounded_identifier(model_id, field="model_id"),
            runtime_identity=_bounded_identifier(runtime_identity, field="runtime_identity"),
            region=_bounded_identifier(region, field="region", maximum=80),
            state=effective_state,
            infrastructure_status=infrastructure_status,
            semantic_status=semantic_status,
            infrastructure_score=infrastructure_score,
            semantic_score=semantic_score,
            inflight=inflight,
            capacity=capacity,
            consecutive_semantic_failures=consecutive_semantic_failures,
            metrics=dict(metrics),
            drain_reason=(
                reason_values[0] if reason_values and effective_state != "HEALTHY" else None
            ),
            last_heartbeat_at=timestamp,
            last_canary_at=(timestamp if semantic_status != "unknown" else None),
            updated_at=timestamp,
        )
        session.add(row)
        await session.flush()
    else:
        if (
            row.pool_key != pool_key
            or row.model_id != model_id
            or row.runtime_identity != runtime_identity
        ):
            raise ParallelRuntimeConflict("worker identity changed without a new worker id")
        row.region = region
        row.state = effective_state
        row.infrastructure_status = infrastructure_status
        row.semantic_status = semantic_status
        row.infrastructure_score = infrastructure_score
        row.semantic_score = semantic_score
        row.inflight = inflight
        row.capacity = capacity
        row.consecutive_semantic_failures = consecutive_semantic_failures
        row.metrics = dict(metrics)
        row.drain_reason = (
            reason_values[0] if reason_values and effective_state != "HEALTHY" else None
        )
        row.last_heartbeat_at = timestamp
        if semantic_status != "unknown":
            row.last_canary_at = timestamp
        row.updated_at = timestamp
    event: SemanticHealthEvent | None = None
    if previous != effective_state or previous_semantic != semantic_status:
        event_type = {
            "DEGRADED": "degraded",
            "DRAINING": "draining",
            "QUARANTINED": "quarantined",
            "HEALTHY": "recovered",
            "TERMINATED": "quarantined",
        }[effective_state]
        if previous == effective_state:
            event_type = "canary_passed" if semantic_status == "healthy" else "canary_failed"
        evidence = {
            "claimed_state": state,
            "effective_state": effective_state,
            "infrastructure_status": infrastructure_status,
            "semantic_status": semantic_status,
            "metrics": dict(metrics),
        }
        event = SemanticHealthEvent(
            tenant_id=tenant_id,
            worker_health_id=row.id,
            event_type=event_type,
            previous_state=previous,
            current_state=effective_state,
            semantic_score=semantic_score,
            reason_codes=reason_values,
            impacted_attempt_ids=impacted_values,
            evidence=evidence,
            evidence_sha256=canonical_sha256(evidence),
            occurred_at=timestamp,
        )
        session.add(event)
    await session.flush()
    return row, event
