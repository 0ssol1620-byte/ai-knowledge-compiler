"""Portable Markdown, constrained table HTML, and CSV export safety."""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

_PROVENANCE_COMMENT = re.compile(r"<!--\s*akmp:block\b[^<>]*-->", re.IGNORECASE)
# Raw HTML, Markdown links and wikilinks are found by hand scanners rather than
# by ``finditer`` over a regex: those regexes re-read the rest of the input from
# every ``<`` or ``[`` and go quadratic on hostile Markdown. Each scanner reports
# exactly what its regex would; the regexes stay as the oracle in
# tests/security/test_regex_redos_regressions.py.
_HTML_TAG_START = re.compile(r"</?[A-Za-z]")
_QUOTE = re.compile(r"['\"]")
_WIKILINK_STOP = re.compile(r"[|\]]")
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


def _has_html_tag(text: str) -> bool:
    """Whether ``</?[A-Za-z][^>]*>`` matches anywhere in ``text``."""

    start = _HTML_TAG_START.search(text)
    return start is not None and text.find(">", start.end()) >= 0


def _markdown_link_targets(text: str) -> Iterator[str]:
    r"""Yield group 1 of every ``!?\[[^\]]*]\(([^)\s]+)(?:\s+['"][^'"]*['"])?\)`` match.

    From a given ``](`` that regex is deterministic, so the only waste is
    retrying it where the outcome is already known: every ``[`` before the same
    ``]`` shares that ``]``, and a target starting inside a target run that
    already failed stops at the same character and fails the same way.
    """

    length = len(text)
    position = 0
    dead_run_end = -1
    while True:
        opening = text.find("[", position)
        if opening < 0:
            return
        closing = text.find("]", opening + 1)
        if closing < 0:
            return
        position = closing + 1
        start = closing + 2
        if text[closing + 1 : start] != "(" or start < dead_run_end:
            continue
        stop = start
        while stop < length and text[stop] != ")" and not text[stop].isspace():
            stop += 1
        if stop == length:
            return  # no ")" remains, so no later link can close either
        if stop == start:
            continue
        if text[stop] == ")":
            yield text[start:stop]
            position = stop + 1
            continue
        title = stop
        while title < length and text[title].isspace():
            title += 1
        if title < length and text[title] in "'\"":
            title_end = _QUOTE.search(text, title + 1)
            if title_end is not None and text[title_end.end() : title_end.end() + 1] == ")":
                yield text[start:stop]
                position = title_end.end() + 1
                continue
        dead_run_end = stop


def _wikilink_targets(text: str) -> Iterator[str]:
    r"""Yield group 1 of every ``\[\[([^|\]]+)(?:\|[^\]]*)?]]`` match.

    A candidate that fails at a ``]`` fails for every later ``[[`` before that
    ``]`` too, so the scan resumes after it and never re-reads a span.
    """

    position = 0
    while True:
        opening = text.find("[[", position)
        if opening < 0:
            return
        start = opening + 2
        stop_match = _WIKILINK_STOP.search(text, start)
        if stop_match is None:
            return  # no "]" remains, so no later wikilink can close either
        stop = stop_match.start()
        if stop == start:
            position = opening + 1
            continue
        closing = stop if text[stop] == "]" else text.find("]", stop + 1)
        if closing < 0:
            return
        if text[closing + 1 : closing + 2] == "]":
            yield text[start:stop]
            position = closing + 2
        else:
            position = closing + 1


def ensure_portable_markdown_safe(markdown: str, *, allow_table_html: bool = False) -> str:
    without_comments = _PROVENANCE_COMMENT.sub("", markdown)
    if "<!--" in without_comments or "-->" in without_comments:
        raise UnsafeMarkupError("html_comment_forbidden")
    if _has_html_tag(without_comments):
        if not allow_table_html:
            raise UnsafeMarkupError("raw_html_forbidden")
        sanitize_table_html(without_comments.strip())
    for link_target in _markdown_link_targets(markdown):
        target = html.unescape(unquote(link_target.strip("<>")))
        compact_target = "".join(character for character in target if not character.isspace())
        scheme = urlsplit(compact_target).scheme.casefold()
        if scheme and scheme not in {"https", "mailto"}:
            raise UnsafeMarkupError("unsafe_markdown_link")
        if compact_target.startswith(("//", "\\\\")):
            raise UnsafeMarkupError("network_path_forbidden")
    for wikilink_target in _wikilink_targets(markdown):
        target = wikilink_target.replace("\\", "/")
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
