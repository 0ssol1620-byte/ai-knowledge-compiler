from __future__ import annotations

import csv
import io
import math
import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from akc_api.credit_policy import (
    CreditPolicyError,
    CreditState,
    apply_credit_transition,
)
from akc_cir import (
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalCell,
    CanonicalDocument,
    CanonicalTable,
    ContentLayer,
    SourceRef,
    sha256_digest,
)
from akc_exporters import deterministic_zip, portable_slug, table_to_csv
from akc_exporters.markdown import _fenced_code
from akc_quality import compare_numeric_tokens
from akc_router import detect_script_distribution
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError


@given(
    x1=st.integers(min_value=0, max_value=999),
    y1=st.integers(min_value=0, max_value=999),
    width=st.integers(min_value=1, max_value=1000),
    height=st.integers(min_value=1, max_value=1000),
)
def test_bbox_round_trip_property(x1: int, y1: int, width: int, height: int) -> None:
    x2 = min(1000, x1 + width)
    y2 = min(1000, y1 + height)
    box = BBox1000([x1, y1, x2, y2])
    assert box.as_tuple() == (x1, y1, x2, y2)
    assert all(0.0 <= value <= 1.0 for value in box.as_unit_interval())


@given(st.integers(min_value=1, max_value=999))
def test_bbox_rejects_reversed_coordinates(value: int) -> None:
    with pytest.raises(ValidationError):
        BBox1000([value, 0, value - 1, 1])


@given(st.text(max_size=500))
def test_script_distribution_is_normalized(text: str) -> None:
    distribution = detect_script_distribution(text)
    assert all(0.0 <= value <= 1.0 for value in distribution.values())
    if distribution:
        assert math.isclose(sum(distribution.values()), 1.0)


@given(st.text(min_size=1, max_size=200))
def test_portable_slug_never_emits_path_separators(value: str) -> None:
    slug = portable_slug(value)
    assert slug
    assert "/" not in slug
    assert "\\" not in slug
    assert len(slug) <= 96


@given(st.lists(st.integers(min_value=-100000, max_value=100000), max_size=30))
def test_numeric_fidelity_is_reflexive(values: list[int]) -> None:
    text = " ".join(str(value) for value in values)
    assert compare_numeric_tokens(text, text).score == 1.0


@given(
    st.dictionaries(
        keys=st.from_regex(r"[a-z]{1,8}\.txt", fullmatch=True),
        values=st.binary(max_size=100),
        max_size=10,
    )
)
def test_zip_is_insertion_order_independent(files: dict[str, bytes]) -> None:
    reverse = dict(reversed(tuple(files.items())))
    assert deterministic_zip(files) == deterministic_zip(reverse)


@given(st.permutations(tuple(range(8))))
def test_document_page_order_is_stable_for_any_input_order(
    insertion_order: list[int],
) -> None:
    blocks: list[CanonicalBlock] = []
    for page_index0 in insertion_order:
        text = f"page-{page_index0 + 1}"
        blocks.append(
            CanonicalBlock(
                id=f"blk_{page_index0:03d}",
                order=page_index0,
                type=BlockType.PARAGRAPH,
                content_layer=ContentLayer.STRUCTURED,
                raw_text=text,
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(
                    SourceRef(
                        document_id="document",
                        document_version_id="version",
                        page_index0=page_index0,
                        page_number1=page_index0 + 1,
                    ),
                ),
                content_hash=sha256_digest(text),
            )
        )
    document = CanonicalDocument(
        tenant_id="tenant",
        document_id="document",
        document_version_id="version",
        title="Stable order",
        source_filename="source.pdf",
        source_sha256=sha256_digest(b"source"),
        content_layer=ContentLayer.STRUCTURED,
        blocks=tuple(blocks),
        created_at=datetime.now(UTC),
    )
    assert [block.source_refs[0].page_number1 for block in document.ordered_blocks()] == list(
        range(1, 9)
    )


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["grant", "reserve", "consume", "release", "refund", "adjust"]),
            st.integers(min_value=1, max_value=100),
            st.booleans(),
        ),
        min_size=1,
        max_size=100,
    )
)
def test_credit_transitions_never_break_balance_invariants(
    actions: list[tuple[str, int, bool]],
) -> None:
    state = CreditState(balance=Decimal("100"), reserved=Decimal("0"))
    for entry_type, credits, from_reserved in actions:
        before = state
        try:
            state = apply_credit_transition(
                state,
                entry_type=entry_type,
                credits=Decimal(credits),
                from_reserved=from_reserved,
            )
        except CreditPolicyError:
            assert state == before
        assert Decimal("0") <= state.reserved <= state.balance
        assert state.available == state.balance - state.reserved


@given(st.text(max_size=2_000))
def test_markdown_code_fence_always_outnests_source_content(text: str) -> None:
    rendered = _fenced_code(text)
    fence = rendered.splitlines()[0]
    longest_source_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)),
        default=0,
    )
    assert set(fence) == {"`"}
    assert len(fence) >= 3
    assert len(fence) > longest_source_run
    assert rendered == f"{fence}\n{text}\n{fence}"


@given(
    rows=st.integers(min_value=1, max_value=8),
    columns=st.integers(min_value=1, max_value=8),
    data=st.data(),
)
def test_table_csv_rows_always_match_declared_width(
    rows: int,
    columns: int,
    data: st.DataObject,
) -> None:
    values = data.draw(
        st.lists(
            st.text(max_size=50),
            min_size=rows * columns,
            max_size=rows * columns,
        )
    )
    source_ref = SourceRef(
        document_id="document",
        document_version_id="version",
        page_index0=0,
        page_number1=1,
    )
    cells = tuple(
        CanonicalCell(
            id=f"cell_{row:02d}_{column:02d}",
            row_index0=row,
            column_index0=column,
            raw_text=values[row * columns + column],
            normalized_text=values[row * columns + column],
            origin=BlockOrigin.NATIVE_EXTRACTED,
            source_refs=(source_ref,),
        )
        for row in range(rows)
        for column in range(columns)
    )
    table = CanonicalTable(
        id="table_001",
        row_count=rows,
        column_count=columns,
        cells=cells,
        source_refs=(source_ref,),
    )
    parsed_rows = list(csv.reader(io.StringIO(table_to_csv(table))))
    assert len(parsed_rows) == rows
    assert all(len(row) == columns for row in parsed_rows)
