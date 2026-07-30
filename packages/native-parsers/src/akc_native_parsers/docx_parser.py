"""DOCX structure, revision, comment, and embedded-asset extraction."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable
from typing import Any

from akc_cir import BlockType
from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException
from docx import Document as open_docx
from docx.document import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from .models import (
    CirBuilder,
    SourceLocation,
    StructuredParseError,
    TableCellSpec,
    normalize_text,
)

_HEADING_PATTERN = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)
_RELATIONSHIP_ATTRIBUTE_NAMES = frozenset({"embed", "id"})


def parse_docx(data: bytes, builder: CirBuilder) -> str:
    try:
        document = open_docx(io.BytesIO(data))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise StructuredParseError("DOCX_PARSE_FAILED") from exc

    title = normalize_text(document.core_properties.title or "")
    heading_stack: list[tuple[int, str]] = []
    table_count = 0
    body_elements = list(document.element.body.iterchildren())
    if len(body_elements) > builder.limits.max_docx_body_elements:
        raise StructuredParseError("DOCX_BODY_ELEMENT_LIMIT")

    comment_parents: dict[str, str] = {}
    last_figure_id: str | None = None
    image_placement_count = 0
    text_box_count = 0
    for body_index, element in enumerate(body_elements):
        local_name = _local_name(element)
        if local_name == "p":
            paragraph = Paragraph(element, document)
            style_name = paragraph.style.name if paragraph.style is not None else ""
            text = _visible_text(element)
            location = SourceLocation(
                page_index0=0,
                native_object_id=f"docx/body/p/{body_index:06d}",
            )
            figure_ids = _add_docx_figures(
                element,
                related_part=document.part,
                builder=builder,
                location=location,
                parent_id=heading_stack[-1][1] if heading_stack else None,
            )
            image_placement_count += len(figure_ids)
            if figure_ids:
                last_figure_id = figure_ids[-1]

            if text and _is_caption_style(style_name):
                block = builder.add_block(
                    block_type=BlockType.CAPTION,
                    location=location,
                    raw_text=text,
                    markdown=f"*{text}*",
                    parent_id=last_figure_id,
                    quality_flags=(
                        "native_caption_preserved",
                        *(
                            ("caption_figure_link_inferred",)
                            if last_figure_id is not None
                            else ("caption_without_figure",)
                        ),
                    ),
                )
                _record_comment_parents(element, block.id, comment_parents)
            elif text:
                paragraph_properties = paragraph._p.pPr
                has_numbering = (
                    paragraph_properties is not None and paragraph_properties.numPr is not None
                )
                block_type, heading_level = _paragraph_type(
                    style_name,
                    has_numbering=has_numbering,
                )
                flags = list(_revision_quality_flags(element))
                if block_type in {BlockType.TITLE, BlockType.HEADING}:
                    level = heading_level or (1 if block_type == BlockType.TITLE else 2)
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    parent_id = heading_stack[-1][1] if heading_stack else None
                    block = builder.add_block(
                        block_type=block_type,
                        location=location,
                        raw_text=text,
                        markdown=(
                            f"# {text}"
                            if block_type == BlockType.TITLE
                            else f"{'#' * min(6, level)} {text}"
                        ),
                        parent_id=parent_id,
                        quality_flags=tuple(flags),
                    )
                    heading_stack.append((level, block.id))
                    if not title and block_type == BlockType.TITLE:
                        title = text
                else:
                    parent_id = heading_stack[-1][1] if heading_stack else None
                    if block_type == BlockType.LIST:
                        flags.append("list_style_inferred")
                    block = builder.add_block(
                        block_type=block_type,
                        location=location,
                        raw_text=text,
                        markdown=f"- {text}" if block_type == BlockType.LIST else text,
                        parent_id=parent_id,
                        quality_flags=tuple(flags),
                    )
                _record_comment_parents(element, block.id, comment_parents)

            text_box_count += _add_text_boxes(
                element,
                builder=builder,
                body_index=body_index,
                parent_id=heading_stack[-1][1] if heading_stack else None,
            )
        elif local_name == "tbl":
            table_count += 1
            if table_count > builder.limits.max_docx_tables:
                raise StructuredParseError("DOCX_TABLE_LIMIT")
            table = Table(element, document)
            parent_id = heading_stack[-1][1] if heading_stack else None
            _add_docx_table(
                table,
                builder=builder,
                body_index=body_index,
                parent_id=parent_id,
            )

    story_image_count = _add_headers_and_footers(document, builder)
    comments = _add_comments(data, builder, comment_parents)
    revisions = _collect_revisions(data, builder)
    if revisions:
        builder.add_warning("docx_tracked_changes_visible_view_preserved")
    _collect_unhandled_docx_warnings(data, builder)
    builder.metadata["docx"] = {
        "imageAssetCount": len(builder.assets),
        "imagePlacementCount": image_placement_count + story_image_count,
        "textBoxCount": text_box_count,
        "commentCount": comments,
        "trackedChanges": revisions,
        "trackedChangeView": "insertions-visible-deletions-metadata-only",
    }
    if not builder.blocks:
        raise StructuredParseError("DOCX_EMPTY_DOCUMENT")
    return title or _filename_title(builder.source_filename)


def _paragraph_type(
    style_name: str,
    *,
    has_numbering: bool,
) -> tuple[BlockType, int | None]:
    normalized = style_name.strip()
    if normalized.casefold() == "title":
        return BlockType.TITLE, 1
    match = _HEADING_PATTERN.match(normalized)
    if match:
        return BlockType.HEADING, int(match.group(1))
    if has_numbering or normalized.casefold().startswith(("list", "bullet", "number")):
        return BlockType.LIST, None
    if normalized.casefold().startswith("quote"):
        return BlockType.QUOTE, None
    return BlockType.PARAGRAPH, None


def _add_docx_table(
    table: Table,
    *,
    builder: CirBuilder,
    body_index: int,
    parent_id: str | None,
) -> None:
    rows = list(table.rows)
    if not rows:
        return
    row_count = len(rows)
    column_count = max((len(row.cells) for row in rows), default=0)
    if row_count > builder.limits.max_table_rows:
        raise StructuredParseError("TABLE_ROW_LIMIT")
    if column_count > builder.limits.max_table_columns:
        raise StructuredParseError("TABLE_COLUMN_LIMIT")

    locations_by_cell: dict[int, list[tuple[int, int]]] = {}
    cell_by_key: dict[int, Any] = {}
    for row_index, row in enumerate(rows):
        for column_index, cell in enumerate(row.cells):
            key = id(cell._tc)
            locations_by_cell.setdefault(key, []).append((row_index, column_index))
            cell_by_key[key] = cell

    cells: list[TableCellSpec] = []
    table_location = SourceLocation(
        page_index0=0,
        native_object_id=f"docx/body/table/{body_index:06d}",
    )
    for key, positions in sorted(
        locations_by_cell.items(),
        key=lambda item: min(item[1]),
    ):
        row_indices = [position[0] for position in positions]
        column_indices = [position[1] for position in positions]
        first_row = min(row_indices)
        first_column = min(column_indices)
        row_span = max(row_indices) - first_row + 1
        column_span = max(column_indices) - first_column + 1
        expected_area = row_span * column_span
        quality_flags: tuple[str, ...] = ()
        if expected_area != len(set(positions)):
            quality_flags = ("irregular_merge_geometry",)
            row_span = 1
            column_span = 1
        text = normalize_text(str(cell_by_key[key].text))
        cells.append(
            TableCellSpec(
                row_index0=first_row,
                column_index0=first_column,
                row_span=row_span,
                column_span=column_span,
                raw_text=text,
                location=SourceLocation(
                    page_index0=0,
                    native_object_id=(
                        f"{table_location.native_object_id}/r/{first_row:06d}/c/{first_column:06d}"
                    ),
                ),
                quality_flags=quality_flags,
            )
        )
    if not cells:
        return
    header_row_count = 1 if _looks_like_header(cells) else 0
    builder.add_table(
        location=table_location,
        row_count=row_count,
        column_count=column_count,
        cells=tuple(cells),
        header_row_count=header_row_count,
        parent_id=parent_id,
        quality_flags=(("header_row_inferred",) if header_row_count else ()),
    )


def _looks_like_header(cells: Iterable[TableCellSpec]) -> bool:
    first_row = [cell for cell in cells if cell.row_index0 == 0]
    return bool(first_row) and all(cell.raw_text.strip() for cell in first_row)


def _add_headers_and_footers(document: Document, builder: CirBuilder) -> int:
    seen_parts: set[str] = set()
    image_count = 0
    for section_index, section in enumerate(document.sections):
        for kind, story, block_type in (
            ("header", section.header, BlockType.HEADER),
            ("footer", section.footer, BlockType.FOOTER),
        ):
            part_name = str(story.part.partname)
            identity = f"{kind}:{part_name}"
            if identity in seen_parts:
                continue
            seen_parts.add(identity)
            for paragraph_index, paragraph in enumerate(story.paragraphs):
                native_id = f"docx/section/{section_index:04d}/{kind}/p/{paragraph_index:06d}"
                text = _visible_text(paragraph._p)
                if text:
                    builder.add_block(
                        block_type=block_type,
                        location=SourceLocation(
                            page_index0=0,
                            native_object_id=native_id,
                        ),
                        raw_text=text,
                        markdown=text,
                        quality_flags=_revision_quality_flags(paragraph._p),
                    )
                image_count += len(
                    _add_docx_figures(
                        paragraph._p,
                        related_part=story.part,
                        builder=builder,
                        location=SourceLocation(
                            page_index0=0,
                            native_object_id=native_id,
                        ),
                        parent_id=None,
                    )
                )
    return image_count


def _add_docx_figures(
    element: Any,
    *,
    related_part: Any,
    builder: CirBuilder,
    location: SourceLocation,
    parent_id: str | None,
) -> list[str]:
    figure_ids: list[str] = []
    drawings = [node for node in element.iter() if _local_name(node) in {"drawing", "pict"}]
    for drawing_index, drawing in enumerate(drawings):
        relationship_id: str | None = None
        for node in drawing.iter():
            if _local_name(node) not in {"blip", "imagedata"}:
                continue
            relationship_id = _attribute_by_local_names(
                node,
                _RELATIONSHIP_ATTRIBUTE_NAMES,
            )
            if relationship_id:
                break
        if not relationship_id:
            continue
        image_part = related_part.related_parts.get(relationship_id)
        if image_part is None or not hasattr(image_part, "blob"):
            builder.add_warning("docx_image_relationship_unresolved")
            continue
        payload = bytes(image_part.blob)
        image = getattr(image_part, "image", None)
        width_px = int(getattr(image, "px_width", 0)) or None
        height_px = int(getattr(image, "px_height", 0)) or None
        part_name = str(getattr(image_part, "partname", relationship_id)).lstrip("/")
        filename = part_name.rsplit("/", 1)[-1]
        media_type = str(getattr(image_part, "content_type", "application/octet-stream"))
        asset_id = builder.register_asset(
            payload=payload,
            native_part=part_name,
            media_type=media_type,
            kind="image",
            filename=filename,
            width_px=width_px,
            height_px=height_px,
        )
        label, has_alt = _drawing_label(drawing, filename)
        figure_location = SourceLocation(
            page_index0=location.page_index0,
            native_object_id=f"{location.native_object_id}/drawing/{drawing_index:04d}",
            image_asset_id=asset_id,
        )
        block = builder.add_block(
            block_type=BlockType.FIGURE,
            location=figure_location,
            raw_text=label,
            markdown=f"![{label}](akc-asset:{asset_id})",
            parent_id=parent_id,
            quality_flags=(
                "embedded_asset_extracted",
                *(("alt_text_preserved",) if has_alt else ()),
            ),
        )
        figure_ids.append(block.id)
    return figure_ids


def _drawing_label(drawing: Any, filename: str) -> tuple[str, bool]:
    for node in drawing.iter():
        if _local_name(node) not in {"docPr", "cNvPr"}:
            continue
        for name in ("descr", "title"):
            value = normalize_text(str(node.get(name, "")))
            if value:
                return value, True
    return normalize_text(filename.replace("_", " ")), False


def _add_text_boxes(
    element: Any,
    *,
    builder: CirBuilder,
    body_index: int,
    parent_id: str | None,
) -> int:
    text_box_count = 0
    for text_box_index, text_box in enumerate(
        node for node in element.iter() if _local_name(node) == "txbxContent"
    ):
        for paragraph_index, paragraph in enumerate(
            node for node in text_box.iter() if _local_name(node) == "p"
        ):
            text = _visible_text(paragraph, include_text_boxes=True)
            if not text:
                continue
            builder.add_block(
                block_type=BlockType.PARAGRAPH,
                location=SourceLocation(
                    page_index0=0,
                    native_object_id=(
                        f"docx/body/p/{body_index:06d}/textbox/"
                        f"{text_box_index:04d}/p/{paragraph_index:04d}"
                    ),
                ),
                raw_text=text,
                markdown=text,
                parent_id=parent_id,
                quality_flags=("text_box_extracted",),
            )
            text_box_count += 1
    return text_box_count


def _add_comments(
    data: bytes,
    builder: CirBuilder,
    comment_parents: dict[str, str],
) -> int:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "word/comments.xml" not in archive.namelist():
            return 0
        try:
            root = SafeElementTree.fromstring(archive.read("word/comments.xml"))
        except (DefusedXmlException, SafeElementTree.ParseError) as exc:
            raise StructuredParseError("DOCX_PARSE_FAILED") from exc
    count = 0
    for comment in root.iter():
        if _local_name(comment) != "comment":
            continue
        comment_id = _attribute_by_local_names(comment, frozenset({"id"}))
        if comment_id is None:
            continue
        text = _visible_text(comment, include_text_boxes=True)
        if not text:
            continue
        author = _attribute_by_local_names(comment, frozenset({"author"}))
        date = _attribute_by_local_names(comment, frozenset({"date"}))
        flags = ["docx_comment"]
        if author:
            flags.append("comment_author_preserved")
        if date:
            flags.append("comment_timestamp_preserved")
        builder.add_block(
            block_type=BlockType.FOOTNOTE,
            location=SourceLocation(
                page_index0=0,
                native_object_id=f"docx/comments/{comment_id}",
            ),
            raw_text=text,
            markdown=text,
            parent_id=comment_parents.get(comment_id),
            quality_flags=tuple(flags),
        )
        count += 1
    return count


def _collect_revisions(data: bytes, builder: CirBuilder) -> list[dict[str, Any]]:
    revisions: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = sorted(
            name
            for name in archive.namelist()
            if name == "word/document.xml" or re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
        )
        for entry in entries:
            try:
                root = SafeElementTree.fromstring(archive.read(entry))
            except (DefusedXmlException, SafeElementTree.ParseError) as exc:
                raise StructuredParseError("DOCX_PARSE_FAILED") from exc
            part_index = 0
            for node in root.iter():
                kind = _local_name(node)
                if kind not in {"ins", "del"}:
                    continue
                text = _revision_text(node)
                descriptor: dict[str, Any] = {
                    "kind": "insertion" if kind == "ins" else "deletion",
                    "nativeObjectId": f"docx/revision/{entry}/{part_index:06d}",
                    "text": text,
                    "visible": kind == "ins",
                }
                author = _attribute_by_local_names(node, frozenset({"author"}))
                changed_at = _attribute_by_local_names(node, frozenset({"date"}))
                if author:
                    descriptor["author"] = author
                if changed_at:
                    descriptor["changedAt"] = changed_at
                builder.reserve_metadata_text(text)
                revisions.append(descriptor)
                part_index += 1
    return revisions


def _collect_unhandled_docx_warnings(data: bytes, builder: CirBuilder) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = {entry.filename.replace("\\", "/").casefold() for entry in archive.infolist()}
    if any(name.startswith("word/diagrams/") for name in names):
        builder.add_warning("docx_smartart_not_extracted")


def _visible_text(element: Any, *, include_text_boxes: bool = False) -> str:
    parts: list[str] = []

    def visit(node: Any, deleted: bool = False) -> None:
        local_name = _local_name(node)
        if local_name == "txbxContent" and not include_text_boxes:
            return
        deleted = deleted or local_name == "del"
        if not deleted:
            if local_name in {"t", "delText"} and node.text:
                parts.append(str(node.text))
            elif local_name == "tab":
                parts.append("\t")
            elif local_name in {"br", "cr"}:
                parts.append("\n")
        for child in node:
            visit(child, deleted)

    visit(element)
    return normalize_text("".join(parts))


def _revision_text(element: Any) -> str:
    parts: list[str] = []
    for node in element.iter():
        if _local_name(node) in {"t", "delText"} and node.text:
            parts.append(str(node.text))
    return normalize_text("".join(parts))


def _revision_quality_flags(element: Any) -> tuple[str, ...]:
    names = {_local_name(node) for node in element.iter()}
    flags: list[str] = []
    if "ins" in names:
        flags.append("tracked_insertions_visible")
    if "del" in names:
        flags.append("tracked_deletions_excluded")
    if "commentReference" in names or "commentRangeStart" in names:
        flags.append("comment_reference_preserved")
    return tuple(flags)


def _record_comment_parents(
    element: Any,
    block_id: str,
    comment_parents: dict[str, str],
) -> None:
    for node in element.iter():
        if _local_name(node) not in {
            "commentReference",
            "commentRangeStart",
            "commentRangeEnd",
        }:
            continue
        comment_id = _attribute_by_local_names(node, frozenset({"id"}))
        if comment_id is not None:
            comment_parents.setdefault(comment_id, block_id)


def _attribute_by_local_names(element: Any, names: frozenset[str]) -> str | None:
    for qualified_name, value in element.attrib.items():
        local_name = str(qualified_name).rsplit("}", 1)[-1]
        if local_name in names:
            normalized = normalize_text(str(value))
            if normalized:
                return normalized
    return None


def _local_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def _is_caption_style(style_name: str) -> bool:
    return "caption" in style_name.casefold()


def _filename_title(filename: str) -> str:
    return normalize_text(filename.rsplit(".", 1)[0].replace("_", " ")) or "Document"
