"""HWPX (OWPML) paragraph and basic-table extraction with explicit partial fidelity.

Profile ``text-basic-tables-v1`` reads paragraph and run text -- direct text,
``hp:t`` text, tabs, line breaks and tails -- and unit-span ``hp:tbl`` tables, in
spine order then document order. Everything else -- pictures, equations, text
boxes, notes, headers and footers, table captions, merged or nested tables --
is counted and omitted, never flattened into body text, and the descendant text
of an omitted control is never read. Tracked-change markers are applied in
source order, exactly when the walk reaches them. HWPX sections are not physical pages, so the whole
document is one logical CIR page.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

from akc_cir import BlockType
from akc_security.hwpx import (
    HWPX_HEAD_NAMESPACES,
    HWPX_PARAGRAPH_NAMESPACES,
    HWPX_SECTION_NAMESPACES,
    HwpxPackage,
    HwpxPackageError,
    parse_bounded_xml,
    qualified_name,
)

from .models import CirBuilder, SourceLocation, StructuredParseError, TableCellSpec, normalize_text

EXTRACTION_PROFILE = "text-basic-tables-v1"
PARTIAL_FIDELITY_WARNINGS = (
    "hwpx_partial_fidelity",
    "hwpx_physical_pagination_unavailable",
    "hwpx_styling_not_preserved",
    "hwpx_layout_not_preserved",
)

# Unsupported elements are named in metadata only when they come from an OWPML
# namespace family; anything else is counted as "other".
_FEATURE_NAMESPACE_PREFIXES = ("http://www.hancom.co.kr/hwpml/", "http://www.owpml.org/owpml/")

_INLINE_TEXT = {
    "tab": "\t",
    "lineBreak": "\n",
    "nbSpace": "\N{NO-BREAK SPACE}",
    "fwSpace": "\N{IDEOGRAPHIC SPACE}",
}
_INERT_MARKS = frozenset({"markpenBegin", "markpenEnd", "titleMark"})
_REVISION_MARKS = frozenset({"insertBegin", "insertEnd", "deleteBegin", "deleteEnd"})
# Sizing and layout children: structure already checked or covered by the layout
# warning, not omitted content. Any other non-row table child (a caption, say)
# and any other non-subList cell child is counted as omitted, never read.
_TABLE_LAYOUT = frozenset({"sz", "pos", "outMargin", "inMargin", "cellzoneList"})
_CELL_LAYOUT = frozenset({"cellAddr", "cellSpan", "cellSz", "cellMargin"})
_FEATURE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{0,47}")
_MAX_FEATURE_KEYS = 64
# A declared table dimension longer than this is certainly over every limit.
_MAX_DIMENSION_DIGITS = 18
# Any count with more digits than this exceeds every table fence.
_HUGE_DIMENSION: int = 10**_MAX_DIMENSION_DIGITS
_INVALID_DIMENSION = -1

# Sentinels interleaved with text and table elements in a paragraph's parts.
_OMITTED = object()
_REVISION = object()


def parse_hwpx(package: HwpxPackage, builder: CirBuilder) -> str:
    walker = _Walker(builder)
    sections: list[dict[str, Any]] = []
    head_parts = 0
    other_spine_parts = 0
    for item in package.spine:
        try:
            root = parse_bounded_xml(
                item.payload,
                max_bytes=builder.limits.max_hwpx_xml_bytes,
                max_nodes=builder.limits.max_hwpx_xml_nodes,
                max_depth=builder.limits.max_hwpx_xml_depth,
            )
        except HwpxPackageError as exc:
            raise StructuredParseError(exc.code.upper()) from exc
        namespace, local = qualified_name(root)
        if namespace in HWPX_HEAD_NAMESPACES and local == "head":
            head_parts += 1
            continue
        if namespace not in HWPX_SECTION_NAMESPACES or local != "sec":
            other_spine_parts += 1
            continue
        section_index = len(sections)
        builder.reserve_metadata_text(item.idref + item.part_name)
        sections.append({"index": section_index, "idref": item.idref, "part": item.part_name})
        walker.section(root, section_index)

    # Unsupported-only content, empty paragraphs and all-empty tables alike
    # produce no readable text: that is an empty document, not a success.
    if not any(block.raw_text for block in builder.blocks):
        raise StructuredParseError("HWPX_EMPTY_DOCUMENT")
    for warning in PARTIAL_FIDELITY_WARNINGS:
        builder.add_warning(warning)
    if walker.unsupported or walker.unsupported_tables or other_spine_parts:
        builder.add_warning("hwpx_unsupported_content_omitted")
    if walker.revision_marks:
        builder.add_warning("hwpx_tracked_changes_present")
    builder.metadata["hwpx"] = {
        "extractionProfile": EXTRACTION_PROFILE,
        "supportStatus": "partial",
        "logicalPageModel": "single-logical-page",
        "sections": sections,
        "spineItemCount": len(package.spine),
        "headPartCount": head_parts,
        "unsupportedSpinePartCount": other_spine_parts,
        "paragraphCount": walker.paragraphs,
        "tableCount": walker.tables,
        "unsupportedTables": dict(sorted(walker.unsupported_tables.items())),
        "unsupportedFeatures": dict(sorted(walker.unsupported.items())),
        "trackedChangeMarkerCount": walker.revision_marks,
        "deletedRevisionCharsOmitted": walker.deleted_chars,
        "binaryPartCount": package.binary_part_count,
        "emptyScriptPlaceholderCount": package.empty_script_placeholder_count,
    }
    return _filename_title(builder.source_filename)


def _paragraph_local(element: Any) -> str:
    """Local name in an OWPML paragraph namespace, or "" for any other element."""

    namespace, local = qualified_name(element)
    return local if namespace in HWPX_PARAGRAPH_NAMESPACES else ""


def _is_indentation(value: str) -> bool:
    # Pretty-printing between elements: whitespace that spans a line break.
    return value.isspace() and ("\n" in value or "\r" in value)


def _declared_dimension(value: Any) -> int | None:
    """Parse ``rowCnt``/``colCnt``: None when absent, -1 when not a plain count."""

    if value is None:
        return None
    text = str(value).strip()
    if not text or not text.isascii() or not text.isdigit():
        return _INVALID_DIMENSION
    if len(text) > _MAX_DIMENSION_DIGITS:
        return _HUGE_DIMENSION
    return int(text)


class _Walker:
    def __init__(self, builder: CirBuilder) -> None:
        self.builder = builder
        self.limits = builder.limits
        self.paragraphs = 0
        self.tables = 0
        self.table_elements = 0
        self.buffered_chars = 0
        self.unsupported: Counter[str] = Counter()
        self.unsupported_tables: Counter[str] = Counter()
        self.revision_marks = 0
        self.open_deletions = 0
        self.deleted_chars = 0

    def section(self, root: Any, section_index: int) -> None:
        paragraph_index = 0
        for child in root:
            if _paragraph_local(child) != "p":
                self._count_unsupported(child)
                continue
            anchor = f"hwpx/section/{section_index:04d}/p/{paragraph_index:06d}"
            self._emit_paragraph(child, anchor)
            paragraph_index += 1
        # A deletion left open never leaks across sections.
        self.open_deletions = 0

    def _emit_paragraph(self, paragraph: Any, anchor: str) -> None:
        buffer: list[str] = []
        flags: set[str] = set()
        text_index = 0
        table_index = 0

        def flush() -> None:
            nonlocal text_index
            text = normalize_text("".join(buffer))
            if text:
                self.builder.add_block(
                    block_type=BlockType.PARAGRAPH,
                    location=SourceLocation(
                        page_index0=0,
                        native_object_id=f"{anchor}/text/{text_index:03d}",
                    ),
                    raw_text=text,
                    quality_flags=tuple(sorted(flags)),
                )
            text_index += 1
            buffer.clear()
            flags.clear()

        for part in self._paragraph_parts(paragraph):
            if isinstance(part, str):
                buffer.append(part)
            elif part is _OMITTED:
                flags.add("hwpx_unsupported_content_omitted")
            elif part is _REVISION:
                flags.add("hwpx_tracked_change_markers")
            else:
                flush()
                self._emit_table(part, f"{anchor}/tbl/{table_index:03d}")
                table_index += 1
        flush()

    def _paragraph_parts(self, paragraph: Any) -> Iterator[Any]:
        """Text, sentinels and table elements of one ``hp:p``, in document order.

        A generator on purpose: nothing past the part being consumed has been
        walked yet. A yielded table is emitted -- its cell paragraphs walked
        through this same generator -- before the walk resumes, so every
        revision marker changes the deletion state exactly where it sits in
        source order: a marker later in the paragraph cannot reach back into an
        earlier table, and a marker inside a cell governs only what follows it.
        """

        self.paragraphs += 1
        if self.paragraphs > self.limits.max_hwpx_paragraphs:
            raise StructuredParseError("HWPX_PARAGRAPH_LIMIT")
        yield from self._direct_text(paragraph.text)
        for child in paragraph:
            local = _paragraph_local(child)
            if local == "run":
                yield from self._run_parts(child)
            elif local != "linesegarray":  # Line-layout cache: covered by the layout warning.
                yield self._omit(child)
            yield from self._direct_text(child.tail)

    def _run_parts(self, run: Any) -> Iterator[Any]:
        yield from self._direct_text(run.text)
        for child in run:
            local = _paragraph_local(child)
            if local == "t":
                yield from self._text_parts(child)
            elif local == "tbl":
                # Judged against the deletion state at the table's own position.
                if self.open_deletions:
                    self._count_table()
                    self.unsupported_tables["deleted_revision"] += 1
                else:
                    yield child
            elif local == "secPr":
                pass  # Page and section layout definitions, not content.
            elif local == "ctrl":
                # Each control is omitted whole: neither its text nor the text
                # of anything inside it is read.
                for control in child:
                    yield self._omit(control)
            elif local in _REVISION_MARKS:
                yield self._mark_revision(local)
            else:
                yield self._omit(child)
            yield from self._direct_text(child.tail)

    def _text_parts(self, text: Any) -> Iterator[Any]:
        # Inside hp:t every character is content, whitespace included.
        yield from self._append_text(text.text)
        for child in text:
            local = _paragraph_local(child)
            if local in _INLINE_TEXT:
                yield from self._append_text(_INLINE_TEXT[local])
            elif local in _REVISION_MARKS:
                yield self._mark_revision(local)
            elif local not in _INERT_MARKS:
                yield self._omit(child)
            yield from self._append_text(child.tail)

    def _direct_text(self, value: str | None) -> Iterator[str]:
        if value and not _is_indentation(value):
            yield from self._append_text(value)

    def _append_text(self, value: str | None) -> Iterator[str]:
        if not value:
            return
        if self.open_deletions:
            self.deleted_chars += len(value)
            return
        self._charge(len(value))  # Charged before the consumer can buffer it.
        yield value

    def _charge(self, characters: int) -> None:
        # The extracted-text budget is enforced before text is buffered, not
        # only when a finished block reaches the builder.
        self.buffered_chars += characters
        if self.buffered_chars > self.limits.max_total_text_chars:
            raise StructuredParseError("EXTRACTED_TEXT_LIMIT")

    def _mark_revision(self, local: str) -> object:
        # Tracked deletions are omitted, insertions stay visible. The deleted
        # text is never promoted into body text.
        self.revision_marks += 1
        if local == "deleteBegin":
            self.open_deletions += 1
        elif local == "deleteEnd":
            self.open_deletions = max(0, self.open_deletions - 1)
        return _REVISION

    def _omit(self, element: Any) -> object:
        self._count_unsupported(element)
        return _OMITTED

    def _count_unsupported(self, element: Any) -> None:
        namespace, local = qualified_name(element)
        key = (
            local
            if namespace.startswith(_FEATURE_NAMESPACE_PREFIXES) and _FEATURE_NAME.fullmatch(local)
            else "other"
        )
        if key not in self.unsupported and len(self.unsupported) >= _MAX_FEATURE_KEYS:
            key = "other"
        self.unsupported[key] += 1

    def _count_table(self) -> None:
        self.table_elements += 1
        if self.table_elements > self.limits.max_hwpx_tables:
            raise StructuredParseError("HWPX_TABLE_LIMIT")

    def _preflight_table(self, table: Any) -> tuple[int, int, int | None, int | None]:
        """Fence declared and actual table dimensions before anything is allocated.

        Returns ``(row count, widest row, declared rows, declared columns)``.
        """

        limits = self.limits
        declared_rows = _declared_dimension(table.attrib.get("rowCnt"))
        declared_columns = _declared_dimension(table.attrib.get("colCnt"))
        if declared_rows is not None and declared_rows > limits.max_table_rows:
            raise StructuredParseError("TABLE_ROW_LIMIT")
        if declared_columns is not None and declared_columns > limits.max_table_columns:
            raise StructuredParseError("TABLE_COLUMN_LIMIT")
        if (
            declared_rows is not None
            and declared_columns is not None
            and declared_rows * declared_columns > limits.max_table_cells
        ):
            raise StructuredParseError("TABLE_CELL_LIMIT")

        rows = 0
        widest = 0
        cells = 0
        for row in table:
            if _paragraph_local(row) != "tr":
                continue
            rows += 1
            if rows > limits.max_table_rows:
                raise StructuredParseError("TABLE_ROW_LIMIT")
            columns = sum(1 for cell in row if _paragraph_local(cell) == "tc")
            if columns > limits.max_table_columns:
                raise StructuredParseError("TABLE_COLUMN_LIMIT")
            cells += columns
            if cells > limits.max_table_cells:
                raise StructuredParseError("TABLE_CELL_LIMIT")
            widest = max(widest, columns)
        if rows * widest > limits.max_table_cells:
            raise StructuredParseError("TABLE_CELL_LIMIT")
        return rows, widest, declared_rows, declared_columns

    def _emit_table(self, table: Any, anchor: str) -> None:
        self._count_table()
        row_count, column_count, declared_rows, declared_columns = self._preflight_table(table)
        grid = [
            [cell for cell in row if _paragraph_local(cell) == "tc"]
            for row in table
            if _paragraph_local(row) == "tr"
        ]
        reason = _unsupported_table_reason(grid, column_count)
        if reason is None and (
            (declared_rows is not None and declared_rows != row_count)
            or (declared_columns is not None and declared_columns != column_count)
        ):
            reason = "dimension_mismatch"
        if reason is None:
            reason = _cell_structure_reason(grid)
        if reason is not None:
            self.unsupported_tables[reason] += 1
            return

        # Children outside the row/cell grid are counted by their own element
        # name only; their descendants are never visited or read.
        table_flags: tuple[str, ...] = ()
        for child in table:
            local = _paragraph_local(child)
            if local == "tr":
                for row_child in child:
                    if _paragraph_local(row_child) != "tc":
                        self._count_unsupported(row_child)
                        table_flags = ("hwpx_unsupported_content_omitted",)
            elif local not in _TABLE_LAYOUT:
                self._count_unsupported(child)
                table_flags = ("hwpx_unsupported_content_omitted",)

        cells: list[TableCellSpec] = []
        for row_index, row in enumerate(grid):
            for column_index, cell in enumerate(row):
                text, flags = self._cell_text(cell)
                cells.append(
                    TableCellSpec(
                        row_index0=row_index,
                        column_index0=column_index,
                        raw_text=text,
                        location=SourceLocation(
                            page_index0=0,
                            native_object_id=f"{anchor}/tr/{row_index:06d}/tc/{column_index:06d}",
                        ),
                        quality_flags=flags,
                    )
                )
        header_rows = 0
        for row in grid:
            if not all(str(cell.attrib.get("header", "0")) == "1" for cell in row):
                break
            header_rows += 1
        self.builder.add_table(
            location=SourceLocation(page_index0=0, native_object_id=anchor),
            row_count=row_count,
            column_count=column_count,
            cells=tuple(cells),
            header_row_count=header_rows,
            quality_flags=table_flags,
        )
        self.tables += 1

    def _cell_text(self, cell: Any) -> tuple[str, tuple[str, ...]]:
        lines: list[str] = []
        flags: set[str] = set()
        # A cell emptied by a deletion opened elsewhere carries no marker of its
        # own; this flag tells it apart from a genuinely empty cell.
        deleted_before = self.deleted_chars
        for child in cell:
            local = _paragraph_local(child)
            if local in _CELL_LAYOUT:
                continue  # Structure checked before any cell was read, or layout.
            if local != "subList":
                self._count_unsupported(child)  # Counted by name; never read.
                flags.add("hwpx_unsupported_content_omitted")
                continue
            for paragraph in child:
                if _paragraph_local(paragraph) != "p":
                    self._count_unsupported(paragraph)
                    flags.add("hwpx_unsupported_content_omitted")
                    continue
                if lines:
                    self._charge(1)  # The line separator joined below.
                text: list[str] = []
                # Walked lazily too: markers in this cell apply from here on, in
                # source order, to later cells and to the rest of the outer walk.
                for part in self._paragraph_parts(paragraph):
                    if isinstance(part, str):
                        text.append(part)
                    elif part is _OMITTED:
                        flags.add("hwpx_unsupported_content_omitted")
                    elif part is _REVISION:
                        flags.add("hwpx_tracked_change_markers")
                    # Nested tables were rejected before any cell was read.
                lines.append("".join(text))
        if self.deleted_chars != deleted_before:
            flags.add("hwpx_tracked_deletion_omitted")
        return "\n".join(lines), tuple(sorted(flags))


def _unsupported_table_reason(grid: list[list[Any]], column_count: int) -> str | None:
    """Return why a table's shape is outside the unit-span basic profile, or None."""

    if not grid or column_count == 0:
        return "empty_table"
    if any(len(row) != column_count for row in grid):
        return "irregular_grid"
    return None


def _cell_structure_reason(grid: list[list[Any]]) -> str | None:
    for row_index, row in enumerate(grid):
        for column_index, cell in enumerate(row):
            if any(
                _paragraph_local(descendant) == "tbl"
                for descendant in cell.iter()
                if descendant is not cell
            ):
                return "nested_table"
            for child in cell:
                local = _paragraph_local(child)
                if local == "cellSpan" and (
                    str(child.attrib.get("colSpan", "1")) != "1"
                    or str(child.attrib.get("rowSpan", "1")) != "1"
                ):
                    return "merged_cells"
                if local == "cellAddr" and (
                    str(child.attrib.get("colAddr", column_index)) != str(column_index)
                    or str(child.attrib.get("rowAddr", row_index)) != str(row_index)
                ):
                    return "cell_address_mismatch"
    return None


def _filename_title(filename: str) -> str:
    return normalize_text(filename.rsplit(".", 1)[0].replace("_", " ")) or "HWPX document"
