from __future__ import annotations

import hashlib

import pytest
from akc_native_parsers.differential import compare_readers
from akc_native_parsers.hwp_contract import (
    HwpAdapterResult,
    HwpBlock,
    HwpManifest,
    ResourceReceipt,
    TableCell,
    build_result,
)

SHA = hashlib.sha256(b"x").hexdigest()


def _para(text: str, anchor: str = "s0/p1", kind: str = "paragraph") -> HwpBlock:
    return HwpBlock(
        id=anchor.replace("/", "_"),
        kind=kind,
        text=text,
        bbox_or_element_anchor=anchor,
        original_ref=anchor,
    )


def _table(*cells: tuple[int, int, str], anchor: str = "s0/t1") -> HwpBlock:
    return HwpBlock(
        id="t",
        kind="table",
        table_grid=tuple(TableCell(row=r, col=c, text=t) for r, c, t in cells),
        bbox_or_element_anchor=anchor,
        original_ref=anchor,
    )


def _result(*blocks: HwpBlock) -> HwpAdapterResult:
    return build_result(
        engine_id="e",
        engine_version="1",
        manifest=HwpManifest(source_sha256=SHA, detected_format="hwp5"),
        blocks=blocks,
        resource_receipt=ResourceReceipt(wall_ms=0, input_bytes=1, output_bytes=0, exit_code=0),
    )


def test_identical_readers_hold_nothing() -> None:
    r = _result(_para("Total 5 kg on 2026-11-16"), _table((0, 0, "A"), (1, 0, "1")))
    assert compare_readers(r, r) == ()


@pytest.mark.parametrize(
    ("a", "b", "field"),
    [
        ("Total 1,200 items", "Total 1,300 items", "number"),
        ("Weight 5 kg", "Weight 5 g", "text"),
        ("Delta -5", "Delta 5", "sign"),
        ("Delta -5", f"Delta {chr(0x2212)}5", ""),
        ("Due 2026-11-16", "Due 2026-11-17", "date"),
    ],
)
def test_number_unit_sign_and_date_disagreements_each_hold_the_region(
    a: str, b: str, field: str
) -> None:
    held = compare_readers(_result(_para(a)), _result(_para(b)))
    if not field:  # unicode minus is the same sign
        assert held == ()
        return
    assert [(h.anchor, h.field) for h in held] == [("s0/p1", field)]
    h = held[0]
    assert h.a_value_sha256 != h.b_value_sha256
    assert a not in h.model_dump_json() and b not in h.model_dump_json()


def test_footnote_and_equation_text_hold_by_kind() -> None:
    for kind in ("footnote", "equation"):
        held = compare_readers(
            _result(_para("see ref A", kind=kind)), _result(_para("see ref B", kind=kind))
        )
        assert [h.field for h in held] == [kind]


def test_cell_shift_holds_the_table() -> None:
    a = _result(_table((0, 0, "Year"), (0, 1, "Cost"), (1, 0, "2025"), (1, 1, "40")))
    b = _result(_table((0, 0, "Year"), (0, 1, "Cost"), (1, 0, "40"), (1, 1, "2025")))
    held = compare_readers(a, b)
    assert held and {h.anchor for h in held} == {"s0/t1"}
    assert {h.field for h in held} == {"cell:r1c0:number", "cell:r1c1:number"}


def test_table_shape_and_header_association_hold() -> None:
    base = _result(_table((0, 0, "A"), (1, 0, "1")))
    wider = _result(_table((0, 0, "A"), (1, 0, "1"), (1, 1, "2")))
    assert "table_shape" in {h.field for h in compare_readers(base, wider)}
    rehead = _result(_table((0, 0, "B"), (1, 0, "1")))
    assert [h.field for h in compare_readers(base, rehead)] == [
        "cell:r0c0:text",
        "cell:r1c0:header",
    ]


def test_whitespace_and_markup_only_differences_are_ignored() -> None:
    a = _result(_para(f"Total  5{chr(0xA0)}kg\r\n"), _para("note one", anchor="s0/p2"))
    b = _result(_para("**Total** 5 kg"), _para("# note_one".replace("_", " "), anchor="s0/p2"))
    assert compare_readers(a, b) == ()


def test_unalignable_anchor_is_held_not_dropped() -> None:
    a = _result(_para("same"), _para("only in a", anchor="s0/p9"))
    b = _result(_para("same"), _para("only in b", anchor="s0/p8"))
    held = compare_readers(a, b)
    assert [(h.anchor, h.field) for h in held] == [("s0/p8", "unaligned"), ("s0/p9", "unaligned")]
    assert held[0].a_value_sha256 is None and held[0].b_value_sha256
    assert held[1].a_value_sha256 and held[1].b_value_sha256 is None


_VALUE_CASES = [
    ("2026. 11. 16.", "2027. 11. 16."),
    ("3. 500", "4. 500"),
    ("5~10%", "510%"),
    ("- 5", "+ 5"),
    ("- 1,200", "1,200"),
    ("x_1 + y", "x1 + y"),
    ("2*3", "23"),
    ("|a|", "a"),
]


@pytest.mark.parametrize(("a", "b"), _VALUE_CASES)
@pytest.mark.parametrize("kind", ["paragraph", "equation"])
def test_characters_that_carry_values_are_never_stripped_as_markup(
    a: str, b: str, kind: str
) -> None:
    assert compare_readers(_result(_para(a, kind=kind)), _result(_para(b, kind=kind)))


@pytest.mark.parametrize(("a", "b"), _VALUE_CASES)
def test_value_characters_in_cells_hold(a: str, b: str) -> None:
    assert compare_readers(
        _result(_table((0, 0, "H"), (1, 0, a))), _result(_table((0, 0, "H"), (1, 0, b)))
    )


def test_paired_emphasis_is_still_ignored() -> None:
    a = _result(_para("**Total** _net_ 5 kg"), _para("# Note", anchor="s0/p2"))
    b = _result(_para("Total net 5 kg"), _para("Note", anchor="s0/p2"))
    assert compare_readers(a, b) == ()


def test_duplicate_grid_position_holds_the_table() -> None:
    a = _result(_table((0, 0, "A"), (1, 0, "X"), (1, 0, "5")))
    b = _result(_table((0, 0, "A"), (1, 0, "Y"), (1, 0, "5")))
    assert [h.field for h in compare_readers(a, b)] == ["table_grid_ambiguous"]
