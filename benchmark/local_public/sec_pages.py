"""Filer-page segmentation and DOM page acceptance (LPC design 2.3 steps 1, 2, 3, 5, 6).

Reads no PDF and no text layer: acceptance is stated on the filed HTML's DOM, the way the scorer's
`value_after_anchor` searches (NFKC, case-insensitive substring of the segment's DOM text, first
occurrence). Page-count acceptance (one printed page) and seed-hash choice belong to the callers.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from lxml import etree

from benchmark.local_public.sec_align import IX, Candidate, Excluded, _cells, _local, _text

MIN_FIELDS = 3
_BEFORE = re.compile(r"(?<![\w-])(page-break-before:always|break-before:page)")
_AFTER = re.compile(r"(?<![\w-])(page-break-after:always|break-after:page)")
_DROP = ("script", "link", "base", "style")  # style moves to <head>; ix:header is dropped by name


class SegmentRefused(ValueError):
    """The filing cannot be segmented; `reason` is the receipt reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Segment:
    index: int
    nested: bool  # a page-break marker sits inside a <table> of this segment
    sha256: str  # of the html bytes segments() read
    root: Any
    seg_of: dict[Any, int]
    tail_seg: dict[Any, int]


def _marker(el: Any) -> tuple[bool, bool]:
    s = "".join((el.get("style") or "").split()).lower()
    return bool(_BEFORE.search(s)), bool(_AFTER.search(s))


def has_script(html_bytes: bytes) -> bool:
    return re.search(rb"<script", html_bytes, re.I) is not None


def segments(html_bytes: bytes) -> list[Segment]:
    """Split the filed HTML at page-break markers; a marker inside a table does not split."""
    root = etree.fromstring(html_bytes, etree.XMLParser(huge_tree=True, recover=True))
    if root is None:
        raise ValueError("unparseable inline XBRL document")
    seg_of: dict[Any, int] = {}
    tail_seg: dict[Any, int] = {}
    nested: set[int] = set()
    cur = tables = markers = 0
    for ev, el in etree.iterwalk(root, events=("start", "end")):
        if not isinstance(el.tag, str):
            continue
        before, after = _marker(el)
        if ev == "start":
            if before:
                markers += 1
                if tables:
                    nested.add(cur)
                else:
                    cur += 1
            seg_of[el] = cur
            tables += _local(el) == "table"
        else:
            tables -= _local(el) == "table"
            if after:
                markers += 1
                if tables:
                    nested.add(cur)
                else:
                    cur += 1
            tail_seg[el] = cur
    if not markers:
        raise SegmentRefused("no_filer_page_breaks")
    sha = hashlib.sha256(html_bytes).hexdigest()
    return [
        Segment(i, i in nested, sha, root, seg_of, tail_seg)
        for i in range(max(seg_of.values()) + 1)
    ]


def _clone(seg: Segment) -> tuple[Any, dict[Any, Any], list[Any]]:
    """Copy of the document pruned to the segment, without hidden/script content; plus styles."""
    k, root = seg.index, seg.root
    styles = [
        copy.deepcopy(s) for s in root.iter() if isinstance(s.tag, str) and _local(s) == "style"
    ]
    for s in styles:
        s.tail = None
    keep: set[Any] = set()
    for el, i in seg.seg_of.items():
        while i == k and el is not None and el not in keep:
            keep.add(el)
            el = el.getparent()
    clone = copy.deepcopy(root)
    pairs = {o: c for o, c in zip(root.iter(), clone.iter(), strict=True) if isinstance(o.tag, str)}

    def drop(c: Any, keep_tail: bool) -> None:
        par = c.getparent()
        if par is None:
            return
        if keep_tail and c.tail:
            prev = c.getprevious()
            if prev is not None:
                prev.tail = (prev.tail or "") + c.tail
            else:
                par.text = (par.text or "") + c.tail
        par.remove(c)

    for o, c in pairs.items():  # text/tail belong to the segment they were read in
        if o in keep:
            if seg.seg_of[o] != k:
                c.text = None
            if seg.tail_seg[o] != k:
                c.tail = None
    for o, c in list(pairs.items()):
        if o is not root and o not in keep and o.getparent() in keep:
            drop(c, seg.tail_seg[o] == k)
    for o, c in pairs.items():
        hidden = "display:none" in "".join((c.get("style") or "").split()).lower()
        if (
            o in keep
            and o is not root
            and (_local(c) in _DROP or c.tag == f"{{{IX}}}header" or hidden)
        ):
            drop(c, True)
    return clone, pairs, styles


def _body(clone: Any) -> Any:
    return next((e for e in clone.iter() if isinstance(e.tag, str) and _local(e) == "body"), clone)


def excerpt_html(html_bytes: bytes, seg: Segment) -> bytes:
    """Standalone HTML: charset meta, the filing's `<style>` elements, the segment's elements."""
    if hashlib.sha256(html_bytes).hexdigest() != seg.sha256:
        raise ValueError("segment was cut from different bytes")
    clone, _, styles = _clone(seg)
    head = "".join(etree.tostring(s, method="html", encoding="unicode") for s in styles)
    body = etree.tostring(_body(clone), method="html", encoding="unicode")
    return f'<!doctype html><html><head><meta charset="utf-8">{head}</head>{body}</html>'.encode()


def _nodes(root: Any, marks: set[Any] | None = None) -> tuple[list[str], dict[Any, int]]:
    """DOM text nodes in document order (a table cell is one node); node index at `marks`."""
    nodes: list[str] = []
    at: dict[Any, int] = {}
    skip = None
    for ev, el in etree.iterwalk(root, events=("start", "end")):
        if not isinstance(el.tag, str) or (skip is not None and el is not skip):
            continue
        if ev == "start":
            if marks is not None and el in marks:
                at[el] = len(nodes)
            if _local(el) in ("td", "th"):
                skip = el
                nodes.append(_text(el))
            elif _local(el) in ("style", "script"):
                skip = el
            elif el.text:
                nodes.append(" ".join(el.text.split()))
        else:
            if el is skip:
                skip = None
            if el.tail:
                nodes.append(" ".join(el.tail.split()))
    return [n for n in nodes if n] if marks is None else nodes, at


def dom_text(excerpt: bytes) -> str:
    """Diagnostic text of an excerpt (`text_source: "html_dom_text"`); never published."""
    root = etree.fromstring(excerpt, etree.HTMLParser(huge_tree=True))
    return " ".join(_nodes(root)[0])


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def accept(seg: Segment, candidates: list[Candidate]) -> tuple[list[Candidate], list[Excluded]]:
    """Accepted candidates of this segment and one Excluded per rejected one.

    A candidate is accepted when no earlier occurrence of its anchor (NFKC, case-insensitive
    substring) exists in the segment's DOM text. Fewer than 3 accepted: all `too_few_fields`.
    """
    mine = []
    tree = seg.root.getroottree()
    by_path = {tree.getpath(e): e for e in seg.root.iter(f"{{{IX}}}nonFraction")}
    for c in candidates:
        el = by_path[c.dom_path]
        if seg.seg_of.get(el) == seg.index:
            tr = next((a for a in el.iterancestors() if _local(a) == "tr"), None)
            if tr is None or not _cells(tr):
                raise ValueError(f"candidate {c.field_id} is not in a table row")
            mine.append((c, _cells(tr)[0]))

    def no(c: Candidate, reason: str) -> Excluded:
        return Excluded(reason, c.adsh, c.tag, c.fsds["ddate"], c.fsds["qtrs"])

    if seg.nested:
        return [], [no(c, "nested_page_break") for c, _ in mine]
    clone, pairs, _ = _clone(seg)
    nodes, at = _nodes(clone, {pairs[cell] for _, cell in mine if cell in pairs})
    off, parts, run = [], [], 0
    for n in nodes:
        off.append(run)
        if _norm(n):
            parts.append(_norm(n))
            run += len(parts[-1]) + 1
    text = " ".join(parts)
    ok: list[Candidate] = []
    bad: list[Excluded] = []
    for c, cell in mine:
        i = at.get(pairs.get(cell))
        if i is None:
            bad.append(no(c, "hidden_only"))
        elif text.find(_norm(c.anchor)) != off[i]:
            bad.append(no(c, "anchor_shadowed"))
        else:
            ok.append(c)
    if len(ok) < MIN_FIELDS:
        return [], bad + [no(c, "too_few_fields") for c in ok]
    return ok, bad
