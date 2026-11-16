"""Differential comparator for two HWP readers (V31 section 1 item 4).

Compares canonical normalized blocks, never Markdown. Any disagreement on value,
unit, sign, date, table shape, cell or header association, footnote or equation
text holds the region. It never picks a winner, and values are reported by
sha256 only, so no original content reaches a log.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable

from akc_cir import ContractModel
from akc_quality.numeric import extract_numeric_tokens

from .hwp_contract import HwpAdapterResult, HwpBlock, TableCell
from .models import normalize_text

_MINUS = dict.fromkeys((0x2212, 0x2012, 0x2013, 0xFF0D), "-")  # minus, figure/en dash, fullwidth
_MARKUP = re.compile(r"[*_`~|]|^\s*(?:#{1,6}|>|[-+*]|\d+\.)\s+", re.MULTILINE)
_DATE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")


class HeldRegion(ContractModel):
    anchor: str
    field: str
    a_value_sha256: str | None
    b_value_sha256: str | None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canon(text: str) -> str:
    """Whitespace and Markdown-only differences vanish; everything else stays."""

    text = _MARKUP.sub("", normalize_text(text).translate(_MINUS))
    return " ".join(text.split())


def _text_fields(a: str, b: str, kind: str) -> list[tuple[str, str, str]]:
    """(field, a_value, b_value) for every way the two canonical texts differ."""

    ca, cb = _canon(a), _canon(b)
    if ca == cb:
        return []
    ta, tb = extract_numeric_tokens(ca), extract_numeric_tokens(cb)
    if ta == tb:
        field = kind if kind in ("footnote", "equation") else "text"  # unit/word change
    elif tuple(t.lstrip("+-") for t in ta) == tuple(t.lstrip("+-") for t in tb):
        field = "sign"
    elif any(_DATE.match(t) for t in ta + tb) and [t for t in ta if not _DATE.match(t)] == [
        t for t in tb if not _DATE.match(t)
    ]:
        field = "date"
    else:
        field = "number"
    return [(field, ca, cb)]


def _shape(grid: Iterable[TableCell]) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(sorted((c.row, c.col, c.row_span, c.col_span) for c in grid))


def _header(grid: tuple[TableCell, ...], cell: TableCell) -> str:
    for h in grid:
        if h.row == 0 and h.col <= cell.col < h.col + h.col_span:
            return _canon(h.text)
    return ""


def _table_diffs(a: HwpBlock, b: HwpBlock) -> list[tuple[str, str, str]]:
    ga, gb = a.table_grid or (), b.table_grid or ()
    out: list[tuple[str, str, str]] = []
    if _shape(ga) != _shape(gb):
        out.append(("table_shape", repr(_shape(ga)), repr(_shape(gb))))
    ca = {(c.row, c.col): c for c in ga}
    cb = {(c.row, c.col): c for c in gb}
    for pos in sorted(ca.keys() & cb.keys()):  # a missing position is a table_shape hold
        x, y = ca[pos], cb[pos]
        tag = f"cell:r{pos[0]}c{pos[1]}"
        diffs = _text_fields(x.text, y.text, "cell")
        for field, va, vb in diffs:
            out.append((f"{tag}:{field}", va, vb))
        if not diffs and _header(ga, x) != _header(gb, y):
            out.append((f"{tag}:header", _header(ga, x), _header(gb, y)))
    return out


def _by_anchor(blocks: Iterable[HwpBlock]) -> dict[str, list[HwpBlock]]:
    grouped: dict[str, list[HwpBlock]] = defaultdict(list)
    for block in blocks:
        grouped[block.bbox_or_element_anchor].append(block)
    return grouped


def compare_readers(a: HwpAdapterResult, b: HwpAdapterResult) -> tuple[HeldRegion, ...]:
    held: list[HeldRegion] = []

    def hold(anchor: str, field: str, va: str | None, vb: str | None) -> None:
        held.append(
            HeldRegion(
                anchor=anchor,
                field=field,
                a_value_sha256=None if va is None else _sha(va),
                b_value_sha256=None if vb is None else _sha(vb),
            )
        )

    ga, gb = _by_anchor(a.blocks), _by_anchor(b.blocks)
    for anchor in sorted(ga.keys() | gb.keys()):
        la, lb = ga.get(anchor, []), gb.get(anchor, [])
        for i in range(max(len(la), len(lb))):
            x = la[i] if i < len(la) else None
            y = lb[i] if i < len(lb) else None
            if x is None or y is None:
                src = x or y
                assert src is not None
                value = _canon(src.text) + repr(_shape(src.table_grid or ()))
                hold(anchor, "unaligned", value if x else None, value if y else None)
                continue
            if x.kind != y.kind:
                hold(anchor, "kind", x.kind, y.kind)
                continue
            for field, va, vb in _text_fields(x.text, y.text, x.kind):
                hold(anchor, field, va, vb)
            for field, va, vb in _table_diffs(x, y):
                hold(anchor, field, va, vb)

    ra = {(r.anchor, r.reason) for r in a.unresolved_regions}
    rb = {(r.anchor, r.reason) for r in b.unresolved_regions}
    for anchor, reason in sorted(ra - rb):
        hold(anchor, "unresolved_region", reason, None)
    for anchor, reason in sorted(rb - ra):
        hold(anchor, "unresolved_region", None, reason)
    return tuple(held)
