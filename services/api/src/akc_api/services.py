"""Transactional domain services shared by HTTP and worker adapters."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, timedelta
from decimal import Decimal
from typing import Any, cast

from akc_cir import (
    EventType,
    KnowledgeBundle,
    NormalizationBlock,
    PageState,
    analyze_document_structure,
    detect_repeated_marginal_blocks,
    normalize_block_text,
    restore_cross_page_continuity,
)
from akc_router import (
    DataPolicy,
    EscalationAction,
    PageMetrics,
    ProcessingMode,
    Route,
    RouterContext,
    decide_escalation,
    select_first_route,
)
from akc_security import detect_prompt_injection, detect_sensitive_data
from akc_telemetry import (
    record_credit_duplicate_consume,
    record_credit_entry,
    record_external_egress_denied,
    record_job_terminal,
    record_page_terminal,
    record_provider_request,
    record_unsupported_claim,
)
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.artifacts import build_export_bundle as build_artifact_bundle
from akc_api.collection_integrity_runtime import (
    IntegrityActionRejected,
    integrity_region_bbox,
    reconcile_integrity_retry_job,
    resolve_pinned_retry_binding,
)
from akc_api.credit_policy import (
    CreditPolicyError,
    CreditState,
    apply_credit_transition,
)
from akc_api.feature_flags import CHART_DESCRIPTION_FLAG, feature_enabled
from akc_api.gpu_jobs import (
    GpuInvocationSpec,
    GpuTransitionPolicy,
    GpuTransitionTarget,
    enqueue_gpu_invocation,
)
from akc_api.knowledge_gpu import (
    KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
    KnowledgeStage,
    KnowledgeStageInput,
    KnowledgeStageResult,
    StageAResult,
    StageBResult,
    StageCResult,
    StageDResult,
    canonical_json_bytes,
    knowledge_input_sha256,
    validate_knowledge_stage_result,
)
from akc_api.knowledge_pipeline import (
    assemble_knowledge_bundle,
    build_stage_a_input,
    build_stage_b_inputs,
    build_stage_c_input,
    build_stage_d_input,
    knowledge_compile_input_sha256,
    pipeline_candidates,
)
from akc_api.models import (
    AuditEvent,
    Block,
    CreditAccount,
    CreditLedger,
    Document,
    DocumentSemanticClassification,
    Export,
    GpuProviderInvocation,
    JobEvent,
    KnowledgeNote,
    OutboxEvent,
    Page,
    PageAsset,
    PageAttempt,
    ProcessingJob,
    Project,
    Relation,
    SourceFile,
    utcnow,
)
from akc_api.page_attempts import (
    attach_provider_invocation,
    create_page_attempt,
    next_attempt_number,
    transition_page_attempt,
)
from akc_api.page_quality import (
    PageQualityBlock,
    evaluate_page_quality,
    quality_block_from_record,
)
from akc_api.providers import (
    CompiledNote,
    DurableQwenKnowledgeProvider,
    KnowledgeProviderSettings,
    ProviderUnavailable,
    knowledge_provider,
)
from akc_api.routing_runtime import (
    RoutingRuntime,
    constrain_routing_runtime_for_page,
    load_routing_runtime,
)
from akc_api.settings import Settings
from akc_api.storage import ObjectStore
from akc_api.telemetry import after_commit_metric, track_audit_write
from akc_api.visual_gpu import (
    VISUAL_ARTIFACT_CONTRACT,
    VISUAL_PROMPT_REVISION,
    VISUAL_RASTER_MAX_BYTES,
    VISUAL_RASTER_MAX_DIMENSION,
    VISUAL_RASTER_MAX_PIXELS,
    VisualBlock,
    VisualFigureBlock,
    VisualFormulaBlock,
    VisualPageResult,
    VisualTableBlock,
    validate_visual_result,
    visual_attestation,
    visual_block_text,
)

logger = logging.getLogger(__name__)


async def audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    track_audit_write(session)
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
        )
    )


async def emit_event(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    event_type: str,
    payload: dict[str, Any],
) -> JobEvent:
    if event_type not in {item.value for item in EventType}:
        raise ValueError(f"unregistered processing event type: {event_type}")
    # Lock and read scalar columns instead of refreshing the ORM identity.
    # ``autoflush=False`` callers commonly mutate status/progress immediately
    # before emitting an event; populate_existing would silently replace those
    # unflushed values with the older database snapshot.
    locked = (
        await session.execute(
            select(ProcessingJob.status, ProcessingJob.event_sequence)
            .where(
                ProcessingJob.tenant_id == job.tenant_id,
                ProcessingJob.id == job.id,
            )
            .with_for_update()
        )
    ).one_or_none()
    if locked is None:
        raise RuntimeError("job_missing")
    locked_status, locked_sequence = locked
    if locked_status == "cancelled" or job.status == "cancelled":
        raise JobCancellationFence
    job.event_sequence = max(job.event_sequence, locked_sequence) + 1
    event = JobEvent(
        tenant_id=job.tenant_id,
        job_id=job.id,
        sequence=job.event_sequence,
        event_type=event_type,
        schema_version="1.0",
        payload=payload,
    )
    session.add(event)
    await session.flush()
    return event


class JobCancellationFence(RuntimeError):
    """Raised when a committed tombstone/cancellation fences a running job."""


async def _active_compile_job(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
    lock_target: bool = False,
) -> ProcessingJob | None:
    statement = (
        select(ProcessingJob)
        .join(
            Project,
            (Project.tenant_id == ProcessingJob.tenant_id)
            & (Project.id == ProcessingJob.project_id),
        )
        .join(
            Document,
            (Document.tenant_id == ProcessingJob.tenant_id)
            & (Document.id == ProcessingJob.document_id),
        )
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.status.in_(("queued", "running")),
            Project.deletion_requested_at.is_(None),
            Document.deletion_requested_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    if tenant_id is not None:
        statement = statement.where(ProcessingJob.tenant_id == tenant_id)
    if lock_target:
        statement = statement.with_for_update()
    return cast(ProcessingJob | None, await session.scalar(statement))


async def _lock_document_compile_revision(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    document_id: uuid.UUID,
    document_version: int,
) -> Document:
    """Serialize active-pointer changes for one immutable document revision."""

    document = cast(
        Document | None,
        await session.scalar(
            select(Document)
            .where(
                Document.tenant_id == job.tenant_id,
                Document.project_id == job.project_id,
                Document.id == document_id,
                Document.active_version == document_version,
                Document.deletion_requested_at.is_(None),
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        ),
    )
    if document is None:
        raise ProviderUnavailable("DURABLE_QWEN_DOCUMENT_REVISION_CHANGED")
    return document


def _active_revision_integrity_error(exc: IntegrityError) -> bool:
    constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint_name in {
        "document_semantic_classifications_one_active_idx",
        "knowledge_notes_one_active_revision_idx",
        "relations_one_active_revision_idx",
        "uq_document_semantic_classification_version",
        "uq_knowledge_note_compile_revision",
        "uq_relation_compile_revision",
    }:
        return True
    message = str(exc.orig).casefold()
    return "unique" in message and any(
        table in message
        for table in (
            "document_semantic_classifications",
            "knowledge_notes",
            "relations",
        )
    )


async def _flush_active_knowledge_revisions(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        if _active_revision_integrity_error(exc):
            raise ProviderUnavailable("DURABLE_QWEN_ACTIVE_REVISION_CONFLICT") from exc
        raise


async def credit_entry(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    operation_key: str,
    entry_type: str,
    credits: Decimal,
    job_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> CreditLedger:
    existing = await session.scalar(
        select(CreditLedger).where(
            CreditLedger.tenant_id == tenant_id,
            CreditLedger.operation_key == operation_key,
        )
    )
    if existing:
        if entry_type == "consume":
            after_commit_metric(session, record_credit_duplicate_consume)
        return existing
    account = await session.scalar(
        select(CreditAccount).where(CreditAccount.tenant_id == tenant_id).with_for_update()
    )
    if account is None:
        account = CreditAccount(tenant_id=tenant_id)
        session.add(account)
        await session.flush()
    amount = Decimal(credits)
    try:
        next_state = apply_credit_transition(
            CreditState(
                balance=Decimal(account.balance),
                reserved=Decimal(account.reserved),
            ),
            entry_type=entry_type,
            credits=amount,
            from_reserved=bool((metadata or {}).get("from_reserved")),
        )
    except CreditPolicyError as exc:
        if exc.code == "insufficient_credits":
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "INSUFFICIENT_CREDITS",
                    "available": str(exc.available),
                    "required": str(amount),
                },
            ) from exc
        if exc.code in {"credits_must_be_positive", "unsupported_credit_entry"}:
            raise ValueError(exc.code) from exc
        raise RuntimeError(exc.code) from exc
    account.balance = next_state.balance
    account.reserved = next_state.reserved
    account.version += 1
    ledger = CreditLedger(
        tenant_id=tenant_id,
        job_id=job_id,
        operation_key=operation_key,
        entry_type=entry_type,
        credits=amount,
        balance_after=account.balance,
        reserved_after=account.reserved,
        metadata_json=metadata or {},
    )
    session.add(ledger)
    await session.flush()
    after_commit_metric(session, record_credit_entry, entry_type, amount)
    return ledger


async def analyze_document(
    session: AsyncSession,
    *,
    document: Document,
    source: SourceFile,
    store: ObjectStore,
    settings: Settings,
) -> tuple[int, int]:
    """Legacy local adapter; the production API never calls this function."""

    if settings.env == "production":
        raise RuntimeError("in_process_document_analysis_forbidden")
    from akc_api.parsers import page_preflight, parse_document

    document.status = "PREFLIGHTING"
    await session.flush()
    raw = await store.read_source(source.storage_key)
    parsed = parse_document(source.safe_filename, raw, settings)
    existing_pages = list(
        (
            await session.scalars(
                select(Page).where(
                    Page.tenant_id == document.tenant_id,
                    Page.document_id == document.id,
                )
            )
        ).all()
    )
    for page in existing_pages:
        await session.delete(page)
    await session.flush()
    block_count = 0
    document_states: set[str] = set()
    for parsed_page in parsed.pages:
        injection = detect_prompt_injection(parsed_page.text)
        metrics = page_preflight(
            parsed_page.text,
            image_coverage=parsed_page.image_coverage,
        )
        router_metrics = PageMetrics(
            page_index0=parsed_page.page_number - 1,
            width=max(1, round(parsed_page.width_pt or 1000)),
            height=max(1, round(parsed_page.height_pt or 1000)),
            native_text_chars=int(metrics["native_text_chars"]),
            native_word_count=int(metrics["native_words"]),
            native_block_count=1 if parsed_page.text else 0,
            native_text_coverage=(
                min(1.0, max(0.03, len(parsed_page.text) / 5000)) if parsed_page.text else 0.0
            ),
            image_coverage=parsed_page.image_coverage,
            invalid_unicode_ratio=float(metrics["invalid_char_ratio"]),
            replacement_char_ratio=float(metrics["replacement_char_ratio"]),
            whitespace_anomaly_score=0.0,
            native_reading_order_score=1.0 if parsed_page.text else 0.0,
            estimated_columns=1 if parsed_page.text else 0,
            table_density=0.0,
            formula_density=0.0,
            chart_probability=0.0,
            handwriting_probability=0.0,
            rotation_degrees=0,
            skew_degrees=0.0,
            blur_score=0.0,
            contrast_score=1.0,
            small_text_score=0.0,
            script_distribution={},
            suspected_prompt_injection=injection.suspected,
        )
        route_decision = select_first_route(
            RouterContext(
                mode=ProcessingMode.PRIVATE if settings.private_mode else ProcessingMode.BALANCED,
                data_policy=DataPolicy(
                    external_api_allowed=False,
                    retention_days=settings.default_retention_days,
                    private_processing=settings.private_mode,
                ),
                ready_routes=frozenset({Route.NATIVE}),
                policy_version="router-2026-07-29.1",
            ),
            router_metrics,
        )
        accepted_native = route_decision.route == Route.NATIVE
        verified_native = accepted_native and not injection.suspected
        isolated_status = "QUARANTINED" if injection.suspected else "UNRESOLVED"
        page = Page(
            tenant_id=document.tenant_id,
            document_id=document.id,
            page_number=parsed_page.page_number,
            width_pt=parsed_page.width_pt,
            height_pt=parsed_page.height_pt,
            status="COMPLETED" if verified_native else isolated_status,
            route=route_decision.route.value,
            route_policy_version=route_decision.policy_version,
            preflight_metrics={
                **metrics,
                "suspected_prompt_injection": injection.suspected,
                "prompt_injection_risk": injection.risk.value,
                "prompt_injection_rules": [signal.rule_id for signal in injection.signals],
                "route_reasons": list(route_decision.reason_codes),
                "route_profile": route_decision.route_profile.value,
                "expected_credits": route_decision.expected_credits,
            },
            quality_metrics={
                "schema_valid": verified_native,
                "source_coverage": 1.0 if parsed_page.text else 0.0,
                "state": (
                    "verified"
                    if verified_native
                    else "quarantined"
                    if injection.suspected
                    else "unresolved"
                ),
                "prompt_injection_advisory": injection.suspected,
            },
        )
        session.add(page)
        document_states.add(page.status)
        await session.flush()
        if parsed_page.text:
            content_hash = hashlib.sha256(parsed_page.text.encode()).hexdigest()
            session.add(
                Block(
                    tenant_id=document.tenant_id,
                    document_id=document.id,
                    page_id=page.id,
                    block_order=block_count,
                    block_type="paragraph",
                    origin="native_extracted",
                    bbox1000=[1, 1, 999, 999],
                    source_text=parsed_page.text,
                    normalized_text=parsed_page.text,
                    markdown=parsed_page.text,
                    engine="native",
                    engine_revision="cpu-document-1",
                    confidence=1.0,
                    content_hash=content_hash,
                )
            )
            block_count += 1
    document.document_type = parsed.document_type
    document.page_count = len(parsed.pages)
    document.status = (
        "QUARANTINED"
        if "QUARANTINED" in document_states
        else "PARTIAL"
        if "UNRESOLVED" in document_states
        else "COMPLETED"
    )
    await session.flush()
    return len(parsed.pages), block_count


async def estimate_document(session: AsyncSession, document: Document) -> dict[str, Any]:
    pages = list(
        (
            await session.scalars(
                select(Page).where(
                    Page.tenant_id == document.tenant_id,
                    Page.document_id == document.id,
                )
            )
        ).all()
    )
    native = sum(1 for page in pages if page.route == "native")
    visual = len(pages) - native
    native_cost = Decimal(native) * Decimal("0.25")
    visual_cost = Decimal(visual) * Decimal("1.0")
    knowledge = Decimal(len(pages)) * Decimal("0.5")
    expected = native_cost + visual_cost + knowledge
    upper = (expected * Decimal("1.15")).quantize(Decimal("0.000001"))
    block_rows = list(
        (
            await session.scalars(
                select(Block).where(
                    Block.tenant_id == document.tenant_id,
                    Block.document_id == document.id,
                )
            )
        ).all()
    )
    precision_candidates = sum(
        1
        for page in pages
        if any(
            float(page.preflight_metrics.get(key, 0)) > 0
            for key in ("table_density", "formula_density", "chart_probability")
        )
    )
    expected_seconds = native * 1 + visual * 8 + len(pages)
    return {
        "native": native_cost,
        "visual": visual_cost,
        "knowledge": knowledge,
        "expected": expected,
        "upper_bound": upper,
        "reserved": upper,
        "total_pages": len(pages),
        "native_pages": native,
        "visual_pages": visual,
        "precision_candidate_pages": precision_candidates,
        "tables": sum(block.block_type == "table" for block in block_rows),
        "formulas": sum(block.block_type == "formula" for block in block_rows),
        "figures": sum(block.block_type == "figure" for block in block_rows),
        "third_party_model_api": False,
        "expected_duration_min": max(1, expected_seconds // 60) if pages else 0,
        "expected_duration_max": max(1, (expected_seconds * 2 + 59) // 60) if pages else 0,
    }


def _knowledge_stage_paths(
    *,
    job: ProcessingJob,
    document: Document,
    stage: KnowledgeStage,
    unit_id: str,
) -> tuple[str, str]:
    prefix = (
        f"tenants/{job.tenant_id}/derived/jobs/{job.id}/knowledge/"
        f"v{document.active_version}/{stage.lower()}/{unit_id}"
    )
    return f"{prefix}.input.json", f"{prefix}.output.json"


def _knowledge_stage_options(
    *,
    provider: DurableQwenKnowledgeProvider,
    stage: KnowledgeStage,
    unit_id: str,
    compile_input_sha256: str,
) -> dict[str, Any]:
    return {
        "artifact_contract": KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
        "prompt_revision": provider.prompt_revision,
        "knowledge_schema_sha256": provider.knowledge_schema_sha256,
        "knowledge_stage": stage,
        "knowledge_unit_id": unit_id,
        "knowledge_compile_input_sha256": compile_input_sha256,
        "temperature": 0.1,
        "top_p": 0.8,
        "max_output_tokens": 8192,
    }


async def _knowledge_pipeline_invocations(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    provider: DurableQwenKnowledgeProvider,
    stage: KnowledgeStage,
) -> dict[str, GpuProviderInvocation]:
    rows = list(
        (
            await session.scalars(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == job.tenant_id,
                    GpuProviderInvocation.job_id == job.id,
                )
                .order_by(GpuProviderInvocation.created_at, GpuProviderInvocation.id)
            )
        ).all()
    )
    child_parent_ids = {
        row.parent_invocation_id for row in rows if row.parent_invocation_id is not None
    }
    rows = [row for row in rows if row.id not in child_parent_ids]
    values: dict[str, GpuProviderInvocation] = {}
    for invocation in rows:
        if (
            invocation.options.get("artifact_contract") != KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT
            or invocation.options.get("knowledge_stage") != stage
        ):
            continue
        unit_id = invocation.options.get("knowledge_unit_id")
        if not isinstance(unit_id, str) or unit_id in values:
            raise ProviderUnavailable("DURABLE_QWEN_STAGE_INVOCATION_DUPLICATE")
        values[unit_id] = invocation
    return values


async def _set_knowledge_waiting(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    pages: list[Page],
    stage: KnowledgeStage,
    invocations: list[GpuProviderInvocation],
    compile_input_sha256: str,
) -> None:
    active_job = await _active_compile_job(
        session,
        job_id=job.id,
        tenant_id=job.tenant_id,
        lock_target=True,
    )
    if active_job is None:
        raise JobCancellationFence
    done = sum(invocation.status == "completed" for invocation in invocations)
    progress = {
        "stage": "knowledge_waiting",
        "knowledge_stage": stage,
        "done": len(pages),
        "total": max(1, len(pages)),
        "knowledge_units_done": done,
        "knowledge_units_total": len(invocations),
        "knowledge_compile_input_sha256": compile_input_sha256,
        "invocation_ids": [str(invocation.id) for invocation in invocations],
    }
    changed = active_job.progress != progress
    active_job.progress = progress
    if changed:
        await emit_event(
            session,
            job=active_job,
            event_type="job.stage.progress.v1",
            payload={
                "stage": "knowledge",
                "pipeline_stage": stage,
                "done": done,
                "total": len(invocations),
                "state": "provider_waiting",
            },
        )
    await session.commit()


def _validate_stage_invocation(
    *,
    invocation: GpuProviderInvocation,
    stage_input: KnowledgeStageInput,
    input_key: str,
    output_key: str,
    input_sha: str,
    options: dict[str, Any],
    provider: DurableQwenKnowledgeProvider,
) -> None:
    expected_options = dict(options)
    actual_options = dict(invocation.options)
    expected_output = output_key
    if invocation.parent_invocation_id is not None:
        if (
            invocation.transition_category != "gpu_oom"
            or invocation.transition_strategy != "reduce_or_escalate"
            or invocation.transition_action != "reduce"
            or invocation.lineage_root_invocation_id is None
        ):
            raise ProviderUnavailable("DURABLE_QWEN_INVOCATION_ATTESTATION_MISMATCH")
        expected_tokens = expected_options.pop("max_output_tokens", None)
        actual_tokens = actual_options.pop("max_output_tokens", None)
        if (
            not isinstance(expected_tokens, int)
            or not isinstance(actual_tokens, int)
            or not 128 <= actual_tokens < expected_tokens
        ):
            raise ProviderUnavailable("DURABLE_QWEN_INVOCATION_ATTESTATION_MISMATCH")
        expected_output = invocation.output_object_key
    if (
        invocation.input_object_key != input_key
        or invocation.input_sha256 != input_sha
        or invocation.output_object_key != expected_output
        or invocation.model_revision != provider.model_revision
        or invocation.runtime_image_digest != provider.runtime_image_digest
        or invocation.adapter_version != provider.adapter_version
        or invocation.document_version_id != stage_input.document_version_id
        or actual_options != expected_options
    ):
        raise ProviderUnavailable("DURABLE_QWEN_INVOCATION_ATTESTATION_MISMATCH")


async def _admit_stage_outputs(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    provider: DurableQwenKnowledgeProvider,
    object_store: ObjectStore,
    expected: tuple[
        tuple[
            KnowledgeStageInput,
            bytes,
            str,
            str,
            str,
            dict[str, Any],
            GpuProviderInvocation,
        ],
        ...,
    ],
) -> tuple[KnowledgeStageResult, ...]:
    terminal_manifests: dict[uuid.UUID, str | None] = {}
    for stage_input, _, _, _, output_key, _, invocation in expected:
        manifest = invocation.result_manifest
        if not isinstance(manifest, dict):
            raise ProviderUnavailable("DURABLE_QWEN_RESULT_MANIFEST_MISSING")
        attestation = manifest.get("knowledge_attestation")
        if (
            not isinstance(attestation, dict)
            or attestation.get("artifact_contract") != KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT
            or attestation.get("prompt_revision") != provider.prompt_revision
            or attestation.get("knowledge_schema_sha256") != provider.knowledge_schema_sha256
            or attestation.get("knowledge_stage") != stage_input.stage
            or attestation.get("knowledge_unit_id") != stage_input.unit_id
            or attestation.get("unsupported_claim_count") != 0
            or manifest.get("output_object_key") != output_key
        ):
            raise ProviderUnavailable("DURABLE_QWEN_RESULT_ATTESTATION_MISMATCH")
        terminal_manifests[invocation.id] = invocation.result_manifest_sha256

    await session.commit()
    results: list[KnowledgeStageResult] = []
    for stage_input, input_body, input_sha, input_key, output_key, _, invocation in expected:
        manifest = invocation.result_manifest
        assert isinstance(manifest, dict)
        output_sha = str(manifest.get("output_sha256", "")).removeprefix("sha256:")
        if len(output_sha) != 64:
            raise ProviderUnavailable("DURABLE_QWEN_RESULT_MANIFEST_INVALID")
        try:
            stored_input, output_body = await asyncio.gather(
                object_store.read_derived(input_key),
                object_store.read_derived(output_key),
            )
        except Exception as exc:
            raise ProviderUnavailable("DURABLE_QWEN_RESULT_OBJECT_UNAVAILABLE") from exc
        if (
            stored_input != input_body
            or hashlib.sha256(stored_input).hexdigest() != input_sha
            or hashlib.sha256(output_body).hexdigest() != output_sha
        ):
            raise ProviderUnavailable("DURABLE_QWEN_RESULT_OBJECT_CHECKSUM_MISMATCH")
        try:
            output_payload = json.loads(output_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderUnavailable("DURABLE_QWEN_RESULT_OBJECT_INVALID") from exc
        if not isinstance(output_payload, dict):
            raise ProviderUnavailable("DURABLE_QWEN_RESULT_OBJECT_INVALID")
        try:
            result = validate_knowledge_stage_result(
                output_payload=output_payload,
                input_body=stored_input,
                expected_prompt_revision=provider.prompt_revision,
                expected_schema_sha256=provider.knowledge_schema_sha256,
                expected_stage=stage_input.stage,
                expected_unit_id=stage_input.unit_id,
            )
        except (TypeError, ValueError) as exc:
            raise ProviderUnavailable("DURABLE_QWEN_KNOWLEDGE_ADMISSION_FAILED") from exc
        results.append(result)

    active_job = await _active_compile_job(
        session,
        job_id=job.id,
        tenant_id=job.tenant_id,
        lock_target=True,
    )
    locked = list(
        (
            await session.scalars(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == job.tenant_id,
                    GpuProviderInvocation.id.in_(terminal_manifests),
                )
                .with_for_update()
            )
        ).all()
    )
    if (
        active_job is None
        or len(locked) != len(terminal_manifests)
        or any(
            invocation.status != "completed"
            or invocation.result_manifest_sha256 != terminal_manifests[invocation.id]
            for invocation in locked
        )
    ):
        raise JobCancellationFence
    return tuple(results)


async def _durable_qwen_stage(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    document: Document,
    pages: list[Page],
    provider: DurableQwenKnowledgeProvider,
    object_store: ObjectStore,
    stage_inputs: tuple[KnowledgeStageInput, ...],
    compile_input_sha256: str,
) -> tuple[KnowledgeStageResult, ...] | None:
    if not stage_inputs:
        raise RuntimeError("knowledge_pipeline_stage_has_no_units")
    stage = stage_inputs[0].stage
    if any(stage_input.stage != stage for stage_input in stage_inputs):
        raise RuntimeError("knowledge_pipeline_mixed_stage_inputs")
    expected_units = {stage_input.unit_id for stage_input in stage_inputs}
    if len(expected_units) != len(stage_inputs):
        raise RuntimeError("knowledge_pipeline_duplicate_unit")
    existing = await _knowledge_pipeline_invocations(
        session=session,
        job=job,
        provider=provider,
        stage=stage,
    )
    if set(existing) - expected_units:
        raise ProviderUnavailable("DURABLE_QWEN_UNEXPECTED_STAGE_INVOCATION")

    prepared: list[
        tuple[
            KnowledgeStageInput,
            bytes,
            str,
            str,
            str,
            dict[str, Any],
            GpuProviderInvocation | None,
        ]
    ] = []
    missing: list[
        tuple[
            KnowledgeStageInput,
            bytes,
            str,
            str,
            str,
            dict[str, Any],
        ]
    ] = []
    for stage_input in stage_inputs:
        input_body = canonical_json_bytes(stage_input)
        input_sha = knowledge_input_sha256(stage_input)
        input_key, output_key = _knowledge_stage_paths(
            job=job,
            document=document,
            stage=stage,
            unit_id=stage_input.unit_id,
        )
        options = _knowledge_stage_options(
            provider=provider,
            stage=stage,
            unit_id=stage_input.unit_id,
            compile_input_sha256=compile_input_sha256,
        )
        invocation = existing.get(stage_input.unit_id)
        if invocation is None:
            missing.append(
                (
                    stage_input,
                    input_body,
                    input_sha,
                    input_key,
                    output_key,
                    options,
                )
            )
        else:
            _validate_stage_invocation(
                invocation=invocation,
                stage_input=stage_input,
                input_key=input_key,
                output_key=output_key,
                input_sha=input_sha,
                options=options,
                provider=provider,
            )
        prepared.append(
            (
                stage_input,
                input_body,
                input_sha,
                input_key,
                (invocation.output_object_key if invocation is not None else output_key),
                options,
                invocation,
            )
        )

    if missing:
        await session.commit()
        try:
            await asyncio.gather(
                *(
                    object_store.put_derived(input_key, input_body)
                    for _, input_body, _, input_key, _, _ in missing
                )
            )
        except Exception as exc:
            raise ProviderUnavailable("DURABLE_QWEN_INPUT_OBJECT_UNAVAILABLE") from exc
        active_job = await _active_compile_job(
            session,
            job_id=job.id,
            tenant_id=job.tenant_id,
            lock_target=True,
        )
        if active_job is None:
            raise JobCancellationFence
        for stage_input, _, input_sha, input_key, output_key, options in missing:
            invocation = await enqueue_gpu_invocation(
                session,
                GpuInvocationSpec(
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    project_id=job.project_id,
                    document_id=document.id,
                    document_version_id=stage_input.document_version_id,
                    provider_key=provider.provider_key,
                    endpoint_id=provider.endpoint_id,
                    idempotency_key=(
                        f"knowledge-{job.id.hex}-{stage.lower()}-{stage_input.unit_id}"
                    ),
                    input_bucket="derived",
                    input_object_key=input_key,
                    input_sha256=input_sha,
                    output_object_key=output_key,
                    model_revision=provider.model_revision,
                    runtime_image_digest=provider.runtime_image_digest,
                    adapter_version=provider.adapter_version,
                    options=options,
                    max_attempts=provider.max_attempts,
                ),
            )
            existing[stage_input.unit_id] = invocation
        await session.flush()

    invocations = [existing[stage_input.unit_id] for stage_input in stage_inputs]
    for invocation in invocations:
        if invocation.status not in {
            "queued",
            "submitting",
            "submitted",
            "running",
            "retry",
            "cancel_requested",
            "cancelling",
            "completed",
        }:
            raise ProviderUnavailable(
                "DURABLE_QWEN_PROVIDER_FAILED:"
                + (invocation.last_error_code or invocation.status).upper()
            )
    if any(invocation.status != "completed" for invocation in invocations):
        await _set_knowledge_waiting(
            session=session,
            job=job,
            pages=pages,
            stage=stage,
            invocations=invocations,
            compile_input_sha256=compile_input_sha256,
        )
        return None

    admitted_input = tuple(
        (
            stage_input,
            input_body,
            input_sha,
            input_key,
            output_key,
            options,
            existing[stage_input.unit_id],
        )
        for stage_input, input_body, input_sha, input_key, output_key, options, _ in prepared
    )
    return await _admit_stage_outputs(
        session=session,
        job=job,
        provider=provider,
        object_store=object_store,
        expected=admitted_input,
    )


_BCP47_LANGUAGE = re.compile(
    r"^[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
    r"(?:-[A-Za-z0-9]{5,8})*$"
)
_UNKNOWN_LANGUAGES = frozenset({"", "und", "unknown", "un", "n/a", "none"})
_HEX_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


def _normalized_language_code(value: str) -> str | None:
    candidate = value.strip()
    if candidate.casefold() in _UNKNOWN_LANGUAGES or not _BCP47_LANGUAGE.fullmatch(candidate):
        return None
    parts = candidate.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def _apply_evidence_bound_languages(
    document: Document,
    stage_a: StageAResult,
) -> None:
    classification = stage_a.classification
    raw = classification.languages or (classification.language,)
    normalized = tuple(
        dict.fromkeys(
            code for value in raw if (code := _normalized_language_code(value)) is not None
        )
    )
    if normalized:
        document.language_codes = list(normalized)


def _gpu_invocation_provenance(
    invocation: GpuProviderInvocation,
) -> dict[str, Any]:
    result = invocation.result_manifest
    output_sha = result.get("output_sha256") if isinstance(result, dict) else None
    values = {
        "input_sha256": invocation.input_sha256,
        "output_sha256": output_sha,
        "request_manifest_sha256": invocation.request_manifest_sha256,
        "result_manifest_sha256": invocation.result_manifest_sha256,
    }
    if invocation.status != "completed" or not all(
        isinstance(value, str) and _HEX_SHA256.fullmatch(value) for value in values.values()
    ):
        raise ProviderUnavailable("DURABLE_QWEN_INVOCATION_PROVENANCE_INCOMPLETE")
    return {
        "invocation_id": str(invocation.id),
        "stage": invocation.options.get("knowledge_stage"),
        "unit_id": invocation.options.get("knowledge_unit_id"),
        **values,
    }


async def _persist_semantic_classification(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    document: Document,
    provider: DurableQwenKnowledgeProvider,
    stage_a: StageAResult,
) -> None:
    payload = stage_a.classification.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    stage_a_invocations = await _knowledge_pipeline_invocations(
        session=session,
        job=job,
        provider=provider,
        stage="A",
    )
    if len(stage_a_invocations) != 1:
        raise ProviderUnavailable("DURABLE_QWEN_STAGE_A_PROVENANCE_INVALID")
    stage_a_invocation = next(iter(stage_a_invocations.values()))
    compile_input_sha256 = stage_a_invocation.options.get("knowledge_compile_input_sha256")
    if not isinstance(compile_input_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", compile_input_sha256
    ):
        raise ProviderUnavailable("DURABLE_QWEN_COMPILE_INPUT_REVISION_INVALID")
    provenance = {
        "artifact_contract": KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT,
        "invocations": [_gpu_invocation_provenance(stage_a_invocation)],
    }
    existing = await session.scalar(
        select(DocumentSemanticClassification).where(
            DocumentSemanticClassification.tenant_id == job.tenant_id,
            DocumentSemanticClassification.document_id == document.id,
            DocumentSemanticClassification.document_version == document.active_version,
            DocumentSemanticClassification.compile_input_sha256 == compile_input_sha256,
            DocumentSemanticClassification.schema_sha256 == provider.knowledge_schema_sha256,
            DocumentSemanticClassification.model_revision == provider.model_revision,
        )
    )
    if existing is not None:
        if (
            existing.classification != payload
            or existing.provider_key != provider.provider_key
            or existing.model_revision != provider.model_revision
            or existing.runtime_image_digest != provider.runtime_image_digest
            or existing.adapter_version != provider.adapter_version
            or existing.prompt_revision != provider.prompt_revision
            or existing.schema_sha256 != provider.knowledge_schema_sha256
            or existing.provenance != provenance
        ):
            raise ProviderUnavailable("DURABLE_QWEN_SEMANTIC_CLASSIFICATION_CONFLICT")
        await session.execute(
            update(DocumentSemanticClassification)
            .where(
                DocumentSemanticClassification.tenant_id == job.tenant_id,
                DocumentSemanticClassification.document_id == document.id,
                DocumentSemanticClassification.document_version == document.active_version,
                DocumentSemanticClassification.id != existing.id,
                DocumentSemanticClassification.is_active.is_(True),
            )
            .values(is_active=False)
        )
        existing.is_active = True
        _apply_evidence_bound_languages(document, stage_a)
        await _flush_active_knowledge_revisions(session)
        return
    await session.execute(
        update(DocumentSemanticClassification)
        .where(
            DocumentSemanticClassification.tenant_id == job.tenant_id,
            DocumentSemanticClassification.document_id == document.id,
            DocumentSemanticClassification.document_version == document.active_version,
            DocumentSemanticClassification.is_active.is_(True),
        )
        .values(is_active=False)
    )
    session.add(
        DocumentSemanticClassification(
            tenant_id=job.tenant_id,
            document_id=document.id,
            document_version=document.active_version,
            compile_input_sha256=compile_input_sha256,
            classification=payload,
            provenance=provenance,
            provider_key=provider.provider_key,
            model_revision=provider.model_revision,
            runtime_image_digest=provider.runtime_image_digest,
            adapter_version=provider.adapter_version,
            prompt_revision=provider.prompt_revision,
            schema_sha256=provider.knowledge_schema_sha256,
            is_active=True,
        )
    )
    _apply_evidence_bound_languages(document, stage_a)
    await _flush_active_knowledge_revisions(session)


async def _durable_qwen_bundle(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    document: Document,
    blocks: list[Block],
    pages: list[Page],
    provider: DurableQwenKnowledgeProvider,
    object_store: ObjectStore | None,
) -> KnowledgeBundle | None:
    """Run the bounded, resumable A-B-C-D knowledge pipeline."""

    if object_store is None:
        raise ProviderUnavailable("DURABLE_QWEN_OBJECT_STORE_REQUIRED")
    compile_input_sha256 = knowledge_compile_input_sha256(
        document=document,
        blocks=blocks,
    )
    stage_a_input = build_stage_a_input(
        document=document,
        blocks=blocks,
        pages=pages,
    )
    stage_a_values = await _durable_qwen_stage(
        session=session,
        job=job,
        document=document,
        pages=pages,
        provider=provider,
        object_store=object_store,
        stage_inputs=(stage_a_input,),
        compile_input_sha256=compile_input_sha256,
    )
    if stage_a_values is None:
        return None
    if len(stage_a_values) != 1 or not isinstance(stage_a_values[0], StageAResult):
        raise ProviderUnavailable("DURABLE_QWEN_STAGE_A_RESULT_INVALID")
    stage_a = stage_a_values[0]
    await _persist_semantic_classification(
        session=session,
        job=job,
        document=document,
        provider=provider,
        stage_a=stage_a,
    )

    stage_b_inputs = build_stage_b_inputs(
        document=document,
        blocks=blocks,
        pages=pages,
        section_map=stage_a,
    )
    stage_b_values = await _durable_qwen_stage(
        session=session,
        job=job,
        document=document,
        pages=pages,
        provider=provider,
        object_store=object_store,
        stage_inputs=stage_b_inputs,
        compile_input_sha256=compile_input_sha256,
    )
    if stage_b_values is None:
        return None
    if not all(isinstance(value, StageBResult) for value in stage_b_values):
        raise ProviderUnavailable("DURABLE_QWEN_STAGE_B_RESULT_INVALID")
    stage_b = tuple(value for value in stage_b_values if isinstance(value, StageBResult))
    candidates = pipeline_candidates(stage_b, stage_b_inputs=stage_b_inputs)

    stage_c_input = build_stage_c_input(
        document=document,
        candidates=candidates,
    )
    stage_c_values = await _durable_qwen_stage(
        session=session,
        job=job,
        document=document,
        pages=pages,
        provider=provider,
        object_store=object_store,
        stage_inputs=(stage_c_input,),
        compile_input_sha256=compile_input_sha256,
    )
    if stage_c_values is None:
        return None
    if len(stage_c_values) != 1 or not isinstance(stage_c_values[0], StageCResult):
        raise ProviderUnavailable("DURABLE_QWEN_STAGE_C_RESULT_INVALID")
    stage_c = stage_c_values[0]

    stage_d_input = build_stage_d_input(
        job=job,
        document=document,
        candidates=candidates,
        merge_plan=stage_c,
    )
    stage_d_values = await _durable_qwen_stage(
        session=session,
        job=job,
        document=document,
        pages=pages,
        provider=provider,
        object_store=object_store,
        stage_inputs=(stage_d_input,),
        compile_input_sha256=compile_input_sha256,
    )
    if stage_d_values is None:
        return None
    if len(stage_d_values) != 1 or not isinstance(stage_d_values[0], StageDResult):
        raise ProviderUnavailable("DURABLE_QWEN_STAGE_D_RESULT_INVALID")
    return assemble_knowledge_bundle(
        document=document,
        stage_b_results=stage_b,
        candidates=candidates,
        merge_plan=stage_c,
        links=stage_d_values[0],
    )


def _knowledge_note_markdown(note: Any) -> str:
    sections = [f"# {note.title}"]
    if note.summary:
        sections.append(note.summary)
    if note.claims:
        sections.append("## Claims\n\n" + "\n".join(f"- {claim.text}" for claim in note.claims))
    return "\n\n".join(sections).rstrip() + "\n"


def _project_note_key(document_id: uuid.UUID, note_id: str) -> str:
    prefix = f"{document_id.hex}."
    candidate = prefix + note_id
    if len(candidate) <= 128:
        return candidate
    return prefix + hashlib.sha256(note_id.encode()).hexdigest()


async def _knowledge_compile_attestation(
    *,
    session: AsyncSession,
    job: ProcessingJob,
) -> dict[str, Any]:
    invocations = list(
        (
            await session.scalars(
                select(GpuProviderInvocation).where(
                    GpuProviderInvocation.tenant_id == job.tenant_id,
                    GpuProviderInvocation.job_id == job.id,
                )
            )
        ).all()
    )
    child_parent_ids = {
        invocation.parent_invocation_id
        for invocation in invocations
        if invocation.parent_invocation_id is not None
    }
    pipeline = [
        invocation
        for invocation in invocations
        if invocation.options.get("artifact_contract") == KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT
        and invocation.id not in child_parent_ids
    ]
    if not pipeline or any(invocation.status != "completed" for invocation in pipeline):
        raise ProviderUnavailable("DURABLE_QWEN_COMPILE_ATTESTATION_INCOMPLETE")

    def exact(field: str, values: set[str]) -> str:
        if len(values) != 1 or "" in values:
            raise ProviderUnavailable(f"DURABLE_QWEN_{field.upper()}_CONFLICT")
        return next(iter(values))

    attestation = {
        "compile_input_sha256": exact(
            "compile_input_sha256",
            {
                str(invocation.options.get("knowledge_compile_input_sha256") or "")
                for invocation in pipeline
            },
        ),
        "pipeline_schema_sha256": exact(
            "pipeline_schema_sha256",
            {
                str(invocation.options.get("knowledge_schema_sha256") or "")
                for invocation in pipeline
            },
        ),
        "prompt_revision": exact(
            "prompt_revision",
            {str(invocation.options.get("prompt_revision") or "") for invocation in pipeline},
        ),
        "model_revision": exact(
            "model_revision",
            {invocation.model_revision for invocation in pipeline},
        ),
        "runtime_image_digest": exact(
            "runtime_image_digest",
            {invocation.runtime_image_digest for invocation in pipeline},
        ),
        "adapter_version": exact(
            "adapter_version",
            {invocation.adapter_version for invocation in pipeline},
        ),
        "provider_key": exact(
            "provider_key",
            {invocation.provider_key for invocation in pipeline},
        ),
        "invocations": [
            _gpu_invocation_provenance(invocation)
            for invocation in sorted(
                pipeline,
                key=lambda value: (
                    str(value.options.get("knowledge_stage") or ""),
                    str(value.options.get("knowledge_unit_id") or ""),
                ),
            )
        ],
    }
    progress_hash = job.progress.get("knowledge_compile_input_sha256")
    if progress_hash != attestation["compile_input_sha256"]:
        raise ProviderUnavailable("DURABLE_QWEN_COMPILE_INPUT_REVISION_MISMATCH")
    return attestation


def _knowledge_note_revision_matches(
    existing: KnowledgeNote,
    row: dict[str, Any],
) -> bool:
    return bool(
        existing.title == row["title"]
        and existing.note_type == row["note_type"]
        and existing.content_markdown == row["content_markdown"]
        and existing.metadata_json == row["metadata"]
        and existing.evidence_block_ids == row["evidence_block_ids"]
        and existing.content_origin == row["content_origin"]
        and existing.review_status == row["review_status"]
        and existing.compile_provenance == row["compile_provenance"]
    )


async def _activate_semantic_compile_revision(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    document: Document,
    compile_attestation: dict[str, Any],
) -> None:
    target = await session.scalar(
        select(DocumentSemanticClassification).where(
            DocumentSemanticClassification.tenant_id == job.tenant_id,
            DocumentSemanticClassification.document_id == document.id,
            DocumentSemanticClassification.document_version == document.active_version,
            DocumentSemanticClassification.compile_input_sha256
            == compile_attestation["compile_input_sha256"],
            DocumentSemanticClassification.schema_sha256
            == compile_attestation["pipeline_schema_sha256"],
            DocumentSemanticClassification.model_revision == compile_attestation["model_revision"],
        )
    )
    if target is None:
        raise ProviderUnavailable("DURABLE_QWEN_SEMANTIC_CLASSIFICATION_REVISION_MISSING")
    await session.execute(
        update(DocumentSemanticClassification)
        .where(
            DocumentSemanticClassification.tenant_id == job.tenant_id,
            DocumentSemanticClassification.document_id == document.id,
            DocumentSemanticClassification.document_version == document.active_version,
            DocumentSemanticClassification.id != target.id,
            DocumentSemanticClassification.is_active.is_(True),
        )
        .values(is_active=False)
    )
    target.is_active = True
    await _flush_active_knowledge_revisions(session)


async def _complete_compile_knowledge(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    document: Document,
    pages: list[Page],
    reserved: Decimal,
    attempt: int,
    provider_name: str,
    compiled: list[CompiledNote] | None = None,
    bundle: KnowledgeBundle | None = None,
) -> None:
    if (compiled is None) == (bundle is None):
        raise RuntimeError("exactly_one_knowledge_result_required")
    document = await _lock_document_compile_revision(
        session,
        job=job,
        document_id=document.id,
        document_version=document.active_version,
    )
    fenced_job = await _active_compile_job(
        session,
        job_id=job.id,
        tenant_id=job.tenant_id,
        lock_target=True,
    )
    if fenced_job is None:
        raise JobCancellationFence
    job = fenced_job
    compile_attestation: dict[str, Any] | None = None
    if bundle is not None:
        compile_attestation = await _knowledge_compile_attestation(
            session=session,
            job=job,
        )
        await _activate_semantic_compile_revision(
            session=session,
            job=job,
            document=document,
            compile_attestation=compile_attestation,
        )
    if compiled is not None:
        if not compiled or any(not note.evidence_block_ids for note in compiled):
            raise RuntimeError("evidence_required")
        note_rows: list[dict[str, Any]] = [
            {
                "stable_key": note.stable_key,
                "title": note.title,
                "note_type": "document",
                "content_markdown": note.markdown,
                "evidence_block_ids": list(note.evidence_block_ids),
                "content_origin": note.content_origin,
                "review_status": "unreviewed",
                "metadata": {"provider": provider_name},
                "compile_provenance": {},
            }
            for note in compiled
        ]
    else:
        assert bundle is not None
        assert compile_attestation is not None
        note_rows = [
            {
                "stable_key": _project_note_key(document.id, note.note_id),
                "title": note.title,
                "note_type": note.note_type.value,
                "content_markdown": _knowledge_note_markdown(note),
                "evidence_block_ids": list(note.evidence_block_ids),
                "content_origin": note.content_origin.value,
                "review_status": note.review_status.value,
                "metadata": {
                    "provider": provider_name,
                    "document_id": bundle.document_id,
                    "bundle_note": note.model_dump(
                        mode="json",
                        by_alias=True,
                        exclude_none=True,
                    ),
                    "bundle_conflicts": [
                        conflict.model_dump(mode="json", by_alias=True)
                        for conflict in bundle.conflicts
                    ],
                    "compile_attestation": compile_attestation,
                },
                "compile_provenance": compile_attestation,
            }
            for note in bundle.notes
        ]
        await session.execute(
            update(KnowledgeNote)
            .where(
                KnowledgeNote.tenant_id == job.tenant_id,
                KnowledgeNote.project_id == job.project_id,
                KnowledgeNote.document_id == document.id,
                KnowledgeNote.document_version == document.active_version,
                KnowledgeNote.is_active.is_(True),
            )
            .values(is_active=False)
        )
    for row in note_rows:
        identity: tuple[Any, ...]
        if compile_attestation is None:
            identity = (
                KnowledgeNote.tenant_id == job.tenant_id,
                KnowledgeNote.project_id == job.project_id,
                KnowledgeNote.stable_key == row["stable_key"],
            )
        else:
            identity = (
                KnowledgeNote.tenant_id == job.tenant_id,
                KnowledgeNote.project_id == job.project_id,
                KnowledgeNote.stable_key == row["stable_key"],
                KnowledgeNote.document_id == document.id,
                KnowledgeNote.document_version == document.active_version,
                KnowledgeNote.compile_input_sha256 == compile_attestation["compile_input_sha256"],
                KnowledgeNote.pipeline_schema_sha256
                == compile_attestation["pipeline_schema_sha256"],
                KnowledgeNote.model_revision == compile_attestation["model_revision"],
            )
        existing = await session.scalar(select(KnowledgeNote).where(*identity))
        created = existing is None
        if existing is None:
            existing = KnowledgeNote(
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                document_id=document.id,
                document_version=document.active_version,
                stable_key=str(row["stable_key"]),
                title=str(row["title"]),
                note_type=str(row["note_type"]),
                content_markdown=str(row["content_markdown"]),
                metadata_json=cast(dict[str, Any], row["metadata"]),
                evidence_block_ids=cast(list[str], row["evidence_block_ids"]),
                content_origin=str(row["content_origin"]),
                review_status=str(row["review_status"]),
                compile_input_sha256=(
                    compile_attestation["compile_input_sha256"]
                    if compile_attestation is not None
                    else None
                ),
                pipeline_schema_sha256=(
                    compile_attestation["pipeline_schema_sha256"]
                    if compile_attestation is not None
                    else None
                ),
                model_revision=(
                    compile_attestation["model_revision"]
                    if compile_attestation is not None
                    else None
                ),
                compile_provenance=cast(
                    dict[str, Any],
                    row["compile_provenance"],
                ),
                is_active=True,
            )
            session.add(existing)
            await _flush_active_knowledge_revisions(session)
        elif compile_attestation is not None:
            if not _knowledge_note_revision_matches(existing, row):
                raise ProviderUnavailable("DURABLE_QWEN_STALE_NOTE_REVISION_CONFLICT")
            existing.is_active = True
        if created:
            await emit_event(
                session,
                job=job,
                event_type="document.knowledge.note_created.v1",
                payload={
                    "note_id": str(existing.id),
                    "stable_key": existing.stable_key,
                    "evidence_block_ids": existing.evidence_block_ids,
                },
            )
    await _flush_active_knowledge_revisions(session)
    if bundle is not None:
        assert compile_attestation is not None
        await session.execute(
            update(Relation)
            .where(
                Relation.tenant_id == job.tenant_id,
                Relation.project_id == job.project_id,
                Relation.document_id == document.id,
                Relation.document_version == document.active_version,
                Relation.is_active.is_(True),
            )
            .values(is_active=False)
        )
        for relation in bundle.relations:
            relation_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                (
                    f"akc:relation:{job.tenant_id}:{job.project_id}:{document.id}:"
                    f"{document.active_version}:{compile_attestation['compile_input_sha256']}:"
                    f"{compile_attestation['pipeline_schema_sha256']}:"
                    f"{compile_attestation['model_revision']}:{relation.id}"
                ),
            )
            existing_relation = await session.scalar(
                select(Relation).where(
                    Relation.tenant_id == job.tenant_id,
                    Relation.project_id == job.project_id,
                    Relation.document_id == document.id,
                    Relation.document_version == document.active_version,
                    Relation.source_relation_key == relation.id,
                    Relation.compile_input_sha256 == compile_attestation["compile_input_sha256"],
                    Relation.pipeline_schema_sha256
                    == compile_attestation["pipeline_schema_sha256"],
                    Relation.model_revision == compile_attestation["model_revision"],
                )
            )
            if existing_relation is None:
                session.add(
                    Relation(
                        id=relation_id,
                        tenant_id=job.tenant_id,
                        project_id=job.project_id,
                        document_id=document.id,
                        document_version=document.active_version,
                        source_relation_key=relation.id,
                        subject_id=relation.subject,
                        predicate=relation.predicate,
                        object_id=relation.object,
                        assertion_status=relation.assertion_status.value,
                        confidence=relation.confidence,
                        evidence_block_ids=list(relation.evidence_block_ids),
                        review_status=relation.review_status.value,
                        compile_input_sha256=compile_attestation["compile_input_sha256"],
                        pipeline_schema_sha256=compile_attestation["pipeline_schema_sha256"],
                        model_revision=compile_attestation["model_revision"],
                        compile_provenance=compile_attestation,
                        is_active=True,
                    )
                )
            elif (
                existing_relation.id != relation_id
                or existing_relation.subject_id != relation.subject
                or existing_relation.predicate != relation.predicate
                or existing_relation.object_id != relation.object
                or existing_relation.assertion_status != relation.assertion_status.value
                or existing_relation.confidence != relation.confidence
                or existing_relation.evidence_block_ids != list(relation.evidence_block_ids)
                or existing_relation.review_status != relation.review_status.value
                or existing_relation.compile_provenance != compile_attestation
            ):
                raise ProviderUnavailable("DURABLE_QWEN_STALE_RELATION_REVISION_CONFLICT")
            else:
                existing_relation.is_active = True
        await _flush_active_knowledge_revisions(session)
    await emit_event(
        session,
        job=job,
        event_type="job.stage.completed.v1",
        payload={"stage": "knowledge", "done": 1, "total": 1},
    )
    await emit_event(
        session,
        job=job,
        event_type="document.validation.completed.v1",
        payload={
            "document_id": str(document.id),
            "schema_valid": True,
            "provenance_complete": True,
        },
    )
    expected = Decimal(str(job.cost_estimate.get("expected", reserved)))
    consumed = min(reserved, expected)
    await credit_entry(
        session,
        tenant_id=job.tenant_id,
        operation_key=f"job:{job.id}:attempt:{attempt}:consume",
        entry_type="consume",
        credits=consumed,
        job_id=job.id,
    )
    await emit_event(
        session,
        job=job,
        event_type="credit.consumed.v1",
        payload={"credits": str(consumed)},
    )
    release = reserved - consumed
    if release > 0:
        await credit_entry(
            session,
            tenant_id=job.tenant_id,
            operation_key=f"job:{job.id}:attempt:{attempt}:release",
            entry_type="release",
            credits=release,
            job_id=job.id,
        )
        await emit_event(
            session,
            job=job,
            event_type="credit.released.v1",
            payload={"credits": str(release)},
        )
    job.status = "completed"
    job.completed_at = utcnow()
    job.progress = {"done": max(1, len(pages)), "total": max(1, len(pages))}
    job.cost_actual = {
        "credits": str(consumed),
        "provider": provider_name,
        "released": str(release),
    }
    await emit_event(
        session,
        job=job,
        event_type="job.completed.v1",
        payload={"status": "completed", "credits": str(consumed)},
    )
    session.add(
        OutboxEvent(
            tenant_id=job.tenant_id,
            aggregate_type="job",
            aggregate_id=job.id,
            event_type="job.completed.v1",
            payload={"job_id": str(job.id)},
        )
    )
    after_commit_metric(session, record_job_terminal, "completed")
    await session.commit()


def _persisted_router_metrics(page: Page) -> PageMetrics:
    persisted = page.preflight_metrics.get("router_metrics")
    if isinstance(persisted, dict):
        try:
            return PageMetrics.model_validate(persisted)
        except (TypeError, ValueError):
            pass

    def ratio(key: str, default: float) -> float:
        try:
            value = float(page.preflight_metrics.get(key, default))
        except (TypeError, ValueError):
            value = default
        return min(1.0, max(0.0, value))

    scripts = page.preflight_metrics.get("script_distribution", {})
    if not isinstance(scripts, dict):
        scripts = {}
    try:
        normalized_scripts = {str(key): float(value) for key, value in scripts.items()}
        if normalized_scripts:
            total = sum(normalized_scripts.values())
            normalized_scripts = (
                {key: max(0.0, value) / total for key, value in normalized_scripts.items()}
                if total > 0
                else {}
            )
    except (TypeError, ValueError):
        normalized_scripts = {}
    return PageMetrics(
        page_index0=page.page_number - 1,
        width=max(1, round(page.width_pt or 1000)),
        height=max(1, round(page.height_pt or 1000)),
        native_text_chars=max(
            0,
            int(page.preflight_metrics.get("native_text_chars", 0)),
        ),
        native_word_count=max(
            0,
            int(page.preflight_metrics.get("native_words", 0)),
        ),
        native_block_count=max(
            0,
            int(page.preflight_metrics.get("native_block_count", 0)),
        ),
        native_text_coverage=ratio("native_text_coverage", 0.0),
        image_coverage=ratio("image_coverage", 0.5),
        invalid_unicode_ratio=ratio("invalid_char_ratio", 0.5),
        replacement_char_ratio=ratio("replacement_char_ratio", 0.5),
        whitespace_anomaly_score=ratio("whitespace_anomaly_score", 0.5),
        native_reading_order_score=ratio("native_reading_order_score", 0.5),
        estimated_columns=max(
            0,
            int(page.preflight_metrics.get("estimated_columns", 0)),
        ),
        table_density=ratio("table_density", 0.0),
        formula_density=ratio("formula_density", 0.0),
        chart_probability=ratio("chart_probability", 0.0),
        handwriting_probability=ratio("handwriting_probability", 0.5),
        rotation_degrees=int(page.rotation or 0),
        skew_degrees=0.0,
        blur_score=ratio("blur_score", 0.5),
        contrast_score=ratio("contrast_score", 0.5),
        small_text_score=ratio("small_text_score", 0.5),
        script_distribution=normalized_scripts,
        suspected_prompt_injection=bool(
            page.preflight_metrics.get("suspected_prompt_injection", False)
        ),
    )


async def _enqueue_visual_page(
    *,
    session: AsyncSession,
    job: ProcessingJob,
    document: Document,
    page: Page,
    page_asset: PageAsset,
    source_sha256: str | None,
    attempt: PageAttempt,
    runtime: RoutingRuntime,
    route: Route,
) -> GpuProviderInvocation:
    try:
        binding = await resolve_pinned_retry_binding(
            session,
            job=job,
            runtime=runtime,
            route=route,
        )
    except IntegrityActionRejected as exc:
        raise ProviderUnavailable(exc.code) from exc
    if route not in runtime.context.ready_routes:
        raise ProviderUnavailable("VISUAL_PROVIDER_NOT_READY")
    try:
        width, height, size_bytes, dpi = _visual_asset_values(page_asset)
    except ValueError as exc:
        raise ProviderUnavailable("VISUAL_PAGE_RASTER_INVALID") from exc
    if (
        source_sha256 is None
        or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
        or page_asset.metadata_json.get("source_sha256") != source_sha256
        or page_asset.metadata_json.get("page_index0") != page.page_number - 1
    ):
        raise ProviderUnavailable("VISUAL_PAGE_RASTER_SCOPE_INVALID")
    preprocessing = page_asset.metadata_json.get("preprocessing")
    preprocessing_transform_sha256 = (
        preprocessing.get("transform_sha256") if isinstance(preprocessing, dict) else None
    )
    if preprocessing is not None and (
        not isinstance(preprocessing_transform_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", preprocessing_transform_sha256)
    ):
        raise ProviderUnavailable("VISUAL_PREPROCESSING_ATTESTATION_INVALID")
    preprocessing_option = (
        {"preprocessing_transform_sha256": (f"sha256:{preprocessing_transform_sha256}")}
        if isinstance(preprocessing_transform_sha256, str)
        else {}
    )
    requested_by: uuid.UUID | None = None
    requested_by_value = job.requested_options.get("requested_by")
    if requested_by_value is not None:
        try:
            requested_by = uuid.UUID(str(requested_by_value))
        except (ValueError, TypeError, AttributeError):
            requested_by = None
    chart_description_enabled = await feature_enabled(
        session,
        tenant_id=job.tenant_id,
        key=CHART_DESCRIPTION_FLAG,
        user_id=requested_by,
        document_type=document.document_type,
    )
    integrity_options: dict[str, Any] = {}
    if job.job_type == "collection_integrity_retry":
        region_bbox = integrity_region_bbox(job)
        if region_bbox is not None:
            integrity_options["bbox1000"] = region_bbox
    transition_policy: GpuTransitionPolicy | None = None
    fallback_route = (
        None
        if job.job_type == "collection_integrity_retry"
        else {
            Route.HPD_FAST: (Route.PADDLE_VL, "parse_balanced_v1"),
            Route.PADDLE_FAST: (Route.PADDLE_VL, "parse_balanced_v1"),
        }.get(route)
    )
    if fallback_route is not None:
        target_route, target_profile = fallback_route
        target_binding = runtime.provider_for(target_route)
        if target_binding is not None and target_route in runtime.context.ready_routes:
            target = GpuTransitionTarget(
                route=target_route.value,
                route_profile=target_profile,
                provider_key=target_binding.model_id,
                endpoint_id=target_binding.endpoint_id,
                model_revision=target_binding.model_revision,
                runtime_image_digest=target_binding.runtime_image_digest,
                adapter_version=target_binding.adapter_version,
                registry_policy_version=target_binding.policy_version,
            )
            transition_policy = GpuTransitionPolicy(
                source_route=route.value,
                source_provider_key=binding.model_id,
                router_policy_version=runtime.context.policy_version,
                invalid_output_fallback=target,
                oom_escalation=target,
            )
    invocation = await enqueue_gpu_invocation(
        session,
        GpuInvocationSpec(
            tenant_id=job.tenant_id,
            job_id=job.id,
            project_id=job.project_id,
            document_id=document.id,
            document_version_id=f"{document.id}:v{document.active_version}",
            page_id=page.id,
            provider_key=binding.model_id,
            endpoint_id=binding.endpoint_id,
            idempotency_key=f"visual-{attempt.id.hex}",
            input_bucket="derived",
            input_object_key=page_asset.storage_key,
            input_sha256=page_asset.sha256,
            output_object_key=(
                f"tenants/{job.tenant_id}/derived/jobs/{job.id}/pages/"
                f"{page.id}/attempt-{attempt.attempt_number}.json"
            ),
            model_revision=binding.model_revision,
            runtime_image_digest=binding.runtime_image_digest,
            adapter_version=binding.adapter_version,
            options={
                "artifact_contract": VISUAL_ARTIFACT_CONTRACT,
                "page_index0": page.page_number - 1,
                "page_range": [page.page_number],
                "page_width_px": width,
                "page_height_px": height,
                "input_size_bytes": size_bytes,
                "page_asset_id": str(page_asset.id),
                "dpi": dpi,
                "colorspace": "RGB",
                "route_profile": attempt.route_profile,
                "quality_profile": runtime.context.risk_tier.value,
                "schema_profile": "canonical-page-1.0",
                "prompt_revision": VISUAL_PROMPT_REVISION,
                "max_output_tokens": 4096,
                "table_recognition": True,
                "formula_recognition": True,
                "chart_recognition": chart_description_enabled,
                # The immutable CPU inference raster already binds orientation,
                # deskew, crop, and contrast decisions. Enabling a second
                # undocumented geometric transform would invalidate source
                # coordinates, so the exact Paddle switches are bound off.
                "orientation_classify": False,
                "unwarp": False,
                "ocr_image_blocks": True,
                **integrity_options,
                **preprocessing_option,
            },
            max_attempts=attempt.max_attempts,
            transition_policy=transition_policy,
        ),
    )
    await attach_provider_invocation(
        session,
        attempt,
        invocation_id=invocation.id,
    )
    job.progress = {
        "stage": "visual_waiting",
        "state": "WAITING_PROVIDER",
        "done": 0,
        "total": 1,
        "page_id": str(page.id),
        "page_attempt_id": str(attempt.id),
        "page_attempt_number": attempt.attempt_number,
        "invocation_id": str(invocation.id),
    }
    await emit_event(
        session,
        job=job,
        event_type="page.processing.started.v1",
        payload={
            "page_id": str(page.id),
            "status": "ocr_queued",
            "route": route.value,
            "attempt_id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "invocation_id": str(invocation.id),
        },
    )
    await emit_event(
        session,
        job=job,
        event_type="job.stage.progress.v1",
        payload={
            "stage": "parse",
            "state": "WAITING_PROVIDER",
            "done": 0,
            "total": 1,
            "page_id": str(page.id),
            "attempt_id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "invocation_id": str(invocation.id),
        },
    )
    return invocation


def _visual_asset_values(page_asset: PageAsset) -> tuple[int, int, int, int]:
    metadata = page_asset.metadata_json if isinstance(page_asset.metadata_json, dict) else {}
    width = metadata.get("width")
    height = metadata.get("height")
    size_bytes = metadata.get("size_bytes")
    dpi = metadata.get("dpi")
    if (
        page_asset.asset_type != "inference_raster"
        or metadata.get("content_type") != "image/png"
        or metadata.get("colorspace") != "RGB"
        or not isinstance(dpi, int)
        or isinstance(dpi, bool)
        or not (180 <= dpi <= 220 or 250 <= dpi <= 300)
        or not isinstance(width, int)
        or isinstance(width, bool)
        or not 1 <= width <= VISUAL_RASTER_MAX_DIMENSION
        or not isinstance(height, int)
        or isinstance(height, bool)
        or not 1 <= height <= VISUAL_RASTER_MAX_DIMENSION
        or width * height > VISUAL_RASTER_MAX_PIXELS
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or not 1 <= size_bytes <= VISUAL_RASTER_MAX_BYTES
    ):
        raise ValueError("VISUAL_PAGE_RASTER_INVALID")
    return width, height, size_bytes, dpi


def _select_inference_raster(
    assets: Sequence[PageAsset],
    *,
    page: Page,
    route: Route,
    mode: ProcessingMode,
) -> PageAsset | None:
    router_metrics = _persisted_router_metrics(page)
    precision = (
        route == Route.PADDLE_VL
        or mode == ProcessingMode.PRECISION
        or router_metrics.small_text_score >= 0.60
        or router_metrics.table_density >= 0.20
    )
    candidates: list[tuple[int, PageAsset]] = []
    for asset in assets:
        try:
            _width, _height, _size_bytes, dpi = _visual_asset_values(asset)
        except ValueError:
            continue
        if (precision and 250 <= dpi <= 300) or (not precision and 180 <= dpi <= 220):
            candidates.append((dpi, asset))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            -item[0] if precision else item[0],
            -item[1].created_at.timestamp(),
            str(item[1].id),
        )
    )
    return candidates[0][1]


async def _validated_visual_output(
    *,
    object_store: ObjectStore,
    job: ProcessingJob,
    document: Document,
    page: Page,
    page_asset: PageAsset,
    source: SourceFile,
    invocation: GpuProviderInvocation,
) -> VisualPageResult:
    width, height, size_bytes, dpi = _visual_asset_values(page_asset)
    metadata = page_asset.metadata_json
    if (
        metadata.get("source_sha256") != source.sha256
        or metadata.get("page_index0") != page.page_number - 1
    ):
        raise ValueError("VISUAL_PAGE_SOURCE_ATTESTATION_MISMATCH")
    if (
        invocation.status != "completed"
        or invocation.page_id != page.id
        or invocation.job_id != job.id
        or invocation.document_id != document.id
        or invocation.document_version_id != f"{document.id}:v{document.active_version}"
        or invocation.input_bucket != "derived"
        or invocation.input_object_key != page_asset.storage_key
        or invocation.input_sha256 != page_asset.sha256
        or invocation.options.get("artifact_contract") != VISUAL_ARTIFACT_CONTRACT
        or invocation.options.get("page_index0") != page.page_number - 1
        or invocation.options.get("page_width_px") != width
        or invocation.options.get("page_height_px") != height
        or invocation.options.get("input_size_bytes") != size_bytes
        or invocation.options.get("page_asset_id") != str(page_asset.id)
        or invocation.options.get("dpi") != dpi
        or invocation.options.get("colorspace") != "RGB"
    ):
        raise ValueError("VISUAL_INVOCATION_SCOPE_MISMATCH")
    manifest = invocation.result_manifest
    manifest_sha = invocation.result_manifest_sha256
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest_sha, str)
        or len(manifest_sha) != 64
        or hashlib.sha256(
            json.dumps(
                manifest,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        != manifest_sha
    ):
        raise ValueError("VISUAL_RESULT_MANIFEST_INVALID")
    expected_manifest = {
        "schema_version": "1.0",
        "invocation_id": str(invocation.id),
        "job_id": str(job.id),
        "tenant_id": str(job.tenant_id),
        "provider": "runpod",
        "endpoint_id": invocation.endpoint_id,
        "provider_key": invocation.provider_key,
        "model_revision": invocation.model_revision,
        "runtime_image_digest": invocation.runtime_image_digest,
        "adapter_version": invocation.adapter_version,
        "output_object_key": invocation.output_object_key,
    }
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise ValueError("VISUAL_RESULT_MANIFEST_SCOPE_MISMATCH")
    output_sha = manifest.get("output_sha256")
    output_bytes = manifest.get("output_bytes")
    if (
        not isinstance(output_sha, str)
        or not re.fullmatch(
            r"[0-9a-f]{64}",
            output_sha.removeprefix("sha256:"),
        )
        or not isinstance(output_bytes, int)
        or isinstance(output_bytes, bool)
        or not 1 <= output_bytes <= 64 * 1024 * 1024
    ):
        raise ValueError("VISUAL_RESULT_MANIFEST_INVALID")
    input_body, output_body = await asyncio.gather(
        object_store.read_derived(page_asset.storage_key),
        object_store.read_derived(invocation.output_object_key),
    )
    if len(input_body) != size_bytes or hashlib.sha256(input_body).hexdigest() != page_asset.sha256:
        raise ValueError("VISUAL_PAGE_RASTER_CHECKSUM_MISMATCH")
    if len(output_body) != output_bytes or hashlib.sha256(
        output_body
    ).hexdigest() != output_sha.removeprefix("sha256:"):
        raise ValueError("VISUAL_RESULT_OBJECT_CHECKSUM_MISMATCH")
    try:
        output_payload = json.loads(output_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("VISUAL_RESULT_OBJECT_INVALID") from exc
    if not isinstance(output_payload, dict):
        raise ValueError("VISUAL_RESULT_OBJECT_INVALID")
    result = validate_visual_result(
        output_payload=output_payload,
        expected_job_id=job.id,
        expected_tenant_id=job.tenant_id,
        expected_document_id=document.id,
        expected_document_version_id=invocation.document_version_id,
        expected_page_index0=page.page_number - 1,
        expected_provider=invocation.provider_key,
        expected_model_revision=invocation.model_revision,
        expected_runtime_image_digest=invocation.runtime_image_digest,
        expected_adapter_version=invocation.adapter_version,
        expected_input_sha256=invocation.input_sha256,
        expected_input_bytes=size_bytes,
        expected_idempotency_key=invocation.idempotency_key,
        expected_image_asset_id=page_asset.id,
    )
    expected_visual_attestation = visual_attestation(
        result,
        page_id=page.id,
        page_index0=page.page_number - 1,
        page_width_px=width,
        page_height_px=height,
        input_size_bytes=size_bytes,
    )
    if manifest.get("visual_attestation") != expected_visual_attestation:
        raise ValueError("VISUAL_RESULT_ATTESTATION_MISMATCH")
    if (
        manifest.get("result_id") != result.result_id
        or manifest.get("metrics") != result.metrics
        or manifest.get("warning_count") != len(result.warnings)
        or manifest.get("warning_sha256")
        != [hashlib.sha256(warning.encode()).hexdigest() for warning in result.warnings]
    ):
        raise ValueError("VISUAL_RESULT_MANIFEST_EVIDENCE_MISMATCH")
    return result


def _visual_markdown(block: VisualBlock) -> str:
    return _visual_markdown_from_text(block, visual_block_text(block))


def _visual_markdown_from_text(block: VisualBlock, text: str) -> str:
    text_value = text.strip()
    if block.type == "title":
        return f"# {text_value}" if text_value else ""
    if block.type == "heading":
        return f"## {text_value}" if text_value else ""
    if isinstance(block, VisualFormulaBlock):
        return f"$$\n{text_value}\n$$" if text_value else ""
    if block.type == "code":
        return f"```\n{text_value}\n```" if text_value else ""
    return text_value


def _visual_quality_block(block: VisualBlock) -> PageQualityBlock:
    source_ref = block.source_refs[0]
    return PageQualityBlock(
        block_id=block.block_id,
        block_type=block.type,
        # OCR has no independent source transcript. Confidence and verifier
        # evidence below are the accuracy gate; comparing text to itself would
        # fabricate perfect fidelity.
        source_text="",
        candidate_text=_visual_markdown(block),
        bbox1000=source_ref.bbox1000,
        has_provenance=True,
        table=(block.table if isinstance(block, VisualTableBlock) else None),
        confidence=block.confidence,
        token_confidences=block.token_confidences,
    )


def _visual_sensitive_summary(
    result: VisualPageResult,
) -> tuple[dict[str, Any], dict[str, Any]]:
    diagnostics = json.dumps(
        {
            "warnings": result.warnings,
            "quality_flags": [block.quality_flags for block in result.blocks],
            "provider_metrics": result.provider_metrics,
            "metrics": result.metrics,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    text = "\n\n".join([*(visual_block_text(block) for block in result.blocks), diagnostics])
    if len(text) > 1_100_000:
        raise ValueError("VISUAL_SECURITY_SCAN_BOUND_EXCEEDED")
    sensitive = detect_sensitive_data(text)
    counts: dict[str, int] = {}
    for finding in sensitive.findings:
        counts[finding.kind.value] = counts.get(finding.kind.value, 0) + 1
    injection = detect_prompt_injection(text, max_scan_characters=1_100_000)
    return (
        {
            "has_pii": sensitive.has_pii,
            "has_secret": sensitive.has_secret,
            "counts": counts,
        },
        {
            "suspected": injection.suspected,
            "risk": injection.risk.value,
            # Never persist signal excerpts: they can contain secret-bearing
            # source text. Rule identifiers are sufficient for review routing.
            "rule_ids": sorted({signal.rule_id for signal in injection.signals}),
        },
    )


def _canonical_visual_source_ref(source_ref: Any) -> dict[str, Any]:
    return {
        "documentId": source_ref.document_id,
        "documentVersionId": source_ref.document_version_id,
        "pageIndex0": source_ref.page_index0,
        "pageNumber1": source_ref.page_number1,
        "bbox1000": list(source_ref.bbox1000),
    }


def _normalization_source_ref_id(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "src_" + hashlib.sha256(encoded).hexdigest()[:32]


def _normalization_bbox(value: list[int] | None) -> tuple[int, int, int, int] | None:
    if (
        value is None
        or len(value) != 4
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        return None
    return value[0], value[1], value[2], value[3]


def _block_excluded_from_body(block: Block) -> bool:
    structured = block.structured_content
    if not isinstance(structured, dict):
        return False
    normalization = structured.get("normalization")
    if not isinstance(normalization, dict):
        return False
    annotation = normalization.get("repeatedMarginal")
    return isinstance(annotation, dict) and annotation.get("excludedFromBody") is True


async def _annotate_document_normalization(
    session: AsyncSession,
    *,
    document: Document,
) -> None:
    """Persist document-level normalization evidence without deleting blocks."""

    records = list(
        (
            await session.execute(
                select(Block, Page.page_number)
                .join(
                    Page,
                    (Page.tenant_id == Block.tenant_id) & (Page.id == Block.page_id),
                )
                .where(
                    Block.tenant_id == document.tenant_id,
                    Block.document_id == document.id,
                )
                .order_by(Page.page_number, Block.block_order, Block.id)
            )
        ).all()
    )
    rows: dict[str, Block] = {}
    views: list[NormalizationBlock] = []
    source_payloads: dict[str, tuple[dict[str, Any], ...]] = {}
    for block, page_number in records:
        structured = dict(block.structured_content or {})
        raw_source_refs = structured.get("sourceRefs")
        source_refs = (
            tuple(item for item in raw_source_refs if isinstance(item, dict))
            if isinstance(raw_source_refs, list)
            else ()
        )
        if not source_refs:
            source_refs = (
                {
                    "documentId": str(document.id),
                    "documentVersionId": f"{document.id}:v{document.active_version}",
                    "pageIndex0": page_number - 1,
                    "pageNumber1": page_number,
                    "bbox1000": block.bbox1000,
                },
            )
            structured["sourceRefs"] = list(source_refs)
            block.structured_content = structured
        identity = str(block.id)
        rows[identity] = block
        source_payloads[identity] = source_refs
        views.append(
            NormalizationBlock(
                block_id=identity,
                page_number=page_number,
                order=block.block_order,
                block_type=block.block_type,
                raw_text=block.source_text or "",
                normalized_text=block.normalized_text or "",
                bbox1000=_normalization_bbox(block.bbox1000),
                source_ref_ids=tuple(
                    _normalization_source_ref_id(source_ref) for source_ref in source_refs
                ),
                provider_order=(
                    int(structured["providerOrder"])
                    if isinstance(structured.get("providerOrder"), int)
                    else None
                ),
                provider_label=(
                    str(structured["providerLabel"])
                    if isinstance(structured.get("providerLabel"), str)
                    else None
                ),
                font_size_pt=(
                    float(structured["fontSizePt"])
                    if isinstance(structured.get("fontSizePt"), (int, float))
                    else None
                ),
                font_weight=(
                    int(structured["fontWeight"])
                    if isinstance(structured.get("fontWeight"), int)
                    else None
                ),
                whitespace_before=(
                    float(structured["whitespaceBefore"])
                    if isinstance(structured.get("whitespaceBefore"), (int, float))
                    else None
                ),
                whitespace_after=(
                    float(structured["whitespaceAfter"])
                    if isinstance(structured.get("whitespaceAfter"), (int, float))
                    else None
                ),
                explicit_heading_level=(
                    int(structured["headingLevel"])
                    if isinstance(structured.get("headingLevel"), int)
                    else None
                ),
                is_toc_entry=structured.get("isTocEntry") is True,
                toc_level=(
                    int(structured["tocLevel"])
                    if isinstance(structured.get("tocLevel"), int)
                    else None
                ),
                markdown=block.markdown,
            )
        )

    reading_order, heading_hierarchy = analyze_document_structure(views)
    heading_by_id = {record.block_id: record for record in heading_hierarchy.records}
    for record in reading_order.records:
        row = rows[record.block_id]
        structured = dict(row.structured_content or {})
        normalization = dict(structured.get("normalization") or {})
        normalization["readingOrder"] = record.payload()
        heading = heading_by_id[record.block_id]
        normalization["headingInference"] = heading.payload()
        structured["normalization"] = normalization
        row.structured_content = structured
        row.warnings = sorted(
            {
                *row.warnings,
                *record.quality_flags,
                *heading.warnings,
            }
        )
        if heading.is_heading:
            row.block_type = heading.inferred_type
            if heading.parent_id is not None:
                row.parent_block_id = uuid.UUID(heading.parent_id)

    marginal_annotations = detect_repeated_marginal_blocks(
        views,
        total_pages=document.page_count,
    )
    marginal_block_ids = {annotation.block_id for annotation in marginal_annotations}
    for annotation in marginal_annotations:
        row = rows[annotation.block_id]
        structured = dict(row.structured_content or {})
        normalization = dict(structured.get("normalization") or {})
        normalization["repeatedMarginal"] = annotation.payload()
        structured["normalization"] = normalization
        row.structured_content = structured
        row.block_type = annotation.classified_type
        row.warnings = sorted(
            {
                *row.warnings,
                f"repeated_{annotation.classified_type}_detected",
            }
        )

    continuity_views = [view for view in views if view.block_id not in marginal_block_ids]
    for restoration in restore_cross_page_continuity(continuity_views):
        combined_refs: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for block_id in restoration.block_ids:
            for source_ref in source_payloads.get(block_id, ()):
                source_id = _normalization_source_ref_id(source_ref)
                if source_id not in seen_refs:
                    combined_refs.append(source_ref)
                    seen_refs.add(source_id)
        if len(combined_refs) < 2:
            continue
        payload = restoration.payload() | {"sourceRefs": combined_refs}
        for block_id in restoration.block_ids:
            row = rows[block_id]
            structured = dict(row.structured_content or {})
            normalization = dict(structured.get("normalization") or {})
            current = normalization.get("crossPageRestorations")
            cross_page = list(current) if isinstance(current, list) else []
            if payload not in cross_page:
                cross_page.append(payload)
            normalization["crossPageRestorations"] = cross_page
            structured["normalization"] = normalization
            row.structured_content = structured
            row.warnings = sorted({*row.warnings, *restoration.quality_flags})
    await session.flush()


def _bbox_intersects(left: object, right: list[int]) -> bool:
    if (
        not isinstance(left, (list, tuple))
        or len(left) != 4
        or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in left)
    ):
        return False
    x0, y0, x1, y1 = (float(value) for value in left)
    return x0 < right[2] and x1 > right[0] and y0 < right[3] and y1 > right[1]


async def _promote_visual_blocks(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    document: Document,
    page: Page,
    page_asset: PageAsset,
    page_attempt: PageAttempt,
    invocation: GpuProviderInvocation,
    result: VisualPageResult,
) -> list[Block]:
    # A visual result remains an in-memory candidate until the quality gate
    # accepts it. A region-scoped integrity recovery replaces only intersecting
    # machine output; ordinary page execution retains the full-page behavior.
    region_bbox = integrity_region_bbox(job)
    visual_blocks = list(result.blocks)
    if region_bbox is None:
        await session.execute(
            delete(Block).where(
                Block.tenant_id == job.tenant_id,
                Block.document_id == document.id,
                Block.page_id == page.id,
                Block.user_locked.is_(False),
            )
        )
    else:
        visual_blocks = [
            block
            for block in visual_blocks
            if any(_bbox_intersects(ref.bbox1000, region_bbox) for ref in block.source_refs)
        ]
        if not visual_blocks:
            raise ValueError("INTEGRITY_RETRY_REGION_EMPTY")
        prior_machine_blocks = list(
            await session.scalars(
                select(Block).where(
                    Block.tenant_id == job.tenant_id,
                    Block.document_id == document.id,
                    Block.page_id == page.id,
                    Block.user_locked.is_(False),
                )
            )
        )
        replace_ids = tuple(
            block.id
            for block in prior_machine_blocks
            if _bbox_intersects(block.bbox1000, region_bbox)
        )
        if replace_ids:
            await session.execute(delete(Block).where(Block.id.in_(replace_ids)))
    await session.flush()
    manifest = invocation.result_manifest
    if (
        not isinstance(manifest, dict)
        or invocation.started_at is None
        or invocation.completed_at is None
        or not isinstance(invocation.options.get("prompt_revision"), str)
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(invocation.options.get("prompt_revision")),
        )
        or not isinstance(manifest.get("output_sha256"), str)
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(manifest.get("output_sha256")),
        )
        or invocation.result_manifest_sha256 is None
    ):
        raise ValueError("VISUAL_MODEL_RUN_ATTESTATION_INCOMPLETE")
    model_run = {
        "id": str(invocation.id),
        "provider": invocation.provider,
        "model": invocation.provider_key,
        "revision": invocation.model_revision,
        "runtime": "serverless_gpu",
        "runtimeVersion": invocation.adapter_version,
        "adapterVersion": invocation.adapter_version,
        "promptSha256": invocation.options["prompt_revision"],
        "hardware": "gpu",
        "containerDigest": invocation.runtime_image_digest,
        "routeProfile": page_attempt.route_profile,
        "startedAt": (
            invocation.started_at
            if invocation.started_at.tzinfo is not None
            else invocation.started_at.replace(tzinfo=UTC)
        ).isoformat(),
        "completedAt": (
            invocation.completed_at
            if invocation.completed_at.tzinfo is not None
            else invocation.completed_at.replace(tzinfo=UTC)
        ).isoformat(),
        "artifactContract": invocation.options["artifact_contract"],
        "schemaProfile": invocation.options["schema_profile"],
        "requestManifestSha256": f"sha256:{invocation.request_manifest_sha256}",
        "resultManifestSha256": f"sha256:{invocation.result_manifest_sha256}",
        "inputSha256": f"sha256:{invocation.input_sha256}",
        "outputSha256": manifest["output_sha256"],
    }
    next_order = (
        int(
            await session.scalar(
                select(func.max(Block.block_order)).where(
                    Block.tenant_id == job.tenant_id,
                    Block.document_id == document.id,
                )
            )
            or -1
        )
        + 1
    )
    persisted: list[Block] = []
    for index, visual_block in enumerate(visual_blocks):
        block_id = uuid.uuid5(invocation.id, visual_block.block_id)
        text_value = visual_block_text(visual_block)
        normalized = normalize_block_text(
            text_value,
            block_type=visual_block.type,
        )
        content_hash = hashlib.sha256(text_value.encode()).hexdigest()
        source_refs = [
            _canonical_visual_source_ref(source_ref) for source_ref in visual_block.source_refs
        ]
        structured_content: dict[str, Any] = {
            "schemaVersion": "akc-visual-block-1.0",
            "contentLayer": "structured",
            "providerBlockId": visual_block.block_id,
            "pageAttemptId": str(page_attempt.id),
            "providerInvocationId": str(invocation.id),
            "modelRunIds": [str(invocation.id)],
            "modelRun": model_run,
            "sourceRefs": source_refs,
            "normalization": normalized.payload(),
        }
        if isinstance(visual_block, VisualTableBlock):
            structured_content["table"] = visual_block.table.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
        elif isinstance(visual_block, VisualFormulaBlock):
            structured_content["formulaLatex"] = visual_block.formula_latex
        elif isinstance(visual_block, VisualFigureBlock):
            if visual_block.image_asset_id is not None:
                structured_content["imageAssetId"] = visual_block.image_asset_id
            else:
                structured_content["imageRef"] = {
                    "pageAssetId": str(page_asset.id),
                    "assetType": page_asset.asset_type,
                    "cropProvenance": visual_block.crop_provenance,
                    "bbox1000": list(visual_block.source_refs[0].bbox1000),
                }
        row = Block(
            id=block_id,
            tenant_id=job.tenant_id,
            document_id=document.id,
            page_id=page.id,
            block_order=next_order + index,
            block_type=visual_block.type,
            origin=visual_block.origin,
            bbox1000=list(visual_block.source_refs[0].bbox1000),
            source_text=text_value,
            normalized_text=normalized.normalized_text,
            markdown=_visual_markdown_from_text(
                visual_block,
                normalized.normalized_text,
            ),
            structured_content=structured_content,
            engine=invocation.provider_key,
            engine_revision=invocation.model_revision,
            confidence=visual_block.confidence,
            content_hash=content_hash,
            warnings=sorted(
                {
                    *visual_block.quality_flags,
                    *normalized.quality_flags,
                }
            ),
            revision=1,
        )
        session.add(row)
        persisted.append(row)
    await session.flush()
    if region_bbox is None:
        await _annotate_document_normalization(
            session,
            document=document,
        )
    return persisted


async def _job_page_attempt(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    page_id: uuid.UUID,
) -> PageAttempt | None:
    return cast(
        PageAttempt | None,
        await session.scalar(
            select(PageAttempt)
            .where(
                PageAttempt.tenant_id == job.tenant_id,
                PageAttempt.job_id == job.id,
                PageAttempt.page_id == page_id,
            )
            .order_by(PageAttempt.attempt_number.desc())
            .with_for_update()
        ),
    )


async def _release_compile_reservation(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    reserved: Decimal,
    attempt: int,
    reason: str,
) -> None:
    if reserved <= 0:
        return
    await credit_entry(
        session,
        tenant_id=job.tenant_id,
        operation_key=f"job:{job.id}:attempt:{attempt}:release",
        entry_type="release",
        credits=reserved,
        job_id=job.id,
        metadata={"reason": reason},
    )
    await emit_event(
        session,
        job=job,
        event_type="credit.released.v1",
        payload={"credits": str(reserved), "reason": reason},
    )


async def _fail_expected_compile(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    code: str,
    reserved: Decimal,
    attempt: int,
) -> None:
    job.status = "failed"
    job.completed_at = utcnow()
    job.error = {"code": code, "retryable": False}
    await emit_event(
        session,
        job=job,
        event_type="job.failed.v1",
        payload={"status": "failed", "code": code},
    )
    await _release_compile_reservation(
        session,
        job=job,
        reserved=reserved,
        attempt=attempt,
        reason="job_failed",
    )
    session.add(
        OutboxEvent(
            tenant_id=job.tenant_id,
            aggregate_type="job",
            aggregate_id=job.id,
            event_type="job.failed.v1",
            payload={"job_id": str(job.id), "code": code},
        )
    )
    after_commit_metric(session, record_job_terminal, "failed")
    await session.commit()


async def _isolate_compile_page(
    session: AsyncSession,
    *,
    job: ProcessingJob,
    page: Page,
    page_attempt: PageAttempt,
    reserved: Decimal,
    attempt: int,
    state: PageState,
    code: str,
    category: str,
    message: str,
) -> None:
    if state not in {PageState.UNRESOLVED, PageState.QUARANTINED}:
        raise ValueError("autonomous isolation requires unresolved or quarantined state")
    job.status = "failed"
    job.completed_at = utcnow()
    job.error = {"code": code, "retryable": False}
    page.status = state.value
    job.progress = {
        "stage": "verify",
        "state": state.value,
        "done": 0,
        "total": 1,
        "page_id": str(page.id),
        "page_attempt_id": str(page_attempt.id),
        "page_attempt_number": page_attempt.attempt_number,
    }
    await emit_event(
        session,
        job=job,
        event_type=(
            "page.quarantined.v1" if state == PageState.QUARANTINED else "page.unresolved.v1"
        ),
        payload={
            "page_id": str(page.id),
            "status": state.value.casefold(),
            "severity": "high",
            "category": category,
            "message": message,
            "attempt_id": str(page_attempt.id),
            "attempt_number": page_attempt.attempt_number,
        },
    )
    await emit_event(
        session,
        job=job,
        event_type="job.failed.v1",
        payload={"status": "failed", "code": code, "isolated_state": state.value},
    )
    await _release_compile_reservation(
        session,
        job=job,
        reserved=reserved,
        attempt=attempt,
        reason=state.value.casefold(),
    )
    session.add(
        OutboxEvent(
            tenant_id=job.tenant_id,
            aggregate_type="job",
            aggregate_id=job.id,
            event_type="job.failed.v1",
            payload={"job_id": str(job.id), "code": code, "isolated_state": state.value},
        )
    )
    after_commit_metric(session, record_job_terminal, "failed")
    await session.commit()


async def _run_compile_job_impl(
    *,
    session: AsyncSession,
    job_id: uuid.UUID,
    settings: KnowledgeProviderSettings,
    object_store: ObjectStore | None = None,
) -> None:
    candidate = await _active_compile_job(
        session,
        job_id=job_id,
        lock_target=False,
    )
    if candidate is None or candidate.document_id is None:
        return
    # Lock in the same document -> job order used by source-version replacement.
    # This keeps a queued worker from crossing the atomic active-version switch.
    document = await session.scalar(
        select(Document)
        .where(
            Document.tenant_id == candidate.tenant_id,
            Document.id == candidate.document_id,
        )
        .with_for_update()
    )
    if document is None:
        return
    job = await _active_compile_job(
        session,
        job_id=job_id,
        tenant_id=candidate.tenant_id,
        lock_target=True,
    )
    if job is None:
        return
    reserved = Decimal(str(job.cost_estimate.get("reserved", "0")))
    attempt = int(job.requested_options.get("retry_count", 0))
    raw_document_version = job.requested_options.get(
        "document_version",
        document.active_version,
    )
    try:
        requested_document_version = (
            0 if isinstance(raw_document_version, bool) else int(raw_document_version)
        )
    except (TypeError, ValueError):
        requested_document_version = 0
    if requested_document_version < 1:
        await _fail_expected_compile(
            session,
            job=job,
            code="JOB_DOCUMENT_VERSION_INVALID",
            reserved=reserved,
            attempt=attempt,
        )
        return
    if requested_document_version != document.active_version:
        await _fail_expected_compile(
            session,
            job=job,
            code="STALE_DOCUMENT_VERSION",
            reserved=reserved,
            attempt=attempt,
        )
        return
    resuming_knowledge = (
        isinstance(job.progress, dict) and job.progress.get("stage") == "knowledge_waiting"
    )
    resuming_visual = (
        isinstance(job.progress, dict) and job.progress.get("stage") == "visual_waiting"
    )
    job.status = "running"
    job.started_at = job.started_at or utcnow()
    if not resuming_knowledge and not resuming_visual:
        await emit_event(
            session,
            job=job,
            event_type="job.stage.started.v1",
            payload={"stage": "route"},
        )
    await session.commit()
    provider_called = False
    provider_name = "deterministic"
    unsupported_claim = False
    try:
        source = (
            await session.scalar(
                select(SourceFile).where(
                    SourceFile.tenant_id == job.tenant_id,
                    SourceFile.id == document.source_file_id,
                )
            )
            if document.source_file_id is not None
            else None
        )
        blocks = list(
            (
                await session.scalars(
                    select(Block)
                    .where(
                        Block.tenant_id == job.tenant_id,
                        Block.document_id == document.id,
                    )
                    .order_by(Block.block_order)
                )
            ).all()
        )
        pages = list(
            (
                await session.scalars(
                    select(Page)
                    .where(
                        Page.tenant_id == job.tenant_id,
                        Page.document_id == document.id,
                    )
                    .order_by(Page.page_number)
                )
            ).all()
        )
        requested_page_ids = {
            uuid.UUID(str(value)) for value in job.requested_options.get("page_ids", [])
        }
        if requested_page_ids:
            pages = [page for page in pages if page.id in requested_page_ids]
            if len(pages) != len(requested_page_ids):
                raise RuntimeError("retry_page_missing")
        if resuming_knowledge:
            provider_called = True
            provider = knowledge_provider(
                settings,
                bool(job.requested_options.get("external_processing_consent")),
            )
            if not isinstance(provider, DurableQwenKnowledgeProvider):
                raise ProviderUnavailable("KNOWLEDGE_RESUME_PROVIDER_MISMATCH")
            provider_name = provider.provider_key
            admitted_bundle = await _durable_qwen_bundle(
                session=session,
                job=job,
                document=document,
                blocks=blocks,
                pages=pages,
                provider=provider,
                object_store=object_store,
            )
            if admitted_bundle is None:
                return
            after_commit_metric(
                session,
                record_provider_request,
                provider_name,
                result="success",
            )
            await _complete_compile_knowledge(
                session=session,
                job=job,
                document=document,
                pages=pages,
                reserved=reserved,
                attempt=attempt,
                provider_name=provider_name,
                bundle=admitted_bundle,
            )
            return
        if resuming_visual:
            progress = job.progress if isinstance(job.progress, dict) else {}
            try:
                page_id = uuid.UUID(str(progress["page_id"]))
                page_attempt_id = uuid.UUID(str(progress["page_attempt_id"]))
                invocation_id = uuid.UUID(str(progress["invocation_id"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("VISUAL_RESUME_STATE_INVALID") from exc
            page = next((item for item in pages if item.id == page_id), None)
            if page is not None:
                page = await session.scalar(
                    select(Page)
                    .where(
                        Page.tenant_id == job.tenant_id,
                        Page.id == page.id,
                    )
                    .with_for_update()
                )
            page_attempt = await session.scalar(
                select(PageAttempt)
                .where(
                    PageAttempt.tenant_id == job.tenant_id,
                    PageAttempt.id == page_attempt_id,
                    PageAttempt.page_id == page_id,
                    PageAttempt.job_id == job.id,
                )
                .with_for_update()
            )
            invocation = await session.scalar(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == job.tenant_id,
                    GpuProviderInvocation.id == invocation_id,
                    GpuProviderInvocation.job_id == job.id,
                    GpuProviderInvocation.page_id == page_id,
                )
                .with_for_update()
            )
            try:
                page_asset_id = uuid.UUID(
                    str(invocation.options.get("page_asset_id") if invocation is not None else None)
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError("VISUAL_RESUME_ASSET_ID_INVALID") from exc
            page_asset = await session.scalar(
                select(PageAsset)
                .where(
                    PageAsset.tenant_id == job.tenant_id,
                    PageAsset.id == page_asset_id,
                    PageAsset.page_id == page_id,
                    PageAsset.asset_type == "inference_raster",
                )
                .with_for_update()
            )
            if (
                page is None
                or page_attempt is None
                or invocation is None
                or page_asset is None
                or source is None
            ):
                raise RuntimeError("VISUAL_RESUME_SCOPE_INVALID")
            if page_attempt.provider_invocation_id not in {
                invocation.id,
                invocation.lineage_root_invocation_id,
            }:
                raise RuntimeError("VISUAL_RESUME_INVOCATION_MISMATCH")
            if invocation.status in {"failed", "dead_letter", "cancelled"}:
                if PageState(page_attempt.status) not in {
                    PageState.COMPLETED,
                    PageState.NEEDS_REVIEW,
                    PageState.FAILED,
                }:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.FAILED,
                        reason="visual_provider_terminal_failure",
                        payload={
                            "invocation_id": str(invocation.id),
                            "provider_state": invocation.status,
                            "error_code": invocation.last_error_code,
                        },
                    )
                await emit_event(
                    session,
                    job=job,
                    event_type="page.failed.v1",
                    payload={
                        "page_id": str(page.id),
                        "status": "failed",
                        "code": invocation.last_error_code or "VISUAL_PROVIDER_FAILED",
                        "attempt_id": str(page_attempt.id),
                        "attempt_number": page_attempt.attempt_number,
                        "invocation_id": str(invocation.id),
                    },
                )
                await _fail_expected_compile(
                    session,
                    job=job,
                    code=invocation.last_error_code or "VISUAL_PROVIDER_FAILED",
                    reserved=reserved,
                    attempt=attempt,
                )
                return
            if invocation.status != "completed":
                if (
                    invocation.status in {"submitted", "running"}
                    and PageState(page_attempt.status) == PageState.OCR_QUEUED
                ):
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.OCR_RUNNING,
                        reason="visual_provider_started",
                        payload={
                            "invocation_id": str(invocation.id),
                            "provider_state": invocation.status,
                        },
                    )
                job.progress = {
                    **progress,
                    "stage": "visual_waiting",
                    "state": "WAITING_PROVIDER",
                    "provider_state": invocation.status,
                }
                await emit_event(
                    session,
                    job=job,
                    event_type="job.stage.progress.v1",
                    payload={
                        "stage": "parse",
                        "state": "WAITING_PROVIDER",
                        "provider_state": invocation.status,
                        "page_id": str(page.id),
                        "attempt_id": str(page_attempt.id),
                        "attempt_number": page_attempt.attempt_number,
                        "invocation_id": str(invocation.id),
                    },
                )
                await session.commit()
                return
            if object_store is None:
                raise RuntimeError("VISUAL_RESULT_OBJECT_STORE_REQUIRED")
            terminal_manifest_sha = invocation.result_manifest_sha256
            await session.commit()
            try:
                visual_result = await _validated_visual_output(
                    object_store=object_store,
                    job=job,
                    document=document,
                    page=page,
                    page_asset=page_asset,
                    source=source,
                    invocation=invocation,
                )
            except Exception as exc:
                await session.rollback()
                active_job = await _active_compile_job(
                    session,
                    job_id=job.id,
                    tenant_id=job.tenant_id,
                    lock_target=True,
                )
                if active_job is None:
                    raise JobCancellationFence from exc
                job = active_job
                failed_attempt = await session.scalar(
                    select(PageAttempt)
                    .where(
                        PageAttempt.tenant_id == job.tenant_id,
                        PageAttempt.id == page_attempt_id,
                    )
                    .with_for_update()
                )
                if failed_attempt is not None and PageState(failed_attempt.status) not in {
                    PageState.COMPLETED,
                    PageState.NEEDS_REVIEW,
                    PageState.FAILED,
                }:
                    await transition_page_attempt(
                        session,
                        failed_attempt,
                        PageState.FAILED,
                        reason="visual_result_admission_failed",
                        payload={"invocation_id": str(invocation_id)},
                    )
                error_code = (
                    str(exc)
                    if str(exc).startswith("VISUAL_") and len(str(exc)) <= 120
                    else "VISUAL_RESULT_ADMISSION_FAILED"
                )
                await emit_event(
                    session,
                    job=job,
                    event_type="page.failed.v1",
                    payload={
                        "page_id": str(page_id),
                        "status": "failed",
                        "code": error_code,
                        "attempt_id": str(page_attempt_id),
                        "attempt_number": page_attempt.attempt_number,
                        "invocation_id": str(invocation_id),
                    },
                )
                await _fail_expected_compile(
                    session,
                    job=job,
                    code=error_code,
                    reserved=reserved,
                    attempt=attempt,
                )
                return

            active_job = await _active_compile_job(
                session,
                job_id=job.id,
                tenant_id=job.tenant_id,
                lock_target=True,
            )
            if active_job is None:
                raise JobCancellationFence
            job = active_job
            page = await session.scalar(
                select(Page)
                .where(
                    Page.tenant_id == job.tenant_id,
                    Page.id == page_id,
                )
                .with_for_update()
            )
            page_attempt = await session.scalar(
                select(PageAttempt)
                .where(
                    PageAttempt.tenant_id == job.tenant_id,
                    PageAttempt.id == page_attempt_id,
                    PageAttempt.job_id == job.id,
                )
                .with_for_update()
            )
            invocation = await session.scalar(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == job.tenant_id,
                    GpuProviderInvocation.id == invocation_id,
                    GpuProviderInvocation.job_id == job.id,
                )
                .with_for_update()
            )
            page_asset = await session.scalar(
                select(PageAsset)
                .where(
                    PageAsset.tenant_id == job.tenant_id,
                    PageAsset.id == page_asset_id,
                    PageAsset.page_id == page_id,
                    PageAsset.asset_type == "inference_raster",
                )
                .with_for_update()
            )
            if (
                page is None
                or page_attempt is None
                or invocation is None
                or page_asset is None
                or invocation.status != "completed"
                or invocation.result_manifest_sha256 != terminal_manifest_sha
                or page_attempt.provider_invocation_id
                not in {
                    invocation.id,
                    invocation.lineage_root_invocation_id,
                }
            ):
                raise RuntimeError("VISUAL_RESULT_ADMISSION_FENCE_CHANGED")
            state = PageState(page_attempt.status)
            if state == PageState.OCR_QUEUED:
                await transition_page_attempt(
                    session,
                    page_attempt,
                    PageState.OCR_RUNNING,
                    reason="visual_provider_result_admitted",
                    payload={
                        "invocation_id": str(invocation.id),
                        "result_manifest_sha256": terminal_manifest_sha,
                    },
                )
            elif state != PageState.OCR_RUNNING:
                raise RuntimeError("VISUAL_RESULT_ATTEMPT_STATE_INVALID")
            await transition_page_attempt(
                session,
                page_attempt,
                PageState.NORMALIZING,
                reason="visual_candidate_normalized",
                payload={
                    "invocation_id": str(invocation.id),
                    "block_count": len(visual_result.blocks),
                },
            )
            await transition_page_attempt(
                session,
                page_attempt,
                PageState.VALIDATING,
                reason="visual_normalization_completed",
            )
            sensitive_summary, injection_summary = _visual_sensitive_summary(visual_result)
            if (
                bool(sensitive_summary["has_pii"])
                or bool(sensitive_summary["has_secret"])
                or bool(injection_summary["suspected"])
            ):
                preflight = dict(page.preflight_metrics)
                preflight["visual_sensitive_data"] = sensitive_summary
                preflight["visual_prompt_injection"] = injection_summary
                page.preflight_metrics = preflight
                await transition_page_attempt(
                    session,
                    page_attempt,
                    PageState.QUARANTINED,
                    reason="visual_security_quarantined",
                    payload={
                        "invocation_id": str(invocation.id),
                        "has_pii": bool(sensitive_summary["has_pii"]),
                        "has_secret": bool(sensitive_summary["has_secret"]),
                        "prompt_injection_suspected": bool(injection_summary["suspected"]),
                        "sensitive_counts": sensitive_summary["counts"],
                        "prompt_injection_rule_ids": injection_summary["rule_ids"],
                    },
                )
                await _isolate_compile_page(
                    session,
                    job=job,
                    page=page,
                    page_attempt=page_attempt,
                    reserved=reserved,
                    attempt=attempt,
                    state=PageState.QUARANTINED,
                    code="VISUAL_SECURITY_QUARANTINED",
                    category="visual_security",
                    message=(
                        "Visual OCR security signals were isolated; candidate content was not "
                        "promoted or billed."
                    ),
                )
                # The strict manifest retains only hashes. Remove the rejected
                # raw OCR result object so secret-bearing text is not retained
                # in derived storage.
                await object_store.delete("derived", invocation.output_object_key)
                return
            runtime = await load_routing_runtime(
                session,
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                requested_route_profile=cast(
                    str | None,
                    job.requested_options.get("route_profile"),
                ),
                external_processing_consent=bool(
                    job.requested_options.get("external_processing_consent")
                ),
                dominant_language=(document.language_codes[0] if document.language_codes else None),
            )
            page_runtime, _has_sensitive_secret = constrain_routing_runtime_for_page(
                runtime,
                preflight_metrics=page.preflight_metrics,
            )
            route = Route(page_attempt.route)
            route_attempt_count = int(
                await session.scalar(
                    select(func.count(PageAttempt.id)).where(
                        PageAttempt.tenant_id == job.tenant_id,
                        PageAttempt.job_id == job.id,
                        PageAttempt.page_id == page.id,
                        PageAttempt.route == route.value,
                    )
                )
                or 1
            )
            quality = evaluate_page_quality(
                [_visual_quality_block(block) for block in visual_result.blocks],
                high_risk=page_runtime.context.risk_tier.value == "high",
                failed_attempts=max(0, route_attempt_count - 1),
                mandatory_ocr_accuracy=True,
                requires_independent_verifier=(
                    page_runtime.context.risk_tier.value == "high"
                    or any(
                        block.type in {"table", "formula"}
                        or any(character.isdigit() for character in visual_block_text(block))
                        for block in visual_result.blocks
                    )
                ),
                verification_agreement=(
                    visual_result.verification.agreement
                    if visual_result.verification is not None
                    else None
                ),
                verification_numeric_agreement=(
                    visual_result.verification.numeric_agreement
                    if visual_result.verification is not None
                    else None
                ),
                verification_table_agreement=(
                    visual_result.verification.table_structure_agreement
                    if visual_result.verification is not None
                    else None
                ),
                verification_formula_agreement=(
                    visual_result.verification.formula_agreement
                    if visual_result.verification is not None
                    else None
                ),
            )
            escalation = decide_escalation(
                current_route=route,
                signal=quality.signal,
                attempt_number=route_attempt_count,
                max_attempts=page_attempt.max_attempts,
                context=page_runtime.context,
            )
            escalation_payload = escalation.model_dump(
                mode="json",
                by_alias=False,
            )
            await emit_event(
                session,
                job=job,
                event_type="page.quality.updated.v1",
                payload={
                    "page_id": str(page.id),
                    "quality": quality.evaluation_payload,
                    "escalation": escalation_payload,
                    "attempt_id": str(page_attempt.id),
                    "attempt_number": page_attempt.attempt_number,
                    "invocation_id": str(invocation.id),
                },
            )
            if escalation.action in {
                EscalationAction.ACCEPT,
                EscalationAction.DISCARD_CHALLENGER,
            }:
                visual_blocks: list[Block] = []
                if escalation.action == EscalationAction.ACCEPT:
                    visual_blocks = await _promote_visual_blocks(
                        session,
                        job=job,
                        document=document,
                        page=page,
                        page_asset=page_asset,
                        page_attempt=page_attempt,
                        invocation=invocation,
                        result=visual_result,
                    )
                    for persisted_block in visual_blocks:
                        source_ref = (persisted_block.structured_content or {}).get(
                            "sourceRefs", []
                        )
                        await emit_event(
                            session,
                            job=job,
                            event_type="page.block.completed.v1",
                            payload={
                                "page_id": str(page.id),
                                "block_id": str(persisted_block.id),
                                "order": persisted_block.block_order,
                                "type": persisted_block.block_type,
                                "block_type": persisted_block.block_type,
                                "origin": persisted_block.origin,
                                "origin_type": persisted_block.origin,
                                "content_layer": "extracted",
                                "markdown": persisted_block.markdown,
                                "source_refs": source_ref,
                                "engine": persisted_block.engine,
                                "engine_version": persisted_block.engine_revision,
                                "confidence": persisted_block.confidence,
                                "quality_flags": persisted_block.warnings,
                                "warnings": persisted_block.warnings,
                                "revision": persisted_block.revision,
                                "attempt_id": str(page_attempt.id),
                                "attempt_number": page_attempt.attempt_number,
                                "invocation_id": str(invocation.id),
                            },
                        )
                await transition_page_attempt(
                    session,
                    page_attempt,
                    PageState.COMPLETED,
                    reason=(
                        "visual_quality_gate_accepted"
                        if escalation.action == EscalationAction.ACCEPT
                        else "visual_challenger_discarded"
                    ),
                    quality_vector=quality.vector_payload,
                    quality_findings=quality.findings_payload,
                    quality_evaluation=quality.evaluation_payload,
                    escalation_decision=escalation_payload,
                )
                after_commit_metric(
                    session,
                    record_page_terminal,
                    "completed",
                    route.value,
                )
                await emit_event(
                    session,
                    job=job,
                    event_type="page.completed.v1",
                    payload={
                        "page_id": str(page.id),
                        "status": "completed",
                        "page_number": page.page_number,
                        "attempt_id": str(page_attempt.id),
                        "attempt_number": page_attempt.attempt_number,
                        "invocation_id": str(invocation.id),
                    },
                )
                done = min(
                    max(1, len(pages)),
                    max(0, int(progress.get("done", 0))) + 1,
                )
                job.progress = {
                    "stage": "parse",
                    "state": "VISUAL_ADMITTED",
                    "done": done,
                    "total": max(1, len(pages)),
                    "page_id": str(page.id),
                    "page_attempt_id": str(page_attempt.id),
                    "page_attempt_number": page_attempt.attempt_number,
                    "invocation_id": str(invocation.id),
                }
                await session.commit()
                blocks = list(
                    (
                        await session.scalars(
                            select(Block)
                            .where(
                                Block.tenant_id == job.tenant_id,
                                Block.document_id == document.id,
                            )
                            .order_by(Block.block_order)
                        )
                    ).all()
                )
            elif (
                job.job_type != "collection_integrity_retry"
                and
                escalation.action in {EscalationAction.RETRY, EscalationAction.ESCALATE}
                and escalation.route is not None
                and escalation.route
                not in {
                    Route.UNRESOLVED,
                    Route.QUARANTINE,
                    Route.AUTHORITY_RECONSTRUCTION,
                }
                and escalation.route in page_runtime.context.ready_routes
                and page_runtime.provider_for(escalation.route) is not None
            ):
                await transition_page_attempt(
                    session,
                    page_attempt,
                    PageState.FAILED,
                    reason=f"visual_quality_{escalation.action.value}",
                    quality_vector=quality.vector_payload,
                    quality_findings=quality.findings_payload,
                    quality_evaluation=quality.evaluation_payload,
                    escalation_decision=escalation_payload,
                )
                followup_route = escalation.route
                available_followup_assets = list(
                    (
                        await session.scalars(
                            select(PageAsset).where(
                                PageAsset.tenant_id == job.tenant_id,
                                PageAsset.page_id == page.id,
                                PageAsset.asset_type == "inference_raster",
                            )
                        )
                    ).all()
                )
                followup_asset = _select_inference_raster(
                    available_followup_assets,
                    page=page,
                    route=followup_route,
                    mode=page_runtime.context.mode,
                )
                if followup_asset is None:
                    await _fail_expected_compile(
                        session,
                        job=job,
                        code="VISUAL_PAGE_RASTER_MISSING",
                        reserved=reserved,
                        attempt=attempt,
                    )
                    return
                followup_attempt = await create_page_attempt(
                    session,
                    tenant_id=job.tenant_id,
                    page_id=page.id,
                    attempt_number=await next_attempt_number(
                        session,
                        tenant_id=job.tenant_id,
                        page_id=page.id,
                    ),
                    trigger="compile",
                    initial_state=PageState.OCR_QUEUED,
                    route=followup_route.value,
                    route_profile=page_attempt.route_profile,
                    route_policy_version=escalation.policy_version,
                    max_attempts=page_attempt.max_attempts,
                    job_id=job.id,
                    reason=f"visual_quality_{escalation.action.value}_enqueued",
                    payload={
                        "previous_attempt_id": str(page_attempt.id),
                        "reason_codes": list(escalation.reason_codes),
                    },
                )
                await _enqueue_visual_page(
                    session=session,
                    job=job,
                    document=document,
                    page=page,
                    page_asset=followup_asset,
                    source_sha256=source.sha256,
                    attempt=followup_attempt,
                    runtime=page_runtime,
                    route=followup_route,
                )
                await session.commit()
                return
            else:
                terminal_state = (
                    PageState.FAILED
                    if escalation.action == EscalationAction.FAIL
                    else PageState.QUARANTINED
                    if escalation.action == EscalationAction.QUARANTINE
                    else PageState.UNRESOLVED
                )
                await transition_page_attempt(
                    session,
                    page_attempt,
                    terminal_state,
                    reason=f"visual_quality_{escalation.action.value}",
                    quality_vector=quality.vector_payload,
                    quality_findings=quality.findings_payload,
                    quality_evaluation=quality.evaluation_payload,
                    escalation_decision=escalation_payload,
                )
                if terminal_state == PageState.FAILED:
                    await _fail_expected_compile(
                        session,
                        job=job,
                        code="VISUAL_PAGE_QUALITY_FAILED",
                        reserved=reserved,
                        attempt=attempt,
                    )
                else:
                    await _isolate_compile_page(
                        session,
                        job=job,
                        page=page,
                        page_attempt=page_attempt,
                        reserved=reserved,
                        attempt=attempt,
                        state=terminal_state,
                        code=(
                            "VISUAL_PAGE_QUARANTINED"
                            if terminal_state == PageState.QUARANTINED
                            else "VISUAL_PAGE_UNRESOLVED"
                        ),
                        category="visual_quality_gate",
                        message="Automatic visual verification exhausted safe recovery paths.",
                    )
                return
        blocks_by_page: dict[uuid.UUID, list[Block]] = {}
        for block in blocks:
            if block.page_id is not None:
                blocks_by_page.setdefault(block.page_id, []).append(block)
        active_job = await _active_compile_job(
            session,
            job_id=job.id,
            tenant_id=job.tenant_id,
            lock_target=True,
        )
        if active_job is None:
            raise JobCancellationFence
        job = active_job
        runtime = await load_routing_runtime(
            session,
            tenant_id=job.tenant_id,
            project_id=job.project_id,
            requested_route_profile=cast(
                str | None,
                job.requested_options.get("route_profile"),
            ),
            external_processing_consent=bool(
                job.requested_options.get("external_processing_consent")
            ),
            dominant_language=(document.language_codes[0] if document.language_codes else None),
        )
        page_ids = [page.id for page in pages]
        if page_ids:
            pages = list(
                (
                    await session.scalars(
                        select(Page)
                        .where(
                            Page.tenant_id == job.tenant_id,
                            Page.id.in_(page_ids),
                        )
                        .order_by(Page.page_number)
                        .with_for_update()
                    )
                ).all()
            )
        page_asset_rows = list(
            (
                await session.scalars(
                    select(PageAsset)
                    .where(
                        PageAsset.tenant_id == job.tenant_id,
                        PageAsset.page_id.in_(page_ids),
                        PageAsset.asset_type == "inference_raster",
                    )
                    .order_by(PageAsset.created_at.desc(), PageAsset.id.desc())
                )
            ).all()
        )
        page_assets: dict[uuid.UUID, list[PageAsset]] = {}
        for page_asset_row in page_asset_rows:
            page_assets.setdefault(page_asset_row.page_id, []).append(page_asset_row)
        total_pages = len(pages)
        for index, page in enumerate(pages, 1):
            if (
                await _active_compile_job(
                    session,
                    job_id=job.id,
                    tenant_id=job.tenant_id,
                )
                is None
            ):
                raise JobCancellationFence
            page_runtime, has_sensitive_secret = constrain_routing_runtime_for_page(
                runtime,
                preflight_metrics=page.preflight_metrics,
            )
            page_context = page_runtime.context
            selected = select_first_route(
                page_context,
                _persisted_router_metrics(page),
            )
            page_attempt = await _job_page_attempt(
                session,
                job=job,
                page_id=page.id,
            )
            route = selected.route
            route_profile = selected.route_profile.value
            route_policy_version = selected.policy_version
            max_attempts = selected.max_attempts
            route_reasons = selected.reason_codes
            expected_credits = selected.expected_credits
            if (
                not isinstance(page.preflight_metrics.get("router_metrics"), dict)
                and page.route == Route.NATIVE.value
            ):
                # Legacy rows may predate the persisted metric snapshot. Their
                # analysis-selected native route remains the only available
                # evidence; compilation still loads the current tenant policy.
                route = Route.NATIVE
                route_reasons = ("persisted_analysis_native_route",)
            if page_attempt is not None:
                try:
                    route = Route(page_attempt.route)
                except ValueError:
                    route = Route.UNRESOLVED
                route_profile = page_attempt.route_profile
                route_policy_version = page_attempt.route_policy_version
                max_attempts = page_attempt.max_attempts
                route_reasons = ("persisted_page_attempt_route",)
                expected_credits = 0.0
            if has_sensitive_secret and route == Route.MISTRAL_FALLBACK:
                route = Route.QUARANTINE
                route_reasons = (
                    "sensitive_data_external_transfer_denied",
                    "fail_closed_quarantine",
                )
            await emit_event(
                session,
                job=job,
                event_type="page.preflight.completed.v1",
                payload={
                    "page_id": str(page.id),
                    "page_number": page.page_number,
                    "metrics": page.preflight_metrics,
                    "processing_mode": page_context.mode.value,
                    "sensitive_data_detected": has_sensitive_secret,
                    "route_profile": route_profile,
                    **(
                        {
                            "attempt_id": str(page_attempt.id),
                            "attempt_number": page_attempt.attempt_number,
                        }
                        if page_attempt is not None
                        else {}
                    ),
                },
            )
            await emit_event(
                session,
                job=job,
                event_type="page.route.selected.v1",
                payload={
                    "page_id": str(page.id),
                    "route": route.value,
                    "policy_version": route_policy_version,
                    "route_profile": route_profile,
                    "processing_mode": page_context.mode.value,
                    "sensitive_data_detected": has_sensitive_secret,
                    "reasons": list(route_reasons),
                    "estimated_credits": expected_credits,
                    **(
                        {
                            "attempt_id": str(page_attempt.id),
                            "attempt_number": page_attempt.attempt_number,
                        }
                        if page_attempt is not None
                        else {}
                    ),
                },
            )
            if page_attempt is not None and PageState(page_attempt.status) in {
                PageState.COMPLETED,
                PageState.UNRESOLVED,
                PageState.QUARANTINED,
                PageState.NEEDS_REVIEW,
                PageState.FAILED,
            }:
                if PageState(page_attempt.status) == PageState.COMPLETED:
                    continue
                terminal_attempt_state = PageState(page_attempt.status)
                if terminal_attempt_state in {
                    PageState.UNRESOLVED,
                    PageState.QUARANTINED,
                    PageState.NEEDS_REVIEW,
                }:
                    isolated_state = (
                        PageState.QUARANTINED
                        if terminal_attempt_state == PageState.QUARANTINED
                        else PageState.UNRESOLVED
                    )
                    await _isolate_compile_page(
                        session,
                        job=job,
                        page=page,
                        page_attempt=page_attempt,
                        reserved=reserved,
                        attempt=attempt,
                        state=isolated_state,
                        code=(
                            "PAGE_QUARANTINED"
                            if isolated_state == PageState.QUARANTINED
                            else "PAGE_UNRESOLVED"
                        ),
                        category="persisted_quality_isolation",
                        message="The latest immutable attempt remains safely isolated.",
                    )
                    return
                await _fail_expected_compile(
                    session,
                    job=job,
                    code="PAGE_ATTEMPT_FAILED",
                    reserved=reserved,
                    attempt=attempt,
                )
                return
            if route in {Route.UNRESOLVED, Route.QUARANTINE}:
                if page_attempt is None:
                    page_attempt = await create_page_attempt(
                        session,
                        tenant_id=job.tenant_id,
                        page_id=page.id,
                        attempt_number=await next_attempt_number(
                            session,
                            tenant_id=job.tenant_id,
                            page_id=page.id,
                        ),
                        trigger="compile",
                        initial_state=PageState.PREFLIGHTED,
                        route=route.value,
                        route_profile=route_profile,
                        route_policy_version=route_policy_version,
                        max_attempts=max_attempts,
                        job_id=job.id,
                        reason="compile_route_selected",
                        payload={"reason_codes": list(route_reasons)},
                    )
                await transition_page_attempt(
                    session,
                    page_attempt,
                    (PageState.QUARANTINED if route == Route.QUARANTINE else PageState.UNRESOLVED),
                    reason="automatic_route_isolated",
                    payload={"reason_codes": list(route_reasons)},
                )
                await emit_event(
                    session,
                    job=job,
                    event_type=(
                        "page.quarantined.v1" if route == Route.QUARANTINE else "page.unresolved.v1"
                    ),
                    payload={
                        "page_id": str(page.id),
                        "status": route.value,
                        "severity": "high",
                        "category": "automatic_route_unavailable",
                        "message": "No verified automatic route is available for this page.",
                        "attempt_id": str(page_attempt.id),
                        "attempt_number": page_attempt.attempt_number,
                    },
                )
                await _isolate_compile_page(
                    session,
                    job=job,
                    page=page,
                    page_attempt=page_attempt,
                    reserved=reserved,
                    attempt=attempt,
                    state=(
                        PageState.QUARANTINED if route == Route.QUARANTINE else PageState.UNRESOLVED
                    ),
                    code=(
                        "PAGE_QUARANTINED"
                        if route == Route.QUARANTINE
                        else "VISUAL_PROVIDER_NOT_CONFIGURED"
                    ),
                    category="automatic_route_unavailable",
                    message="The page was isolated without billing or human dependency.",
                )
                return
            if route != Route.NATIVE:
                provider_called = True
                provider_name = route.value
                if page_attempt is None:
                    page_attempt = await create_page_attempt(
                        session,
                        tenant_id=job.tenant_id,
                        page_id=page.id,
                        attempt_number=await next_attempt_number(
                            session,
                            tenant_id=job.tenant_id,
                            page_id=page.id,
                        ),
                        trigger="compile",
                        initial_state=PageState.PREFLIGHTED,
                        route=route.value,
                        route_profile=route_profile,
                        route_policy_version=route_policy_version,
                        max_attempts=max_attempts,
                        job_id=job.id,
                        reason="compile_route_selected",
                        payload={"reason_codes": list(route_reasons)},
                    )
                state = PageState(page_attempt.status)
                if state == PageState.PREFLIGHTED:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.OCR_QUEUED,
                        reason="visual_provider_enqueue_requested",
                    )
                elif state == PageState.RETRY_SCHEDULED:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.OCR_QUEUED,
                        reason="retry_visual_provider_enqueue_requested",
                    )
                elif state not in {PageState.OCR_QUEUED, PageState.OCR_RUNNING}:
                    raise RuntimeError("VISUAL_ATTEMPT_STATE_INVALID")
                page_asset = _select_inference_raster(
                    page_assets.get(page.id, ()),
                    page=page,
                    route=route,
                    mode=page_context.mode,
                )
                if page_asset is None:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.FAILED,
                        reason="visual_page_raster_missing",
                    )
                    await _fail_expected_compile(
                        session,
                        job=job,
                        code="VISUAL_PAGE_RASTER_MISSING",
                        reserved=reserved,
                        attempt=attempt,
                    )
                    return
                await _enqueue_visual_page(
                    session=session,
                    job=job,
                    document=document,
                    page=page,
                    page_asset=page_asset,
                    source_sha256=(source.sha256 if source is not None else None),
                    attempt=page_attempt,
                    runtime=page_runtime,
                    route=route,
                )
                await session.commit()
                return

            while True:
                if page_attempt is None:
                    page_attempt = await create_page_attempt(
                        session,
                        tenant_id=job.tenant_id,
                        page_id=page.id,
                        attempt_number=await next_attempt_number(
                            session,
                            tenant_id=job.tenant_id,
                            page_id=page.id,
                        ),
                        trigger="compile",
                        initial_state=PageState.PREFLIGHTED,
                        route=route.value,
                        route_profile=route_profile,
                        route_policy_version=route_policy_version,
                        max_attempts=max_attempts,
                        job_id=job.id,
                        reason="compile_route_selected",
                        payload={"reason_codes": list(route_reasons)},
                    )
                state = PageState(page_attempt.status)
                if state == PageState.PREFLIGHTED:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.NATIVE_EXTRACTING,
                        reason="native_extraction_started",
                    )
                elif state not in {
                    PageState.NATIVE_EXTRACTING,
                    PageState.NORMALIZING,
                    PageState.VALIDATING,
                }:
                    raise RuntimeError("NATIVE_ATTEMPT_STATE_INVALID")
                await emit_event(
                    session,
                    job=job,
                    event_type="page.processing.started.v1",
                    payload={
                        "page_id": str(page.id),
                        "status": "native_extracting",
                        "route": route.value,
                        "attempt_id": str(page_attempt.id),
                        "attempt_number": page_attempt.attempt_number,
                    },
                )
                for block in blocks_by_page.get(page.id, []):
                    source_ref = {
                        "document_id": str(document.id),
                        "document_version_id": (f"{document.id}:v{document.active_version}"),
                        "page_index": page.page_number - 1,
                        "page_number": page.page_number,
                        "bbox1000": block.bbox1000,
                    }
                    await emit_event(
                        session,
                        job=job,
                        event_type="page.block.completed.v1",
                        payload={
                            "page_id": str(page.id),
                            "block_id": str(block.id),
                            "order": block.block_order,
                            "type": block.block_type,
                            "block_type": block.block_type,
                            "origin": block.origin,
                            "origin_type": block.origin,
                            "content_layer": "extracted",
                            "markdown": block.markdown,
                            "source_text": block.source_text,
                            "source_refs": [source_ref],
                            "engine": block.engine,
                            "engine_version": block.engine_revision,
                            "confidence": block.confidence,
                            "quality_flags": block.warnings,
                            "warnings": block.warnings,
                            "revision": block.revision,
                            "attempt_id": str(page_attempt.id),
                            "attempt_number": page_attempt.attempt_number,
                        },
                    )
                    await emit_event(
                        session,
                        job=job,
                        event_type="page.markdown.updated.v1",
                        payload={
                            "page_id": str(page.id),
                            "block_id": str(block.id),
                            "markdown": block.markdown,
                            "revision": block.revision,
                            "attempt_id": str(page_attempt.id),
                            "attempt_number": page_attempt.attempt_number,
                        },
                    )
                if PageState(page_attempt.status) == PageState.NATIVE_EXTRACTING:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.NORMALIZING,
                        reason="native_extraction_completed",
                    )
                if PageState(page_attempt.status) == PageState.NORMALIZING:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.VALIDATING,
                        reason="native_normalization_completed",
                    )
                route_attempt_count = int(
                    await session.scalar(
                        select(func.count(PageAttempt.id)).where(
                            PageAttempt.tenant_id == job.tenant_id,
                            PageAttempt.job_id == job.id,
                            PageAttempt.page_id == page.id,
                            PageAttempt.route == route.value,
                        )
                    )
                    or 1
                )
                quality = evaluate_page_quality(
                    [quality_block_from_record(block) for block in blocks_by_page.get(page.id, [])],
                    high_risk=page_context.risk_tier.value == "high",
                    failed_attempts=max(0, route_attempt_count - 1),
                )
                escalation = decide_escalation(
                    current_route=route,
                    signal=quality.signal,
                    attempt_number=route_attempt_count,
                    max_attempts=max_attempts,
                    context=page_context,
                )
                escalation_payload = escalation.model_dump(
                    mode="json",
                    by_alias=False,
                )
                await emit_event(
                    session,
                    job=job,
                    event_type="page.quality.updated.v1",
                    payload={
                        "page_id": str(page.id),
                        "quality": quality.evaluation_payload,
                        "escalation": escalation_payload,
                        "attempt_id": str(page_attempt.id),
                        "attempt_number": page_attempt.attempt_number,
                    },
                )
                if escalation.action == EscalationAction.ACCEPT:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.COMPLETED,
                        reason="quality_gate_accepted",
                        quality_vector=quality.vector_payload,
                        quality_findings=quality.findings_payload,
                        quality_evaluation=quality.evaluation_payload,
                        escalation_decision=escalation_payload,
                    )
                    after_commit_metric(
                        session,
                        record_page_terminal,
                        "completed",
                        route.value,
                    )
                    await emit_event(
                        session,
                        job=job,
                        event_type="page.completed.v1",
                        payload={
                            "page_id": str(page.id),
                            "status": "completed",
                            "page_number": page.page_number,
                            "attempt_id": str(page_attempt.id),
                            "attempt_number": page_attempt.attempt_number,
                        },
                    )
                    break
                if escalation.action == EscalationAction.RETRY:
                    await transition_page_attempt(
                        session,
                        page_attempt,
                        PageState.FAILED,
                        reason="bounded_native_retry",
                        payload={
                            "next_route_attempt": route_attempt_count + 1,
                        },
                        quality_vector=quality.vector_payload,
                        quality_findings=quality.findings_payload,
                        quality_evaluation=quality.evaluation_payload,
                        escalation_decision=escalation_payload,
                    )
                    retry_from = page_attempt
                    page_attempt = await create_page_attempt(
                        session,
                        tenant_id=job.tenant_id,
                        page_id=page.id,
                        attempt_number=await next_attempt_number(
                            session,
                            tenant_id=job.tenant_id,
                            page_id=page.id,
                        ),
                        trigger="compile",
                        initial_state=PageState.PREFLIGHTED,
                        route=route.value,
                        route_profile=route_profile,
                        route_policy_version=route_policy_version,
                        max_attempts=max_attempts,
                        job_id=job.id,
                        reason="bounded_native_retry_created",
                        payload={"previous_attempt_id": str(retry_from.id)},
                    )
                    await emit_event(
                        session,
                        job=job,
                        event_type="page.retry.scheduled.v1",
                        payload={
                            "page_id": str(page.id),
                            "status": "retry_scheduled",
                            "attempt_id": str(page_attempt.id),
                            "attempt_number": page_attempt.attempt_number,
                            "previous_attempt_id": str(retry_from.id),
                        },
                    )
                    continue
                terminal_state = (
                    PageState.FAILED
                    if escalation.action == EscalationAction.FAIL
                    else PageState.QUARANTINED
                    if escalation.action == EscalationAction.QUARANTINE
                    else PageState.UNRESOLVED
                )
                await transition_page_attempt(
                    session,
                    page_attempt,
                    terminal_state,
                    reason=f"quality_gate_{escalation.action.value}",
                    quality_vector=quality.vector_payload,
                    quality_findings=quality.findings_payload,
                    quality_evaluation=quality.evaluation_payload,
                    escalation_decision=escalation_payload,
                )
                after_commit_metric(
                    session,
                    record_page_terminal,
                    terminal_state.value.casefold(),
                    route.value,
                )
                if (
                    job.job_type != "collection_integrity_retry"
                    and escalation.action == EscalationAction.ESCALATE
                    and escalation.route is not None
                    and escalation.route
                    not in {
                        Route.UNRESOLVED,
                        Route.QUARANTINE,
                        Route.AUTHORITY_RECONSTRUCTION,
                    }
                    and escalation.route in page_context.ready_routes
                ):
                    escalation_asset = _select_inference_raster(
                        page_assets.get(page.id, ()),
                        page=page,
                        route=escalation.route,
                        mode=page_context.mode,
                    )
                    if escalation_asset is None:
                        await _fail_expected_compile(
                            session,
                            job=job,
                            code="VISUAL_PAGE_RASTER_MISSING",
                            reserved=reserved,
                            attempt=attempt,
                        )
                        return
                    escalation_attempt = await create_page_attempt(
                        session,
                        tenant_id=job.tenant_id,
                        page_id=page.id,
                        attempt_number=await next_attempt_number(
                            session,
                            tenant_id=job.tenant_id,
                            page_id=page.id,
                        ),
                        trigger="compile",
                        initial_state=PageState.OCR_QUEUED,
                        route=escalation.route.value,
                        route_profile=route_profile,
                        route_policy_version=escalation.policy_version,
                        max_attempts=max_attempts,
                        job_id=job.id,
                        reason="quality_escalation_enqueued",
                        payload={
                            "previous_attempt_id": str(page_attempt.id),
                            "reason_codes": list(escalation.reason_codes),
                        },
                    )
                    provider_called = True
                    provider_name = escalation.route.value
                    await _enqueue_visual_page(
                        session=session,
                        job=job,
                        document=document,
                        page=page,
                        page_asset=escalation_asset,
                        source_sha256=(source.sha256 if source is not None else None),
                        attempt=escalation_attempt,
                        runtime=page_runtime,
                        route=escalation.route,
                    )
                    await session.commit()
                    return
                if terminal_state == PageState.FAILED:
                    await emit_event(
                        session,
                        job=job,
                        event_type="page.failed.v1",
                        payload={
                            "page_id": str(page.id),
                            "status": "failed",
                            "code": "PAGE_QUALITY_FAILED",
                            "attempt_id": str(page_attempt.id),
                            "attempt_number": page_attempt.attempt_number,
                        },
                    )
                    await _fail_expected_compile(
                        session,
                        job=job,
                        code="PAGE_QUALITY_FAILED",
                        reserved=reserved,
                        attempt=attempt,
                    )
                    return
                await _isolate_compile_page(
                    session,
                    job=job,
                    page=page,
                    page_attempt=page_attempt,
                    reserved=reserved,
                    attempt=attempt,
                    state=terminal_state,
                    code=(
                        "PAGE_QUARANTINED"
                        if terminal_state == PageState.QUARANTINED
                        else "PAGE_UNRESOLVED"
                    ),
                    category="quality_gate",
                    message="Automatic verification exhausted safe recovery paths.",
                )
                return
            job.progress = {"done": index, "total": max(1, total_pages)}
            await emit_event(
                session,
                job=job,
                event_type="job.stage.progress.v1",
                payload={
                    "stage": "parse",
                    "done": index,
                    "total": total_pages,
                    "page_id": str(page.id),
                    "attempt_id": str(page_attempt.id),
                    "attempt_number": page_attempt.attempt_number,
                },
            )
        if job.job_type == "collection_integrity_retry":
            # Integrity retries are extraction-only and never fan out into
            # knowledge compilation or billing authority.
            job.status = "completed"
            job.completed_at = utcnow()
            job.progress = {
                "stage": "integrity_retry_completed",
                "done": max(1, total_pages),
                "total": max(1, total_pages),
            }
            job.cost_actual = {
                "credits": "0.000000",
                "provider": provider_name,
                "released": "0.000000",
                "billing_disposition": "unbillable_integrity_retry",
            }
            await emit_event(
                session,
                job=job,
                event_type="job.stage.completed.v1",
                payload={"stage": "route", "done": total_pages, "total": total_pages},
            )
            await emit_event(
                session,
                job=job,
                event_type="job.completed.v1",
                payload={"status": "completed", "credits": "0.000000"},
            )
            session.add(
                OutboxEvent(
                    tenant_id=job.tenant_id,
                    aggregate_type="job",
                    aggregate_id=job.id,
                    event_type="job.completed.v1",
                    payload={
                        "job_id": str(job.id),
                        "billing_disposition": "unbillable_integrity_retry",
                    },
                )
            )
            after_commit_metric(session, record_job_terminal, "completed")
            await session.commit()
            return
        # Repeated marginal blocks remain persisted for provenance and review,
        # but high-confidence non-legal header/footer annotations do not enter
        # the knowledge compiler's body context.
        body_blocks = [block for block in blocks if not _block_excluded_from_body(block)]
        # Marginal detection is deliberately conservative. A document whose
        # every block resembles a repeated header/footer still needs a
        # provenance-bearing body; never erase the compiler's entire evidence
        # set because of a heuristic annotation.
        if body_blocks:
            blocks = body_blocks
        await emit_event(
            session,
            job=job,
            event_type="job.stage.completed.v1",
            payload={"stage": "route", "done": total_pages, "total": total_pages},
        )
        await emit_event(
            session,
            job=job,
            event_type="job.stage.started.v1",
            payload={"stage": "knowledge"},
        )
        # Provider latency must not hold job/document row locks or an open
        # write transaction. The durable stage boundary is committed first;
        # provider results are admitted only after a fresh tombstone/cancel
        # fence when control returns.
        await session.commit()
        if (
            await _active_compile_job(
                session,
                job_id=job.id,
                tenant_id=job.tenant_id,
            )
            is None
        ):
            raise JobCancellationFence
        provider_name = (
            "external"
            if job.requested_options.get("external_processing_consent")
            else str(settings.knowledge_provider)
        )
        provider_called = True
        provider = knowledge_provider(
            settings,
            bool(job.requested_options.get("external_processing_consent")),
        )
        if isinstance(provider, DurableQwenKnowledgeProvider):
            provider_name = provider.provider_key
            admitted_bundle = await _durable_qwen_bundle(
                session=session,
                job=job,
                document=document,
                blocks=blocks,
                pages=pages,
                provider=provider,
                object_store=object_store,
            )
            if admitted_bundle is None:
                return
            after_commit_metric(
                session,
                record_provider_request,
                provider_name,
                result="success",
            )
            await _complete_compile_knowledge(
                session=session,
                job=job,
                document=document,
                pages=pages,
                reserved=reserved,
                attempt=attempt,
                provider_name=provider_name,
                bundle=admitted_bundle,
            )
        else:
            compiled = await provider.compile(
                title=document.title,
                blocks=[
                    (
                        str(block.id),
                        block.markdown or block.normalized_text or "",
                    )
                    for block in blocks
                ],
            )
            if not compiled or any(not note.evidence_block_ids for note in compiled):
                unsupported_claim = True
                raise RuntimeError("evidence_required")
            after_commit_metric(
                session,
                record_provider_request,
                provider_name,
                result="success",
            )
            await _complete_compile_knowledge(
                session=session,
                job=job,
                document=document,
                pages=pages,
                reserved=reserved,
                attempt=attempt,
                provider_name=provider_name,
                compiled=compiled,
            )
    except Exception as exc:
        logger.exception(
            "compile job failed",
            extra={"job_id": str(job_id)},
        )
        await session.rollback()
        job = await session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .execution_options(populate_existing=True)
        )
        if job is None:
            return
        if isinstance(exc, JobCancellationFence):
            return
        target_active = await _active_compile_job(
            session,
            job_id=job.id,
            tenant_id=job.tenant_id,
        )
        if job.status == "cancelled" or target_active is None:
            return
        if reserved:
            await credit_entry(
                session,
                tenant_id=job.tenant_id,
                operation_key=f"job:{job.id}:attempt:{attempt}:release",
                entry_type="release",
                credits=reserved,
                job_id=job.id,
            )
        job.status = "failed"
        job.completed_at = utcnow()
        code = str(exc) if isinstance(exc, ProviderUnavailable) else "COMPILE_FAILED"
        job.error = {"code": code, "retryable": False}
        await emit_event(
            session,
            job=job,
            event_type="job.failed.v1",
            payload={"status": "failed", "code": code},
        )
        if reserved:
            await emit_event(
                session,
                job=job,
                event_type="credit.released.v1",
                payload={"credits": str(reserved), "reason": "job_failed"},
            )
        session.add(
            OutboxEvent(
                tenant_id=job.tenant_id,
                aggregate_type="job",
                aggregate_id=job.id,
                event_type="job.failed.v1",
                payload={"job_id": str(job.id), "code": code},
            )
        )
        if provider_called:
            result = (
                "denied"
                if isinstance(exc, ProviderUnavailable)
                and str(exc)
                in {
                    "PRIVATE_MODE_EXTERNAL_TRANSFER_DENIED",
                    "EXTERNAL_PROVIDER_DISABLED",
                }
                else "failed"
            )
            after_commit_metric(
                session,
                record_provider_request,
                provider_name,
                result=result,
            )
            if result == "denied":
                after_commit_metric(session, record_external_egress_denied)
        if unsupported_claim:
            after_commit_metric(
                session,
                record_unsupported_claim,
                accepted=False,
            )
        after_commit_metric(session, record_job_terminal, "failed")
        await session.commit()


async def run_compile_job(
    *,
    session: AsyncSession,
    job_id: uuid.UUID,
    settings: KnowledgeProviderSettings,
    object_store: ObjectStore | None = None,
) -> None:
    try:
        await _run_compile_job_impl(
            session=session,
            job_id=job_id,
            settings=settings,
            object_store=object_store,
        )
    finally:
        # No return path may strand customer-visible integrity execution state.
        await reconcile_integrity_retry_job(session, job_id=job_id)


async def build_export_bundle(
    session: AsyncSession,
    export: Export,
    *,
    profiles: Sequence[str] | None = None,
    object_store: ObjectStore | None = None,
) -> tuple[bytes, str]:
    return await build_artifact_bundle(
        session,
        export,
        profiles=profiles,
        object_store=object_store,
    )


async def cleanup_expired_events(session: AsyncSession, settings: Settings) -> int:
    cutoff = utcnow() - timedelta(days=settings.event_retention_days)
    rows = list(
        (await session.scalars(select(JobEvent).where(JobEvent.occurred_at < cutoff))).all()
    )
    for row in rows:
        await session.delete(row)
    return len(rows)
