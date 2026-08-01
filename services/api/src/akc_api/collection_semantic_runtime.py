"""Authoritative collection semantic compile and retrieval completion gates.

This module is deliberately separate from ``collection_api``.  The route owns
collection lifecycle and credits; this service owns semantic construction,
numeric/region verification, PostgreSQL indexing, and the success outbox
receipt.  A caller must not mark a compile complete unless the returned result
is accepted.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from akc_cir import (
    BBox1000,
    CanonicalKnowledgeModel,
    KnowledgeObjectKind,
    KnowledgeOrigin,
    KnowledgeVerificationState,
    SourceRef,
    build_knowledge_object,
    canonical_json,
    sha256_digest,
)
from akc_domain_packs import builtin_blueprint_modules
from akc_exporters import (
    KnowledgePackageSemanticProfile,
    SemanticAssetManifest,
    SemanticBlueprintManifest,
    canonical_knowledge_model_bytes,
    knowledge_package_semantic_profile,
)
from akc_quality import (
    AgentFinding,
    AgentReport,
    AuthorityNumericFact,
    AutonomousState,
    AutonomousVerificationDecision,
    AutonomousVerificationInput,
    DartXbrlProvenance,
    FindingLevel,
    GeometrySource,
    GeometryWord,
    NumericCellKey,
    NumericGeometryResult,
    ParserNumericCell,
    RecoveryStage,
    SecInlineXbrlProvenance,
    VerificationAgent,
    decide_autonomously,
    match_numeric_geometry,
)
from akc_retrieval import (
    AttestedRetrievalPayload,
    MediaKind,
    NumericAnswerVerification,
    NumericFactKey,
    PostgresHybridIndexer,
    PostgresHybridStore,
    RetrievalFilters,
    RetrievalIndexBatch,
    RetrievalIndexDocument,
    RetrievalIndexEdge,
    RetrievalIndexReceipt,
    RetrievalQuery,
    RetrievalUnavailable,
    VectorCandidate,
    VerificationState,
    verify_numeric_answer,
)
from akc_retrieval import (
    NumericAuthorityFact as RetrievalNumericAuthorityFact,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.collection_integrity_runtime import load_integrity_decision_projection
from akc_api.collection_region_runtime import promoted_region_text_by_block
from akc_api.models import (
    ArchitecturePlan,
    AuthorityFact,
    AuthorityMapping,
    Block,
    BlueprintModule,
    Collection,
    CollectionFile,
    CollectionRegion,
    CollectionRegionAttempt,
    Document,
    Entity,
    KnowledgeNote,
    OutboxEvent,
    Page,
    PageAttempt,
    Relation,
    SourceFile,
)

_SHA256 = r"^[0-9a-f]{64}$"
_PROMOTED_STATES = frozenset(
    {
        KnowledgeVerificationState.VERIFIED,
        KnowledgeVerificationState.AUTHORITY_VERIFIED,
        KnowledgeVerificationState.AUTO_REPAIRED,
        KnowledgeVerificationState.VERIFIED_WITH_WARNING,
    }
)
_REGION_REQUIRED_BLOCK_TYPES = frozenset({"table", "figure", "formula"})
_OUTPUT_MODULE_KEYS = frozenset(
    {
        "source_index",
        "document_catalog",
        "knowledge_notes",
        "entities",
        "relations",
        "integrity",
        "export_manifest",
    }
)


class _RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticSourceIntegrityReceipt(_RuntimeModel):
    """Deterministic receipt over the persisted source and page evidence."""

    document_id: uuid.UUID
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    source_file_id: uuid.UUID
    collection_file_id: uuid.UUID
    source_sha256: Annotated[str, Field(pattern=_SHA256)]
    collection_file_sha256: Annotated[str, Field(pattern=_SHA256)]
    source_size_bytes: Annotated[int, Field(ge=0)]
    collection_file_size_bytes: Annotated[int, Field(ge=0)]
    collection_file_status: Annotated[str, Field(min_length=1, max_length=32)]
    antivirus_status: Annotated[str, Field(min_length=1, max_length=32)]
    cdr_status: Annotated[str, Field(min_length=1, max_length=32)]
    expected_page_count: Annotated[int, Field(ge=0)]
    observed_page_count: Annotated[int, Field(ge=0)]
    terminal_page_count: Annotated[int, Field(ge=0)]
    render_required_page_count: Annotated[int, Field(ge=0)]
    rendered_page_count: Annotated[int, Field(ge=0)]
    render_corruption_count: Annotated[int, Field(ge=0)]
    receipt_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class SemanticDocumentInput(_RuntimeModel):
    id: uuid.UUID
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    title: Annotated[str, Field(min_length=1, max_length=500)]
    source_refs: Annotated[tuple[SourceRef, ...], Field(min_length=1)]
    integrity_receipt: SemanticSourceIntegrityReceipt | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bind_sources_to_document(self) -> SemanticDocumentInput:
        if any(source.document_id != str(self.id) for source in self.source_refs):
            raise ValueError("document source references must use the document ID")
        if any(
            source.document_version_id != self.document_version_id for source in self.source_refs
        ):
            raise ValueError("document source references must use the active version")
        return self


class SemanticBlockInput(_RuntimeModel):
    id: uuid.UUID
    document_id: uuid.UUID
    block_type: Annotated[str, Field(min_length=1, max_length=80)]
    text: str
    source_refs: Annotated[tuple[SourceRef, ...], Field(min_length=1)]
    origin: KnowledgeOrigin
    verification_state: KnowledgeVerificationState
    payload: dict[str, Any] = Field(default_factory=dict)


class SemanticNoteInput(_RuntimeModel):
    id: uuid.UUID
    document_id: uuid.UUID
    stable_key: Annotated[str, Field(min_length=1, max_length=160)]
    title: Annotated[str, Field(min_length=1, max_length=500)]
    note_type: Annotated[str, Field(min_length=1, max_length=80)]
    content_markdown: Annotated[str, Field(min_length=1, max_length=2_000_000)]
    evidence_block_ids: Annotated[tuple[uuid.UUID, ...], Field(min_length=1, max_length=100)]
    origin: KnowledgeOrigin
    verification_state: KnowledgeVerificationState
    payload: dict[str, Any] = Field(default_factory=dict)


class SemanticEntityInput(_RuntimeModel):
    id: uuid.UUID
    stable_key: Annotated[str, Field(min_length=1, max_length=160)]
    entity_type: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_block_ids: Annotated[tuple[uuid.UUID, ...], Field(min_length=1, max_length=100)]
    origin: KnowledgeOrigin
    verification_state: KnowledgeVerificationState
    payload: dict[str, Any] = Field(default_factory=dict)


class SemanticRelationInput(_RuntimeModel):
    id: uuid.UUID
    document_id: uuid.UUID | None = None
    subject_id: Annotated[str, Field(min_length=1, max_length=240)]
    predicate: Annotated[str, Field(min_length=1, max_length=240)]
    object_id: Annotated[str, Field(min_length=1, max_length=240)]
    evidence_block_ids: Annotated[tuple[uuid.UUID, ...], Field(min_length=1, max_length=100)]
    origin: KnowledgeOrigin
    verification_state: KnowledgeVerificationState
    payload: dict[str, Any] = Field(default_factory=dict)


class SemanticRegionInput(_RuntimeModel):
    id: uuid.UUID
    region_type: Annotated[str, Field(min_length=1, max_length=80)]
    source_refs: Annotated[tuple[SourceRef, ...], Field(min_length=1)]
    verification_state: KnowledgeVerificationState
    findings: tuple[AgentFinding, ...] = ()
    repair_stages_completed: tuple[RecoveryStage, ...] = ()
    independent_signal_count: Annotated[int, Field(ge=0, le=16)] = 0
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repair_stages_completed")
    @classmethod
    def ordered_recovery(cls, value: tuple[RecoveryStage, ...]) -> tuple[RecoveryStage, ...]:
        if value != tuple(RecoveryStage)[: len(value)]:
            raise ValueError("region recovery stages must be a deterministic prefix")
        return value


class CollectionOutputModuleInput(_RuntimeModel):
    id: uuid.UUID
    module_key: Annotated[str, Field(min_length=1, max_length=120)]
    module_version: Annotated[str, Field(min_length=1, max_length=40)]
    status: Annotated[str, Field(pattern=r"^compiled$")] = "compiled"
    config: dict[str, Any]
    output_summary: dict[str, Any]


class SemanticIntegrityDecisionReceipt(_RuntimeModel):
    decision_id: uuid.UUID
    execution_id: uuid.UUID
    target_type: Literal["quarantine_item", "review_item"]
    target_id: uuid.UUID
    action: Literal[
        "keep_quarantined",
        "exclude",
        "retry_new_engine",
        "provide_password",
        "correct_source",
        "override",
    ]
    reason_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,119}$")]
    execution_receipt_sha256: Annotated[str, Field(pattern=_SHA256)]
    result_code: Annotated[str | None, Field(max_length=120)] = None


class CollectionSemanticCompileInput(_RuntimeModel):
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    collection_id: uuid.UUID
    architecture_plan_id: uuid.UUID
    architecture_plan_version: Annotated[int, Field(ge=1)]
    architecture_plan: dict[str, Any]
    input_integrity_sha256: Annotated[str, Field(pattern=_SHA256)]
    knowledge_blueprint_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,79}$")]
    knowledge_blueprint_registry_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    knowledge_blueprint_module_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    documents: Annotated[tuple[SemanticDocumentInput, ...], Field(min_length=1)]
    blocks: Annotated[tuple[SemanticBlockInput, ...], Field(min_length=1)]
    notes: Annotated[tuple[SemanticNoteInput, ...], Field(min_length=1)]
    entities: tuple[SemanticEntityInput, ...] = ()
    relations: tuple[SemanticRelationInput, ...] = ()
    regions: tuple[SemanticRegionInput, ...] = ()
    output_modules: tuple[CollectionOutputModuleInput, ...] = ()
    integrity_decision_receipts: tuple[SemanticIntegrityDecisionReceipt, ...] = ()
    numeric_scope_declared: bool = False
    authority_facts: tuple[AuthorityNumericFact, ...] = ()
    parser_numeric_cells: tuple[ParserNumericCell, ...] = ()
    numeric_source_refs: dict[str, SourceRef] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_collection_graph_input(self) -> CollectionSemanticCompileInput:
        for label, values in (
            ("document", self.documents),
            ("block", self.blocks),
            ("note", self.notes),
            ("entity", self.entities),
            ("relation", self.relations),
            ("region", self.regions),
            ("output module", self.output_modules),
        ):
            identifiers = [item.id for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} IDs must be unique")
        module_keys = [module.module_key for module in self.output_modules]
        if len(module_keys) != len(set(module_keys)):
            raise ValueError("output module keys must be unique")

        document_ids = {document.id for document in self.documents}
        if any(block.document_id not in document_ids for block in self.blocks):
            raise ValueError("blocks must belong to collection documents")
        if any(note.document_id not in document_ids for note in self.notes):
            raise ValueError("notes must belong to collection documents")
        if any(
            relation.document_id is not None and relation.document_id not in document_ids
            for relation in self.relations
        ):
            raise ValueError("relations must belong to collection documents")

        block_ids = {block.id for block in self.blocks}
        evidence_sets = (
            *(note.evidence_block_ids for note in self.notes),
            *(entity.evidence_block_ids for entity in self.entities),
            *(relation.evidence_block_ids for relation in self.relations),
        )
        if any(len(evidence) != len(set(evidence)) for evidence in evidence_sets):
            raise ValueError("semantic evidence block IDs must be unique")
        missing_evidence = sorted(
            str(block_id)
            for evidence in evidence_sets
            for block_id in evidence
            if block_id not in block_ids
        )
        if missing_evidence:
            raise ValueError(f"semantic evidence references unknown blocks: {missing_evidence}")

        plan_collection = self.architecture_plan.get("collection_id")
        plan_project = self.architecture_plan.get("project_id")
        if plan_collection is not None and str(plan_collection) != str(self.collection_id):
            raise ValueError("architecture plan collection scope mismatch")
        if plan_project is not None and str(plan_project) != str(self.project_id):
            raise ValueError("architecture plan project scope mismatch")

        parser_ids = {cell.parser_cell_id for cell in self.parser_numeric_cells}
        if set(self.numeric_source_refs) != parser_ids:
            raise ValueError("numeric source references must exactly cover parser cells")
        return self


@lru_cache(maxsize=1)
def builtin_semantic_blueprint_manifests() -> tuple[SemanticBlueprintManifest, ...]:
    """Load and hash the exact seven built-in declarative blueprint modules."""

    manifests: list[SemanticBlueprintManifest] = []
    for module in builtin_blueprint_modules():
        assets = tuple(
            SemanticAssetManifest(**asset.model_dump(mode="python")) for asset in module.assets
        )
        manifests.append(
            SemanticBlueprintManifest(
                blueprint_id=module.blueprint.id,
                blueprint_version=module.blueprint.version,
                module_sha256=module.module_sha256,
                assets=assets,
                prompt_assets=tuple(asset for asset in assets if asset.path.startswith("prompts/")),
                validator_assets=tuple(
                    asset for asset in assets if asset.path.startswith("validators/")
                ),
                template_assets=tuple(
                    asset for asset in assets if asset.path.startswith("templates/")
                ),
                validator_ids=module.blueprint.validators,
                template_ids=module.blueprint.moc_templates,
                export_profiles=module.blueprint.export_profiles,
            )
        )
    manifests.sort(key=lambda item: item.blueprint_id)
    if len(manifests) != 7:
        raise RuntimeError("semantic runtime requires all seven built-in blueprints")
    return tuple(manifests)


def semantic_blueprint_registry_sha256(
    manifests: tuple[SemanticBlueprintManifest, ...] | None = None,
) -> str:
    selected = manifests or builtin_semantic_blueprint_manifests()
    return sha256_digest(canonical_json([item.model_dump(mode="json") for item in selected]))


def canonical_object_id(kind: KnowledgeObjectKind, identifier: str | uuid.UUID) -> str:
    """Return the stable, type-scoped ID used by canonical and retrieval planes."""

    return f"{kind.value}:{identifier}"


def _knowledge_origin(value: str | None) -> KnowledgeOrigin:
    normalized = (value or "").casefold()
    mapping = {
        "source_explicit": KnowledgeOrigin.SOURCE_EXPLICIT,
        "extracted": KnowledgeOrigin.SOURCE_EXPLICIT,
        "structured_derived": KnowledgeOrigin.STRUCTURED_DERIVED,
        "rule_derived": KnowledgeOrigin.RULE_DERIVED,
        "rule_reconstructed": KnowledgeOrigin.RULE_DERIVED,
        "model_inferred": KnowledgeOrigin.MODEL_INFERRED,
        "ai_inferred": KnowledgeOrigin.MODEL_INFERRED,
        "ai_summarized": KnowledgeOrigin.MODEL_INFERRED,
        "native_extracted": KnowledgeOrigin.NATIVE_EXTRACTED,
        "native_text": KnowledgeOrigin.NATIVE_EXTRACTED,
        "ocr_extracted": KnowledgeOrigin.VISUAL_EXTRACTED,
        "visual_extracted": KnowledgeOrigin.VISUAL_EXTRACTED,
        "ai_reconstructed": KnowledgeOrigin.VISUAL_EXTRACTED,
        "authority_reconstructed": KnowledgeOrigin.AUTHORITY_RECONSTRUCTED,
        "user_verified": KnowledgeOrigin.STRUCTURED_DERIVED,
        "user_edited": KnowledgeOrigin.STRUCTURED_DERIVED,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported semantic origin: {value}") from exc


def _verification_state(value: str | None) -> KnowledgeVerificationState:
    normalized = (value or "").casefold()
    mapping = {
        "completed": KnowledgeVerificationState.VERIFIED,
        "verified": KnowledgeVerificationState.VERIFIED,
        "user_verified": KnowledgeVerificationState.VERIFIED,
        "authority_verified": KnowledgeVerificationState.AUTHORITY_VERIFIED,
        "auto_repaired": KnowledgeVerificationState.AUTO_REPAIRED,
        "verified_with_warning": KnowledgeVerificationState.VERIFIED_WITH_WARNING,
        "auto_with_warnings": KnowledgeVerificationState.VERIFIED_WITH_WARNING,
        "needs_review": KnowledgeVerificationState.UNRESOLVED,
        "pending": KnowledgeVerificationState.UNRESOLVED,
        "unreviewed": KnowledgeVerificationState.UNRESOLVED,
        "unresolved": KnowledgeVerificationState.UNRESOLVED,
        "discovered": KnowledgeVerificationState.UNRESOLVED,
        "queued": KnowledgeVerificationState.UNRESOLVED,
        "processing": KnowledgeVerificationState.UNRESOLVED,
        "quarantined": KnowledgeVerificationState.QUARANTINED,
        "failed": KnowledgeVerificationState.REJECTED,
        "rejected": KnowledgeVerificationState.REJECTED,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported verification state: {value}") from exc


def _active_version_id(document: Document) -> str:
    return f"document:{document.id}:v{document.active_version}"


def _bbox(value: Sequence[int] | None) -> BBox1000 | None:
    if value is None:
        return None
    if len(value) != 4:
        raise ValueError("bbox1000 requires four coordinates")
    return BBox1000((int(value[0]), int(value[1]), int(value[2]), int(value[3])))


def _block_source_ref(block: Block, page: Page, document: Document) -> SourceRef:
    return SourceRef(
        document_id=str(document.id),
        document_version_id=_active_version_id(document),
        page_index0=page.page_number - 1,
        page_number1=page.page_number,
        bbox1000=_bbox(block.bbox1000),
        native_object_id=str(block.id),
    )


def _region_source_ref(
    region: CollectionRegion,
    page: Page,
    document: Document,
) -> SourceRef:
    return SourceRef(
        document_id=str(document.id),
        document_version_id=_active_version_id(document),
        page_index0=page.page_number - 1,
        page_number1=page.page_number,
        bbox1000=_bbox(region.bbox1000),
        native_object_id=str(region.id),
    )


def _source_integrity_receipt_sha256(payload: Mapping[str, Any]) -> str:
    return sha256_digest(canonical_json(payload))


def _receipt_payload(receipt: SemanticSourceIntegrityReceipt) -> dict[str, Any]:
    return receipt.model_dump(mode="json", exclude={"receipt_sha256"})


def _page_render_is_corrupt(page: Page, attempt: PageAttempt) -> bool:
    if page.route not in {None, "native"} and not page.render_key:
        return True
    evidence = canonical_json(
        {
            "page_status": page.status,
            "attempt_status": attempt.status,
            "quality_findings": attempt.quality_findings,
            "quality_evaluation": attempt.quality_evaluation,
        }
    ).casefold()
    return any(
        marker in evidence
        for marker in (
            "blank_render",
            "corrupt_render",
            "render_corrupt",
            "render_failed",
            "render_unreadable",
        )
    )


def _date_value(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _authority_fact_contract(row: AuthorityFact) -> AuthorityNumericFact:
    context = row.context
    locator = row.source_locator
    unit = row.unit or context.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("authority fact unit is missing")
    key = NumericCellKey(
        entity_id=str(context["entity_id"]),
        statement=str(context["statement"]),
        concept=str(context["concept"]),
        period_start=_date_value(context.get("period_start")),
        period_end=_date_value(context.get("period_end")),
        instant=_date_value(context.get("instant")),
        unit=unit,
        scale=int(context.get("scale", 1)),
        dimensions=dict(context.get("dimensions", {})),
        page=int(context["page"]),
        row_key=str(context["row_key"]),
        column_key=str(context["column_key"]),
    )
    common = {
        "entity_id": key.entity_id,
        "fact_period_start": key.period_start,
        "fact_period_end": key.period_end,
        "fact_instant": key.instant,
    }
    provenance: DartXbrlProvenance | SecInlineXbrlProvenance
    if row.source_kind == "dart":
        provenance = DartXbrlProvenance(
            **common,
            receipt_number=str(locator["receipt_number"]),
            report_code=str(locator["report_code"]),
            xml_fact_id=str(locator["xml_fact_id"]),
            xml_document_uri=str(locator["xml_document_uri"]),
            pdf_document_uri=str(locator["pdf_document_uri"]),
        )
    elif row.source_kind == "sec":
        provenance = SecInlineXbrlProvenance(
            **common,
            accession_number=str(locator["accession_number"]),
            form=str(locator["form"]),
            inline_xbrl_fact_id=str(locator["inline_xbrl_fact_id"]),
            filing_html_uri=str(locator["filing_html_uri"]),
        )
    else:
        raise ValueError("numeric authority requires a DART or SEC fact")
    return AuthorityNumericFact(
        fact_id=str(row.id),
        key=key,
        xbrl_label=str(context["xbrl_label"]),
        value=Decimal(row.normalized_value),
        provenance=provenance,
    )


def _parser_cell_contract(
    row: AuthorityMapping,
    fact: AuthorityNumericFact,
) -> ParserNumericCell:
    geometry = row.geometry
    key_payload = geometry.get("key")
    key = NumericCellKey.model_validate(key_payload) if isinstance(key_payload, dict) else fact.key
    return ParserNumericCell(
        parser_cell_id=str(geometry.get("parser_cell_id", row.id)),
        key=key,
        geometry_source=GeometrySource(str(geometry["geometry_source"])),
        source_document_uri=str(geometry["source_document_uri"]),
        label=str(geometry["label"]),
        row_header=str(geometry["row_header"]),
        column_header=str(geometry["column_header"]),
        original_parser_number=str(geometry["original_parser_number"]),
        parser_value=Decimal(str(geometry["parser_value"])),
        bbox1000=BBox1000.model_validate(geometry["bbox1000"]),
        words=tuple(GeometryWord.model_validate(item) for item in geometry["words"]),
    )


def _geometry_intersects(left: object, right: object) -> bool:
    def values(candidate: object) -> tuple[float, float, float, float] | None:
        if (
            not isinstance(candidate, (list, tuple))
            or len(candidate) != 4
            or any(
                not isinstance(item, (int, float)) or isinstance(item, bool)
                for item in candidate
            )
        ):
            return None
        x0, y0, x1, y1 = (float(item) for item in candidate)
        return x0, y0, x1, y1

    left_values = values(left)
    right_values = values(right)
    if left_values is None or right_values is None:
        return False
    lx0, ly0, lx1, ly1 = left_values
    rx0, ry0, rx1, ry1 = right_values
    return lx0 < rx1 and lx1 > rx0 and ly0 < ry1 and ly1 > ry0


async def load_collection_semantic_compile_input(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    project_id: uuid.UUID,
    architecture_plan_id: uuid.UUID,
    document_ids: Sequence[uuid.UUID],
) -> CollectionSemanticCompileInput:
    """Load current tenant-scoped collection rows into the strict runtime contract."""

    projection = await load_integrity_decision_projection(
        session,
        tenant_id=tenant_id,
        collection_id=collection_id,
    )
    requested_documents = tuple(
        sorted(set(document_ids) - projection.excluded_document_ids, key=str)
    )
    if not requested_documents:
        raise ValueError("integrity decisions exclude all collection documents")
    collection = await session.scalar(
        select(Collection).where(
            Collection.tenant_id == tenant_id,
            Collection.id == collection_id,
            Collection.project_id == project_id,
        )
    )
    plan = await session.scalar(
        select(ArchitecturePlan).where(
            ArchitecturePlan.tenant_id == tenant_id,
            ArchitecturePlan.collection_id == collection_id,
            ArchitecturePlan.id == architecture_plan_id,
        )
    )
    if collection is None or plan is None:
        raise ValueError("collection or architecture plan is outside the tenant scope")
    documents = list(
        await session.scalars(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.project_id == project_id,
                Document.id.in_(requested_documents),
            )
        )
    )
    if {item.id for item in documents} != set(requested_documents):
        raise ValueError("collection document scope is incomplete")
    document_by_id = {item.id: item for item in documents}
    source_file_ids = tuple(
        sorted(
            {item.source_file_id for item in documents if item.source_file_id is not None},
            key=str,
        )
    )
    source_files = (
        list(
            await session.scalars(
                select(SourceFile).where(
                    SourceFile.tenant_id == tenant_id,
                    SourceFile.project_id == project_id,
                    SourceFile.id.in_(source_file_ids),
                )
            )
        )
        if source_file_ids
        else []
    )
    source_file_by_id = {item.id: item for item in source_files}
    collection_files = (
        list(
            await session.scalars(
                select(CollectionFile).where(
                    CollectionFile.tenant_id == tenant_id,
                    CollectionFile.collection_id == collection_id,
                    CollectionFile.source_file_id.in_(source_file_ids),
                )
            )
        )
        if source_file_ids
        else []
    )
    collection_files_by_source: dict[uuid.UUID, list[CollectionFile]] = {}
    for collection_file in collection_files:
        if collection_file.source_file_id is not None:
            collection_files_by_source.setdefault(collection_file.source_file_id, []).append(
                collection_file
            )
    excluded_source_ids = {
        row.source_file_id
        for row in collection_files
        if row.id in projection.excluded_collection_file_ids and row.source_file_id is not None
    }
    if excluded_source_ids:
        documents = [
            document for document in documents if document.source_file_id not in excluded_source_ids
        ]
        requested_documents = tuple(sorted((row.id for row in documents), key=str))
        document_by_id = {item.id: item for item in documents}
        if not requested_documents:
            raise ValueError("integrity decisions exclude all collection documents")
    pages = list(
        await session.scalars(
            select(Page).where(
                Page.tenant_id == tenant_id,
                Page.document_id.in_(requested_documents),
            )
        )
    )
    pages = [page for page in pages if page.id not in projection.excluded_page_ids]
    page_by_id = {item.id: item for item in pages}
    blocks = list(
        await session.scalars(
            select(Block).where(
                Block.tenant_id == tenant_id,
                Block.document_id.in_(requested_documents),
            )
        )
    )
    blocks = [
        block
        for block in blocks
        if block.id not in projection.excluded_block_ids and block.page_id in page_by_id
    ]
    if not blocks or any(block.page_id not in page_by_id for block in blocks):
        raise ValueError("semantic blocks require collection page provenance")
    block_by_id = {block.id: block for block in blocks}

    attempts = list(
        await session.scalars(
            select(PageAttempt).where(
                PageAttempt.tenant_id == tenant_id,
                PageAttempt.page_id.in_(tuple(page_by_id)),
            )
        )
    )
    latest_page_attempt: dict[uuid.UUID, PageAttempt] = {}
    for attempt in sorted(attempts, key=lambda item: item.attempt_number):
        latest_page_attempt[attempt.page_id] = attempt
    if set(latest_page_attempt) != set(page_by_id):
        raise ValueError("semantic pages require terminal attempt evidence")
    pages_by_document: dict[uuid.UUID, list[Page]] = {}
    for page in pages:
        pages_by_document.setdefault(page.document_id, []).append(page)

    notes = list(
        await session.scalars(
            select(KnowledgeNote).where(
                KnowledgeNote.tenant_id == tenant_id,
                KnowledgeNote.project_id == project_id,
                KnowledgeNote.document_id.in_(requested_documents),
                KnowledgeNote.is_active.is_(True),
            )
        )
    )
    relations = list(
        await session.scalars(
            select(Relation).where(
                Relation.tenant_id == tenant_id,
                Relation.project_id == project_id,
                Relation.document_id.in_(requested_documents),
                Relation.is_active.is_(True),
            )
        )
    )
    entities = [
        item
        for item in await session.scalars(
            select(Entity).where(
                Entity.tenant_id == tenant_id,
                Entity.project_id == project_id,
            )
        )
        if any(uuid.UUID(str(block_id)) in block_by_id for block_id in item.evidence_block_ids)
    ]
    all_regions = list(
        await session.scalars(
            select(CollectionRegion).where(
                CollectionRegion.tenant_id == tenant_id,
                CollectionRegion.collection_id == collection_id,
            )
        )
    )
    excluded_regions = [
        region for region in all_regions if region.id in projection.excluded_region_ids
    ]
    regions = [region for region in all_regions if region.id not in projection.excluded_region_ids]
    if excluded_regions:
        blocks = [
            block
            for block in blocks
            if not any(
                region.page_id == block.page_id
                and _geometry_intersects(block.bbox1000, region.bbox1000)
                for region in excluded_regions
            )
        ]
        if not blocks:
            raise ValueError("integrity decisions exclude all semantic blocks")
        block_by_id = {block.id: block for block in blocks}
        entities = [
            entity
            for entity in entities
            if any(
                uuid.UUID(str(block_id)) in block_by_id
                for block_id in entity.evidence_block_ids
            )
        ]
    region_ids = tuple(region.id for region in regions)
    region_attempts = (
        list(
            await session.scalars(
                select(CollectionRegionAttempt).where(
                    CollectionRegionAttempt.tenant_id == tenant_id,
                    CollectionRegionAttempt.collection_id == collection_id,
                    CollectionRegionAttempt.region_id.in_(region_ids),
                )
            )
        )
        if region_ids
        else []
    )
    output_modules = list(
        await session.scalars(
            select(BlueprintModule).where(
                BlueprintModule.tenant_id == tenant_id,
                BlueprintModule.collection_id == collection_id,
                BlueprintModule.architecture_plan_id == architecture_plan_id,
            )
        )
    )

    authority_rows = list(
        await session.scalars(
            select(AuthorityFact).where(
                AuthorityFact.tenant_id == tenant_id,
                AuthorityFact.collection_id == collection_id,
            )
        )
    )
    mapping_rows = list(
        await session.scalars(
            select(AuthorityMapping).where(
                AuthorityMapping.tenant_id == tenant_id,
                AuthorityMapping.collection_id == collection_id,
            )
        )
    )
    authority_contracts = {
        row.id: _authority_fact_contract(row) for row in authority_rows if row.status == "verified"
    }
    region_by_id = {region.id: region for region in regions}
    parser_cells: list[ParserNumericCell] = []
    numeric_sources: dict[str, SourceRef] = {}
    for mapping in mapping_rows:
        fact = authority_contracts.get(mapping.authority_fact_id)
        region = region_by_id.get(mapping.region_id)
        if mapping.mapping_status != "matched" or fact is None or region is None:
            continue
        if region.page_id is None or region.document_id is None:
            raise ValueError("numeric authority mapping requires document page geometry")
        cell = _parser_cell_contract(mapping, fact)
        parser_cells.append(cell)
        numeric_sources[cell.parser_cell_id] = _region_source_ref(
            region,
            page_by_id[region.page_id],
            document_by_id[region.document_id],
        )

    region_attempts_by_id: dict[uuid.UUID, list[CollectionRegionAttempt]] = {}
    for region_attempt in region_attempts:
        region_attempts_by_id.setdefault(region_attempt.region_id, []).append(region_attempt)
    semantic_regions: list[SemanticRegionInput] = []
    for region in regions:
        if region.page_id is None or region.document_id is None:
            raise ValueError("collection regions require document page provenance")
        completed: list[RecoveryStage] = []
        findings: list[AgentFinding] = []
        independent_signal_count = 0
        for region_attempt in sorted(
            region_attempts_by_id.get(region.id, ()),
            key=lambda item: item.attempt_number,
        ):
            summary = region_attempt.validator_summary
            stage = summary.get("recovery_stage")
            if stage is not None:
                completed.append(RecoveryStage(str(stage)))
            independent_signal_count = max(
                independent_signal_count,
                int(summary.get("independent_signal_count", 0)),
            )
            raw_findings = summary.get("findings", ())
            if isinstance(raw_findings, list):
                findings.extend(AgentFinding.model_validate(item) for item in raw_findings)
            raw_reasons = summary.get("reason_codes", ())
            if isinstance(raw_reasons, list):
                findings.extend(_finding(str(reason), FindingLevel.HARD) for reason in raw_reasons)
        semantic_regions.append(
            SemanticRegionInput(
                id=region.id,
                region_type=region.region_type,
                source_refs=(
                    _region_source_ref(
                        region,
                        page_by_id[region.page_id],
                        document_by_id[region.document_id],
                    ),
                ),
                verification_state=_verification_state(region.status),
                findings=tuple(findings),
                repair_stages_completed=tuple(completed),
                independent_signal_count=independent_signal_count,
                payload={
                    "collection_file_id": str(region.collection_file_id),
                    "stable_key": region.stable_key,
                },
            )
        )

    source_refs_by_document: dict[uuid.UUID, dict[str, SourceRef]] = {}
    semantic_blocks: list[SemanticBlockInput] = []
    promoted_region_text = promoted_region_text_by_block(
        regions,
        region_attempts,
        blocks=blocks,
        latest_page_attempts=latest_page_attempt,
    )
    promoted_region_state: dict[uuid.UUID, KnowledgeVerificationState] = {}
    for region in regions:
        if not region.stable_key.startswith("block:"):
            continue
        try:
            block_id = uuid.UUID(region.stable_key.removeprefix("block:"))
        except ValueError:
            continue
        if block_id in promoted_region_text:
            promoted_region_state[block_id] = _verification_state(region.status)

    def block_is_overridden(block: Block, page: Page) -> bool:
        return bool(
            block.id in projection.overridden_block_ids
            or page.id in projection.overridden_page_ids
            or block.document_id in projection.overridden_document_ids
        )

    for block in blocks:
        if block.page_id is None:
            raise ValueError("semantic blocks require a source page")
        page = page_by_id[block.page_id]
        document = document_by_id[block.document_id]
        source = _block_source_ref(block, page, document)
        source_refs_by_document.setdefault(block.document_id, {})[canonical_json(source)] = source
        semantic_blocks.append(
            SemanticBlockInput(
                id=block.id,
                document_id=block.document_id,
                block_type=block.block_type,
                text=promoted_region_text.get(
                    block.id,
                    block.normalized_text or block.markdown or block.source_text or "",
                ),
                source_refs=(source,),
                origin=_knowledge_origin(block.origin),
                verification_state=(
                    KnowledgeVerificationState.VERIFIED_WITH_WARNING
                    if block_is_overridden(block, page)
                    else promoted_region_state.get(
                        block.id,
                        _verification_state(latest_page_attempt[page.id].status),
                    )
                ),
                payload={
                    "content_hash": block.content_hash,
                    "region_output_promoted": block.id in promoted_region_text,
                    "structured_content": block.structured_content,
                    "engine": block.engine,
                    "engine_revision": block.engine_revision,
                },
            )
        )
    if set(source_refs_by_document) != set(requested_documents):
        raise ValueError("every collection document requires semantic block evidence")

    def evidence_ids(values: Sequence[str]) -> tuple[uuid.UUID, ...]:
        return tuple(uuid.UUID(str(item)) for item in values)

    def included_evidence_ids(values: Sequence[str]) -> tuple[uuid.UUID, ...]:
        return tuple(item for item in evidence_ids(values) if item in block_by_id)

    def evidence_verification_state(block_id: uuid.UUID) -> KnowledgeVerificationState:
        block = block_by_id[block_id]
        page_id = block.page_id
        if page_id is None:
            raise ValueError("semantic evidence block requires a source page")
        if block_is_overridden(block, page_by_id[page_id]):
            return KnowledgeVerificationState.VERIFIED_WITH_WARNING
        if block_id in promoted_region_state:
            return promoted_region_state[block_id]
        return _verification_state(latest_page_attempt[page_id].status)

    def projected_review_state(
        stored_state: str | None,
        values: Sequence[str],
    ) -> KnowledgeVerificationState:
        evidence = included_evidence_ids(values)
        if any(
            evidence_verification_state(block_id)
            is KnowledgeVerificationState.VERIFIED_WITH_WARNING
            for block_id in evidence
        ):
            return KnowledgeVerificationState.VERIFIED_WITH_WARNING
        return _verification_state(stored_state)

    def source_integrity_receipt(
        document: Document,
    ) -> SemanticSourceIntegrityReceipt | None:
        if document.source_file_id is None:
            return None
        source_file = source_file_by_id.get(document.source_file_id)
        candidates = sorted(
            collection_files_by_source.get(document.source_file_id, ()),
            key=lambda item: (item.status not in {"verified", "duplicate"}, str(item.id)),
        )
        if source_file is None or not candidates:
            return None
        collection_file = candidates[0]
        document_pages = sorted(
            pages_by_document.get(document.id, ()),
            key=lambda item: item.page_number,
        )
        render_required = tuple(
            page for page in document_pages if page.route not in {None, "native"}
        )
        receipt_payload: dict[str, Any] = {
            "document_id": str(document.id),
            "document_version_id": _active_version_id(document),
            "source_file_id": str(source_file.id),
            "collection_file_id": str(collection_file.id),
            "source_sha256": source_file.sha256,
            "collection_file_sha256": collection_file.sha256,
            "source_size_bytes": source_file.size_bytes,
            "collection_file_size_bytes": collection_file.size_bytes,
            "collection_file_status": collection_file.status,
            "antivirus_status": source_file.antivirus_status,
            "cdr_status": source_file.cdr_status,
            "expected_page_count": document.page_count or 0,
            "observed_page_count": len(document_pages),
            "terminal_page_count": sum(
                latest_page_attempt[page.id].status == "COMPLETED" for page in document_pages
            ),
            "render_required_page_count": len(render_required),
            "rendered_page_count": sum(bool(page.render_key) for page in render_required),
            "render_corruption_count": sum(
                _page_render_is_corrupt(page, latest_page_attempt[page.id])
                for page in render_required
            ),
        }
        return SemanticSourceIntegrityReceipt.model_validate(
            {
                **receipt_payload,
                "receipt_sha256": _source_integrity_receipt_sha256(receipt_payload),
            }
        )

    plan_payload = plan.plan
    selected_blueprint = plan_payload.get("knowledge_blueprint_id")
    if selected_blueprint is None:
        selected_blueprint = plan_payload.get("selected_knowledge_blueprint_id")
    registry_sha = plan_payload.get("knowledge_blueprint_registry_sha256")
    module_sha = plan_payload.get("knowledge_blueprint_module_sha256")
    if module_sha is None:
        module_sha = plan_payload.get("selected_knowledge_blueprint_module_sha256")
    if not all(isinstance(item, str) for item in (selected_blueprint, registry_sha, module_sha)):
        raise ValueError("architecture plan is missing Knowledge Blueprint attestations")

    return CollectionSemanticCompileInput(
        tenant_id=tenant_id,
        project_id=project_id,
        collection_id=collection_id,
        architecture_plan_id=architecture_plan_id,
        architecture_plan_version=plan.plan_version,
        architecture_plan=plan_payload,
        input_integrity_sha256=plan.input_integrity_sha256,
        knowledge_blueprint_id=str(selected_blueprint),
        knowledge_blueprint_registry_sha256=str(registry_sha),
        knowledge_blueprint_module_sha256=str(module_sha),
        documents=tuple(
            SemanticDocumentInput(
                id=document.id,
                document_version_id=_active_version_id(document),
                title=document.title,
                source_refs=tuple(
                    source_refs_by_document[document.id][key]
                    for key in sorted(source_refs_by_document[document.id])
                ),
                integrity_receipt=source_integrity_receipt(document),
                payload={
                    "active_version": document.active_version,
                    "document_type": document.document_type,
                    "status": document.status,
                },
            )
            for document in sorted(documents, key=lambda item: str(item.id))
        ),
        blocks=tuple(sorted(semantic_blocks, key=lambda item: str(item.id))),
        notes=tuple(
            SemanticNoteInput(
                id=note.id,
                document_id=note.document_id,
                stable_key=note.stable_key,
                title=note.title,
                note_type=note.note_type,
                content_markdown=note.content_markdown,
                evidence_block_ids=included_evidence_ids(note.evidence_block_ids),
                origin=_knowledge_origin(note.content_origin),
                verification_state=projected_review_state(
                    note.review_status,
                    note.evidence_block_ids,
                ),
                payload={"compile_provenance": note.compile_provenance},
            )
            for note in sorted(notes, key=lambda item: str(item.id))
            if note.document_id is not None and included_evidence_ids(note.evidence_block_ids)
        ),
        entities=tuple(
            SemanticEntityInput(
                id=entity.id,
                stable_key=entity.stable_key,
                entity_type=entity.entity_type,
                label=entity.label,
                evidence_block_ids=included_evidence_ids(entity.evidence_block_ids),
                origin=KnowledgeOrigin.STRUCTURED_DERIVED,
                verification_state=_aggregate_verification_state(
                    [
                        evidence_verification_state(block_id)
                        for block_id in included_evidence_ids(entity.evidence_block_ids)
                    ]
                ),
            )
            for entity in sorted(entities, key=lambda item: str(item.id))
            if included_evidence_ids(entity.evidence_block_ids)
        ),
        relations=tuple(
            SemanticRelationInput(
                id=relation.id,
                document_id=relation.document_id,
                subject_id=relation.subject_id,
                predicate=relation.predicate,
                object_id=relation.object_id,
                evidence_block_ids=included_evidence_ids(relation.evidence_block_ids),
                origin=_knowledge_origin(relation.assertion_status),
                verification_state=projected_review_state(
                    relation.review_status,
                    relation.evidence_block_ids,
                ),
                payload={
                    "assertion_status": relation.assertion_status,
                    "compile_provenance": relation.compile_provenance,
                },
            )
            for relation in sorted(relations, key=lambda item: str(item.id))
            if included_evidence_ids(relation.evidence_block_ids)
        ),
        regions=tuple(semantic_regions),
        output_modules=tuple(
            CollectionOutputModuleInput(
                id=module.id,
                module_key=module.module_key,
                module_version=module.module_version,
                status=module.status,
                config=module.config_json,
                output_summary=module.output_summary,
            )
            for module in sorted(output_modules, key=lambda item: item.module_key)
        ),
        integrity_decision_receipts=tuple(
            SemanticIntegrityDecisionReceipt.model_validate(receipt)
            for receipt in projection.receipts
        ),
        numeric_scope_declared=(
            bool(authority_rows or mapping_rows)
            or any(block.block_type.casefold() == "table" for block in blocks)
        ),
        authority_facts=tuple(authority_contracts.values()),
        parser_numeric_cells=tuple(parser_cells),
        numeric_source_refs=numeric_sources,
    )


def _architecture_plan_with_semantics(
    value: CollectionSemanticCompileInput,
    blueprints: tuple[SemanticBlueprintManifest, ...],
) -> tuple[dict[str, Any], str]:
    canonical_plan = {
        key: item
        for key, item in value.architecture_plan.items()
        if key
        not in {
            "selected_knowledge_blueprint_id",
            "selected_knowledge_blueprint_module_sha256",
        }
    }
    blueprint_payload = [item.model_dump(mode="json") for item in blueprints]
    module_payload = [
        {
            "module_id": str(module.id),
            "module_key": module.module_key,
            "module_version": module.module_version,
            "status": module.status,
            "config_sha256": sha256_digest(canonical_json(module.config)),
            "output_sha256": sha256_digest(canonical_json(module.output_summary)),
        }
        for module in sorted(value.output_modules, key=lambda item: item.module_key)
    ]
    integrity_decisions = [
        item.model_dump(mode="json") for item in value.integrity_decision_receipts
    ]
    plan = {
        **canonical_plan,
        "schema_version": str(value.architecture_plan.get("schema_version", "1.0")),
        "collection_id": str(value.collection_id),
        "project_id": str(value.project_id),
        "architecture_plan_id": str(value.architecture_plan_id),
        "architecture_plan_version": value.architecture_plan_version,
        "output_modules": module_payload,
        "knowledge_blueprints": blueprint_payload,
        "knowledge_blueprint_registry_sha256": value.knowledge_blueprint_registry_sha256,
        "knowledge_blueprint_id": value.knowledge_blueprint_id,
        "knowledge_blueprint_module_sha256": value.knowledge_blueprint_module_sha256,
        "integrity_decisions": integrity_decisions,
        "integrity_decision_set_sha256": sha256_digest(canonical_json(integrity_decisions)),
    }
    return plan, sha256_digest(canonical_json(plan))


def _source_refs_for_evidence(
    evidence_ids: Sequence[uuid.UUID],
    block_by_id: Mapping[uuid.UUID, SemanticBlockInput],
) -> tuple[SourceRef, ...]:
    refs: dict[str, SourceRef] = {}
    for block_id in evidence_ids:
        for source in block_by_id[block_id].source_refs:
            refs[canonical_json(source)] = source
    return tuple(refs[key] for key in sorted(refs))


def _aggregate_verification_state(
    states: Sequence[KnowledgeVerificationState],
) -> KnowledgeVerificationState:
    if any(state is KnowledgeVerificationState.QUARANTINED for state in states):
        return KnowledgeVerificationState.QUARANTINED
    if any(state is KnowledgeVerificationState.REJECTED for state in states):
        return KnowledgeVerificationState.REJECTED
    if any(state is KnowledgeVerificationState.UNRESOLVED for state in states):
        return KnowledgeVerificationState.UNRESOLVED
    if any(state is KnowledgeVerificationState.VERIFIED_WITH_WARNING for state in states):
        return KnowledgeVerificationState.VERIFIED_WITH_WARNING
    if any(state is KnowledgeVerificationState.AUTO_REPAIRED for state in states):
        return KnowledgeVerificationState.AUTO_REPAIRED
    if any(state is KnowledgeVerificationState.AUTHORITY_VERIFIED for state in states):
        return KnowledgeVerificationState.AUTHORITY_VERIFIED
    return KnowledgeVerificationState.VERIFIED


def _numeric_result(value: CollectionSemanticCompileInput) -> NumericGeometryResult:
    return match_numeric_geometry(value.authority_facts, value.parser_numeric_cells)


def _numeric_required(value: CollectionSemanticCompileInput) -> bool:
    return bool(value.numeric_scope_declared or value.authority_facts or value.parser_numeric_cells)


def _numeric_gate_passed(
    value: CollectionSemanticCompileInput,
    result: NumericGeometryResult,
) -> bool:
    if not result.hard_gate.passed:
        return False
    return not _numeric_required(value) or bool(result.publishable_matches)


def _build_canonical_model(
    value: CollectionSemanticCompileInput,
    *,
    architecture_plan: dict[str, Any],
    architecture_plan_sha256: str,
    blueprints: tuple[SemanticBlueprintManifest, ...],
    numeric_result: NumericGeometryResult,
) -> CanonicalKnowledgeModel:
    tenant_id = str(value.tenant_id)
    collection_id = str(value.collection_id)
    activity_id = f"architecture-plan:{value.architecture_plan_id}"
    block_by_id = {block.id: block for block in value.blocks}
    note_by_document: dict[uuid.UUID, list[str]] = {}
    relation_by_document: dict[uuid.UUID, list[str]] = {}
    block_by_document: dict[uuid.UUID, list[str]] = {}
    region_by_document: dict[str, list[str]] = {}
    objects = []

    for block in value.blocks:
        object_id = canonical_object_id(KnowledgeObjectKind.BLOCK, block.id)
        block_by_document.setdefault(block.document_id, []).append(object_id)
        objects.append(
            build_knowledge_object(
                stable_id=object_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.BLOCK,
                source_refs=block.source_refs,
                origin=block.origin,
                verification_state=block.verification_state,
                created_by_activity=activity_id,
                version=1,
                payload={
                    "document_id": str(block.document_id),
                    "block_type": block.block_type,
                    "text": block.text,
                    **block.payload,
                },
            )
        )

    for note in value.notes:
        object_id = canonical_object_id(KnowledgeObjectKind.NOTE, note.id)
        note_by_document.setdefault(note.document_id, []).append(object_id)
        objects.append(
            build_knowledge_object(
                stable_id=object_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.NOTE,
                source_refs=_source_refs_for_evidence(note.evidence_block_ids, block_by_id),
                origin=note.origin,
                verification_state=note.verification_state,
                created_by_activity=activity_id,
                version=1,
                links=tuple(
                    canonical_object_id(KnowledgeObjectKind.BLOCK, block_id)
                    for block_id in note.evidence_block_ids
                ),
                payload={
                    "document_id": str(note.document_id),
                    "stable_key": note.stable_key,
                    "title": note.title,
                    "note_type": note.note_type,
                    "content_markdown": note.content_markdown,
                    "evidence_block_ids": [str(item) for item in note.evidence_block_ids],
                    **note.payload,
                },
            )
        )

    for entity in value.entities:
        objects.append(
            build_knowledge_object(
                stable_id=canonical_object_id(KnowledgeObjectKind.ENTITY, entity.id),
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.ENTITY,
                source_refs=_source_refs_for_evidence(entity.evidence_block_ids, block_by_id),
                origin=entity.origin,
                verification_state=entity.verification_state,
                created_by_activity=activity_id,
                version=1,
                links=tuple(
                    canonical_object_id(KnowledgeObjectKind.BLOCK, block_id)
                    for block_id in entity.evidence_block_ids
                ),
                payload={
                    "stable_key": entity.stable_key,
                    "entity_type": entity.entity_type,
                    "label": entity.label,
                    "evidence_block_ids": [str(item) for item in entity.evidence_block_ids],
                    **entity.payload,
                },
            )
        )

    for relation in value.relations:
        object_id = canonical_object_id(KnowledgeObjectKind.RELATION, relation.id)
        if relation.document_id is not None:
            relation_by_document.setdefault(relation.document_id, []).append(object_id)
        objects.append(
            build_knowledge_object(
                stable_id=object_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.RELATION,
                source_refs=_source_refs_for_evidence(relation.evidence_block_ids, block_by_id),
                origin=relation.origin,
                verification_state=relation.verification_state,
                created_by_activity=activity_id,
                version=1,
                links=tuple(
                    canonical_object_id(KnowledgeObjectKind.BLOCK, block_id)
                    for block_id in relation.evidence_block_ids
                ),
                payload={
                    "document_id": (
                        str(relation.document_id) if relation.document_id is not None else None
                    ),
                    "subject_id": relation.subject_id,
                    "predicate": relation.predicate,
                    "object_id": relation.object_id,
                    "evidence_block_ids": [str(item) for item in relation.evidence_block_ids],
                    **relation.payload,
                },
            )
        )

    for region in value.regions:
        object_id = canonical_object_id(KnowledgeObjectKind.REGION, region.id)
        for source in region.source_refs:
            region_by_document.setdefault(source.document_id, []).append(object_id)
        objects.append(
            build_knowledge_object(
                stable_id=object_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.REGION,
                source_refs=region.source_refs,
                origin=KnowledgeOrigin.STRUCTURED_DERIVED,
                verification_state=region.verification_state,
                created_by_activity=activity_id,
                version=1,
                payload={
                    "region_type": region.region_type,
                    "repair_stages_completed": [
                        stage.value for stage in region.repair_stages_completed
                    ],
                    "independent_signal_count": region.independent_signal_count,
                    "findings": [finding.model_dump(mode="json") for finding in region.findings],
                    **region.payload,
                },
            )
        )

    numeric_objects: list[str] = []
    cell_by_id = {cell.parser_cell_id: cell for cell in value.parser_numeric_cells}
    for match in numeric_result.publishable_matches:
        source = value.numeric_source_refs[match.parser_cell_id]
        object_id = canonical_object_id(
            KnowledgeObjectKind.EVIDENCE,
            f"numeric:{match.authority_fact_id}:{match.parser_cell_id}",
        )
        numeric_objects.append(object_id)
        objects.append(
            build_knowledge_object(
                stable_id=object_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.EVIDENCE,
                source_refs=(source,),
                origin=KnowledgeOrigin.AUTHORITY_RECONSTRUCTED,
                verification_state=KnowledgeVerificationState.AUTHORITY_VERIFIED,
                created_by_activity=activity_id,
                version=1,
                payload={
                    "numeric_authority_merge": match.model_dump(mode="json", by_alias=True),
                    "geometry_source": cell_by_id[match.parser_cell_id].geometry_source.value,
                },
            )
        )

    root_source = min(
        (source for document in value.documents for source in document.source_refs),
        key=canonical_json,
    )
    for blueprint in blueprints:
        objects.append(
            build_knowledge_object(
                stable_id=canonical_object_id(
                    KnowledgeObjectKind.ASSET,
                    f"blueprint:{blueprint.blueprint_id}:{blueprint.blueprint_version}",
                ),
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.ASSET,
                source_refs=(root_source,),
                origin=KnowledgeOrigin.RULE_DERIVED,
                verification_state=KnowledgeVerificationState.VERIFIED,
                created_by_activity=activity_id,
                version=1,
                payload={
                    "semantic_role": "knowledge_blueprint_module",
                    "manifest": blueprint.model_dump(mode="json"),
                },
            )
        )

    for module in value.output_modules:
        objects.append(
            build_knowledge_object(
                stable_id=canonical_object_id(
                    KnowledgeObjectKind.ASSET, f"compile-module:{module.id}"
                ),
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.ASSET,
                source_refs=(root_source,),
                origin=KnowledgeOrigin.RULE_DERIVED,
                verification_state=KnowledgeVerificationState.VERIFIED,
                created_by_activity=activity_id,
                version=1,
                payload={
                    "semantic_role": "architecture_output_module",
                    "module_id": str(module.id),
                    "module_key": module.module_key,
                    "module_version": module.module_version,
                    "status": module.status,
                    "config": module.config,
                    "config_sha256": sha256_digest(canonical_json(module.config)),
                    "output_summary": module.output_summary,
                    "output_sha256": sha256_digest(canonical_json(module.output_summary)),
                },
            )
        )

    validation_id = canonical_object_id(
        KnowledgeObjectKind.VALIDATION_RECORD,
        f"numeric:{value.architecture_plan_id}",
    )
    objects.append(
        build_knowledge_object(
            stable_id=validation_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            kind=KnowledgeObjectKind.VALIDATION_RECORD,
            source_refs=(root_source,),
            origin=KnowledgeOrigin.RULE_DERIVED,
            verification_state=(
                KnowledgeVerificationState.AUTHORITY_VERIFIED
                if _numeric_gate_passed(value, numeric_result) and _numeric_required(value)
                else KnowledgeVerificationState.VERIFIED
                if _numeric_gate_passed(value, numeric_result)
                else KnowledgeVerificationState.UNRESOLVED
            ),
            created_by_activity=activity_id,
            version=1,
            links=tuple(numeric_objects),
            payload={
                "semantic_role": "numeric_geometry_validation",
                "result": numeric_result.model_dump(mode="json", by_alias=True),
                "numeric_scope_declared": value.numeric_scope_declared,
            },
        )
    )

    for document in value.documents:
        links = sorted(
            [
                *block_by_document.get(document.id, ()),
                *note_by_document.get(document.id, ()),
                *relation_by_document.get(document.id, ()),
                *region_by_document.get(str(document.id), ()),
            ]
        )
        document_states = [
            block.verification_state for block in value.blocks if block.document_id == document.id
        ]
        objects.append(
            build_knowledge_object(
                stable_id=canonical_object_id(KnowledgeObjectKind.DOCUMENT, document.id),
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=KnowledgeObjectKind.DOCUMENT,
                source_refs=document.source_refs,
                origin=KnowledgeOrigin.NATIVE_EXTRACTED,
                verification_state=_aggregate_verification_state(document_states),
                created_by_activity=activity_id,
                version=1,
                links=tuple(links),
                payload={
                    "document_version_id": document.document_version_id,
                    "title": document.title,
                    **document.payload,
                },
            )
        )

    collection_state = _aggregate_verification_state([item.verification_state for item in objects])
    child_ids = sorted(item.stable_id for item in objects)
    objects.append(
        build_knowledge_object(
            stable_id=canonical_object_id(KnowledgeObjectKind.COLLECTION, value.collection_id),
            tenant_id=tenant_id,
            collection_id=collection_id,
            kind=KnowledgeObjectKind.COLLECTION,
            source_refs=(root_source,),
            origin=KnowledgeOrigin.RULE_DERIVED,
            verification_state=collection_state,
            created_by_activity=activity_id,
            version=1,
            links=tuple(child_ids),
            payload={
                "project_id": str(value.project_id),
                "architecture_plan_id": str(value.architecture_plan_id),
                "architecture_plan_version": value.architecture_plan_version,
                "architecture_plan_sha256": architecture_plan_sha256,
                "architecture_plan": architecture_plan,
                "input_integrity_sha256": f"sha256:{value.input_integrity_sha256}",
                "knowledge_blueprint_ids": [blueprint.blueprint_id for blueprint in blueprints],
            },
        )
    )
    return CanonicalKnowledgeModel(
        tenant_id=tenant_id,
        collection_id=collection_id,
        objects=tuple(sorted(objects, key=lambda item: item.stable_id)),
    )


class RegionRuntimeDecision(_RuntimeModel):
    region_id: uuid.UUID
    declared_state: KnowledgeVerificationState
    decision: AutonomousVerificationDecision


class RetrievalIndexExpectation(_RuntimeModel):
    stable_id: Annotated[str, Field(min_length=1, max_length=240)]
    document_id: uuid.UUID
    source_hash: Annotated[str, Field(pattern=_SHA256)]
    evidence_block_ids: Annotated[tuple[uuid.UUID, ...], Field(min_length=1, max_length=100)]
    lexical_text: Annotated[str, Field(min_length=1, max_length=2_000_000)]
    verification_state: VerificationState


class CollectionRuntimeOutboxEvent(_RuntimeModel):
    tenant_id: uuid.UUID
    aggregate_id: uuid.UUID
    event_type: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{2,119}$")]
    payload: dict[str, Any]


@runtime_checkable
class CollectionRuntimeOutbox(Protocol):
    async def append(self, event: CollectionRuntimeOutboxEvent) -> None: ...


class SQLAlchemyCollectionRuntimeOutbox:
    """Persist the receipt event in the caller-owned collection transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: CollectionRuntimeOutboxEvent) -> None:
        self._session.add(
            OutboxEvent(
                tenant_id=event.tenant_id,
                aggregate_type="collection",
                aggregate_id=event.aggregate_id,
                event_type=event.event_type,
                payload=event.payload,
            )
        )
        await self._session.flush()


class PreparedCollectionSemanticRuntime(_RuntimeModel):
    compile_input: CollectionSemanticCompileInput
    architecture_plan: dict[str, Any]
    architecture_plan_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    blueprint_modules: tuple[SemanticBlueprintManifest, ...]
    selected_blueprint: SemanticBlueprintManifest
    canonical_model: CanonicalKnowledgeModel
    canonical_model_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    semantic_profile: KnowledgePackageSemanticProfile
    numeric_result: NumericGeometryResult
    region_decisions: tuple[RegionRuntimeDecision, ...]
    pre_index_reports: tuple[AgentReport, ...]
    preliminary_decision: AutonomousVerificationDecision
    index_expectations: tuple[RetrievalIndexExpectation, ...]
    graph_edges: tuple[RetrievalIndexEdge, ...]
    ready_for_index: bool

    @model_validator(mode="after")
    def validate_readiness(self) -> PreparedCollectionSemanticRuntime:
        expected = all(report.passed for report in self.pre_index_reports)
        if self.ready_for_index is not expected:
            raise ValueError("semantic runtime readiness must equal all pre-index gates")
        if self.semantic_profile.canonical_model_sha256 != self.canonical_model_sha256:
            raise ValueError("semantic profile and canonical model digest differ")
        return self


class CollectionSemanticRuntimeResult(_RuntimeModel):
    accepted: bool
    billable: bool
    state: AutonomousState
    reason_codes: tuple[str, ...]
    architecture_plan: dict[str, Any]
    architecture_plan_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    canonical_model: CanonicalKnowledgeModel
    canonical_model_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    semantic_profile: KnowledgePackageSemanticProfile
    numeric_result: NumericGeometryResult
    region_decisions: tuple[RegionRuntimeDecision, ...]
    decision: AutonomousVerificationDecision
    retrieval_receipt: RetrievalIndexReceipt | None = None
    outbox_event: CollectionRuntimeOutboxEvent | None = None

    @model_validator(mode="after")
    def enforce_completion_receipts(self) -> CollectionSemanticRuntimeResult:
        if (
            self.accepted != self.decision.accepted
            or self.billable != self.decision.billable
            or self.state is not self.decision.state
            or self.reason_codes != self.decision.reason_codes
        ):
            raise ValueError("runtime result must mirror the autonomous decision")
        if self.accepted != (self.retrieval_receipt is not None and self.outbox_event is not None):
            raise ValueError("accepted semantic runtime requires index and outbox receipts")
        return self


def _reports(
    overrides: Mapping[VerificationAgent, AgentReport],
) -> tuple[AgentReport, ...]:
    expected = set(VerificationAgent)
    supplied = set(overrides)
    if supplied != expected:
        missing = sorted(agent.value for agent in expected - supplied)
        extra = sorted(str(agent) for agent in supplied - expected)
        raise ValueError(f"verification reports must be explicit: missing={missing}; extra={extra}")
    reports = tuple(overrides[agent] for agent in VerificationAgent)
    for agent, report in zip(VerificationAgent, reports, strict=True):
        if report.agent is not agent:
            raise ValueError("verification report key and agent mismatch")
        if not report.findings or not any(finding.source_refs for finding in report.findings):
            raise ValueError(f"{report.agent.value} report requires an evidence receipt")
    return reports


def _finding(
    code: str,
    level: FindingLevel,
    detail: str = "",
    *,
    source_refs: Sequence[str] = (),
) -> AgentFinding:
    return AgentFinding(
        code=code,
        level=level,
        detail=detail,
        source_refs=tuple(source_refs),
    )


def _scope_receipt(scope: str, payload: Any) -> str:
    return sha256_digest(canonical_json({"scope": scope, "payload": payload}))


def _scope_finding(
    agent: VerificationAgent,
    payload: Any,
    *,
    applicable: bool,
) -> AgentFinding:
    suffix = "verified" if applicable else "scope_not_applicable"
    return _finding(
        f"{agent.value}_{suffix}",
        FindingLevel.INFO,
        source_refs=(_scope_receipt(agent.value, payload),),
    )


def _source_integrity_report(value: CollectionSemanticCompileInput) -> AgentReport:
    findings: list[AgentFinding] = []
    for document in value.documents:
        missing_receipt_ref = _scope_receipt(
            "source_integrity_missing",
            {
                "document_id": str(document.id),
                "document_version_id": document.document_version_id,
                "source_refs": [source.model_dump(mode="json") for source in document.source_refs],
            },
        )
        receipt = document.integrity_receipt
        if receipt is None:
            findings.append(
                _finding(
                    "source_integrity_receipt_missing",
                    FindingLevel.HARD,
                    str(document.id),
                    source_refs=(missing_receipt_ref,),
                )
            )
            continue
        receipt_refs = (receipt.receipt_sha256,)
        if receipt.receipt_sha256 != _source_integrity_receipt_sha256(
            _receipt_payload(receipt)
        ):
            findings.append(
                _finding(
                    "source_integrity_receipt_mismatch",
                    FindingLevel.HARD,
                    str(document.id),
                    source_refs=receipt_refs,
                )
            )
        if (
            receipt.document_id != document.id
            or receipt.document_version_id != document.document_version_id
        ):
            findings.append(
                _finding(
                    "source_integrity_scope_mismatch",
                    FindingLevel.HARD,
                    str(document.id),
                    source_refs=receipt_refs,
                )
            )
        if receipt.source_sha256 != receipt.collection_file_sha256:
            findings.append(
                _finding(
                    "source_hash_mismatch",
                    FindingLevel.SECURITY,
                    str(document.id),
                    source_refs=receipt_refs,
                )
            )
        if receipt.source_size_bytes != receipt.collection_file_size_bytes:
            findings.append(
                _finding(
                    "source_size_mismatch",
                    FindingLevel.HARD,
                    str(document.id),
                    source_refs=receipt_refs,
                )
            )
        if receipt.collection_file_status not in {"verified", "duplicate"}:
            findings.append(
                _finding(
                    "collection_file_receipt_unverified",
                    FindingLevel.HARD,
                    receipt.collection_file_status,
                    source_refs=receipt_refs,
                )
            )
        antivirus_status = receipt.antivirus_status.casefold()
        if antivirus_status != "clean":
            code = (
                "malware_detected"
                if antivirus_status in {"infected", "malware", "quarantined", "rejected"}
                else "antivirus_receipt_unresolved"
            )
            level = FindingLevel.SECURITY if code == "malware_detected" else FindingLevel.HARD
            findings.append(
                _finding(
                    code,
                    level,
                    receipt.antivirus_status,
                    source_refs=receipt_refs,
                )
            )
        cdr_status = receipt.cdr_status.casefold()
        if cdr_status == "rejected":
            findings.append(
                _finding(
                    "active_content",
                    FindingLevel.SECURITY,
                    receipt.cdr_status,
                    source_refs=receipt_refs,
                )
            )
        elif cdr_status not in {"not_requested", "sanitized", "unsupported"}:
            findings.append(
                _finding(
                    "cdr_receipt_unresolved",
                    FindingLevel.HARD,
                    receipt.cdr_status,
                    source_refs=receipt_refs,
                )
            )
        if receipt.expected_page_count <= 0:
            findings.append(
                _finding(
                    "expected_page_count_missing",
                    FindingLevel.HARD,
                    str(document.id),
                    source_refs=receipt_refs,
                )
            )
        if receipt.expected_page_count != receipt.observed_page_count:
            findings.append(
                _finding(
                    "page_count_mismatch",
                    FindingLevel.HARD,
                    (
                        f"expected={receipt.expected_page_count};"
                        f"observed={receipt.observed_page_count}"
                    ),
                    source_refs=receipt_refs,
                )
            )
        if receipt.terminal_page_count != receipt.observed_page_count:
            findings.append(
                _finding(
                    "page_terminal_evidence_incomplete",
                    FindingLevel.HARD,
                    (
                        f"terminal={receipt.terminal_page_count};"
                        f"observed={receipt.observed_page_count}"
                    ),
                    source_refs=receipt_refs,
                )
            )
        if receipt.rendered_page_count != receipt.render_required_page_count:
            findings.append(
                _finding(
                    "render_receipt_incomplete",
                    FindingLevel.HARD,
                    (
                        f"required={receipt.render_required_page_count};"
                        f"rendered={receipt.rendered_page_count}"
                    ),
                    source_refs=receipt_refs,
                )
            )
        if receipt.render_corruption_count:
            findings.append(
                _finding(
                    "render_corruption_detected",
                    FindingLevel.HARD,
                    str(receipt.render_corruption_count),
                    source_refs=receipt_refs,
                )
            )
        if not any(
            finding.level in {FindingLevel.HARD, FindingLevel.SECURITY}
            and receipt.receipt_sha256 in finding.source_refs
            for finding in findings
        ):
            findings.append(
                _finding(
                    "source_integrity_verified",
                    FindingLevel.INFO,
                    str(document.id),
                    source_refs=receipt_refs,
                )
            )
    passed = not any(
        finding.level in {FindingLevel.HARD, FindingLevel.SECURITY} for finding in findings
    )
    return AgentReport(
        agent=VerificationAgent.SOURCE_INTEGRITY,
        passed=passed,
        findings=tuple(findings),
    )


def _source_reference_is_valid(
    source: SourceRef,
    documents: Mapping[uuid.UUID, SemanticDocumentInput],
    *,
    expected_document_id: uuid.UUID | None = None,
) -> bool:
    try:
        document_id = uuid.UUID(source.document_id)
    except ValueError:
        return False
    document = documents.get(document_id)
    if document is None or (
        expected_document_id is not None and document_id != expected_document_id
    ):
        return False
    receipt = document.integrity_receipt
    return bool(
        receipt is not None
        and source.document_version_id == document.document_version_id
        and source.page_index0 + 1 == source.page_number1
        and 1 <= source.page_number1 <= receipt.expected_page_count
    )


def _citation_report(value: CollectionSemanticCompileInput) -> AgentReport:
    receipt = _scope_receipt(
        "citation",
        {
            "documents": [str(item.id) for item in value.documents],
            "blocks": [str(item.id) for item in value.blocks],
            "notes": [str(item.id) for item in value.notes],
            "entities": [str(item.id) for item in value.entities],
            "relations": [str(item.id) for item in value.relations],
        },
    )
    findings: list[AgentFinding] = []
    documents = {document.id: document for document in value.documents}
    blocks = {block.id: block for block in value.blocks}
    for document in value.documents:
        expected_pages = (
            set(range(1, document.integrity_receipt.expected_page_count + 1))
            if document.integrity_receipt is not None
            else set()
        )
        covered_pages = {
            source.page_number1
            for source in document.source_refs
            if _source_reference_is_valid(
                source,
                documents,
                expected_document_id=document.id,
            )
        }
        if covered_pages != expected_pages or not expected_pages:
            findings.append(
                _finding(
                    "document_source_ref_coverage_incomplete",
                    FindingLevel.HARD,
                    str(document.id),
                    source_refs=(receipt,),
                )
            )
    for block in value.blocks:
        if not all(
            _source_reference_is_valid(
                source,
                documents,
                expected_document_id=block.document_id,
            )
            for source in block.source_refs
        ):
            findings.append(
                _finding(
                    "block_source_ref_invalid",
                    FindingLevel.HARD,
                    str(block.id),
                    source_refs=(receipt,),
                )
            )
    for region in value.regions:
        if not all(_source_reference_is_valid(source, documents) for source in region.source_refs):
            findings.append(
                _finding(
                    "region_source_ref_invalid",
                    FindingLevel.HARD,
                    str(region.id),
                    source_refs=(receipt,),
                )
            )
    for parser_cell_id, source in value.numeric_source_refs.items():
        if not _source_reference_is_valid(source, documents):
            findings.append(
                _finding(
                    "numeric_source_ref_invalid",
                    FindingLevel.HARD,
                    parser_cell_id,
                    source_refs=(receipt,),
                )
            )
    for note in value.notes:
        if any(
            blocks[block_id].document_id != note.document_id
            for block_id in note.evidence_block_ids
        ):
            findings.append(
                _finding(
                    "note_evidence_scope_mismatch",
                    FindingLevel.HARD,
                    str(note.id),
                    source_refs=(receipt,),
                )
            )
    for relation in value.relations:
        if relation.document_id is not None and any(
            blocks[block_id].document_id != relation.document_id
            for block_id in relation.evidence_block_ids
        ):
            findings.append(
                _finding(
                    "relation_evidence_scope_mismatch",
                    FindingLevel.HARD,
                    str(relation.id),
                    source_refs=(receipt,),
                )
            )
    if not findings:
        findings.append(
            _finding(
                "citation_evidence_coverage_verified",
                FindingLevel.INFO,
                source_refs=(receipt,),
            )
        )
    return AgentReport(
        agent=VerificationAgent.CITATION,
        passed=not any(finding.level is FindingLevel.HARD for finding in findings),
        findings=tuple(findings),
    )


def _source_reference_coverage(value: CollectionSemanticCompileInput) -> float:
    documents = {document.id: document for document in value.documents}
    obligations = 0
    satisfied = 0
    for document in value.documents:
        receipt = document.integrity_receipt
        expected = receipt.expected_page_count if receipt is not None else 1
        obligations += max(expected, 1)
        valid_pages = {
            source.page_number1
            for source in document.source_refs
            if _source_reference_is_valid(
                source,
                documents,
                expected_document_id=document.id,
            )
        }
        satisfied += min(len(valid_pages), max(expected, 1))
    scoped_sources: tuple[tuple[SourceRef, uuid.UUID | None], ...] = (
        *((source, block.document_id) for block in value.blocks for source in block.source_refs),
        *((source, None) for region in value.regions for source in region.source_refs),
        *((source, None) for source in value.numeric_source_refs.values()),
    )
    obligations += len(scoped_sources)
    satisfied += sum(
        _source_reference_is_valid(source, documents, expected_document_id=document_id)
        for source, document_id in scoped_sources
    )
    return satisfied / obligations if obligations else 0.0


def _relation_endpoint_failures(value: CollectionSemanticCompileInput) -> tuple[str, ...]:
    aliases: set[str] = set()
    for note in value.notes:
        aliases.update(
            {
                canonical_object_id(KnowledgeObjectKind.NOTE, note.id),
                str(note.id),
                note.stable_key,
                f"note:{note.stable_key}",
            }
        )
    for entity in value.entities:
        aliases.update(
            {
                canonical_object_id(KnowledgeObjectKind.ENTITY, entity.id),
                str(entity.id),
                entity.stable_key,
                f"entity:{entity.stable_key}",
            }
        )
    for block in value.blocks:
        aliases.update(
            {
                canonical_object_id(KnowledgeObjectKind.BLOCK, block.id),
                str(block.id),
            }
        )
    return tuple(
        str(relation.id)
        for relation in value.relations
        if (
            relation.subject_id not in aliases
            or relation.object_id not in aliases
            or relation.subject_id == relation.object_id
        )
    )


def _region_is_high_risk(region: SemanticRegionInput) -> bool:
    kind = region.region_type.casefold()
    return "table" in kind or "numeric" in kind or "financial" in kind


def _region_runtime_decision(
    region: SemanticRegionInput,
    *,
    numeric_result: NumericGeometryResult,
    numeric_gate_passed: bool,
) -> RegionRuntimeDecision:
    region_receipt = _scope_receipt(
        "region_verification",
        {
            "region_id": str(region.id),
            "region_type": region.region_type,
            "source_refs": [source.model_dump(mode="json") for source in region.source_refs],
            "repair_stages": [stage.value for stage in region.repair_stages_completed],
            "independent_signal_count": region.independent_signal_count,
        },
    )
    structure_findings = list(region.findings)
    if region.verification_state is KnowledgeVerificationState.UNRESOLVED and not any(
        finding.level is FindingLevel.HARD for finding in structure_findings
    ):
        structure_findings.append(
            _finding(
                "durable_region_unresolved",
                FindingLevel.HARD,
                source_refs=(region_receipt,),
            )
        )
    if region.verification_state is KnowledgeVerificationState.QUARANTINED and not any(
        finding.level is FindingLevel.SECURITY for finding in structure_findings
    ):
        structure_findings.append(
            _finding(
                "durable_region_quarantined",
                FindingLevel.SECURITY,
                source_refs=(region_receipt,),
            )
        )
    if region.verification_state is KnowledgeVerificationState.REJECTED:
        structure_findings.append(
            _finding(
                "durable_region_rejected",
                FindingLevel.HARD,
                source_refs=(region_receipt,),
            )
        )
    if region.verification_state is KnowledgeVerificationState.VERIFIED_WITH_WARNING and not any(
        finding.level is FindingLevel.WARNING for finding in structure_findings
    ):
        structure_findings.append(
            _finding(
                "durable_region_warning",
                FindingLevel.WARNING,
                source_refs=(region_receipt,),
            )
        )
    structure_findings = [
        finding
        if finding.source_refs
        else finding.model_copy(update={"source_refs": (region_receipt,)})
        for finding in structure_findings
    ]
    if not structure_findings:
        structure_findings.append(
            _scope_finding(
                VerificationAgent.STRUCTURE,
                {"region_receipt": region_receipt},
                applicable=True,
            )
        )

    high_risk = _region_is_high_risk(region)
    numeric_passed = not high_risk or numeric_gate_passed
    numeric_findings: tuple[AgentFinding, ...]
    if not numeric_passed:
        codes = numeric_result.reason_codes or ("numeric_authority_evidence_missing",)
        numeric_findings = tuple(
            _finding(code, FindingLevel.HARD, source_refs=(region_receipt,)) for code in codes
        )
    else:
        numeric_findings = (
            _scope_finding(
                VerificationAgent.NUMERIC,
                {
                    "region_receipt": region_receipt,
                    "publishable_matches": len(numeric_result.publishable_matches),
                },
                applicable=high_risk,
            ),
        )
    differential_applicable = bool(region.repair_stages_completed)
    differential_passed = not differential_applicable or region.independent_signal_count > 0
    differential_findings = (
        (
            _scope_finding(
                VerificationAgent.DIFFERENTIAL,
                {
                    "region_receipt": region_receipt,
                    "independent_signal_count": region.independent_signal_count,
                },
                applicable=differential_applicable,
            ),
        )
        if differential_passed
        else (
            _finding(
                "differential_evidence_missing",
                FindingLevel.HARD,
                source_refs=(region_receipt,),
            ),
        )
    )

    def report_map() -> dict[VerificationAgent, AgentReport]:
        not_applicable = {
            agent: AgentReport(
                agent=agent,
                passed=True,
                findings=(
                    _scope_finding(
                        agent,
                        {"region_receipt": region_receipt},
                        applicable=False,
                    ),
                ),
            )
            for agent in (
                VerificationAgent.SOURCE_INTEGRITY,
                VerificationAgent.CITATION,
                VerificationAgent.KNOWLEDGE,
                VerificationAgent.EXPORT,
                VerificationAgent.RETRIEVAL,
            )
        }
        return {
            **not_applicable,
            VerificationAgent.STRUCTURE: AgentReport(
                agent=VerificationAgent.STRUCTURE,
                passed=not any(
                    finding.level in {FindingLevel.HARD, FindingLevel.SECURITY}
                    for finding in structure_findings
                ),
                findings=tuple(structure_findings),
            ),
            VerificationAgent.NUMERIC: AgentReport(
                agent=VerificationAgent.NUMERIC,
                passed=numeric_passed,
                findings=numeric_findings,
                authority_confirmed=(
                    high_risk and numeric_passed and bool(numeric_result.publishable_matches)
                ),
            ),
            VerificationAgent.DIFFERENTIAL: AgentReport(
                agent=VerificationAgent.DIFFERENTIAL,
                passed=differential_passed,
                findings=differential_findings,
                independent_signal_count=region.independent_signal_count,
            ),
        }

    overrides = report_map()
    decision = decide_autonomously(
        AutonomousVerificationInput(
            reports=_reports(overrides),
            high_risk=high_risk,
            repair_stages_completed=region.repair_stages_completed,
        )
    )
    if decision.state.value != region.verification_state.value:
        structure_findings.append(
            _finding(
                "region_state_attestation_mismatch",
                FindingLevel.HARD,
                f"declared={region.verification_state.value};derived={decision.state.value}",
                source_refs=(region_receipt,),
            )
        )
        overrides = report_map()
        decision = decide_autonomously(
            AutonomousVerificationInput(
                reports=_reports(overrides),
                high_risk=high_risk,
                repair_stages_completed=region.repair_stages_completed,
            )
        )
    return RegionRuntimeDecision(
        region_id=region.id,
        declared_state=region.verification_state,
        decision=decision,
    )


def _pre_index_reports(
    value: CollectionSemanticCompileInput,
    *,
    model: CanonicalKnowledgeModel,
    numeric_result: NumericGeometryResult,
    region_decisions: tuple[RegionRuntimeDecision, ...],
    semantic_round_trip: bool,
) -> tuple[AgentReport, ...]:
    model_sha256 = sha256_digest(canonical_json(model.model_dump(mode="json")))
    numeric_passed = _numeric_gate_passed(value, numeric_result)
    numeric_receipt = _scope_receipt(
        "numeric_verification",
        {
            "numeric_scope_declared": value.numeric_scope_declared,
            "authority_fact_ids": [item.fact_id for item in value.authority_facts],
            "parser_cell_ids": [item.parser_cell_id for item in value.parser_numeric_cells],
            "result": numeric_result.model_dump(mode="json"),
        },
    )
    numeric_findings: tuple[AgentFinding, ...]
    if numeric_passed:
        numeric_findings = (
            _scope_finding(
                VerificationAgent.NUMERIC,
                {
                    "numeric_receipt": numeric_receipt,
                    "publishable_matches": len(numeric_result.publishable_matches),
                },
                applicable=_numeric_required(value),
            ),
        )
    else:
        numeric_findings = tuple(
            _finding(code, FindingLevel.HARD, source_refs=(numeric_receipt,))
            for code in (
                numeric_result.reason_codes or ("numeric_authority_evidence_missing",)
            )
        )
    region_required = any(
        block.block_type.casefold() in _REGION_REQUIRED_BLOCK_TYPES for block in value.blocks
    )
    region_missing = region_required and not value.regions
    rejected_regions = tuple(item for item in region_decisions if not item.decision.accepted)
    region_receipt = _scope_receipt(
        "collection_regions",
        {
            "required": region_required,
            "regions": [
                {
                    "region_id": str(item.region_id),
                    "accepted": item.decision.accepted,
                    "state": item.decision.state.value,
                    "reason_codes": list(item.decision.reason_codes),
                }
                for item in region_decisions
            ],
        },
    )
    differential_findings = tuple(
        _finding(
            "region_recovery_incomplete",
            FindingLevel.HARD,
            ",".join(str(item.region_id) for item in rejected_regions),
            source_refs=(region_receipt,),
        )
        for _ in [0]
        if rejected_regions
    )
    if region_missing:
        differential_findings += (
            _finding(
                "region_evidence_missing",
                FindingLevel.HARD,
                source_refs=(region_receipt,),
            ),
        )
    unpromoted = tuple(
        item.stable_id for item in model.objects if item.verification_state not in _PROMOTED_STATES
    )
    relation_endpoint_failures = _relation_endpoint_failures(value)
    knowledge_receipt = _scope_receipt(
        "knowledge_graph",
        {
            "model_sha256": model_sha256,
            "object_count": len(model.objects),
            "relation_ids": [str(item.id) for item in value.relations],
        },
    )
    knowledge_findings: tuple[AgentFinding, ...] = ()
    if unpromoted:
        knowledge_findings += (
            _finding(
                "unpromoted_semantic_objects",
                FindingLevel.HARD,
                ",".join(unpromoted[:10]),
                source_refs=(knowledge_receipt,),
            ),
        )
    if relation_endpoint_failures:
        knowledge_findings += (
            _finding(
                "relation_endpoint_unresolved",
                FindingLevel.HARD,
                ",".join(relation_endpoint_failures[:10]),
                source_refs=(knowledge_receipt,),
            ),
        )
    if not knowledge_findings:
        knowledge_findings = (
            _finding(
                "knowledge_graph_verified",
                FindingLevel.INFO,
                source_refs=(knowledge_receipt,),
            ),
        )
    warning_codes = sorted(
        {
            code
            for item in region_decisions
            if item.decision.accepted
            for code in item.decision.reason_codes
        }
    )
    if not differential_findings and not warning_codes:
        differential_findings = (
            _scope_finding(
                VerificationAgent.DIFFERENTIAL,
                {"region_receipt": region_receipt},
                applicable=bool(value.regions or region_required),
            ),
        )
    else:
        differential_findings += tuple(
            _finding(code, FindingLevel.WARNING, source_refs=(region_receipt,))
            for code in warning_codes
        )
    structure_findings = (
        (
            _finding(
                "region_evidence_missing",
                FindingLevel.HARD,
                source_refs=(region_receipt,),
            ),
        )
        if region_missing
        else (
            _scope_finding(
                VerificationAgent.STRUCTURE,
                {"region_receipt": region_receipt, "block_count": len(value.blocks)},
                applicable=bool(value.regions or region_required),
            ),
        )
    )
    export_receipt = _scope_receipt(
        "semantic_export",
        {"model_sha256": model_sha256, "round_trip": semantic_round_trip},
    )
    retrieval_pending_receipt = _scope_receipt(
        "retrieval_pending",
        {"collection_id": str(value.collection_id), "model_sha256": model_sha256},
    )
    return tuple(
        report
        for report in _reports(
            {
                VerificationAgent.SOURCE_INTEGRITY: _source_integrity_report(value),
                VerificationAgent.STRUCTURE: AgentReport(
                    agent=VerificationAgent.STRUCTURE,
                    passed=not region_missing,
                    findings=structure_findings,
                ),
                VerificationAgent.NUMERIC: AgentReport(
                    agent=VerificationAgent.NUMERIC,
                    passed=numeric_passed,
                    findings=numeric_findings,
                    authority_confirmed=(
                        _numeric_required(value)
                        and numeric_passed
                        and bool(numeric_result.publishable_matches)
                    ),
                ),
                VerificationAgent.DIFFERENTIAL: AgentReport(
                    agent=VerificationAgent.DIFFERENTIAL,
                    passed=not any(
                        finding.level in {FindingLevel.HARD, FindingLevel.SECURITY}
                        for finding in differential_findings
                    ),
                    findings=differential_findings,
                    independent_signal_count=max(
                        (region.independent_signal_count for region in value.regions),
                        default=0,
                    ),
                ),
                VerificationAgent.CITATION: _citation_report(value),
                VerificationAgent.KNOWLEDGE: AgentReport(
                    agent=VerificationAgent.KNOWLEDGE,
                    passed=not any(
                        finding.level in {FindingLevel.HARD, FindingLevel.SECURITY}
                        for finding in knowledge_findings
                    ),
                    findings=knowledge_findings,
                ),
                VerificationAgent.EXPORT: AgentReport(
                    agent=VerificationAgent.EXPORT,
                    passed=semantic_round_trip,
                    findings=(
                        (
                            _finding(
                                "semantic_round_trip_verified",
                                FindingLevel.INFO,
                                source_refs=(export_receipt,),
                            ),
                        )
                        if semantic_round_trip
                        else (
                            _finding(
                                "semantic_round_trip_failed",
                                FindingLevel.HARD,
                                source_refs=(export_receipt,),
                            ),
                        )
                    ),
                ),
                VerificationAgent.RETRIEVAL: AgentReport(
                    agent=VerificationAgent.RETRIEVAL,
                    passed=False,
                    findings=(
                        _finding(
                            "retrieval_index_pending",
                            FindingLevel.HARD,
                            source_refs=(retrieval_pending_receipt,),
                        ),
                    ),
                ),
            }
        )
        if report.agent is not VerificationAgent.RETRIEVAL
    )


def _decision_with_retrieval(
    value: CollectionSemanticCompileInput,
    pre_index_reports: tuple[AgentReport, ...],
    retrieval_report: AgentReport,
) -> AutonomousVerificationDecision:
    reports = _reports(
        {report.agent: report for report in (*pre_index_reports, retrieval_report)}
    )
    return decide_autonomously(
        AutonomousVerificationInput(
            reports=reports,
            high_risk=_numeric_required(value),
            schema_valid=True,
            source_coverage=_source_reference_coverage(value),
            unsupported_content_count=sum(not report.passed for report in pre_index_reports),
        )
    )


def _retrieval_expectations(
    value: CollectionSemanticCompileInput,
    model: CanonicalKnowledgeModel,
) -> tuple[RetrievalIndexExpectation, ...]:
    canonical = {item.stable_id: item for item in model.objects}
    expectations: list[RetrievalIndexExpectation] = []
    for note in sorted(value.notes, key=lambda item: str(item.id)):
        if note.verification_state not in _PROMOTED_STATES:
            continue
        stable_id = canonical_object_id(KnowledgeObjectKind.NOTE, note.id)
        semantic_object = canonical[stable_id]
        expectations.append(
            RetrievalIndexExpectation(
                stable_id=stable_id,
                document_id=note.document_id,
                source_hash=semantic_object.hash.removeprefix("sha256:"),
                evidence_block_ids=note.evidence_block_ids,
                lexical_text=note.content_markdown,
                verification_state=VerificationState(note.verification_state.value),
            )
        )
    return tuple(expectations)


def _retrieval_edges(
    value: CollectionSemanticCompileInput,
) -> tuple[RetrievalIndexEdge, ...]:
    aliases: dict[str, str] = {}
    for note in value.notes:
        canonical = canonical_object_id(KnowledgeObjectKind.NOTE, note.id)
        for alias in (canonical, str(note.id), note.stable_key, f"note:{note.stable_key}"):
            aliases[alias] = canonical
    for entity in value.entities:
        canonical = canonical_object_id(KnowledgeObjectKind.ENTITY, entity.id)
        for alias in (canonical, str(entity.id), entity.stable_key, f"entity:{entity.stable_key}"):
            aliases[alias] = canonical
    for block in value.blocks:
        canonical = canonical_object_id(KnowledgeObjectKind.BLOCK, block.id)
        aliases[canonical] = canonical
        aliases[str(block.id)] = canonical

    edges: dict[tuple[str, str], RetrievalIndexEdge] = {}
    for relation in value.relations:
        if relation.verification_state not in _PROMOTED_STATES:
            continue
        source = aliases.get(relation.subject_id)
        target = aliases.get(relation.object_id)
        if source is None or target is None or source == target:
            continue
        edge = RetrievalIndexEdge(
            project_id=value.project_id,
            from_stable_id=source,
            to_stable_id=target,
            edge_weight=1.0,
        )
        edges[(source, target)] = edge
    return tuple(edges[key] for key in sorted(edges))


def prepare_collection_semantic_runtime(
    value: CollectionSemanticCompileInput,
) -> PreparedCollectionSemanticRuntime:
    """Build and validate semantic truth without performing external writes."""

    blueprints = builtin_semantic_blueprint_manifests()
    actual_registry_sha256 = semantic_blueprint_registry_sha256(blueprints)
    if value.knowledge_blueprint_registry_sha256 != actual_registry_sha256:
        raise ValueError("knowledge blueprint registry hash mismatch")
    selected = next(
        (
            blueprint
            for blueprint in blueprints
            if blueprint.blueprint_id == value.knowledge_blueprint_id
        ),
        None,
    )
    if selected is None:
        raise ValueError("knowledge blueprint is not in the verified registry")
    if selected.module_sha256 != value.knowledge_blueprint_module_sha256:
        raise ValueError("knowledge blueprint module hash mismatch")
    if {module.module_key for module in value.output_modules} != _OUTPUT_MODULE_KEYS:
        raise ValueError("semantic compile requires all seven output modules")

    plan, plan_sha256 = _architecture_plan_with_semantics(value, blueprints)
    numeric_result = _numeric_result(value)
    model = _build_canonical_model(
        value,
        architecture_plan=plan,
        architecture_plan_sha256=plan_sha256,
        blueprints=blueprints,
        numeric_result=numeric_result,
    )
    canonical_payload = canonical_knowledge_model_bytes(model)
    round_tripped = CanonicalKnowledgeModel.model_validate_json(canonical_payload)
    semantic_round_trip = (
        round_tripped == model
        and canonical_knowledge_model_bytes(round_tripped) == canonical_payload
    )
    profile = knowledge_package_semantic_profile(
        model,
        blueprint_modules=blueprints,
    )
    numeric_passed = _numeric_gate_passed(value, numeric_result)
    region_decisions = tuple(
        _region_runtime_decision(
            region,
            numeric_result=numeric_result,
            numeric_gate_passed=numeric_passed,
        )
        for region in sorted(value.regions, key=lambda item: str(item.id))
    )
    reports = _pre_index_reports(
        value,
        model=model,
        numeric_result=numeric_result,
        region_decisions=region_decisions,
        semantic_round_trip=semantic_round_trip,
    )
    preliminary = _decision_with_retrieval(
        value,
        reports,
        AgentReport(
            agent=VerificationAgent.RETRIEVAL,
            passed=False,
            findings=(
                _finding(
                    "retrieval_not_attempted_due_to_gate",
                    FindingLevel.HARD,
                    source_refs=(
                        _scope_receipt(
                            "retrieval_not_attempted",
                            {
                                "collection_id": str(value.collection_id),
                                "failed_pre_index_agents": [
                                    report.agent.value for report in reports if not report.passed
                                ],
                            },
                        ),
                    ),
                ),
            ),
        ),
    )
    return PreparedCollectionSemanticRuntime(
        compile_input=value,
        architecture_plan=plan,
        architecture_plan_sha256=plan_sha256,
        blueprint_modules=blueprints,
        selected_blueprint=selected,
        canonical_model=model,
        canonical_model_sha256=profile.canonical_model_sha256,
        semantic_profile=profile,
        numeric_result=numeric_result,
        region_decisions=region_decisions,
        pre_index_reports=reports,
        preliminary_decision=preliminary,
        index_expectations=_retrieval_expectations(value, model),
        graph_edges=_retrieval_edges(value),
        ready_for_index=all(report.passed for report in reports),
    )


def build_collection_retrieval_batch(
    prepared: PreparedCollectionSemanticRuntime,
    *,
    embeddings: Mapping[str, Sequence[float]],
    model_id: str,
    model_revision: str,
) -> RetrievalIndexBatch:
    """Bind real 1024-d embeddings to canonical note hashes and evidence."""

    expected_ids = {item.stable_id for item in prepared.index_expectations}
    if set(embeddings) != expected_ids:
        missing = sorted(expected_ids - set(embeddings))
        extra = sorted(set(embeddings) - expected_ids)
        raise ValueError(f"retrieval source miss: missing={missing}; extra={extra}")
    documents = tuple(
        RetrievalIndexDocument(
            payload=AttestedRetrievalPayload(
                tenant_id=prepared.compile_input.tenant_id,
                project_id=prepared.compile_input.project_id,
                collection_id=prepared.compile_input.collection_id,
                stable_id=expectation.stable_id,
                document_id=expectation.document_id,
                media_kind=MediaKind.TEXT,
                source_hash=expectation.source_hash,
                evidence_block_ids=expectation.evidence_block_ids,
                model_id=model_id,
                model_revision=model_revision,
                vector=tuple(float(component) for component in embeddings[expectation.stable_id]),
                verification_state=expectation.verification_state,
                source_type="canonical_note",
                metadata={
                    "object_kind": KnowledgeObjectKind.NOTE.value,
                    "canonical_model_sha256": prepared.canonical_model_sha256,
                },
            ),
            lexical_text=expectation.lexical_text,
        )
        for expectation in prepared.index_expectations
    )
    return RetrievalIndexBatch(
        tenant_id=prepared.compile_input.tenant_id,
        documents=documents,
        edges=prepared.graph_edges,
    )


def _retrieval_batch_failure_codes(
    prepared: PreparedCollectionSemanticRuntime,
    batch: RetrievalIndexBatch,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    value = prepared.compile_input
    if batch.tenant_id != value.tenant_id:
        reasons.add("retrieval_tenant_scope_mismatch")
    expected = {item.stable_id: item for item in prepared.index_expectations}
    supplied = {item.payload.stable_id: item for item in batch.documents}
    if set(expected) != set(supplied):
        reasons.add("retrieval_source_miss")
    model_attestations: set[tuple[str, str]] = set()
    for stable_id in set(expected) & set(supplied):
        expectation = expected[stable_id]
        document = supplied[stable_id]
        payload = document.payload
        model_attestations.add((payload.model_id, payload.model_revision))
        if (
            payload.tenant_id != value.tenant_id
            or payload.project_id != value.project_id
            or payload.collection_id != value.collection_id
            or payload.document_id != expectation.document_id
        ):
            reasons.add("retrieval_scope_mismatch")
        if (
            payload.source_hash != expectation.source_hash
            or payload.evidence_block_ids != expectation.evidence_block_ids
            or payload.verification_state is not expectation.verification_state
            or document.lexical_text != expectation.lexical_text
        ):
            reasons.add("retrieval_source_attestation_mismatch")
        if (
            payload.metadata.get("canonical_model_sha256") != prepared.canonical_model_sha256
            or payload.metadata.get("object_kind") != KnowledgeObjectKind.NOTE.value
        ):
            reasons.add("retrieval_canonical_binding_mismatch")
    if len(model_attestations) != 1:
        reasons.add("retrieval_model_attestation_inconsistent")
    expected_edges = {
        (edge.project_id, edge.from_stable_id, edge.to_stable_id, edge.edge_weight)
        for edge in prepared.graph_edges
    }
    supplied_edges = {
        (edge.project_id, edge.from_stable_id, edge.to_stable_id, edge.edge_weight)
        for edge in batch.edges
    }
    if expected_edges != supplied_edges:
        reasons.add("retrieval_graph_binding_mismatch")
    return tuple(sorted(reasons))


def _runtime_result(
    prepared: PreparedCollectionSemanticRuntime,
    *,
    decision: AutonomousVerificationDecision,
    receipt: RetrievalIndexReceipt | None = None,
    outbox_event: CollectionRuntimeOutboxEvent | None = None,
) -> CollectionSemanticRuntimeResult:
    return CollectionSemanticRuntimeResult(
        accepted=decision.accepted,
        billable=decision.billable,
        state=decision.state,
        reason_codes=decision.reason_codes,
        architecture_plan=prepared.architecture_plan,
        architecture_plan_sha256=prepared.architecture_plan_sha256,
        canonical_model=prepared.canonical_model,
        canonical_model_sha256=prepared.canonical_model_sha256,
        semantic_profile=prepared.semantic_profile,
        numeric_result=prepared.numeric_result,
        region_decisions=prepared.region_decisions,
        decision=decision,
        retrieval_receipt=receipt,
        outbox_event=outbox_event,
    )


def _retrieval_failure_decision(
    prepared: PreparedCollectionSemanticRuntime,
    reason_codes: Sequence[str],
) -> AutonomousVerificationDecision:
    receipt = _scope_receipt(
        "retrieval_failure",
        {
            "collection_id": str(prepared.compile_input.collection_id),
            "canonical_model_sha256": prepared.canonical_model_sha256,
            "reason_codes": sorted(set(reason_codes)),
        },
    )
    findings = tuple(
        _finding(code, FindingLevel.HARD, source_refs=(receipt,))
        for code in sorted(set(reason_codes))
    )
    return _decision_with_retrieval(
        prepared.compile_input,
        prepared.pre_index_reports,
        AgentReport(
            agent=VerificationAgent.RETRIEVAL,
            passed=False,
            findings=findings,
        ),
    )


async def run_collection_semantic_runtime(
    session: AsyncSession,
    *,
    compile_input: CollectionSemanticCompileInput,
    retrieval_indexer: PostgresHybridIndexer,
    retrieval_batch: RetrievalIndexBatch | None,
    processing_job_id: uuid.UUID | None = None,
    outbox: CollectionRuntimeOutbox | None = None,
) -> CollectionSemanticRuntimeResult:
    """Complete collection semantics only after durable PostgreSQL index proof."""

    prepared = prepare_collection_semantic_runtime(compile_input)
    if not prepared.ready_for_index:
        return _runtime_result(prepared, decision=prepared.preliminary_decision)
    if retrieval_batch is None:
        return _runtime_result(
            prepared,
            decision=_retrieval_failure_decision(prepared, ("retrieval_batch_missing",)),
        )

    batch_failures = _retrieval_batch_failure_codes(prepared, retrieval_batch)
    if batch_failures:
        return _runtime_result(
            prepared,
            decision=_retrieval_failure_decision(prepared, batch_failures),
        )
    try:
        receipt = await retrieval_indexer.index(retrieval_batch)
    except Exception:
        return _runtime_result(
            prepared,
            decision=_retrieval_failure_decision(prepared, ("retrieval_index_failed_closed",)),
        )
    if (
        receipt.tenant_id != compile_input.tenant_id
        or receipt.indexed_records != len(retrieval_batch.documents)
        or receipt.indexed_edges != len(retrieval_batch.edges)
        or not receipt.batch_sha256.startswith("sha256:")
    ):
        return _runtime_result(
            prepared,
            decision=_retrieval_failure_decision(prepared, ("retrieval_receipt_mismatch",)),
        )

    retrieval_report = AgentReport(
        agent=VerificationAgent.RETRIEVAL,
        passed=True,
        findings=(
            _finding(
                "retrieval_index_verified",
                FindingLevel.INFO,
                source_refs=(receipt.batch_sha256,),
            ),
        ),
    )
    decision = _decision_with_retrieval(
        compile_input,
        prepared.pre_index_reports,
        retrieval_report,
    )
    if not decision.accepted:
        return _runtime_result(prepared, decision=decision)

    event = CollectionRuntimeOutboxEvent(
        tenant_id=compile_input.tenant_id,
        aggregate_id=compile_input.collection_id,
        event_type="collection.retrieval.indexed.v1",
        payload={
            "collection_id": str(compile_input.collection_id),
            "project_id": str(compile_input.project_id),
            "architecture_plan_id": str(compile_input.architecture_plan_id),
            "processing_job_id": str(processing_job_id) if processing_job_id else None,
            "canonical_model_sha256": prepared.canonical_model_sha256,
            "architecture_plan_sha256": prepared.architecture_plan_sha256,
            "retrieval_batch_sha256": receipt.batch_sha256,
            "indexed_records": receipt.indexed_records,
            "indexed_terms": receipt.indexed_terms,
            "indexed_edges": receipt.indexed_edges,
            "raw_text_persisted": receipt.raw_text_persisted,
            "verification_state": decision.state.value,
        },
    )
    writer = outbox or SQLAlchemyCollectionRuntimeOutbox(session)
    try:
        await writer.append(event)
    except Exception:
        return _runtime_result(
            prepared,
            decision=_retrieval_failure_decision(prepared, ("retrieval_index_outbox_failed",)),
        )
    return _runtime_result(
        prepared,
        decision=decision,
        receipt=receipt,
        outbox_event=event,
    )


async def search_collection_semantic_runtime(
    store: PostgresHybridStore,
    *,
    tenant_id: uuid.UUID,
    allowed_project_ids: tuple[uuid.UUID, ...],
    collection_id: uuid.UUID,
    vector: Sequence[float],
    lexical_query: str = "",
    graph_seed_ids: tuple[str, ...] = (),
    candidate_k: int = 50,
    top_k: int = 10,
) -> tuple[VectorCandidate, ...]:
    """Run retrieval with mandatory tenant, project, collection and state filters."""

    if not allowed_project_ids or len(allowed_project_ids) != len(set(allowed_project_ids)):
        raise ValueError("tenant-scoped retrieval requires unique allowed projects")
    query = RetrievalQuery(
        tenant_id=tenant_id,
        project_ids=allowed_project_ids,
        vector=tuple(float(component) for component in vector),
        lexical_query=lexical_query,
        graph_seed_ids=graph_seed_ids,
        filters=RetrievalFilters(
            collection_ids=frozenset({collection_id}),
            verification_states=frozenset(VerificationState),
        ),
        candidate_k=candidate_k,
        top_k=top_k,
    )
    candidates = tuple(await store.search(query))
    for candidate in candidates:
        metadata = candidate.record.metadata
        if metadata.get("collection_id") != str(collection_id):
            raise RetrievalUnavailable("collection retrieval escaped its mandatory scope")
    return candidates[:top_k]


def verify_collection_numeric_answer(
    token: str,
    *,
    expected_key: NumericFactKey,
    facts: Sequence[RetrievalNumericAuthorityFact],
) -> NumericAnswerVerification:
    """Expose the final answer gate; unresolved results never emit a number."""

    return verify_numeric_answer(token, expected_key=expected_key, facts=facts)


__all__ = [
    "CollectionOutputModuleInput",
    "CollectionRuntimeOutbox",
    "CollectionRuntimeOutboxEvent",
    "CollectionSemanticCompileInput",
    "CollectionSemanticRuntimeResult",
    "PreparedCollectionSemanticRuntime",
    "RetrievalIndexExpectation",
    "SQLAlchemyCollectionRuntimeOutbox",
    "SemanticBlockInput",
    "SemanticDocumentInput",
    "SemanticEntityInput",
    "SemanticIntegrityDecisionReceipt",
    "SemanticNoteInput",
    "SemanticRegionInput",
    "SemanticRelationInput",
    "build_collection_retrieval_batch",
    "builtin_semantic_blueprint_manifests",
    "canonical_object_id",
    "load_collection_semantic_compile_input",
    "prepare_collection_semantic_runtime",
    "run_collection_semantic_runtime",
    "search_collection_semantic_runtime",
    "semantic_blueprint_registry_sha256",
    "verify_collection_numeric_answer",
]
