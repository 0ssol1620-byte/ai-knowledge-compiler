"""Differential comparator for two HWP readers (V31 section 1 item 4).

Compares canonical normalized blocks, never Markdown. Any disagreement on value,
unit, sign, date, table shape, cell or header association, footnote or equation
text holds the region. It never picks a winner, and values are reported by
sha256 only, so no original content reaches a log.

Every pass is linear (or n log n) in the input, because every document is hostile:
regexes cannot backtrack across a delimiter, and a table's headers are resolved
and hashed once per grid, never once per cell.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable

from akc_cir import ContractModel
from akc_quality.numeric import extract_numeric_tokens

from .hwp_contract import HwpAdapterResult, HwpBlock, TableCell
from .models import normalize_text

_MINUS = dict.fromkeys((0x2212, 0x2012, 0x2013, 0xFF0D), "-")  # minus, figure/en dash, fullwidth
_HEADING = re.compile(r"^#{1,6}[ \t]+", re.MULTILINE)
# the body cannot contain its own delimiter, so a scan stops at the next one
_EMPHASIS = re.compile(
    r"\*\*([^\s*](?:[^*\n]*[^\s*])?)\*\*|(?<!\w)_([^\s_](?:[^_\n]*[^\s_])?)_(?!\w)"
)
_DATE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")


class HeldRegion(ContractModel):
    anchor: str
    field: str
    a_value_sha256: str | None
    b_value_sha256: str | None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_NO_HEADER = _sha("")


def _collapse(text: str) -> str:
    return " ".join(normalize_text(text).translate(_MINUS).split())


def _canon(text: str, kind: str = "paragraph") -> str:
    """Whitespace, paired emphasis and a leading heading mark vanish; all else stays.

    The text is engine text, not Markdown: `~ | _ *`, `N.` and sign marks carry
    values and are never stripped, and equation blocks are never touched.
    """

    text = normalize_text(text).translate(_MINUS)
    if kind in ("paragraph", "heading"):
        text = _HEADING.sub("", text)
    if kind != "equation":
        text = _EMPHASIS.sub(lambda m: m.group(1) or m.group(2), text)
    return " ".join(text.split())


def _text_fields(a: str, b: str, kind: str) -> list[tuple[str, str, str]]:
    """(field, a_sha256, b_sha256) for every way the two canonical texts differ."""

    ca, cb = _canon(a, kind), _canon(b, kind)
    ta, tb = extract_numeric_tokens(_collapse(a)), extract_numeric_tokens(_collapse(b))
    if ca == cb and ta == tb:
        return []
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
    return [(field, _sha(ca), _sha(cb))]


def _shape(grid: Iterable[TableCell]) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(sorted((c.row, c.col, c.row_span, c.col_span) for c in grid))


def _headers(grid: tuple[TableCell, ...]) -> dict[int, str]:
    """col -> sha256 of the first row-0 cell (grid order) whose span covers it.

    Each used column is assigned once (union-find over the sorted used columns),
    so overlapping or huge spans cost O(cells log cells), and each header is
    canonicalized and hashed once, however many cells sit under it.
    """

    cols = sorted({c.col for c in grid})
    nxt = list(range(len(cols) + 1))  # nxt[i]: first unassigned index >= i

    def find(i: int) -> int:
        while nxt[i] != i:
            nxt[i] = nxt[nxt[i]]
            i = nxt[i]
        return i

    out: dict[int, str] = {}
    for h in grid:
        if h.row != 0:
            continue
        i = find(bisect_left(cols, h.col))
        if i < len(cols) and cols[i] < h.col + h.col_span:
            digest = _sha(_canon(h.text, "cell"))
            while i < len(cols) and cols[i] < h.col + h.col_span:
                out[cols[i]] = digest
                nxt[i] = i + 1
                i = find(i + 1)
    return out


def _table_diffs(a: HwpBlock, b: HwpBlock) -> list[tuple[str, str, str]]:
    ga, gb = a.table_grid or (), b.table_grid or ()
    out: list[tuple[str, str, str]] = []
    if len({(c.row, c.col) for c in ga}) != len(ga) or len({(c.row, c.col) for c in gb}) != len(gb):
        # repeated positions: no cell can be paired safely, so hold the whole table
        return [("table_grid_ambiguous", _sha(repr(_shape(ga))), _sha(repr(_shape(gb))))]
    if _shape(ga) != _shape(gb):
        out.append(("table_shape", _sha(repr(_shape(ga))), _sha(repr(_shape(gb)))))
    ha, hb = _headers(ga), _headers(gb)
    ca = {(c.row, c.col): c for c in ga}
    cb = {(c.row, c.col): c for c in gb}
    for pos in sorted(ca.keys() & cb.keys()):  # a missing position is a table_shape hold
        x, y = ca[pos], cb[pos]
        tag = f"cell:r{pos[0]}c{pos[1]}"
        diffs = _text_fields(x.text, y.text, "cell")
        for field, va, vb in diffs:
            out.append((f"{tag}:{field}", va, vb))
        hx, hy = ha.get(x.col, _NO_HEADER), hb.get(y.col, _NO_HEADER)
        if not diffs and hx != hy:
            out.append((f"{tag}:header", hx, hy))
    return out


def _by_anchor(blocks: Iterable[HwpBlock]) -> dict[str, list[HwpBlock]]:
    grouped: dict[str, list[HwpBlock]] = defaultdict(list)
    for block in blocks:
        grouped[block.bbox_or_element_anchor].append(block)
    return grouped


def compare_readers(a: HwpAdapterResult, b: HwpAdapterResult) -> tuple[HeldRegion, ...]:
    held: list[HeldRegion] = []

    def hold(anchor: str, field: str, sa: str | None, sb: str | None) -> None:
        held.append(HeldRegion(anchor=anchor, field=field, a_value_sha256=sa, b_value_sha256=sb))

    ga, gb = _by_anchor(a.blocks), _by_anchor(b.blocks)
    for anchor in sorted(ga.keys() | gb.keys()):
        la, lb = ga.get(anchor, []), gb.get(anchor, [])
        for i in range(max(len(la), len(lb))):
            x = la[i] if i < len(la) else None
            y = lb[i] if i < len(lb) else None
            if x is None or y is None:
                src = x or y
                assert src is not None
                value = _sha(_canon(src.text, src.kind) + repr(_shape(src.table_grid or ())))
                hold(anchor, "unaligned", value if x else None, value if y else None)
                continue
            if x.kind != y.kind:
                hold(anchor, "kind", _sha(x.kind), _sha(y.kind))
                continue
            for field, va, vb in _text_fields(x.text, y.text, x.kind):
                hold(anchor, field, va, vb)
            for field, va, vb in _table_diffs(x, y):
                hold(anchor, field, va, vb)

    ra = {(r.anchor, r.reason) for r in a.unresolved_regions}
    rb = {(r.anchor, r.reason) for r in b.unresolved_regions}
    for anchor, reason in sorted(ra - rb):
        hold(anchor, "unresolved_region", _sha(reason), None)
    for anchor, reason in sorted(rb - ra):
        hold(anchor, "unresolved_region", None, _sha(reason))
    return tuple(held)
