from __future__ import annotations

import json

from akc_cir import (
    NormalizationBlock,
    analyze_document_structure,
    infer_heading_hierarchy,
    infer_reading_order,
)


def _block(
    block_id: str,
    *,
    page: int = 1,
    order: int = 0,
    block_type: str = "paragraph",
    text: str | None = None,
    bbox: tuple[int, int, int, int] | None = None,
    provider_order: int | None = None,
    provider_label: str | None = None,
    font_size: float | None = None,
    font_weight: int | None = None,
    whitespace_before: float | None = None,
    whitespace_after: float | None = None,
    heading_level: int | None = None,
    is_toc_entry: bool = False,
    toc_level: int | None = None,
) -> NormalizationBlock:
    value = text or block_id
    return NormalizationBlock(
        block_id=block_id,
        page_number=page,
        order=order,
        block_type=block_type,
        raw_text=value,
        normalized_text=value,
        bbox1000=bbox,
        source_ref_ids=(f"src-{block_id}",),
        provider_order=provider_order,
        provider_label=provider_label,
        font_size_pt=font_size,
        font_weight=font_weight,
        whitespace_before=whitespace_before,
        whitespace_after=whitespace_after,
        explicit_heading_level=heading_level,
        is_toc_entry=is_toc_entry,
        toc_level=toc_level,
        markdown=value,
    )


def test_multicolumn_order_is_stable_and_column_first() -> None:
    blocks = (
        _block("right-2", order=3, bbox=(550, 190, 950, 240), provider_order=3),
        _block("left-1", order=0, bbox=(50, 100, 450, 150), provider_order=0),
        _block("right-1", order=1, bbox=(550, 90, 950, 140), provider_order=1),
        _block("left-2", order=2, bbox=(50, 200, 450, 250), provider_order=2),
    )

    first = infer_reading_order(blocks)
    second = infer_reading_order(tuple(reversed(blocks)))

    assert first.ordered_block_ids == ("left-1", "left-2", "right-1", "right-2")
    assert second.ordered_block_ids == first.ordered_block_ids
    assert {record.column_count for record in first.records} == {2}
    assert all("column_cluster_assigned" in record.evidence for record in first.records)


def test_overlap_and_cross_page_continuation_emit_uncertainty() -> None:
    blocks = (
        _block(
            "page-1-a",
            order=0,
            text="This sentence continues",
            bbox=(60, 760, 800, 900),
        ),
        _block(
            "page-1-overlap",
            order=1,
            bbox=(100, 790, 850, 930),
        ),
        _block(
            "page-2-a",
            page=2,
            order=0,
            text="on the next page.",
            bbox=(60, 80, 800, 180),
        ),
    )

    result = infer_reading_order(blocks)
    records = result.record_by_id()

    assert {"page-1-a", "page-1-overlap"}.issubset(result.uncertain_block_ids)
    assert "substantial_bbox_overlap" in records["page-1-a"].evidence
    assert records["page-2-a"].cross_page_relation == "possible_prose_continuation"
    assert records["page-2-a"].quality_flags == ("reading_order_uncertain",)


def test_missing_geometry_uses_provider_order_and_flags_ambiguity() -> None:
    result = infer_reading_order(
        (
            _block("b", order=1, provider_order=1),
            _block("a", order=0, provider_order=0),
            _block("unknown", order=-1),
        )
    )

    assert result.ordered_block_ids == ("a", "b", "unknown")
    assert result.record_by_id()["unknown"].uncertain is True
    assert "no_provider_or_geometry_order" in result.record_by_id()["unknown"].evidence


def test_heading_hierarchy_preserves_stable_parents_and_warns_on_jump() -> None:
    blocks = (
        _block(
            "title",
            order=0,
            block_type="title",
            text="Reliable Systems",
            font_size=24,
            font_weight=700,
        ),
        _block(
            "chapter",
            order=1,
            block_type="heading",
            text="1 Introduction",
            heading_level=2,
            font_size=18,
            font_weight=700,
        ),
        _block(
            "deep",
            order=2,
            block_type="heading",
            text="1.1.1 Constraints",
            heading_level=4,
            font_size=14,
            font_weight=700,
        ),
        _block("body", order=3, text="Body text.", font_size=10),
    )

    result = infer_heading_hierarchy(blocks)
    records = {record.block_id: record for record in result.records}

    assert records["chapter"].parent_id == "title"
    assert records["deep"].parent_id == "chapter"
    assert "heading_level_jump" in records["deep"].warnings
    assert "heading_numbering_parent_missing" in records["deep"].warnings
    assert records["body"].is_heading is False


def test_toc_validation_and_llm_payload_are_bounded_candidate_only() -> None:
    blocks = (
        _block(
            "toc-title",
            order=0,
            block_type="heading",
            text="Table of Contents",
        ),
        _block(
            "toc-entry",
            order=1,
            text="2 Methods .... 4",
            is_toc_entry=True,
            toc_level=2,
        ),
        _block(
            "methods",
            page=4,
            order=2,
            block_type="heading",
            text="2 Methods",
            heading_level=2,
        ),
        _block(
            "ambiguous",
            page=4,
            order=3,
            text="A. Potential subsection",
            font_size=13,
            font_weight=700,
            whitespace_before=18,
            whitespace_after=5,
        ),
    )

    result = infer_heading_hierarchy(blocks)
    records = {record.block_id: record for record in result.records}
    encoded = json.dumps(
        result.llm_candidate_payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode()

    assert records["methods"].toc_status == "matched"
    assert records["methods"].toc_anchor == "methods"
    assert records["ambiguous"].llm_candidate is True
    assert len(encoded) <= 32_768
    assert "rawText" not in result.llm_candidate_payload
    assert result.llm_candidate_payload["purpose"] == (
        "heading_ambiguity_candidate_review"
    )


def test_combined_analysis_reorders_before_heading_parent_assignment() -> None:
    blocks = (
        _block(
            "child",
            order=0,
            block_type="heading",
            text="1.1 Child",
            bbox=(550, 180, 900, 230),
            heading_level=3,
        ),
        _block(
            "parent",
            order=1,
            block_type="heading",
            text="1 Parent",
            bbox=(60, 100, 440, 150),
            heading_level=2,
        ),
    )

    reading, headings = analyze_document_structure(blocks)
    records = {record.block_id: record for record in headings.records}

    assert reading.ordered_block_ids == ("parent", "child")
    assert records["child"].parent_id == "parent"
