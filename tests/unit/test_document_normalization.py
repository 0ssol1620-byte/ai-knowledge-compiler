from __future__ import annotations

from akc_cir import (
    NormalizationBlock,
    detect_repeated_marginal_blocks,
    normalize_block_text,
    restore_cross_page_continuity,
)
from hypothesis import given
from hypothesis import strategies as st


def _block(
    identity: str,
    *,
    page: int,
    order: int,
    block_type: str = "paragraph",
    text: str = "Body",
    bbox: tuple[int, int, int, int] | None = (100, 200, 900, 800),
    refs: tuple[str, ...] | None = None,
) -> NormalizationBlock:
    return NormalizationBlock(
        block_id=identity,
        page_number=page,
        order=order,
        block_type=block_type,
        raw_text=text,
        normalized_text=text,
        bbox1000=bbox,
        source_ref_ids=refs or (f"src-page-{page}-{identity}",),
    )


def test_language_aware_normalizer_preserves_raw_and_protected_content() -> None:
    raw = "A docu-\r\nment explains 인공지능\n시스템.\n문서는\n지식을 보존한다."
    result = normalize_block_text(raw, block_type="paragraph")

    assert result.raw_text == raw
    assert result.normalized_text == (
        "A document explains 인공지능 시스템. 문서는 지식을 보존한다."
    )
    assert "english_line_end_hyphen_joined" in result.operations
    assert "korean_line_spacing_uncertain" in result.quality_flags

    hyphenated = normalize_block_text("well-\nknown behavior", block_type="paragraph")
    assert hyphenated.normalized_text == "well-known behavior"
    assert "english_hyphenated_word_line_joined" in hyphenated.operations

    for protected_type in ("code", "formula", "table", "table_cell"):
        protected = normalize_block_text(
            "left-\nright\n다음 줄",
            block_type=protected_type,
        )
        assert protected.raw_text == "left-\nright\n다음 줄"
        assert protected.normalized_text == "left-\nright\n다음 줄"
        assert protected.operations == ("line_merge_skipped_protected_content",)


@given(st.text(max_size=1_000))
def test_text_normalization_is_deterministic_idempotent_and_raw_preserving(value: str) -> None:
    first = normalize_block_text(value, block_type="paragraph")
    repeated = normalize_block_text(value, block_type="paragraph")
    normalized_again = normalize_block_text(first.normalized_text, block_type="paragraph")

    assert first == repeated
    assert first.raw_text == value
    assert normalized_again.normalized_text == first.normalized_text


def test_repeated_margin_detection_uses_position_and_multipage_similarity() -> None:
    blocks: list[NormalizationBlock] = []
    for page in range(1, 6):
        blocks.extend(
            (
                _block(
                    f"header-{page}",
                    page=page,
                    order=page * 10,
                    text=f"Acme Research Report {page}",
                    bbox=(100, 20, 900, 90),
                ),
                _block(
                    f"footer-{page}",
                    page=page,
                    order=page * 10 + 1,
                    text=f"Copyright 2026 Acme - {page}",
                    bbox=(100, 920, 900, 980),
                ),
                _block(
                    f"heading-{page}",
                    page=page,
                    order=page * 10 + 2,
                    block_type="heading",
                    text="Repeated chapter title",
                    bbox=(100, 30, 900, 100),
                ),
            )
        )

    annotations = detect_repeated_marginal_blocks(blocks, total_pages=5)
    by_id = {annotation.block_id: annotation for annotation in annotations}

    assert all(by_id[f"header-{page}"].classified_type == "header" for page in range(1, 6))
    assert all(by_id[f"header-{page}"].excluded_from_body for page in range(1, 6))
    assert all(not by_id[f"footer-{page}"].excluded_from_body for page in range(1, 6))
    assert not any(identity.startswith("heading-") for identity in by_id)
    assert all(annotation.payload()["preservedInCir"] is True for annotation in annotations)


def test_cross_page_paragraph_restoration_has_two_refs_and_uncertainty() -> None:
    restoration = restore_cross_page_continuity(
        (
            _block(
                "left",
                page=1,
                order=1,
                text="The document contin-",
                refs=("src-a",),
            ),
            _block(
                "right",
                page=2,
                order=2,
                text="ues on the next page.",
                refs=("src-b",),
            ),
        )
    )

    assert len(restoration) == 1
    assert restoration[0].kind == "paragraph_continuation"
    assert restoration[0].source_ref_ids == ("src-a", "src-b")
    assert restoration[0].uncertain is True
    assert restoration[0].payload()["sourceRefIds"] == ["src-a", "src-b"]


def test_all_named_cross_page_restoration_contracts_are_supported() -> None:
    cases = (
        (
            "split_table_header",
            _block(
                "table-a",
                page=1,
                order=1,
                block_type="table",
                text="Name | Value\nA | 1",
            ),
            _block(
                "table-b",
                page=2,
                order=2,
                block_type="table",
                text="Name | Value\nB | 2",
            ),
        ),
        (
            "figure_caption_continuation",
            _block("figure", page=1, order=1, block_type="figure", text="Chart"),
            _block("caption", page=2, order=2, block_type="caption", text="Figure 1"),
        ),
        (
            "footnote_continuation",
            _block("foot-a", page=1, order=1, block_type="footnote", text="1 Continued"),
            _block("foot-b", page=2, order=2, block_type="footnote", text="footnote."),
        ),
        (
            "heading_body_continuation",
            _block(
                "heading",
                page=1,
                order=1,
                block_type="heading",
                text="2 Results",
                bbox=(100, 820, 900, 900),
            ),
            _block("body", page=2, order=2, text="The measured result."),
        ),
    )

    for expected, left, right in cases:
        result = restore_cross_page_continuity((left, right))
        assert len(result) == 1
        assert result[0].kind == expected
        assert len(result[0].source_ref_ids) >= 2

    no_provenance = restore_cross_page_continuity(
        (
            _block("left", page=1, order=1, text="Incomplete", refs=("same",)),
            _block("right", page=2, order=2, text="sentence.", refs=("same",)),
        )
    )
    assert no_provenance == ()
