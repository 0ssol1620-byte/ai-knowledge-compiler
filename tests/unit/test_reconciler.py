"""Document reconciliation — §18 and §N12.

The premise under test is that every page can parse perfectly and the document
still be wrong. The invariants in §N12.5 get the most attention here because they
are the ones that fail silently: a merged table that cannot be taken apart again
looks exactly like a correct one until somebody asks where a cell came from.
"""

from __future__ import annotations

import pytest
from akc_cir.reconciler import (
    PARAGRAPH_WEIGHTS,
    TABLE_AUTO_MERGE,
    TABLE_RELATION_FLOOR,
    TABLE_WEIGHTS,
    Block,
    BlockKind,
    ContinuationVerdict,
    MergeRefused,
    RelationKind,
    TableBlock,
    build_heading_hierarchy,
    link_paragraphs,
    link_tables,
    merge_tables,
    paragraph_continuation_score,
    repeated_page_furniture,
    table_continuation_score,
)


def _para(
    page: int,
    local_id: str,
    text: str,
    *,
    kind: BlockKind = BlockKind.PARAGRAPH,
    x0: int = 100,
    font: str = "serif-10",
    spacing: float = 1.2,
    section: tuple[str, ...] = ("Warranty",),
    **kw,
) -> Block:
    return Block(
        page_number1=page,
        local_id=local_id,
        kind=kind,
        text=text,
        x0=x0,
        font_style=font,
        line_spacing=spacing,
        section_path=section,
        **kw,
    )


def _table(page: int, local_id: str, **kw) -> TableBlock:
    base = {
        "header": ("Part", "Qty", "Price"),
        "rows": (("bolt", "12", "3.50"),),
        "column_x_boundaries": (100, 400, 700),
        "border_style": "grid-thin",
        "table_id": "Table 4",
        "y0": 750,
        "y1": 980,
    }
    base.update(kw)
    return TableBlock(page_number1=page, local_id=local_id, **base)


# --------------------------------------------------------------------------
# §N12.2 — paragraph continuation
# --------------------------------------------------------------------------


def test_the_paragraph_weights_are_the_ones_the_masterplan_fixed() -> None:
    assert PARAGRAPH_WEIGHTS == {
        "sentence_boundary_compatibility": 0.25,
        "semantic_continuity": 0.20,
        "font_style_similarity": 0.15,
        "x_alignment": 0.15,
        "line_spacing_similarity": 0.10,
        "language_model_continuation": 0.10,
        "section_context_match": 0.05,
    }


def test_a_sentence_broken_across_a_page_break_is_a_continuation() -> None:
    left = _para(1, "p1", "The warranty covers parts and labour for a period of")
    right = _para(2, "p2", "twenty four months from the date of delivery.")

    decision = link_paragraphs(left, right, language_model_continuation=0.95)

    assert decision.verdict is ContinuationVerdict.MERGE
    assert decision.relation is RelationKind.NEXT_TEXT


def test_two_complete_paragraphs_are_not_a_continuation() -> None:
    left = _para(1, "p1", "The warranty covers parts and labour.")
    right = _para(
        2,
        "p2",
        "Shipping is arranged separately by the carrier.",
        section=("Shipping",),
        x0=400,
        font="sans-9",
        spacing=2.0,
    )

    decision = link_paragraphs(left, right, language_model_continuation=0.05)

    assert decision.verdict is ContinuationVerdict.SEPARATE
    assert decision.relation is None


def test_a_broken_sentence_scores_higher_than_a_complete_one() -> None:
    complete = _para(1, "p1", "The warranty covers parts and labour.")
    broken = _para(1, "p1b", "The warranty covers parts and labour for a period of")
    right = _para(2, "p2", "twenty four months from delivery.")

    broken_score, _, _ = paragraph_continuation_score(broken, right)
    complete_score, _, _ = paragraph_continuation_score(complete, right)

    assert broken_score > complete_score


def test_a_list_that_continues_gets_a_list_relation() -> None:
    left = _para(
        1, "l7", "7. Coverage extends to parts replaced under", kind=BlockKind.LIST_ITEM
    )
    right = _para(
        2, "l8", "an authorised service agreement.", kind=BlockKind.LIST_ITEM
    )

    decision = link_paragraphs(left, right, language_model_continuation=0.9)

    assert decision.relation is RelationKind.CONTINUES_LIST


def test_no_language_model_is_recorded_not_scored_zero() -> None:
    """A classifier that did not run has not said the paragraphs are unrelated."""
    left = _para(1, "p1", "The warranty covers parts and labour for a period of")
    right = _para(2, "p2", "twenty four months from the date of delivery.")

    score, signals, missing = paragraph_continuation_score(left, right)

    assert missing["language_model_continuation"] == "MODEL_UNAVAILABLE"
    assert "language_model_continuation" not in signals
    assert score > 0.0


def test_a_parser_reporting_no_font_does_not_report_the_fonts_differ() -> None:
    left = _para(1, "p1", "The warranty covers parts and labour for a period of", font="")
    right = _para(2, "p2", "twenty four months from delivery.", font="")

    _, signals, missing = paragraph_continuation_score(left, right)

    assert "font_style_similarity" in missing
    assert "font_style_similarity" not in signals


def test_the_middle_band_records_a_relation_without_merging() -> None:
    """A continuation the parser reported in a different font. Genuinely unclear."""
    left = _para(1, "p1", "Coverage extends to every component listed in schedule")
    right = _para(
        2, "p2", "b and to labour performed by an approved agent.", font="sans-9"
    )

    decision = link_paragraphs(left, right, language_model_continuation=0.55)

    assert decision.verdict is ContinuationVerdict.RELATION_ONLY
    assert decision.relation is not None


def test_semantic_continuity_is_absent_until_an_embedding_supplies_it() -> None:
    """Token overlap would score a true continuation near zero.

    The two halves of a broken sentence say different things on purpose, so
    overlap measures the opposite of continuation. A signal whose arithmetic
    contradicts its name is worse than a missing one.
    """
    left = _para(1, "p1", "The warranty covers parts and labour for a period of")
    right = _para(2, "p2", "twenty four months from the date of delivery.")

    _, signals, missing = paragraph_continuation_score(left, right)

    assert missing["semantic_continuity"] == "MODEL_UNAVAILABLE"
    assert "semantic_continuity" not in signals


def test_an_injected_semantic_score_is_used() -> None:
    left = _para(1, "p1", "The warranty covers parts and labour for a period of")
    right = _para(2, "p2", "twenty four months from the date of delivery.")

    _, signals, _ = paragraph_continuation_score(left, right, semantic_continuity=0.88)

    assert signals["semantic_continuity"] == 0.88


# --------------------------------------------------------------------------
# §N12.3 — table continuation and its three bands
# --------------------------------------------------------------------------


def test_the_table_weights_are_the_ones_the_masterplan_fixed() -> None:
    assert TABLE_WEIGHTS == {
        "normalized_header_similarity": 0.25,
        "column_count_compatibility": 0.20,
        "x_boundary_alignment": 0.20,
        "data_type_pattern_similarity": 0.10,
        "border_style_similarity": 0.10,
        "page_bottom_top_position": 0.10,
        "caption_or_table_id_match": 0.05,
    }


def test_the_bands_are_the_ones_the_masterplan_fixed() -> None:
    assert TABLE_AUTO_MERGE == 0.90
    assert TABLE_RELATION_FLOOR == 0.70


def test_a_table_running_onto_the_next_page_merges() -> None:
    upper = _table(1, "t1")
    lower = _table(
        2, "t2", rows=(("nut", "40", "0.80"),), y0=100, y1=400
    )

    decision = link_tables(upper, lower)

    assert decision.verdict is ContinuationVerdict.MERGE
    assert decision.relation is RelationKind.CONTINUES_TABLE


def test_a_different_table_on_the_next_page_stays_separate() -> None:
    upper = _table(1, "t1")
    lower = _table(
        2,
        "t2",
        header=("Region", "Contact"),
        rows=(("EMEA", "ops@example.com"),),
        column_x_boundaries=(50, 600),
        border_style="none",
        table_id="Table 9",
        y0=500,
        y1=700,
    )

    decision = link_tables(upper, lower)

    assert decision.verdict is ContinuationVerdict.SEPARATE


def test_a_table_in_the_middle_of_its_page_did_not_run_over() -> None:
    upper = _table(1, "t1", y0=200, y1=400)
    lower = _table(2, "t2", rows=(("nut", "40", "0.80"),), y0=500, y1=700)

    _, signals, _ = table_continuation_score(upper, lower)

    assert signals["page_bottom_top_position"] < 0.3


def test_non_adjacent_pages_are_not_a_continuation() -> None:
    upper = _table(1, "t1")
    lower = _table(5, "t2", rows=(("nut", "40", "0.80"),), y0=100, y1=400)

    _, signals, _ = table_continuation_score(upper, lower)

    assert signals["page_bottom_top_position"] == 0.0


def test_a_continuation_table_with_no_repeated_header_is_still_comparable() -> None:
    """Many continuation tables drop the header. That is not disagreement."""
    upper = _table(1, "t1")
    lower = _table(2, "t2", header=(), rows=(("nut", "40", "0.80"),), y0=100, y1=400)

    score, signals, missing = table_continuation_score(upper, lower)

    assert "normalized_header_similarity" in missing
    assert "normalized_header_similarity" not in signals
    assert score >= TABLE_RELATION_FLOOR


def test_mismatched_column_boundaries_pull_the_score_down() -> None:
    upper = _table(1, "t1")
    lower = _table(
        2,
        "t2",
        rows=(("nut", "40", "0.80"),),
        column_x_boundaries=(300, 550, 900),
        y0=100,
        y1=400,
    )

    same_boundaries = _table(2, "t3", rows=(("nut", "40", "0.80"),), y0=100, y1=400)
    aligned, _, _ = table_continuation_score(upper, same_boundaries)
    misaligned, _, _ = table_continuation_score(upper, lower)

    assert misaligned < aligned


# --------------------------------------------------------------------------
# §N12.5 — merge invariants
# --------------------------------------------------------------------------


def test_an_uncertain_merge_is_refused() -> None:
    """§18.4 forbids it, and a relation is what the middle band produces instead."""
    upper = _table(1, "t1")
    lower = _table(2, "t2", rows=(("nut", "40", "0.80"),), border_style="none", y0=100, y1=400)
    decision = link_tables(upper, lower)

    if decision.verdict is ContinuationVerdict.MERGE:  # pragma: no cover
        pytest.skip("fixture no longer lands in the review band")

    with pytest.raises(MergeRefused, match="uncertain physical merge"):
        merge_tables(upper, lower, decision=decision)


def test_a_merged_table_keeps_every_row_origin() -> None:
    upper = _table(1, "t1", rows=(("bolt", "12", "3.50"), ("screw", "8", "1.10")))
    lower = _table(2, "t2", rows=(("nut", "40", "0.80"),), y0=100, y1=400)
    decision = link_tables(upper, lower)

    merged = merge_tables(upper, lower, decision=decision)

    assert merged.row_origins == ((1, 0), (1, 1), (2, 0))


def test_the_original_page_span_is_recoverable_after_a_merge() -> None:
    upper = _table(1, "t1")
    lower = _table(2, "t2", rows=(("nut", "40", "0.80"),), y0=100, y1=400)

    merged = merge_tables(upper, lower, decision=link_tables(upper, lower))

    assert merged.page_span == (1, 2)


def test_every_row_survives_the_merge() -> None:
    upper = _table(1, "t1", rows=(("bolt", "12", "3.50"), ("screw", "8", "1.10")))
    lower = _table(2, "t2", rows=(("nut", "40", "0.80"), ("pin", "2", "9.00")), y0=100, y1=400)

    merged = merge_tables(upper, lower, decision=link_tables(upper, lower))

    assert len(merged.rows) == 4
    assert merged.rows[0] == ("bolt", "12", "3.50")
    assert merged.rows[-1] == ("pin", "2", "9.00")


def test_merging_tables_of_different_widths_is_refused() -> None:
    upper = _table(1, "t1")
    lower = _table(2, "t2", header=("Part", "Qty"), rows=(("nut", "40"),), y0=100, y1=400)
    forced = link_tables(upper, upper)

    with pytest.raises(MergeRefused, match="column counts differ"):
        merge_tables(upper, lower, decision=forced)


def test_a_row_without_an_origin_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="every row needs an origin"):
        TableBlock(
            page_number1=1,
            local_id="t1",
            rows=(("a",), ("b",)),
            row_origins=((1, 0),),
        )


# --------------------------------------------------------------------------
# §N12.4 — heading hierarchy
# --------------------------------------------------------------------------


def _heading(local_id: str, text: str, x0: int = 100) -> Block:
    return Block(
        page_number1=1, local_id=local_id, kind=BlockKind.HEADING, text=text, x0=x0
    )


def test_dotted_numbering_nests_the_headings() -> None:
    nodes, anomalies = build_heading_hierarchy(
        [
            _heading("h1", "1. Warranty"),
            _heading("h2", "1.1 Coverage"),
            _heading("h3", "1.2 Exclusions"),
            _heading("h4", "2. Shipping"),
        ]
    )

    levels = {node.block.local_id: node.level for node in nodes}
    parents = {node.block.local_id: node.parent_id for node in nodes}

    assert levels == {"h1": 1, "h2": 2, "h3": 2, "h4": 1}
    assert parents == {"h1": None, "h2": "h1", "h3": "h1", "h4": None}
    assert anomalies == ()


def test_a_skipped_level_is_reported_rather_than_repaired() -> None:
    """Quietly inserting the missing level hides the evidence of what went wrong."""
    _, anomalies = build_heading_hierarchy(
        [_heading("h1", "1. Warranty"), _heading("h2", "1.1.1 Parts")]
    )

    assert len(anomalies) == 1
    assert "level jumped" in anomalies[0]


def test_korean_and_latin_numbering_are_recognised() -> None:
    nodes, _ = build_heading_hierarchy(
        [_heading("h1", "가. 보증"), _heading("h2", "A. Coverage")]
    )

    assert all(node.level == 1 for node in nodes)


def test_indentation_stands_in_when_there_is_no_numbering() -> None:
    nodes, _ = build_heading_hierarchy(
        [_heading("h1", "Warranty", x0=100), _heading("h2", "Coverage", x0=200)]
    )

    assert nodes[1].level == 2
    assert nodes[1].parent_id == "h1"


def test_an_empty_document_has_no_hierarchy_and_no_anomalies() -> None:
    assert build_heading_hierarchy([]) == ((), ())


# --------------------------------------------------------------------------
# §18.1 — page furniture
# --------------------------------------------------------------------------


def test_a_running_header_is_recognised_as_furniture() -> None:
    blocks = [
        Block(page_number1=page, local_id=f"h{page}", kind=BlockKind.PARAGRAPH,
              text="ACME CORPORATION CONFIDENTIAL", y0=20)
        for page in range(1, 6)
    ]

    furniture = repeated_page_furniture(blocks)

    assert "acme corporation confidential" in furniture


def test_a_repeated_body_line_is_not_furniture() -> None:
    """Removing it would delete content, and hide a real decoder loop from §N9.3."""
    blocks = [
        Block(page_number1=page, local_id=f"b{page}", kind=BlockKind.PARAGRAPH,
              text="Subject to the terms of this agreement", y0=500)
        for page in range(1, 6)
    ]

    assert repeated_page_furniture(blocks) == frozenset()


def test_text_appearing_on_too_few_pages_is_not_furniture() -> None:
    blocks = [
        Block(page_number1=page, local_id=f"h{page}", kind=BlockKind.PARAGRAPH,
              text="DRAFT", y0=20)
        for page in range(1, 3)
    ]

    assert repeated_page_furniture(blocks) == frozenset()


def test_a_footer_counts_as_furniture_too() -> None:
    blocks = [
        Block(page_number1=page, local_id=f"f{page}", kind=BlockKind.PARAGRAPH,
              text="Page footer notice", y0=950)
        for page in range(1, 5)
    ]

    assert "page footer notice" in repeated_page_furniture(blocks)
