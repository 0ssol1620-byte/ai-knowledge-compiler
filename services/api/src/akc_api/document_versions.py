"""Immutable source-version snapshots and deterministic model/version diffs."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    Block,
    BlockRevision,
    Document,
    DocumentSemanticClassification,
    DocumentVersion,
    GpuProviderInvocation,
    KnowledgeNote,
    Page,
    PageAsset,
    PageAttempt,
    PageAttemptTransitionEvent,
    Relation,
    ReviewItem,
    SourceFile,
)
from akc_api.storage import ObjectStore


@dataclass(frozen=True, slots=True)
class DocumentVersionSnapshot:
    payload: bytes
    sha256: str
    page_count: int
    block_count: int
    review_item_count: int
    object_targets: tuple[tuple[str, str], ...]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


async def build_document_version_snapshot(
    session: AsyncSession,
    *,
    document: Document,
    version: DocumentVersion,
) -> DocumentVersionSnapshot:
    """Serialize the active projection without timestamps or host-dependent data."""

    if version.document_id != document.id or version.tenant_id != document.tenant_id:
        raise ValueError("document version identity mismatch")
    if version.version != document.active_version:
        raise ValueError("only the active document projection can be snapshotted")
    source = await session.scalar(
        select(SourceFile).where(
            SourceFile.tenant_id == document.tenant_id,
            SourceFile.id == document.source_file_id,
        )
    )
    if source is None:
        raise ValueError("active document source is unavailable")
    if version.source_file_id is not None and version.source_file_id != source.id:
        raise ValueError("document version source identity mismatch")
    if version.source_sha256 is not None and version.source_sha256 != source.sha256:
        raise ValueError("document version source hash mismatch")

    pages = list(
        (
            await session.scalars(
                select(Page)
                .where(
                    Page.tenant_id == document.tenant_id,
                    Page.document_id == document.id,
                )
                .order_by(Page.page_number, Page.id)
            )
        ).all()
    )
    page_ids = [page.id for page in pages]
    assets = (
        list(
            (
                await session.scalars(
                    select(PageAsset)
                    .where(
                        PageAsset.tenant_id == document.tenant_id,
                        PageAsset.page_id.in_(page_ids),
                    )
                    .order_by(PageAsset.page_id, PageAsset.asset_type, PageAsset.id)
                )
            ).all()
        )
        if page_ids
        else []
    )
    attempts = (
        list(
            (
                await session.scalars(
                    select(PageAttempt)
                    .where(
                        PageAttempt.tenant_id == document.tenant_id,
                        PageAttempt.page_id.in_(page_ids),
                    )
                    .order_by(
                        PageAttempt.page_id,
                        PageAttempt.attempt_number,
                        PageAttempt.id,
                    )
                )
            ).all()
        )
        if page_ids
        else []
    )
    attempt_ids = [attempt.id for attempt in attempts]
    attempt_events = (
        list(
            (
                await session.scalars(
                    select(PageAttemptTransitionEvent)
                    .where(
                        PageAttemptTransitionEvent.tenant_id == document.tenant_id,
                        PageAttemptTransitionEvent.attempt_id.in_(attempt_ids),
                    )
                    .order_by(
                        PageAttemptTransitionEvent.attempt_id,
                        PageAttemptTransitionEvent.sequence,
                        PageAttemptTransitionEvent.id,
                    )
                )
            ).all()
        )
        if attempt_ids
        else []
    )
    gpu_invocations = list(
        (
            await session.scalars(
                select(GpuProviderInvocation)
                .where(
                    GpuProviderInvocation.tenant_id == document.tenant_id,
                    GpuProviderInvocation.document_id == document.id,
                    GpuProviderInvocation.document_version_id
                    == f"{document.id}:v{version.version}",
                )
                .order_by(
                    GpuProviderInvocation.created_at,
                    GpuProviderInvocation.id,
                )
            )
        ).all()
    )
    blocks = list(
        (
            await session.scalars(
                select(Block)
                .where(
                    Block.tenant_id == document.tenant_id,
                    Block.document_id == document.id,
                )
                .order_by(Block.block_order, Block.id)
            )
        ).all()
    )
    block_ids = [block.id for block in blocks]
    revisions = (
        list(
            (
                await session.scalars(
                    select(BlockRevision)
                    .where(
                        BlockRevision.tenant_id == document.tenant_id,
                        BlockRevision.block_id.in_(block_ids),
                    )
                    .order_by(
                        BlockRevision.block_id,
                        BlockRevision.new_revision,
                        BlockRevision.id,
                    )
                )
            ).all()
        )
        if block_ids
        else []
    )
    reviews = list(
        (
            await session.scalars(
                select(ReviewItem)
                .where(
                    ReviewItem.tenant_id == document.tenant_id,
                    ReviewItem.document_id == document.id,
                )
                .order_by(ReviewItem.created_at, ReviewItem.id)
            )
        ).all()
    )
    semantic_classifications = list(
        (
            await session.scalars(
                select(DocumentSemanticClassification)
                .where(
                    DocumentSemanticClassification.tenant_id == document.tenant_id,
                    DocumentSemanticClassification.document_id == document.id,
                    DocumentSemanticClassification.document_version == version.version,
                )
                .order_by(
                    DocumentSemanticClassification.created_at,
                    DocumentSemanticClassification.id,
                )
            )
        ).all()
    )
    knowledge_notes = list(
        (
            await session.scalars(
                select(KnowledgeNote)
                .where(
                    KnowledgeNote.tenant_id == document.tenant_id,
                    KnowledgeNote.document_id == document.id,
                    KnowledgeNote.document_version == version.version,
                )
                .order_by(KnowledgeNote.stable_key, KnowledgeNote.id)
            )
        ).all()
    )
    relations = list(
        (
            await session.scalars(
                select(Relation)
                .where(
                    Relation.tenant_id == document.tenant_id,
                    Relation.document_id == document.id,
                    Relation.document_version == version.version,
                )
                .order_by(
                    Relation.source_relation_key,
                    Relation.subject_id,
                    Relation.predicate,
                    Relation.object_id,
                    Relation.id,
                )
            )
        ).all()
    )
    payload = _json_bytes(
        {
            "schema_version": "document-version-snapshot-1.0.0",
            "tenant_id": str(document.tenant_id),
            "document_id": str(document.id),
            "document_version": version.version,
            "source": {
                "source_file_id": str(source.id),
                "filename": source.safe_filename,
                "mime_type": source.mime_type,
                "size_bytes": source.size_bytes,
                "sha256": source.sha256,
                "storage_key": source.storage_key,
            },
            "document": {
                "title": document.title,
                "source_format": document.document_type,
                "language_codes": document.language_codes,
                "page_count": document.page_count,
                "cir_schema_version": document.cir_schema_version,
                "status": document.status,
            },
            "processing": {
                "policy_version": version.policy_version,
                "model_revision": version.model_revision,
                "prompt_revision": version.prompt_revision,
                "normalization_revision": version.normalization_revision,
                "akmp_schema_version": version.akmp_schema_version,
                "input_revision_hash": version.input_revision_hash,
            },
            "pages": [
                {
                    "id": str(page.id),
                    "page_number": page.page_number,
                    "width_pt": page.width_pt,
                    "height_pt": page.height_pt,
                    "rotation": page.rotation,
                    "status": page.status,
                    "route": page.route,
                    "route_policy_version": page.route_policy_version,
                    "preflight_metrics": page.preflight_metrics,
                    "quality_metrics": page.quality_metrics,
                    "thumbnail_key": page.thumbnail_key,
                    "render_key": page.render_key,
                }
                for page in pages
            ],
            "page_assets": [
                {
                    "id": str(asset.id),
                    "page_id": str(asset.page_id),
                    "asset_type": asset.asset_type,
                    "storage_key": asset.storage_key,
                    "sha256": asset.sha256,
                    "metadata": asset.metadata_json,
                }
                for asset in assets
            ],
            "page_attempts": [
                {
                    "id": str(attempt.id),
                    "page_id": str(attempt.page_id),
                    "attempt_number": attempt.attempt_number,
                    "trigger": attempt.trigger,
                    "status": attempt.status,
                    "route": attempt.route,
                    "route_profile": attempt.route_profile,
                    "route_policy_version": attempt.route_policy_version,
                    "max_attempts": attempt.max_attempts,
                    "quality_vector": attempt.quality_vector,
                    "quality_findings": attempt.quality_findings,
                    "quality_evaluation": attempt.quality_evaluation,
                    "escalation_decision": attempt.escalation_decision,
                    "event_sequence": attempt.event_sequence,
                }
                for attempt in attempts
            ],
            "page_attempt_transition_events": [
                {
                    "id": str(event.id),
                    "attempt_id": str(event.attempt_id),
                    "sequence": event.sequence,
                    "previous_state": event.previous_state,
                    "current_state": event.current_state,
                    "reason": event.reason,
                    "payload": event.payload,
                }
                for event in attempt_events
            ],
            "blocks": [
                {
                    "id": str(block.id),
                    "page_id": str(block.page_id) if block.page_id else None,
                    "parent_block_id": (
                        str(block.parent_block_id) if block.parent_block_id else None
                    ),
                    "order": block.block_order,
                    "type": block.block_type,
                    "origin": block.origin,
                    "bbox1000": block.bbox1000,
                    "polygon_norm": block.polygon_norm,
                    "source_text": block.source_text,
                    "normalized_text": block.normalized_text,
                    "markdown": block.markdown,
                    "structured_content": block.structured_content,
                    "engine": block.engine,
                    "engine_revision": block.engine_revision,
                    "confidence": block.confidence,
                    "content_hash": block.content_hash,
                    "warnings": block.warnings,
                    "user_locked": block.user_locked,
                    "revision": block.revision,
                }
                for block in blocks
            ],
            "block_revisions": [
                {
                    "id": str(revision.id),
                    "block_id": str(revision.block_id),
                    "base_revision": revision.base_revision,
                    "new_revision": revision.new_revision,
                    "operation": revision.operation,
                    "base_value": revision.base_value,
                    "value": revision.value,
                    "actor_id": str(revision.actor_id),
                    "created_at": _iso(revision.created_at),
                }
                for revision in revisions
            ],
            "review_items": [
                {
                    "id": str(review.id),
                    "page_id": str(review.page_id) if review.page_id else None,
                    "block_id": str(review.block_id) if review.block_id else None,
                    "severity": review.severity,
                    "category": review.category,
                    "status": review.status,
                    "evidence": review.evidence,
                    "resolution": review.resolution,
                    "resolved_by": str(review.resolved_by) if review.resolved_by else None,
                    "resolved_at": _iso(review.resolved_at),
                    "created_at": _iso(review.created_at),
                }
                for review in reviews
            ],
            "semantic_classifications": [
                {
                    "id": str(classification.id),
                    "classification": classification.classification,
                    "provenance": classification.provenance,
                    "provider_key": classification.provider_key,
                    "model_revision": classification.model_revision,
                    "runtime_image_digest": classification.runtime_image_digest,
                    "adapter_version": classification.adapter_version,
                    "prompt_revision": classification.prompt_revision,
                    "schema_sha256": classification.schema_sha256,
                    "compile_input_sha256": classification.compile_input_sha256,
                    "is_active": classification.is_active,
                }
                for classification in semantic_classifications
            ],
            "knowledge_notes": [
                {
                    "id": str(note.id),
                    "stable_key": note.stable_key,
                    "title": note.title,
                    "note_type": note.note_type,
                    "content_markdown": note.content_markdown,
                    "metadata": note.metadata_json,
                    "evidence_block_ids": note.evidence_block_ids,
                    "content_origin": note.content_origin,
                    "review_status": note.review_status,
                    "compile_input_sha256": note.compile_input_sha256,
                    "pipeline_schema_sha256": note.pipeline_schema_sha256,
                    "model_revision": note.model_revision,
                    "compile_provenance": note.compile_provenance,
                    "is_active": note.is_active,
                }
                for note in knowledge_notes
            ],
            "relations": [
                {
                    "id": str(relation.id),
                    "source_relation_key": relation.source_relation_key,
                    "subject_id": relation.subject_id,
                    "predicate": relation.predicate,
                    "object_id": relation.object_id,
                    "assertion_status": relation.assertion_status,
                    "confidence": relation.confidence,
                    "evidence_block_ids": relation.evidence_block_ids,
                    "review_status": relation.review_status,
                    "compile_input_sha256": relation.compile_input_sha256,
                    "pipeline_schema_sha256": relation.pipeline_schema_sha256,
                    "model_revision": relation.model_revision,
                    "compile_provenance": relation.compile_provenance,
                    "is_active": relation.is_active,
                }
                for relation in relations
            ],
            "gpu_invocations": [
                {
                    "id": str(invocation.id),
                    "job_id": str(invocation.job_id),
                    "page_id": (str(invocation.page_id) if invocation.page_id else None),
                    "provider": invocation.provider,
                    "provider_key": invocation.provider_key,
                    "endpoint_id": invocation.endpoint_id,
                    "request_manifest_sha256": (invocation.request_manifest_sha256),
                    "status": invocation.status,
                    "input_sha256": invocation.input_sha256,
                    "model_revision": invocation.model_revision,
                    "runtime_image_digest": invocation.runtime_image_digest,
                    "adapter_version": invocation.adapter_version,
                    "transition_policy": invocation.transition_policy,
                    "parent_invocation_id": (
                        str(invocation.parent_invocation_id)
                        if invocation.parent_invocation_id is not None
                        else None
                    ),
                    "lineage_root_invocation_id": (
                        str(invocation.lineage_root_invocation_id)
                        if invocation.lineage_root_invocation_id is not None
                        else None
                    ),
                    "transition_category": invocation.transition_category,
                    "transition_strategy": invocation.transition_strategy,
                    "transition_action": invocation.transition_action,
                    "transition_attempt": invocation.transition_attempt,
                    "attempt_count": invocation.attempt_count,
                    "completion_source": invocation.completion_source,
                    "result_manifest_sha256": (invocation.result_manifest_sha256),
                    "last_error_code": invocation.last_error_code,
                }
                for invocation in gpu_invocations
            ],
        }
    )
    object_targets: set[tuple[str, str]] = set()
    for page in pages:
        if page.render_key:
            object_targets.add(("working", page.render_key))
        if page.thumbnail_key:
            object_targets.add(("derived", page.thumbnail_key))
    for asset in assets:
        bucket = str(asset.metadata_json.get("bucket", "derived"))
        if bucket not in {"working", "derived"}:
            bucket = "derived"
        object_targets.add((bucket, asset.storage_key))
    for invocation in gpu_invocations:
        if invocation.input_bucket == "derived":
            object_targets.add(("derived", invocation.input_object_key))
        object_targets.add(("derived", invocation.output_object_key))
    return DocumentVersionSnapshot(
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        page_count=len(pages),
        block_count=len(blocks),
        review_item_count=len(reviews),
        object_targets=tuple(sorted(object_targets)),
    )


async def archive_active_document_version(
    session: AsyncSession,
    *,
    store: ObjectStore,
    document: Document,
    now: datetime,
) -> DocumentVersionSnapshot:
    version = await session.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == document.tenant_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.version == document.active_version,
        )
        .with_for_update()
    )
    if version is None:
        raise ValueError("active document version record is unavailable")
    snapshot = await build_document_version_snapshot(
        session,
        document=document,
        version=version,
    )
    key = (
        f"tenants/{document.tenant_id}/projects/{document.project_id}/"
        f"documents/{document.id}/versions/v{version.version}/"
        f"cir-{snapshot.sha256}.json"
    )
    if version.cir_snapshot_sha256 is not None:
        if version.cir_snapshot_sha256 != snapshot.sha256 or version.cir_object_key != key:
            raise ValueError("immutable document version snapshot changed")
        persisted = await store.read_derived(key)
        if persisted != snapshot.payload:
            raise ValueError("persisted document version snapshot integrity mismatch")
        if version.archived_objects != [
            {"bucket": bucket, "object_key": object_key}
            for bucket, object_key in snapshot.object_targets
        ]:
            raise ValueError("immutable document version object manifest changed")
    else:
        await store.put_derived(key, snapshot.payload)
        version.cir_object_key = key
        version.cir_snapshot_sha256 = snapshot.sha256
        version.archived_objects = [
            {"bucket": bucket, "object_key": object_key}
            for bucket, object_key in snapshot.object_targets
        ]
    version.status = "archived"
    version.archived_at = now
    return snapshot


async def clear_active_document_projection(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    """Remove only the mutable current projection after its snapshot is durable."""

    await session.execute(
        update(DocumentSemanticClassification)
        .where(
            DocumentSemanticClassification.tenant_id == tenant_id,
            DocumentSemanticClassification.document_id == document_id,
            DocumentSemanticClassification.is_active.is_(True),
        )
        .values(is_active=False)
    )
    await session.execute(
        update(KnowledgeNote)
        .where(
            KnowledgeNote.tenant_id == tenant_id,
            KnowledgeNote.document_id == document_id,
            KnowledgeNote.is_active.is_(True),
        )
        .values(is_active=False)
    )
    await session.execute(
        update(Relation)
        .where(
            Relation.tenant_id == tenant_id,
            Relation.document_id == document_id,
            Relation.is_active.is_(True),
        )
        .values(is_active=False)
    )
    await session.execute(
        delete(ReviewItem).where(
            ReviewItem.tenant_id == tenant_id,
            ReviewItem.document_id == document_id,
        )
    )
    await session.execute(
        delete(Block).where(
            Block.tenant_id == tenant_id,
            Block.document_id == document_id,
        )
    )
    await session.execute(
        delete(Page).where(
            Page.tenant_id == tenant_id,
            Page.document_id == document_id,
        )
    )


def document_version_diff(
    older: DocumentVersion,
    newer: DocumentVersion,
) -> dict[str, Any]:
    if older.document_id != newer.document_id or older.tenant_id != newer.tenant_id:
        raise ValueError("cannot compare versions from different documents")
    if older.version >= newer.version:
        raise ValueError("document version diff must be ordered")
    fields = {
        "source_sha256": (older.source_sha256, newer.source_sha256),
        "cir_snapshot_sha256": (
            older.cir_snapshot_sha256,
            newer.cir_snapshot_sha256,
        ),
        "input_revision_hash": (
            older.input_revision_hash,
            newer.input_revision_hash,
        ),
        "policy_version": (older.policy_version, newer.policy_version),
        "model_revision": (older.model_revision, newer.model_revision),
        "prompt_revision": (older.prompt_revision, newer.prompt_revision),
        "normalization_revision": (
            older.normalization_revision,
            newer.normalization_revision,
        ),
        "akmp_schema_version": (
            older.akmp_schema_version,
            newer.akmp_schema_version,
        ),
    }
    return {
        "schema_version": "document-version-diff-1.0.0",
        "document_id": str(older.document_id),
        "from_version": older.version,
        "to_version": newer.version,
        "changes": {
            field: {"from": values[0], "to": values[1]}
            for field, values in fields.items()
            if values[0] != values[1]
        },
    }


async def read_public_document_version_snapshot(
    *,
    store: ObjectStore,
    version: DocumentVersion,
) -> dict[str, Any]:
    """Read, authenticate, and redact an archived snapshot for API delivery."""

    if (
        version.status != "archived"
        or not version.cir_object_key
        or not version.cir_snapshot_sha256
    ):
        raise ValueError("document version snapshot is not archived")
    payload = await store.read_derived(version.cir_object_key)
    if hashlib.sha256(payload).hexdigest() != version.cir_snapshot_sha256:
        raise ValueError("document version snapshot integrity mismatch")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("document version snapshot is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "document-version-snapshot-1.0.0"
        or value.get("document_id") != str(version.document_id)
        or value.get("document_version") != version.version
    ):
        raise ValueError("document version snapshot identity mismatch")
    source = value.get("source")
    if isinstance(source, dict):
        source.pop("storage_key", None)
    page_assets = value.get("page_assets")
    if isinstance(page_assets, list):
        for asset in page_assets:
            if isinstance(asset, dict):
                asset.pop("storage_key", None)
    pages = value.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if isinstance(page, dict):
                page.pop("thumbnail_key", None)
                page.pop("render_key", None)
    return value
