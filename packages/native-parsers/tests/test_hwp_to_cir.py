from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from akc_cir import BlockType
from akc_native_parsers.hwp_contract import (
    FixtureEngine,
    HwpAdapterRequest,
    HwpAdapterResult,
    HwpBlock,
    HwpManifest,
    ResourceReceipt,
    TableCell,
    build_result,
)
from akc_native_parsers.hwp_to_cir import hwp_result_to_cir
from akc_native_parsers.models import ParseContext, StructuredParseError

DATA = b"synthetic"
SHA = hashlib.sha256(DATA).hexdigest()
CTX = ParseContext(
    tenant_id="tenant-1",
    document_id="doc-1",
    document_version_id="ver-1",
    created_at=datetime(2026, 1, 1, tzinfo=UTC),
)


def _fixture(profile: str) -> HwpAdapterResult:
    request = HwpAdapterRequest(
        job_id="j",
        source_handle="src_0001",
        source_sha256=SHA,
        declared_format="hwp5",
        authorized_scope_ref="s",
        parser_profile=profile,
        max_bytes=1000,
        max_runtime_ms=1000,
    )
    return FixtureEngine().parse(DATA, request)


def _result(*blocks: HwpBlock) -> HwpAdapterResult:
    return build_result(
        engine_id="e",
        engine_version="1",
        manifest=HwpManifest(source_sha256=SHA, detected_format="hwp5"),
        blocks=blocks,
        resource_receipt=ResourceReceipt(wall_ms=0, input_bytes=1, output_bytes=0, exit_code=0),
    )


def _table(cells: tuple[TableCell, ...], state: str = "native_unverified") -> HwpBlock:
    return HwpBlock.model_validate(
        {
            "id": "t",
            "kind": "table",
            "table_grid": cells,
            "bbox_or_element_anchor": "s0/t1",
            "original_ref": "s0/t1",
            "verification_state": state,
        }
    )


def test_complex_table_spans_survive() -> None:
    doc = hwp_result_to_cir(_fixture("fixture:complex_table"), CTX)
    table = next(b for b in doc.blocks if b.type == BlockType.TABLE).table
    assert table is not None and (table.row_count, table.column_count) == (2, 2)
    head = next(c for c in table.cells if (c.row_index0, c.column_index0) == (0, 0))
    assert head.column_span == 2 and head.normalized_text == "header"
    assert not any("held_incomplete_grid" in b.quality_flags for b in doc.blocks)


def test_missing_cell_holds_the_table() -> None:
    grid = (TableCell(row=0, col=0, text="a"), TableCell(row=1, col=1, text="d"))
    doc = hwp_result_to_cir(_result(_table(grid, "verified")), CTX)
    block = doc.blocks[0]
    assert block.type == BlockType.TABLE and "held_incomplete_grid" in block.quality_flags
    assert block.table is not None and len(block.table.cells) == 2  # no cell inferred
    assert doc.metadata["hwp"]["acceptedBlockIds"] == []
    assert block.id in doc.metadata["hwp"]["heldBlockIds"]


def test_overlapping_spans_hold_without_choosing_a_winner() -> None:
    grid = (TableCell(row=0, col=0, col_span=2, text="x"), TableCell(row=0, col=1, text="y"))
    doc = hwp_result_to_cir(_result(_table(grid, "verified")), CTX)
    block = doc.blocks[0]
    assert block.table is None and "held_incomplete_grid" in block.quality_flags
    assert doc.metadata["hwp"]["acceptedBlockIds"] == []


def test_embedded_image_region_keeps_anchor_and_is_held() -> None:
    doc = hwp_result_to_cir(_fixture("fixture:embedded_image"), CTX)
    region = doc.blocks[-1]
    assert region.type == BlockType.FIGURE and "held_unresolved_region" in region.quality_flags
    assert region.source_refs[0].native_object_id == "hwp/unresolved/section0/pic1"
    assert doc.metadata["hwp"]["heldRegions"] == [
        {"anchor": "section0/pic1", "reason": "embedded_image", "critical": True}
    ]


def test_unverified_blocks_are_never_accepted() -> None:
    doc = hwp_result_to_cir(_fixture("fixture:complex_table"), CTX)
    assert doc.metadata["hwp"]["acceptedBlockIds"] == []
    assert all(b.confidence is None for b in doc.blocks)
    verified = HwpBlock(
        id="p",
        kind="paragraph",
        text="ok",
        bbox_or_element_anchor="s0/p1",
        original_ref="s0/p1",
        verification_state="verified",
        confidence=0.9,
    )
    doc2 = hwp_result_to_cir(_result(verified), CTX)
    assert doc2.metadata["hwp"]["acceptedBlockIds"] == [doc2.blocks[0].id]
    assert doc2.blocks[0].confidence == 0.9


def test_locator_semantics_is_container_ordinal() -> None:
    doc = hwp_result_to_cir(_fixture("fixture:complex_table"), CTX)
    assert doc.metadata["locatorPageSemantics"] == "container_ordinal"
    assert doc.metadata["documentType"] == "hwp5"
    assert {r.page_index0 for b in doc.blocks for r in b.source_refs} == {0}


def test_duplicate_original_ref_and_hostile_span_fail_closed() -> None:
    p = HwpBlock(
        id="a", kind="paragraph", text="x", bbox_or_element_anchor="s0/p1", original_ref="s0/p1"
    )
    with pytest.raises(StructuredParseError):
        hwp_result_to_cir(_result(p, p.model_copy(update={"id": "b"})), CTX)
    huge = (TableCell(row=0, col=0, row_span=10**9, col_span=10**9, text="x"),)
    with pytest.raises(StructuredParseError):
        hwp_result_to_cir(_result(_table(huge)), CTX)
