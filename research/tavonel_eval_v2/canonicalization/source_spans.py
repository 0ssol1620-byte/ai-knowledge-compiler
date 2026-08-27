"""Raw source → declared spans → canonical facts. P0d sections 2 and 3.

INC-V2-006 found two real revisions whose canonical units were byte-identical
while the raw source had changed — in one case a link target moved. Every
mechanism P0b and P0c measure sits *downstream* of the canonicaliser, so none of
them could see it. This module is the missing upstream stage.

The rule, in the order it is applied:

    raw source difference
      → declared-irrelevant syntax, or a canonical source fact
      → projected into a known facet
      → if unprojectable but possibly meaningful: UNMODELED_SOURCE_FACT
      → and an UNMODELED_SOURCE_FACT may never support a CURRENT verdict

Two classifications that must not be conflated:

``IGNORED_BY_DECLARED_POLICY``
    a construct declared non-semantic, with the declaration recorded and
    justified. An HTML comment addressed to editors is the example. Ignoring is
    a claim, and the claim is written down where it can be disagreed with.

``UNMODELED_SOURCE_FACT``
    source the grammar did not classify. It might be meaningless; nobody has
    established that. It is counted, surfaced, and barred from supporting a
    currency claim.

The distinction is the whole point. A model that silently folds the second into
the first reports full coverage and has merely stopped looking.

Reference-bearing constructs — hyperlink targets, directive arguments, citation
destinations, include targets, anchor identifiers — are **first-class canonical
facts**, not prose. They change downstream meaning and relationships without
changing a word of visible text, which is precisely how INC-V2-006 escaped.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Iterable

# --- classifications ---------------------------------------------------------

MODELED = "MODELED"
IGNORED = "IGNORED_BY_DECLARED_POLICY"
UNMODELED = "UNMODELED_SOURCE_FACT"

# --- typed reference edges ---------------------------------------------------

HYPERLINK = "hyperlink"
IMAGE = "image"
LINK_DEFINITION = "link_definition"
DIRECTIVE = "directive"
INCLUDE = "include"
ANCHOR = "anchor"

REFERENCE_KINDS = (HYPERLINK, IMAGE, LINK_DEFINITION, DIRECTIVE, INCLUDE, ANCHOR)

#: Directive names whose argument is an include target rather than a rendering
#: parameter. Declared, because guessing from the name at runtime is how a
#: silent misclassification gets in.
INCLUDE_DIRECTIVES = frozenset(
    {"include", "readfile", "include-html", "include-md", "insert"}
)


class Span:
    __slots__ = ("start", "end", "kind", "classification", "text", "fact")

    def __init__(
        self,
        start: int,
        end: int,
        kind: str,
        classification: str,
        text: str,
        fact: dict[str, Any] | None = None,
    ) -> None:
        self.start = start
        self.end = end
        self.kind = kind
        self.classification = classification
        self.text = text
        self.fact = fact

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "length": self.end - self.start,
            "kind": self.kind,
            "classification": self.classification,
            "fact": self.fact,
        }


# --- markdown grammar --------------------------------------------------------

_MD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("html_comment", re.compile(r"<!--.*?-->", re.DOTALL)),
    ("front_matter", re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*\r?\n", re.DOTALL)),
    ("fenced_code", re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)),
    ("shortcode", re.compile(r"\{\{[<%]-?\s*(?P<name>[\w./-]+)(?P<args>[^}]*?)-?[>%]\}\}")),
    ("image", re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")),
    ("link_inline", re.compile(r"(?<!!)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")),
    ("link_reference_def", re.compile(r"^[ \t]{0,3}\[(?P<id>[^\]]+)\]:[ \t]*(?P<target>\S+)", re.MULTILINE)),
    ("autolink", re.compile(r"<(?P<target>(?:https?|mailto):[^>\s]+)>")),
    ("heading_anchor", re.compile(r"\{#(?P<id>[\w-]+)\}")),
    ("html_anchor", re.compile(r"<a\s+(?:id|name)=\"(?P<id>[^\"]+)\"[^>]*>")),
    ("html_href", re.compile(r"<a\s+[^>]*href=\"(?P<target>[^\"]+)\"[^>]*>")),
    ("atx_heading", re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<title>.+?)[ \t]*#*[ \t]*$", re.MULTILINE)),
)

#: Declared non-semantic in markdown. Each entry is a claim about meaning, and
#: the protocol carries the justification for it.
_MD_IGNORED_KINDS = frozenset({"html_comment", "blank"})

_BLANK = re.compile(r"\A[\s]*\Z")


def _shortcode_fact(match: re.Match[str]) -> dict[str, Any]:
    name = match.group("name")
    raw_args = (match.group("args") or "").strip()
    # named arguments first, then bare positional ones
    named = dict(re.findall(r'([\w.-]+)\s*=\s*"([^"]*)"', raw_args))
    positional = re.findall(r'(?<![\w.=-])"([^"]*)"', raw_args)
    kind = INCLUDE if name.lower() in INCLUDE_DIRECTIVES else DIRECTIVE
    target = named.get("page") or named.get("src") or named.get("file") or (
        positional[0] if positional else None
    )
    return {
        "reference_kind": kind,
        "name": name,
        "arguments": named,
        "positional": positional,
        "target": target,
        "raw_arguments": raw_args,
    }


def _markdown_facts(kind: str, match: re.Match[str]) -> dict[str, Any] | None:
    if kind == "shortcode":
        return _shortcode_fact(match)
    if kind == "image":
        return {"reference_kind": IMAGE, "target": match.group("target"), "alt": match.group("alt")}
    if kind == "link_inline":
        return {"reference_kind": HYPERLINK, "target": match.group("target"), "label": match.group("text")}
    if kind == "link_reference_def":
        return {"reference_kind": LINK_DEFINITION, "identifier": match.group("id"), "target": match.group("target")}
    if kind == "autolink":
        return {"reference_kind": HYPERLINK, "target": match.group("target"), "label": match.group("target")}
    if kind in ("heading_anchor", "html_anchor"):
        return {"reference_kind": ANCHOR, "identifier": match.group("id"), "target": "#" + match.group("id")}
    if kind == "html_href":
        return {"reference_kind": HYPERLINK, "target": match.group("target"), "label": None}
    if kind == "front_matter":
        fields = dict(
            re.findall(r"^([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$", match.group(0), re.MULTILINE)
        )
        return {"reference_kind": None, "front_matter_fields": fields}
    if kind == "atx_heading":
        return {"reference_kind": None, "heading_level": len(match.group("hashes")), "title": match.group("title")}
    if kind == "fenced_code":
        return {"reference_kind": None, "code_block": True}
    return None


def _collect(text: str, patterns: Iterable[tuple[str, re.Pattern[str]]]) -> list[Span]:
    """Non-overlapping matches, earliest first, longest at a tie."""
    found: list[tuple[int, int, str, re.Match[str]]] = []
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            found.append((match.start(), match.end(), kind, match))
    found.sort(key=lambda row: (row[0], -(row[1] - row[0])))

    spans: list[Span] = []
    cursor = 0
    for start, end, kind, match in found:
        if start < cursor:
            continue  # already inside an earlier, longer construct
        spans.append(
            Span(
                start,
                end,
                kind,
                IGNORED if kind in _MD_IGNORED_KINDS else MODELED,
                text[start:end],
                _markdown_facts(kind, match),
            )
        )
        cursor = end
    return spans


def _fill(text: str, spans: list[Span]) -> list[Span]:
    """Close every gap, so the span list is a partition of the source.

    Gap text is left **unclassified here**; the caller decides whether it
    reached the canonical state. That separation matters: a filler that marked
    its own gaps MODELED would report total coverage by construction.
    """
    filled: list[Span] = []
    cursor = 0
    for span in sorted(spans, key=lambda item: item.start):
        if span.start > cursor:
            body = text[cursor : span.start]
            filled.append(
                Span(
                    cursor,
                    span.start,
                    "blank" if _BLANK.match(body) else "prose",
                    IGNORED if _BLANK.match(body) else UNMODELED,
                    body,
                    None,
                )
            )
        filled.append(span)
        cursor = span.end
    if cursor < len(text):
        body = text[cursor:]
        filled.append(
            Span(
                cursor,
                len(text),
                "blank" if _BLANK.match(body) else "prose",
                IGNORED if _BLANK.match(body) else UNMODELED,
                body,
                None,
            )
        )
    return filled


def markdown_spans(text: str) -> list[Span]:
    return _fill(text, _collect(text, _MD_PATTERNS))


# --- html grammar ------------------------------------------------------------

#: Attributes that carry a reference. Everything reference-bearing must be here
#: or it is not captured at all, so the list is the contract.
_HTML_REFERENCE_ATTRS: dict[str, tuple[str, str]] = {
    "href": (HYPERLINK, "target"),
    "src": (IMAGE, "target"),
    "id": (ANCHOR, "identifier"),
    "name": (ANCHOR, "identifier"),
    "data-src": (INCLUDE, "target"),
    "cite": (HYPERLINK, "target"),
    "action": (HYPERLINK, "target"),
}

#: Presentation attributes declared non-semantic. An attribute in neither list
#: becomes an UNMODELED_SOURCE_FACT rather than being dropped.
_HTML_IGNORED_ATTRS = frozenset(
    {
        "style", "class", "width", "height", "align", "valign", "border",
        "cellpadding", "cellspacing", "colspan", "rowspan", "bgcolor", "color",
        "size", "face", "nowrap", "type", "start", "role", "aria-hidden",
        "aria-label", "alt", "title", "lang", "dir", "scope", "abbr", "span",
        "charset", "content", "http-equiv", "rel", "media", "target", "xmlns",
        "version", "viewbox", "d", "fill", "stroke", "transform", "points",
    }
)


class _HtmlScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events.append(("tag", (tag, attrs, self.getpos())))

    handle_startendtag = handle_starttag

    def handle_data(self, data: str) -> None:
        self.events.append(("text", (data, self.getpos())))

    def handle_comment(self, data: str) -> None:
        self.events.append(("comment", (data, self.getpos())))


def html_spans(text: str) -> list[Span]:
    """Event-level spans for HTML.

    Offsets are event ordinals rather than character positions: the standard
    library parser reports line and column, and reconstructing exact byte ranges
    from those across a 2 MB filing would add a second parser to be wrong in.
    The protocol declares this, and every share below is over events, not bytes.
    """
    scanner = _HtmlScanner()
    try:
        scanner.feed(text)
    except Exception:  # a malformed filing still yields the events seen so far
        pass

    spans: list[Span] = []
    for index, (event, payload) in enumerate(scanner.events):
        if event == "comment":
            spans.append(Span(index, index + 1, "html_comment", IGNORED, payload[0], None))
            continue
        if event == "text":
            body = payload[0]
            spans.append(
                Span(
                    index,
                    index + 1,
                    "blank" if _BLANK.match(body) else "text",
                    IGNORED if _BLANK.match(body) else MODELED,
                    body,
                    None,
                )
            )
            continue
        tag, attrs, _ = payload
        references = []
        unmodelled_attrs = []
        for name, value in attrs:
            lowered = (name or "").lower()
            if lowered in _HTML_REFERENCE_ATTRS and value:
                kind, field = _HTML_REFERENCE_ATTRS[lowered]
                references.append(
                    {"reference_kind": kind, field: value, "tag": tag, "attribute": lowered}
                )
            elif lowered in _HTML_IGNORED_ATTRS or not value:
                continue
            else:
                unmodelled_attrs.append({"tag": tag, "attribute": lowered, "value": value[:120]})
        if references:
            spans.append(
                Span(index, index + 1, "html_reference", MODELED, tag, {"references": references})
            )
        elif unmodelled_attrs:
            spans.append(
                Span(
                    index,
                    index + 1,
                    "html_unknown_attribute",
                    UNMODELED,
                    tag,
                    {"attributes": unmodelled_attrs},
                )
            )
        else:
            spans.append(Span(index, index + 1, "html_markup", IGNORED, tag, None))
    return spans


# --- canonical facts ---------------------------------------------------------


def reference_facts(spans: Iterable[Span]) -> list[dict[str, Any]]:
    """Every typed reference edge the grammar recognised, in source order."""
    facts: list[dict[str, Any]] = []
    for span in spans:
        if not span.fact:
            continue
        if "references" in span.fact:
            for reference in span.fact["references"]:
                facts.append({**reference, "span_start": span.start, "span_kind": span.kind})
            continue
        if span.fact.get("reference_kind"):
            facts.append({**span.fact, "span_start": span.start, "span_kind": span.kind})
    return facts


def coverage(spans: Iterable[Span]) -> dict[str, Any]:
    """Share of source in each classification.

    Units are characters for markdown and events for HTML; the caller records
    which, because a share whose denominator is unstated is not a measurement.
    """
    totals: dict[str, int] = {MODELED: 0, IGNORED: 0, UNMODELED: 0}
    by_kind: dict[str, int] = {}
    for span in spans:
        size = span.end - span.start
        totals[span.classification] = totals.get(span.classification, 0) + size
        by_kind[span.kind] = by_kind.get(span.kind, 0) + size
    total = sum(totals.values())
    return {
        "total": total,
        "by_classification": totals,
        "by_kind": dict(sorted(by_kind.items())),
        "modeled_share": (totals[MODELED] / total) if total else 0.0,
        "ignored_share": (totals[IGNORED] / total) if total else 0.0,
        "unmodeled_share": (totals[UNMODELED] / total) if total else 0.0,
        "source_coverage": ((totals[MODELED] + totals[IGNORED]) / total) if total else 0.0,
    }


def partition_holds(spans: list[Span], length: int) -> dict[str, Any]:
    """Whether the spans tile the source exactly: no gap, no overlap."""
    ordered = sorted(spans, key=lambda item: item.start)
    gaps: list[tuple[int, int]] = []
    overlaps: list[tuple[int, int]] = []
    cursor = 0
    for span in ordered:
        if span.start > cursor:
            gaps.append((cursor, span.start))
        elif span.start < cursor:
            overlaps.append((span.start, cursor))
        cursor = max(cursor, span.end)
    if cursor < length:
        gaps.append((cursor, length))
    return {
        "holds": not gaps and not overlaps,
        "gaps": gaps[:8],
        "overlaps": overlaps[:8],
        "gap_count": len(gaps),
        "overlap_count": len(overlaps),
        "covered_to": cursor,
        "length": length,
    }


# --- source coverage → canonical fact coverage -------------------------------

_WS = re.compile(r"\s+")
_ALNUM = re.compile(r"[^\W_]", re.UNICODE)

#: Residue of the markup itself once its construct has been recognised: list
#: bullets, table pipes, emphasis marks, punctuation between spans. Declared
#: non-semantic because the construct they belong to is already a fact.
_SYNTAX_ONLY = re.compile(r"\A[\s\W_]*\Z", re.UNICODE)


def _normalise(text: str) -> str:
    return _WS.sub(" ", text).strip()


_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


def _fold(text: str) -> str:
    """Alphanumeric projection, for the containment probe only.

    The canonicaliser strips emphasis marks, link syntax and HTML tags before it
    stores a unit's text, so raw prose and the unit built from it differ by
    punctuation. Comparing on alphanumerics alone survives that without this
    module having to re-implement -- and then drift from -- the canonicaliser's
    cleaning rules.

    It is a deliberately loose test. The direction of the looseness matters: it
    can only ever say a span *did* reach the canonical state, so the risk it
    carries is over-reporting coverage, and the protocol records that. Under a
    stricter probe the unmodeled share would be larger, never smaller.
    """
    return _NON_ALNUM.sub("", text).casefold()


def attribute_to_canonical(
    spans: list[Span], unit_texts: Iterable[str], fact_values: Iterable[str]
) -> dict[str, Any]:
    """Decide, per unclassified span, whether it reached the canonical state.

    This is the join the P0d chain turns on. ``_fill`` deliberately does not
    make this decision: a filler that marked its own gaps MODELED would report
    total coverage by construction, which is the failure mode the whole protocol
    is about.

    A span counts as modeled when its alphanumeric projection appears in some
    canonical unit's text or in some canonical fact's value. Containment rather
    than equality, because the canonicaliser joins adjacent source lines into
    one unit and an exact match would under-count real coverage.
    """
    haystack = _fold(" ".join(unit_texts))
    values = _fold(" ".join(str(value) for value in fact_values))

    reclassified = 0
    still_unmodeled: list[dict[str, Any]] = []
    for span in spans:
        if span.classification != UNMODELED or span.kind != "prose":
            continue
        body = _normalise(span.text)
        if not body or _SYNTAX_ONLY.match(body):
            span.kind = "syntax_residue"
            span.classification = IGNORED
            reclassified += 1
            continue
        probe = _fold(body)
        if probe and (probe in haystack or probe in values):
            span.classification = MODELED
            span.kind = "prose_in_unit"
            reclassified += 1
            continue
        still_unmodeled.append(
            {
                "start": span.start,
                "end": span.end,
                "length": span.end - span.start,
                "sample": body[:160],
                "has_alphanumeric": bool(_ALNUM.search(body)),
            }
        )

    return {
        "spans_reclassified": reclassified,
        "unmodeled_span_count": len(still_unmodeled),
        "unmodeled_spans": still_unmodeled[:24],
        "unmodeled_spans_truncated": max(0, len(still_unmodeled) - 24),
    }
