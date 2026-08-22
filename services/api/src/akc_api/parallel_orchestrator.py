"""Atomic durable adapter for the Structara v6 parallel runtime domain core.

The pure ``akc_parallel_runtime`` package decides what should happen.  This
module persists that decision without weakening it: every public mutation uses
the caller's :class:`~sqlalchemy.ext.asyncio.AsyncSession`, a savepoint, tenant
and document scoping, content-bound event replay, and flush-only semantics.

No method commits.  A caller can compose several mutations in one outer
transaction and either commit all state, evidence, billing, and events, or roll
all of them back together.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from akc_parallel_runtime import (
    ACCEPTED_VERIFICATION_STATES,
    ArbitrationBasis,
    AttemptKind,
    AttemptOutput,
    ContinuityMergeResult,
    FinalizationResult,
    HealthTransition,
    ShardPlan,
    ValidationLevel,
    ValidationPolicy,
    ValidationResult,
    VerificationState,
    WorkerState,
    require_sha256,
)
from akc_parallel_runtime import (
    ArbitrationDecision as CoreArbitrationDecision,
)
from akc_parallel_runtime import (
    RecoveryDecision as CoreRecoveryDecision,
)
from akc_parallel_runtime import (
    RecoveryTask as CoreRecoveryTask,
)
from akc_parallel_runtime import (
    canonical_json as runtime_canonical_json,
)
from akc_parallel_runtime import (
    canonical_sha256 as runtime_canonical_sha256,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    Collection,
    CollectionEvent,
    CreditLedger,
    Document,
    GpuProviderInvocation,
    ProcessingJob,
    utcnow,
)
from akc_api.parallel_models import (
    AcceptedBlock,
    AcceptedBlockInvalidation,
    AttemptValidation,
    ContinuityEdge,
    ParallelParseAttempt,
    ParallelParseShard,
    RecoveryTask,
    SemanticHealthEvent,
    WorkerHealth,
)
from akc_api.parallel_models import (
    ArbitrationDecision as DurableArbitrationDecision,
)
from akc_api.parallel_runtime_store import (
    ParallelRuntimeConflict,
    accept_verified_block,
    canonical_sha256,
    create_parse_attempt,
    create_parse_shard,
    emit_parallel_event,
    record_attempt_output,
    record_attempt_validation,
    request_recovery,
    transition_parse_attempt,
    update_worker_health,
)
from akc_api.services import credit_entry

_CREDIT_QUANTUM = Decimal("0.000001")
_SUPPORTED_ATTEMPT_KINDS = frozenset(
    {"primary", "retry", "hedge", "straggler", "recovery", "shadow"}
)
_TERMINAL_ATTEMPT_STATES = frozenset(
    {
        "ACCEPTED",
        "REJECTED",
        "RETRYABLE_FAILED",
        "TERMINAL_FAILED",
        "SUPERSEDED",
        "QUARANTINED",
    }
)
_OUTPUT_ENVELOPE_SCHEMA = "parallel-v6-output-admission-1.0"
_VERIFICATION_ENVELOPE_SCHEMA = "parallel-v6-verification-1.0"
_ENVELOPE_ISSUER = "akc-api"
_OUTPUT_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "issuer",
        "tenant_id",
        "collection_id",
        "processing_job_id",
        "document_id",
        "document_version_id",
        "shard_id",
        "attempt_id",
        "expected_input_sha256",
        "expected_shard_input_sha256",
        "expected_request_sha256",
        "expected_output_object_key",
        "expected_model_revision",
        "expected_runtime_image_digest",
        "expected_adapter_version",
    }
)
_VERIFICATION_ENVELOPE_BASE_FIELDS = frozenset(
    {
        "schema_version",
        "issuer",
        "tenant_id",
        "collection_id",
        "processing_job_id",
        "document_id",
        "document_version_id",
        "shard_id",
        "attempt_id",
        "provider_invocation_id",
        "output_envelope_sha256",
        "result_manifest_sha256",
        "output_sha256",
        "operation_prefix",
        "required_validation_levels",
        "validator_revisions",
        "arbitration_policy_version",
        "validation_digest",
        "arbitration_decision_sha256",
        "selected_attempt_id",
        "logical_block_key",
        "credit_amount",
    }
)
_VERIFICATION_ENVELOPE_FIELDS = _VERIFICATION_ENVELOPE_BASE_FIELDS | {
    "envelope_sha256",
    "signature_sha256",
}
_MAX_GPU_SECONDS = Decimal("604800")
_MAX_PROVIDER_COST_USD = Decimal("1000000")
_AUTONOMOUS_PIPELINE_CHECKPOINT_KEY = "parallel_v6_autonomous_pipeline"
_RECOVERY_PROJECTION_KEY = "parallel_v6_recovery"
_RECOVERY_PROJECTION_SCHEMA = "parallel-v6-recovery-projection-1.0"


@dataclass(frozen=True, slots=True)
class ParallelRuntimeScope:
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    document_id: uuid.UUID
    processing_job_id: uuid.UUID | None = None
    document_version_id: str | None = None

    def __post_init__(self) -> None:
        if (self.processing_job_id is None) != (self.document_version_id is None):
            raise ValueError("processing_job_id and document_version_id must be supplied together")
        if self.document_version_id is not None and (
            not self.document_version_id
            or len(self.document_version_id) > 160
            or any(character.isspace() for character in self.document_version_id)
        ):
            raise ValueError("document_version_id is outside the durable identity contract")


@dataclass(frozen=True, slots=True)
class ValidatorRevision:
    validator_key: str
    validator_revision: str

    def __post_init__(self) -> None:
        if not self.validator_key or not self.validator_revision:
            raise ValueError("validator identity and revision are required")
        if len(self.validator_key) > 120 or len(self.validator_revision) > 160:
            raise ValueError("validator identity is outside its persistence bound")


@dataclass(frozen=True, slots=True)
class DurableWrite[T]:
    row: T
    event: CollectionEvent | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class PlannedShardWrite:
    core_shard_id: str
    row: ParallelParseShard
    event: CollectionEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class PlanWrite:
    shards: tuple[PlannedShardWrite, ...]

    @property
    def replayed(self) -> bool:
        return all(item.replayed for item in self.shards)


@dataclass(frozen=True, slots=True)
class ValidationWrite:
    rows: tuple[AttemptValidation, ...]
    failure_events: tuple[CollectionEvent, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class AcceptanceWrite:
    block: AcceptedBlock
    ledger: CreditLedger
    event: CollectionEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class WorkerHealthWrite:
    worker: WorkerHealth
    semantic_event: SemanticHealthEvent
    event: CollectionEvent
    replayed: bool
    invalidations: tuple[AcceptedBlockInvalidation, ...] = ()
    refund_ledgers: tuple[CreditLedger, ...] = ()
    recovery_tasks: tuple[RecoveryTask, ...] = ()
    recovery_events: tuple[CollectionEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class ParallelV6OutputEnvelope:
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    processing_job_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: str
    shard_id: uuid.UUID
    attempt_id: uuid.UUID
    expected_input_sha256: str
    expected_shard_input_sha256: str
    expected_request_sha256: str
    expected_output_object_key: str
    expected_model_revision: str
    expected_runtime_image_digest: str
    expected_adapter_version: str


@dataclass(frozen=True, slots=True)
class ParallelV6VerificationEnvelope:
    tenant_id: uuid.UUID
    collection_id: uuid.UUID
    document_id: uuid.UUID
    processing_job_id: uuid.UUID
    shard_id: uuid.UUID
    attempt_id: uuid.UUID
    provider_invocation_id: uuid.UUID
    document_version_id: str
    output_envelope_sha256: str
    result_manifest_sha256: str
    output_sha256: str
    operation_prefix: str
    required_levels: frozenset[ValidationLevel]
    validator_revisions: Mapping[ValidationLevel, ValidatorRevision]
    arbitration_policy_version: str
    validation_digest: str
    arbitration_decision_sha256: str
    selected_attempt_id: uuid.UUID | None
    logical_block_key: str | None
    credit_amount: Decimal
    envelope_sha256: str
    signature_sha256: str


@dataclass(frozen=True, slots=True)
class GpuAdmissionWrite:
    attempt: ParallelParseAttempt
    validation: ValidationWrite
    arbitration: DurableArbitrationDecision
    acceptance: AcceptanceWrite | None
    rejection: DurableWrite[ParallelParseAttempt] | None

    @property
    def accepted(self) -> bool:
        return self.acceptance is not None


@dataclass(frozen=True, slots=True)
class ContinuityEdgeInput:
    source_shard_id: uuid.UUID
    target_shard_id: uuid.UUID
    edge_type: str
    confidence: Decimal
    authority: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ContinuityWrite:
    edges: tuple[ContinuityEdge, ...]
    event: CollectionEvent
    replayed: bool


def _operation_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError("operation_key must be non-empty and at most 500 characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("operation_key cannot contain control characters")
    return normalized


def _logical_unit_key(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or normalized != value
        or len(normalized) > 200
        or any(character.isspace() for character in normalized)
    ):
        raise ParallelRuntimeConflict("logical unit key is outside the durable contract")
    return normalized


def _store_key(namespace: str, operation_key: str, *parts: object) -> str:
    return f"{namespace}:{canonical_sha256({'key': _operation_key(operation_key), 'parts': parts})}"


def _uuid_string(value: str, *, field: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ParallelRuntimeConflict(f"{field} must reference a durable UUID") from exc
    if str(parsed) != value:
        raise ParallelRuntimeConflict(f"{field} must use canonical UUID form")
    return parsed


def _decimal_string(value: Decimal) -> str:
    bounded = Decimal(value)
    if not bounded.is_finite() or bounded < 0:
        raise ValueError("event decimals must be finite and nonnegative")
    quantized = bounded.quantize(_CREDIT_QUANTUM)
    if quantized != bounded:
        raise ValueError("event decimals support at most six fractional places")
    rendered = format(quantized, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _reserved_merge(
    supplied: Mapping[str, Any],
    reserved: Mapping[str, Any],
) -> dict[str, Any]:
    overlap = supplied.keys() & reserved.keys()
    if overlap:
        raise ParallelRuntimeConflict(
            f"caller metadata cannot replace durable fields: {sorted(overlap)}"
        )
    return {**dict(supplied), **dict(reserved)}


def _envelope_mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ParallelRuntimeConflict(f"{field} must be an exact JSON object")
    return value


def _envelope_uuid(value: object, *, field: str) -> uuid.UUID:
    if not isinstance(value, str):
        raise ParallelRuntimeConflict(f"{field} must be a canonical UUID string")
    return _uuid_string(value, field=field)


def _envelope_string(
    value: object,
    *,
    field: str,
    maximum: int,
    allow_space: bool = True,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
        or (not allow_space and any(character.isspace() for character in value))
    ):
        raise ParallelRuntimeConflict(f"{field} must be a bounded string")
    return value


def _envelope_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ParallelRuntimeConflict(f"{field} must be a lowercase SHA-256")
    try:
        return require_sha256(value, field_name=field)
    except ValueError as exc:
        raise ParallelRuntimeConflict(str(exc)) from exc


def _parallel_v6_signing_key(signing_key: bytes) -> bytes:
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError("parallel v6 signing key must contain at least 32 bytes")
    return signing_key


def sign_parallel_v6_verification(
    payload: Mapping[str, Any],
    *,
    signing_key: bytes,
) -> dict[str, Any]:
    """Content-bind a server-authored verification and arbitration envelope."""

    body = dict(payload)
    if set(body) != _VERIFICATION_ENVELOPE_BASE_FIELDS:
        raise ValueError("parallel_v6_verification has missing or unknown fields")
    if (
        body.get("schema_version") != _VERIFICATION_ENVELOPE_SCHEMA
        or body.get("issuer") != _ENVELOPE_ISSUER
    ):
        raise ValueError("parallel_v6_verification has an unsupported issuer or schema")
    key = _parallel_v6_signing_key(signing_key)
    envelope_sha256 = runtime_canonical_sha256(body)
    signed = {**body, "envelope_sha256": envelope_sha256}
    signature_sha256 = hmac.new(
        key,
        runtime_canonical_json(signed).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {**signed, "signature_sha256": signature_sha256}


def _parse_parallel_v6_output_envelope(value: object) -> ParallelV6OutputEnvelope:
    body = _envelope_mapping(value, field="parallel_v6")
    if set(body) != _OUTPUT_ENVELOPE_FIELDS:
        raise ParallelRuntimeConflict("parallel_v6 has missing or unknown fields")
    if (
        body.get("schema_version") != _OUTPUT_ENVELOPE_SCHEMA
        or body.get("issuer") != _ENVELOPE_ISSUER
    ):
        raise ParallelRuntimeConflict("parallel_v6 has an unsupported issuer or schema")
    return ParallelV6OutputEnvelope(
        tenant_id=_envelope_uuid(body["tenant_id"], field="parallel_v6.tenant_id"),
        collection_id=_envelope_uuid(body["collection_id"], field="parallel_v6.collection_id"),
        processing_job_id=_envelope_uuid(
            body["processing_job_id"], field="parallel_v6.processing_job_id"
        ),
        document_id=_envelope_uuid(body["document_id"], field="parallel_v6.document_id"),
        document_version_id=_envelope_string(
            body["document_version_id"],
            field="parallel_v6.document_version_id",
            maximum=160,
        ),
        shard_id=_envelope_uuid(body["shard_id"], field="parallel_v6.shard_id"),
        attempt_id=_envelope_uuid(body["attempt_id"], field="parallel_v6.attempt_id"),
        expected_input_sha256=_envelope_sha256(
            body["expected_input_sha256"],
            field="parallel_v6.expected_input_sha256",
        ),
        expected_shard_input_sha256=_envelope_sha256(
            body["expected_shard_input_sha256"],
            field="parallel_v6.expected_shard_input_sha256",
        ),
        expected_request_sha256=_envelope_sha256(
            body["expected_request_sha256"],
            field="parallel_v6.expected_request_sha256",
        ),
        expected_output_object_key=_envelope_string(
            body["expected_output_object_key"],
            field="parallel_v6.expected_output_object_key",
            maximum=500,
        ),
        expected_model_revision=_envelope_string(
            body["expected_model_revision"],
            field="parallel_v6.expected_model_revision",
            maximum=160,
        ),
        expected_runtime_image_digest=_envelope_string(
            body["expected_runtime_image_digest"],
            field="parallel_v6.expected_runtime_image_digest",
            maximum=160,
        ),
        expected_adapter_version=_envelope_string(
            body["expected_adapter_version"],
            field="parallel_v6.expected_adapter_version",
            maximum=160,
        ),
    )


def _verification_credit(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ParallelRuntimeConflict("parallel_v6_verification.credit_amount must be a string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ParallelRuntimeConflict("parallel_v6_verification.credit_amount is invalid") from exc
    if (
        not parsed.is_finite()
        or parsed < 0
        or parsed.quantize(_CREDIT_QUANTUM) != parsed
        or _decimal_string(parsed) != value
    ):
        raise ParallelRuntimeConflict("parallel_v6_verification.credit_amount is not canonical")
    return parsed


def _parse_parallel_v6_verification_envelope(
    value: object,
    *,
    signing_key: bytes,
) -> ParallelV6VerificationEnvelope:
    body = _envelope_mapping(value, field="parallel_v6_verification")
    if set(body) != _VERIFICATION_ENVELOPE_FIELDS:
        raise ParallelRuntimeConflict("parallel_v6_verification has missing or unknown fields")
    if (
        body.get("schema_version") != _VERIFICATION_ENVELOPE_SCHEMA
        or body.get("issuer") != _ENVELOPE_ISSUER
    ):
        raise ParallelRuntimeConflict(
            "parallel_v6_verification has an unsupported issuer or schema"
        )
    envelope_sha256 = _envelope_sha256(
        body["envelope_sha256"],
        field="parallel_v6_verification.envelope_sha256",
    )
    signature_sha256 = _envelope_sha256(
        body["signature_sha256"],
        field="parallel_v6_verification.signature_sha256",
    )
    unsigned = {key: body[key] for key in _VERIFICATION_ENVELOPE_BASE_FIELDS}
    try:
        actual_envelope_sha256 = runtime_canonical_sha256(unsigned)
        expected_signature = hmac.new(
            _parallel_v6_signing_key(signing_key),
            runtime_canonical_json({**unsigned, "envelope_sha256": envelope_sha256}).encode(
                "utf-8"
            ),
            hashlib.sha256,
        ).hexdigest()
    except ValueError as exc:
        raise ParallelRuntimeConflict(
            "parallel_v6_verification is not canonically encodable"
        ) from exc
    if actual_envelope_sha256 != envelope_sha256 or not hmac.compare_digest(
        expected_signature, signature_sha256
    ):
        raise ParallelRuntimeConflict("parallel_v6_verification signature is invalid")

    raw_levels = body["required_validation_levels"]
    if (
        not isinstance(raw_levels, list)
        or any(
            not isinstance(level, int) or isinstance(level, bool) or level < 0 or level > 6
            for level in raw_levels
        )
        or raw_levels != sorted(set(raw_levels))
    ):
        raise ParallelRuntimeConflict("parallel_v6_verification validation levels are invalid")
    levels = frozenset(ValidationLevel(level) for level in raw_levels)
    if not {ValidationLevel.TRANSPORT, ValidationLevel.STRUCTURAL} <= levels:
        raise ParallelRuntimeConflict("parallel_v6_verification omits mandatory L0-L1")

    raw_revisions = _envelope_mapping(
        body["validator_revisions"],
        field="parallel_v6_verification.validator_revisions",
    )
    if set(raw_revisions) != {str(int(level)) for level in ValidationLevel}:
        raise ParallelRuntimeConflict("parallel_v6_verification must bind all L0-L6 validators")
    revisions: dict[ValidationLevel, ValidatorRevision] = {}
    for level in ValidationLevel:
        raw_revision = _envelope_mapping(
            raw_revisions[str(int(level))],
            field=f"parallel_v6_verification.validator_revisions.{int(level)}",
        )
        if set(raw_revision) != {"validator_key", "validator_revision"}:
            raise ParallelRuntimeConflict("validator revision has unknown fields")
        revisions[level] = ValidatorRevision(
            _envelope_string(
                raw_revision["validator_key"],
                field="validator_key",
                maximum=120,
                allow_space=False,
            ),
            _envelope_string(
                raw_revision["validator_revision"],
                field="validator_revision",
                maximum=160,
                allow_space=False,
            ),
        )

    selected_value = body["selected_attempt_id"]
    selected_attempt_id = (
        None
        if selected_value is None
        else _envelope_uuid(
            selected_value,
            field="parallel_v6_verification.selected_attempt_id",
        )
    )
    logical_value = body["logical_block_key"]
    logical_block_key = (
        None
        if logical_value is None
        else _envelope_string(
            logical_value,
            field="parallel_v6_verification.logical_block_key",
            maximum=200,
            allow_space=False,
        )
    )
    operation_prefix = _envelope_string(
        body["operation_prefix"],
        field="parallel_v6_verification.operation_prefix",
        maximum=400,
    )
    if _operation_key(operation_prefix) != operation_prefix:
        raise ParallelRuntimeConflict("parallel_v6_verification operation prefix is ambiguous")
    return ParallelV6VerificationEnvelope(
        tenant_id=_envelope_uuid(body["tenant_id"], field="parallel_v6_verification.tenant_id"),
        collection_id=_envelope_uuid(
            body["collection_id"], field="parallel_v6_verification.collection_id"
        ),
        document_id=_envelope_uuid(
            body["document_id"], field="parallel_v6_verification.document_id"
        ),
        processing_job_id=_envelope_uuid(
            body["processing_job_id"],
            field="parallel_v6_verification.processing_job_id",
        ),
        shard_id=_envelope_uuid(body["shard_id"], field="parallel_v6_verification.shard_id"),
        attempt_id=_envelope_uuid(body["attempt_id"], field="parallel_v6_verification.attempt_id"),
        provider_invocation_id=_envelope_uuid(
            body["provider_invocation_id"],
            field="parallel_v6_verification.provider_invocation_id",
        ),
        document_version_id=_envelope_string(
            body["document_version_id"],
            field="parallel_v6_verification.document_version_id",
            maximum=160,
        ),
        output_envelope_sha256=_envelope_sha256(
            body["output_envelope_sha256"],
            field="parallel_v6_verification.output_envelope_sha256",
        ),
        result_manifest_sha256=_envelope_sha256(
            body["result_manifest_sha256"],
            field="parallel_v6_verification.result_manifest_sha256",
        ),
        output_sha256=_envelope_sha256(
            body["output_sha256"], field="parallel_v6_verification.output_sha256"
        ),
        operation_prefix=operation_prefix,
        required_levels=levels,
        validator_revisions=revisions,
        arbitration_policy_version=_envelope_string(
            body["arbitration_policy_version"],
            field="parallel_v6_verification.arbitration_policy_version",
            maximum=120,
            allow_space=False,
        ),
        validation_digest=_envelope_sha256(
            body["validation_digest"],
            field="parallel_v6_verification.validation_digest",
        ),
        arbitration_decision_sha256=_envelope_sha256(
            body["arbitration_decision_sha256"],
            field="parallel_v6_verification.arbitration_decision_sha256",
        ),
        selected_attempt_id=selected_attempt_id,
        logical_block_key=logical_block_key,
        credit_amount=_verification_credit(body["credit_amount"]),
        envelope_sha256=envelope_sha256,
        signature_sha256=signature_sha256,
    )


def _manifest_metric(
    metrics: Mapping[str, Any],
    key: str,
    *,
    maximum: Decimal,
) -> Decimal:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ParallelRuntimeConflict(f"result manifest metric {key} is invalid")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ParallelRuntimeConflict(f"result manifest metric {key} is invalid") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > maximum:
        raise ParallelRuntimeConflict(f"result manifest metric {key} is outside bounds")
    if key == "estimated_cost_usd" and parsed.quantize(Decimal("0.00000001")) != parsed:
        raise ParallelRuntimeConflict("result manifest provider cost exceeds precision")
    return parsed


class DurableParallelOrchestrator:
    """Tenant-safe, content-addressed persistence boundary for v6 decisions."""

    def __init__(self, session: AsyncSession, scope: ParallelRuntimeScope) -> None:
        self.session = session
        self.scope = scope

    def _require_execution_scope(self) -> tuple[uuid.UUID, str]:
        if self.scope.processing_job_id is None or self.scope.document_version_id is None:
            raise ParallelRuntimeConflict(
                "parallel v6 mutations require processing job and document version scope"
            )
        return self.scope.processing_job_id, self.scope.document_version_id

    async def _assert_scope(self) -> tuple[Collection, Document, ProcessingJob | None]:
        collection = await self.session.scalar(
            select(Collection)
            .where(
                Collection.tenant_id == self.scope.tenant_id,
                Collection.id == self.scope.collection_id,
            )
            .with_for_update()
        )
        document = await self.session.scalar(
            select(Document)
            .where(
                Document.tenant_id == self.scope.tenant_id,
                Document.id == self.scope.document_id,
            )
            .with_for_update()
        )
        if collection is None or document is None or collection.project_id != document.project_id:
            raise ParallelRuntimeConflict("collection and document do not share the tenant project")
        job: ProcessingJob | None = None
        if self.scope.processing_job_id is not None:
            job = await self.session.scalar(
                select(ProcessingJob)
                .where(
                    ProcessingJob.tenant_id == self.scope.tenant_id,
                    ProcessingJob.id == self.scope.processing_job_id,
                )
                .with_for_update()
            )
            if (
                job is None
                or job.project_id != document.project_id
                or (job.document_id is not None and job.document_id != document.id)
            ):
                raise ParallelRuntimeConflict("processing job is outside the durable scope")
        return collection, document, job

    async def _load_shard(self, shard_id: uuid.UUID) -> ParallelParseShard:
        processing_job_id, document_version_id = self._require_execution_scope()
        shard = await self.session.scalar(
            select(ParallelParseShard)
            .where(
                ParallelParseShard.tenant_id == self.scope.tenant_id,
                ParallelParseShard.id == shard_id,
                ParallelParseShard.document_id == self.scope.document_id,
                ParallelParseShard.collection_id == self.scope.collection_id,
                ParallelParseShard.processing_job_id == processing_job_id,
                ParallelParseShard.document_version_id == document_version_id,
            )
            .with_for_update()
        )
        if shard is None:
            raise ParallelRuntimeConflict("parse shard is outside the durable scope")
        return shard

    async def _load_attempt(
        self, attempt_id: uuid.UUID
    ) -> tuple[ParallelParseAttempt, ParallelParseShard]:
        attempt = await self.session.scalar(
            select(ParallelParseAttempt)
            .where(
                ParallelParseAttempt.tenant_id == self.scope.tenant_id,
                ParallelParseAttempt.id == attempt_id,
            )
            .with_for_update()
        )
        if attempt is None:
            raise ParallelRuntimeConflict("parse attempt is outside the tenant")
        shard = await self._load_shard(attempt.shard_id)
        return attempt, shard

    @staticmethod
    def _event_payload(
        event_type: str,
        operation_key: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        base = dict(payload)
        return {
            **base,
            "operation_sha256": canonical_sha256(
                {"event_type": event_type, "operation_key": _operation_key(operation_key)}
            ),
            "content_sha256": canonical_sha256(base),
        }

    async def _existing_event(
        self,
        *,
        event_type: str,
        operation_key: str,
        payload: Mapping[str, Any],
    ) -> CollectionEvent | None:
        expected = self._event_payload(event_type, operation_key, payload)
        operation_sha256 = expected["operation_sha256"]
        candidates = list(
            (
                await self.session.scalars(
                    select(CollectionEvent).where(
                        CollectionEvent.tenant_id == self.scope.tenant_id,
                        CollectionEvent.collection_id == self.scope.collection_id,
                        CollectionEvent.event_type == event_type,
                    )
                )
            ).all()
        )
        matching = [
            event
            for event in candidates
            if isinstance(event.payload, dict)
            and event.payload.get("operation_sha256") == operation_sha256
        ]
        if len(matching) > 1:
            raise ParallelRuntimeConflict("duplicate durable event operation identity")
        if not matching:
            return None
        event = matching[0]
        if canonical_sha256(event.payload) != canonical_sha256(expected):
            raise ParallelRuntimeConflict("event operation key was reused with different content")
        return event

    async def _emit_once(
        self,
        *,
        event_type: str,
        operation_key: str,
        payload: Mapping[str, Any],
    ) -> tuple[CollectionEvent, bool]:
        existing = await self._existing_event(
            event_type=event_type,
            operation_key=operation_key,
            payload=payload,
        )
        if existing is not None:
            return existing, True
        event = await emit_parallel_event(
            self.session,
            tenant_id=self.scope.tenant_id,
            collection_id=self.scope.collection_id,
            job_id=self.scope.processing_job_id,
            event_type=event_type,
            payload=self._event_payload(event_type, operation_key, payload),
        )
        return event, False

    @staticmethod
    def _required_levels(shard: ParallelParseShard) -> frozenset[ValidationLevel]:
        configured = shard.context.get("required_validation_levels")
        if not isinstance(configured, list):
            raise ParallelRuntimeConflict("persisted shard validation policy is malformed")
        try:
            levels = frozenset(ValidationLevel(level) for level in configured)
        except (ValueError, TypeError) as exc:
            raise ParallelRuntimeConflict(
                "persisted shard validation levels are malformed"
            ) from exc
        return levels | {ValidationLevel.TRANSPORT, ValidationLevel.STRUCTURAL}

    @staticmethod
    def _pinned_validator(
        shard: ParallelParseShard, level: ValidationLevel
    ) -> ValidatorRevision | None:
        configured = shard.context.get("required_validator_revisions")
        if not isinstance(configured, dict):
            raise ParallelRuntimeConflict("persisted validator revisions are malformed")
        value = configured.get(str(int(level)))
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ParallelRuntimeConflict("persisted validator revision is malformed")
        key = value.get("validator_key")
        revision = value.get("validator_revision")
        if not isinstance(key, str) or not isinstance(revision, str):
            raise ParallelRuntimeConflict("persisted validator identity is malformed")
        return ValidatorRevision(key, revision)

    async def persist_plan(
        self,
        plan: ShardPlan,
        *,
        page_number_by_id: Mapping[str, int],
        required_levels: frozenset[ValidationLevel],
        validator_revisions: Mapping[ValidationLevel, ValidatorRevision],
        operation_key: str,
    ) -> PlanWrite:
        """Persist a deterministic plan and one planned event per shard."""

        async with self.session.begin_nested():
            await self._assert_scope()
            processing_job_id, document_version_id = self._require_execution_scope()
            if plan.document_id != str(self.scope.document_id):
                raise ParallelRuntimeConflict("core shard plan targets a different document")
            if plan.document_version_id != document_version_id:
                raise ParallelRuntimeConflict(
                    "core shard plan targets a different document version"
                )
            require_sha256(plan.source_sha256, field_name="plan.source_sha256")
            normalized_required = required_levels | {
                ValidationLevel.TRANSPORT,
                ValidationLevel.STRUCTURAL,
            }
            if set(validator_revisions) != set(ValidationLevel):
                raise ParallelRuntimeConflict("all L0-L6 validator revisions must be pinned")
            expected_page_ids = {
                page_id for shard in plan.shards for page_id in shard.input_page_ids
            }
            if expected_page_ids - page_number_by_id.keys():
                raise ParallelRuntimeConflict("page number map does not cover every shard input")
            writes: list[PlannedShardWrite] = []
            required_revision_payload = {
                str(int(level)): {
                    "validator_key": validator_revisions[level].validator_key,
                    "validator_revision": validator_revisions[level].validator_revision,
                }
                for level in sorted(normalized_required, key=int)
            }
            for core_shard in plan.shards:
                primary_numbers = tuple(
                    page_number_by_id[item] for item in core_shard.primary_page_ids
                )
                if not primary_numbers or any(number < 1 for number in primary_numbers):
                    raise ParallelRuntimeConflict("primary page numbers must be positive")
                ordered_primary = tuple(sorted(primary_numbers))
                if ordered_primary != tuple(range(ordered_primary[0], ordered_primary[-1] + 1)):
                    raise ParallelRuntimeConflict("a durable page-group shard must be contiguous")
                context = {
                    "core_shard_id": core_shard.shard_id,
                    "document_version_id": plan.document_version_id,
                    "source_sha256": plan.source_sha256,
                    "expected_seconds": core_shard.expected_seconds,
                    "required_worker_class": core_shard.required_worker_class,
                    "required_validation_levels": [
                        int(level) for level in sorted(normalized_required, key=int)
                    ],
                    "required_validator_revisions": required_revision_payload,
                    "native_comparison_required": ValidationLevel.NATIVE in normalized_required,
                    "authority_required": ValidationLevel.AUTHORITY in normalized_required,
                    "differential_required": ValidationLevel.DIFFERENTIAL in normalized_required,
                    "multimodal_required": ValidationLevel.MULTIMODAL in normalized_required,
                    "downstream_required": ValidationLevel.DOWNSTREAM in normalized_required,
                }
                overlap = {
                    "context_page_ids": list(core_shard.context_page_ids),
                    "ordered_input_page_ids": list(core_shard.ordered_input_page_ids),
                }
                ownership = {
                    "primary_page_ids": list(core_shard.primary_page_ids),
                    "context_only_page_ids": list(core_shard.context_page_ids),
                }
                input_sha256 = runtime_canonical_sha256(
                    {
                        "source_sha256": plan.source_sha256,
                        "core_shard": core_shard,
                        "context": context,
                        "overlap": overlap,
                        "ownership": ownership,
                    }
                )
                row, row_replayed = await create_parse_shard(
                    self.session,
                    tenant_id=self.scope.tenant_id,
                    collection_id=self.scope.collection_id,
                    document_id=self.scope.document_id,
                    processing_job_id=processing_job_id,
                    document_version_id=document_version_id,
                    parent_shard_id=None,
                    shard_key=core_shard.shard_id,
                    shard_kind=("page" if len(primary_numbers) == 1 else "page_group"),
                    ordinal=core_shard.ordinal,
                    page_start=min(primary_numbers),
                    page_end=max(primary_numbers),
                    region={},
                    context=context,
                    overlap=overlap,
                    ownership=ownership,
                    route_class=core_shard.required_worker_class,
                    priority=50,
                    size_units=len(primary_numbers),
                    plan_version=plan.policy_version,
                    input_sha256=input_sha256,
                    dispatch_idempotency_key=_store_key("plan", operation_key, core_shard.shard_id),
                )
                if (
                    row.collection_id != self.scope.collection_id
                    or row.processing_job_id != processing_job_id
                    or row.document_version_id != document_version_id
                    or row.priority != 50
                    or row.size_units != len(primary_numbers)
                ):
                    raise ParallelRuntimeConflict(
                        "replayed shard differs from durable plan metadata"
                    )
                event_payload = {
                    "collection_id": str(self.scope.collection_id),
                    "document_id": str(self.scope.document_id),
                    "shard_id": str(row.id),
                    "shard_kind": row.shard_kind,
                    "page_start": row.page_start,
                    "page_end": row.page_end,
                    "route_class": row.route_class,
                    "shard_state": "PLANNED",
                }
                event, event_replayed = await self._emit_once(
                    event_type="shard.planned.v1",
                    operation_key=f"{_operation_key(operation_key)}:{core_shard.shard_id}",
                    payload=event_payload,
                )
                writes.append(
                    PlannedShardWrite(
                        core_shard_id=core_shard.shard_id,
                        row=row,
                        event=event,
                        replayed=row_replayed and event_replayed,
                    )
                )
            await self.session.flush()
            return PlanWrite(tuple(writes))

    async def dispatch(
        self,
        shard_id: uuid.UUID,
        *,
        attempt_kind: AttemptKind,
        pool_key: str,
        model_id: str,
        model_revision: str,
        runtime_identity: str,
        route_policy_version: str,
        request_sha256: str,
        operation_key: str,
        parent_attempt_id: uuid.UUID | None = None,
        provider_invocation_id: uuid.UUID | None = None,
    ) -> DurableWrite[ParallelParseAttempt]:
        """Create an immutable attempt child and atomically dispatch its shard."""

        async with self.session.begin_nested():
            await self._assert_scope()
            shard = await self._load_shard(shard_id)
            kind = attempt_kind.value
            if kind not in _SUPPORTED_ATTEMPT_KINDS:
                raise ParallelRuntimeConflict(f"attempt kind is not durable: {kind}")
            if parent_attempt_id is not None:
                parent, _ = await self._load_attempt(parent_attempt_id)
                if parent.shard_id != shard.id:
                    raise ParallelRuntimeConflict("attempt child must remain on its parent shard")
            attempt, attempt_replayed = await create_parse_attempt(
                self.session,
                tenant_id=self.scope.tenant_id,
                shard_id=shard.id,
                attempt_kind=kind,
                pool_key=pool_key,
                model_id=model_id,
                model_revision=model_revision,
                runtime_identity=runtime_identity,
                route_policy_version=route_policy_version,
                idempotency_key=_store_key("dispatch", operation_key),
                request_sha256=request_sha256,
                parent_attempt_id=parent_attempt_id,
                provider_invocation_id=provider_invocation_id,
            )
            if attempt.state == "CREATED":
                await transition_parse_attempt(self.session, attempt, "QUEUED")
            elif attempt.state not in {
                "QUEUED",
                "RUNNING",
                "OUTPUT_RECEIVED",
                "VALIDATING",
                *_TERMINAL_ATTEMPT_STATES,
            }:
                raise ParallelRuntimeConflict("replayed attempt has an invalid durable state")
            if shard.status in {"PLANNED", "QUEUED", "RECOVERY_PENDING"}:
                shard.status = "DISPATCHED"
                shard.updated_at = utcnow()
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "pool_key": attempt.pool_key,
                "route_class": shard.route_class,
                "shard_state": "DISPATCHED",
            }
            event, event_replayed = await self._emit_once(
                event_type="shard.dispatched.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(attempt, event, attempt_replayed and event_replayed)

    async def start(
        self,
        attempt_id: uuid.UUID,
        *,
        worker_id: str,
        operation_key: str,
    ) -> DurableWrite[ParallelParseAttempt]:
        """Bind one worker identity and start an already queued attempt."""

        async with self.session.begin_nested():
            await self._assert_scope()
            attempt, shard = await self._load_attempt(attempt_id)
            if attempt.worker_id is not None and attempt.worker_id != worker_id:
                raise ParallelRuntimeConflict("attempt cannot move to a different worker")
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "attempt_kind": attempt.attempt_kind,
                "pool_key": attempt.pool_key,
                "model_id": attempt.model_id,
                "attempt_state": "RUNNING",
                "worker_id": worker_id,
            }
            existing_event = await self._existing_event(
                event_type="attempt.started.v1",
                operation_key=operation_key,
                payload=payload,
            )
            if existing_event is not None:
                if attempt.worker_id != worker_id or attempt.started_at is None:
                    raise ParallelRuntimeConflict("started event lost its attempt projection")
                return DurableWrite(attempt, existing_event, True)
            if attempt.state != "QUEUED":
                raise ParallelRuntimeConflict("only a queued attempt can start")
            attempt.worker_id = worker_id
            await transition_parse_attempt(self.session, attempt, "RUNNING")
            shard.status = "RUNNING"
            shard.updated_at = utcnow()
            event, _ = await self._emit_once(
                event_type="attempt.started.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(attempt, event, False)

    async def receive_output(
        self,
        attempt_id: uuid.UUID,
        output: AttemptOutput,
        *,
        output_summary: Mapping[str, Any],
        operation_key: str,
    ) -> DurableWrite[ParallelParseAttempt]:
        """Persist immutable provider output and its usage telemetry."""

        async with self.session.begin_nested():
            await self._assert_scope()
            attempt, shard = await self._load_attempt(attempt_id)
            gpu_milliseconds = int(
                (output.cost.gpu_seconds * Decimal("1000")).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )
            summary = _reserved_merge(
                output_summary,
                {
                    "duplicate_compute": output.cost.duplicate_compute,
                    "user_credits_candidate": _decimal_string(output.cost.user_credits),
                },
            )
            if attempt.output_sha256 is not None and (
                attempt.output_sha256 != output.prediction_sha256
                or attempt.output_artifact_key != output.prediction_uri
                or attempt.output_summary != summary
                or attempt.gpu_milliseconds != gpu_milliseconds
                or Decimal(attempt.cost_usd) != output.cost.provider_cost
            ):
                raise ParallelRuntimeConflict("output replay differs in content or usage")
            await record_attempt_output(
                self.session,
                attempt,
                artifact_key=output.prediction_uri,
                output_sha256=output.prediction_sha256,
                output_summary=summary,
                gpu_milliseconds=gpu_milliseconds,
                cost_usd=output.cost.provider_cost,
                now=output.completed_at,
            )
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "output_sha256": output.prediction_sha256,
                "gpu_milliseconds": gpu_milliseconds,
                "attempt_state": "OUTPUT_RECEIVED",
            }
            event, event_replayed = await self._emit_once(
                event_type="attempt.output.received.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(attempt, event, event_replayed)

    async def persist_validation(
        self,
        attempt_id: uuid.UUID,
        result: ValidationResult,
        *,
        validator_revisions: Mapping[ValidationLevel, ValidatorRevision],
        operation_key: str,
    ) -> ValidationWrite:
        """Persist exactly one content-addressed L0-L6 receipt per level."""

        async with self.session.begin_nested():
            await self._assert_scope()
            attempt, shard = await self._load_attempt(attempt_id)
            require_sha256(result.digest, field_name="validation.digest")
            by_level = {item.level: item for item in result.results}
            if set(by_level) != set(ValidationLevel) or len(result.results) != len(ValidationLevel):
                raise ParallelRuntimeConflict("validation result must cover L0-L6 exactly once")
            if set(validator_revisions) != set(ValidationLevel):
                raise ParallelRuntimeConflict("all L0-L6 validator revisions must be supplied")
            required_levels = self._required_levels(shard)
            expected_passed = all(by_level[level].passed for level in required_levels)
            if expected_passed != result.passed or result.hard_failure_count != len(
                result.findings
            ):
                raise ParallelRuntimeConflict("validation summary contradicts its level evidence")
            primary_page_ids = shard.ownership.get("primary_page_ids")
            if (
                not isinstance(primary_page_ids, list)
                or not primary_page_ids
                or any(not isinstance(item, str) or not item for item in primary_page_ids)
            ):
                raise ParallelRuntimeConflict("shard validation page policy is malformed")
            validation_policy = ValidationPolicy(
                expected_page_ids=tuple(primary_page_ids),
                native_comparison_required=bool(shard.context.get("native_comparison_required")),
                authority_required=bool(shard.context.get("authority_required")),
                differential_required=bool(shard.context.get("differential_required")),
                multimodal_required=bool(shard.context.get("multimodal_required")),
                downstream_required=bool(shard.context.get("downstream_required")),
                minimum_source_coverage=1.0,
            )
            expected_digest = runtime_canonical_sha256(
                {
                    "policy": validation_policy,
                    "results": result.results,
                    "findings": result.findings,
                    "passed": result.passed,
                }
            )
            if result.digest != expected_digest:
                raise ParallelRuntimeConflict(
                    "validation digest differs from canonical L0-L6 material"
                )
            rows: list[AttemptValidation] = []
            failure_events: list[CollectionEvent] = []
            replay_flags: list[bool] = []
            for level in ValidationLevel:
                level_result = by_level[level]
                required = level in required_levels
                if level_result.required != required:
                    raise ParallelRuntimeConflict("core and durable validator policies differ")
                binding = validator_revisions[level]
                pinned = self._pinned_validator(shard, level)
                if required and pinned != binding:
                    raise ParallelRuntimeConflict("validator revision differs from the planned pin")
                findings = tuple(finding for finding in result.findings if finding.level is level)
                finding_payloads: list[dict[str, Any]] = [
                    {
                        "code": finding.code,
                        "severity": finding.severity.value,
                        "detail": finding.detail,
                        "evidence_sha256": [receipt.sha256 for receipt in finding.evidence],
                    }
                    for finding in findings
                ]
                evidence = {
                    "validation_digest": result.digest,
                    "required": required,
                    "passed": level_result.passed,
                    "receipts": [
                        {
                            "source_ref": receipt.source_ref,
                            "sha256": receipt.sha256,
                            "kind": receipt.kind,
                        }
                        for receipt in level_result.evidence
                    ],
                    "findings": finding_payloads,
                }
                status = (
                    "abstained"
                    if not required
                    else "passed"
                    if level_result.passed
                    else "unavailable"
                    if not level_result.evidence
                    else "failed"
                )
                row, row_replayed = await record_attempt_validation(
                    self.session,
                    attempt=attempt,
                    level=int(level),
                    validator_key=binding.validator_key,
                    validator_revision=binding.validator_revision,
                    status=status,
                    score=(
                        Decimal("1")
                        if status == "passed"
                        else Decimal("0")
                        if status == "failed"
                        else None
                    ),
                    hard_fail=required and not level_result.passed,
                    reason_codes=level_result.reason_codes,
                    findings=finding_payloads,
                    evidence=evidence,
                )
                rows.append(row)
                replay_flags.append(row_replayed)
                if required and not level_result.passed:
                    reasons = list(level_result.reason_codes) or ["validation_failed"]
                    payload = {
                        "collection_id": str(self.scope.collection_id),
                        "document_id": str(self.scope.document_id),
                        "shard_id": str(shard.id),
                        "attempt_id": str(attempt.id),
                        "validation_id": str(row.id),
                        "validation_level": int(level),
                        "validator_key": binding.validator_key,
                        "reason_codes": reasons,
                        "hard_fail": True,
                        "attempt_state": "VALIDATING",
                    }
                    event, event_replayed = await self._emit_once(
                        event_type="attempt.validation.failed.v1",
                        operation_key=f"{_operation_key(operation_key)}:L{int(level)}",
                        payload=payload,
                    )
                    failure_events.append(event)
                    replay_flags.append(event_replayed)
            await self.session.flush()
            return ValidationWrite(
                rows=tuple(rows),
                failure_events=tuple(failure_events),
                replayed=all(replay_flags),
            )

    async def _attempt_has_required_receipts(
        self, attempt: ParallelParseAttempt, shard: ParallelParseShard
    ) -> bool:
        rows = list(
            (
                await self.session.scalars(
                    select(AttemptValidation).where(
                        AttemptValidation.tenant_id == self.scope.tenant_id,
                        AttemptValidation.attempt_id == attempt.id,
                    )
                )
            ).all()
        )
        if any(row.hard_fail or row.status == "failed" for row in rows):
            return False
        for level in self._required_levels(shard):
            pinned = self._pinned_validator(shard, level)
            if not any(
                row.level == int(level)
                and row.status == "passed"
                and not row.hard_fail
                and (
                    pinned is None
                    or (
                        row.validator_key == pinned.validator_key
                        and row.validator_revision == pinned.validator_revision
                    )
                )
                for row in rows
            ):
                return False
        return True

    @staticmethod
    def _authority_tier(basis: ArbitrationBasis) -> str:
        return {
            ArbitrationBasis.AUTHORITY_EXACT: "exact_authority",
            ArbitrationBasis.NATIVE_EXACT: "native",
            ArbitrationBasis.PIXEL_SPECIALIST: "pixel_ocr",
            ArbitrationBasis.INDEPENDENT_AGREEMENT: "independent_agreement",
            ArbitrationBasis.SOURCE_GEOMETRY: "independent_agreement",
            ArbitrationBasis.TABLE_CELL_MAP: "independent_agreement",
            ArbitrationBasis.DOWNSTREAM_CONSISTENCY: "independent_agreement",
            ArbitrationBasis.UNRESOLVED: "none",
        }[basis]

    async def persist_arbitration(
        self,
        shard_id: uuid.UUID,
        decision: CoreArbitrationDecision,
        *,
        policy_version: str,
        evidence: Mapping[str, Any],
        operation_key: str,
        priced_credit_amount: Decimal | None = None,
    ) -> DurableWrite[DurableArbitrationDecision]:
        """Persist authority-first arbitration without creating billability."""

        async with self.session.begin_nested():
            await self._assert_scope()
            shard = await self._load_shard(shard_id)
            require_sha256(decision.decision_sha256, field_name="arbitration.decision_sha256")
            candidate_ids = tuple(
                _uuid_string(value, field="considered_attempt_id")
                for value in decision.considered_attempt_ids
            )
            excluded_ids = tuple(
                _uuid_string(value, field="excluded_attempt_id")
                for value in decision.excluded_hard_gate_attempt_ids
            )
            if (
                len(set(candidate_ids)) != len(candidate_ids)
                or len(set(excluded_ids)) != len(excluded_ids)
                or set(candidate_ids) & set(excluded_ids)
            ):
                raise ParallelRuntimeConflict("arbitration candidates and exclusions overlap")
            attempts_by_id: dict[uuid.UUID, ParallelParseAttempt] = {}
            for attempt_id in (*candidate_ids, *excluded_ids):
                attempt, attempt_shard = await self._load_attempt(attempt_id)
                if attempt_shard.id != shard.id or attempt.shard_id != shard.id:
                    raise ParallelRuntimeConflict("arbitration cannot cross shard boundaries")
                attempts_by_id[attempt.id] = attempt
            selected_id = (
                _uuid_string(decision.selected_attempt_id, field="selected_attempt_id")
                if decision.selected_attempt_id is not None
                else None
            )
            if (
                decision.accepted != (selected_id is not None)
                or decision.billable != decision.accepted
            ):
                raise ParallelRuntimeConflict(
                    "core arbitration acceptance and billing are inconsistent"
                )
            logical_unit_key = _logical_unit_key(decision.scope_id)
            logical_unit_sha256 = runtime_canonical_sha256({"logical_unit_key": logical_unit_key})
            price = Decimal("0") if priced_credit_amount is None else Decimal(priced_credit_amount)
            if (
                not price.is_finite()
                or price < 0
                or price.quantize(_CREDIT_QUANTUM) != price
                or (decision.accepted and price <= 0)
                or (not decision.accepted and price != 0)
            ):
                raise ParallelRuntimeConflict(
                    "arbitration price is inconsistent with its acceptance decision"
                )
            if selected_id is not None:
                if selected_id not in candidate_ids:
                    raise ParallelRuntimeConflict("selected attempt was not considered")
                selected, selected_shard = await self._load_attempt(selected_id)
                if (
                    selected_shard.id != shard.id
                    or selected.output_sha256 != decision.selected_prediction_sha256
                    or not await self._attempt_has_required_receipts(selected, shard)
                ):
                    raise ParallelRuntimeConflict(
                        "selected attempt lacks matching verified evidence"
                    )
            if decision.accepted:
                expected_state = {
                    ArbitrationBasis.AUTHORITY_EXACT: VerificationState.AUTHORITY_VERIFIED,
                    ArbitrationBasis.INDEPENDENT_AGREEMENT: (
                        VerificationState.CROSS_MODEL_VERIFIED
                    ),
                    ArbitrationBasis.NATIVE_EXACT: VerificationState.VERIFIED,
                    ArbitrationBasis.PIXEL_SPECIALIST: VerificationState.VERIFIED,
                    ArbitrationBasis.SOURCE_GEOMETRY: VerificationState.VERIFIED,
                    ArbitrationBasis.TABLE_CELL_MAP: VerificationState.VERIFIED,
                    ArbitrationBasis.DOWNSTREAM_CONSISTENCY: VerificationState.VERIFIED,
                }.get(decision.basis)
                if (
                    expected_state is None
                    or decision.verification_state is not expected_state
                    or decision.reason_codes != (decision.basis.value,)
                    or selected_id is None
                ):
                    raise ParallelRuntimeConflict(
                        "arbitration basis and verification state are inconsistent"
                    )
                basis_level = {
                    ArbitrationBasis.AUTHORITY_EXACT: ValidationLevel.AUTHORITY,
                    ArbitrationBasis.NATIVE_EXACT: ValidationLevel.NATIVE,
                    ArbitrationBasis.PIXEL_SPECIALIST: ValidationLevel.MULTIMODAL,
                    ArbitrationBasis.SOURCE_GEOMETRY: ValidationLevel.MULTIMODAL,
                    ArbitrationBasis.TABLE_CELL_MAP: ValidationLevel.MULTIMODAL,
                    ArbitrationBasis.DOWNSTREAM_CONSISTENCY: ValidationLevel.DOWNSTREAM,
                    ArbitrationBasis.INDEPENDENT_AGREEMENT: ValidationLevel.DIFFERENTIAL,
                }[decision.basis]
                evidence_attempt_ids = (
                    candidate_ids
                    if decision.basis is ArbitrationBasis.INDEPENDENT_AGREEMENT
                    else (selected_id,)
                )
                basis_binding = self._pinned_validator(shard, basis_level)
                if basis_binding is None:
                    raise ParallelRuntimeConflict(
                        "arbitration basis is not enabled by the pinned validation policy"
                    )
                passed_evidence_models: set[str] = set()
                for attempt_id in evidence_attempt_ids:
                    receipt = await self.session.scalar(
                        select(AttemptValidation).where(
                            AttemptValidation.tenant_id == self.scope.tenant_id,
                            AttemptValidation.attempt_id == attempt_id,
                            AttemptValidation.level == int(basis_level),
                            AttemptValidation.validator_key == basis_binding.validator_key,
                            AttemptValidation.validator_revision
                            == basis_binding.validator_revision,
                            AttemptValidation.status == "passed",
                            AttemptValidation.hard_fail.is_(False),
                        )
                    )
                    if (
                        receipt is not None
                        and isinstance(receipt.evidence, dict)
                        and receipt.evidence.get("required") is True
                        and receipt.evidence.get("passed") is True
                        and isinstance(receipt.evidence.get("validation_digest"), str)
                    ):
                        passed_evidence_models.add(attempts_by_id[attempt_id].model_id)
                minimum_evidence = (
                    2 if decision.basis is ArbitrationBasis.INDEPENDENT_AGREEMENT else 1
                )
                if len(passed_evidence_models) < minimum_evidence:
                    raise ParallelRuntimeConflict(
                        "arbitration basis lacks persisted validator evidence"
                    )
                expected_decision_sha256 = runtime_canonical_sha256(
                    {
                        "scope_id": logical_unit_key,
                        "attempt_id": str(selected_id),
                        "prediction_sha256": decision.selected_prediction_sha256,
                        "basis": decision.basis,
                        "state": decision.verification_state,
                    }
                )
            else:
                if (
                    decision.basis is not ArbitrationBasis.UNRESOLVED
                    or decision.verification_state
                    not in {VerificationState.UNRESOLVED, VerificationState.QUARANTINED}
                ):
                    raise ParallelRuntimeConflict(
                        "unaccepted arbitration must remain unresolved or quarantined"
                    )
                expected_decision_sha256 = runtime_canonical_sha256(
                    {
                        "scope_id": logical_unit_key,
                        "basis": ArbitrationBasis.UNRESOLVED,
                        "considered": tuple(str(item) for item in candidate_ids),
                        "excluded": tuple(str(item) for item in excluded_ids),
                        "reasons": decision.reason_codes,
                    }
                )
            if decision.decision_sha256 != expected_decision_sha256:
                raise ParallelRuntimeConflict(
                    "arbitration digest differs from canonical decision material"
                )
            authority_tier = self._authority_tier(decision.basis)
            durable_decision = (
                "selected"
                if decision.accepted
                else "quarantined"
                if decision.verification_state is VerificationState.QUARANTINED
                else "unresolved"
            )
            evidence_value = _reserved_merge(
                evidence,
                {
                    "core_decision_id": decision.decision_id,
                    "decision_sha256": decision.decision_sha256,
                    "basis": decision.basis.value,
                    "verification_state": decision.verification_state.value,
                    "billable_candidate": decision.billable,
                    "logical_unit_key": logical_unit_key,
                    "logical_unit_sha256": logical_unit_sha256,
                    "priced_credit_amount": _decimal_string(price),
                },
            )
            evidence_sha256 = canonical_sha256(evidence_value)
            decision_key = _store_key("arbitration", operation_key)
            existing = await self.session.scalar(
                select(DurableArbitrationDecision).where(
                    DurableArbitrationDecision.tenant_id == self.scope.tenant_id,
                    DurableArbitrationDecision.decision_key == decision_key,
                )
            )
            requested = (
                self.scope.document_id,
                shard.id,
                [str(item) for item in candidate_ids],
                [str(item) for item in excluded_ids],
                selected_id,
                durable_decision,
                authority_tier,
                list(decision.reason_codes),
                evidence_sha256,
                policy_version,
                logical_unit_key,
                logical_unit_sha256,
                price,
            )
            if existing is not None:
                persisted = (
                    existing.document_id,
                    existing.shard_id,
                    existing.candidate_attempt_ids,
                    existing.excluded_attempt_ids,
                    existing.selected_attempt_id,
                    existing.decision,
                    existing.authority_tier,
                    existing.reason_codes,
                    existing.evidence_sha256,
                    existing.policy_version,
                    existing.logical_unit_key,
                    existing.logical_unit_sha256,
                    Decimal(existing.priced_credit_amount),
                )
                if persisted != requested or existing.evidence != evidence_value:
                    raise ParallelRuntimeConflict(
                        "arbitration operation key was reused with different evidence"
                    )
                return DurableWrite(existing, None, True)
            row = DurableArbitrationDecision(
                tenant_id=self.scope.tenant_id,
                document_id=self.scope.document_id,
                shard_id=shard.id,
                decision_key=decision_key,
                candidate_attempt_ids=requested[2],
                excluded_attempt_ids=requested[3],
                selected_attempt_id=selected_id,
                decision=durable_decision,
                authority_tier=authority_tier,
                reason_codes=list(decision.reason_codes),
                evidence=evidence_value,
                evidence_sha256=evidence_sha256,
                policy_version=policy_version,
                logical_unit_key=logical_unit_key,
                logical_unit_sha256=logical_unit_sha256,
                priced_credit_amount=price,
            )
            self.session.add(row)
            await self.session.flush()
            return DurableWrite(row, None, False)

    @staticmethod
    def _verify_ledger(
        ledger: CreditLedger,
        *,
        amount: Decimal,
        job_id: uuid.UUID | None,
        metadata: Mapping[str, Any],
    ) -> None:
        if (
            ledger.entry_type != "consume"
            or Decimal(ledger.credits) != amount
            or ledger.job_id != job_id
            or ledger.metadata_json != dict(metadata)
        ):
            raise ParallelRuntimeConflict("credit operation key was reused with different content")

    @staticmethod
    def _verify_refund_ledger(
        ledger: CreditLedger,
        *,
        amount: Decimal,
        job_id: uuid.UUID,
        metadata: Mapping[str, Any],
    ) -> None:
        if (
            ledger.entry_type != "refund"
            or Decimal(ledger.credits) != amount
            or ledger.job_id != job_id
            or ledger.metadata_json != dict(metadata)
        ):
            raise ParallelRuntimeConflict("refund operation key was reused with different content")

    async def accept(
        self,
        arbitration_id: uuid.UUID,
        *,
        logical_block_key: str,
        artifact_key: str,
        artifact_sha256: str,
        provenance: Mapping[str, Any],
        credit_amount: Decimal,
        operation_key: str,
    ) -> AcceptanceWrite:
        """Persist the selected block and its sole credit consume atomically."""

        async with self.session.begin_nested():
            await self._assert_scope()
            processing_job_id, document_version_id = self._require_execution_scope()
            decision = await self.session.scalar(
                select(DurableArbitrationDecision)
                .where(
                    DurableArbitrationDecision.tenant_id == self.scope.tenant_id,
                    DurableArbitrationDecision.id == arbitration_id,
                    DurableArbitrationDecision.document_id == self.scope.document_id,
                )
                .with_for_update()
            )
            if (
                decision is None
                or decision.decision != "selected"
                or decision.selected_attempt_id is None
            ):
                raise ParallelRuntimeConflict(
                    "only a persisted selected arbitration can be accepted"
                )
            logical_key = _logical_unit_key(logical_block_key)
            if (
                logical_key != decision.logical_unit_key
                or runtime_canonical_sha256({"logical_unit_key": logical_key})
                != decision.logical_unit_sha256
            ):
                raise ParallelRuntimeConflict(
                    "acceptance logical unit differs from its arbitration"
                )
            amount = Decimal(credit_amount)
            if not amount.is_finite() or amount <= 0 or amount.quantize(_CREDIT_QUANTUM) != amount:
                raise ValueError("credit_amount must be positive with at most six decimals")
            if amount != Decimal(decision.priced_credit_amount):
                raise ParallelRuntimeConflict(
                    "acceptance credit amount differs from its priced arbitration"
                )
            attempt, shard = await self._load_attempt(decision.selected_attempt_id)
            if shard.id != decision.shard_id or not await self._attempt_has_required_receipts(
                attempt, shard
            ):
                raise ParallelRuntimeConflict("accepted arbitration lost its validation receipts")
            require_sha256(artifact_sha256, field_name="artifact_sha256")
            if attempt.output_sha256 != artifact_sha256:
                raise ParallelRuntimeConflict("accepted artifact differs from selected prediction")
            verification_state = decision.evidence.get("verification_state")
            if verification_state not in {state.value for state in ACCEPTED_VERIFICATION_STATES}:
                raise ParallelRuntimeConflict("arbitration has no billable verification state")
            source_refs_value = provenance.get("source_refs")
            if source_refs_value is None:
                primary_page_ids = shard.ownership.get("primary_page_ids")
                if not isinstance(primary_page_ids, list) or not primary_page_ids:
                    raise ParallelRuntimeConflict(
                        "accepted shard has no source reference projection"
                    )
                source_refs = tuple(f"page://{item}" for item in primary_page_ids)
            elif (
                not isinstance(source_refs_value, (list, tuple))
                or not source_refs_value
                or any(not isinstance(item, str) or not item for item in source_refs_value)
            ):
                raise ParallelRuntimeConflict("accepted source references are malformed")
            else:
                source_refs = tuple(source_refs_value)
            provenance_attempts_value = provenance.get("provenance_attempt_ids")
            if provenance_attempts_value is None:
                provenance_attempt_ids = (str(attempt.id),)
            elif (
                not isinstance(provenance_attempts_value, (list, tuple))
                or not provenance_attempts_value
                or any(not isinstance(item, str) or not item for item in provenance_attempts_value)
            ):
                raise ParallelRuntimeConflict("accepted attempt provenance is malformed")
            else:
                provenance_attempt_ids = tuple(provenance_attempts_value)
            if str(attempt.id) not in provenance_attempt_ids:
                raise ParallelRuntimeConflict(
                    "accepted attempt provenance omits the selected attempt"
                )
            provenance_value = {
                **dict(provenance),
                "source_refs": list(source_refs),
                "provenance_attempt_ids": list(provenance_attempt_ids),
            }
            acceptance_key = _store_key("accept", str(decision.id))
            settlement_key = _store_key("credit", str(decision.id))
            block, block_replayed = await accept_verified_block(
                self.session,
                attempt=attempt,
                document_id=self.scope.document_id,
                processing_job_id=processing_job_id,
                document_version_id=document_version_id,
                arbitration_id=decision.id,
                logical_block_key=logical_key,
                final_state=str(verification_state),
                artifact_key=artifact_key,
                artifact_sha256=artifact_sha256,
                provenance=_reserved_merge(
                    provenance_value,
                    {
                        "arbitration_id": str(decision.id),
                        "arbitration_evidence_sha256": decision.evidence_sha256,
                        "logical_unit_sha256": decision.logical_unit_sha256,
                        "priced_credit_amount": _decimal_string(amount),
                        "accept_operation_sha256": runtime_canonical_sha256(
                            {"operation_key": _operation_key(operation_key)}
                        ),
                        "processing_job_id": str(processing_job_id),
                        "document_version_id": document_version_id,
                    },
                ),
                acceptance_idempotency_key=acceptance_key,
                credit_settlement_key=settlement_key,
                credit_amount=amount,
            )
            metadata = {
                "source": "parallel_runtime_v6",
                "document_id": str(self.scope.document_id),
                "document_version_id": document_version_id,
                "processing_job_id": str(processing_job_id),
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "arbitration_id": str(decision.id),
                "accepted_block_id": str(block.id),
                "artifact_sha256": artifact_sha256,
                "arbitration_evidence_sha256": decision.evidence_sha256,
            }
            existing_ledger = await self.session.scalar(
                select(CreditLedger).where(
                    CreditLedger.tenant_id == self.scope.tenant_id,
                    CreditLedger.operation_key == settlement_key,
                )
            )
            if existing_ledger is not None:
                if not block_replayed:
                    raise ParallelRuntimeConflict("credit ledger existed before its accepted block")
                self._verify_ledger(
                    existing_ledger,
                    amount=amount,
                    job_id=self.scope.processing_job_id,
                    metadata=metadata,
                )
                ledger = existing_ledger
                ledger_replayed = True
            else:
                if block_replayed:
                    raise ParallelRuntimeConflict("accepted block lost its atomic credit ledger")
                ledger = await credit_entry(
                    self.session,
                    tenant_id=self.scope.tenant_id,
                    operation_key=settlement_key,
                    entry_type="consume",
                    credits=amount,
                    job_id=self.scope.processing_job_id,
                    metadata=metadata,
                )
                self._verify_ledger(
                    ledger,
                    amount=amount,
                    job_id=self.scope.processing_job_id,
                    metadata=metadata,
                )
                ledger_replayed = False
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "final_state": str(verification_state),
                "authority_tier": decision.authority_tier,
                "billable": True,
                "cost_usd": _decimal_string(Decimal(attempt.cost_usd)),
            }
            event, event_replayed = await self._emit_once(
                event_type="attempt.accepted.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return AcceptanceWrite(
                block=block,
                ledger=ledger,
                event=event,
                replayed=block_replayed and ledger_replayed and event_replayed,
            )

    async def reject(
        self,
        attempt_id: uuid.UUID,
        *,
        target_state: str,
        failure_domain: str,
        reason_codes: Sequence[str],
        operation_key: str,
    ) -> DurableWrite[ParallelParseAttempt]:
        """Reject, fail, or quarantine one attempt without creating billing."""

        if target_state not in {
            "REJECTED",
            "RETRYABLE_FAILED",
            "TERMINAL_FAILED",
            "QUARANTINED",
        }:
            raise ValueError("target_state is not a reject terminal")
        if failure_domain not in {"infrastructure", "semantic", "policy", "cancelled"}:
            raise ValueError("failure_domain is outside the durable enum")
        reasons = tuple(reason_codes)
        if not reasons:
            raise ValueError("rejection requires at least one reason code")
        async with self.session.begin_nested():
            await self._assert_scope()
            attempt, shard = await self._load_attempt(attempt_id)
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "failure_domain": failure_domain,
                "reason_codes": list(reasons),
                "attempt_state": target_state,
            }
            existing_event = await self._existing_event(
                event_type="attempt.rejected.v1",
                operation_key=operation_key,
                payload=payload,
            )
            if existing_event is not None:
                if (
                    attempt.state != target_state
                    or attempt.failure_domain != failure_domain
                    or attempt.failure_code != reasons[0]
                ):
                    raise ParallelRuntimeConflict("reject event lost its terminal projection")
                return DurableWrite(attempt, existing_event, True)
            if attempt.state in _TERMINAL_ATTEMPT_STATES:
                raise ParallelRuntimeConflict("terminal attempt cannot be rejected differently")
            attempt.failure_domain = failure_domain
            attempt.failure_code = reasons[0]
            attempt.billing_disposition = (
                "quarantine_unbillable"
                if target_state == "QUARANTINED"
                else "unresolved_unbillable"
            )
            await transition_parse_attempt(self.session, attempt, target_state)
            shard.status = (
                "QUARANTINED"
                if target_state == "QUARANTINED"
                else "RECOVERY_PENDING"
                if target_state == "RETRYABLE_FAILED"
                else "FAILED"
                if target_state == "TERMINAL_FAILED"
                else "UNRESOLVED"
            )
            shard.updated_at = utcnow()
            event, _ = await self._emit_once(
                event_type="attempt.rejected.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(attempt, event, False)

    async def hedge(
        self,
        source_attempt_id: uuid.UUID,
        *,
        pool_key: str,
        model_id: str,
        model_revision: str,
        runtime_identity: str,
        route_policy_version: str,
        request_sha256: str,
        predicted_p95_milliseconds: int,
        elapsed_milliseconds: int,
        operation_key: str,
    ) -> DurableWrite[ParallelParseAttempt]:
        """Create at most one unbillable hedge child for a running attempt."""

        if predicted_p95_milliseconds < 1 or elapsed_milliseconds < 0:
            raise ValueError("hedge timing must be nonnegative with a positive p95")
        async with self.session.begin_nested():
            await self._assert_scope()
            source, shard = await self._load_attempt(source_attempt_id)
            existing_children = list(
                (
                    await self.session.scalars(
                        select(ParallelParseAttempt).where(
                            ParallelParseAttempt.tenant_id == self.scope.tenant_id,
                            ParallelParseAttempt.parent_attempt_id == source.id,
                            ParallelParseAttempt.attempt_kind == "hedge",
                        )
                    )
                ).all()
            )
            expected_key = _store_key("hedge", operation_key)
            if any(child.idempotency_key != expected_key for child in existing_children):
                raise ParallelRuntimeConflict("a logical attempt already has a different hedge")
            if source.state != "RUNNING" and not existing_children:
                raise ParallelRuntimeConflict("a hedge can only launch from a running source")
            child, child_replayed = await create_parse_attempt(
                self.session,
                tenant_id=self.scope.tenant_id,
                shard_id=shard.id,
                parent_attempt_id=source.id,
                attempt_kind="hedge",
                pool_key=pool_key,
                model_id=model_id,
                model_revision=model_revision,
                runtime_identity=runtime_identity,
                route_policy_version=route_policy_version,
                idempotency_key=expected_key,
                request_sha256=request_sha256,
            )
            if child.state == "CREATED":
                await transition_parse_attempt(self.session, child, "QUEUED")
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "source_attempt_id": str(source.id),
                "hedge_attempt_id": str(child.id),
                "predicted_p95_milliseconds": predicted_p95_milliseconds,
                "elapsed_milliseconds": elapsed_milliseconds,
                "billing_disposition": "speculative_unbillable",
            }
            event, event_replayed = await self._emit_once(
                event_type="attempt.hedged.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(child, event, child_replayed and event_replayed)

    async def record_worker_health(
        self,
        transition: HealthTransition,
        *,
        pool_key: str,
        model_id: str,
        runtime_identity: str,
        region: str,
        infrastructure_status: str,
        semantic_status: str,
        infrastructure_score: Decimal,
        inflight: int,
        capacity: int,
        consecutive_semantic_failures: int,
        metrics: Mapping[str, Any],
        impacted_attempt_ids: Sequence[uuid.UUID],
        operation_key: str,
    ) -> WorkerHealthWrite:
        """Persist independent infrastructure and semantic health projections."""

        event_type = {
            WorkerState.DEGRADED: "worker.semantic.degraded.v1",
            WorkerState.DRAINING: "worker.draining.v1",
            WorkerState.QUARANTINED: "worker.quarantined.v1",
        }.get(transition.to_state)
        if event_type is None:
            raise ValueError("collection health events support degraded, draining, or quarantined")
        async with self.session.begin_nested():
            await self._assert_scope()
            authoritative_attempts = await self._authoritative_worker_attempts(
                worker_id=transition.worker_id,
                pool_key=pool_key,
                model_id=model_id,
                runtime_identity=runtime_identity,
                hinted_attempt_ids=impacted_attempt_ids,
            )
            authoritative_attempt_ids = tuple(attempt.id for attempt in authoritative_attempts)
            transition_sha256 = runtime_canonical_sha256(
                {
                    "worker_id": transition.worker_id,
                    "from_state": transition.from_state,
                    "to_state": transition.to_state,
                    "occurred_at": transition.occurred_at,
                    "reason_codes": transition.reason_codes,
                    "semantic_score": transition.semantic_score,
                    "infrastructure_status": infrastructure_status,
                    "semantic_status": semantic_status,
                    "metrics": dict(metrics),
                    "impacted_attempt_ids": tuple(str(item) for item in authoritative_attempt_ids),
                }
            )
            metrics_value = _reserved_merge(metrics, {"transition_sha256": transition_sha256})
            current = await self.session.scalar(
                select(WorkerHealth)
                .where(
                    WorkerHealth.tenant_id == self.scope.tenant_id,
                    WorkerHealth.worker_id == transition.worker_id,
                )
                .with_for_update()
            )
            semantic_score = (Decimal(str(transition.semantic_score)) / Decimal("100")).quantize(
                Decimal("0.00000001")
            )
            if current is not None:
                payload = self._worker_event_payload(
                    event_type=event_type,
                    worker=current,
                    semantic_score=semantic_score,
                    reason_codes=transition.reason_codes,
                    impacted_attempt_ids=authoritative_attempt_ids,
                )
                existing_event = await self._existing_event(
                    event_type=event_type,
                    operation_key=operation_key,
                    payload=payload,
                )
                if existing_event is not None:
                    semantic_event = await self.session.scalar(
                        select(SemanticHealthEvent).where(
                            SemanticHealthEvent.tenant_id == self.scope.tenant_id,
                            SemanticHealthEvent.worker_health_id == current.id,
                            SemanticHealthEvent.evidence_sha256
                            == canonical_sha256(
                                {
                                    "claimed_state": transition.to_state.value,
                                    "effective_state": current.state,
                                    "infrastructure_status": infrastructure_status,
                                    "semantic_status": semantic_status,
                                    "metrics": metrics_value,
                                }
                            ),
                        )
                    )
                    if semantic_event is None or current.metrics != metrics_value:
                        raise ParallelRuntimeConflict("health event lost its dual projection")
                    invalidation_write = (
                        await self._invalidate_worker_acceptances(
                            attempts=authoritative_attempts,
                            worker_id=transition.worker_id,
                            model_id=model_id,
                            runtime_identity=runtime_identity,
                        )
                        if transition.to_state is WorkerState.QUARANTINED
                        else ((), (), (), (), True)
                    )
                    return WorkerHealthWrite(
                        current,
                        semantic_event,
                        existing_event,
                        invalidation_write[4],
                        invalidation_write[0],
                        invalidation_write[1],
                        invalidation_write[2],
                        invalidation_write[3],
                    )
                if current.state != transition.from_state.value:
                    raise ParallelRuntimeConflict("worker transition starts from a stale state")
            elif transition.from_state is not WorkerState.HEALTHY:
                raise ParallelRuntimeConflict("a new worker health row must start from HEALTHY")
            worker, semantic_event = await update_worker_health(
                self.session,
                tenant_id=self.scope.tenant_id,
                worker_id=transition.worker_id,
                pool_key=pool_key,
                model_id=model_id,
                runtime_identity=runtime_identity,
                region=region,
                state=transition.to_state.value,
                infrastructure_status=infrastructure_status,
                semantic_status=semantic_status,
                infrastructure_score=Decimal(infrastructure_score),
                semantic_score=semantic_score,
                inflight=inflight,
                capacity=capacity,
                consecutive_semantic_failures=consecutive_semantic_failures,
                metrics=metrics_value,
                reason_codes=transition.reason_codes,
                impacted_attempt_ids=authoritative_attempt_ids,
                observed_at=transition.occurred_at,
            )
            if semantic_event is None:
                raise ParallelRuntimeConflict("worker transition did not append semantic evidence")
            payload = self._worker_event_payload(
                event_type=event_type,
                worker=worker,
                semantic_score=semantic_score,
                reason_codes=transition.reason_codes,
                impacted_attempt_ids=authoritative_attempt_ids,
            )
            event, _ = await self._emit_once(
                event_type=event_type,
                operation_key=operation_key,
                payload=payload,
            )
            invalidation_write = (
                await self._invalidate_worker_acceptances(
                    attempts=authoritative_attempts,
                    worker_id=transition.worker_id,
                    model_id=model_id,
                    runtime_identity=runtime_identity,
                )
                if transition.to_state is WorkerState.QUARANTINED
                else ((), (), (), (), True)
            )
            await self.session.flush()
            return WorkerHealthWrite(
                worker,
                semantic_event,
                event,
                False,
                invalidation_write[0],
                invalidation_write[1],
                invalidation_write[2],
                invalidation_write[3],
            )

    async def _authoritative_worker_attempts(
        self,
        *,
        worker_id: str,
        pool_key: str,
        model_id: str,
        runtime_identity: str,
        hinted_attempt_ids: Sequence[uuid.UUID],
    ) -> tuple[ParallelParseAttempt, ...]:
        processing_job_id, document_version_id = self._require_execution_scope()
        shard_ids = select(ParallelParseShard.id).where(
            ParallelParseShard.tenant_id == self.scope.tenant_id,
            ParallelParseShard.collection_id == self.scope.collection_id,
            ParallelParseShard.document_id == self.scope.document_id,
            ParallelParseShard.processing_job_id == processing_job_id,
            ParallelParseShard.document_version_id == document_version_id,
        )
        attempts = tuple(
            sorted(
                (
                    await self.session.scalars(
                        select(ParallelParseAttempt)
                        .where(
                            ParallelParseAttempt.tenant_id == self.scope.tenant_id,
                            ParallelParseAttempt.shard_id.in_(shard_ids),
                            ParallelParseAttempt.worker_id == worker_id,
                        )
                        .with_for_update()
                    )
                ).all(),
                key=lambda item: str(item.id),
            )
        )
        authoritative_ids = {attempt.id for attempt in attempts}
        if any(
            (
                attempt.pool_key,
                attempt.model_id,
                attempt.runtime_identity,
            )
            != (pool_key, model_id, runtime_identity)
            for attempt in attempts
        ):
            raise ParallelRuntimeConflict(
                "worker health identity does not match its scoped attempt lineage"
            )
        hint_ids = set(hinted_attempt_ids)
        if len(hint_ids) != len(hinted_attempt_ids):
            raise ParallelRuntimeConflict("impacted attempt hints contain duplicates")
        if not hint_ids <= authoritative_ids:
            raise ParallelRuntimeConflict(
                "impacted attempt hint does not match the scoped worker lineage"
            )
        return attempts

    @staticmethod
    def _verified_recovery_projection(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ParallelRuntimeConflict("parallel v6 recovery projection is malformed")
        expected_fields = {
            "schema_version",
            "epoch",
            "phase",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "accepted_block_ids",
            "invalidation_ids",
            "recovery_task_ids",
            "invalidation_set_sha256",
            "revoked_checkpoint_sha256",
            "completion",
            "projection_sha256",
        }
        if set(value) != expected_fields:
            raise ParallelRuntimeConflict("parallel v6 recovery projection shape is invalid")
        body = {key: item for key, item in value.items() if key != "projection_sha256"}
        projection_sha256 = value.get("projection_sha256")
        if (
            not isinstance(projection_sha256, str)
            or runtime_canonical_sha256(body) != projection_sha256
        ):
            raise ParallelRuntimeConflict("parallel v6 recovery projection digest is invalid")
        if (
            body["schema_version"] != _RECOVERY_PROJECTION_SCHEMA
            or not isinstance(body["epoch"], int)
            or isinstance(body["epoch"], bool)
            or body["epoch"] < 1
            or body["phase"] not in {"requested", "needs_review", "completed"}
        ):
            raise ParallelRuntimeConflict("parallel v6 recovery projection state is invalid")
        for field in ("accepted_block_ids", "invalidation_ids", "recovery_task_ids"):
            items = body[field]
            if (
                not isinstance(items, list)
                or any(not isinstance(item, str) or not item for item in items)
                or items != sorted(set(items))
            ):
                raise ParallelRuntimeConflict(f"parallel v6 recovery projection {field} is invalid")
        require_sha256(
            str(body["invalidation_set_sha256"]),
            field_name="recovery_projection.invalidation_set_sha256",
        )
        revoked_sha256 = body["revoked_checkpoint_sha256"]
        if revoked_sha256 is not None:
            require_sha256(
                str(revoked_sha256),
                field_name="recovery_projection.revoked_checkpoint_sha256",
            )
        completion = body["completion"]
        if body["phase"] == "completed":
            if not isinstance(completion, dict) or set(completion) != {
                "manifest_sha256",
                "active_blocks",
            }:
                raise ParallelRuntimeConflict(
                    "completed recovery projection lost its active-block manifest"
                )
            require_sha256(
                str(completion["manifest_sha256"]),
                field_name="recovery_projection.completion.manifest_sha256",
            )
            active_blocks = completion["active_blocks"]
            if not isinstance(active_blocks, list) or any(
                not isinstance(item, dict)
                or set(item) != {"accepted_block_id", "generation", "logical_block_key"}
                or not isinstance(item["accepted_block_id"], str)
                or not item["accepted_block_id"]
                or not isinstance(item["generation"], int)
                or isinstance(item["generation"], bool)
                or item["generation"] < 1
                or not isinstance(item["logical_block_key"], str)
                or not item["logical_block_key"]
                for item in active_blocks
            ):
                raise ParallelRuntimeConflict(
                    "completed recovery projection active blocks are malformed"
                )
        elif completion is not None:
            raise ParallelRuntimeConflict(
                "non-completed recovery projection cannot carry completion evidence"
            )
        return body

    async def _project_worker_quarantine_recovery(
        self,
        *,
        new_invalidation_count: int,
    ) -> None:
        """Revoke publishability and invalidate any stale terminal scheduler checkpoint."""

        if new_invalidation_count < 0:
            raise ValueError("new invalidation count cannot be negative")
        _, document, job = await self._assert_scope()
        processing_job_id, document_version_id = self._require_execution_scope()
        if job is None:
            raise ParallelRuntimeConflict("worker quarantine lost its processing job projection")
        invalidations = tuple(
            sorted(
                (
                    await self.session.scalars(
                        select(AcceptedBlockInvalidation).where(
                            AcceptedBlockInvalidation.tenant_id == self.scope.tenant_id,
                            AcceptedBlockInvalidation.document_id == self.scope.document_id,
                            AcceptedBlockInvalidation.processing_job_id == processing_job_id,
                            AcceptedBlockInvalidation.document_version_id == document_version_id,
                        )
                    )
                ).all(),
                key=lambda item: str(item.id),
            )
        )
        if not invalidations:
            if new_invalidation_count:
                raise ParallelRuntimeConflict(
                    "new worker quarantine invalidation lost its durable projection"
                )
            return
        accepted_block_ids = sorted(str(item.accepted_block_id) for item in invalidations)
        invalidation_ids = sorted(str(item.id) for item in invalidations)
        recovery_task_ids = sorted(
            str(item.recovery_task_id)
            for item in invalidations
            if item.recovery_task_id is not None
        )
        invalidation_set_sha256 = runtime_canonical_sha256(
            tuple(
                {
                    "accepted_block_id": str(item.accepted_block_id),
                    "evidence_sha256": item.evidence_sha256,
                    "invalidation_id": str(item.id),
                }
                for item in invalidations
            )
        )
        progress = dict(job.progress) if isinstance(job.progress, dict) else {}
        existing_projection_value = progress.get(_RECOVERY_PROJECTION_KEY)
        existing_projection = (
            self._verified_recovery_projection(existing_projection_value)
            if existing_projection_value is not None
            else None
        )
        expected_scope = (
            str(self.scope.document_id),
            str(processing_job_id),
            document_version_id,
        )
        if new_invalidation_count:
            prior_epoch = int(existing_projection["epoch"]) if existing_projection else 0
            checkpoint = progress.pop(_AUTONOMOUS_PIPELINE_CHECKPOINT_KEY, None)
            revoked_checkpoint_sha256: str | None
            if checkpoint is None:
                revoked_checkpoint_sha256 = (
                    str(existing_projection["revoked_checkpoint_sha256"])
                    if existing_projection is not None
                    and existing_projection["revoked_checkpoint_sha256"] is not None
                    else None
                )
            elif (
                isinstance(checkpoint, dict)
                and isinstance(checkpoint.get("checkpoint_sha256"), str)
                and len(str(checkpoint["checkpoint_sha256"])) == 64
            ):
                revoked_checkpoint_sha256 = require_sha256(
                    str(checkpoint["checkpoint_sha256"]),
                    field_name="parallel_v6_checkpoint.checkpoint_sha256",
                )
            else:
                revoked_checkpoint_sha256 = runtime_canonical_sha256(checkpoint)
            body: dict[str, Any] = {
                "schema_version": _RECOVERY_PROJECTION_SCHEMA,
                "epoch": prior_epoch + 1,
                "phase": "requested",
                "document_id": expected_scope[0],
                "processing_job_id": expected_scope[1],
                "document_version_id": expected_scope[2],
                "accepted_block_ids": accepted_block_ids,
                "invalidation_ids": invalidation_ids,
                "recovery_task_ids": recovery_task_ids,
                "invalidation_set_sha256": invalidation_set_sha256,
                "revoked_checkpoint_sha256": revoked_checkpoint_sha256,
                "completion": None,
            }
            progress[_RECOVERY_PROJECTION_KEY] = {
                **body,
                "projection_sha256": runtime_canonical_sha256(body),
            }
            progress.update(
                {
                    "stage": "parallel_v6_recovery_requested",
                    "done": 0,
                    "total": len(recovery_task_ids),
                    "publishable": False,
                }
            )
            document.status = "PROCESSING"
            document.updated_at = utcnow()
            job.status = "running"
            job.completed_at = None
            job.error = None
            job.progress = progress
            return
        if existing_projection is None:
            raise ParallelRuntimeConflict("worker quarantine replay lost its recovery projection")
        persisted_scope = (
            existing_projection["document_id"],
            existing_projection["processing_job_id"],
            existing_projection["document_version_id"],
        )
        if (
            persisted_scope != expected_scope
            or existing_projection["accepted_block_ids"] != accepted_block_ids
            or existing_projection["invalidation_ids"] != invalidation_ids
            or existing_projection["recovery_task_ids"] != recovery_task_ids
            or existing_projection["invalidation_set_sha256"] != invalidation_set_sha256
        ):
            raise ParallelRuntimeConflict(
                "worker quarantine replay differs from its recovery projection"
            )
        if existing_projection["phase"] == "completed":
            if document.status != "COMPLETED" or job.status != "completed":
                raise ParallelRuntimeConflict(
                    "completed recovery projection lost its completed document or job"
                )
            invalidated_blocks = list(
                (
                    await self.session.scalars(
                        select(AcceptedBlock).where(
                            AcceptedBlock.tenant_id == self.scope.tenant_id,
                            AcceptedBlock.id.in_(
                                tuple(item.accepted_block_id for item in invalidations)
                            ),
                        )
                    )
                ).all()
            )
            active_blocks = list(
                (
                    await self.session.scalars(
                        select(AcceptedBlock).where(
                            AcceptedBlock.tenant_id == self.scope.tenant_id,
                            AcceptedBlock.document_id == self.scope.document_id,
                            AcceptedBlock.processing_job_id == processing_job_id,
                            AcceptedBlock.document_version_id == document_version_id,
                            ~AcceptedBlock.id.in_(
                                select(AcceptedBlockInvalidation.accepted_block_id).where(
                                    AcceptedBlockInvalidation.tenant_id == self.scope.tenant_id,
                                    AcceptedBlockInvalidation.processing_job_id
                                    == processing_job_id,
                                    AcceptedBlockInvalidation.document_version_id
                                    == document_version_id,
                                )
                            ),
                        )
                    )
                ).all()
            )
            active_by_key = {block.logical_block_key: block for block in active_blocks}
            completion = existing_projection["completion"]
            expected_active = [
                {
                    "accepted_block_id": str(block.id),
                    "generation": block.generation,
                    "logical_block_key": block.logical_block_key,
                }
                for block in sorted(
                    active_blocks,
                    key=lambda item: (item.logical_block_key, str(item.id)),
                )
            ]
            if (
                not isinstance(completion, dict)
                or completion["active_blocks"] != expected_active
                or len(invalidated_blocks) != len(invalidations)
                or any(
                    old.logical_block_key not in active_by_key
                    or active_by_key[old.logical_block_key].generation <= old.generation
                    for old in invalidated_blocks
                )
            ):
                raise ParallelRuntimeConflict(
                    "completed recovery projection differs from active replacement generations"
                )
            return
        if (
            _AUTONOMOUS_PIPELINE_CHECKPOINT_KEY in progress
            or document.status == "COMPLETED"
            or job.status in {"completed", "failed", "cancelled"}
            or job.completed_at is not None
        ):
            raise ParallelRuntimeConflict(
                "worker quarantine replay found a stale publishable projection"
            )

    async def _invalidate_worker_acceptances(
        self,
        *,
        attempts: Sequence[ParallelParseAttempt],
        worker_id: str,
        model_id: str,
        runtime_identity: str,
    ) -> tuple[
        tuple[AcceptedBlockInvalidation, ...],
        tuple[CreditLedger, ...],
        tuple[RecoveryTask, ...],
        tuple[CollectionEvent, ...],
        bool,
    ]:
        processing_job_id, document_version_id = self._require_execution_scope()
        if not attempts:
            return (), (), (), (), True
        attempt_by_id = {attempt.id: attempt for attempt in attempts}
        blocks = tuple(
            sorted(
                (
                    await self.session.scalars(
                        select(AcceptedBlock)
                        .where(
                            AcceptedBlock.tenant_id == self.scope.tenant_id,
                            AcceptedBlock.document_id == self.scope.document_id,
                            AcceptedBlock.processing_job_id == processing_job_id,
                            AcceptedBlock.document_version_id == document_version_id,
                            AcceptedBlock.attempt_id.in_(tuple(attempt_by_id)),
                        )
                        .with_for_update()
                    )
                ).all(),
                key=lambda item: str(item.id),
            )
        )
        invalidations: list[AcceptedBlockInvalidation] = []
        refunds: list[CreditLedger] = []
        recoveries: list[RecoveryTask] = []
        recovery_events: list[CollectionEvent] = []
        all_replayed = True
        new_invalidation_count = 0
        for block in blocks:
            attempt = attempt_by_id[block.attempt_id]
            shard = await self._load_shard(block.shard_id)
            if (
                attempt.worker_id != worker_id
                or attempt.model_id != model_id
                or attempt.runtime_identity != runtime_identity
                or attempt.state != "ACCEPTED"
                or shard.id != attempt.shard_id
            ):
                raise ParallelRuntimeConflict(
                    "accepted block is outside the quarantined worker lineage"
                )
            if block.credit_settlement_key is None:
                raise ParallelRuntimeConflict("accepted block lost its original credit settlement")
            consume = await self.session.scalar(
                select(CreditLedger).where(
                    CreditLedger.tenant_id == self.scope.tenant_id,
                    CreditLedger.operation_key == block.credit_settlement_key,
                )
            )
            amount = Decimal(block.credit_amount)
            if (
                consume is None
                or consume.entry_type != "consume"
                or consume.job_id != processing_job_id
                or Decimal(consume.credits) != amount
            ):
                raise ParallelRuntimeConflict(
                    "accepted block cannot be invalidated without its consume ledger"
                )
            source_refs = block.provenance.get("source_refs")
            if (
                not isinstance(source_refs, list)
                or not source_refs
                or any(not isinstance(item, str) or not item for item in source_refs)
            ):
                raise ParallelRuntimeConflict(
                    "accepted block cannot recover without source references"
                )
            recovery_level = (
                shard.shard_kind
                if shard.shard_kind in {"cell", "row", "table", "region", "page"}
                else "page_group"
            )
            recovery_operation_key = _store_key(
                "worker-quarantine-recovery",
                str(block.id),
            )
            recovery_target = {
                "core_task_id": f"worker-quarantine:{block.id}",
                "accepted_block_id": str(block.id),
                "processing_job_id": str(processing_job_id),
                "document_version_id": document_version_id,
                "logical_block_key": block.logical_block_key,
                "invalidated_artifact_sha256": block.artifact_sha256,
                "source_refs": source_refs,
                "worker_id": worker_id,
            }
            recovery, recovery_replayed = await request_recovery(
                self.session,
                tenant_id=self.scope.tenant_id,
                document_id=self.scope.document_id,
                shard_id=shard.id,
                source_attempt_id=attempt.id,
                recovery_level=recovery_level,
                reason_code="accepted_output_worker_quarantined",
                target=recovery_target,
                preprocessing_variants=("worker_quarantine_reparse",),
                route_candidates=(attempt.model_id,),
                idempotency_key=recovery_operation_key,
            )
            recovery_payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "source_attempt_id": str(attempt.id),
                "recovery_task_id": str(recovery.id),
                "recovery_level": recovery.recovery_level,
                "reason_codes": ["accepted_output_worker_quarantined"],
                "recovery_state": "REQUESTED",
            }
            recovery_event, recovery_event_replayed = await self._emit_once(
                event_type="recovery.region.requested.v1",
                operation_key=_store_key(
                    "worker-quarantine-recovery-event",
                    str(block.id),
                ),
                payload=recovery_payload,
            )
            refund_key = _store_key("worker-quarantine-refund", str(block.id))
            refund_metadata = {
                "source": "parallel_runtime_v6_worker_quarantine",
                "document_id": str(self.scope.document_id),
                "document_version_id": document_version_id,
                "processing_job_id": str(processing_job_id),
                "shard_id": str(shard.id),
                "attempt_id": str(attempt.id),
                "accepted_block_id": str(block.id),
                "original_settlement_key": block.credit_settlement_key,
                "reason": "accepted_output_worker_quarantined",
            }
            refund = await self.session.scalar(
                select(CreditLedger).where(
                    CreditLedger.tenant_id == self.scope.tenant_id,
                    CreditLedger.operation_key == refund_key,
                )
            )
            refund_replayed = refund is not None
            if refund is None:
                refund = await credit_entry(
                    self.session,
                    tenant_id=self.scope.tenant_id,
                    operation_key=refund_key,
                    entry_type="refund",
                    credits=amount,
                    job_id=processing_job_id,
                    metadata=refund_metadata,
                )
            self._verify_refund_ledger(
                refund,
                amount=amount,
                job_id=processing_job_id,
                metadata=refund_metadata,
            )
            invalidation_key = _store_key(
                "worker-quarantine-invalidation",
                str(block.id),
            )
            evidence = {
                "accepted_block_id": str(block.id),
                "arbitration_id": str(block.arbitration_id),
                "worker_id": worker_id,
                "model_id": model_id,
                "runtime_identity": runtime_identity,
                "artifact_sha256": block.artifact_sha256,
                "original_settlement_key": block.credit_settlement_key,
                "recovery_task_id": str(recovery.id),
                "refund_ledger_id": str(refund.id),
            }
            evidence_sha256 = canonical_sha256(evidence)
            operation_sha256 = canonical_sha256(
                {
                    "operation_key": invalidation_key,
                    "accepted_block_id": str(block.id),
                    "evidence_sha256": evidence_sha256,
                }
            )
            invalidation = await self.session.scalar(
                select(AcceptedBlockInvalidation).where(
                    AcceptedBlockInvalidation.tenant_id == self.scope.tenant_id,
                    AcceptedBlockInvalidation.accepted_block_id == block.id,
                )
            )
            invalidation_replayed = invalidation is not None
            requested = (
                self.scope.document_id,
                processing_job_id,
                document_version_id,
                block.generation,
                block.shard_id,
                block.attempt_id,
                block.id,
                recovery.id,
                "invalidated",
                "accepted_output_worker_quarantined",
                invalidation_key,
                operation_sha256,
                evidence,
                evidence_sha256,
                refund_key,
                amount,
                refund.id,
            )
            if invalidation is not None:
                persisted = (
                    invalidation.document_id,
                    invalidation.processing_job_id,
                    invalidation.document_version_id,
                    invalidation.generation,
                    invalidation.shard_id,
                    invalidation.attempt_id,
                    invalidation.accepted_block_id,
                    invalidation.recovery_task_id,
                    invalidation.action,
                    invalidation.reason_code,
                    invalidation.operation_key,
                    invalidation.operation_sha256,
                    invalidation.evidence,
                    invalidation.evidence_sha256,
                    invalidation.refund_settlement_key,
                    Decimal(invalidation.refund_amount),
                    invalidation.refund_ledger_id,
                )
                if persisted != requested:
                    raise ParallelRuntimeConflict(
                        "accepted-block invalidation replay differs from durable evidence"
                    )
            else:
                invalidation = AcceptedBlockInvalidation(
                    tenant_id=self.scope.tenant_id,
                    document_id=self.scope.document_id,
                    processing_job_id=processing_job_id,
                    document_version_id=document_version_id,
                    generation=block.generation,
                    shard_id=block.shard_id,
                    attempt_id=block.attempt_id,
                    accepted_block_id=block.id,
                    recovery_task_id=recovery.id,
                    action="invalidated",
                    reason_code="accepted_output_worker_quarantined",
                    operation_key=invalidation_key,
                    operation_sha256=operation_sha256,
                    evidence=evidence,
                    evidence_sha256=evidence_sha256,
                    refund_settlement_key=refund_key,
                    refund_amount=amount,
                    refund_ledger_id=refund.id,
                )
                self.session.add(invalidation)
                await self.session.flush()
                new_invalidation_count += 1
            invalidations.append(invalidation)
            refunds.append(refund)
            recoveries.append(recovery)
            recovery_events.append(recovery_event)
            all_replayed = all_replayed and all(
                (
                    recovery_replayed,
                    recovery_event_replayed,
                    refund_replayed,
                    invalidation_replayed,
                )
            )
        blocks_by_shard: dict[uuid.UUID, list[AcceptedBlock]] = {}
        for block in blocks:
            blocks_by_shard.setdefault(block.shard_id, []).append(block)
        for attempt in attempts:
            shard = await self._load_shard(attempt.shard_id)
            invalidated_on_shard = blocks_by_shard.get(shard.id, [])
            active_blocks = list(
                (
                    await self.session.scalars(
                        select(AcceptedBlock).where(
                            AcceptedBlock.tenant_id == self.scope.tenant_id,
                            AcceptedBlock.document_id == self.scope.document_id,
                            AcceptedBlock.processing_job_id == processing_job_id,
                            AcceptedBlock.document_version_id == document_version_id,
                            AcceptedBlock.shard_id == shard.id,
                            ~AcceptedBlock.id.in_(
                                select(AcceptedBlockInvalidation.accepted_block_id).where(
                                    AcceptedBlockInvalidation.tenant_id == self.scope.tenant_id,
                                    AcceptedBlockInvalidation.processing_job_id
                                    == processing_job_id,
                                    AcceptedBlockInvalidation.document_version_id
                                    == document_version_id,
                                )
                            ),
                        )
                    )
                ).all()
            )
            active_by_key = {item.logical_block_key: item for item in active_blocks}
            fully_recovered = bool(invalidated_on_shard) and all(
                old.logical_block_key in active_by_key
                and active_by_key[old.logical_block_key].generation > old.generation
                for old in invalidated_on_shard
            )
            if not fully_recovered:
                shard.status = "QUARANTINED"
                shard.updated_at = utcnow()
        await self._project_worker_quarantine_recovery(
            new_invalidation_count=new_invalidation_count,
        )
        return (
            tuple(invalidations),
            tuple(refunds),
            tuple(recoveries),
            tuple(recovery_events),
            all_replayed,
        )

    def _worker_event_payload(
        self,
        *,
        event_type: str,
        worker: WorkerHealth,
        semantic_score: Decimal,
        reason_codes: Sequence[str],
        impacted_attempt_ids: Sequence[uuid.UUID],
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "collection_id": str(self.scope.collection_id),
            "worker_health_id": str(worker.id),
            "worker_id": worker.worker_id,
            "pool_key": worker.pool_key,
            "worker_state": worker.state,
            "reason_codes": list(reason_codes),
        }
        if event_type == "worker.semantic.degraded.v1":
            base["semantic_score"] = _decimal_string(semantic_score)
        elif event_type == "worker.quarantined.v1":
            base["impacted_attempt_count"] = len(impacted_attempt_ids)
        return base

    async def request_recovery(
        self,
        shard_id: uuid.UUID,
        task: CoreRecoveryTask,
        *,
        reason_codes: Sequence[str],
        operation_key: str,
    ) -> DurableWrite[RecoveryTask]:
        """Persist a smallest-scope immutable recovery request."""

        reasons = tuple(reason_codes)
        if not reasons:
            raise ValueError("recovery requires at least one reason code")
        async with self.session.begin_nested():
            await self._assert_scope()
            shard = await self._load_shard(shard_id)
            base_id = _uuid_string(task.base_attempt_id, field="base_attempt_id")
            base, base_shard = await self._load_attempt(base_id)
            if base_shard.id != shard.id or base.output_sha256 != task.base_prediction_sha256:
                raise ParallelRuntimeConflict("recovery base evidence does not match its shard")
            target = {
                "core_task_id": task.task_id,
                "scope_id": task.scope.scope_id,
                "source_refs": list(task.scope.source_refs),
                "base_prediction_sha256": task.base_prediction_sha256,
            }
            variants = [task.variant.value]
            routes = [task.parser_recipe]
            idempotency_key = _store_key("recovery", operation_key)
            existing = await self.session.scalar(
                select(RecoveryTask).where(
                    RecoveryTask.tenant_id == self.scope.tenant_id,
                    RecoveryTask.idempotency_key == idempotency_key,
                )
            )
            if existing is not None and (
                existing.document_id != self.scope.document_id
                or existing.shard_id != shard.id
                or existing.source_attempt_id != base.id
                or existing.recovery_level != task.scope.level.value
                or existing.reason_code != reasons[0]
                or existing.target != target
                or existing.preprocessing_variants != variants
                or existing.route_candidates != routes
            ):
                raise ParallelRuntimeConflict(
                    "recovery operation key was reused with different input"
                )
            row, row_replayed = await request_recovery(
                self.session,
                tenant_id=self.scope.tenant_id,
                document_id=self.scope.document_id,
                shard_id=shard.id,
                source_attempt_id=base.id,
                recovery_level=task.scope.level.value,
                reason_code=reasons[0],
                target=target,
                preprocessing_variants=variants,
                route_candidates=routes,
                idempotency_key=idempotency_key,
            )
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(shard.id),
                "source_attempt_id": str(base.id),
                "recovery_task_id": str(row.id),
                "recovery_level": row.recovery_level,
                "reason_codes": list(reasons),
                "recovery_state": "REQUESTED",
            }
            event, event_replayed = await self._emit_once(
                event_type="recovery.region.requested.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(row, event, row_replayed and event_replayed)

    async def complete_recovery(
        self,
        recovery_task_id: uuid.UUID,
        decision: CoreRecoveryDecision,
        *,
        observed_result_attempt_id: uuid.UUID,
        operation_key: str,
    ) -> DurableWrite[RecoveryTask]:
        """Complete recovery while preserving unsuccessful candidate lineage."""

        async with self.session.begin_nested():
            await self._assert_scope()
            row = await self.session.scalar(
                select(RecoveryTask)
                .where(
                    RecoveryTask.tenant_id == self.scope.tenant_id,
                    RecoveryTask.id == recovery_task_id,
                    RecoveryTask.document_id == self.scope.document_id,
                )
                .with_for_update()
            )
            if row is None or row.target.get("core_task_id") != decision.task_id:
                raise ParallelRuntimeConflict("recovery decision does not match its durable task")
            require_sha256(decision.decision_sha256, field_name="recovery.decision_sha256")
            source, source_shard = await self._load_attempt(row.source_attempt_id)
            observed, observed_shard = await self._load_attempt(observed_result_attempt_id)
            if source_shard.id != row.shard_id or observed_shard.id != row.shard_id:
                raise ParallelRuntimeConflict("recovery result belongs to another shard")
            if (
                source.output_sha256 is None
                or source.output_sha256 != decision.base_prediction_sha256
            ):
                raise ParallelRuntimeConflict(
                    "recovery decision differs from its immutable base prediction"
                )
            if decision.accepted:
                selected_id = _uuid_string(
                    decision.selected_attempt_id or "", field="selected_recovery_attempt_id"
                )
                if (
                    selected_id != observed.id
                    or decision.state not in ACCEPTED_VERIFICATION_STATES
                    or observed.output_sha256 is None
                    or decision.repaired_prediction_sha256 != observed.output_sha256
                ):
                    raise ParallelRuntimeConflict(
                        "accepted recovery did not select its observed result"
                    )
                target_state = "COMPLETED"
                persisted_result_id: uuid.UUID | None = observed.id
            else:
                if decision.selected_attempt_id is not None:
                    raise ParallelRuntimeConflict("unaccepted recovery cannot select a winner")
                if (
                    decision.repaired_prediction_sha256 is not None
                    and decision.repaired_prediction_sha256 != observed.output_sha256
                ):
                    raise ParallelRuntimeConflict(
                        "unaccepted recovery differs from its observed prediction"
                    )
                target_state = (
                    "FAILED" if decision.state is VerificationState.FAILED else "UNRESOLVED"
                )
                persisted_result_id = None
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "shard_id": str(row.shard_id),
                "recovery_task_id": str(row.id),
                "result_attempt_id": str(observed.id),
                "recovery_level": row.recovery_level,
                "final_state": decision.state.value,
            }
            existing_event = await self._existing_event(
                event_type="recovery.completed.v1",
                operation_key=operation_key,
                payload=payload,
            )
            if existing_event is not None:
                if row.state != target_state or row.result_attempt_id != persisted_result_id:
                    raise ParallelRuntimeConflict("recovery event lost its terminal projection")
                return DurableWrite(row, existing_event, True)
            if row.state in {"COMPLETED", "UNRESOLVED", "FAILED", "CANCELLED"}:
                raise ParallelRuntimeConflict("terminal recovery task is immutable")
            row.state = target_state
            row.result_attempt_id = persisted_result_id
            row.completed_at = utcnow()
            event, _ = await self._emit_once(
                event_type="recovery.completed.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(row, event, False)

    async def start_continuity(
        self,
        *,
        merge_revision: str,
        edges: Sequence[ContinuityEdgeInput],
        operation_key: str,
    ) -> ContinuityWrite:
        """Persist immutable continuity candidates and the merge-start event."""

        async with self.session.begin_nested():
            await self._assert_scope()
            rows: list[ContinuityEdge] = []
            all_replayed = True
            for candidate in edges:
                source = await self._load_shard(candidate.source_shard_id)
                target = await self._load_shard(candidate.target_shard_id)
                if source.id == target.id:
                    raise ParallelRuntimeConflict("continuity edge cannot be self-referential")
                evidence = dict(candidate.evidence)
                evidence_sha256 = canonical_sha256(evidence)
                existing = await self.session.scalar(
                    select(ContinuityEdge).where(
                        ContinuityEdge.document_id == self.scope.document_id,
                        ContinuityEdge.source_shard_id == source.id,
                        ContinuityEdge.target_shard_id == target.id,
                        ContinuityEdge.edge_type == candidate.edge_type,
                        ContinuityEdge.merge_revision == merge_revision,
                    )
                )
                if existing is not None:
                    if (
                        existing.tenant_id != self.scope.tenant_id
                        or Decimal(existing.confidence) != Decimal(candidate.confidence)
                        or existing.authority != candidate.authority
                        or existing.evidence_sha256 != evidence_sha256
                        or existing.evidence != evidence
                    ):
                        raise ParallelRuntimeConflict("continuity edge identity was reused")
                    rows.append(existing)
                    continue
                row = ContinuityEdge(
                    tenant_id=self.scope.tenant_id,
                    document_id=self.scope.document_id,
                    source_shard_id=source.id,
                    target_shard_id=target.id,
                    edge_type=candidate.edge_type,
                    confidence=Decimal(candidate.confidence),
                    authority=candidate.authority,
                    evidence=evidence,
                    evidence_sha256=evidence_sha256,
                    merge_revision=merge_revision,
                    status="candidate",
                )
                self.session.add(row)
                await self.session.flush()
                rows.append(row)
                all_replayed = False
            accepted_blocks = list(
                (
                    await self.session.scalars(
                        select(AcceptedBlock).where(
                            AcceptedBlock.tenant_id == self.scope.tenant_id,
                            AcceptedBlock.document_id == self.scope.document_id,
                        )
                    )
                ).all()
            )
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "merge_revision": merge_revision,
                "candidate_edge_count": len(rows),
                "accepted_block_count": len(accepted_blocks),
            }
            event, event_replayed = await self._emit_once(
                event_type="continuity.merge.started.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return ContinuityWrite(tuple(rows), event, all_replayed and event_replayed)

    async def complete_continuity(
        self,
        result: ContinuityMergeResult,
        *,
        merge_revision: str,
        accepted_edge_ids: Sequence[uuid.UUID],
        operation_key: str,
    ) -> ContinuityWrite:
        """Promote only explicitly accepted edges and persist conservation counts."""

        async with self.session.begin_nested():
            await self._assert_scope()
            require_sha256(result.merge_sha256, field_name="continuity.merge_sha256")
            rows = list(
                (
                    await self.session.scalars(
                        select(ContinuityEdge)
                        .where(
                            ContinuityEdge.tenant_id == self.scope.tenant_id,
                            ContinuityEdge.document_id == self.scope.document_id,
                            ContinuityEdge.merge_revision == merge_revision,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            accepted_ids = set(accepted_edge_ids)
            if accepted_ids - {row.id for row in rows}:
                raise ParallelRuntimeConflict("accepted continuity edge is outside the merge")
            desired = {
                row.id: (
                    "accepted"
                    if result.accepted and row.id in accepted_ids
                    else "rejected"
                    if result.accepted
                    else "unresolved"
                )
                for row in rows
            }
            source_pages = {page_id for block in result.blocks for page_id in block.page_ids}
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "merge_revision": merge_revision,
                "accepted_edge_count": len(accepted_ids) if result.accepted else 0,
                "deduplicated_block_count": len(result.dropped_marginal_block_ids),
                "source_coverage_count": len(source_pages),
                "unresolved_count": 0 if result.accepted else max(1, len(result.reason_codes)),
                "continuity_sha256": result.merge_sha256,
            }
            existing_event = await self._existing_event(
                event_type="continuity.merge.completed.v1",
                operation_key=operation_key,
                payload=payload,
            )
            if existing_event is not None:
                if any(row.status != desired[row.id] for row in rows):
                    raise ParallelRuntimeConflict("continuity event lost its edge projection")
                return ContinuityWrite(tuple(rows), existing_event, True)
            for row in rows:
                if row.status not in {"candidate", desired[row.id]}:
                    raise ParallelRuntimeConflict("terminal continuity edge cannot be reclassified")
                row.status = desired[row.id]
            event, _ = await self._emit_once(
                event_type="continuity.merge.completed.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return ContinuityWrite(tuple(rows), event, False)

    async def admit_gpu_invocation_result(
        self,
        invocation_id: uuid.UUID,
        validation: ValidationResult,
        decision: CoreArbitrationDecision,
        *,
        worker_id: str,
        signing_key: bytes,
    ) -> GpuAdmissionWrite:
        """Atomically validate, arbitrate, and settle one completed GPU output.

        GPU completion itself only creates the immutable output receipt and
        moves its parse attempt toward validation.  This separate entrypoint
        requires a server-signed ``parallel_v6_verification`` envelope that
        binds the validator revisions, decision digest, result manifest,
        output checksum, settlement amount, and exact durable scope.  It is the
        only bridge here that can turn a provider result into a billable block.
        """

        async with self.session.begin_nested():
            _, document, job = await self._assert_scope()
            if job is None or self.scope.processing_job_id is None:
                raise ParallelRuntimeConflict(
                    "GPU admission requires an explicitly scoped processing job"
                )
            invocation = await self.session.scalar(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == self.scope.tenant_id,
                    GpuProviderInvocation.id == invocation_id,
                    GpuProviderInvocation.job_id == self.scope.processing_job_id,
                    GpuProviderInvocation.document_id == self.scope.document_id,
                    GpuProviderInvocation.project_id == document.project_id,
                )
                .with_for_update()
            )
            if invocation is None:
                raise ParallelRuntimeConflict("GPU invocation is outside the durable scope")
            if (
                invocation.status != "completed"
                or invocation.result_manifest is None
                or invocation.result_manifest_sha256 is None
                or invocation.completed_at is None
            ):
                raise ParallelRuntimeConflict(
                    "GPU invocation has no completed immutable result manifest"
                )
            if not isinstance(invocation.options, dict):
                raise ParallelRuntimeConflict("GPU invocation options are malformed")
            output_value = invocation.options.get("parallel_v6")
            verification_value = invocation.options.get("parallel_v6_verification")
            if output_value is None or verification_value is None:
                raise ParallelRuntimeConflict(
                    "GPU invocation is missing a v6 output or verification envelope"
                )
            output_body = _envelope_mapping(output_value, field="parallel_v6")
            output_envelope = _parse_parallel_v6_output_envelope(output_body)
            verification = _parse_parallel_v6_verification_envelope(
                verification_value,
                signing_key=signing_key,
            )

            durable_scope = (
                self.scope.tenant_id,
                self.scope.collection_id,
                self.scope.document_id,
                self.scope.processing_job_id,
            )
            if (
                output_envelope.tenant_id,
                output_envelope.collection_id,
                output_envelope.document_id,
                output_envelope.processing_job_id,
            ) != durable_scope or (
                verification.tenant_id,
                verification.collection_id,
                verification.document_id,
                verification.processing_job_id,
            ) != durable_scope:
                raise ParallelRuntimeConflict("GPU envelopes cross the durable scope")
            if (
                verification.provider_invocation_id != invocation.id
                or verification.output_envelope_sha256 != runtime_canonical_sha256(output_body)
                or output_envelope.document_version_id != invocation.document_version_id
                or verification.document_version_id != invocation.document_version_id
                or output_envelope.expected_input_sha256 != invocation.input_sha256
                or output_envelope.expected_output_object_key != invocation.output_object_key
                or output_envelope.expected_model_revision != invocation.model_revision
                or output_envelope.expected_runtime_image_digest != invocation.runtime_image_digest
                or output_envelope.expected_adapter_version != invocation.adapter_version
            ):
                raise ParallelRuntimeConflict("GPU envelopes do not bind the completed invocation")

            attempt, shard = await self._load_attempt(verification.attempt_id)
            if (
                output_envelope.attempt_id != attempt.id
                or output_envelope.shard_id != shard.id
                or verification.shard_id != shard.id
                or attempt.provider_invocation_id != invocation.id
                or output_envelope.expected_shard_input_sha256 != shard.input_sha256
                or output_envelope.expected_request_sha256 != attempt.request_sha256
                or attempt.model_revision != invocation.model_revision
                or attempt.runtime_identity != invocation.runtime_image_digest
                or attempt.worker_id != worker_id
            ):
                raise ParallelRuntimeConflict(
                    "GPU invocation is not bound to the durable parse attempt"
                )
            if attempt.state not in {
                "OUTPUT_RECEIVED",
                "VALIDATING",
                "ACCEPTED",
                "REJECTED",
                "QUARANTINED",
            }:
                raise ParallelRuntimeConflict(
                    "GPU verification requires an admitted output receipt"
                )
            if verification.required_levels != self._required_levels(shard):
                raise ParallelRuntimeConflict(
                    "signed validation policy differs from the planned shard"
                )
            for level in verification.required_levels:
                if self._pinned_validator(shard, level) != verification.validator_revisions[level]:
                    raise ParallelRuntimeConflict(
                        "signed validator revision differs from the planned pin"
                    )

            manifest = _envelope_mapping(
                invocation.result_manifest,
                field="gpu.result_manifest",
            )
            manifest_sha256 = canonical_sha256(manifest)
            if (
                manifest_sha256 != invocation.result_manifest_sha256
                or manifest_sha256 != verification.result_manifest_sha256
            ):
                raise ParallelRuntimeConflict("GPU result manifest digest is invalid")
            required_manifest_fields = {
                "schema_version",
                "invocation_id",
                "job_id",
                "tenant_id",
                "provider",
                "provider_job_id",
                "endpoint_id",
                "provider_key",
                "model_revision",
                "runtime_image_digest",
                "adapter_version",
                "result_id",
                "output_object_key",
                "output_sha256",
                "output_bytes",
                "metrics",
                "warning_count",
                "warning_sha256",
                "raw_provider_response_sha256",
                "completion_source",
            }
            optional_manifest_fields = {
                "knowledge_attestation",
                "visual_attestation",
            }
            if (
                set(manifest) - required_manifest_fields
            ) - optional_manifest_fields or not required_manifest_fields <= set(manifest):
                raise ParallelRuntimeConflict("GPU result manifest shape is invalid")
            manifest_output = manifest.get("output_sha256")
            if not isinstance(manifest_output, str):
                raise ParallelRuntimeConflict("GPU result output digest is invalid")
            normalized_output_sha256 = manifest_output.removeprefix("sha256:")
            _envelope_sha256(
                normalized_output_sha256,
                field="gpu.result_manifest.output_sha256",
            )
            expected_manifest_values: Mapping[str, object] = {
                "schema_version": "1.0",
                "invocation_id": str(invocation.id),
                "job_id": str(invocation.job_id),
                "tenant_id": str(invocation.tenant_id),
                "provider": invocation.provider,
                "provider_job_id": invocation.provider_job_id,
                "endpoint_id": invocation.endpoint_id,
                "provider_key": invocation.provider_key,
                "model_revision": invocation.model_revision,
                "runtime_image_digest": invocation.runtime_image_digest,
                "adapter_version": invocation.adapter_version,
                "output_object_key": invocation.output_object_key,
                "completion_source": invocation.completion_source,
            }
            if any(
                manifest.get(field) != expected
                for field, expected in expected_manifest_values.items()
            ):
                raise ParallelRuntimeConflict("GPU result manifest identity is invalid")
            metrics = manifest.get("metrics")
            if not isinstance(metrics, dict):
                raise ParallelRuntimeConflict("GPU result manifest metrics are malformed")
            gpu_seconds = _manifest_metric(
                metrics,
                "gpu_seconds",
                maximum=_MAX_GPU_SECONDS,
            )
            provider_cost = _manifest_metric(
                metrics,
                "estimated_cost_usd",
                maximum=_MAX_PROVIDER_COST_USD,
            )
            expected_gpu_milliseconds = int(
                (gpu_seconds * Decimal("1000")).to_integral_value(rounding=ROUND_HALF_UP)
            )
            summary = attempt.output_summary
            if not isinstance(summary, dict):
                raise ParallelRuntimeConflict("GPU attempt output summary is malformed")
            summary_bindings: Mapping[str, object] = {
                "provider_invocation_id": str(invocation.id),
                "provider_job_id": manifest.get("provider_job_id"),
                "provider_key": manifest.get("provider_key"),
                "endpoint_id": manifest.get("endpoint_id"),
                "result_id": manifest.get("result_id"),
                "completion_source": manifest.get("completion_source"),
                "raw_provider_response_sha256": manifest.get("raw_provider_response_sha256"),
            }
            if (
                any(summary.get(field) != expected for field, expected in summary_bindings.items())
                or attempt.output_artifact_key != invocation.output_object_key
                or attempt.output_sha256 != normalized_output_sha256
                or verification.output_sha256 != normalized_output_sha256
                or attempt.gpu_milliseconds != expected_gpu_milliseconds
                or Decimal(attempt.cost_usd) != provider_cost
            ):
                raise ParallelRuntimeConflict(
                    "GPU result manifest differs from its admitted output receipt"
                )

            if (
                validation.digest != verification.validation_digest
                or decision.decision_sha256 != verification.arbitration_decision_sha256
            ):
                raise ParallelRuntimeConflict(
                    "signed verification digests differ from the supplied decisions"
                )
            selected_attempt_id = (
                None
                if decision.selected_attempt_id is None
                else _uuid_string(
                    decision.selected_attempt_id,
                    field="decision.selected_attempt_id",
                )
            )
            if selected_attempt_id != verification.selected_attempt_id:
                raise ParallelRuntimeConflict("signed winner differs from the arbitration decision")
            if decision.accepted:
                if (
                    selected_attempt_id != attempt.id
                    or verification.logical_block_key is None
                    or verification.credit_amount <= 0
                    or decision.selected_prediction_sha256 != verification.output_sha256
                ):
                    raise ParallelRuntimeConflict(
                        "accepted GPU decision lacks a signed winner or settlement"
                    )
            elif (
                selected_attempt_id is not None
                or verification.logical_block_key is not None
                or verification.credit_amount != 0
            ):
                raise ParallelRuntimeConflict(
                    "unaccepted GPU decision cannot carry a winner or settlement"
                )

            validation_write = await self.persist_validation(
                attempt.id,
                validation,
                validator_revisions=verification.validator_revisions,
                operation_key=f"{verification.operation_prefix}:validation",
            )
            arbitration_write = await self.persist_arbitration(
                shard.id,
                decision,
                policy_version=verification.arbitration_policy_version,
                evidence={
                    "provider_invocation_id": str(invocation.id),
                    "result_manifest_sha256": manifest_sha256,
                    "output_envelope_sha256": verification.output_envelope_sha256,
                    "verification_envelope_sha256": verification.envelope_sha256,
                    "verification_signature_sha256": verification.signature_sha256,
                },
                operation_key=f"{verification.operation_prefix}:arbitration",
                priced_credit_amount=(
                    verification.credit_amount if decision.accepted else Decimal("0")
                ),
            )
            acceptance: AcceptanceWrite | None = None
            rejection: DurableWrite[ParallelParseAttempt] | None = None
            if decision.accepted:
                if verification.logical_block_key is None:
                    raise AssertionError("accepted envelope lost its logical block key")
                acceptance = await self.accept(
                    arbitration_write.row.id,
                    logical_block_key=verification.logical_block_key,
                    artifact_key=invocation.output_object_key,
                    artifact_sha256=verification.output_sha256,
                    provenance={
                        "provider_invocation_id": str(invocation.id),
                        "result_manifest_sha256": manifest_sha256,
                        "output_envelope_sha256": verification.output_envelope_sha256,
                        "verification_envelope_sha256": verification.envelope_sha256,
                        "verification_signature_sha256": verification.signature_sha256,
                    },
                    credit_amount=verification.credit_amount,
                    operation_key=f"{verification.operation_prefix}:accept",
                )
            else:
                rejection = await self.reject(
                    attempt.id,
                    target_state=(
                        "QUARANTINED"
                        if decision.verification_state is VerificationState.QUARANTINED
                        else "REJECTED"
                    ),
                    failure_domain="semantic",
                    reason_codes=decision.reason_codes or ("verification_failed",),
                    operation_key=f"{verification.operation_prefix}:reject",
                )
            await self.session.flush()
            return GpuAdmissionWrite(
                attempt=attempt,
                validation=validation_write,
                arbitration=arbitration_write.row,
                acceptance=acceptance,
                rejection=rejection,
            )

    async def finalize_document(
        self,
        result: FinalizationResult,
        *,
        operation_key: str,
    ) -> DurableWrite[Document]:
        """Project the core finalization only when durable evidence agrees."""

        async with self.session.begin_nested():
            _, document, job = await self._assert_scope()
            processing_job_id, document_version_id = self._require_execution_scope()
            if job is None:
                raise ParallelRuntimeConflict("finalization lost its processing job projection")
            require_sha256(result.manifest_sha256, field_name="finalization.manifest_sha256")
            require_sha256(result.merge_sha256, field_name="finalization.merge_sha256")
            if result.document_version_id != document_version_id:
                raise ParallelRuntimeConflict(
                    "finalization targets a different durable document version"
                )
            blocks = list(
                (
                    await self.session.scalars(
                        select(AcceptedBlock).where(
                            AcceptedBlock.tenant_id == self.scope.tenant_id,
                            AcceptedBlock.document_id == self.scope.document_id,
                            AcceptedBlock.processing_job_id == processing_job_id,
                            AcceptedBlock.document_version_id == document_version_id,
                            AcceptedBlock.billable.is_(True),
                            ~AcceptedBlock.id.in_(
                                select(AcceptedBlockInvalidation.accepted_block_id).where(
                                    AcceptedBlockInvalidation.tenant_id == self.scope.tenant_id,
                                    AcceptedBlockInvalidation.processing_job_id
                                    == processing_job_id,
                                    AcceptedBlockInvalidation.document_version_id
                                    == document_version_id,
                                )
                            ),
                        )
                    )
                ).all()
            )
            shards = list(
                (
                    await self.session.scalars(
                        select(ParallelParseShard).where(
                            ParallelParseShard.tenant_id == self.scope.tenant_id,
                            ParallelParseShard.document_id == self.scope.document_id,
                            ParallelParseShard.collection_id == self.scope.collection_id,
                            ParallelParseShard.processing_job_id == processing_job_id,
                            ParallelParseShard.document_version_id == document_version_id,
                        )
                    )
                ).all()
            )
            if not shards:
                raise ParallelRuntimeConflict(
                    "finalization requires at least one current job/version shard"
                )
            block_by_key = {block.logical_block_key: block for block in blocks}
            if len(block_by_key) != len(blocks):
                raise ParallelRuntimeConflict(
                    "multiple active accepted blocks own one logical unit"
                )
            block_keys = set(block_by_key)
            accepted_unit_ids = {unit.unit_id for unit in result.accepted_units}
            if block_keys != accepted_unit_ids or block_keys != set(result.billable_unit_ids):
                raise ParallelRuntimeConflict(
                    "finalization units differ from durable accepted blocks"
                )
            for unit in result.accepted_units:
                block = block_by_key[unit.unit_id]
                source_refs = block.provenance.get("source_refs")
                provenance_attempt_ids = block.provenance.get("provenance_attempt_ids")
                if (
                    not isinstance(source_refs, list)
                    or not source_refs
                    or any(not isinstance(item, str) or not item for item in source_refs)
                    or not isinstance(provenance_attempt_ids, list)
                    or not provenance_attempt_ids
                    or any(not isinstance(item, str) or not item for item in provenance_attempt_ids)
                ):
                    raise ParallelRuntimeConflict(
                        "accepted block lost its source or attempt provenance"
                    )
                if (
                    unit.prediction_sha256 != block.artifact_sha256
                    or unit.state.value != block.final_state
                    or unit.source_refs != tuple(source_refs)
                    or unit.provenance_attempt_ids != tuple(provenance_attempt_ids)
                    or str(block.attempt_id) not in provenance_attempt_ids
                ):
                    raise ParallelRuntimeConflict(
                        "finalization unit differs from its active accepted block"
                    )
            expected_manifest_sha256 = runtime_canonical_sha256(
                {
                    "document_version_id": document_version_id,
                    "merge_sha256": result.merge_sha256,
                    "accepted_unit_ids": tuple(unit.unit_id for unit in result.accepted_units),
                    "unresolved": result.unresolved_manifest,
                    "excluded": result.excluded_unit_ids,
                    "publishable": result.publishable,
                    "reason_codes": result.reason_codes,
                }
            )
            if result.manifest_sha256 != expected_manifest_sha256:
                raise ParallelRuntimeConflict(
                    "finalization manifest is not the canonical durable material"
                )
            required_shards = [shard for shard in shards if shard.status != "SUPERSEDED"]
            if not required_shards:
                raise ParallelRuntimeConflict(
                    "finalization has no required current job/version shard"
                )
            manifest_shard_keys = {item.unit_id for item in result.unresolved_manifest} | set(
                result.excluded_unit_ids
            )
            known_shard_keys = {shard.shard_key for shard in required_shards}
            if manifest_shard_keys - known_shard_keys:
                raise ParallelRuntimeConflict("failure manifest references a foreign durable shard")
            covered_shard_ids = {block.shard_id for block in blocks} | {
                shard.id for shard in required_shards if shard.shard_key in manifest_shard_keys
            }
            missing_shards = {shard.id for shard in required_shards} - covered_shard_ids
            if missing_shards:
                raise ParallelRuntimeConflict(
                    "finalization omits required current job/version shards"
                )
            total_credits = Decimal("0")
            for block in blocks:
                if block.credit_settlement_key is None:
                    raise ParallelRuntimeConflict("billable block lost its settlement key")
                ledger = await self.session.scalar(
                    select(CreditLedger).where(
                        CreditLedger.tenant_id == self.scope.tenant_id,
                        CreditLedger.operation_key == block.credit_settlement_key,
                    )
                )
                if (
                    ledger is None
                    or ledger.entry_type != "consume"
                    or ledger.job_id != processing_job_id
                    or Decimal(ledger.credits) != Decimal(block.credit_amount)
                ):
                    raise ParallelRuntimeConflict("billable block lost its credit ledger")
                total_credits += Decimal(block.credit_amount)
            unresolved_shards = sum(shard.status == "UNRESOLVED" for shard in shards)
            quarantined_shards = sum(shard.status == "QUARANTINED" for shard in shards)
            failed_shards = sum(shard.status == "FAILED" for shard in shards)
            incomplete_shards = [
                shard
                for shard in shards
                if shard.status
                not in {
                    "ACCEPTED",
                    "SUPERSEDED",
                    "UNRESOLVED",
                    "QUARANTINED",
                    "FAILED",
                }
            ]
            durably_publishable = bool(blocks) and all(
                shard.status == "ACCEPTED" and any(block.shard_id == shard.id for block in blocks)
                for shard in required_shards
            )
            if result.publishable != durably_publishable:
                raise ParallelRuntimeConflict(
                    "caller publishability differs from current durable evidence"
                )
            if result.publishable and (
                result.unresolved_manifest
                or result.excluded_unit_ids
                or unresolved_shards
                or quarantined_shards
                or failed_shards
                or incomplete_shards
            ):
                raise ParallelRuntimeConflict(
                    "publishable finalization has unresolved durable work"
                )
            if not result.publishable and not (
                result.unresolved_manifest
                or result.excluded_unit_ids
                or unresolved_shards
                or quarantined_shards
                or failed_shards
                or incomplete_shards
                or result.reason_codes
            ):
                raise ParallelRuntimeConflict(
                    "non-publishable finalization lacks a failure manifest"
                )
            if result.publishable:
                states = {unit.state for unit in result.accepted_units}
                final_state = (
                    VerificationState.AUTO_REPAIRED.value
                    if VerificationState.AUTO_REPAIRED in states
                    else VerificationState.CROSS_MODEL_VERIFIED.value
                    if VerificationState.CROSS_MODEL_VERIFIED in states
                    else VerificationState.AUTHORITY_VERIFIED.value
                    if VerificationState.AUTHORITY_VERIFIED in states
                    else VerificationState.VERIFIED.value
                )
                document_status = "COMPLETED"
            elif quarantined_shards or any(
                item in result.excluded_unit_ids for item in (shard.shard_key for shard in shards)
            ):
                final_state = VerificationState.QUARANTINED.value
                document_status = "QUARANTINED"
            elif failed_shards:
                final_state = VerificationState.FAILED.value
                document_status = "FAILED"
            else:
                final_state = VerificationState.UNRESOLVED.value
                document_status = "PARTIAL"
            payload = {
                "collection_id": str(self.scope.collection_id),
                "document_id": str(self.scope.document_id),
                "final_state": final_state,
                "verified_block_count": len(blocks),
                "unresolved_count": max(len(result.unresolved_manifest), unresolved_shards),
                "quarantined_count": quarantined_shards,
                "manifest_sha256": result.manifest_sha256,
                "billable_credits": _decimal_string(total_credits),
            }
            existing_event = await self._existing_event(
                event_type="document.finalized.v1",
                operation_key=operation_key,
                payload=payload,
            )
            expected_job_status = "completed" if result.publishable else "waiting_review"
            if existing_event is not None:
                if (
                    document.status != document_status
                    or job.status != expected_job_status
                    or (result.publishable and job.completed_at is None)
                    or (not result.publishable and job.completed_at is not None)
                ):
                    raise ParallelRuntimeConflict(
                        "finalization event lost its document or processing job projection"
                    )
                replay_progress = job.progress if isinstance(job.progress, dict) else {}
                replay_recovery = replay_progress.get(_RECOVERY_PROJECTION_KEY)
                if replay_recovery is not None:
                    recovered = self._verified_recovery_projection(replay_recovery)
                    replay_completion = recovered["completion"]
                    if result.publishable and (
                        recovered["phase"] != "completed"
                        or not isinstance(replay_completion, dict)
                        or replay_completion["manifest_sha256"] != result.manifest_sha256
                    ):
                        raise ParallelRuntimeConflict(
                            "replayed recovery finalization lost its completion evidence"
                        )
                return DurableWrite(document, existing_event, True)
            progress = dict(job.progress) if isinstance(job.progress, dict) else {}
            recovery_projection_value = progress.get(_RECOVERY_PROJECTION_KEY)
            if recovery_projection_value is not None:
                recovery_projection = self._verified_recovery_projection(recovery_projection_value)
                if (
                    recovery_projection["document_id"] != str(self.scope.document_id)
                    or recovery_projection["processing_job_id"] != str(processing_job_id)
                    or recovery_projection["document_version_id"] != document_version_id
                ):
                    raise ParallelRuntimeConflict(
                        "finalization recovery projection is outside the durable scope"
                    )
                recovery_completion: dict[str, Any] | None = None
                recovery_phase = "needs_review"
                if result.publishable:
                    invalidated_ids = [
                        _uuid_string(item, field="recovery_projection.accepted_block_id")
                        for item in recovery_projection["accepted_block_ids"]
                    ]
                    invalidated_blocks = list(
                        (
                            await self.session.scalars(
                                select(AcceptedBlock).where(
                                    AcceptedBlock.tenant_id == self.scope.tenant_id,
                                    AcceptedBlock.id.in_(tuple(invalidated_ids)),
                                )
                            )
                        ).all()
                    )
                    if len(invalidated_blocks) != len(invalidated_ids):
                        raise ParallelRuntimeConflict(
                            "recovery finalization lost its invalidated block lineage"
                        )
                    active_by_key = {block.logical_block_key: block for block in blocks}
                    if any(
                        old.logical_block_key not in active_by_key
                        or active_by_key[old.logical_block_key].generation <= old.generation
                        for old in invalidated_blocks
                    ):
                        raise ParallelRuntimeConflict(
                            "recovery finalization has no newer active replacement generation"
                        )
                    recovery_completion = {
                        "manifest_sha256": result.manifest_sha256,
                        "active_blocks": [
                            {
                                "accepted_block_id": str(block.id),
                                "generation": block.generation,
                                "logical_block_key": block.logical_block_key,
                            }
                            for block in sorted(
                                blocks,
                                key=lambda item: (item.logical_block_key, str(item.id)),
                            )
                        ],
                    }
                    recovery_phase = "completed"
                recovery_body = {
                    **recovery_projection,
                    "phase": recovery_phase,
                    "completion": recovery_completion,
                }
                progress[_RECOVERY_PROJECTION_KEY] = {
                    **recovery_body,
                    "projection_sha256": runtime_canonical_sha256(recovery_body),
                }
            timestamp = utcnow()
            document.status = document_status
            document.updated_at = timestamp
            if job.started_at is None:
                job.started_at = timestamp
            job.status = expected_job_status
            job.completed_at = timestamp if result.publishable else None
            job.error = None if result.publishable else {"codes": list(result.reason_codes)}
            progress.update(
                {
                    "stage": "completed" if result.publishable else "parallel_v6_needs_review",
                    "done": len(required_shards),
                    "total": len(required_shards),
                    "publishable": result.publishable,
                    "finalization_manifest_sha256": result.manifest_sha256,
                }
            )
            job.progress = progress
            event, _ = await self._emit_once(
                event_type="document.finalized.v1",
                operation_key=operation_key,
                payload=payload,
            )
            await self.session.flush()
            return DurableWrite(document, event, False)


async def admit_gpu_invocation_result(
    session: AsyncSession,
    scope: ParallelRuntimeScope,
    invocation_id: uuid.UUID,
    validation: ValidationResult,
    decision: CoreArbitrationDecision,
    *,
    worker_id: str,
    signing_key: bytes,
) -> GpuAdmissionWrite:
    """Public transaction-composable entrypoint for explicit GPU verification."""

    return await DurableParallelOrchestrator(
        session,
        scope,
    ).admit_gpu_invocation_result(
        invocation_id,
        validation,
        decision,
        worker_id=worker_id,
        signing_key=signing_key,
    )


__all__ = [
    "AcceptanceWrite",
    "ContinuityEdgeInput",
    "ContinuityWrite",
    "DurableParallelOrchestrator",
    "DurableWrite",
    "GpuAdmissionWrite",
    "ParallelRuntimeScope",
    "ParallelV6OutputEnvelope",
    "ParallelV6VerificationEnvelope",
    "PlanWrite",
    "PlannedShardWrite",
    "ValidationWrite",
    "ValidatorRevision",
    "WorkerHealthWrite",
    "admit_gpu_invocation_result",
    "sign_parallel_v6_verification",
]
