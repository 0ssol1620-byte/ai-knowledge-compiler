"""DOM-order HTML parsing with active content and outbound fetches disabled."""

from __future__ import annotations

from typing import Any

from akc_cir import BlockType
from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag

from .models import (
    CirBuilder,
    SourceLocation,
    StructuredParseError,
    TableCellSpec,
    normalize_text,
)

_REMOVED_TAGS = {
    "script",
    "style",
    "noscript",
    "iframe",
    "object",
    "embed",
    "applet",
    "canvas",
    "svg",
    "form",
    "input",
    "button",
    "template",
}
_SKIPPED_LAYOUT_TAGS = {
    "html",
    "body",
    "main",
    "article",
    "section",
    "div",
    "header",
    "footer",
    "details",
    "summary",
}
_URL_ATTRIBUTES = {"href", "src", "srcset", "action", "formaction", "poster", "data"}


def parse_html(source: str, builder: CirBuilder) -> str:
    try:
        soup = BeautifulSoup(source, "lxml")
    except (ValueError, TypeError) as exc:
        raise StructuredParseError("HTML_PARSE_FAILED") from exc
    _enforce_dom_limits(soup, builder)
    removed_active = 0
    for tag_name in sorted(_REMOVED_TAGS):
        matches = list(soup.find_all(tag_name))
        removed_active += len(matches)
        for tag in matches:
            tag.decompose()
    for tag in list(soup.find_all(["nav", "aside"])):
        removed_active += 1
        tag.decompose()
    for tag in list(soup.find_all(None, attrs={"role": "navigation"})):
        removed_active += 1
        tag.decompose()

    stripped_references = 0
    for tag in soup.find_all(True):
        for attribute in tuple(tag.attrs):
            if attribute.casefold() in _URL_ATTRIBUTES:
                value = tag.attrs.get(attribute)
                if _has_outbound_reference(value):
                    stripped_references += 1
                del tag.attrs[attribute]
            elif attribute.casefold().startswith("on"):
                del tag.attrs[attribute]
    if removed_active:
        builder.add_warning("html_active_content_removed")
    if stripped_references:
        builder.add_warning("html_external_references_not_fetched")
    builder.metadata["htmlSafety"] = {
        "removedActiveElementCount": removed_active,
        "strippedReferenceCount": stripped_references,
    }

    title_tag = soup.title
    title = normalize_text(title_tag.get_text(" ", strip=True) if title_tag else "")
    if title and title_tag is not None:
        builder.add_block(
            block_type=BlockType.TITLE,
            location=SourceLocation(
                page_index0=0,
                native_object_id=f"html/{_dom_path(title_tag)}",
            ),
            raw_text=title,
            markdown=f"# {title}",
        )
    main = soup.find("main")
    articles = soup.find_all("article")
    root = main or (articles[0] if len(articles) == 1 else None) or soup.body or soup
    state = _HtmlState(builder=builder, title=title)
    for child in list(root.children):
        state.consume(child)
    if not builder.blocks:
        raise StructuredParseError("HTML_EMPTY_DOCUMENT")
    return state.title or _filename_title(builder.source_filename)


class _HtmlState:
    def __init__(self, *, builder: CirBuilder, title: str) -> None:
        self.builder = builder
        self.title = title
        self.heading_stack: list[tuple[int, str]] = []

    @property
    def parent_id(self) -> str | None:
        return self.heading_stack[-1][1] if self.heading_stack else None

    def consume(self, node: Any) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            text = normalize_text(str(node))
            if text:
                parent = node.parent
                self._add_text_block(
                    parent if isinstance(parent, Tag) else None,
                    text,
                    location=(self._text_location(node) if isinstance(parent, Tag) else None),
                )
            return
        if not isinstance(node, Tag) or not node.name:
            return
        name = node.name.casefold()
        if name in {"title", "meta", "link"}:
            return
        if name in _SKIPPED_LAYOUT_TAGS:
            for child in list(node.children):
                self.consume(child)
            return
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._add_heading(node, int(name[1]))
            return
        if name == "p":
            self._add_text_block(node, node.get_text(" ", strip=True))
            return
        if name in {"ul", "ol"}:
            self._add_list(node, ordered=name == "ol")
            return
        if name == "table":
            self._add_table(node)
            return
        if name == "blockquote":
            self._add_text_block(
                node,
                node.get_text("\n", strip=True),
                block_type=BlockType.QUOTE,
            )
            return
        if name == "pre":
            text = normalize_text(node.get_text("\n", strip=False))
            if text:
                self.builder.add_block(
                    block_type=BlockType.CODE,
                    location=self._location(node),
                    raw_text=text,
                    markdown=f"```\n{text}\n```",
                    parent_id=self.parent_id,
                )
            return
        if name == "figure":
            self._add_figure(node)
            return
        if name == "img":
            self._add_image(node)
            return
        if name in {"hr", "br"}:
            return
        for child in list(node.children):
            self.consume(child)

    def _add_heading(self, tag: Tag, level: int) -> None:
        text = normalize_text(tag.get_text(" ", strip=True))
        if not text:
            return
        while self.heading_stack and self.heading_stack[-1][0] >= level:
            self.heading_stack.pop()
        parent_id = self.parent_id
        block_type = BlockType.TITLE if level == 1 and not self.title else BlockType.HEADING
        block = self.builder.add_block(
            block_type=block_type,
            location=self._location(tag),
            raw_text=text,
            markdown=f"{'#' * min(6, level)} {text}",
            parent_id=parent_id,
        )
        self.heading_stack.append((level, block.id))
        if not self.title:
            self.title = text

    def _add_text_block(
        self,
        tag: Tag | None,
        text: str,
        *,
        block_type: BlockType = BlockType.PARAGRAPH,
        location: SourceLocation | None = None,
    ) -> None:
        normalized = normalize_text(text)
        if not normalized or tag is None:
            return
        self.builder.add_block(
            block_type=block_type,
            location=location or self._location(tag),
            raw_text=normalized,
            markdown=normalized,
            parent_id=self.parent_id,
        )

    def _add_list(self, tag: Tag, *, ordered: bool) -> None:
        items = [
            normalize_text(item.get_text(" ", strip=True))
            for item in tag.find_all("li", recursive=False)
        ]
        items = [item for item in items if item]
        if not items:
            return
        markdown = "\n".join(
            f"{index + 1}. {item}" if ordered else f"- {item}" for index, item in enumerate(items)
        )
        self.builder.add_block(
            block_type=BlockType.LIST,
            location=self._location(tag),
            raw_text="\n".join(items),
            markdown=markdown,
            parent_id=self.parent_id,
            quality_flags=(("ordered_list",) if ordered else ("unordered_list",)),
        )

    def _add_table(self, tag: Tag) -> None:
        rows = [row for row in tag.find_all("tr") if row.find_parent("table") is tag]
        if not rows:
            return
        if len(rows) > self.builder.limits.max_table_rows:
            raise StructuredParseError("TABLE_ROW_LIMIT")
        occupied: set[tuple[int, int]] = set()
        specs: list[TableCellSpec] = []
        max_column = 0
        header_rows = 0
        for row_index, row in enumerate(rows):
            column_index = 0
            row_cells = [cell for cell in row.find_all(["th", "td"], recursive=False)]
            if (
                row_cells
                and all(cell.name == "th" for cell in row_cells)
                and row_index == header_rows
            ):
                header_rows += 1
            for cell in row_cells:
                while (row_index, column_index) in occupied:
                    column_index += 1
                row_span = _positive_span(cell.get("rowspan"))
                column_span = _positive_span(cell.get("colspan"))
                if row_index + row_span > self.builder.limits.max_table_rows:
                    raise StructuredParseError("TABLE_ROW_LIMIT")
                if column_index + column_span > self.builder.limits.max_table_columns:
                    raise StructuredParseError("TABLE_COLUMN_LIMIT")
                if len(occupied) + row_span * column_span > self.builder.limits.max_table_cells:
                    raise StructuredParseError("TABLE_CELL_LIMIT")
                for occupied_row in range(row_index, row_index + row_span):
                    for occupied_column in range(
                        column_index,
                        column_index + column_span,
                    ):
                        if (occupied_row, occupied_column) in occupied:
                            raise StructuredParseError("HTML_TABLE_OVERLAP")
                        occupied.add((occupied_row, occupied_column))
                specs.append(
                    TableCellSpec(
                        row_index0=row_index,
                        column_index0=column_index,
                        row_span=row_span,
                        column_span=column_span,
                        raw_text=normalize_text(cell.get_text(" ", strip=True)),
                        location=self._location(cell),
                    )
                )
                max_column = max(max_column, column_index + column_span)
                column_index += column_span
        row_count = max(
            len(rows),
            max((row for row, _column in occupied), default=-1) + 1,
        )
        if not specs or max_column <= 0:
            return
        caption_tag = tag.find("caption", recursive=False)
        caption = (
            normalize_text(caption_tag.get_text(" ", strip=True))
            if isinstance(caption_tag, Tag)
            else None
        )
        self.builder.add_table(
            location=self._location(tag),
            row_count=row_count,
            column_count=max_column,
            cells=tuple(specs),
            header_row_count=header_rows,
            caption=caption,
            parent_id=self.parent_id,
        )

    def _add_figure(self, tag: Tag) -> None:
        image = tag.find("img")
        caption_tag = tag.find("figcaption")
        caption = (
            normalize_text(caption_tag.get_text(" ", strip=True))
            if isinstance(caption_tag, Tag)
            else ""
        )
        alt = normalize_text(str(image.get("alt", ""))) if isinstance(image, Tag) else ""
        label = caption or alt or "Figure"
        figure = self.builder.add_block(
            block_type=BlockType.FIGURE,
            location=self._location(tag),
            raw_text=label,
            markdown=f"![{alt or label}]()",
            parent_id=self.parent_id,
            quality_flags=("asset_not_fetched",),
        )
        if caption:
            if not isinstance(caption_tag, Tag):
                raise RuntimeError("caption text exists without a caption tag")
            self.builder.add_block(
                block_type=BlockType.CAPTION,
                location=self._location(caption_tag),
                raw_text=caption,
                markdown=caption,
                parent_id=figure.id,
            )

    def _add_image(self, tag: Tag) -> None:
        alt = normalize_text(str(tag.get("alt", ""))) or "Image"
        self.builder.add_block(
            block_type=BlockType.FIGURE,
            location=self._location(tag),
            raw_text=alt,
            markdown=f"![{alt}]()",
            parent_id=self.parent_id,
            quality_flags=("asset_not_fetched",),
        )

    def _location(self, tag: Tag) -> SourceLocation:
        return SourceLocation(
            page_index0=0,
            native_object_id=f"html/{_dom_path(tag)}",
        )

    def _text_location(self, node: NavigableString) -> SourceLocation:
        parent = node.parent
        if not isinstance(parent, Tag):
            return SourceLocation(
                page_index0=0,
                native_object_id="html/document/text()[1]",
            )
        text_index = 1 + sum(
            1
            for sibling in node.previous_siblings
            if isinstance(sibling, NavigableString) and not isinstance(sibling, Comment)
        )
        return SourceLocation(
            page_index0=0,
            native_object_id=f"html/{_dom_path(parent)}/text()[{text_index}]",
        )


def _enforce_dom_limits(soup: BeautifulSoup, builder: CirBuilder) -> None:
    for count, tag in enumerate(soup.find_all(True), start=1):
        if count > builder.limits.max_html_nodes:
            raise StructuredParseError("HTML_NODE_LIMIT")
        depth = sum(1 for parent in tag.parents if isinstance(parent, Tag))
        if depth > builder.limits.max_html_depth:
            raise StructuredParseError("HTML_DEPTH_LIMIT")


def _dom_path(tag: Tag) -> str:
    parts: list[str] = []
    current: Tag | None = tag
    while current is not None and current.name not in {"[document]"}:
        name = current.name.casefold()
        index = 1 + sum(
            1
            for sibling in current.previous_siblings
            if isinstance(sibling, Tag) and sibling.name == current.name
        )
        parts.append(f"{name}[{index}]")
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return "/".join(reversed(parts)) or "document"


def _positive_span(value: Any) -> int:
    if value is None:
        return 1
    try:
        parsed = int(str(value))
    except ValueError as exc:
        raise StructuredParseError("HTML_TABLE_INVALID_SPAN") from exc
    if parsed < 1:
        raise StructuredParseError("HTML_TABLE_INVALID_SPAN")
    return parsed


def _has_outbound_reference(value: Any) -> bool:
    if value is None:
        return False
    text = " ".join(str(item) for item in value) if isinstance(value, list) else str(value)
    stripped = text.strip()
    return bool(stripped and not stripped.startswith("#"))


def _filename_title(filename: str) -> str:
    return normalize_text(filename.rsplit(".", 1)[0].replace("_", " ")) or "HTML document"
