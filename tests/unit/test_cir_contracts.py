from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir import (
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalCell,
    CanonicalDocument,
    CanonicalTable,
    ContentLayer,
    ErrorCode,
    ErrorEnvelope,
    EventType,
    PageState,
    ProcessingEvent,
    SourceRef,
    build_knowledge_messages,
    page_transition_allowed,
    sha256_digest,
)
from pydantic import ValidationError


def test_bbox_and_page_pair_are_canonical() -> None:
    box = BBox1000([0, 1, 999, 1000])
    assert box.as_unit_interval() == (0.0, 0.001, 0.999, 1.0)
    with pytest.raises(ValidationError):
        BBox1000([10, 10, 9, 20])
    with pytest.raises(ValidationError):
        SourceRef(
            document_id="doc",
            document_version_id="ver",
            page_index0=0,
            page_number1=2,
        )


def test_table_spans_cannot_overlap(source_ref: SourceRef) -> None:
    cells = (
        CanonicalCell(
            id="cell_001",
            row_index0=0,
            column_index0=0,
            row_span=1,
            column_span=2,
            raw_text="A",
            normalized_text="A",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
        ),
        CanonicalCell(
            id="cell_002",
            row_index0=0,
            column_index0=1,
            raw_text="B",
            normalized_text="B",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
        ),
    )
    with pytest.raises(ValidationError, match="overlaps"):
        CanonicalTable(
            id="tbl_001",
            row_count=1,
            column_count=2,
            cells=cells,
            source_refs=(source_ref,),
        )


def test_ai_content_cannot_claim_extracted_layer(source_ref: SourceRef) -> None:
    with pytest.raises(ValidationError, match="AI-derived"):
        CanonicalBlock(
            id="blk_001",
            order=0,
            type=BlockType.PARAGRAPH,
            content_layer=ContentLayer.EXTRACTED,
            raw_text="Unsupported",
            origin=BlockOrigin.AI_INFERRED,
            source_refs=(source_ref,),
            content_hash=sha256_digest("Unsupported"),
        )


def test_document_rejects_duplicate_block_ids(source_ref: SourceRef) -> None:
    block = CanonicalBlock(
        id="blk_001",
        order=0,
        type=BlockType.PARAGRAPH,
        content_layer=ContentLayer.STRUCTURED,
        raw_text="A",
        origin=BlockOrigin.NATIVE_EXTRACTED,
        source_refs=(source_ref,),
        content_hash=sha256_digest("A"),
    )
    duplicate = block.model_copy(update={"order": 1})
    with pytest.raises(ValidationError, match="unique"):
        CanonicalDocument(
            tenant_id="tenant",
            document_id="document",
            document_version_id="version",
            title="Title",
            source_filename="a.pdf",
            source_sha256=sha256_digest(b"a"),
            content_layer=ContentLayer.STRUCTURED,
            blocks=(block, duplicate),
            created_at=datetime.now(UTC),
        )


def test_page_state_transition_policy_is_fail_closed() -> None:
    assert page_transition_allowed(PageState.UPLOADED, PageState.SECURITY_SCANNING)
    assert page_transition_allowed(
        PageState.SECURITY_SCANNING, PageState.SECURITY_VERIFIED
    )
    assert page_transition_allowed(PageState.SECURITY_VERIFIED, PageState.PREFLIGHTING)
    assert page_transition_allowed(PageState.PREFLIGHTING, PageState.PREFLIGHTED)
    assert not page_transition_allowed(PageState.UPLOADED, PageState.PREFLIGHTING)
    assert not page_transition_allowed(PageState.UPLOADED, PageState.COMPLETED)


def test_processing_event_uses_masterplan_snake_case_wire_contract() -> None:
    event = ProcessingEvent(
        event_id="evt_001",
        event_type=EventType.JOB_STAGE_PROGRESS,
        sequence=1,
        occurred_at=datetime.now(UTC),
        tenant_id="tenant",
        job_id="job_001",
        project_id="project",
        payload={"stage": "extract", "done": 1, "total": 2},
    )
    wire = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert wire["schema_version"] == "1.0"
    assert wire["event_type"] == "job.stage.progress.v1"
    assert "eventId" not in wire


def test_prompt_keeps_source_in_user_data(canonical_document: CanonicalDocument) -> None:
    messages = build_knowledge_messages(
        blocks=canonical_document.blocks,
        task="Create evidence-bound notes.",
        schema={"type": "object"},
    )
    assert len(messages) == 2
    assert "매출은 10% 증가했다." not in messages[0]["content"]
    assert "SOURCE_DOCUMENT_JSON" in messages[1]["content"]
    assert "매출은 10% 증가했다." in messages[1]["content"]
    assert "Never call tools" in messages[0]["content"]


def test_public_error_and_event_payloads_reject_nested_document_content() -> None:
    with pytest.raises(ValidationError, match="sensitive public payload key"):
        ErrorEnvelope(
            code=ErrorCode.INTERNAL_ERROR,
            message="Safe message",
            trace_id="trace_001",
            details={"nested": {"rawText": "document body"}},
        )
    with pytest.raises(ValidationError, match="sensitive public payload key"):
        ProcessingEvent(
            event_id="evt_001",
            event_type=EventType.JOB_STAGE_PROGRESS,
            sequence=1,
            occurred_at=datetime.now(UTC),
            tenant_id="tenant",
            job_id="job_001",
            project_id="project",
            payload={"content": "document body"},
        )
