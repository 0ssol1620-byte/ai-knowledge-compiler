from __future__ import annotations

from akc_cir import (
    AssertionStatus,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalCell,
    CanonicalTable,
    Claim,
    ContentLayer,
    KnowledgeBundle,
    KnowledgeNote,
    NoteType,
    RelationAssertion,
    sha256_digest,
)
from akc_quality import (
    markdown_anomalies,
    source_coverage_ratio,
    table_numeric_fidelity,
    table_shape_fidelity,
    text_anomalies,
    validate_block_provenance,
    validate_knowledge_evidence,
    validate_table,
)


def test_text_and_markdown_anomalies_cover_objective_failures() -> None:
    assert {item.code for item in text_anomalies("")} == {"text.empty"}
    findings = text_anomalies(
        "abcdefgh" * 20 + "\ufffd" * 10 + "\x01",
        reference_length=10,
    )
    codes = {item.code for item in findings}
    assert {
        "text.replacement_characters",
        "text.control_characters",
        "text.repetition",
        "text.length_anomaly",
    } <= codes
    markdown_codes = {item.code for item in markdown_anomalies("# A\n# B\n#### Jump\nbody\x00")}
    assert {
        "markdown.multiple_h1",
        "markdown.heading_level_jump",
        "markdown.null_byte",
    } <= markdown_codes


def test_table_quality_reports_missing_grid_and_header(source_ref) -> None:
    cell = CanonicalCell(
        id="cell_001",
        row_index0=0,
        column_index0=0,
        raw_text="10",
        normalized_text="10",
        origin=BlockOrigin.OCR_EXTRACTED,
        source_refs=(source_ref,),
    )
    sparse = CanonicalTable(
        id="tbl_001",
        row_count=2,
        column_count=2,
        cells=(cell,),
        source_refs=(source_ref,),
    )
    codes = {item.code for item in validate_table(sparse)}
    assert {"table.empty_cell_ratio", "table.header_missing"} <= codes
    candidate = sparse.model_copy(update={"row_count": 3})
    assert table_shape_fidelity(sparse, candidate) < 1.0
    assert table_numeric_fidelity(sparse, sparse) == 1.0


def test_provenance_and_knowledge_evidence_find_unknown_ids(source_ref) -> None:
    block = CanonicalBlock(
        id="blk_001",
        order=0,
        type=BlockType.PARAGRAPH,
        content_layer=ContentLayer.STRUCTURED,
        raw_text="Evidence",
        origin=BlockOrigin.NATIVE_EXTRACTED,
        source_refs=(source_ref, source_ref),
        content_hash=sha256_digest("Evidence"),
    )
    assert source_coverage_ratio(()) == 0.0
    assert source_coverage_ratio((block,)) == 1.0
    assert {item.code for item in validate_block_provenance((block,))} == {
        "provenance.duplicate_ref"
    }

    note = KnowledgeNote(
        note_id="note_001",
        title="Claim",
        note_type=NoteType.CONCEPT,
        content_origin=BlockOrigin.AI_SUMMARIZED,
        evidence_block_ids=("blk_missing",),
        claims=(
            Claim(
                text="Unknown evidence",
                origin=BlockOrigin.AI_SUMMARIZED,
                source_block_ids=("blk_missing",),
                confidence=0.8,
            ),
        ),
    )
    relation = RelationAssertion(
        id="rel_001",
        subject="entity_001",
        predicate="akmp:relatedTo",
        object="entity_002",
        assertion_status=AssertionStatus.AI_INFERRED,
        confidence=0.7,
        evidence_block_ids=("blk_missing",),
    )
    bundle = KnowledgeBundle(
        document_id="doc_001",
        notes=(note,),
        relations=(relation,),
    )
    codes = {
        item.code for item in validate_knowledge_evidence(bundle, available_block_ids={"blk_001"})
    }
    assert {
        "evidence.note_unknown_block",
        "evidence.claim_unknown_block",
        "evidence.relation_unknown_block",
    } <= codes
