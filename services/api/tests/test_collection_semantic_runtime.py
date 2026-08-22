from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from akc_api.collection_api import _knowledge_blueprint_receipt
from akc_api.collection_semantic_runtime import (
    CollectionOutputModuleInput,
    CollectionRuntimeOutboxEvent,
    CollectionSemanticCompileInput,
    SemanticBlockInput,
    SemanticDocumentInput,
    SemanticIntegrityDecisionReceipt,
    SemanticNoteInput,
    SemanticRegionInput,
    SemanticRelationInput,
    SemanticSourceIntegrityReceipt,
    build_collection_retrieval_batch,
    builtin_semantic_blueprint_manifests,
    canonical_object_id,
    prepare_collection_semantic_runtime,
    run_collection_semantic_runtime,
    search_collection_semantic_runtime,
    semantic_blueprint_registry_sha256,
    verify_collection_numeric_answer,
)
from akc_cir import (
    BBox1000,
    KnowledgeObjectKind,
    KnowledgeOrigin,
    KnowledgeVerificationState,
    SourceRef,
    canonical_json,
    sha256_digest,
)
from akc_quality import (
    AgentFinding,
    AuthorityNumericFact,
    DartXbrlProvenance,
    FindingLevel,
    GeometrySource,
    GeometryWord,
    GeometryWordRole,
    NumericCellKey,
    NumericResolutionState,
    ParserNumericCell,
    RecoveryStage,
    SecInlineXbrlProvenance,
    VerificationAgent,
)
from akc_retrieval import (
    HmacSha256RowAttestor,
    NumericAnswerState,
    NumericFactKey,
    PostgresHybridIndexer,
    RetrievalIndexBatch,
)
from sqlalchemy.ext.asyncio import AsyncSession

TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
COLLECTION_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
PLAN_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
DOCUMENT_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
BLOCK_ID = uuid.UUID("60000000-0000-0000-0000-000000000001")
REGION_ID = uuid.UUID("70000000-0000-0000-0000-000000000001")
SOURCE_FILE_ID = uuid.UUID("80000000-0000-0000-0000-000000000001")
COLLECTION_FILE_ID = uuid.UUID("90000000-0000-0000-0000-000000000001")
VERSION_ID = f"document:{DOCUMENT_ID}:v1"
START = date(2025, 1, 1)
END = date(2025, 12, 31)
PDF_URI = "r2://filings/dart/20250731000001.pdf"
XML_URI = "r2://filings/dart/20250731000001.xml"
OUTPUT_KEYS = (
    "source_index",
    "document_catalog",
    "knowledge_notes",
    "entities",
    "relations",
    "integrity",
    "export_manifest",
)


def _source(*, bbox: BBox1000 | None = None) -> SourceRef:
    return SourceRef(
        document_id=str(DOCUMENT_ID),
        document_version_id=VERSION_ID,
        page_index0=0,
        page_number1=1,
        bbox1000=bbox,
    )


def _integrity_receipt(**updates: Any) -> SemanticSourceIntegrityReceipt:
    payload: dict[str, Any] = {
        "document_id": str(DOCUMENT_ID),
        "document_version_id": VERSION_ID,
        "source_file_id": str(SOURCE_FILE_ID),
        "collection_file_id": str(COLLECTION_FILE_ID),
        "source_sha256": "c" * 64,
        "collection_file_sha256": "c" * 64,
        "source_size_bytes": 1024,
        "collection_file_size_bytes": 1024,
        "collection_file_status": "verified",
        "antivirus_status": "clean",
        "cdr_status": "not_requested",
        "expected_page_count": 1,
        "observed_page_count": 1,
        "terminal_page_count": 1,
        "render_required_page_count": 0,
        "rendered_page_count": 0,
        "render_corruption_count": 0,
    }
    payload.update(updates)
    return SemanticSourceIntegrityReceipt.model_validate(
        {
            **payload,
            "receipt_sha256": sha256_digest(canonical_json(payload)),
        }
    )


def _numeric_evidence(
    *, parser_value: Decimal = Decimal("123")
) -> tuple[AuthorityNumericFact, ParserNumericCell]:
    key = NumericCellKey(
        entity_id="corp001",
        statement="CONSOLIDATED_INCOME_STATEMENT",
        concept="ifrs-full:Revenue",
        period_start=START,
        period_end=END,
        unit="KRW",
        scale=1_000_000,
        page=1,
        row_key="revenue",
        column_key="current_year",
    )
    fact = AuthorityNumericFact(
        fact_id="fact-revenue-current",
        key=key,
        xbrl_label="Revenue",
        value=Decimal("123000000"),
        provenance=DartXbrlProvenance(
            entity_id=key.entity_id,
            receipt_number="20250731000001",
            report_code="11011",
            xml_fact_id="xml-fact-revenue-current",
            xml_document_uri=XML_URI,
            pdf_document_uri=PDF_URI,
            fact_period_start=START,
            fact_period_end=END,
        ),
    )
    bbox = BBox1000((600, 300, 780, 340))
    cell = ParserNumericCell(
        parser_cell_id="cell-revenue-current",
        key=key,
        geometry_source=GeometrySource.PDF_CELL,
        source_document_uri=PDF_URI,
        label="Revenue",
        row_header="revenue",
        column_header="current year",
        original_parser_number=str(parser_value),
        parser_value=parser_value,
        bbox1000=bbox,
        words=(
            GeometryWord(
                text="Revenue",
                bbox1000=BBox1000((100, 300, 250, 340)),
                role=GeometryWordRole.ROW_HEADER,
            ),
            GeometryWord(
                text=str(parser_value),
                bbox1000=BBox1000((620, 305, 760, 335)),
                role=GeometryWordRole.VALUE,
            ),
        ),
    )
    return fact, cell


def _sec_numeric_evidence() -> tuple[AuthorityNumericFact, ParserNumericCell]:
    key = NumericCellKey(
        entity_id="cik0000320193",
        statement="BALANCE_SHEET",
        concept="us-gaap:Assets",
        instant=END,
        unit="USD",
        scale=1,
        page=1,
        row_key="assets",
        column_key="current_year",
    )
    uri = "https://www.sec.gov/Archives/edgar/data/320193/report.htm"
    fact = AuthorityNumericFact(
        fact_id="sec-assets-current",
        key=key,
        xbrl_label="Total assets",
        value=Decimal("364980000000"),
        provenance=SecInlineXbrlProvenance(
            entity_id=key.entity_id,
            accession_number="0000320193-25-000079",
            form="10-k",
            inline_xbrl_fact_id="ix-assets-current",
            filing_html_uri=uri,
            fact_instant=END,
        ),
    )
    bbox = BBox1000((600, 300, 780, 340))
    cell = ParserNumericCell(
        parser_cell_id="cell-assets-current",
        key=key,
        geometry_source=GeometrySource.RENDERED_HTML_REGION,
        source_document_uri=uri,
        label="Total assets",
        row_header="assets",
        column_header="current year",
        original_parser_number="364980000000",
        parser_value=Decimal("364980000000"),
        bbox1000=bbox,
        words=(
            GeometryWord(
                text="Total assets",
                bbox1000=BBox1000((100, 300, 250, 340)),
                role=GeometryWordRole.ROW_HEADER,
            ),
            GeometryWord(
                text="364980000000",
                bbox1000=BBox1000((620, 305, 760, 335)),
                role=GeometryWordRole.VALUE,
            ),
        ),
    )
    return fact, cell


def _compile_input(
    *,
    note_count: int = 2,
    block_type: str = "paragraph",
    block_state: KnowledgeVerificationState = KnowledgeVerificationState.VERIFIED,
    note_state: KnowledgeVerificationState = KnowledgeVerificationState.VERIFIED,
    numeric: tuple[AuthorityNumericFact, ParserNumericCell] | None = None,
    regions: tuple[SemanticRegionInput, ...] = (),
) -> CollectionSemanticCompileInput:
    blueprints = builtin_semantic_blueprint_manifests()
    selected = next(item for item in blueprints if item.blueprint_id == "generic-mixed-corpus")
    notes = tuple(
        SemanticNoteInput(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"structara:test:note:{index}"),
            document_id=DOCUMENT_ID,
            stable_key=f"note-{index}",
            title=f"Note {index}",
            note_type="source_summary",
            content_markdown=f"Evidence-bound note {index}.",
            evidence_block_ids=(BLOCK_ID,),
            origin=KnowledgeOrigin.SOURCE_EXPLICIT,
            verification_state=note_state,
        )
        for index in range(note_count)
    )
    authority_facts = (numeric[0],) if numeric else ()
    parser_cells = (numeric[1],) if numeric else ()
    numeric_refs = {numeric[1].parser_cell_id: _source(bbox=numeric[1].bbox1000)} if numeric else {}
    return CollectionSemanticCompileInput(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        collection_id=COLLECTION_ID,
        architecture_plan_id=PLAN_ID,
        architecture_plan_version=1,
        architecture_plan={
            "schema_version": "1.0",
            "collection_id": str(COLLECTION_ID),
            "project_id": str(PROJECT_ID),
        },
        input_integrity_sha256="a" * 64,
        knowledge_blueprint_id=selected.blueprint_id,
        knowledge_blueprint_registry_sha256=semantic_blueprint_registry_sha256(blueprints),
        knowledge_blueprint_module_sha256=selected.module_sha256,
        documents=(
            SemanticDocumentInput(
                id=DOCUMENT_ID,
                document_version_id=VERSION_ID,
                title="Verified source",
                source_refs=(_source(),),
                integrity_receipt=_integrity_receipt(),
            ),
        ),
        blocks=(
            SemanticBlockInput(
                id=BLOCK_ID,
                document_id=DOCUMENT_ID,
                block_type=block_type,
                text="Verified collection evidence.",
                source_refs=(_source(bbox=BBox1000((10, 10, 990, 100))),),
                origin=KnowledgeOrigin.NATIVE_EXTRACTED,
                verification_state=block_state,
            ),
        ),
        notes=notes,
        regions=regions,
        output_modules=tuple(
            CollectionOutputModuleInput(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"structara:test:output:{key}"),
                module_key=key,
                module_version="1.0",
                config={"declarative": True},
                output_summary={"status": "compiled"},
            )
            for key in OUTPUT_KEYS
        ),
        numeric_scope_declared=numeric is not None,
        authority_facts=authority_facts,
        parser_numeric_cells=parser_cells,
        numeric_source_refs=numeric_refs,
    )


def _decision_receipt() -> SemanticIntegrityDecisionReceipt:
    return SemanticIntegrityDecisionReceipt(
        decision_id=uuid.UUID("a0000000-0000-0000-0000-000000000001"),
        execution_id=uuid.UUID("b0000000-0000-0000-0000-000000000001"),
        target_type="review_item",
        target_id=uuid.UUID("c0000000-0000-0000-0000-000000000001"),
        action="override",
        reason_code="CUSTOMER_VERIFIED_OVERRIDE",
        execution_receipt_sha256="d" * 64,
        result_code="CUSTOMER_OVERRIDE_APPLIED",
    )


class RecordingExecutor:
    dialect_name = "postgresql"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def execute_transaction(self, mutations: Any) -> tuple[str | None, ...]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("database unavailable")
        return tuple("persisted" if item.requires_returned_row else None for item in mutations)


class RecordingOutbox:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[CollectionRuntimeOutboxEvent] = []
        self.fail = fail

    async def append(self, event: CollectionRuntimeOutboxEvent) -> None:
        if self.fail:
            raise RuntimeError("outbox unavailable")
        self.events.append(event)


def _indexer(executor: RecordingExecutor) -> PostgresHybridIndexer:
    return PostgresHybridIndexer(
        executor=executor,
        row_attestor=HmacSha256RowAttestor(b"r" * 32),
    )


def _batch(value: CollectionSemanticCompileInput) -> tuple[Any, RetrievalIndexBatch]:
    prepared = prepare_collection_semantic_runtime(value)
    embeddings = {
        item.stable_id: (1.0, *(0.0 for _ in range(1023))) for item in prepared.index_expectations
    }
    return prepared, build_collection_retrieval_batch(
        prepared,
        embeddings=embeddings,
        model_id="Qwen3-Embedding-0.6B",
        model_revision="b" * 40,
    )


@pytest.mark.asyncio
async def test_canonical_blueprints_postgres_receipt_and_outbox_gate_completion() -> None:
    value = _compile_input()
    prepared, batch = _batch(value)
    executor = RecordingExecutor()
    outbox = RecordingOutbox()

    result = await run_collection_semantic_runtime(
        cast(AsyncSession, None),
        compile_input=value,
        retrieval_indexer=_indexer(executor),
        retrieval_batch=batch,
        outbox=outbox,
    )

    assert result.accepted and result.billable
    assert result.retrieval_receipt is not None
    assert result.retrieval_receipt.indexed_records == 2
    assert executor.calls == 1 and outbox.events == [result.outbox_event]
    assert len(result.semantic_profile.blueprint_modules) == 7
    assert prepared.selected_blueprint.blueprint_id == "generic-mixed-corpus"
    assert result.architecture_plan["knowledge_blueprint_id"] == "generic-mixed-corpus"
    assert "selected_knowledge_blueprint_id" not in result.architecture_plan
    assert "selected_knowledge_blueprint_module_sha256" not in result.architecture_plan
    assert {item["module_key"] for item in result.architecture_plan["output_modules"]} == set(
        OUTPUT_KEYS
    )
    assert result.architecture_plan["knowledge_blueprints"] == [
        module.model_dump(mode="json") for module in result.semantic_profile.blueprint_modules
    ]
    blueprint_assets = [
        item
        for item in result.canonical_model.objects
        if item.kind is KnowledgeObjectKind.ASSET
        and item.payload.get("semantic_role") == "knowledge_blueprint_module"
    ]
    output_assets = [
        item
        for item in result.canonical_model.objects
        if item.kind is KnowledgeObjectKind.ASSET
        and item.payload.get("semantic_role") == "architecture_output_module"
    ]
    assert len(blueprint_assets) == len(output_assets) == 7
    assert {item.payload["manifest"]["blueprint_id"] for item in blueprint_assets} != {
        item.payload["module_key"] for item in output_assets
    }
    root = next(
        item
        for item in result.canonical_model.objects
        if item.kind is KnowledgeObjectKind.COLLECTION
    )
    assert root.payload["architecture_plan_sha256"] == result.architecture_plan_sha256
    assert result.architecture_plan_sha256 == sha256_digest(
        canonical_json(result.architecture_plan)
    )
    assert root.payload["input_integrity_sha256"] == ("sha256:" + value.input_integrity_sha256)
    expected_modules = {item.module_key: item for item in value.output_modules}
    planned_modules = {
        item["module_key"]: item for item in result.architecture_plan["output_modules"]
    }
    attested_modules = {item.payload["module_key"]: item for item in output_assets}
    assert set(expected_modules) == set(planned_modules) == set(attested_modules)
    for key, expected in expected_modules.items():
        assert planned_modules[key]["status"] == expected.status
        assert planned_modules[key]["output_sha256"] == sha256_digest(
            canonical_json(expected.output_summary)
        )
        assert attested_modules[key].payload["status"] == expected.status
        assert attested_modules[key].payload["output_summary"] == expected.output_summary


def test_integrity_decision_receipts_are_attested_in_semantic_compile_plan() -> None:
    baseline = prepare_collection_semantic_runtime(_compile_input())
    receipt = _decision_receipt()
    value = _compile_input().model_copy(update={"integrity_decision_receipts": (receipt,)})

    prepared = prepare_collection_semantic_runtime(value)

    payload = receipt.model_dump(mode="json")
    assert prepared.architecture_plan["integrity_decisions"] == [payload]
    assert prepared.architecture_plan["integrity_decision_set_sha256"] == sha256_digest(
        canonical_json([payload])
    )
    assert prepared.architecture_plan_sha256 != baseline.architecture_plan_sha256
    root = next(
        item
        for item in prepared.canonical_model.objects
        if item.kind is KnowledgeObjectKind.COLLECTION
    )
    assert root.payload["architecture_plan_sha256"] == prepared.architecture_plan_sha256


def test_all_pre_index_agents_are_explicit_and_carry_evidence_receipts() -> None:
    prepared = prepare_collection_semantic_runtime(_compile_input())

    assert {report.agent for report in prepared.pre_index_reports} == set(VerificationAgent) - {
        VerificationAgent.RETRIEVAL
    }
    assert all(report.findings for report in prepared.pre_index_reports)
    assert all(
        any(finding.source_refs for finding in report.findings)
        for report in prepared.pre_index_reports
    )
    assert prepared.ready_for_index


def test_missing_source_integrity_receipt_is_unresolved_before_index() -> None:
    value = _compile_input()
    document = value.documents[0].model_copy(update={"integrity_receipt": None})
    prepared = prepare_collection_semantic_runtime(
        value.model_copy(update={"documents": (document,)})
    )

    source_report = next(
        report
        for report in prepared.pre_index_reports
        if report.agent is VerificationAgent.SOURCE_INTEGRITY
    )
    assert not source_report.passed
    assert {finding.code for finding in source_report.findings} == {
        "source_integrity_receipt_missing"
    }
    assert not prepared.ready_for_index
    assert prepared.preliminary_decision.state.value == "unresolved"


def test_source_hash_mismatch_is_quarantined() -> None:
    value = _compile_input()
    document = value.documents[0].model_copy(
        update={"integrity_receipt": _integrity_receipt(collection_file_sha256="d" * 64)}
    )
    prepared = prepare_collection_semantic_runtime(
        value.model_copy(update={"documents": (document,)})
    )

    assert not prepared.ready_for_index
    assert prepared.preliminary_decision.state.value == "quarantined"
    assert "source_hash_mismatch" in prepared.preliminary_decision.reason_codes


@pytest.mark.parametrize(
    ("receipt", "reason_code"),
    [
        (_integrity_receipt(expected_page_count=2), "page_count_mismatch"),
        (
            _integrity_receipt(
                render_required_page_count=1,
                rendered_page_count=1,
                render_corruption_count=1,
            ),
            "render_corruption_detected",
        ),
    ],
)
def test_page_count_and_render_corruption_receipts_fail_closed(
    receipt: SemanticSourceIntegrityReceipt,
    reason_code: str,
) -> None:
    value = _compile_input()
    document = value.documents[0].model_copy(update={"integrity_receipt": receipt})
    prepared = prepare_collection_semantic_runtime(
        value.model_copy(update={"documents": (document,)})
    )

    assert not prepared.ready_for_index
    assert reason_code in prepared.preliminary_decision.reason_codes


def test_invalid_block_source_reference_fails_citation_agent() -> None:
    value = _compile_input()
    invalid_source = SourceRef(
        document_id=str(DOCUMENT_ID),
        document_version_id=VERSION_ID,
        page_index0=1,
        page_number1=2,
    )
    block = value.blocks[0].model_copy(update={"source_refs": (invalid_source,)})
    prepared = prepare_collection_semantic_runtime(value.model_copy(update={"blocks": (block,)}))

    citation_report = next(
        report
        for report in prepared.pre_index_reports
        if report.agent is VerificationAgent.CITATION
    )
    assert not citation_report.passed
    assert "block_source_ref_invalid" in {
        finding.code for finding in citation_report.findings
    }


def test_unresolved_relation_endpoint_fails_knowledge_agent() -> None:
    value = _compile_input()
    relation = SemanticRelationInput(
        id=uuid.uuid5(uuid.NAMESPACE_URL, "structara:test:relation:unresolved"),
        document_id=DOCUMENT_ID,
        subject_id="missing:subject",
        predicate="references",
        object_id=str(value.notes[0].id),
        evidence_block_ids=(BLOCK_ID,),
        origin=KnowledgeOrigin.SOURCE_EXPLICIT,
        verification_state=KnowledgeVerificationState.VERIFIED,
    )
    prepared = prepare_collection_semantic_runtime(
        value.model_copy(update={"relations": (relation,)})
    )

    knowledge_report = next(
        report
        for report in prepared.pre_index_reports
        if report.agent is VerificationAgent.KNOWLEDGE
    )
    assert not knowledge_report.passed
    assert "relation_endpoint_unresolved" in {
        finding.code for finding in knowledge_report.findings
    }


@pytest.mark.asyncio
async def test_retrieval_source_miss_stops_index_and_never_emits_outbox() -> None:
    value = _compile_input(note_count=2)
    prepared, complete_batch = _batch(value)
    incomplete_batch = RetrievalIndexBatch(
        tenant_id=TENANT_ID,
        documents=(complete_batch.documents[0],),
        edges=complete_batch.edges,
    )
    executor = RecordingExecutor()
    outbox = RecordingOutbox()

    result = await run_collection_semantic_runtime(
        cast(AsyncSession, None),
        compile_input=value,
        retrieval_indexer=_indexer(executor),
        retrieval_batch=incomplete_batch,
        outbox=outbox,
    )

    assert not result.accepted and not result.billable
    assert "retrieval_source_miss" in result.reason_codes
    assert executor.calls == 0 and outbox.events == []
    assert result.retrieval_receipt is None
    assert len(prepared.index_expectations) == 2


@pytest.mark.asyncio
async def test_dart_numeric_mismatch_and_region_recovery_fail_closed_before_index() -> None:
    fact, cell = _numeric_evidence(parser_value=Decimal("124"))
    region = SemanticRegionInput(
        id=REGION_ID,
        region_type="financial_table",
        source_refs=(_source(bbox=cell.bbox1000),),
        verification_state=KnowledgeVerificationState.UNRESOLVED,
        findings=(AgentFinding(code="numeric_mismatch", level=FindingLevel.HARD),),
    )
    value = _compile_input(
        block_type="table",
        block_state=KnowledgeVerificationState.UNRESOLVED,
        note_state=KnowledgeVerificationState.UNRESOLVED,
        numeric=(fact, cell),
        regions=(region,),
    )
    prepared = prepare_collection_semantic_runtime(value)
    executor = RecordingExecutor()

    # The batch is structurally valid but cannot authorize a failed semantic compile.
    promoted_value = _compile_input()
    _, unrelated_batch = _batch(promoted_value)
    result = await run_collection_semantic_runtime(
        cast(AsyncSession, None),
        compile_input=value,
        retrieval_indexer=_indexer(executor),
        retrieval_batch=unrelated_batch,
        outbox=RecordingOutbox(),
    )

    assert prepared.numeric_result.state is NumericResolutionState.UNRESOLVED
    assert prepared.numeric_result.publishable_matches == ()
    assert not prepared.ready_for_index and not result.accepted
    assert executor.calls == 0
    assert prepared.region_decisions[0].decision.next_recovery_stage is (
        RecoveryStage.DETERMINISTIC_NORMALIZATION
    )


@pytest.mark.asyncio
async def test_authority_verified_numeric_table_can_reach_index_completion() -> None:
    fact, cell = _numeric_evidence()
    region = SemanticRegionInput(
        id=REGION_ID,
        region_type="financial_table",
        source_refs=(_source(bbox=cell.bbox1000),),
        verification_state=KnowledgeVerificationState.AUTHORITY_VERIFIED,
    )
    value = _compile_input(
        block_type="table",
        block_state=KnowledgeVerificationState.AUTHORITY_VERIFIED,
        note_state=KnowledgeVerificationState.AUTHORITY_VERIFIED,
        numeric=(fact, cell),
        regions=(region,),
    )
    _, batch = _batch(value)
    result = await run_collection_semantic_runtime(
        cast(AsyncSession, None),
        compile_input=value,
        retrieval_indexer=_indexer(RecordingExecutor()),
        retrieval_batch=batch,
        outbox=RecordingOutbox(),
    )

    assert result.accepted
    assert result.state.value == "authority_verified"
    assert result.numeric_result.publishable_matches


@pytest.mark.asyncio
async def test_sec_inline_xbrl_geometry_reaches_the_same_authority_gate() -> None:
    fact, cell = _sec_numeric_evidence()
    region = SemanticRegionInput(
        id=REGION_ID,
        region_type="financial_table",
        source_refs=(_source(bbox=cell.bbox1000),),
        verification_state=KnowledgeVerificationState.AUTHORITY_VERIFIED,
    )
    value = _compile_input(
        block_type="table",
        block_state=KnowledgeVerificationState.AUTHORITY_VERIFIED,
        note_state=KnowledgeVerificationState.AUTHORITY_VERIFIED,
        numeric=(fact, cell),
        regions=(region,),
    )
    _, batch = _batch(value)
    result = await run_collection_semantic_runtime(
        cast(AsyncSession, None),
        compile_input=value,
        retrieval_indexer=_indexer(RecordingExecutor()),
        retrieval_batch=batch,
        outbox=RecordingOutbox(),
    )
    assert result.accepted
    assert result.numeric_result.publishable_matches[0].authority_fact_id == fact.fact_id


def test_hungarian_ambiguity_is_nonpublishable_in_collection_compile() -> None:
    fact, cell = _numeric_evidence()
    duplicate = cell.model_copy(update={"parser_cell_id": "cell-revenue-duplicate"})
    region = SemanticRegionInput(
        id=REGION_ID,
        region_type="financial_table",
        source_refs=(_source(bbox=cell.bbox1000),),
        verification_state=KnowledgeVerificationState.UNRESOLVED,
        findings=(AgentFinding(code="ambiguous_mapping", level=FindingLevel.HARD),),
    )
    value = _compile_input(
        block_type="table",
        block_state=KnowledgeVerificationState.UNRESOLVED,
        note_state=KnowledgeVerificationState.UNRESOLVED,
        numeric=(fact, cell),
        regions=(region,),
    ).model_copy(
        update={
            "parser_numeric_cells": (cell, duplicate),
            "numeric_source_refs": {
                cell.parser_cell_id: _source(bbox=cell.bbox1000),
                duplicate.parser_cell_id: _source(bbox=duplicate.bbox1000),
            },
        }
    )
    prepared = prepare_collection_semantic_runtime(value)
    assert not prepared.ready_for_index
    assert prepared.numeric_result.publishable_matches == ()
    assert "ambiguous_bipartite_match" in prepared.numeric_result.reason_codes


@pytest.mark.asyncio
async def test_outbox_failure_revokes_completion_even_after_index_receipt() -> None:
    value = _compile_input()
    _, batch = _batch(value)
    executor = RecordingExecutor()
    result = await run_collection_semantic_runtime(
        cast(AsyncSession, None),
        compile_input=value,
        retrieval_indexer=_indexer(executor),
        retrieval_batch=batch,
        outbox=RecordingOutbox(fail=True),
    )
    assert executor.calls == 1
    assert not result.accepted
    assert result.retrieval_receipt is None
    assert "retrieval_index_outbox_failed" in result.reason_codes


def test_batch_builder_rejects_missing_embedding_as_source_miss() -> None:
    prepared = prepare_collection_semantic_runtime(_compile_input())
    with pytest.raises(ValueError, match="retrieval source miss"):
        build_collection_retrieval_batch(
            prepared,
            embeddings={},
            model_id="Qwen3-Embedding-0.6B",
            model_revision="b" * 40,
        )


@pytest.mark.asyncio
async def test_ready_runtime_rejects_a_missing_retrieval_batch() -> None:
    executor = RecordingExecutor()
    result = await run_collection_semantic_runtime(
        cast(AsyncSession, None),
        compile_input=_compile_input(),
        retrieval_indexer=_indexer(executor),
        retrieval_batch=None,
        outbox=RecordingOutbox(),
    )

    assert not result.accepted
    assert result.reason_codes == ("retrieval_batch_missing",)
    assert result.retrieval_receipt is None
    assert result.outbox_event is None
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_tenant_collection_search_always_injects_mandatory_scope() -> None:
    class EmptyStore:
        query: Any = None

        async def search(self, query: Any) -> tuple[()]:
            self.query = query
            return ()

    store = EmptyStore()
    result = await search_collection_semantic_runtime(
        cast(Any, store),
        tenant_id=TENANT_ID,
        allowed_project_ids=(PROJECT_ID,),
        collection_id=COLLECTION_ID,
        vector=(1.0, *(0.0 for _ in range(1023))),
    )
    assert result == ()
    assert store.query.tenant_id == TENANT_ID
    assert store.query.project_ids == (PROJECT_ID,)
    assert store.query.filters.collection_ids == frozenset({COLLECTION_ID})


def test_final_numeric_answer_never_emits_when_authority_source_is_missing() -> None:
    key = NumericFactKey(
        entity_id="corp001",
        statement="INCOME_STATEMENT",
        concept="Revenue",
        period_start="2025-01-01",
        period_end="2025-12-31",
        unit="KRW",
        currency="KRW",
        scale=1_000_000,
        dimensions_hash="c" * 64,
    )
    result = verify_collection_numeric_answer("123000000", expected_key=key, facts=())
    assert result.state is NumericAnswerState.UNRESOLVED
    assert not result.emit_answer
    assert result.reason_codes == ("authority_fact_missing",)


def test_canonical_note_id_is_the_retrieval_identity() -> None:
    value = _compile_input(note_count=1)
    prepared = prepare_collection_semantic_runtime(value)
    assert prepared.index_expectations[0].stable_id == canonical_object_id(
        KnowledgeObjectKind.NOTE,
        value.notes[0].id,
    )


def test_architecture_plan_normalizes_transitional_blueprint_aliases() -> None:
    value = _compile_input(note_count=1)
    value = value.model_copy(
        update={
            "architecture_plan": {
                **value.architecture_plan,
                "selected_knowledge_blueprint_id": "legacy-alias",
                "selected_knowledge_blueprint_module_sha256": "sha256:" + "f" * 64,
            }
        }
    )

    prepared = prepare_collection_semantic_runtime(value)

    assert prepared.architecture_plan["knowledge_blueprint_id"] == (value.knowledge_blueprint_id)
    assert prepared.architecture_plan["knowledge_blueprint_module_sha256"] == (
        value.knowledge_blueprint_module_sha256
    )
    assert "selected_knowledge_blueprint_id" not in prepared.architecture_plan
    assert "selected_knowledge_blueprint_module_sha256" not in prepared.architecture_plan


def test_collection_receipt_uses_full_semantic_registry_and_canonical_plan_keys() -> None:
    receipt = _knowledge_blueprint_receipt({})

    assert receipt["knowledge_blueprint_registry_sha256"] == (semantic_blueprint_registry_sha256())
    assert receipt["knowledge_blueprint_id"] == "generic-mixed-corpus"
    assert receipt["knowledge_blueprint_module_sha256"].startswith("sha256:")
    assert "selected_knowledge_blueprint_id" not in receipt
    assert "selected_knowledge_blueprint_module_sha256" not in receipt
