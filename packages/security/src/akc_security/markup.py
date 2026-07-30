"""Portable Markdown, constrained table HTML, and CSV export safety."""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

_PROVENANCE_COMMENT = re.compile(r"<!--\s*akmp:block\b[^<>]*-->", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
_WIKILINK = re.compile(r"\[\[([^|\]]+)(?:\|[^\]]*)?]]")
_SAFE_TABLE_TAGS = frozenset(
    {"table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "br"}
)
_SAFE_ATTRIBUTES = {
    "th": frozenset({"rowspan", "colspan", "scope"}),
    "td": frozenset({"rowspan", "colspan"}),
}


class UnsafeMarkupError(ValueError):
    pass


class _StrictTableSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.stack: list[str] = []
        self.violations: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag not in _SAFE_TABLE_TAGS:
            self.violations.append(f"tag:{tag}")
            return
        rendered_attrs: list[str] = []
        allowed = _SAFE_ATTRIBUTES.get(tag, frozenset())
        for name, value in attrs:
            name = name.casefold()
            if name not in allowed or value is None:
                self.violations.append(f"attribute:{tag}.{name}")
                continue
            if name in {"rowspan", "colspan"} and (
                not value.isdigit() or not 1 <= int(value) <= 1000
            ):
                self.violations.append(f"attribute_value:{tag}.{name}")
                continue
            if name == "scope" and value not in {"row", "col", "rowgroup", "colgroup"}:
                self.violations.append("attribute_value:th.scope")
                continue
            rendered_attrs.append(f' {name}="{html.escape(value, quote=True)}"')
        self.output.append(f"<{tag}{''.join(rendered_attrs)}>")
        if tag != "br":
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag not in _SAFE_TABLE_TAGS or tag == "br":
            self.violations.append(f"end_tag:{tag}")
            return
        if not self.stack or self.stack[-1] != tag:
            self.violations.append(f"unbalanced:{tag}")
            return
        self.stack.pop()
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.output.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        self.violations.append("comment")

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&amp;{html.escape(name)};")


def sanitize_table_html(fragment: str) -> str:
    parser = _StrictTableSanitizer()
    try:
        parser.feed(fragment)
        parser.close()
    except Exception as exc:
        raise UnsafeMarkupError("malformed_html") from exc
    if parser.stack:
        parser.violations.append("unclosed_tags")
    if parser.violations:
        raise UnsafeMarkupError(",".join(sorted(set(parser.violations))))
    result = "".join(parser.output)
    if not result.lstrip().startswith("<table"):
        raise UnsafeMarkupError("table_root_required")
    return result


def ensure_portable_markdown_safe(markdown: str, *, allow_table_html: bool = False) -> str:
    without_comments = _PROVENANCE_COMMENT.sub("", markdown)
    if "<!--" in without_comments or "-->" in without_comments:
        raise UnsafeMarkupError("html_comment_forbidden")
    tags = _HTML_TAG.findall(without_comments)
    if tags:
        if not allow_table_html:
            raise UnsafeMarkupError("raw_html_forbidden")
        sanitize_table_html(without_comments.strip())
    for match in _MARKDOWN_LINK.finditer(markdown):
        target = html.unescape(unquote(match.group(1).strip("<>")))
        compact_target = "".join(character for character in target if not character.isspace())
        scheme = urlsplit(compact_target).scheme.casefold()
        if scheme and scheme not in {"https", "mailto"}:
            raise UnsafeMarkupError("unsafe_markdown_link")
        if compact_target.startswith(("//", "\\\\")):
            raise UnsafeMarkupError("network_path_forbidden")
    for match in _WIKILINK.finditer(markdown):
        target = match.group(1).replace("\\", "/")
        candidate = PurePosixPath(target)
        if candidate.is_absolute() or ".." in candidate.parts or ":" in target:
            raise UnsafeMarkupError("unsafe_wikilink")
    if "\x00" in markdown:
        raise UnsafeMarkupError("null_byte")
    return markdown.replace("\r\n", "\n").replace("\r", "\n")


def escape_csv_formula(value: str) -> str:
    index = 0
    while index < len(value):
        character = value[index]
        if character.isspace() or unicodedata.category(character).startswith("C"):
            index += 1
            continue
        break
    if index < len(value) and value[index] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value
