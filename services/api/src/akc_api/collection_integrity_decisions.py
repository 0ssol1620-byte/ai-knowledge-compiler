"""Audited customer decisions for collection integrity findings.

The boundary is intentionally code-and-reference only: it accepts no free
text, document body, filename, path, password, or secret-store locator.  A
decision is immutable, is committed with its audit and canonical collection
event, and can act only on an open finding while the collection has no active
processing job.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Annotated, Literal, Self, cast

from akc_cir import validate_collection_event_payload
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from akc_api.collection_integrity_runtime import (
    IntegrityActionRejected,
    approved_retry_candidates,
    corrected_source_candidates,
    create_password_execution,
    create_retry_execution,
    emit_execution_state_event,
    invalidate_collection_derived_state,
    reconcile_integrity_analysis_task,
    replace_collection_source,
    secure_password_tasks,
    synchronous_execution,
    target_scope_for_quarantine,
    target_scope_for_review,
)
from akc_api.database import get_session, set_rls_context
from akc_api.idempotency import idempotent_mutation
from akc_api.models import (
    AnalysisTask,
    ArchitecturePlan,
    Collection,
    CollectionEvent,
    CollectionFile,
    CollectionIntegrityActionExecution,
    CollectionIntegrityDecision,
    Document,
    ProcessingJob,
    Project,
    QuarantineItem,
    ReviewItem,
    User,
    utcnow,
)
from akc_api.project_access import project_access_predicate
from akc_api.security import Principal, require_roles
from akc_api.services import audit

router = APIRouter(prefix="/v1", tags=["collection-integrity"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReaderDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "editor", "reviewer", "viewer")),
]
EditorDep = Annotated[
    Principal,
    Depends(require_roles("owner", "admin", "editor")),
]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]

TargetType = Literal["quarantine_item", "review_item"]
DecisionAction = Literal[
    "keep_quarantined",
    "exclude",
    "retry_new_engine",
    "provide_password",
    "correct_source",
    "override",
]
EvidenceKind = Literal[
    "artifact_sha256",
    "analysis_task",
    "source_file",
    "engine_revision",
    "support_case",
]
ReasonCode = Literal[
    "ACCEPTED_QUARANTINE",
    "EXCLUDED_FROM_OUTPUT",
    "RETRY_WITH_APPROVED_ENGINE",
    "ENCRYPTED_PDF_SECRET_SUBMITTED",
    "CORRECTED_SOURCE_SUBMITTED",
    "CUSTOMER_OVERRIDE_APPROVED",
]

_REASON_BY_ACTION: dict[str, str] = {
    "keep_quarantined": "ACCEPTED_QUARANTINE",
    "exclude": "EXCLUDED_FROM_OUTPUT",
    "retry_new_engine": "RETRY_WITH_APPROVED_ENGINE",
    # Public audit reason code, never a credential.
    "provide_password": "ENCRYPTED_PDF_SECRET_SUBMITTED",  # nosec B105
    "correct_source": "CORRECTED_SOURCE_SUBMITTED",
    "override": "CUSTOMER_OVERRIDE_APPROVED",
}
_DECISION_STATES = frozenset({"PARTIAL", "UNRESOLVED", "QUARANTINED", "FAILED_RETRYABLE"})
_ACTIVE_JOB_STATES = frozenset({"queued", "running", "paused", "waiting_review"})
_UNSAFE_OVERRIDE_CATEGORY_PARTS = (
    "security",
    "credential",
    "access_control",
    "malware",
    "virus",
    "injection",
)
_SAFE_OVERRIDE_CATEGORIES = frozenset(
    {
        "ambiguous_layout",
        "formatting",
        "low_confidence_text",
        "numeric_format",
        "reading_order",
        "table_structure",
    }
)
_REVISION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+\-]{0,119}$")


class IntegrityEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    reference_id: uuid.UUID | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    revision: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.revision is not None and not _REVISION_PATTERN.fullmatch(self.revision):
            raise ValueError("revision must be a bounded non-secret identifier")
        if self.kind == "artifact_sha256":
            valid = self.sha256 is not None and self.reference_id is None and self.revision is None
        elif self.kind in {"analysis_task", "support_case"}:
            valid = self.reference_id is not None and self.sha256 is None and self.revision is None
        elif self.kind == "source_file":
            valid = (
                self.reference_id is not None and self.sha256 is not None and self.revision is None
            )
        else:
            valid = (
                self.reference_id is None and self.sha256 is not None and self.revision is not None
            )
        if not valid:
            raise ValueError("evidence reference fields do not match its kind")
        return self


class CollectionIntegrityDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: TargetType
    target_id: uuid.UUID
    action: DecisionAction
    reason_code: ReasonCode
    evidence_reference: IntegrityEvidenceReference | None = None
    acknowledge_override: bool = False

    @model_validator(mode="after")
    def validate_action_contract(self) -> Self:
        if self.reason_code != _REASON_BY_ACTION[self.action]:
            raise ValueError("reason_code does not match action")
        expected_kinds: dict[str, frozenset[str]] = {
            "keep_quarantined": frozenset({"artifact_sha256", "support_case"}),
            "exclude": frozenset({"artifact_sha256", "support_case"}),
            "retry_new_engine": frozenset({"engine_revision"}),
            "provide_password": frozenset({"analysis_task"}),
            "correct_source": frozenset({"source_file"}),
            "override": frozenset({"artifact_sha256", "support_case"}),
        }
        if (
            self.action in {"retry_new_engine", "provide_password", "correct_source", "override"}
            and self.evidence_reference is None
        ):
            raise ValueError("action requires a structured evidence reference")
        if (
            self.evidence_reference is not None
            and self.evidence_reference.kind not in expected_kinds[self.action]
        ):
            raise ValueError("evidence reference kind is not allowed for action")
        if self.action == "override" and not self.acknowledge_override:
            raise ValueError("override requires explicit acknowledgement")
        if self.action != "override" and self.acknowledge_override:
            raise ValueError("override acknowledgement is only valid for override")
        return self


class CollectionIntegrityActionExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    execution_kind: Literal["synchronous", "compile_retry", "password_analysis"]
    status: Literal["queued", "running", "completed", "failed"]
    processing_job_id: uuid.UUID | None
    analysis_task_id: uuid.UUID | None
    registry_model_id: uuid.UUID | None
    execution_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class CollectionIntegrityDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    collection_id: uuid.UUID
    target_type: TargetType
    target_id: uuid.UUID
    action: DecisionAction
    reason_code: ReasonCode
    evidence_reference: IntegrityEvidenceReference | None
    previous_status: str
    resulting_status: str
    override_applied: bool
    actor_id: uuid.UUID
    created_at: datetime
    execution: CollectionIntegrityActionExecutionResponse | None = None


class CollectionIntegrityDecisionList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: uuid.UUID
    items: list[CollectionIntegrityDecisionResponse]
    next_cursor: uuid.UUID | None


FindingStatus = Literal["open"]
FindingSeverity = Literal["critical", "high", "medium", "low", "unknown"]


class CollectionIntegrityFindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: TargetType
    target_id: uuid.UUID
    status: FindingStatus
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    severity: FindingSeverity
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,119}$")
    allowed_actions: list[DecisionAction]
    action_evidence: dict[DecisionAction, list[IntegrityEvidenceReference]] = Field(
        default_factory=dict
    )
    created_at: datetime


class CollectionIntegrityFindingList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: uuid.UUID
    items: list[CollectionIntegrityFindingResponse]
    next_cursor: str | None


def _require_idempotency_key(value: str | None) -> None:
    if value is None:
        raise HTTPException(status_code=428, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})


async def _require_verified_user(session: AsyncSession, principal: Principal) -> None:
    user = await session.scalar(
        select(User).where(User.id == principal.user_id, User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "SESSION_REVOKED"})
    if user.email_verified_at is None:
        raise HTTPException(status_code=403, detail={"code": "EMAIL_VERIFICATION_REQUIRED"})


async def _collection(
    session: AsyncSession,
    *,
    principal: Principal,
    collection_id: uuid.UUID,
    capability: Literal["read", "write"],
    lock: bool,
) -> Collection:
    statement = (
        select(Collection)
        .join(
            Project,
            (Project.tenant_id == Collection.tenant_id) & (Project.id == Collection.project_id),
        )
        .where(
            Collection.tenant_id == principal.tenant_id,
            Collection.id == collection_id,
            Collection.deletion_requested_at.is_(None),
            Project.deletion_requested_at.is_(None),
            project_access_predicate(principal, Collection.project_id, capability),
        )
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "COLLECTION_NOT_FOUND"})
    return row


async def _assert_decision_window(
    session: AsyncSession,
    *,
    collection: Collection,
) -> None:
    if collection.status not in _DECISION_STATES:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COLLECTION_INTEGRITY_DECISION_UNSAFE_STATE",
                "collection_status": collection.status,
            },
        )
    if await _has_active_collection_job(session, collection=collection):
        raise HTTPException(
            status_code=409,
            detail={"code": "COLLECTION_INTEGRITY_PROCESSING_ACTIVE"},
        )


async def _has_active_collection_job(
    session: AsyncSession,
    *,
    collection: Collection,
) -> bool:
    active_job = await session.scalar(
        select(
            exists().where(
                ArchitecturePlan.tenant_id == collection.tenant_id,
                ArchitecturePlan.collection_id == collection.id,
                ProcessingJob.tenant_id == ArchitecturePlan.tenant_id,
                ProcessingJob.id == ArchitecturePlan.processing_job_id,
                ProcessingJob.status.in_(_ACTIVE_JOB_STATES),
            )
        )
    )
    return bool(active_job)


async def _quarantine_target(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    target_id: uuid.UUID,
) -> QuarantineItem:
    row = await session.scalar(
        select(QuarantineItem)
        .where(
            QuarantineItem.tenant_id == tenant_id,
            QuarantineItem.collection_id == collection_id,
            QuarantineItem.id == target_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "INTEGRITY_FINDING_NOT_FOUND"})
    if row.status != "open":
        raise HTTPException(
            status_code=409,
            detail={"code": "INTEGRITY_FINDING_NOT_OPEN", "finding_status": row.status},
        )
    return row


async def _review_target(
    session: AsyncSession,
    *,
    collection: Collection,
    target_id: uuid.UUID,
) -> ReviewItem:
    belongs_to_collection = _review_belongs_to_collection(collection)
    row = await session.scalar(
        select(ReviewItem)
        .where(
            ReviewItem.tenant_id == collection.tenant_id,
            ReviewItem.id == target_id,
            ReviewItem.project_id == collection.project_id,
            belongs_to_collection,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "INTEGRITY_FINDING_NOT_FOUND"})
    if row.status != "open":
        raise HTTPException(
            status_code=409,
            detail={"code": "INTEGRITY_FINDING_NOT_OPEN", "finding_status": row.status},
        )
    prior_decision = await session.scalar(
        select(CollectionIntegrityDecision.id).where(
            CollectionIntegrityDecision.tenant_id == collection.tenant_id,
            CollectionIntegrityDecision.collection_id == collection.id,
            CollectionIntegrityDecision.review_item_id == row.id,
        )
    )
    if prior_decision is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "INTEGRITY_FINDING_NOT_OPEN", "finding_status": "resolved"},
        )
    return row


def _review_belongs_to_collection(collection: Collection) -> Exists:
    return exists(
        select(CollectionFile.id)
        .join(
            Document,
            (Document.tenant_id == CollectionFile.tenant_id)
            & (Document.source_file_id == CollectionFile.source_file_id),
        )
        .where(
            CollectionFile.tenant_id == collection.tenant_id,
            CollectionFile.collection_id == collection.id,
            Document.id == ReviewItem.document_id,
            Document.project_id == collection.project_id,
            Document.deletion_requested_at.is_(None),
        )
    )


def _override_action_allowed(target: ReviewItem, principal: Principal) -> bool:
    forbidden_category = target.category.casefold().replace("-", "_")
    return not (
        principal.roles.isdisjoint({"owner", "admin"})
        or target.severity.casefold() not in {"low", "medium"}
        or forbidden_category not in _SAFE_OVERRIDE_CATEGORIES
        or any(part in forbidden_category for part in _UNSAFE_OVERRIDE_CATEGORY_PARTS)
    )


def _structured_code(value: str, *, fallback: str, upper: bool, limit: int) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")[:limit]
    normalized = normalized.upper() if upper else normalized.casefold()
    if not normalized or not normalized[0].isalpha():
        return fallback
    return normalized


def _quarantine_category(target: QuarantineItem) -> tuple[str, FindingSeverity]:
    folded = target.reason_code.casefold()
    if any(part in folded for part in ("security", "malware", "virus", "injection")):
        return "security", "critical"
    if "password" in folded or "encrypted" in folded:
        return "encrypted_pdf", "high"
    if any(part in folded for part in ("corrupt", "unsupported", "source")):
        return "source_integrity", "high"
    return "quarantine", "high"


def _quarantine_finding(
    target: QuarantineItem,
    *,
    actions: list[DecisionAction],
    action_evidence: dict[DecisionAction, list[IntegrityEvidenceReference]],
) -> CollectionIntegrityFindingResponse:
    category, severity = _quarantine_category(target)
    return CollectionIntegrityFindingResponse(
        target_type="quarantine_item",
        target_id=target.id,
        status="open",
        category=category,
        severity=severity,
        reason_code=_structured_code(
            target.reason_code,
            fallback="UNCLASSIFIED_INTEGRITY_FINDING",
            upper=True,
            limit=120,
        ),
        allowed_actions=actions,
        action_evidence=action_evidence,
        created_at=target.created_at,
    )


async def _quarantine_capabilities(
    session: AsyncSession,
    *,
    collection: Collection,
    target: QuarantineItem,
    principal: Principal,
    actions_enabled: bool,
) -> tuple[
    list[DecisionAction],
    dict[DecisionAction, list[IntegrityEvidenceReference]],
]:
    if not actions_enabled or principal.roles.isdisjoint({"owner", "admin", "editor"}):
        return [], {}
    actions: list[DecisionAction] = ["keep_quarantined", "exclude"]
    evidence: dict[DecisionAction, list[IntegrityEvidenceReference]] = {}
    category, _ = _quarantine_category(target)
    if category == "security":
        return actions, evidence
    try:
        scope = await target_scope_for_quarantine(
            session,
            collection=collection,
            target=target,
        )
    except IntegrityActionRejected:
        scope = {}
    if "page_id" in scope:
        try:
            retry_candidates = await approved_retry_candidates(
                session,
                collection=collection,
                scope=scope,
            )
        except IntegrityActionRejected:
            retry_candidates = ()
        if retry_candidates:
            actions.append("retry_new_engine")
            evidence["retry_new_engine"] = [
                IntegrityEvidenceReference.model_validate(item.evidence_reference)
                for item in retry_candidates
            ]
    if category == "encrypted_pdf":
        password_tasks = await secure_password_tasks(
            session,
            collection=collection,
            target=target,
        )
        if password_tasks:
            actions.append("provide_password")
            evidence["provide_password"] = [
                IntegrityEvidenceReference(kind="analysis_task", reference_id=item.id)
                for item in password_tasks
            ]
    corrected_sources = await corrected_source_candidates(
        session,
        collection=collection,
        target=target,
    )
    if corrected_sources:
        actions.append("correct_source")
        evidence["correct_source"] = [
            IntegrityEvidenceReference(
                kind="source_file",
                reference_id=item.id,
                sha256=item.sha256,
            )
            for item in corrected_sources
        ]
    return actions, evidence


def _review_finding(
    target: ReviewItem,
    *,
    actions_enabled: bool,
    principal: Principal,
) -> CollectionIntegrityFindingResponse:
    category = _structured_code(
        target.category,
        fallback="unclassified",
        upper=False,
        limit=80,
    )
    severity_value = target.severity.casefold()
    severity: FindingSeverity = (
        cast(FindingSeverity, severity_value)
        if severity_value in {"critical", "high", "medium", "low"}
        else "unknown"
    )
    actions: list[DecisionAction] = []
    if actions_enabled and not principal.roles.isdisjoint({"owner", "admin", "editor"}):
        actions.append("exclude")
        if _override_action_allowed(target, principal):
            actions.append("override")
    return CollectionIntegrityFindingResponse(
        target_type="review_item",
        target_id=target.id,
        status="open",
        category=category,
        severity=severity,
        reason_code=f"REVIEW_{category.upper()}",
        allowed_actions=actions,
        action_evidence={},
        created_at=target.created_at,
    )


def _apply_quarantine_action(
    *,
    target: QuarantineItem,
    payload: CollectionIntegrityDecisionCreate,
) -> str:
    if payload.action == "override":
        raise HTTPException(
            status_code=422,
            detail={"code": "INTEGRITY_QUARANTINE_OVERRIDE_FORBIDDEN"},
        )
    now = utcnow()
    if payload.action == "keep_quarantined":
        # Close the actionable finding while leaving all quarantined source and
        # derivative state untouched.  The immutable decision is the durable
        # record that the customer accepted continued isolation.
        target.status = "resolved"
        target.resolved_at = now
        return target.status
    if payload.action == "exclude":
        target.status = "rejected"
        target.resolved_at = now
        return target.status
    if payload.action in {"retry_new_engine", "provide_password"}:
        return "retrying"
    if payload.action == "correct_source":
        target.status = "resolved"
        target.resolved_at = now
        return target.status
    raise HTTPException(
        status_code=422,
        detail={"code": "INTEGRITY_ACTION_NOT_ALLOWED"},
    )


def _apply_review_action(
    *,
    target: ReviewItem,
    payload: CollectionIntegrityDecisionCreate,
    principal: Principal,
) -> str:
    if payload.action == "exclude":
        return "resolved"
    if payload.action != "override":
        raise HTTPException(
            status_code=422,
            detail={"code": "INTEGRITY_ACTION_NOT_ALLOWED"},
        )
    if not _override_action_allowed(target, principal):
        raise HTTPException(
            status_code=403,
            detail={"code": "INTEGRITY_OVERRIDE_FORBIDDEN"},
        )
    return "resolved"


def _request_sha256(
    collection_id: uuid.UUID,
    payload: CollectionIntegrityDecisionCreate,
) -> str:
    canonical = json.dumps(
        {
            "collection_id": str(collection_id),
            "decision": payload.model_dump(mode="json", exclude_none=True),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _execution_response(
    row: CollectionIntegrityActionExecution,
) -> CollectionIntegrityActionExecutionResponse:
    return CollectionIntegrityActionExecutionResponse(
        id=row.id,
        execution_kind=cast(
            Literal["synchronous", "compile_retry", "password_analysis"],
            row.execution_kind,
        ),
        status=cast(Literal["queued", "running", "completed", "failed"], row.status),
        processing_job_id=row.processing_job_id,
        analysis_task_id=row.analysis_task_id,
        registry_model_id=row.registry_model_id,
        execution_receipt_sha256=row.execution_receipt_sha256,
        result_code=row.result_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _response(
    row: CollectionIntegrityDecision,
    execution: CollectionIntegrityActionExecution | None = None,
) -> CollectionIntegrityDecisionResponse:
    if row.quarantine_item_id is not None:
        target_type: TargetType = "quarantine_item"
        target_id = row.quarantine_item_id
    else:
        assert row.review_item_id is not None
        target_type = "review_item"
        target_id = row.review_item_id
    evidence = (
        IntegrityEvidenceReference.model_validate(row.evidence_reference)
        if row.evidence_reference
        else None
    )
    return CollectionIntegrityDecisionResponse(
        id=row.id,
        collection_id=row.collection_id,
        target_type=target_type,
        target_id=target_id,
        action=row.action,
        reason_code=row.reason_code,
        evidence_reference=evidence,
        previous_status=row.previous_status,
        resulting_status=row.resulting_status,
        override_applied=row.override_applied,
        actor_id=row.actor_id,
        created_at=row.created_at,
        execution=_execution_response(execution) if execution is not None else None,
    )


async def _emit_decision_event(
    session: AsyncSession,
    *,
    collection: Collection,
    decision: CollectionIntegrityDecision,
    response: CollectionIntegrityDecisionResponse,
) -> None:
    event_type = "integrity.decision.recorded.v1"
    payload = {
        "collection_id": str(collection.id),
        "decision_id": str(decision.id),
        "target_type": response.target_type,
        "target_id": str(response.target_id),
        "action": response.action,
        "reason_code": response.reason_code,
        "result_status": response.resulting_status,
        "evidence_reference_kind": (
            response.evidence_reference.kind if response.evidence_reference is not None else "none"
        ),
    }
    safe_payload = validate_collection_event_payload(
        event_type,
        payload,
        collection_id=collection.id,
        job_id=None,
    )
    collection.event_sequence += 1
    session.add(
        CollectionEvent(
            tenant_id=collection.tenant_id,
            collection_id=collection.id,
            job_id=None,
            sequence=collection.event_sequence,
            event_type=event_type,
            schema_version="1.0",
            payload=safe_payload,
        )
    )


@router.post(
    "/collections/{collection_id}/integrity/decisions",
    response_model=CollectionIntegrityDecisionResponse,
    status_code=201,
)
@idempotent_mutation
async def create_collection_integrity_decision(
    collection_id: uuid.UUID,
    payload: CollectionIntegrityDecisionCreate,
    request: Request,
    principal: EditorDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey = None,
) -> CollectionIntegrityDecisionResponse:
    del request
    _require_idempotency_key(idempotency_key)
    await set_rls_context(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="write",
        lock=True,
    )
    await _assert_decision_window(session, collection=collection)

    previous_status: str
    resulting_status: str
    quarantine_item_id: uuid.UUID | None = None
    review_item_id: uuid.UUID | None = None
    quarantine_target: QuarantineItem | None = None
    review_target: ReviewItem | None = None
    if payload.target_type == "quarantine_item":
        quarantine_target = await _quarantine_target(
            session,
            tenant_id=principal.tenant_id,
            collection_id=collection.id,
            target_id=payload.target_id,
        )
        if payload.action == "override":
            raise HTTPException(
                status_code=422,
                detail={"code": "INTEGRITY_QUARANTINE_OVERRIDE_FORBIDDEN"},
            )
        if payload.action in {"retry_new_engine", "provide_password", "correct_source"}:
            allowed, _ = await _quarantine_capabilities(
                session,
                collection=collection,
                target=quarantine_target,
                principal=principal,
                actions_enabled=True,
            )
            if payload.action not in allowed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "INTEGRITY_ACTION_NOT_EXECUTABLE",
                        "action": payload.action,
                    },
                )
        previous_status = quarantine_target.status
        resulting_status = _apply_quarantine_action(
            target=quarantine_target,
            payload=payload,
        )
        quarantine_item_id = quarantine_target.id
    else:
        review_target = await _review_target(
            session,
            collection=collection,
            target_id=payload.target_id,
        )
        previous_status = review_target.status
        resulting_status = _apply_review_action(
            target=review_target,
            payload=payload,
            principal=principal,
        )
        review_item_id = review_target.id

    reference = (
        payload.evidence_reference.model_dump(mode="json", exclude_none=True)
        if payload.evidence_reference is not None
        else {}
    )
    decision = CollectionIntegrityDecision(
        tenant_id=principal.tenant_id,
        collection_id=collection.id,
        quarantine_item_id=quarantine_item_id,
        review_item_id=review_item_id,
        action=payload.action,
        reason_code=payload.reason_code,
        evidence_reference=reference,
        previous_status=previous_status,
        resulting_status=resulting_status,
        override_applied=payload.action == "override",
        request_sha256=_request_sha256(collection.id, payload),
        actor_id=principal.user_id,
    )
    session.add(decision)
    await session.flush()
    execution: CollectionIntegrityActionExecution
    try:
        if quarantine_target is not None:
            scope = await target_scope_for_quarantine(
                session,
                collection=collection,
                target=quarantine_target,
            )
            evidence = payload.evidence_reference
            if payload.action == "retry_new_engine":
                assert evidence is not None
                assert evidence.revision is not None
                assert evidence.sha256 is not None
                execution = await create_retry_execution(
                    session,
                    collection=collection,
                    decision=decision,
                    target=quarantine_target,
                    evidence_revision=evidence.revision,
                    evidence_sha256=evidence.sha256,
                    requested_by=principal.user_id,
                )
            elif payload.action == "provide_password":
                assert evidence is not None
                assert evidence.reference_id is not None
                execution = await create_password_execution(
                    session,
                    collection=collection,
                    decision=decision,
                    target=quarantine_target,
                    analysis_task_id=evidence.reference_id,
                )
            elif payload.action == "correct_source":
                assert evidence is not None
                assert evidence.reference_id is not None
                assert evidence.sha256 is not None
                replacement, invalidated = await replace_collection_source(
                    session,
                    collection=collection,
                    target=quarantine_target,
                    source_file_id=evidence.reference_id,
                    source_sha256=evidence.sha256,
                )
                collection.status = "PARTIAL"
                collection.paused_from = None
                collection.status_reason = "CORRECTED_SOURCE_RECOMPILE_REQUIRED"
                collection.updated_at = utcnow()
                execution = synchronous_execution(
                    decision=decision,
                    target_scope=scope,
                    result_code="CORRECTED_SOURCE_APPLIED",
                    result={"replacement": replacement, "invalidated": invalidated},
                )
                session.add(execution)
            else:
                invalidated = await invalidate_collection_derived_state(
                    session,
                    collection=collection,
                )
                collection.status = "PARTIAL"
                collection.paused_from = None
                collection.status_reason = "INTEGRITY_EXCLUSION_RECOMPILE_REQUIRED"
                collection.updated_at = utcnow()
                execution = synchronous_execution(
                    decision=decision,
                    target_scope=scope,
                    result_code=(
                        "QUARANTINE_ACCEPTED"
                        if payload.action == "keep_quarantined"
                        else "TARGET_EXCLUDED"
                    ),
                    result={"invalidated": invalidated},
                )
                session.add(execution)
        else:
            assert review_target is not None
            scope = target_scope_for_review(review_target)
            invalidated = await invalidate_collection_derived_state(
                session,
                collection=collection,
            )
            collection.status = "PARTIAL"
            collection.paused_from = None
            collection.status_reason = "INTEGRITY_DECISION_RECOMPILE_REQUIRED"
            collection.updated_at = utcnow()
            execution = synchronous_execution(
                decision=decision,
                target_scope=scope,
                result_code=(
                    "CUSTOMER_OVERRIDE_APPLIED"
                    if payload.action == "override"
                    else "TARGET_EXCLUDED"
                ),
                result={"invalidated": invalidated},
            )
            session.add(execution)
    except IntegrityActionRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    await session.flush()
    response = _response(decision, execution)
    await _emit_decision_event(
        session,
        collection=collection,
        decision=decision,
        response=response,
    )
    await emit_execution_state_event(
        session,
        collection=collection,
        decision=decision,
        execution=execution,
    )
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="collection.integrity.decision.recorded",
        target_type=payload.target_type,
        target_id=str(payload.target_id),
        metadata={
            "collection_id": str(collection.id),
            "decision_id": str(decision.id),
            "action": payload.action,
            "reason_code": payload.reason_code,
            "result_status": resulting_status,
            "execution_id": str(execution.id),
            "execution_status": execution.status,
            "evidence_reference_kind": (
                payload.evidence_reference.kind
                if payload.evidence_reference is not None
                else "none"
            ),
        },
    )
    if execution.execution_kind == "password_analysis" and execution.analysis_task_id is not None:
        task = await session.get(AnalysisTask, execution.analysis_task_id)
        if task is not None and task.status == "completed":
            await reconcile_integrity_analysis_task(session, task=task)
            await session.flush()
            response = _response(decision, execution)
    await session.commit()
    return response


@router.get(
    "/collections/{collection_id}/integrity/findings",
    response_model=CollectionIntegrityFindingList,
)
async def list_collection_integrity_findings(
    collection_id: uuid.UUID,
    principal: ReaderDep,
    session: SessionDep,
    target_type: Annotated[TargetType | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=38, max_length=38)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CollectionIntegrityFindingList:
    await set_rls_context(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
        lock=False,
    )
    actions_enabled = (
        collection.status in _DECISION_STATES
        and not await _has_active_collection_job(
            session,
            collection=collection,
        )
    )
    cursor_type: TargetType | None = None
    cursor_id: uuid.UUID | None = None
    if cursor is not None:
        prefix, separator, raw_id = cursor.partition(":")
        if separator != ":" or prefix not in {"q", "r"}:
            raise HTTPException(
                status_code=400,
                detail={"code": "INTEGRITY_FINDING_CURSOR_INVALID"},
            )
        try:
            cursor_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "INTEGRITY_FINDING_CURSOR_INVALID"},
            ) from exc
        cursor_type = "quarantine_item" if prefix == "q" else "review_item"
        if target_type is not None and cursor_type != target_type:
            raise HTTPException(
                status_code=400,
                detail={"code": "INTEGRITY_FINDING_CURSOR_SCOPE_MISMATCH"},
            )
        assert cursor_id is not None
        if cursor_type == "quarantine_item":
            cursor_exists = await session.scalar(
                select(QuarantineItem.id).where(
                    QuarantineItem.tenant_id == principal.tenant_id,
                    QuarantineItem.collection_id == collection.id,
                    QuarantineItem.id == cursor_id,
                )
            )
        else:
            cursor_exists = await session.scalar(
                select(ReviewItem.id).where(
                    ReviewItem.tenant_id == principal.tenant_id,
                    ReviewItem.project_id == collection.project_id,
                    ReviewItem.id == cursor_id,
                    _review_belongs_to_collection(collection),
                )
            )
        if cursor_exists is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "INTEGRITY_FINDING_CURSOR_NOT_FOUND"},
            )

    ranked: list[tuple[int, uuid.UUID, CollectionIntegrityFindingResponse]] = []
    include_quarantine = target_type in {None, "quarantine_item"} and cursor_type != "review_item"
    if include_quarantine:
        quarantine_statement = select(QuarantineItem).where(
            QuarantineItem.tenant_id == principal.tenant_id,
            QuarantineItem.collection_id == collection.id,
            QuarantineItem.status == "open",
        )
        if cursor_type == "quarantine_item":
            assert cursor_id is not None
            quarantine_statement = quarantine_statement.where(QuarantineItem.id > cursor_id)
        quarantine_rows = list(
            await session.scalars(
                quarantine_statement.order_by(QuarantineItem.id.asc()).limit(limit + 1)
            )
        )
        for row in quarantine_rows:
            actions, action_evidence = await _quarantine_capabilities(
                session,
                collection=collection,
                target=row,
                principal=principal,
                actions_enabled=actions_enabled,
            )
            ranked.append(
                (
                    0,
                    row.id,
                    _quarantine_finding(
                        row,
                        actions=actions,
                        action_evidence=action_evidence,
                    ),
                )
            )

    include_reviews = target_type in {None, "review_item"}
    if include_reviews:
        review_statement = select(ReviewItem).where(
            ReviewItem.tenant_id == principal.tenant_id,
            ReviewItem.project_id == collection.project_id,
            ReviewItem.status == "open",
            _review_belongs_to_collection(collection),
            ~exists(
                select(CollectionIntegrityDecision.id).where(
                    CollectionIntegrityDecision.tenant_id == principal.tenant_id,
                    CollectionIntegrityDecision.collection_id == collection.id,
                    CollectionIntegrityDecision.review_item_id == ReviewItem.id,
                )
            ),
        )
        if cursor_type == "review_item":
            assert cursor_id is not None
            review_statement = review_statement.where(ReviewItem.id > cursor_id)
        review_rows = list(
            await session.scalars(review_statement.order_by(ReviewItem.id.asc()).limit(limit + 1))
        )
        ranked.extend(
            (
                1,
                row.id,
                _review_finding(
                    row,
                    actions_enabled=actions_enabled,
                    principal=principal,
                ),
            )
            for row in review_rows
        )

    ranked.sort(key=lambda item: (item[0], item[1].hex))
    has_more = len(ranked) > limit
    visible = ranked[:limit]
    next_cursor = None
    if has_more and visible:
        rank, target_id, _ = visible[-1]
        next_cursor = f"{'q' if rank == 0 else 'r'}:{target_id}"
    return CollectionIntegrityFindingList(
        collection_id=collection.id,
        items=[item[2] for item in visible],
        next_cursor=next_cursor,
    )


@router.get(
    "/collections/{collection_id}/integrity/decisions",
    response_model=CollectionIntegrityDecisionList,
)
async def list_collection_integrity_decisions(
    collection_id: uuid.UUID,
    principal: ReaderDep,
    session: SessionDep,
    target_type: Annotated[TargetType | None, Query()] = None,
    target_id: Annotated[uuid.UUID | None, Query()] = None,
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CollectionIntegrityDecisionList:
    await set_rls_context(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    await _require_verified_user(session, principal)
    collection = await _collection(
        session,
        principal=principal,
        collection_id=collection_id,
        capability="read",
        lock=False,
    )
    statement = select(CollectionIntegrityDecision).where(
        CollectionIntegrityDecision.tenant_id == principal.tenant_id,
        CollectionIntegrityDecision.collection_id == collection.id,
    )
    if target_type is not None:
        column = (
            CollectionIntegrityDecision.quarantine_item_id
            if target_type == "quarantine_item"
            else CollectionIntegrityDecision.review_item_id
        )
        statement = statement.where(column.is_not(None))
        if target_id is not None:
            statement = statement.where(column == target_id)
    elif target_id is not None:
        statement = statement.where(
            or_(
                CollectionIntegrityDecision.quarantine_item_id == target_id,
                CollectionIntegrityDecision.review_item_id == target_id,
            )
        )
    if cursor is not None:
        cursor_row = await session.scalar(
            select(CollectionIntegrityDecision).where(
                CollectionIntegrityDecision.tenant_id == principal.tenant_id,
                CollectionIntegrityDecision.collection_id == collection.id,
                CollectionIntegrityDecision.id == cursor,
            )
        )
        if cursor_row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "INTEGRITY_DECISION_CURSOR_NOT_FOUND"},
            )
        cursor_target_type = (
            "quarantine_item" if cursor_row.quarantine_item_id is not None else "review_item"
        )
        cursor_target_id = cursor_row.quarantine_item_id or cursor_row.review_item_id
        if (target_type is not None and cursor_target_type != target_type) or (
            target_id is not None and cursor_target_id != target_id
        ):
            raise HTTPException(
                status_code=400,
                detail={"code": "INTEGRITY_DECISION_CURSOR_SCOPE_MISMATCH"},
            )
        statement = statement.where(
            or_(
                CollectionIntegrityDecision.created_at < cursor_row.created_at,
                and_(
                    CollectionIntegrityDecision.created_at == cursor_row.created_at,
                    CollectionIntegrityDecision.id < cursor_row.id,
                ),
            )
        )
    rows = list(
        await session.scalars(
            statement.order_by(
                CollectionIntegrityDecision.created_at.desc(),
                CollectionIntegrityDecision.id.desc(),
            ).limit(limit + 1)
        )
    )
    has_more = len(rows) > limit
    visible = rows[:limit]
    executions: dict[uuid.UUID, CollectionIntegrityActionExecution] = {}
    if visible:
        execution_rows = list(
            await session.scalars(
                select(CollectionIntegrityActionExecution).where(
                    CollectionIntegrityActionExecution.tenant_id == principal.tenant_id,
                    CollectionIntegrityActionExecution.collection_id == collection.id,
                    CollectionIntegrityActionExecution.decision_id.in_(
                        tuple(row.id for row in visible)
                    ),
                )
            )
        )
        executions = {row.decision_id: row for row in execution_rows}
    return CollectionIntegrityDecisionList(
        collection_id=collection.id,
        items=[_response(row, executions.get(row.id)) for row in visible],
        next_cursor=visible[-1].id if has_more and visible else None,
    )
