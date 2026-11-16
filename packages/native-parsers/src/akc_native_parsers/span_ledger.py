"""Source-span roundtrip and coverage ledger for the non-PDF native formats.

For every block and table cell that carries a ``native_object_id`` the locator
is resolved against the *original bytes* by a resolver that never calls the
parser, and the resolved text is compared with the CIR text. Nothing is filled
in: a locator that cannot be resolved is reported with its reason, never
passed. The ledger holds counts and ids only, no document text.

Ceilings (stated, not hidden):
* The HTML resolver uses the stdlib tokenizer, which does not repair markup the
  way the parser's lxml does. Sloppy HTML (implicit ``<p>`` closes, stray top
  level text) ends up ``unresolvable`` or ``resolved_mismatch``, never passed.
* DOCX cell text follows the visible-text rule of the parser (tracked
  deletions excluded); a cell whose runs sit inside ``w:ins`` is reported as a
  mismatch rather than reconciled.
* PDF text is re-extracted inside the block's bbox with pypdfium2, a different
  library from the parser's pypdf. The parser's bbox is an estimate (glyph width
  is modelled, not measured), so a text object that shares its bbox with a
  neighbour on the same line resolves to more text than the block holds and is
  reported as a mismatch, never reconciled. Rotated pages are inverted from the
  parser's own display transform; multi-column and rotated real PDFs are not
  proven here.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from html.parser import HTMLParser
from typing import Any

from akc_cir import CanonicalDocument, sha256_digest
from akc_quality.numeric import extract_numeric_tokens
from defusedxml import ElementTree as SafeElementTree
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from .models import LOCATOR_PAGE_SEMANTICS, ParserLimits, StructuredParseError, normalize_text

_HELD_MARKERS = ("held", "unresolved")
_MEMBER_LIMIT = ParserLimits().max_archive_member_bytes

_PDF_TEXT = re.compile(r"pdf/page/(?P<p>\d+)/text/[0-9a-f]{20}")
_PDF_GEOMETRY = re.compile(r"pdf/page/(?P<p>\d+)/(?:drawing|image-placement)/\d+")

# (text, optional (start_ms, end_ms)) for a resolved locator.
_Resolved = tuple[str, tuple[int, int] | None]
_Resolver = Callable[[str], _Resolved]


class _Unresolvable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SpanLedger:
    document_type: str
    locator_page_semantics: str
    source_hash_matches: bool
    units_expected: int
    units_observed: int
    units_missing: tuple[int, ...]
    blocks_total: int
    blocks_with_locator: int
    table_blocks_derived: int  # tables are judged through their cells
    resolved_exact: int  # leaf units: non-table blocks and table cells
    resolved_mismatch: tuple[str, ...]
    unresolvable: tuple[tuple[str, str], ...]
    numeric_tokens_total: int
    numeric_tokens_roundtripped: int
    omitted: tuple[str, ...]
    held: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_ledger(data: bytes, document: CanonicalDocument) -> SpanLedger:
    document_type = str(document.metadata.get("documentType", ""))
    factory = _FACTORIES.get(document_type)
    if factory is None or document_type not in LOCATOR_PAGE_SEMANTICS:
        raise StructuredParseError("LEDGER_TYPE_UNSUPPORTED")
    resolver: _Resolver | None
    open_failure = ""
    try:
        resolver = factory(data)
    except Exception as exc:  # unreadable original: every unit becomes unresolvable
        resolver = None
        open_failure = exc.reason if isinstance(exc, _Unresolvable) else "original_unreadable"

    exact = 0
    mismatch: list[str] = []
    unresolvable: list[tuple[str, str]] = []
    held: list[str] = []
    tokens_total = tokens_ok = with_locator = derived = 0
    observed_pages: set[int] = set()
    observed_cues: set[int] = set()

    assets = {str(a.get("id")): str(a.get("sha256")) for a in document.metadata.get("assets", ())}

    def _pdf_geometry(unit_id: str, locator: str, ref: Any, known: dict[str, str]) -> str:
        # Image/drawing blocks: never compare text. The box must sit inside the page and
        # an image placement must name an asset whose hash the document registered.
        nonlocal exact
        box = ref.bbox1000.root if ref.bbox1000 is not None else None
        inside = box is not None and 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000
        asset_ok = "/image-placement/" not in locator or known.get(
            str(ref.image_asset_id), ""
        ).startswith("sha256:")
        if inside and asset_ok:
            exact += 1
            return "exact"
        mismatch.append(unit_id)
        return "mismatch"

    def check(unit_id: str, locator: str, expected: str, ref: Any) -> str:
        nonlocal exact, tokens_total, tokens_ok
        want = tuple(extract_numeric_tokens(expected))
        tokens_total += len(want)
        if not locator:
            unresolvable.append((unit_id, "no_locator"))
            return "unresolvable"
        if resolver is None:
            unresolvable.append((unit_id, open_failure))
            return "unresolvable"
        try:
            if _PDF_GEOMETRY.fullmatch(locator):
                return _pdf_geometry(unit_id, locator, ref, assets)
            text, span = (
                resolver(locator, ref.bbox1000)  # type: ignore[call-arg]
                if getattr(resolver, "wants_bbox", False)
                else resolver(locator)
            )
        except _Unresolvable as exc:
            unresolvable.append((unit_id, exc.reason))
            return "unresolvable"
        except Exception as exc:
            unresolvable.append((unit_id, f"resolver_error:{type(exc).__name__}"))
            return "unresolvable"
        text = normalize_text(text)
        tokens_ok += sum((Counter(want) & Counter(extract_numeric_tokens(text))).values())
        timing_ok = span is None or (ref.time_start_ms, ref.time_end_ms) == span
        if text == expected and timing_ok:
            exact += 1
            return "exact"
        mismatch.append(unit_id)
        return "mismatch"

    for block in document.blocks:
        ref = block.source_refs[0] if block.source_refs else None
        locator = ref.native_object_id if ref is not None and ref.native_object_id else ""
        if locator:
            with_locator += 1
        if ref is not None:
            observed_pages.add(ref.page_index0)
            observed_cues.update(_cue_indexes(locator))
        if any(m in flag for flag in block.quality_flags for m in _HELD_MARKERS):
            held.append(block.id)
        if block.table is not None:
            derived += 1
            for cell in block.table.cells:
                cell_ref = cell.source_refs[0] if cell.source_refs else None
                cell_locator = (cell_ref.native_object_id or "") if cell_ref is not None else ""
                if any(m in flag for flag in cell.quality_flags for m in _HELD_MARKERS):
                    held.append(cell.id)
                check(cell.id, cell_locator, cell.raw_text, cell_ref)
        else:
            check(block.id, locator, block.raw_text or "", ref)

    expected_units, expected_set = _expected_units(resolver)
    if document_type in {"srt", "vtt"}:
        observed = observed_cues
    elif document_type in {"docx", "html"}:
        observed = {0} if document.blocks else set()
    else:
        observed = observed_pages
    covered = expected_set & observed
    return SpanLedger(
        document_type=document_type,
        locator_page_semantics=str(document.metadata.get("locatorPageSemantics", "")),
        source_hash_matches=sha256_digest(data) == document.source_sha256,
        units_expected=expected_units,
        units_observed=len(covered),
        units_missing=tuple(sorted(expected_set - observed)),
        blocks_total=len(document.blocks),
        blocks_with_locator=with_locator,
        table_blocks_derived=derived,
        resolved_exact=exact,
        resolved_mismatch=tuple(mismatch),
        unresolvable=tuple(unresolvable),
        numeric_tokens_total=tokens_total,
        numeric_tokens_roundtripped=tokens_ok,
        omitted=tuple(str(w) for w in document.metadata.get("warnings", ())),
        held=tuple(held),
    )


def _expected_units(resolver: _Resolver | None) -> tuple[int, set[int]]:
    # The unit set was stashed on the resolver by its factory (None = unreadable).
    units: set[int] | None = getattr(resolver, "units", None)
    if units is None:
        return 0, set()
    return len(units), set(units)


def _cue_indexes(locator: str) -> set[int]:
    match = _CUE.fullmatch(locator)
    if match is None:
        return set()
    first = int(match["first"])
    return set(range(first, int(match["last"] or match["first"]) + 1))


_CUE = re.compile(r"(?:srt|vtt)/cue/(?P<first>\d{6})(?:-(?P<last>\d{6}))?")


# ----------------------------------------------------------------- helpers


def _ln(element: Any) -> str:
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _read(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise _Unresolvable("original_part_missing") from exc
    if info.file_size > _MEMBER_LIMIT:
        raise _Unresolvable("original_part_too_large")
    return archive.read(info)


def _xml(archive: zipfile.ZipFile, name: str) -> Any:
    return SafeElementTree.fromstring(_read(archive, name))


def _with_units(resolver: Callable[[str], _Resolved], units: set[int]) -> _Resolver:
    resolver.units = units  # type: ignore[attr-defined]
    return resolver


def _attr(element: Any, local: str) -> str | None:
    for key, value in element.attrib.items():
        if key.rsplit("}", 1)[-1] == local:
            return str(value)
    return None


# -------------------------------------------------------------------- DOCX

_DOCX = re.compile(r"docx/body/(?:p/(?P<p>\d{6})|table/(?P<t>\d{6})/r/(?P<r>\d{6})/c/(?P<c>\d{6}))")


def _docx_text(element: Any) -> str:
    parts: list[str] = []

    def visit(node: Any, deleted: bool) -> None:
        name = _ln(node)
        if name == "txbxContent":
            return
        deleted = deleted or name == "del"
        if not deleted:
            if name in {"t", "delText"} and node.text:
                parts.append(str(node.text))
            elif name == "tab":
                parts.append("\t")
            elif name in {"br", "cr"}:
                parts.append("\n")
        for child in node:
            visit(child, deleted)

    visit(element, False)
    return "".join(parts)


def _docx_resolver(data: bytes) -> _Resolver:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = _xml(archive, "word/document.xml")
    body = next((child for child in root if _ln(child) == "body"), None)
    if body is None:
        raise _Unresolvable("docx_body_missing")
    kids = list(body)

    def resolve(locator: str) -> _Resolved:
        match = _DOCX.fullmatch(locator)
        if match is None:
            raise _Unresolvable("unknown_locator_grammar")
        index = int(match["p"] or match["t"])
        if index >= len(kids):
            raise _Unresolvable("locator_out_of_range")
        element = kids[index]
        if match["p"] is not None:
            if _ln(element) != "p":
                raise _Unresolvable("locator_kind_mismatch")
            return _docx_text(element), None
        if _ln(element) != "tbl":
            raise _Unresolvable("locator_kind_mismatch")
        rows = [row for row in element if _ln(row) == "tr"]
        row_index, column = int(match["r"]), int(match["c"])
        if row_index >= len(rows):
            raise _Unresolvable("locator_out_of_range")
        position = 0
        for cell in (c for c in rows[row_index] if _ln(c) == "tc"):
            span = 1
            for prop in cell:
                if _ln(prop) == "tcPr":
                    for item in prop:
                        if _ln(item) == "gridSpan" and (value := _attr(item, "val")):
                            span = max(1, int(value))
            if position == column:
                return "\n".join(_docx_text(p) for p in cell if _ln(p) == "p"), None
            position += span
        raise _Unresolvable("locator_out_of_range")

    return _with_units(resolve, {0})


# -------------------------------------------------------------------- PPTX

_PPTX = re.compile(
    r"pptx/slide/(?P<s>\d{4})"
    r"(?:/(?P<notes>notes)"
    r"|/shape/(?P<z>\d{4}(?:\.\d{4})*)(?:/p/(?P<p>\d{4})|/table/r/(?P<r>\d{4})/c/(?P<c>\d{4}))?)?"
)
_SHAPES = frozenset({"sp", "grpSp", "graphicFrame", "cxnSp", "pic", "contentPart"})


def _a_paragraph(paragraph: Any) -> str:
    out: list[str] = []
    for child in paragraph:
        name = _ln(child)
        if name in {"r", "fld"}:
            out.extend(str(t.text or "") for t in child if _ln(t) == "t")
        elif name == "br":
            out.append("\n")
    return "".join(out)


def _a_paragraphs(shape: Any) -> list[Any]:
    body = next((c for c in shape if _ln(c) in {"txBody"}), None)
    return [p for p in body if _ln(p) == "p"] if body is not None else []


def _pptx_resolver(data: bytes) -> _Resolver:
    archive = zipfile.ZipFile(io.BytesIO(data))
    presentation = _xml(archive, "ppt/presentation.xml")
    rels = {
        _attr(r, "Id"): _attr(r, "Target") for r in _xml(archive, "ppt/_rels/presentation.xml.rels")
    }
    slide_parts: list[str] = []
    for node in presentation.iter():
        if _ln(node) == "sldId":
            rid = next((v for k, v in node.attrib.items() if k.endswith("relationships}id")), None)
            target = rels.get(rid)
            if target is None:
                raise _Unresolvable("pptx_slide_relationship_missing")
            slide_parts.append("ppt/" + target.removeprefix("/ppt/").removeprefix("../ppt/"))
    cache: dict[int, Any] = {}

    def slide_root(index: int) -> Any:
        if index >= len(slide_parts):
            raise _Unresolvable("locator_out_of_range")
        if index not in cache:
            cache[index] = _xml(archive, slide_parts[index])
        return cache[index]

    def shape_at(root: Any, z_path: str) -> Any:
        tree = next(n for n in root.iter() if _ln(n) == "spTree")
        node = tree
        for part in z_path.split("."):
            shapes = [c for c in node if _ln(c) in _SHAPES]
            if int(part) >= len(shapes):
                raise _Unresolvable("locator_out_of_range")
            node = shapes[int(part)]
        return node

    def placeholder(root: Any, kinds: set[str] | None) -> Any | None:
        for shape in root.iter():
            if _ln(shape) != "sp":
                continue
            for ph in shape.iter():
                if _ln(ph) == "ph":
                    kind = _attr(ph, "type") or "obj"
                    idx = _attr(ph, "idx") or "0"
                    if (kinds is None and idx == "0") or (kinds is not None and kind in kinds):
                        return shape
        return None

    def resolve(locator: str) -> _Resolved:
        match = _PPTX.fullmatch(locator)
        if match is None:
            raise _Unresolvable("unknown_locator_grammar")
        root = slide_root(int(match["s"]))
        if match["notes"]:
            rel_name = slide_parts[int(match["s"])].rsplit("/", 1)
            rel_path = f"{rel_name[0]}/_rels/{rel_name[1]}.rels"
            target = next(
                (
                    _attr(r, "Target")
                    for r in _xml(archive, rel_path)
                    if (_attr(r, "Type") or "").endswith("/notesSlide")
                ),
                None,
            )
            if target is None:
                raise _Unresolvable("pptx_notes_part_missing")
            notes = _xml(archive, "ppt/" + target.removeprefix("../"))
            shape = placeholder(notes, {"body"})
            if shape is None:
                raise _Unresolvable("pptx_notes_body_missing")
            return "\n".join(_a_paragraph(p) for p in _a_paragraphs(shape)), None
        if match["z"] is None:
            title = placeholder(root, None)
            if title is None:
                raise _Unresolvable("inferred_title_not_in_source")
            return "\n".join(_a_paragraph(p) for p in _a_paragraphs(title)), None
        shape = shape_at(root, match["z"])
        if match["p"] is not None:
            paragraphs = _a_paragraphs(shape)
            if int(match["p"]) >= len(paragraphs):
                raise _Unresolvable("locator_out_of_range")
            return _a_paragraph(paragraphs[int(match["p"])]), None
        if match["r"] is not None:
            rows = [n for n in shape.iter() if _ln(n) == "tr"]
            if int(match["r"]) >= len(rows):
                raise _Unresolvable("locator_out_of_range")
            cells = [c for c in rows[int(match["r"])] if _ln(c) == "tc"]
            if int(match["c"]) >= len(cells):
                raise _Unresolvable("locator_out_of_range")
            return "\n".join(_a_paragraph(p) for p in _a_paragraphs(cells[int(match["c"])])), None
        raise _Unresolvable("non_text_object")

    return _with_units(resolve, set(range(len(slide_parts))))


# -------------------------------------------------------------------- XLSX

_XLSX = re.compile(r"xlsx/sheet/(?P<s>\d{4})(?:/cell/(?P<cell>[A-Z]{1,3}[0-9]{1,7}))?")


def _xlsx_text(value: Any) -> str:
    if value is None or isinstance(value, MergedCell):
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def _xlsx_resolver(data: bytes) -> _Resolver:
    book = load_workbook(io.BytesIO(data), read_only=False, data_only=False, keep_links=False)
    sheets = list(book.worksheets)

    def resolve(locator: str) -> _Resolved:
        match = _XLSX.fullmatch(locator)
        if match is None:
            raise _Unresolvable("unknown_locator_grammar")
        if int(match["s"]) >= len(sheets):
            raise _Unresolvable("locator_out_of_range")
        sheet: Any = sheets[int(match["s"])]
        if match["cell"] is None:
            return sheet.title, None
        return _xlsx_text(sheet[match["cell"]].value), None

    return _with_units(resolve, set(range(len(sheets))))


# -------------------------------------------------------------------- HTML

_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_DROPPED = frozenset(
    {
        "script", "style", "noscript", "iframe", "object", "embed", "applet", "canvas", "svg",
        "form", "input", "button", "template", "nav", "aside",
    }
)  # fmt: skip
_COMMENT = object()


class _Node:
    __slots__ = ("kids", "name", "role")

    def __init__(self, name: str, role: str = "") -> None:
        self.name = name
        self.role = role
        self.kids: list[Any] = []  # str | _Node | _COMMENT


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("[document]")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, dict(attrs).get("role") or "")
        self.stack[-1].kids.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].kids.append(_Node(tag, dict(attrs).get("role") or ""))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].name == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        kids = self.stack[-1].kids
        if kids and isinstance(kids[-1], str):
            kids[-1] += data
        else:
            kids.append(data)

    def handle_comment(self, data: str) -> None:
        self.stack[-1].kids.append(_COMMENT)


def _strings(node: _Node) -> list[str]:
    out: list[str] = []
    for kid in node.kids:
        if isinstance(kid, str):
            out.append(kid)
        elif isinstance(kid, _Node) and kid.name not in _DROPPED and kid.role != "navigation":
            out.extend(_strings(kid))
    return out


def _get_text(node: _Node, separator: str, *, strip: bool) -> str:
    parts = _strings(node)
    if strip:
        parts = [p.strip() for p in parts if p.strip()]
    return separator.join(parts)


_SEGMENT = re.compile(r"(?P<name>[a-z0-9]+)\[(?P<i>\d+)\]")
_TEXT_SEGMENT = re.compile(r"text\(\)\[(?P<i>\d+)\]")


def _html_resolver(data: bytes) -> _Resolver:
    tree = _Tree()
    tree.feed(data.decode("utf-8-sig"))
    tree.close()

    def resolve(locator: str) -> _Resolved:
        if not locator.startswith("html/"):
            raise _Unresolvable("unknown_locator_grammar")
        parts = locator[5:].split("/")
        text_index = None
        if (tail := _TEXT_SEGMENT.fullmatch(parts[-1])) is not None:
            text_index = int(tail["i"])
            parts = parts[:-1]
        node = tree.root
        for part in parts:
            match = _SEGMENT.fullmatch(part)
            if match is None:
                raise _Unresolvable("unknown_locator_grammar")
            name, index = match["name"], int(match["i"])
            same = [
                k
                for k in node.kids
                if isinstance(k, _Node)
                and k.name == name
                and k.name not in _DROPPED  # the parser decomposes these before indexing
                and k.role != "navigation"
            ]
            if 1 <= index <= len(same):
                node = same[index - 1]
            elif not (name in {"html", "head", "body"} and index == 1):
                raise _Unresolvable("path_not_found")  # lxml implies html/head/body; we do too
        if text_index is not None:
            texts = [k for k in node.kids if isinstance(k, str)]
            if not 1 <= text_index <= len(texts):
                raise _Unresolvable("path_not_found")
            return texts[text_index - 1], None
        name = node.name
        if name in {"figure", "img"}:
            raise _Unresolvable("non_text_object")
        if name in {"ul", "ol"}:
            items = [
                normalize_text(_get_text(li, " ", strip=True))
                for li in node.kids
                if isinstance(li, _Node) and li.name == "li"
            ]
            return "\n".join(item for item in items if item), None
        if name == "blockquote":
            return _get_text(node, "\n", strip=True), None
        if name == "pre":
            return _get_text(node, "\n", strip=False), None
        return _get_text(node, " ", strip=True), None

    return _with_units(resolve, {0})


# ---------------------------------------------------------------- subtitles

_TIMING = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})(?:\s+.*)?$"
)


def _ms(stamp: str) -> int:
    clock, millis = stamp.replace(",", ".").split(".")
    fields = [int(p) for p in clock.split(":")]
    hours, minutes, seconds = [0, *fields] if len(fields) == 2 else fields
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(millis)


# Cue markup by each format's own grammar, never the parser's: SRT knows i/b/u/font,
# WebVTT knows c/i/b/u/ruby/rt, lang (annotated), v and timestamp tags. Anything
# else in angle brackets ("<10%>", "<USD -1,234.50>") is cue text and stays in the key.
# Cue text is hostile, so every pattern runs in linear time: a tag body never crosses
# another "<" (a scan from each "<" stops at the next one instead of re-reading the
# rest of the cue), and no two adjacent quantifiers can match the same character.
# A "<" inside a would-be tag leaves it in the key, which can only add a mismatch.
_CUE_MARKUP = {
    "srt": re.compile(r"</?(?:i|b|u)>|<font(?:\s[^<>]*)?>|</font>", re.IGNORECASE),
    "vtt": re.compile(
        r"</?(?:c|i|b|u|ruby|rt)(?:\.[^\s<>]*)?>|<lang(?:\.[^\s<>]*)?\s[^<>]*>|</lang>"
        r"|<v(?:\.[^\s<>]*)?>|</v>|<\d+(?::\d{2}){1,2}\.\d{3}>"
    ),
}
# A leading WebVTT voice span names the speaker; an annotated <v name> later in the
# cue is not markup to strip, so that name stays in the key. The class suffix is one
# optional group (it already spans ".a.b") and the name starts at a non-space, so the
# whitespace run between them has exactly one way to match.
_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^\s>][^>]*)>(.*)", re.DOTALL)
_SPEAKER_LABEL = re.compile(r"([^\n:]{1,80}):\s+(.+)", re.DOTALL)


def _merge_key(kind: str, raw: str) -> tuple[str | None, str]:
    # speaker + markup-free text: what two cues must share to be one CIR block
    voice = _VOICE.fullmatch(raw) if kind == "vtt" else None
    if voice is not None:
        return normalize_text(voice[1]), normalize_text(_CUE_MARKUP[kind].sub("", voice[2]))
    text = _CUE_MARKUP[kind].sub("", raw)
    label = _SPEAKER_LABEL.fullmatch(text)
    if label is not None:
        return normalize_text(label[1]), normalize_text(label[2])
    return None, normalize_text(text)


def _subtitle_factory(kind: str) -> Callable[[bytes], _Resolver]:
    def factory(data: bytes) -> _Resolver:
        source = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        cues: dict[int, tuple[str, int, int]] = {}
        if kind == "srt":
            blocks = list(enumerate(re.split(r"\n{2,}", source.strip())))
        else:
            if not re.match(r"WEBVTT(?:[ \t\n]|$)", source):
                raise _Unresolvable("vtt_signature_missing")
            payload = source.split("\n", 1)[1] if "\n" in source else ""
            blocks = list(enumerate(re.split(r"\n{2,}", payload.strip())))
        counter = 0
        for position, block in blocks:
            lines = block.splitlines()
            if kind == "vtt" and lines and lines[0].strip().startswith(("NOTE", "STYLE", "REGION")):
                continue  # mirrors the parser's skipped blocks
            at = next((i for i, ln in enumerate(lines[:2]) if _TIMING.match(ln.strip())), None)
            if at is None:
                continue
            timing = _TIMING.match(lines[at].strip())
            assert timing is not None
            text = normalize_text("\n".join(lines[at + 1 :]))
            if not text:
                continue
            key = position if kind == "srt" else counter
            counter += 1
            cues[key] = (text, _ms(timing["start"]), _ms(timing["end"]))

        def resolve(locator: str) -> _Resolved:
            match = re.fullmatch(rf"{kind}/cue/(?P<a>\d{{6}})(?:-(?P<b>\d{{6}}))?", locator)
            if match is None:
                if re.fullmatch(rf"{kind}/(?:document|segment/\d{{6}})", locator):
                    raise _Unresolvable("parser_generated_text")
                raise _Unresolvable("unknown_locator_grammar")
            first = int(match["a"])
            last = int(match["b"] or match["a"])
            if last < first:
                raise _Unresolvable("locator_range_reversed")
            if first not in cues:
                raise _Unresolvable("locator_out_of_range")
            inside = [cues[i] for i in range(first, last + 1) if i in cues]
            end = max(cue[2] for cue in inside)
            key = _merge_key(kind, cues[first][0])
            if any(_merge_key(kind, c[0]) != key for c in inside):
                # a merged range is only exact if every cue in it says the same thing
                return "\x00range_text_differs", (cues[first][1], end)
            return cues[first][0], (cues[first][1], end)

        return _with_units(resolve, set(cues))

    return factory


# --------------------------------------------------------------------- PDF


def _pdf_resolver(data: bytes) -> _Resolver:
    import pypdfium2  # type: ignore[import-untyped]  # lazy: only PDF ledgers need it

    pdf = pypdfium2.PdfDocument(data)
    pages = len(pdf)
    cache: dict[int, Any] = {}

    def resolve(locator: str, bbox: Any) -> _Resolved:
        match = _PDF_TEXT.fullmatch(locator)
        if match is None:
            raise _Unresolvable("unknown_locator_grammar")
        index = int(match["p"])
        if index >= pages:
            raise _Unresolvable("locator_out_of_range")
        if bbox is None:
            raise _Unresolvable("no_bbox")
        if index not in cache:
            page = pdf[index]
            cache[index] = (page, page.get_textpage(), page.get_cropbox(), page.get_rotation())
        page, textpage, (left, bottom, right, top), rotation = cache[index]
        width, height = right - left, top - bottom
        x1, y1, x2, y2 = (v / 1000 for v in bbox.root)
        dw, dh = (height, width) if rotation % 180 else (width, height)
        # invert the parser's display transform (_display_bbox1000): v runs top-down
        corners = [(x * dw, dh - y * dh) for x in (x1, x2) for y in (y1, y2)]
        if rotation == 90:
            points = [(width - y, x) for x, y in corners]
        elif rotation == 180:
            points = [(width - x, height - y) for x, y in corners]
        elif rotation == 270:
            points = [(y, height - x) for x, y in corners]
        else:
            points = corners
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return textpage.get_text_bounded(
            left + min(xs), bottom + min(ys), left + max(xs), bottom + max(ys)
        ), None

    resolve.wants_bbox = True  # type: ignore[attr-defined]
    return _with_units(resolve, set(range(pages)))  # type: ignore[arg-type]


_FACTORIES: dict[str, Callable[[bytes], _Resolver]] = {
    "docx": _docx_resolver,
    "pdf": _pdf_resolver,
    "pptx": _pptx_resolver,
    "xlsx": _xlsx_resolver,
    "html": _html_resolver,
    "srt": _subtitle_factory("srt"),
    "vtt": _subtitle_factory("vtt"),
}
