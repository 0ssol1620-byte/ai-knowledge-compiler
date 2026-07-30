"""Persistence-to-CIR bridge and deterministic production exporters."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from html import escape
from typing import Any

from akc_cir import (
    AssertionStatus,
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalTable,
    ContentLayer,
    ExportFile,
    ExportManifest,
    ExportProfile,
    KnowledgeBundle,
    KnowledgeNote,
    ModelRunRecord,
    NoteType,
    QualityReport,
    RelationAssertion,
    ReviewStatus,
    SourceRef,
)
from akc_exporters import (
    KNOWLEDGE_NOTE_SHACL,
    MarkdownExportOptions,
    adaptive_chunks,
    chunks_jsonl,
    compile_vault,
    context_jsonld,
    deterministic_zip,
    documents_jsonl,
    export_markdown,
    knowledge_jsonld,
    portable_slug,
    source_map_json,
    validate_internal_links,
)
from PIL import Image, UnidentifiedImageError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    Block,
    Document,
    DocumentSemanticClassification,
    Entity,
    Export,
    Page,
    PageAsset,
    Relation,
    ReviewItem,
    SourceFile,
)
from akc_api.models import (
    KnowledgeNote as StoredKnowledgeNote,
)
from akc_api.storage import ObjectStore

_BLOCK_TYPES = {item.value: item for item in BlockType}
_ORIGINS = {item.value: item for item in BlockOrigin}
_NOTE_TYPES = {item.value: item for item in NoteType}
_ASSERTION_STATUSES = {item.value: item for item in AssertionStatus}
_REVIEW_STATUSES = {item.value: item for item in ReviewStatus}
_CONTENT_LAYERS = {item.value: item for item in ContentLayer}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_HEX_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _sha256(value: str | None, fallback: str) -> str:
    digest = value or hashlib.sha256(fallback.encode("utf-8")).hexdigest()
    return digest if digest.startswith("sha256:") else f"sha256:{digest}"


def _visual_model_run(
    structured: dict[str, Any],
) -> ModelRunRecord:
    value = structured.get("modelRun")
    model_run_ids = structured.get("modelRunIds")
    if (
        structured.get("schemaVersion") != "akc-visual-block-1.0"
        or not isinstance(value, dict)
        or not isinstance(model_run_ids, list)
        or model_run_ids != [value.get("id")]
    ):
        raise ValueError("visual block has incomplete model-run attestation")
    required_hashes = (
        "promptSha256",
        "containerDigest",
        "requestManifestSha256",
        "resultManifestSha256",
        "inputSha256",
        "outputSha256",
    )
    if any(
        not isinstance(value.get(key), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get(key)))
        for key in required_hashes
    ):
        raise ValueError("visual block has invalid model-run hashes")
    if (
        value.get("artifactContract") != "akc-visual-page-1.0.0"
        or value.get("schemaProfile") != "canonical-page-1.0"
        or value.get("runtime") != "serverless_gpu"
        or value.get("hardware") != "gpu"
        or value.get("runtimeVersion") != value.get("adapterVersion")
    ):
        raise ValueError("visual block has inconsistent model-run attestation")
    try:
        return ModelRunRecord(
            id=str(value["id"]),
            provider=str(value["provider"]),
            model=str(value["model"]),
            revision=str(value["revision"]),
            runtime=str(value["runtime"]),
            runtime_version=str(value["runtimeVersion"]),
            prompt_sha256=str(value["promptSha256"]),
            hardware=str(value["hardware"]),
            container_digest=str(value["containerDigest"]),
            route_profile=str(value["routeProfile"]),
            started_at=datetime.fromisoformat(str(value["startedAt"])),
            completed_at=datetime.fromisoformat(str(value["completedAt"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("visual block has invalid model-run attestation") from exc


def _block_type(row: Block) -> BlockType:
    value = row.block_type.casefold()
    if value == "text":
        return BlockType.PARAGRAPH
    candidate = _BLOCK_TYPES.get(value, BlockType.UNKNOWN)
    structured = row.structured_content or {}
    # A table without a structured cell grid is retained as text rather than
    # falsely asserting that the canonical table contract was satisfied.
    if candidate == BlockType.TABLE and not structured.get("table"):
        return BlockType.PARAGRAPH
    if candidate == BlockType.FORMULA and not (
        structured.get("formulaLatex") or structured.get("latex")
    ):
        return BlockType.PARAGRAPH
    return candidate


def _content_layer(origin: BlockOrigin) -> ContentLayer:
    if origin in {BlockOrigin.AI_SUMMARIZED, BlockOrigin.AI_INFERRED}:
        return ContentLayer.KNOWLEDGE
    if origin in {BlockOrigin.RULE_RECONSTRUCTED, BlockOrigin.AI_RECONSTRUCTED}:
        return ContentLayer.STRUCTURED
    return ContentLayer.EXTRACTED


def _semantic_frontmatter(document: CanonicalDocument) -> dict[str, Any]:
    value = document.metadata.get("semanticClassification")
    if not isinstance(value, dict):
        return {}
    attestation = value.get("attestation")
    return {
        "semantic_type": (str(value["documentType"]) if value.get("documentType") else None),
        "topics": tuple(value.get("topics") or value.get("secondaryTypes") or ()),
        "domains": tuple(value.get("domain") or ()),
        "semantic_evidence_block_ids": tuple(value.get("evidenceBlockIds") or ()),
        "semantic_model_attestation": (
            {str(key): str(item) for key, item in attestation.items()}
            if isinstance(attestation, dict)
            else {}
        ),
    }


def _validated_compile_provenance(value: Any) -> dict[str, Any]:
    required = {
        "compile_input_sha256",
        "pipeline_schema_sha256",
        "prompt_revision",
        "model_revision",
        "runtime_image_digest",
        "adapter_version",
        "provider_key",
        "invocations",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("knowledge compile provenance is incomplete")
    for field in (
        "compile_input_sha256",
        "pipeline_schema_sha256",
        "prompt_revision",
        "model_revision",
        "runtime_image_digest",
    ):
        item = value.get(field)
        if not isinstance(item, str) or not _HEX_SHA256.fullmatch(item):
            raise ValueError("knowledge compile provenance hash is invalid")
    if not value.get("adapter_version") or not value.get("provider_key"):
        raise ValueError("knowledge compile model attestation is incomplete")
    invocations = value.get("invocations")
    if not isinstance(invocations, list) or not invocations:
        raise ValueError("knowledge compile invocation provenance is missing")
    for invocation in invocations:
        if not isinstance(invocation, dict) or set(invocation) != {
            "invocation_id",
            "stage",
            "unit_id",
            "input_sha256",
            "output_sha256",
            "request_manifest_sha256",
            "result_manifest_sha256",
        }:
            raise ValueError("knowledge compile invocation provenance is invalid")
        try:
            uuid.UUID(str(invocation["invocation_id"]))
        except ValueError as exc:
            raise ValueError("knowledge compile invocation ID is invalid") from exc
        if (
            invocation.get("stage") not in {"A", "B", "C", "D"}
            or not invocation.get("unit_id")
            or any(
                not isinstance(invocation.get(field), str)
                or not _HEX_SHA256.fullmatch(invocation[field])
                for field in (
                    "input_sha256",
                    "output_sha256",
                    "request_manifest_sha256",
                    "result_manifest_sha256",
                )
            )
        ):
            raise ValueError("knowledge compile invocation provenance is invalid")
    return value


def _has_attested_compile_revision(value: Any) -> bool:
    identity = (
        value.compile_input_sha256,
        value.pipeline_schema_sha256,
        value.model_revision,
    )
    provenance = value.compile_provenance
    if not any(item is not None for item in identity) and not provenance:
        return False
    if not all(isinstance(item, str) and item for item in identity) or not provenance:
        raise ValueError("knowledge compile revision identity is incomplete")
    return True


async def build_canonical_document(
    session: AsyncSession, export: Export
) -> tuple[CanonicalDocument, KnowledgeBundle]:
    if export.document_id is None:
        raise ValueError("document-scoped export is required")
    document = await session.scalar(
        select(Document).where(
            Document.tenant_id == export.tenant_id,
            Document.id == export.document_id,
        )
    )
    if document is None or document.source_file_id is None:
        raise ValueError("export document source is unavailable")
    semantic_row = await session.scalar(
        select(DocumentSemanticClassification).where(
            DocumentSemanticClassification.tenant_id == export.tenant_id,
            DocumentSemanticClassification.document_id == document.id,
            DocumentSemanticClassification.document_version == document.active_version,
            DocumentSemanticClassification.is_active.is_(True),
        )
    )
    source = await session.scalar(
        select(SourceFile).where(
            SourceFile.tenant_id == export.tenant_id,
            SourceFile.id == document.source_file_id,
        )
    )
    if source is None:
        raise ValueError("export source file is unavailable")
    pages = {
        page.id: page
        for page in (
            await session.scalars(
                select(Page).where(
                    Page.tenant_id == export.tenant_id,
                    Page.document_id == document.id,
                )
            )
        ).all()
    }
    rows = list(
        (
            await session.scalars(
                select(Block)
                .where(
                    Block.tenant_id == export.tenant_id,
                    Block.document_id == document.id,
                )
                .order_by(Block.block_order, Block.id)
            )
        ).all()
    )
    version_id = f"{document.id}:v{document.active_version}"
    canonical_blocks: list[CanonicalBlock] = []
    model_runs: dict[str, ModelRunRecord] = {}
    for block_row in rows:
        if block_row.page_id is None:
            raise ValueError(f"block {block_row.id} has no persisted page provenance")
        page = pages.get(block_row.page_id)
        if page is None:
            raise ValueError(f"block {block_row.id} has no persisted page provenance")
        bbox = None
        if block_row.bbox1000:
            coordinates = tuple(block_row.bbox1000)
            if len(coordinates) != 4:
                raise ValueError(f"block {block_row.id} has an invalid bbox1000")
            bbox = BBox1000((coordinates[0], coordinates[1], coordinates[2], coordinates[3]))
        origin = _ORIGINS.get(block_row.origin, BlockOrigin.RULE_RECONSTRUCTED)
        block_type = _block_type(block_row)
        structured = block_row.structured_content or {}
        native_structured = structured.get("schemaVersion") == "akc-native-block-1.0"
        visual_structured = structured.get("schemaVersion") == "akc-visual-block-1.0"
        formula = None
        if block_type == BlockType.FORMULA:
            formula_value = structured.get("formulaLatex") or structured.get("latex")
            formula = str(formula_value) if formula_value else None
        table = None
        if block_type == BlockType.TABLE:
            table_value = structured.get("table")
            if not isinstance(table_value, dict):
                raise ValueError(f"block {block_row.id} has invalid canonical table content")
            table = CanonicalTable.model_validate(table_value)
        block_model_run_ids: tuple[str, ...] = ()
        if native_structured or visual_structured:
            source_ref_values = structured.get("sourceRefs")
            if not isinstance(source_ref_values, list) or not source_ref_values:
                raise ValueError(f"block {block_row.id} has no structured source references")
            source_refs = tuple(
                SourceRef.model_validate(source_ref) for source_ref in source_ref_values
            )
            if any(
                source_ref.document_id != str(document.id)
                or source_ref.document_version_id != version_id
                or source_ref.page_number1 != page.page_number
                for source_ref in source_refs
            ):
                raise ValueError(f"block {block_row.id} has inconsistent native provenance")
            content_layer = _CONTENT_LAYERS.get(
                str(structured.get("contentLayer")),
                ContentLayer.STRUCTURED,
            )
            sanitized_html_value = structured.get("sanitizedHtml")
            sanitized_html = str(sanitized_html_value) if sanitized_html_value is not None else None
            if visual_structured:
                model_run = _visual_model_run(structured)
                existing_run = model_runs.get(model_run.id)
                if existing_run is not None and existing_run != model_run:
                    raise ValueError("visual model-run identity has conflicting attestation")
                model_runs[model_run.id] = model_run
                block_model_run_ids = (model_run.id,)
        else:
            source_refs = (
                SourceRef(
                    document_id=str(document.id),
                    document_version_id=version_id,
                    page_index0=page.page_number - 1,
                    page_number1=page.page_number,
                    bbox1000=bbox,
                ),
            )
            content_layer = _content_layer(origin)
            sanitized_html = None
        canonical_blocks.append(
            CanonicalBlock(
                id=str(block_row.id),
                parent_id=(str(block_row.parent_block_id) if block_row.parent_block_id else None),
                order=block_row.block_order,
                type=block_type,
                content_layer=content_layer,
                raw_text=block_row.source_text,
                normalized_text=block_row.normalized_text,
                markdown=block_row.markdown,
                sanitized_html=sanitized_html,
                table=table,
                formula_latex=formula,
                origin=origin,
                source_refs=source_refs,
                model_run_ids=block_model_run_ids,
                confidence=block_row.confidence,
                quality_flags=tuple(block_row.warnings),
                content_hash=_sha256(
                    block_row.content_hash,
                    block_row.markdown or block_row.normalized_text or "",
                ),
                revision=block_row.revision,
            )
        )
    document_metadata: dict[str, Any] = {
        "documentType": document.document_type,
        "languageCodes": document.language_codes,
        "activeVersion": document.active_version,
    }
    if semantic_row is not None:
        semantic_provenance = semantic_row.provenance
        if (
            not isinstance(semantic_provenance, dict)
            or semantic_provenance.get("artifact_contract") != "akc-knowledge-pipeline-stage-1.0.0"
            or not isinstance(semantic_provenance.get("invocations"), list)
            or not semantic_provenance["invocations"]
        ):
            raise ValueError("semantic classification provenance is incomplete")
        document_metadata["semanticClassification"] = {
            **semantic_row.classification,
            "attestation": {
                "providerKey": semantic_row.provider_key,
                "modelRevision": semantic_row.model_revision,
                "runtimeImageDigest": semantic_row.runtime_image_digest,
                "adapterVersion": semantic_row.adapter_version,
                "promptRevision": semantic_row.prompt_revision,
                "schemaSha256": semantic_row.schema_sha256,
            },
            "provenance": semantic_provenance,
        }
    for page in sorted(pages.values(), key=lambda value: value.page_number):
        native_structure = page.preflight_metrics.get("native_structure")
        if not isinstance(native_structure, dict):
            continue
        native_metadata = native_structure.get("documentMetadata")
        if isinstance(native_metadata, dict):
            document_metadata.update(native_metadata)
            break
    canonical_values: dict[str, Any] = {}
    if document.cir_schema_version.startswith("cir-"):
        canonical_values["schema_version"] = document.cir_schema_version
    canonical = CanonicalDocument(
        **canonical_values,
        tenant_id=str(document.tenant_id),
        document_id=str(document.id),
        document_version_id=version_id,
        title=document.title,
        source_filename=source.safe_filename,
        source_sha256=_sha256(source.sha256, source.safe_filename),
        content_layer=ContentLayer.STRUCTURED,
        blocks=tuple(canonical_blocks),
        model_runs=tuple(model_runs[key] for key in sorted(model_runs)),
        metadata=document_metadata,
        created_at=_aware(document.created_at),
    )
    stored_notes = list(
        (
            await session.scalars(
                select(StoredKnowledgeNote)
                .where(
                    StoredKnowledgeNote.tenant_id == export.tenant_id,
                    StoredKnowledgeNote.project_id == export.project_id,
                    or_(
                        StoredKnowledgeNote.document_id == document.id,
                        StoredKnowledgeNote.document_id.is_(None),
                    ),
                    or_(
                        StoredKnowledgeNote.document_version == document.active_version,
                        StoredKnowledgeNote.document_version.is_(None),
                    ),
                    StoredKnowledgeNote.is_active.is_(True),
                )
                .order_by(StoredKnowledgeNote.stable_key)
            )
        ).all()
    )
    available = {block.id for block in canonical.blocks}
    notes: list[KnowledgeNote] = []
    compile_provenance: dict[str, Any] | None = None
    compile_provenance_json: str | None = None
    for note_row in stored_notes:
        if _has_attested_compile_revision(note_row):
            note_provenance = _validated_compile_provenance(note_row.compile_provenance)
            serialized = json.dumps(
                note_provenance,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if compile_provenance_json is not None and serialized != compile_provenance_json:
                raise ValueError("active knowledge notes have mixed provenance")
            compile_provenance = note_provenance
            compile_provenance_json = serialized
        evidence = tuple(
            block_id for block_id in note_row.evidence_block_ids if block_id in available
        )
        if note_row.document_id is not None and len(evidence) != len(note_row.evidence_block_ids):
            raise ValueError("active knowledge note evidence is stale")
        if not evidence:
            continue
        notes.append(
            KnowledgeNote(
                note_id=str(note_row.id),
                title=note_row.title,
                note_type=_NOTE_TYPES.get(note_row.note_type, NoteType.CONCEPT),
                content_origin=_ORIGINS.get(
                    note_row.content_origin,
                    BlockOrigin.AI_SUMMARIZED,
                ),
                evidence_block_ids=evidence,
                summary=note_row.content_markdown,
                claims=(),
                review_status=(
                    ReviewStatus.USER_VERIFIED
                    if note_row.review_status == "user_verified"
                    else ReviewStatus.PENDING
                ),
            )
        )
    stored_relations = list(
        (
            await session.scalars(
                select(Relation)
                .where(
                    Relation.tenant_id == export.tenant_id,
                    Relation.project_id == export.project_id,
                    or_(
                        Relation.document_id == document.id,
                        Relation.document_id.is_(None),
                    ),
                    or_(
                        Relation.document_version == document.active_version,
                        Relation.document_version.is_(None),
                    ),
                    Relation.is_active.is_(True),
                )
                .order_by(Relation.id)
            )
        ).all()
    )
    relations: list[RelationAssertion] = []
    for relation_row in stored_relations:
        if _has_attested_compile_revision(relation_row):
            relation_provenance = _validated_compile_provenance(relation_row.compile_provenance)
            serialized = json.dumps(
                relation_provenance,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if compile_provenance_json is not None and serialized != compile_provenance_json:
                raise ValueError("active knowledge relations have mixed provenance")
            compile_provenance = relation_provenance
            compile_provenance_json = serialized
        evidence = tuple(
            block_id for block_id in relation_row.evidence_block_ids if block_id in available
        )
        if relation_row.document_id is not None and len(evidence) != len(
            relation_row.evidence_block_ids
        ):
            raise ValueError("active knowledge relation evidence is stale")
        assertion_status = _ASSERTION_STATUSES.get(relation_row.assertion_status)
        review_status = _REVIEW_STATUSES.get(relation_row.review_status, ReviewStatus.PENDING)
        if not evidence or assertion_status is None or relation_row.confidence is None:
            # A relation without document-local evidence or calibrated confidence
            # is not safe to publish as an assertion.
            continue
        relations.append(
            RelationAssertion(
                id=str(relation_row.id),
                subject=relation_row.subject_id,
                predicate=relation_row.predicate,
                object=relation_row.object_id,
                assertion_status=assertion_status,
                confidence=relation_row.confidence,
                evidence_block_ids=evidence,
                review_status=review_status,
            )
        )
    bundle = KnowledgeBundle(
        document_id=str(document.id),
        notes=tuple(notes),
        relations=tuple(relations),
    )
    if compile_provenance is not None:
        canonical = canonical.model_copy(
            update={
                "metadata": {
                    **canonical.metadata,
                    "knowledgeCompileProvenance": compile_provenance,
                }
            }
        )
    return canonical, bundle


def _bounded_score(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    if numeric != numeric:
        return None
    return min(1.0, max(0.0, numeric))


async def _build_quality_report(
    session: AsyncSession,
    export: Export,
    document: CanonicalDocument,
) -> QualityReport:
    pages = list(
        (
            await session.scalars(
                select(Page)
                .where(
                    Page.tenant_id == export.tenant_id,
                    Page.document_id == export.document_id,
                )
                .order_by(Page.page_number)
            )
        ).all()
    )
    review_items = list(
        (
            await session.scalars(
                select(ReviewItem)
                .where(
                    ReviewItem.tenant_id == export.tenant_id,
                    ReviewItem.document_id == export.document_id,
                    ReviewItem.status == "open",
                )
                .order_by(ReviewItem.severity, ReviewItem.category, ReviewItem.id)
            )
        ).all()
    )

    confidence_values = [
        score
        for block in document.blocks
        if (score := _bounded_score(block.confidence)) is not None
    ]
    text_score = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    provenance_score = (
        sum(bool(block.source_refs) for block in document.blocks) / len(document.blocks)
        if document.blocks
        else 0.0
    )
    persisted_page_scores = [
        score
        for page in pages
        for candidate in (
            page.quality_metrics.get("overall_score"),
            page.quality_metrics.get("quality_score"),
        )
        if (score := _bounded_score(candidate)) is not None
    ]
    page_score = (
        sum(persisted_page_scores) / len(persisted_page_scores)
        if persisted_page_scores
        else text_score
    )
    weighted_open = sum(
        {
            "critical": 1.0,
            "high": 0.6,
            "medium": 0.25,
            "low": 0.1,
            "info": 0.05,
        }.get(item.severity.casefold(), 0.25)
        for item in review_items
    )
    review_score = max(0.0, 1.0 - weighted_open / max(1, len(document.blocks)))
    component_scores = {
        "page_quality": round(page_score, 6),
        "provenance_coverage": round(provenance_score, 6),
        "review_readiness": round(review_score, 6),
        "text_confidence": round(text_score, 6),
    }
    overall_score = round(min(component_scores.values()), 6)
    requires_review = any(item.severity.casefold() in {"critical", "high"} for item in review_items)
    if requires_review:
        status = "REVIEW_REQUIRED"
    elif overall_score >= 0.85 and not review_items:
        status = "PASS"
    else:
        status = "WARN"
    findings = tuple(
        {
            "id": str(item.id),
            "severity": item.severity,
            "category": item.category,
            "page_id": str(item.page_id) if item.page_id else None,
            "block_id": str(item.block_id) if item.block_id else None,
            "evidence": item.evidence,
        }
        for item in sorted(
            review_items,
            key=lambda item: (
                _SEVERITY_ORDER.get(item.severity.casefold(), 99),
                item.category,
                str(item.id),
            ),
        )
    )
    return QualityReport(
        document_id=document.document_id,
        overall_score=overall_score,
        status=status,
        component_scores=component_scores,
        findings=findings,
        review_item_count=len(review_items),
    )


def _quality_html(report: QualityReport) -> str:
    rows = "".join(
        (
            "<tr>"
            f'<th scope="row">{escape(name.replace("_", " ").title())}</th>'
            f"<td>{score:.4f}</td>"
            "</tr>"
        )
        for name, score in sorted(report.component_scores.items())
    )
    findings = "".join(
        (
            "<li>"
            f"<strong>{escape(str(item.get('severity', 'unknown')).upper())}</strong> "
            f"{escape(str(item.get('category', 'unspecified')))}"
            "</li>"
        )
        for item in report.findings
    )
    if not findings:
        findings = "<li>No open review findings.</li>"
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'\">"
        "<title>Quality report</title>"
        "<style>"
        "body{font:16px/1.5 system-ui,sans-serif;max-width:56rem;margin:3rem auto;"
        "padding:0 1rem;color:#17202a}table{border-collapse:collapse;width:100%}"
        "th,td{border-bottom:1px solid #d5d8dc;padding:.65rem;text-align:left}"
        ".score{font-size:2rem;font-weight:700}small{color:#566573}"
        "</style></head><body>"
        "<main>"
        "<h1>Quality report</h1>"
        f"<p><small>Document {escape(report.document_id)}</small></p>"
        f'<p class="score">{report.overall_score:.4f} · {escape(report.status)}</p>'
        f"<table><tbody>{rows}</tbody></table>"
        f"<h2>Open review findings ({report.review_item_count})</h2><ul>{findings}</ul>"
        "</main></body></html>\n"
    )


async def _knowledge_jsonl_files(
    session: AsyncSession,
    export: Export,
    document: CanonicalDocument,
    knowledge: KnowledgeBundle,
) -> dict[str, bytes]:
    available = {block.id for block in document.blocks}
    stored_entities = list(
        (
            await session.scalars(
                select(Entity)
                .where(
                    Entity.tenant_id == export.tenant_id,
                    Entity.project_id == export.project_id,
                )
                .order_by(Entity.stable_key, Entity.id)
            )
        ).all()
    )
    entity_lines = [
        json.dumps(
            {
                "id": str(entity.id),
                "stable_key": entity.stable_key,
                "entity_type": entity.entity_type,
                "label": entity.label,
                "evidence_block_ids": evidence,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for entity in stored_entities
        if (
            evidence := sorted(
                block_id for block_id in entity.evidence_block_ids if block_id in available
            )
        )
    ]
    relation_lines = [
        json.dumps(
            relation.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for relation in sorted(knowledge.relations, key=lambda value: value.id)
    ]
    return {
        "knowledge/entities.jsonl": (
            ("\n".join(entity_lines) + ("\n" if entity_lines else "")).encode("utf-8")
        ),
        "knowledge/relations.jsonl": (
            ("\n".join(relation_lines) + ("\n" if relation_lines else "")).encode("utf-8")
        ),
    }


def _media_type(path: str) -> str:
    suffix = path.rsplit(".", 1)[-1].casefold() if "." in path else ""
    return {
        "csv": "text/csv",
        "html": "text/html",
        "json": "application/json",
        "jsonld": "application/ld+json",
        "jsonl": "application/x-ndjson",
        "md": "text/markdown",
        "png": "image/png",
        "tex": "application/x-tex",
        "ttl": "text/turtle",
    }.get(suffix, "application/octet-stream")


def _manifest_profile(profiles: Sequence[str]) -> ExportProfile:
    unique = tuple(dict.fromkeys(profiles))
    if len(unique) != 1:
        return ExportProfile.BUNDLE
    return {
        "portable": ExportProfile.PORTABLE_STRUCTURED,
        "obsidian": ExportProfile.OBSIDIAN,
        "rag": ExportProfile.RAG,
        "jsonld": ExportProfile.JSON_LD,
    }[unique[0]]


def _export_model_provenance(document: CanonicalDocument) -> dict[str, Any]:
    result: dict[str, Any] = {}
    compile_value = document.metadata.get("knowledgeCompileProvenance")
    if isinstance(compile_value, dict):
        result["knowledge_compile"] = compile_value
    semantic = document.metadata.get("semanticClassification")
    if isinstance(semantic, dict):
        result["semantic_classification"] = {
            "attestation": semantic.get("attestation"),
            "provenance": semantic.get("provenance"),
        }
    if document.model_runs:
        result["model_runs"] = [
            model_run.model_dump(mode="json", by_alias=True, exclude_none=True)
            for model_run in sorted(document.model_runs, key=lambda value: value.id)
        ]
    return result


def _add_manifest(
    files: dict[str, bytes],
    profiles: list[str],
    *,
    export: Export,
    document: CanonicalDocument,
    generated_at: datetime,
    warnings: Sequence[str],
) -> None:
    manifest = ExportManifest(
        export_id=str(export.id),
        tenant_id=str(export.tenant_id),
        project_id=str(export.project_id),
        document_id=document.document_id,
        document_version_id=document.document_version_id,
        profile=_manifest_profile(profiles),
        source_sha256=document.source_sha256,
        generated_at=generated_at,
        model_provenance=_export_model_provenance(document),
        files=tuple(
            ExportFile(
                path=path,
                media_type=_media_type(path),
                sha256=f"sha256:{hashlib.sha256(content).hexdigest()}",
                size_bytes=len(content),
            )
            for path, content in sorted(files.items())
        ),
        warnings=tuple(sorted(set(warnings))),
    )
    files["manifest.json"] = (
        json.dumps(
            manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _normalized_sha256(value: str) -> str:
    return value.removeprefix("sha256:").casefold()


def _verified_page_image(payload: bytes, asset: PageAsset) -> Image.Image:
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != _normalized_sha256(asset.sha256):
        raise ValueError(f"page asset integrity mismatch: {asset.id}")
    expected_size = asset.metadata_json.get("size_bytes")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size != len(payload)
    ):
        raise ValueError(f"page asset size attestation mismatch: {asset.id}")
    content_type = asset.metadata_json.get("content_type")
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError(f"unsupported page asset media type: {asset.id}")
    try:
        with Image.open(io.BytesIO(payload)) as candidate:
            candidate.verify()
        with Image.open(io.BytesIO(payload)) as candidate:
            candidate.load()
            image = candidate.convert("RGBA" if candidate.mode == "RGBA" else "RGB")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"invalid page image asset: {asset.id}") from exc
    expected_width = asset.metadata_json.get("width")
    expected_height = asset.metadata_json.get("height")
    if (
        not isinstance(expected_width, int)
        or isinstance(expected_width, bool)
        or not isinstance(expected_height, int)
        or isinstance(expected_height, bool)
        or image.size != (expected_width, expected_height)
    ):
        raise ValueError(f"page asset dimension attestation mismatch: {asset.id}")
    return image


async def _build_figure_assets(
    session: AsyncSession,
    export: Export,
    document: CanonicalDocument,
    object_store: ObjectStore | None,
) -> tuple[dict[str, bytes], dict[str, str]]:
    figure_blocks = [block for block in document.blocks if block.type == BlockType.FIGURE]
    if not figure_blocks or object_store is None:
        return {}, {}
    pages = list(
        (
            await session.scalars(
                select(Page)
                .where(
                    Page.tenant_id == export.tenant_id,
                    Page.document_id == export.document_id,
                )
                .order_by(Page.page_number)
            )
        ).all()
    )
    pages_by_number = {page.page_number: page for page in pages}
    page_ids = [page.id for page in pages]
    assets = (
        list(
            (
                await session.scalars(
                    select(PageAsset)
                    .where(
                        PageAsset.tenant_id == export.tenant_id,
                        PageAsset.page_id.in_(page_ids),
                        PageAsset.asset_type.in_(
                            (
                                "inference_raster",
                                "visual_ocr_raster",
                                "page_raster",
                                "preview",
                            )
                        ),
                    )
                    .order_by(PageAsset.created_at.desc(), PageAsset.id.desc())
                )
            ).all()
        )
        if page_ids
        else []
    )
    priority = {
        "inference_raster": 0,
        "visual_ocr_raster": 1,
        "page_raster": 2,
        "preview": 3,
    }
    assets.sort(
        key=lambda asset: (
            priority.get(asset.asset_type, 99),
            -asset.created_at.timestamp(),
            str(asset.id),
        )
    )
    asset_by_page: dict[Any, PageAsset] = {}
    for candidate_asset in assets:
        asset_by_page.setdefault(candidate_asset.page_id, candidate_asset)

    decoded_pages: dict[Any, Image.Image] = {}
    files: dict[str, bytes] = {}
    paths: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for block in sorted(figure_blocks, key=lambda value: (value.order, value.id)):
        source_ref = next(
            (candidate for candidate in block.source_refs if candidate.bbox1000 is not None),
            None,
        )
        if source_ref is None:
            records.append({"block_id": block.id, "status": "unavailable", "reason": "no_bbox"})
            continue
        bbox1000 = source_ref.bbox1000
        if bbox1000 is None:
            records.append({"block_id": block.id, "status": "unavailable", "reason": "no_bbox"})
            continue
        page = pages_by_number.get(source_ref.page_number1)
        selected_asset = asset_by_page.get(page.id) if page is not None else None
        if page is None or selected_asset is None:
            records.append(
                {
                    "block_id": block.id,
                    "page_number1": source_ref.page_number1,
                    "status": "unavailable",
                    "reason": "no_verified_page_raster",
                }
            )
            continue
        image = decoded_pages.get(page.id)
        if image is None:
            payload = await object_store.read_derived(selected_asset.storage_key)
            image = _verified_page_image(payload, selected_asset)
            decoded_pages[page.id] = image
        x1, y1, x2, y2 = bbox1000.root
        left = max(0, min(image.width - 1, math.floor(image.width * x1 / 1000)))
        top = max(0, min(image.height - 1, math.floor(image.height * y1 / 1000)))
        right = max(left + 1, min(image.width, math.ceil(image.width * x2 / 1000)))
        bottom = max(top + 1, min(image.height, math.ceil(image.height * y2 / 1000)))
        crop = image.crop((left, top, right, bottom))
        output = io.BytesIO()
        crop.save(output, format="PNG", optimize=False, compress_level=9)
        content = output.getvalue()
        path = f"assets/figures/{portable_slug(block.id)}.png"
        if path in files and files[path] != content:
            raise ValueError(f"figure asset path collision: {path}")
        files[path] = content
        paths[block.id] = f"../{path}"
        records.append(
            {
                "block_id": block.id,
                "page_number1": source_ref.page_number1,
                "bbox1000": list(bbox1000.root),
                "source_asset_id": str(selected_asset.id),
                "source_asset_sha256": _normalized_sha256(selected_asset.sha256),
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "status": "available",
            }
        )
    if records:
        files["assets/figures/manifest.json"] = (
            json.dumps(
                {"schema_version": "1.0", "figures": records},
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    return files, paths


async def build_export_bundle(
    session: AsyncSession,
    export: Export,
    *,
    profiles: Sequence[str] | None = None,
    object_store: ObjectStore | None = None,
) -> tuple[bytes, str]:
    """Compile one or more AKMP profiles into a byte-reproducible ZIP."""

    selected = list(profiles) if profiles else [export.export_type]
    unsupported = sorted(set(selected) - {"portable", "obsidian", "rag", "jsonld"})
    if unsupported:
        raise ValueError(f"unsupported export profiles: {unsupported}")
    document, knowledge = await build_canonical_document(session, export)
    files: dict[str, bytes] = {}
    figure_files, figure_paths = await _build_figure_assets(
        session,
        export,
        document,
        object_store,
    )
    files.update(figure_files)
    processed_at = _aware(export.created_at)
    quality_report = await _build_quality_report(session, export, document)
    quality_path = f"quality/{document.document_id}"
    files[f"{quality_path}.json"] = (
        json.dumps(
            quality_report.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    files[f"{quality_path}.html"] = _quality_html(quality_report).encode("utf-8")

    if "portable" in selected:
        portable_artifact = export_markdown(
            document,
            MarkdownExportOptions(
                profile=ExportProfile.PORTABLE_STRUCTURED,
                document_type=str(document.metadata.get("documentType", "other")),
                **_semantic_frontmatter(document),
                language=(
                    str(document.metadata.get("languageCodes", ["unknown"])[0])
                    if document.metadata.get("languageCodes")
                    else "unknown"
                ),
                languages=tuple(document.metadata.get("languageCodes") or ["unknown"]),
                review_status=ReviewStatus.AUTO_WITH_WARNINGS,
                model_policy="parse_balanced_v1",
                processed_at=processed_at,
                include_ai_knowledge=False,
                wikilinks=False,
                quality_score=quality_report.overall_score,
                figure_asset_paths=figure_paths,
            ),
        )
        files[portable_artifact.path] = portable_artifact.markdown.encode("utf-8")
        files[f"source-map/{document.document_id}.json"] = source_map_json(
            portable_artifact.source_map
        ).encode("utf-8")
        for path, content in portable_artifact.table_assets.items():
            files[path.removeprefix("../")] = content.encode("utf-8")
        for path, content in portable_artifact.supplemental_assets.items():
            files[path.removeprefix("../")] = content.encode("utf-8")

        raw_path = (
            portable_artifact.path.removesuffix(".md") + ".raw.md"
            if portable_artifact.path.endswith(".md")
            else portable_artifact.path + ".raw"
        )
        raw_artifact = export_markdown(
            document,
            MarkdownExportOptions(
                profile=ExportProfile.PORTABLE_RAW,
                document_type=str(document.metadata.get("documentType", "other")),
                **_semantic_frontmatter(document),
                language=(
                    str(document.metadata.get("languageCodes", ["unknown"])[0])
                    if document.metadata.get("languageCodes")
                    else "unknown"
                ),
                languages=tuple(document.metadata.get("languageCodes") or ["unknown"]),
                review_status=ReviewStatus.AUTO_WITH_WARNINGS,
                model_policy="parse_balanced_v1",
                processed_at=processed_at,
                include_ai_knowledge=False,
                wikilinks=False,
                quality_score=quality_report.overall_score,
                provenance_file=f"../source-map/{document.document_id}.raw.json",
                figure_asset_paths=figure_paths,
            ),
            output_path=raw_path,
        )
        files[raw_artifact.path] = raw_artifact.markdown.encode("utf-8")
        files[f"source-map/{document.document_id}.raw.json"] = source_map_json(
            raw_artifact.source_map
        ).encode("utf-8")
        for path, content in raw_artifact.table_assets.items():
            normalized = path.removeprefix("../")
            encoded = content.encode("utf-8")
            previous = files.get(normalized)
            if previous is not None and previous != encoded:
                raise ValueError(f"portable table asset collision: {normalized}")
            files[normalized] = encoded
        for path, content in raw_artifact.supplemental_assets.items():
            normalized = path.removeprefix("../")
            encoded = content.encode("utf-8")
            previous = files.get(normalized)
            if previous is not None and previous != encoded:
                raise ValueError(f"portable supplemental asset collision: {normalized}")
            files[normalized] = encoded

    if "obsidian" in selected:
        obsidian_artifact = export_markdown(
            document,
            MarkdownExportOptions(
                profile=ExportProfile.OBSIDIAN,
                document_type=str(document.metadata.get("documentType", "other")),
                **_semantic_frontmatter(document),
                language=(
                    str(document.metadata.get("languageCodes", ["unknown"])[0])
                    if document.metadata.get("languageCodes")
                    else "unknown"
                ),
                languages=tuple(document.metadata.get("languageCodes") or ["unknown"]),
                review_status=ReviewStatus.AUTO_WITH_WARNINGS,
                model_policy="parse_balanced_v1",
                processed_at=processed_at,
                include_ai_knowledge=False,
                wikilinks=True,
                quality_score=quality_report.overall_score,
                figure_asset_paths=figure_paths,
            ),
        )
        vault_files = compile_vault(
            document,
            obsidian_artifact,
            quality_report=quality_report,
            knowledge_bundle=knowledge,
            wikilinks=True,
            binary_assets=figure_files,
        )
        broken = validate_internal_links(vault_files)
        if broken:
            raise ValueError(f"generated Vault contains broken links: {broken}")
        files.update({f"obsidian/{path}": value for path, value in vault_files.items()})

    if "rag" in selected:
        chunks = adaptive_chunks(document, language="unknown")
        files["rag/chunks.jsonl"] = chunks_jsonl(chunks).encode("utf-8")
        files["rag/documents.jsonl"] = documents_jsonl(document).encode("utf-8")

    if "jsonld" in selected:
        files["knowledge/graph.jsonld"] = knowledge_jsonld(
            document,
            knowledge,
        ).encode("utf-8")
        files["linked-data/context-v1.jsonld"] = context_jsonld().encode("utf-8")
        files["linked-data/knowledge-note.shacl.ttl"] = KNOWLEDGE_NOTE_SHACL.encode("utf-8")
        files.update(
            await _knowledge_jsonl_files(
                session,
                export,
                document,
                knowledge,
            )
        )

    manifest_warnings = (
        [] if quality_report.status == "PASS" else [f"quality:{quality_report.status}"]
    )
    figure_manifest = figure_files.get("assets/figures/manifest.json")
    if figure_manifest is not None:
        figure_records = json.loads(figure_manifest).get("figures", [])
        manifest_warnings.extend(
            f"figure:{record['block_id']}:{record['reason']}"
            for record in figure_records
            if record.get("status") == "unavailable" and isinstance(record.get("reason"), str)
        )
    _add_manifest(
        files,
        selected,
        export=export,
        document=document,
        generated_at=processed_at,
        warnings=manifest_warnings,
    )
    payload = deterministic_zip(files)
    return payload, hashlib.sha256(payload).hexdigest()
