from __future__ import annotations

from datetime import UTC, datetime

from akc_cir import (
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalCell,
    CanonicalDocument,
    CanonicalTable,
    ContentLayer,
    PreservationInvariant,
    SemanticEvidenceBinding,
    SourceRef,
    sha256_digest,
    verify_semantic_preservation,
)


def _ref(*, document_id: str = "doc_001", version: str = "docver_001", page: int = 0) -> SourceRef:
    return SourceRef(
        document_id=document_id,
        document_version_id=version,
        page_index0=page,
        page_number1=page + 1,
        bbox1000=BBox1000([100, 100, 900, 300]),
    )


def _table_document(*, value_text: str = "1.5.3", value_version: str = "docver_001") -> CanonicalDocument:
    source = _ref()
    cells = (
        CanonicalCell(
            id="cell_model_header",
            row_index0=0,
            column_index0=0,
            raw_text="Model",
            normalized_text="Model",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source,),
        ),
        CanonicalCell(
            id="cell_version_header",
            row_index0=0,
            column_index0=1,
            raw_text="Version",
            normalized_text="Version",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source,),
        ),
        CanonicalCell(
            id="cell_n2",
            row_index0=1,
            column_index0=0,
            raw_text="N2",
            normalized_text="N2",
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source,),
        ),
        CanonicalCell(
            id="cell_n2_version",
            row_index0=1,
            column_index0=1,
            raw_text=value_text,
            normalized_text=value_text,
            origin=BlockOrigin.OCR_EXTRACTED,
            source_refs=(_ref(version=value_version),),
        ),
    )
    table = CanonicalTable(
        id="table_versions",
        row_count=2,
        column_count=2,
        header_row_count=1,
        cells=cells,
        source_refs=(source,),
    )
    block = CanonicalBlock(
        id="blk_versions",
        order=0,
        type=BlockType.TABLE,
        content_layer=ContentLayer.STRUCTURED,
        table=table,
        origin=BlockOrigin.NATIVE_EXTRACTED,
        source_refs=(source,),
        content_hash=sha256_digest(f"N2:{value_text}"),
    )
    return CanonicalDocument(
        tenant_id="tenant_001",
        document_id="doc_001",
        document_version_id="docver_001",
        title="Firmware versions",
        source_filename="versions.pdf",
        source_sha256=sha256_digest(b"versions"),
        content_layer=ContentLayer.STRUCTURED,
        blocks=(block,),
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def test_table_fact_preserves_cell_attachment_and_critical_value() -> None:
    document = _table_document()
    binding = SemanticEvidenceBinding(
        knowledge_id="fact:n2-version",
        knowledge_kind="world_fact",
        source_block_ids=("blk_versions",),
        source_cell_ids=("cell_n2", "cell_n2_version"),
        critical_tokens=("N2", "1.5.3"),
    )

    report = verify_semantic_preservation(document, (binding,))

    assert report.passed
    assert report.quarantine_block_ids == ()
    assert report.quarantine_page_indexes0 == ()


def test_silent_table_value_corruption_is_localized_to_affected_block_and_page() -> None:
    document = _table_document(value_text="1.5.8")
    binding = SemanticEvidenceBinding(
        knowledge_id="fact:n2-version",
        knowledge_kind="world_fact",
        source_block_ids=("blk_versions",),
        source_cell_ids=("cell_n2", "cell_n2_version"),
        critical_tokens=("N2", "1.5.3"),
    )

    report = verify_semantic_preservation(document, (binding,))

    assert not report.passed
    assert [item.invariant for item in report.violations] == [
        PreservationInvariant.CRITICAL_TOKEN_PRESERVED
    ]
    assert report.quarantine_block_ids == ("blk_versions",)
    assert report.quarantine_page_indexes0 == (0,)
    assert report.recovery_action == "rerender_or_stronger_parser_then_reverify"


def test_detached_table_cell_is_rejected_instead_of_falling_back_to_block_text() -> None:
    document = _table_document()
    binding = SemanticEvidenceBinding(
        knowledge_id="fact:n2-version",
        knowledge_kind="world_fact",
        source_block_ids=("blk_versions",),
        source_cell_ids=("cell_n2", "cell_missing"),
        critical_tokens=("N2", "1.5.3"),
    )

    report = verify_semantic_preservation(document, (binding,))

    assert not report.passed
    assert PreservationInvariant.SOURCE_CELL_EXISTS in {
        item.invariant for item in report.violations
    }
    assert report.quarantine_block_ids == ("blk_versions",)


def test_cross_version_evidence_is_rejected_even_if_text_matches() -> None:
    document = _table_document(value_version="docver_000")
    binding = SemanticEvidenceBinding(
        knowledge_id="fact:n2-version",
        knowledge_kind="world_fact",
        source_block_ids=("blk_versions",),
        source_cell_ids=("cell_n2_version",),
        critical_tokens=("1.5.3",),
    )

    report = verify_semantic_preservation(document, (binding,))

    assert not report.passed
    assert PreservationInvariant.SOURCE_DOCUMENT_VERSION in {
        item.invariant for item in report.violations
    }
    assert report.quarantine_block_ids == ("blk_versions",)


def test_missing_source_block_fails_closed() -> None:
    document = _table_document()
    binding = SemanticEvidenceBinding(
        knowledge_id="claim:missing",
        knowledge_kind="claim",
        source_block_ids=("blk_missing",),
        critical_tokens=("2026-09-30",),
    )

    report = verify_semantic_preservation(document, (binding,))

    assert not report.passed
    assert report.violations[0].invariant is PreservationInvariant.SOURCE_BLOCK_EXISTS
    assert report.quarantine_block_ids == ("blk_missing",)
