"""Tenant-local, privacy-safe product analytics contracts and aggregation.

The module deliberately computes only from first-party operational records.
It does not export customer analytics, infer currency costs from credits, or
silently turn an empty denominator into zero.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Self

from akc_telemetry import (
    record_product_analytics_event,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import get_session
from akc_api.idempotency import idempotent_mutation
from akc_api.models import (
    AnalysisTask,
    AuditEvent,
    Block,
    BlockRevision,
    Checkout,
    Document,
    DocumentVersion,
    Export,
    FeatureFlag,
    KnowledgeNote,
    Membership,
    Page,
    Payment,
    ProcessingJob,
    Project,
    Refund,
    ReviewItem,
    SourceFile,
    Tenant,
    utcnow,
)
from akc_api.project_access import project_access_predicate
from akc_api.security import Principal, get_principal
from akc_api.telemetry import after_commit_metric, track_audit_write

PRODUCT_ANALYTICS_FLAG = "product_analytics_enabled"
PRODUCT_EVENT_PREFIX = "product."
_WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_AI_NOTE_ORIGINS = frozenset({"ai_summarized", "ai_inferred", "derived"})
_FALLBACK_ROUTES = frozenset({"mistral_fallback"})
_EVENT_ACTIONS = frozenset(
    {
        "product.estimate_viewed",
        "product.result_first_viewed",
        "product.project_revisited",
        "product.source_merged",
        "product.support_session_closed",
        "product.user_reported_error",
    }
)

MetricStatus = Literal[
    "available",
    "empty_denominator",
    "insufficient_evidence",
    "disabled",
    "not_instrumented",
]
MetricUnit = Literal[
    "count",
    "ratio",
    "seconds",
    "minutes_per_job",
    "credits_per_page",
    "credits_per_project",
]


class AnalyticsMetric(BaseModel):
    """A metric that cannot hide its denominator or evidence status."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: int | float | None
    numerator: int | float | None
    denominator: int | float | None
    unit: MetricUnit
    status: MetricStatus
    definition: str
    sources: list[str]


class AnalyticsWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Literal["7d", "30d", "90d"]
    start_at: datetime
    end_at: datetime
    days: int
    boundary: Literal["start_inclusive_end_exclusive"] = "start_inclusive_end_exclusive"
    timezone: Literal["UTC"] = "UTC"


class AnalyticsCohort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    start_at: datetime
    end_at: datetime
    observation_days: int
    population: int
    definition: str


class ActivationStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    users: int | None
    cohort_rate: float | None
    step_rate: float | None
    status: MetricStatus
    definition: str
    sources: list[str]


class ExportProfileShare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str
    exports: int
    share: float | None


class RefundCurrencySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    paid_payments: int
    paid_amount_minor: int
    refunded_payments: int
    refunded_amount_minor: int


class AnalyticsPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    private_mode: bool
    collection_mode: Literal[
        "disabled",
        "private_operational_only",
        "tenant_local_first_party",
    ]
    external_export: Literal[False] = False
    optional_behavior_events_stored: bool
    payload_policy: str


class ProductAnalyticsSnapshot(BaseModel):
    """Stable reader contract for masterplan section 28."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2026-07-30"] = "2026-07-30"
    generated_at: datetime
    window: AnalyticsWindow
    privacy: AnalyticsPrivacy
    cohorts: list[AnalyticsCohort]
    north_star: AnalyticsMetric
    activation: list[ActivationStage]
    product: dict[str, AnalyticsMetric]
    export_profiles: list[ExportProfileShare]
    quality: dict[str, AnalyticsMetric]
    economics: dict[str, AnalyticsMetric]
    refunds_by_currency: list[RefundCurrencySummary]
    limitations: list[str]


ProductEventType = Literal[
    "estimate_viewed",
    "result_first_viewed",
    "project_revisited",
    "source_merged",
    "support_session_closed",
    "user_reported_error",
]
ProductErrorCategory = Literal[
    "incorrect_text",
    "numeric_mismatch",
    "table_error",
    "missing_source",
    "other",
]


class ProductAnalyticsEventCreate(BaseModel):
    """Strict event allowlist: no free text, filenames, URLs, or contacts."""

    model_config = ConfigDict(extra="forbid")

    event_type: ProductEventType
    project_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    duration_seconds: int | None = Field(default=None, ge=1, le=86_400)
    category: ProductErrorCategory | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        identifiers = [
            self.project_id is not None,
            self.document_id is not None,
            self.job_id is not None,
        ]
        if self.event_type == "estimate_viewed":
            valid_target = self.document_id is not None and sum(identifiers) == 1
        elif self.event_type == "result_first_viewed":
            valid_target = self.job_id is not None and sum(identifiers) == 1
        elif self.event_type in {
            "project_revisited",
            "source_merged",
            "user_reported_error",
        }:
            valid_target = self.project_id is not None and sum(identifiers) == 1
        else:
            valid_target = sum(identifiers) == 0
        if not valid_target:
            raise ValueError("event_type requires exactly its documented target")
        if (self.event_type == "support_session_closed") != (self.duration_seconds is not None):
            raise ValueError("duration_seconds is allowed only for support_session_closed")
        if (self.event_type == "user_reported_error") != (self.category is not None):
            raise ValueError("category is required only for user_reported_error")
        return self


class ProductAnalyticsEventAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    reason: Literal["stored", "analytics_disabled", "private_mode"]
    server_received_at: datetime


SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
event_router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _decimal(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result


def _count_metric(
    *,
    key: str,
    label: str,
    value: int,
    definition: str,
    sources: list[str],
) -> AnalyticsMetric:
    return AnalyticsMetric(
        key=key,
        label=label,
        value=value,
        numerator=value,
        denominator=None,
        unit="count",
        status="available",
        definition=definition,
        sources=sources,
    )


def _ratio_metric(
    *,
    key: str,
    label: str,
    numerator: int | float,
    denominator: int | float,
    definition: str,
    sources: list[str],
) -> AnalyticsMetric:
    return AnalyticsMetric(
        key=key,
        label=label,
        value=(float(numerator) / float(denominator) if denominator > 0 else None),
        numerator=numerator,
        denominator=denominator,
        unit="ratio",
        status="available" if denominator > 0 else "empty_denominator",
        definition=definition,
        sources=sources,
    )


def _average_metric(
    *,
    key: str,
    label: str,
    numerator: float,
    denominator: int,
    unit: Literal[
        "seconds",
        "minutes_per_job",
        "credits_per_page",
        "credits_per_project",
    ],
    definition: str,
    sources: list[str],
) -> AnalyticsMetric:
    return AnalyticsMetric(
        key=key,
        label=label,
        value=(numerator / denominator if denominator > 0 else None),
        numerator=numerator,
        denominator=denominator,
        unit=unit,
        status="available" if denominator > 0 else "empty_denominator",
        definition=definition,
        sources=sources,
    )


def _percentile_metric(
    *,
    key: str,
    label: str,
    values: list[float],
    percentile: float,
    definition: str,
    sources: list[str],
) -> AnalyticsMetric:
    ordered = sorted(value for value in values if math.isfinite(value) and value >= 0)
    value = None if not ordered else ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]
    return AnalyticsMetric(
        key=key,
        label=label,
        value=value,
        numerator=None,
        denominator=len(ordered),
        unit="seconds",
        status="available" if ordered else "empty_denominator",
        definition=definition,
        sources=sources,
    )


def _unavailable_metric(
    *,
    key: str,
    label: str,
    unit: MetricUnit,
    definition: str,
    sources: list[str],
    status: Literal["insufficient_evidence", "disabled", "not_instrumented"],
) -> AnalyticsMetric:
    return AnalyticsMetric(
        key=key,
        label=label,
        value=None,
        numerator=None,
        denominator=None,
        unit=unit,
        status=status,
        definition=definition,
        sources=sources,
    )


def _disabled_snapshot(
    *,
    generated_at: datetime,
    window: AnalyticsWindow,
    tenant: Tenant,
) -> ProductAnalyticsSnapshot:
    product_specs: tuple[tuple[str, str, MetricUnit], ...] = (
        ("job_completion_rate", "Job completion rate", "ratio"),
        ("export_rate", "Export rate", "ratio"),
        ("review_items_per_page", "Review items per page", "ratio"),
        ("edits_per_block", "Edits per block", "ratio"),
        ("second_job_7d_rate", "Second job within 7 days", "ratio"),
        ("second_job_30d_rate", "Second job within 30 days", "ratio"),
        ("existing_project_merge_rate", "Existing-project merge rate", "ratio"),
    )
    disabled = {
        key: _unavailable_metric(
            key=key,
            label=label,
            unit=unit,
            definition="Workspace product analytics is disabled; no aggregate was computed.",
            sources=[],
            status="disabled",
        )
        for key, label, unit in product_specs
    }
    quality = {
        key: _unavailable_metric(
            key=key,
            label=label,
            unit="ratio",
            definition="Workspace product analytics is disabled; no aggregate was computed.",
            sources=[],
            status="disabled",
        )
        for key, label in (
            ("accepted_without_review_rate", "Accepted without review"),
            ("fallback_rate", "Fallback rate"),
            ("source_coverage_rate", "Source coverage"),
            ("unsupported_claim_rate", "Unsupported claim rate"),
            ("numeric_mismatch_rate", "Numeric mismatch rate"),
            ("table_correction_rate", "Table correction rate"),
            ("user_reported_error_rate", "User-reported error rate"),
        )
    }
    economics_specs: tuple[tuple[str, str, MetricUnit], ...] = (
        ("credit_cost_per_page", "Credit cost per processed page", "credits_per_page"),
        (
            "credit_cost_per_exported_project",
            "Credit cost per exported project",
            "credits_per_project",
        ),
        ("credit_breakage_rate", "Paid-credit breakage rate", "ratio"),
        ("gross_margin_rate", "Gross margin rate", "ratio"),
        ("paid_conversion_rate", "Paid conversion rate", "ratio"),
        ("support_minutes_per_job", "Support minutes per job", "minutes_per_job"),
        ("refund_payment_rate", "Refunded-payment rate", "ratio"),
    )
    economics = {
        key: _unavailable_metric(
            key=key,
            label=label,
            unit=unit,
            definition="Workspace product analytics is disabled; no aggregate was computed.",
            sources=[],
            status="disabled",
        )
        for key, label, unit in economics_specs
    }
    return ProductAnalyticsSnapshot(
        generated_at=generated_at,
        window=window,
        privacy=AnalyticsPrivacy(
            enabled=False,
            private_mode=tenant.private_mode,
            collection_mode="disabled",
            optional_behavior_events_stored=False,
            payload_policy="No product analytics events are stored while opted out.",
        ),
        cohorts=[],
        north_star=_unavailable_metric(
            key="weekly_verified_exported_or_reused_projects",
            label="Weekly verified projects exported or reused",
            unit="count",
            definition="Workspace product analytics is disabled; no aggregate was computed.",
            sources=[],
            status="disabled",
        ),
        activation=[],
        product=disabled,
        export_profiles=[],
        quality=quality,
        economics=economics,
        refunds_by_currency=[],
        limitations=[
            "The workspace opted out, so the endpoint returns definitions without aggregates."
        ],
    )


async def product_analytics_enabled(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> bool:
    """Return the tenant override; absence preserves the pre-existing enabled default."""

    row = await session.scalar(
        select(FeatureFlag).where(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.key == PRODUCT_ANALYTICS_FLAG,
        )
    )
    return True if row is None else row.enabled


async def set_product_analytics_enabled(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    enabled: bool,
) -> None:
    row = await session.scalar(
        select(FeatureFlag)
        .where(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.key == PRODUCT_ANALYTICS_FLAG,
        )
        .with_for_update()
    )
    if row is None:
        session.add(
            FeatureFlag(
                tenant_id=tenant_id,
                key=PRODUCT_ANALYTICS_FLAG,
                enabled=enabled,
                rollout_percent=100 if enabled else 0,
                conditions={"scope": "workspace_privacy"},
            )
        )
        return
    row.enabled = enabled
    row.rollout_percent = 100 if enabled else 0
    row.conditions = {"scope": "workspace_privacy"}


async def _event_target(
    session: AsyncSession,
    *,
    principal: Principal,
    payload: ProductAnalyticsEventCreate,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    tenant_id = principal.tenant_id
    project_id: uuid.UUID | None
    if payload.project_id is not None:
        project_id = await session.scalar(
            select(Project.id).where(
                Project.tenant_id == tenant_id,
                Project.id == payload.project_id,
                Project.deletion_requested_at.is_(None),
                project_access_predicate(principal, Project.id, "read"),
            )
        )
        document_id = None
    elif payload.document_id is not None:
        document_project_id = await session.scalar(
            select(Document.project_id)
            .join(
                Project,
                (Project.tenant_id == Document.tenant_id) & (Project.id == Document.project_id),
            )
            .where(
                Document.tenant_id == tenant_id,
                Document.id == payload.document_id,
                Document.deletion_requested_at.is_(None),
                Project.deletion_requested_at.is_(None),
                project_access_predicate(principal, Document.project_id, "read"),
            )
        )
        project_id = document_project_id
        document_id = payload.document_id if project_id is not None else None
    elif payload.job_id is not None:
        target = (
            await session.execute(
                select(ProcessingJob.project_id, ProcessingJob.document_id)
                .join(
                    Project,
                    (Project.tenant_id == ProcessingJob.tenant_id)
                    & (Project.id == ProcessingJob.project_id),
                )
                .where(
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.id == payload.job_id,
                    Project.deletion_requested_at.is_(None),
                    project_access_predicate(principal, ProcessingJob.project_id, "read"),
                )
            )
        ).one_or_none()
        if target is None:
            project_id = None
            document_id = None
        else:
            project_id, document_id = target
    else:
        return None, None
    if project_id is None:
        raise HTTPException(status_code=404, detail={"code": "ANALYTICS_TARGET_NOT_FOUND"})
    return project_id, document_id


async def _version_context(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID | None,
) -> dict[str, str]:
    if document_id is None:
        return {}
    row = (
        await session.execute(
            select(
                DocumentVersion.model_revision,
                DocumentVersion.policy_version,
            )
            .join(
                Document,
                (Document.tenant_id == DocumentVersion.tenant_id)
                & (Document.id == DocumentVersion.document_id),
            )
            .where(
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.document_id == document_id,
                Document.deletion_requested_at.is_(None),
            )
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return {}
    return {
        "model_revision": row.model_revision,
        "policy_version": row.policy_version,
    }


@event_router.post("/events", response_model=ProductAnalyticsEventAccepted, status_code=202)
@idempotent_mutation
async def create_product_analytics_event(
    payload: ProductAnalyticsEventCreate,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> ProductAnalyticsEventAccepted:
    del request
    received_at = utcnow()
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    enabled = await product_analytics_enabled(session, principal.tenant_id)
    if not enabled:
        after_commit_metric(
            session,
            record_product_analytics_event,
            payload.event_type,
            result="opted_out",
        )
        await session.commit()
        return ProductAnalyticsEventAccepted(
            accepted=False,
            reason="analytics_disabled",
            server_received_at=received_at,
        )
    if tenant.private_mode:
        after_commit_metric(
            session,
            record_product_analytics_event,
            payload.event_type,
            result="private_mode",
        )
        await session.commit()
        return ProductAnalyticsEventAccepted(
            accepted=False,
            reason="private_mode",
            server_received_at=received_at,
        )

    project_id, document_id = await _event_target(
        session,
        principal=principal,
        payload=payload,
    )
    metadata: dict[str, Any] = {"schema_version": 1}
    if payload.duration_seconds is not None:
        metadata["duration_seconds"] = payload.duration_seconds
    if payload.category is not None:
        metadata["category"] = payload.category
    metadata.update(
        await _version_context(
            session,
            tenant_id=principal.tenant_id,
            document_id=document_id,
        )
    )
    track_audit_write(session)
    session.add(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action=f"{PRODUCT_EVENT_PREFIX}{payload.event_type}",
            target_type="project" if project_id is not None else "tenant",
            target_id=str(project_id or principal.tenant_id),
            metadata_json=metadata,
            occurred_at=received_at,
        )
    )
    after_commit_metric(
        session,
        record_product_analytics_event,
        payload.event_type,
        result="stored",
    )
    await session.commit()
    return ProductAnalyticsEventAccepted(
        accepted=True,
        reason="stored",
        server_received_at=received_at,
    )


def _first_at_or_after(
    values: list[datetime],
    *,
    earliest: datetime,
    latest: datetime,
) -> datetime | None:
    return next(
        (
            value
            for value in sorted(values)
            if _aware(value) >= earliest and _aware(value) <= latest
        ),
        None,
    )


def _has_finding_code(evidence: dict[str, Any], code: str) -> bool:
    findings = evidence.get("quality_findings", [])
    if not isinstance(findings, list):
        return False
    return any(isinstance(item, dict) and str(item.get("code", "")) == code for item in findings)


async def build_product_analytics_snapshot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    window_key: Literal["7d", "30d", "90d"],
    principal: Principal | None = None,
    now: datetime | None = None,
) -> ProductAnalyticsSnapshot:
    """Build one exact, tenant-bound snapshot with explicit evidence gaps."""

    generated_at = _aware(now or utcnow())
    days = _WINDOW_DAYS[window_key]
    start_at = generated_at - timedelta(days=days)
    window = AnalyticsWindow(
        key=window_key,
        start_at=start_at,
        end_at=generated_at,
        days=days,
    )
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND"})
    enabled = await product_analytics_enabled(session, tenant_id)
    if not enabled:
        return _disabled_snapshot(
            generated_at=generated_at,
            window=window,
            tenant=tenant,
        )

    active_project_statement = select(Project.id).where(
        Project.tenant_id == tenant_id,
        Project.deletion_requested_at.is_(None),
    )
    if principal is not None:
        active_project_statement = active_project_statement.where(
            project_access_predicate(principal, Project.id, "read")
        )
    active_project_ids = set(await session.scalars(active_project_statement))

    membership_rows = (
        await session.execute(
            select(Membership.user_id, Membership.created_at).where(
                Membership.tenant_id == tenant_id,
                Membership.created_at < generated_at,
            )
        )
    ).all()
    memberships = {user_id: _aware(created_at) for user_id, created_at in membership_rows}

    activation_cohort_start = start_at - timedelta(days=7)
    activation_cohort_end = generated_at - timedelta(days=7)
    activation_members = {
        user_id: joined_at
        for user_id, joined_at in memberships.items()
        if activation_cohort_start <= joined_at < activation_cohort_end
    }
    observation_start = activation_cohort_start

    source_rows = (
        await session.execute(
            select(
                SourceFile.project_id,
                SourceFile.uploaded_by,
                SourceFile.created_at,
            ).where(
                SourceFile.tenant_id == tenant_id,
                SourceFile.project_id.in_(active_project_ids),
                SourceFile.created_at >= observation_start,
                SourceFile.created_at < generated_at,
            )
        )
    ).all()
    upload_times: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    upload_project_times: dict[uuid.UUID, dict[uuid.UUID, list[datetime]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for project_id, user_id, created_at in source_rows:
        observed = _aware(created_at)
        upload_times[user_id].append(observed)
        upload_project_times[user_id][project_id].append(observed)

    task_rows = (
        await session.execute(
            select(
                AnalysisTask.project_id,
                AnalysisTask.document_id,
                AnalysisTask.requested_by,
                AnalysisTask.started_at,
                AnalysisTask.completed_at,
            ).where(
                AnalysisTask.tenant_id == tenant_id,
                AnalysisTask.project_id.in_(active_project_ids),
                AnalysisTask.created_at >= observation_start,
                AnalysisTask.created_at < generated_at,
            )
        )
    ).all()
    processing_start_times: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    completed_tasks: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, datetime, datetime]] = []
    for project_id, document_id, user_id, started_at, completed_at in task_rows:
        if started_at is not None:
            processing_start_times[user_id].append(_aware(started_at))
        if started_at is not None and completed_at is not None:
            completed_tasks.append(
                (
                    project_id,
                    document_id,
                    user_id,
                    _aware(started_at),
                    _aware(completed_at),
                )
            )

    event_rows: list[tuple[uuid.UUID | None, str, str, dict[str, Any], datetime]]
    if tenant.private_mode:
        event_rows = []
    else:
        event_rows = [
            (actor_id, action, target_id, metadata, _aware(occurred_at))
            for actor_id, action, target_id, metadata, occurred_at in (
                await session.execute(
                    select(
                        AuditEvent.actor_id,
                        AuditEvent.action,
                        AuditEvent.target_id,
                        AuditEvent.metadata_json,
                        AuditEvent.occurred_at,
                    ).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.action.in_(_EVENT_ACTIONS),
                        AuditEvent.occurred_at >= observation_start,
                        AuditEvent.occurred_at < generated_at,
                    )
                )
            ).all()
        ]
    event_times: dict[str, dict[uuid.UUID, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    project_event_times: dict[str, list[tuple[uuid.UUID, datetime]]] = defaultdict(list)
    support_seconds = 0
    reported_error_events = 0
    for actor_id, action, target_id, metadata, occurred_at in event_rows:
        if actor_id is not None:
            event_times[action][actor_id].append(occurred_at)
        if action in {"product.project_revisited", "product.source_merged"}:
            try:
                event_project_id = uuid.UUID(target_id)
            except ValueError:
                event_project_id = None
            if event_project_id in active_project_ids:
                project_event_times[action].append((event_project_id, occurred_at))
        if action == "product.support_session_closed":
            seconds = metadata.get("duration_seconds")
            if isinstance(seconds, int) and 1 <= seconds <= 86_400:
                support_seconds += seconds
        if action == "product.user_reported_error":
            reported_error_events += 1

    review_rows = (
        await session.execute(
            select(
                ReviewItem.project_id,
                ReviewItem.document_id,
                ReviewItem.page_id,
                ReviewItem.block_id,
                ReviewItem.category,
                ReviewItem.status,
                ReviewItem.evidence,
                ReviewItem.resolution,
                ReviewItem.resolved_by,
                ReviewItem.resolved_at,
                ReviewItem.created_at,
            ).where(
                ReviewItem.tenant_id == tenant_id,
                ReviewItem.project_id.in_(active_project_ids),
                ReviewItem.created_at < generated_at,
            )
        )
    ).all()
    reviews_by_document: dict[uuid.UUID, list[Any]] = defaultdict(list)
    reviews_by_project: dict[uuid.UUID, list[Any]] = defaultdict(list)
    review_clear_times: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    for row in review_rows:
        reviews_by_project[row.project_id].append(row)
        reviews_by_document[row.document_id].append(row)
        if row.resolved_by is not None and row.resolved_at is not None:
            review_clear_times[row.resolved_by].append(_aware(row.resolved_at))
    for _, document_id, user_id, _, completed_at in completed_tasks:
        document_reviews = reviews_by_document.get(document_id, [])
        if not document_reviews:
            review_clear_times[user_id].append(completed_at)
            continue
        if all(
            review.resolved_at is not None and _aware(review.resolved_at) >= completed_at
            for review in document_reviews
        ):
            review_clear_times[user_id].append(
                max(_aware(review.resolved_at) for review in document_reviews)
            )

    export_rows = (
        await session.execute(
            select(
                Export.project_id,
                Export.created_by,
                Export.export_type,
                Export.status,
                Export.completed_at,
            ).where(
                Export.tenant_id == tenant_id,
                Export.project_id.in_(active_project_ids),
                Export.created_at < generated_at,
            )
        )
    ).all()
    export_times: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    completed_exports: list[tuple[uuid.UUID, str, datetime]] = []
    for project_id, user_id, export_type, status, completed_at in export_rows:
        if status == "completed" and completed_at is not None:
            observed = _aware(completed_at)
            export_times[user_id].append(observed)
            completed_exports.append((project_id, export_type, observed))

    reuse_times: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    for user_id, projects in upload_project_times.items():
        for values in projects.values():
            ordered = sorted(values)
            if len(ordered) >= 2:
                reuse_times[user_id].extend(ordered[1:])
    for action in ("product.project_revisited", "product.source_merged"):
        for user_id, values in event_times[action].items():
            reuse_times[user_id].extend(values)

    activation_sources: dict[str, list[str]] = {
        "signup": ["memberships"],
        "first_upload": ["source_files"],
        "estimate_viewed": ["audit_events(product.estimate_viewed)"],
        "processing_started": ["analysis_tasks"],
        "result_first_viewed": ["audit_events(product.result_first_viewed)"],
        "review_cleared": ["analysis_tasks", "review_items"],
        "export_completed": ["exports"],
        "reuse_or_merge": [
            "source_files",
            "audit_events(product.project_revisited|product.source_merged)",
        ],
    }
    stage_candidates: list[tuple[str, str, dict[uuid.UUID, list[datetime]], str]] = [
        (
            "first_upload",
            "First upload",
            upload_times,
            "First source-file upload after workspace membership.",
        ),
        (
            "estimate_viewed",
            "Estimate viewed",
            event_times["product.estimate_viewed"],
            "First recorded estimate view after upload.",
        ),
        (
            "processing_started",
            "Processing started",
            processing_start_times,
            "First analysis task start after estimate view.",
        ),
        (
            "result_first_viewed",
            "Result first viewed",
            event_times["product.result_first_viewed"],
            "First recorded result view after processing started.",
        ),
        (
            "review_cleared",
            "Review cleared",
            review_clear_times,
            "First review resolution, or task completion when no review item existed.",
        ),
        (
            "export_completed",
            "Export completed",
            export_times,
            "First completed export after review was cleared.",
        ),
        (
            "reuse_or_merge",
            "Revisit or new-source merge",
            reuse_times,
            "First recorded revisit or second source in the same project after export.",
        ),
    ]
    activation: list[ActivationStage] = [
        ActivationStage(
            key="signup",
            label="Signup",
            users=len(activation_members),
            cohort_rate=1.0 if activation_members else None,
            step_rate=1.0 if activation_members else None,
            status="available" if activation_members else "empty_denominator",
            definition=(
                "Members whose membership began in the selected-length cohort shifted "
                "back seven days, giving every member a complete seven-day observation."
            ),
            sources=activation_sources["signup"],
        )
    ]
    surviving: dict[uuid.UUID, datetime] = dict(activation_members)
    for key, label, candidates, definition in stage_candidates:
        behavior_event_stage = key in {
            "estimate_viewed",
            "result_first_viewed",
            "reuse_or_merge",
        }
        if tenant.private_mode and behavior_event_stage and key != "reuse_or_merge":
            activation.append(
                ActivationStage(
                    key=key,
                    label=label,
                    users=None,
                    cohort_rate=None,
                    step_rate=None,
                    status="not_instrumented",
                    definition=(
                        f"{definition} Optional behavior events are suppressed in private mode."
                    ),
                    sources=activation_sources[key],
                )
            )
            surviving = {}
            continue
        previous_count = len(surviving)
        next_surviving: dict[uuid.UUID, datetime] = {}
        for user_id, earliest in surviving.items():
            joined_at = activation_members[user_id]
            candidate_at = _first_at_or_after(
                candidates.get(user_id, []),
                earliest=earliest,
                latest=joined_at + timedelta(days=7),
            )
            if candidate_at is not None:
                next_surviving[user_id] = _aware(candidate_at)
        users = len(next_surviving)
        activation.append(
            ActivationStage(
                key=key,
                label=label,
                users=users,
                cohort_rate=(users / len(activation_members) if activation_members else None),
                step_rate=users / previous_count if previous_count else None,
                status=("available" if previous_count else "empty_denominator"),
                definition=definition,
                sources=activation_sources[key],
            )
        )
        surviving = next_surviving

    document_rows = (
        await session.execute(
            select(Document.id, Document.project_id, Document.created_at).where(
                Document.tenant_id == tenant_id,
                Document.project_id.in_(active_project_ids),
                Document.deletion_requested_at.is_(None),
                Document.created_at < generated_at,
            )
        )
    ).all()
    first_document_at: dict[uuid.UUID, datetime] = {}
    document_project: dict[uuid.UUID, uuid.UUID] = {}
    documents_in_window: list[tuple[uuid.UUID, uuid.UUID, datetime]] = []
    for document_id, project_id, created_at in document_rows:
        observed = _aware(created_at)
        document_project[document_id] = project_id
        first_document_at[project_id] = min(
            observed,
            first_document_at.get(project_id, observed),
        )
        if start_at <= observed < generated_at:
            documents_in_window.append((document_id, project_id, observed))

    processing_job_rows = (
        await session.execute(
            select(
                ProcessingJob.id,
                ProcessingJob.project_id,
                ProcessingJob.document_id,
                ProcessingJob.status,
                ProcessingJob.progress,
                ProcessingJob.cost_actual,
                ProcessingJob.started_at,
                ProcessingJob.completed_at,
                ProcessingJob.created_at,
            ).where(
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.project_id.in_(active_project_ids),
                ProcessingJob.created_at < generated_at,
            )
        )
    ).all()
    jobs_created_in_window = [
        row for row in processing_job_rows if start_at <= _aware(row.created_at) < generated_at
    ]
    completed_jobs_in_window = [
        row
        for row in processing_job_rows
        if row.status == "completed"
        and row.completed_at is not None
        and start_at <= _aware(row.completed_at) < generated_at
    ]
    completed_job_times_by_project: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    for row in processing_job_rows:
        if row.status == "completed" and row.completed_at is not None:
            completed_job_times_by_project[row.project_id].append(_aware(row.completed_at))
    for values in completed_job_times_by_project.values():
        values.sort()

    north_star_start = generated_at - timedelta(days=7)
    north_star_activities: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    for project_id, _, completed_at in completed_exports:
        if north_star_start <= completed_at < generated_at:
            north_star_activities[project_id].append(completed_at)
    for _, project_id, created_at in document_rows:
        observed = _aware(created_at)
        if north_star_start <= observed < generated_at and observed > first_document_at[project_id]:
            north_star_activities[project_id].append(observed)
    for action in ("product.project_revisited", "product.source_merged"):
        for project_id, occurred_at in project_event_times[action]:
            if north_star_start <= occurred_at < generated_at:
                north_star_activities[project_id].append(occurred_at)

    qualified_projects: set[uuid.UUID] = set()
    for project_id, activities in north_star_activities.items():
        completed_job_times = completed_job_times_by_project.get(project_id, [])
        if not completed_job_times:
            continue
        project_reviews = reviews_by_project.get(project_id, [])
        for activity_at in activities:
            prior_jobs = [value for value in completed_job_times if value <= activity_at]
            prior_reviews = [
                review for review in project_reviews if _aware(review.created_at) <= activity_at
            ]
            reviews_clear = all(
                review.resolved_at is not None and _aware(review.resolved_at) <= activity_at
                for review in prior_reviews
            )
            if prior_jobs and reviews_clear:
                qualified_projects.add(project_id)
                break
    north_star = _count_metric(
        key="weekly_verified_exported_or_reused_projects",
        label="Weekly verified projects exported or reused",
        value=len(qualified_projects),
        definition=(
            "Distinct projects in the trailing seven days that had a completed job and "
            "no unresolved review existing at the activity time, followed by a completed "
            "export, second document, recorded revisit, or recorded source merge."
        ),
        sources=["processing_jobs", "review_items", "exports", "documents", "audit_events"],
    )

    task_first_block_latencies: list[float] = []
    task_first_page_latencies: list[float] = []
    task_document_ids = {
        document_id
        for _, document_id, _, started_at, _ in completed_tasks
        if start_at <= started_at < generated_at
    }
    first_block_by_document: dict[uuid.UUID, datetime] = {}
    block_rows = (
        await session.execute(
            select(
                Block.id,
                Block.document_id,
                Block.page_id,
                Block.block_type,
                Block.source_text,
                Block.created_at,
            ).where(
                Block.tenant_id == tenant_id,
                Block.document_id.in_(document_project),
                Block.created_at < generated_at,
            )
        )
    ).all()
    blocks_in_window = []
    block_type_by_id: dict[uuid.UUID, str] = {}
    for block_id, document_id, page_id, block_type, source_text, created_at in block_rows:
        observed = _aware(created_at)
        block_type_by_id[block_id] = block_type
        if document_id in task_document_ids:
            first_block_by_document[document_id] = min(
                observed,
                first_block_by_document.get(document_id, observed),
            )
        if start_at <= observed < generated_at:
            blocks_in_window.append(
                (block_id, document_id, page_id, block_type, source_text, observed)
            )

    page_rows = (
        await session.execute(
            select(
                Page.id,
                Page.document_id,
                Page.status,
                Page.route,
                Page.created_at,
            ).where(
                Page.tenant_id == tenant_id,
                Page.document_id.in_(document_project),
                Page.created_at < generated_at,
            )
        )
    ).all()
    pages_in_window = [
        row for row in page_rows if start_at <= _aware(row.created_at) < generated_at
    ]
    first_usable_page_by_document: dict[uuid.UUID, datetime] = {}
    for row in page_rows:
        if row.status == "COMPLETED" and row.document_id in task_document_ids:
            observed = _aware(row.created_at)
            first_usable_page_by_document[row.document_id] = min(
                observed,
                first_usable_page_by_document.get(row.document_id, observed),
            )
    for _, document_id, _, started_at, _ in completed_tasks:
        if not (start_at <= started_at < generated_at):
            continue
        block_at = first_block_by_document.get(document_id)
        if block_at is not None and block_at >= started_at:
            task_first_block_latencies.append((block_at - started_at).total_seconds())
        page_at = first_usable_page_by_document.get(document_id)
        if page_at is not None and page_at >= started_at:
            task_first_page_latencies.append((page_at - started_at).total_seconds())

    completed_page_ids = {row.id for row in pages_in_window if row.status == "COMPLETED"}
    reviewed_page_ids = {
        row.page_id
        for row in review_rows
        if row.page_id is not None and row.page_id in completed_page_ids
    }
    review_items_created_in_window = [
        row for row in review_rows if start_at <= _aware(row.created_at) < generated_at
    ]
    revision_rows = (
        await session.execute(
            select(
                BlockRevision.block_id,
                BlockRevision.operation,
                BlockRevision.created_at,
            ).where(
                BlockRevision.tenant_id == tenant_id,
                BlockRevision.created_at >= start_at,
                BlockRevision.created_at < generated_at,
            )
        )
    ).all()

    def repeat_rate(horizon_days: int) -> tuple[AnalyticsMetric, AnalyticsCohort]:
        horizon = timedelta(days=horizon_days)
        cohort_start = start_at - horizon
        cohort_end = generated_at - horizon
        first_completions = {
            project_id: values[0]
            for project_id, values in completed_job_times_by_project.items()
            if values and cohort_start <= values[0] < cohort_end
        }
        repeated = sum(
            any(first < value <= first + horizon for value in completed_job_times_by_project[pid])
            for pid, first in first_completions.items()
        )
        metric = _ratio_metric(
            key=f"second_job_{horizon_days}d_rate",
            label=f"Second job within {horizon_days} days",
            numerator=repeated,
            denominator=len(first_completions),
            definition=(
                f"Projects whose first completed processing job was followed by another "
                f"completed job within {horizon_days} days. The cohort is shifted back "
                f"{horizon_days} days to avoid right-censoring."
            ),
            sources=["processing_jobs"],
        )
        cohort = AnalyticsCohort(
            key=f"first_completed_job_{horizon_days}d_matured",
            start_at=cohort_start,
            end_at=cohort_end,
            observation_days=horizon_days,
            population=len(first_completions),
            definition=(
                f"Projects with their first completed job in the selected-length interval "
                f"ending {horizon_days} days before the snapshot."
            ),
        )
        return metric, cohort

    second_7d, repeat_7d_cohort = repeat_rate(7)
    second_30d, repeat_30d_cohort = repeat_rate(30)
    completed_project_ids = {row.project_id for row in completed_jobs_in_window}
    exported_project_ids = {
        project_id
        for project_id, _, completed_at in completed_exports
        if start_at <= completed_at < generated_at
    }
    merged_documents = sum(
        created_at > first_document_at[project_id]
        for _, project_id, created_at in documents_in_window
    )

    profile_counts: dict[str, int] = defaultdict(int)
    for _, export_type, completed_at in completed_exports:
        if start_at <= completed_at < generated_at:
            profile = (
                export_type
                if export_type in {"portable", "obsidian", "rag", "jsonld", "bundle"}
                else "other"
            )
            profile_counts[profile] += 1
    profile_total = sum(profile_counts.values())
    export_profiles = [
        ExportProfileShare(
            profile=profile,
            exports=count,
            share=(count / profile_total if profile_total else None),
        )
        for profile, count in sorted(profile_counts.items())
    ]

    product = {
        "time_to_first_visible_block_p50_seconds": _percentile_metric(
            key="time_to_first_visible_block_p50_seconds",
            label="Time to first visible block (p50)",
            values=task_first_block_latencies,
            percentile=0.50,
            definition=(
                "Nearest-rank p50 from analysis-task started_at to the earliest persisted "
                "block created_at for the same document; only non-negative pairs count."
            ),
            sources=["analysis_tasks", "blocks"],
        ),
        "time_to_first_visible_block_p95_seconds": _percentile_metric(
            key="time_to_first_visible_block_p95_seconds",
            label="Time to first visible block (p95)",
            values=task_first_block_latencies,
            percentile=0.95,
            definition=(
                "Nearest-rank p95 from analysis-task started_at to the earliest persisted "
                "block created_at for the same document; only non-negative pairs count."
            ),
            sources=["analysis_tasks", "blocks"],
        ),
        "time_to_first_usable_page_p50_seconds": _percentile_metric(
            key="time_to_first_usable_page_p50_seconds",
            label="Time to first usable page (p50)",
            values=task_first_page_latencies,
            percentile=0.50,
            definition=(
                "Nearest-rank p50 from analysis-task started_at to the earliest completed "
                "page created_at for the same document."
            ),
            sources=["analysis_tasks", "pages"],
        ),
        "time_to_first_usable_page_p95_seconds": _percentile_metric(
            key="time_to_first_usable_page_p95_seconds",
            label="Time to first usable page (p95)",
            values=task_first_page_latencies,
            percentile=0.95,
            definition=(
                "Nearest-rank p95 from analysis-task started_at to the earliest completed "
                "page created_at for the same document."
            ),
            sources=["analysis_tasks", "pages"],
        ),
        "job_completion_rate": _ratio_metric(
            key="job_completion_rate",
            label="Job completion rate",
            numerator=sum(row.status == "completed" for row in jobs_created_in_window),
            denominator=len(jobs_created_in_window),
            definition=(
                "Processing jobs created inside the window that are currently completed, "
                "divided by all processing jobs created inside the window."
            ),
            sources=["processing_jobs"],
        ),
        "export_rate": _ratio_metric(
            key="export_rate",
            label="Export rate",
            numerator=len(completed_project_ids & exported_project_ids),
            denominator=len(completed_project_ids),
            definition=(
                "Distinct projects with both a completed processing job and completed export "
                "inside the window, divided by projects with a completed job in the window."
            ),
            sources=["processing_jobs", "exports"],
        ),
        "review_items_per_page": _ratio_metric(
            key="review_items_per_page",
            label="Review items per page",
            numerator=len(review_items_created_in_window),
            denominator=len(pages_in_window),
            definition="Review items created in the window divided by pages created in the window.",
            sources=["review_items", "pages"],
        ),
        "edits_per_block": _ratio_metric(
            key="edits_per_block",
            label="Edits per block",
            numerator=len(revision_rows),
            denominator=len(block_rows),
            definition=(
                "Block revisions created in the window divided by all active-document blocks "
                "that existed before the window end."
            ),
            sources=["block_revisions", "blocks"],
        ),
        "second_job_7d_rate": second_7d,
        "second_job_30d_rate": second_30d,
        "existing_project_merge_rate": _ratio_metric(
            key="existing_project_merge_rate",
            label="Existing-project merge rate",
            numerator=merged_documents,
            denominator=len(documents_in_window),
            definition=(
                "Documents created in the window that were not their project's first document, "
                "divided by all documents created in the window."
            ),
            sources=["documents"],
        ),
    }

    ai_notes = list(
        (
            await session.execute(
                select(
                    KnowledgeNote.content_origin,
                    KnowledgeNote.evidence_block_ids,
                    KnowledgeNote.created_at,
                ).where(
                    KnowledgeNote.tenant_id == tenant_id,
                    KnowledgeNote.project_id.in_(active_project_ids),
                    KnowledgeNote.created_at >= start_at,
                    KnowledgeNote.created_at < generated_at,
                )
            )
        ).all()
    )
    ai_notes = [row for row in ai_notes if row.content_origin in _AI_NOTE_ORIGINS]
    numeric_mismatches = sum(
        _has_finding_code(row.evidence, "numeric.token_mismatch")
        for row in review_items_created_in_window
    )
    resolved_reviews = [
        row
        for row in review_rows
        if row.resolved_at is not None and start_at <= _aware(row.resolved_at) < generated_at
    ]
    table_corrections = sum(
        row.block_id is not None
        and block_type_by_id.get(row.block_id) == "table"
        and isinstance(row.resolution, dict)
        and row.resolution.get("action") == "replace"
        for row in resolved_reviews
    )
    routed_pages = [row for row in pages_in_window if row.route is not None]
    quality = {
        "accepted_without_review_rate": _ratio_metric(
            key="accepted_without_review_rate",
            label="Accepted without review",
            numerator=len(completed_page_ids - reviewed_page_ids),
            denominator=len(completed_page_ids),
            definition=(
                "Completed pages created in the window with no review item for that page, "
                "divided by completed pages created in the window."
            ),
            sources=["pages", "review_items"],
        ),
        "fallback_rate": _ratio_metric(
            key="fallback_rate",
            label="Fallback rate",
            numerator=sum(row.route in _FALLBACK_ROUTES for row in routed_pages),
            denominator=len(routed_pages),
            definition=(
                "Pages created in the window routed to the explicit mistral_fallback route, "
                "divided by pages with a recorded route. Manual review is not mislabeled fallback."
            ),
            sources=["pages"],
        ),
        "source_coverage_rate": _ratio_metric(
            key="source_coverage_rate",
            label="Source coverage",
            numerator=sum(
                isinstance(row[4], str) and bool(row[4].strip()) for row in blocks_in_window
            ),
            denominator=len(blocks_in_window),
            definition=(
                "Blocks created in the window with non-empty source_text, divided by all "
                "blocks created in the window. Content is never returned in analytics."
            ),
            sources=["blocks"],
        ),
        "unsupported_claim_rate": _ratio_metric(
            key="unsupported_claim_rate",
            label="Unsupported claim rate",
            numerator=sum(not row.evidence_block_ids for row in ai_notes),
            denominator=len(ai_notes),
            definition=(
                "AI/derived knowledge notes created in the window with no evidence block ID, "
                "divided by AI/derived notes created in the window."
            ),
            sources=["knowledge_notes"],
        ),
        "numeric_mismatch_rate": _ratio_metric(
            key="numeric_mismatch_rate",
            label="Numeric mismatch rate",
            numerator=numeric_mismatches,
            denominator=len(review_items_created_in_window),
            definition=(
                "Review items created in the window containing quality finding "
                "numeric.token_mismatch, divided by review items created in the window."
            ),
            sources=["review_items"],
        ),
        "table_correction_rate": _ratio_metric(
            key="table_correction_rate",
            label="Table correction rate",
            numerator=table_corrections,
            denominator=len(resolved_reviews),
            definition=(
                "Resolved review items in the window that replaced a table block, divided by "
                "all review items resolved in the window."
            ),
            sources=["review_items", "blocks"],
        ),
        "user_reported_error_rate": (
            _unavailable_metric(
                key="user_reported_error_rate",
                label="User-reported error rate",
                unit="ratio",
                definition=(
                    "Optional behavior events are suppressed in private mode; no error rate "
                    "is inferred from absence."
                ),
                sources=["audit_events(product.user_reported_error)", "processing_jobs"],
                status="not_instrumented",
            )
            if tenant.private_mode
            else _ratio_metric(
                key="user_reported_error_rate",
                label="User-reported error rate",
                numerator=reported_error_events,
                denominator=len(completed_jobs_in_window),
                definition=(
                    "Recorded user-reported-error events in the window divided by completed "
                    "processing jobs in the window."
                ),
                sources=["audit_events(product.user_reported_error)", "processing_jobs"],
            )
        ),
    }

    attributable_jobs: list[tuple[Any, Decimal, int]] = []
    for row in completed_jobs_in_window:
        credits = _decimal(
            row.cost_actual.get("credits") if isinstance(row.cost_actual, dict) else None
        )
        pages = row.progress.get("total") if isinstance(row.progress, dict) else None
        if credits is not None and isinstance(pages, int) and pages > 0:
            attributable_jobs.append((row, credits, pages))
    attributable_credits = sum(
        (credits for _, credits, _ in attributable_jobs),
        Decimal("0"),
    )
    attributable_pages = sum(pages for _, _, pages in attributable_jobs)
    exported_attributable = [
        item for item in attributable_jobs if item[0].project_id in exported_project_ids
    ]
    exported_cost_complete = bool(exported_project_ids) and all(
        any(item[0].project_id == project_id for item in exported_attributable)
        for project_id in exported_project_ids
    )
    exported_credits = sum(
        (credits for _, credits, _ in exported_attributable),
        Decimal("0"),
    )

    conversion_cohort = {
        user_id: joined_at
        for user_id, joined_at in memberships.items()
        if start_at <= joined_at < generated_at
    }
    paid_rows = (
        await session.execute(
            select(
                Payment.id,
                Checkout.created_by,
                Payment.amount_minor,
                Payment.currency,
                Payment.status,
                Payment.paid_at,
            )
            .join(
                Checkout,
                (Checkout.tenant_id == Payment.tenant_id) & (Checkout.id == Payment.checkout_id),
            )
            .where(
                Payment.tenant_id == tenant_id,
                Payment.paid_at >= start_at,
                Payment.paid_at < generated_at,
                Payment.status.in_(("succeeded", "partially_refunded", "refunded")),
            )
        )
    ).all()
    converted_users = {
        row.created_by
        for row in paid_rows
        if row.created_by in conversion_cohort
        and row.paid_at is not None
        and _aware(row.paid_at) >= conversion_cohort[row.created_by]
    }
    payment_ids = {row.id for row in paid_rows}
    refund_rows = (
        await session.execute(
            select(
                Refund.payment_id,
                Refund.amount_minor,
                Refund.currency,
                Refund.status,
                Refund.created_at,
            ).where(
                Refund.tenant_id == tenant_id,
                Refund.payment_id.in_(payment_ids),
                Refund.status == "succeeded",
                Refund.created_at < generated_at,
            )
        )
    ).all()
    refunded_payment_ids = {row.payment_id for row in refund_rows}
    currency_summaries: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "paid_payments": 0,
            "paid_amount_minor": 0,
            "refunded_payments": 0,
            "refunded_amount_minor": 0,
        }
    )
    for row in paid_rows:
        summary = currency_summaries[row.currency]
        summary["paid_payments"] += 1
        summary["paid_amount_minor"] += row.amount_minor
    refunded_by_currency_payment: dict[str, set[uuid.UUID]] = defaultdict(set)
    for row in refund_rows:
        summary = currency_summaries[row.currency]
        summary["refunded_amount_minor"] += row.amount_minor
        refunded_by_currency_payment[row.currency].add(row.payment_id)
    for currency, ids in refunded_by_currency_payment.items():
        currency_summaries[currency]["refunded_payments"] = len(ids)
    refunds_by_currency = [
        RefundCurrencySummary(currency=currency, **values)
        for currency, values in sorted(currency_summaries.items())
    ]

    if exported_cost_complete:
        credit_cost_per_exported_project = _average_metric(
            key="credit_cost_per_exported_project",
            label="Credit cost per exported project",
            numerator=float(exported_credits),
            denominator=len(exported_project_ids),
            unit="credits_per_project",
            definition=(
                "Completed-job credits inside the window for projects exported inside the "
                "window, divided by distinct exported projects. Every project must have "
                "attributable job-cost evidence or the metric is withheld."
            ),
            sources=["processing_jobs", "exports"],
        )
    else:
        credit_cost_per_exported_project = _unavailable_metric(
            key="credit_cost_per_exported_project",
            label="Credit cost per exported project",
            unit="credits_per_project",
            definition=(
                "Withheld until each exported project in the window has attributable "
                "completed-job credit evidence in the same window."
            ),
            sources=["processing_jobs", "exports"],
            status="insufficient_evidence",
        )

    economics = {
        "credit_cost_per_page": _average_metric(
            key="credit_cost_per_page",
            label="Credit cost per processed page",
            numerator=float(attributable_credits),
            denominator=attributable_pages,
            unit="credits_per_page",
            definition=(
                "Recorded completed-job credits divided by recorded progress.total pages, "
                "using only jobs where both values are valid. Credits are not currency."
            ),
            sources=["processing_jobs.cost_actual", "processing_jobs.progress"],
        ),
        "credit_cost_evidence_coverage": _ratio_metric(
            key="credit_cost_evidence_coverage",
            label="Credit-cost evidence coverage",
            numerator=len(attributable_jobs),
            denominator=len(completed_jobs_in_window),
            definition=(
                "Completed jobs in the window with valid non-negative credit cost and positive "
                "page count, divided by completed jobs in the window."
            ),
            sources=["processing_jobs.cost_actual", "processing_jobs.progress"],
        ),
        "credit_cost_per_exported_project": credit_cost_per_exported_project,
        "credit_breakage_rate": _unavailable_metric(
            key="credit_breakage_rate",
            label="Paid-credit breakage rate",
            unit="ratio",
            definition=(
                "Not computed: expired ledger entries cannot currently be attributed to a "
                "specific paid credit grant without inventing a FIFO/LIFO policy."
            ),
            sources=["credit_ledger", "credit_grants"],
            status="insufficient_evidence",
        ),
        "gross_margin_rate": _unavailable_metric(
            key="gross_margin_rate",
            label="Gross margin rate",
            unit="ratio",
            definition=(
                "Not computed: provider invoice costs and currency-normalized revenue are not "
                "present. Credit consumption is never treated as monetary cost."
            ),
            sources=["payments", "provider invoices (not connected)"],
            status="insufficient_evidence",
        ),
        "paid_conversion_rate": _ratio_metric(
            key="paid_conversion_rate",
            label="Paid conversion rate",
            numerator=len(converted_users),
            denominator=len(conversion_cohort),
            definition=(
                "Members who joined in the selected window and completed a successful payment "
                "after joining but before the window end, divided by members joining in the "
                "window. This is a period cohort and may be right-censored."
            ),
            sources=["memberships", "payment_checkouts", "payments"],
        ),
        "support_minutes_per_job": (
            _unavailable_metric(
                key="support_minutes_per_job",
                label="Instrumented support minutes per job",
                unit="minutes_per_job",
                definition=(
                    "Optional support-session events are suppressed in private mode; absence "
                    "is not interpreted as zero."
                ),
                sources=["audit_events(product.support_session_closed)", "processing_jobs"],
                status="not_instrumented",
            )
            if tenant.private_mode
            else _average_metric(
                key="support_minutes_per_job",
                label="Instrumented support minutes per job",
                numerator=support_seconds / 60,
                denominator=len(completed_jobs_in_window),
                unit="minutes_per_job",
                definition=(
                    "Sum of recorded support-session duration seconds in the window, converted "
                    "to minutes, divided by completed processing jobs in the window."
                ),
                sources=["audit_events(product.support_session_closed)", "processing_jobs"],
            )
        ),
        "refund_payment_rate": _ratio_metric(
            key="refund_payment_rate",
            label="Refunded-payment rate",
            numerator=len(refunded_payment_ids),
            denominator=len(payment_ids),
            definition=(
                "Successful-payment cohort paid in the selected window with at least one "
                "successful refund observed before window end, divided by that payment cohort."
            ),
            sources=["payments", "payment_refunds"],
        ),
    }

    cohorts = [
        AnalyticsCohort(
            key="activation_signup_7d_matured",
            start_at=activation_cohort_start,
            end_at=activation_cohort_end,
            observation_days=7,
            population=len(activation_members),
            definition=(
                "Workspace members in a selected-length signup interval shifted back seven "
                "days; each has a full seven-day activation observation."
            ),
        ),
        repeat_7d_cohort,
        repeat_30d_cohort,
        AnalyticsCohort(
            key="paid_conversion_period",
            start_at=start_at,
            end_at=generated_at,
            observation_days=days,
            population=len(conversion_cohort),
            definition=(
                "Members joining in the selected window; payments must occur after join and "
                "before window end. Recent members have shorter exposure."
            ),
        ),
    ]
    collection_mode: Literal[
        "private_operational_only",
        "tenant_local_first_party",
    ] = "private_operational_only" if tenant.private_mode else "tenant_local_first_party"
    limitations = [
        "All intervals use UTC and [start, end) boundaries.",
        "Optional behavior metrics count only allowlisted events recorded after instrumentation.",
        "Soft-deleted projects and documents are excluded.",
        "Currency amounts remain in minor units and are never summed across currencies.",
        "No external benchmark, support platform, provider invoice, or market data is inferred.",
    ]
    if tenant.private_mode:
        limitations.append(
            "Private mode suppresses optional behavior-event storage; "
            "operational aggregates remain local."
        )
    return ProductAnalyticsSnapshot(
        generated_at=generated_at,
        window=window,
        privacy=AnalyticsPrivacy(
            enabled=True,
            private_mode=tenant.private_mode,
            collection_mode=collection_mode,
            optional_behavior_events_stored=not tenant.private_mode,
            payload_policy=(
                "Tenant-scoped counts and allowlisted enums/numbers only; no content, "
                "filename, URL, contact, or free-text fields."
            ),
        ),
        cohorts=cohorts,
        north_star=north_star,
        activation=activation,
        product=product,
        export_profiles=export_profiles,
        quality=quality,
        economics=economics,
        refunds_by_currency=refunds_by_currency,
        limitations=limitations,
    )
