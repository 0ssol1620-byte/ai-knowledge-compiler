"""The canonical document of protocol section 3, with provenance built in.

Founder ruling, 2026-08-23:

    Do not iterate _locate heuristics. Replace retrospective text-location with
    native provenance propagation. Implement provenance as: raw source span ->
    parsed node span -> canonical transformation span-map -> SourceFact/
    CanonicalAtom witness. Source witnesses must survive markup stripping,
    whitespace normalisation, entity decoding and block composition BY
    CONSTRUCTION, not by searching canonical text back inside raw bytes.

`canonical_document` built the text first and then asked where it came from.
SFI1 returned 1,284 units whose text could not be found in the raw payload, and
that is not a tuning failure: after markup is stripped, whitespace collapsed,
entities decoded and blocks joined, the canonical text no longer occurs in the
source at all. A tolerant search does not recover the answer, it invents one,
and an invented span is worse than a missing one because nothing downstream can
tell it apart from a real one.

This module keeps the information instead of reconstructing it. Every character
of canonical text is emitted together with the raw byte range it came from, at
the moment the emitter still knows it. The carrier is `Trace`: canonical text
plus one origin per character, in ORIGINAL PAYLOAD BYTE OFFSETS at every stage —
never offsets into the decoded str, never into an intermediate rewrite. Traces
are then handed to `spanmap.TrackedText` as `copy` / `replace` / `insert` runs,
and the resulting `SpanMap` is checked against the payload by `spanmap.verify`
before it is allowed into the output.

Coordinates, because this is the failure mode that hides:

  * `_decode` is the ONLY place a byte offset is minted. It walks the payload
    and gives each decoded character the byte range that produced it, so a CJK
    character carries three bytes and an emoji four.
  * Every later stage slices, drops or replaces characters and carries their
    existing origins along. No stage ever re-derives an offset from a string
    index, because a string index is in the wrong coordinate space by
    construction.
  * The HTML reader is the one component that receives positions from somebody
    else (`HTMLParser.getpos()`). Those are char positions into the decoded text
    and are converted through a '\\n'-only line table — matching what
    `HTMLParser.updatepos` counts — then resolved against the decoded trace.
    Every such position is checked against the text it claims to describe, and a
    mismatch is counted in `provenance.parser_position_anomalies` rather than
    trusted.

`insert` is the only unsourced path. It is used in exactly one place: the single
space `assemble` puts between two blocks folded under the same heading. That
space genuinely has no source, so a unit built from more than one block reports
`fully_sourced: False`. That number is not chased. It is reported.

Segmentation is the legacy module's, deliberately: a canonicaliser that splits
differently is a different study, not a provenance upgrade. See `DIVERGENCES`
for the three implementation differences and why each is text-equivalent, and
`OBSERVABLE_DIVERGENCES` for cases where the output is known to differ — it is
empty, and `tests/test_provenance_document.py` fails if any output difference
appears that is not listed there.
"""

from __future__ import annotations

import codecs
import hashlib
import html
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

_NAMESPACE_ROOT = Path(__file__).resolve().parents[1]
_SPANMAP_DIR = str(_NAMESPACE_ROOT / "source_fact_ir")
if _SPANMAP_DIR not in sys.path:
    sys.path.insert(0, _SPANMAP_DIR)

from spanmap import COPY, INSERT, REPLACE, SpanMap, TrackedText, verify  # noqa: E402

#: Implementation differences from `canonical_document`. Each one exists because
#: provenance needs information the legacy path throws away, and each is
#: text-equivalent — the reasoning is recorded here so a reviewer can attack it,
#: and `tests/test_provenance_document.py` checks the equivalence on fixtures.
DIVERGENCES: tuple[str, ...] = (
    "html-convert-charrefs-off: the EDGAR reader runs HTMLParser with "
    "convert_charrefs=False so each character reference reports its own span. "
    "Each reference is then decoded with html.unescape over its exact raw text, "
    "which is what convert_charrefs=True does to the enclosing data chunk, and "
    "the second unescape that legacy `normalise` performs is preserved, so "
    "double-decoded input such as '&amp;amp;' still yields '&'.",
    "markdown-line-terminators: body lines keep their own terminator instead of "
    "being re-joined with a synthesised '\\n'. The synthesised newline has no "
    "source; the real terminator has one. Both are whitespace runs that "
    "`normalise` collapses to a single space, so the canonical text is "
    "unchanged.",
    "local-charref-pattern: entity decoding is driven by a local copy of "
    "CPython's html._charref pattern so that each reference's extent is known. "
    "The replacement itself is still computed by html.unescape. If a future "
    "CPython changed that pattern, the match set could drift.",
)

#: Fixture/document identifiers whose canonical output legitimately differs from
#: `canonical_document`. Empty on purpose: there is no known case. A difference
#: that is not listed here is a bug, and the test suite treats it as one.
OBSERVABLE_DIVERGENCES: frozenset[str] = frozenset()

SPACE = re.compile(r"\s+")
ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
FRONT_MATTER = re.compile(r"^---\s*$")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MD_EMPH = re.compile(r"(\*\*|\*|__|_|`)")
SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)
HTML_TAG = re.compile(r"<[^>]+>")
SEC_ITEM = re.compile(r"^item\s+\d+[a-z]?\s*[.:]?", re.IGNORECASE)
SEC_PART = re.compile(r"^part\s+[ivx]+\s*[.:]?", re.IGNORECASE)

#: A verbatim copy of CPython's `html._charref`. Copied rather than imported
#: because it is private, and needed rather than inferred because `html.unescape`
#: does not report where it substituted.
CHARREF = re.compile(r"&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)")

MIN_TEXT_CHARS = 120
EXCLUDED_HEADINGS = frozenset(
    {"references", "external links", "see also", "further reading", "notes"}
)

SCHEMA = "tavonel.v2.canonical_document.v1"
PROVENANCE_SCHEMA = "tavonel.v2.native_provenance.v1"

#: One character's origin: (source_start, source_end, kind). An inserted
#: character carries (-1, -1, INSERT) and `spanmap.Segment` refuses to give it a
#: source, which is the point.
Origin = tuple[int, int, str]
UNSOURCED: Origin = (-1, -1, INSERT)


def sha_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Trace:
    """Canonical text plus, per character, the raw bytes behind it.

    Deliberately per-character rather than per-run: a run-based carrier has to
    decide how to split a run every time a transformation cuts through one, and
    that decision is where an off-by-one becomes a plausible-looking wrong span.
    Runs are re-formed once, at emission, and only where the bytes are actually
    contiguous.
    """

    text: str
    origins: tuple[Origin, ...]

    def __post_init__(self) -> None:
        if len(self.text) != len(self.origins):
            raise ValueError(
                f"trace has {len(self.text)} characters but {len(self.origins)} "
                "origins; a character without an origin is exactly the gap this "
                "module exists to close"
            )

    def __len__(self) -> int:
        return len(self.text)

    def slice(self, start: int, stop: int) -> Trace:
        return Trace(self.text[start:stop], self.origins[start:stop])


EMPTY = Trace("", ())
Builder = Callable[[Trace, "re.Match[str]"], Trace]


def _union(origins: Sequence[Origin]) -> tuple[int, int] | None:
    """The minimal byte range behind a group of characters, or None."""
    sourced = [origin for origin in origins if origin[2] != INSERT]
    if not sourced:
        return None
    return (
        min(origin[0] for origin in sourced),
        max(origin[1] for origin in sourced),
    )


def _concat(parts: Iterable[Trace]) -> Trace:
    materialised = [part for part in parts if part.text]
    if not materialised:
        return EMPTY
    if len(materialised) == 1:
        return materialised[0]
    text: list[str] = []
    origins: list[Origin] = []
    for part in materialised:
        text.append(part.text)
        origins.extend(part.origins)
    return Trace("".join(text), tuple(origins))


def _inserted(text: str) -> Trace:
    return Trace(text, tuple(UNSOURCED for _ in text))


# --------------------------------------------------------------------------- #
# Stage 0 — bytes to characters. The only place a byte offset is minted.
# --------------------------------------------------------------------------- #


def _decode(payload: bytes) -> tuple[Trace, int]:
    """Decode the payload, giving every character its own byte range.

    Returns the trace and the number of characters that are U+FFFD replacements
    rather than real source characters. The legacy reader decodes with
    errors="replace" and this one must agree with it byte for byte, so the
    malformed case is handled rather than refused — but it is counted, because a
    replacement character has no faithful source and saying so is cheap.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return _decode_incrementally(payload)
    origins: list[Origin] = []
    cursor = 0
    for character in text:
        width = 1 if character.isascii() else len(character.encode("utf-8"))
        origins.append((cursor, cursor + width, COPY))
        cursor += width
    return Trace(text, tuple(origins)), 0


def _decode_incrementally(payload: bytes) -> tuple[Trace, int]:
    """Byte-at-a-time decode, for payloads that are not valid UTF-8.

    An incremental decoder emits a character only when its byte sequence
    completes, so the bytes fed since the last emission are exactly the bytes
    behind it. Anything that does not round-trip is REPLACE, never COPY, so
    `spanmap.verify` is never asked to accept a span whose bytes do not decode
    to the text it claims.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    characters: list[str] = []
    origins: list[Origin] = []
    replacements = 0
    pending = 0
    for position in range(len(payload)):
        produced = decoder.decode(payload[position : position + 1])
        if not produced:
            continue
        low, high = pending, position + 1
        pending = high
        #: strict, deliberately. Under errors="replace" a bad byte round-trips to
        #: the same U+FFFD it produced, so a lenient comparison would call the
        #: replacement character a faithful COPY of the byte it stands in for.
        try:
            exact = len(produced) == 1 and payload[low:high].decode("utf-8") == produced
        except UnicodeDecodeError:
            exact = False
        kind = COPY if exact else REPLACE
        if not exact:
            replacements += len(produced)
        for character in produced:
            characters.append(character)
            origins.append((low, high, kind))
    for character in decoder.decode(b"", final=True):
        characters.append(character)
        origins.append((pending, len(payload), REPLACE))
        replacements += 1
    return Trace("".join(characters), tuple(origins)), replacements


# --------------------------------------------------------------------------- #
# Stage 1 — transformations. Each keeps the origins it did not consume.
# --------------------------------------------------------------------------- #


def _rewrite(trace: Trace, pattern: re.Pattern[str], build: Builder) -> Trace:
    """Apply `pattern` to a trace, letting `build` decide what each match emits.

    `pattern.finditer` scans the CANONICAL-SO-FAR text, never the raw payload,
    and never to locate canonical text — it locates markup that is about to be
    removed. The distinction is the whole difference from `_locate`.
    """
    pieces: list[Trace] = []
    cursor = 0
    for match in pattern.finditer(trace.text):
        start, stop = match.span()
        if stop == start:
            continue
        pieces.append(trace.slice(cursor, start))
        pieces.append(build(trace, match))
        cursor = stop
    if not pieces:
        return trace
    pieces.append(trace.slice(cursor, len(trace)))
    return _concat(pieces)


def _drop(_trace: Trace, _match: re.Match[str]) -> Trace:
    """Emit nothing. The markup is simply not part of the canonical text."""
    return EMPTY


def _keep_first_group(trace: Trace, match: re.Match[str]) -> Trace:
    """Emit the link's label, carrying the label's own bytes with it."""
    start, stop = match.span(1)
    if start < 0:
        return EMPTY
    return trace.slice(start, stop)


def _single_space(trace: Trace, match: re.Match[str]) -> Trace:
    """One space instead of the matched run, sourced to the whole run."""
    start, stop = match.span()
    origins = trace.origins[start:stop]
    if len(origins) == 1 and trace.text[start] == " " and origins[0][2] == COPY:
        #: Already exactly one space from exactly those bytes. Keeping it a COPY
        #: keeps `verify` able to check it against the payload.
        return trace.slice(start, stop)
    bounds = _union(origins)
    if bounds is None:
        return _inserted(" ")
    return Trace(" ", ((bounds[0], bounds[1], REPLACE),))


def _decoded_charref(trace: Trace, match: re.Match[str]) -> Trace:
    """Decode one character reference, sourced to the reference's own bytes."""
    start, stop = match.span()
    raw = match.group(0)
    replacement = html.unescape(raw)
    if replacement == raw:
        #: `html.unescape` leaves unknown references alone, so nothing was
        #: transformed and the characters keep their own COPY origins.
        return trace.slice(start, stop)
    bounds = _union(trace.origins[start:stop])
    if bounds is None:
        return _inserted(replacement)
    return Trace(replacement, tuple((bounds[0], bounds[1], REPLACE) for _ in replacement))


def _unescape(trace: Trace) -> Trace:
    if "&" not in trace.text:
        return trace
    return _rewrite(trace, CHARREF, _decoded_charref)


def _collapse(trace: Trace) -> Trace:
    return _rewrite(trace, SPACE, _single_space)


def _strip(trace: Trace) -> Trace:
    start = 0
    stop = len(trace)
    while start < stop and trace.text[start].isspace():
        start += 1
    while stop > start and trace.text[stop - 1].isspace():
        stop -= 1
    if start == 0 and stop == len(trace):
        return trace
    return trace.slice(start, stop)


def normalise(trace: Trace) -> Trace:
    """`canonical_document.normalise`, with the origins kept.

    Order matters and is the legacy order: unescape first, because decoding can
    produce whitespace (`&#32;`, `&nbsp;`) that the collapse must then see.
    """
    return _strip(_collapse(_unescape(trace)))


def clean_markdown(trace: Trace) -> Trace:
    """`canonical_document.clean_markdown`, with the origins kept."""
    value = _rewrite(trace, MD_LINK, _keep_first_group)
    value = _rewrite(value, HTML_TAG, _single_space)
    value = _rewrite(value, MD_EMPH, _drop)
    return normalise(value)


# --------------------------------------------------------------------------- #
# Stage 2 — emission. Characters become runs, runs become a SpanMap.
# --------------------------------------------------------------------------- #


def to_tracked_text(trace: Trace) -> TrackedText:
    """Fold a trace into `TrackedText` runs.

    Adjacent characters merge only when their bytes are actually contiguous (or,
    for a replacement, when they came from the very same reference). A merge
    across a gap would produce a span that covers bytes the text never contained
    — a plausible span that is wrong, which is the thing being eliminated.
    """
    tracked = TrackedText()
    index = 0
    total = len(trace)
    while index < total:
        start, end, kind = trace.origins[index]
        stop = index + 1
        while stop < total:
            following = trace.origins[stop]
            previous = trace.origins[stop - 1]
            if following[2] != kind:
                break
            if kind == INSERT:
                stop += 1
                continue
            if following[0] == previous[1] or (kind == REPLACE and following == previous):
                end = max(end, following[1])
                stop += 1
                continue
            break
        chunk = trace.text[index:stop]
        if kind == COPY:
            tracked.copy(chunk, start, end)
        elif kind == REPLACE:
            tracked.replace(chunk, start, end)
        else:
            tracked.insert(chunk)
        index = stop
    return tracked


# --------------------------------------------------------------------------- #
# Readers. Same segmentation decisions as the legacy module.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TracedSection:
    path: tuple[str, ...]
    heading: str
    trace: Trace

    @property
    def text(self) -> str:
        return self.trace.text


def _line_starts(text: str) -> list[int]:
    """Char offset of each line start, counting '\\n' only.

    `HTMLParser.updatepos` counts newlines with `str.count('\\n')`, so a lone
    '\\r' does not start a line as far as `getpos()` is concerned. Matching that
    exactly is the difference between a correct offset and a believable one.
    """
    starts = [0]
    for index, character in enumerate(text):
        if character == "\n":
            starts.append(index + 1)
    return starts


class ProvenanceHtmlReader(HTMLParser):
    """`canonical_document.SecHtmlReader`, emitting traces instead of strings.

    EDGAR filings rarely use ``h1``-``h6``. Their structure is carried by the
    ``Item N.`` and ``Part N`` captions the forms mandate, so those are treated
    as headings when a block element contains one and little else. That rule is
    a property of the form, not of any particular filing, and it is reproduced
    here unchanged.
    """

    SKIP: ClassVar[frozenset[str]] = frozenset({"script", "style", "head", "title"})
    BLOCK: ClassVar[frozenset[str]] = frozenset(
        {"p", "div", "tr", "li", "br", "table", "h1", "h2", "h3", "h4", "h5", "h6", "td"}
    )

    def __init__(self, base: Trace) -> None:
        super().__init__(convert_charrefs=False)
        self._base = base
        self._line_starts = _line_starts(base.text)
        self.blocks: list[tuple[str | None, Trace]] = []
        self.anomalies = 0
        self._buffer: list[Trace] = []
        self._skip_depth = 0
        self._heading_level: int | None = None

    def _offset(self) -> int:
        lineno, column = self.getpos()
        if lineno < 1 or lineno > len(self._line_starts):
            return -1
        return self._line_starts[lineno - 1] + column

    def _take(self, start: int, stop: int, expected: str) -> Trace:
        """Slice the decoded trace at a parser-reported position, checked.

        The parser is the only component here that hands us a position we did
        not compute, so it is the only one that can be silently wrong. If the
        bytes at that position do not spell what the parser said it found, the
        text is emitted as unsourced and the disagreement is counted, because a
        counted anomaly is recoverable and a trusted one is not.
        """
        if 0 <= start <= stop <= len(self._base) and self._base.text[start:stop] == expected:
            return self._base.slice(start, stop)
        self.anomalies += 1
        return _inserted(expected)

    def _flush(self) -> None:
        trace = normalise(_concat(self._buffer))
        self._buffer = []
        if not trace.text:
            self._heading_level = None
            return
        level = self._heading_level
        if level is None and len(trace.text) <= 120:
            if SEC_PART.match(trace.text):
                level = 1
            elif SEC_ITEM.match(trace.text):
                level = 2
        self.blocks.append((str(level) if level else None, trace))
        self._heading_level = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if tag in self.BLOCK:
            self._flush()
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self._heading_level = int(tag[1])

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        start = self._offset()
        self._buffer.append(self._take(start, start + len(data), data))

    def _reference(self, prefix: str, name: str) -> None:
        """Emit one character reference, sourced to the reference's own bytes.

        `getpos()` gives the '&'. The extent is the prefix plus the name plus a
        semicolon when one is actually there — HTMLParser accepts a reference
        without one and consumes one character less, so the terminator is read
        from the text rather than assumed.
        """
        start = self._offset()
        stop = start + len(prefix) + len(name)
        if start < 0 or self._base.text[start:stop] != prefix + name:
            #: The parser told us where it found a reference and the text there
            #: is not that reference. Nothing sound can be said about the span.
            self.anomalies += 1
            self._buffer.append(_inserted(html.unescape(prefix + name + ";")))
            return
        if self._base.text[stop : stop + 1] == ";":
            stop += 1
        raw = self._base.text[start:stop]
        source = self._take(start, stop, raw)
        decoded = html.unescape(raw)
        if decoded == raw:
            self._buffer.append(source)
            return
        bounds = _union(source.origins)
        if bounds is None:
            self._buffer.append(_inserted(decoded))
            return
        self._buffer.append(
            Trace(decoded, tuple((bounds[0], bounds[1], REPLACE) for _ in decoded))
        )

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._reference("&", name)

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._reference("&#", name)

    def close(self) -> None:
        super().close()
        self._flush()


def blocks_from_html(base: Trace) -> tuple[list[tuple[str | None, Trace]], int]:
    reader = ProvenanceHtmlReader(base)
    reader.feed(base.text)
    reader.close()
    return reader.blocks, reader.anomalies


def _split_lines(base: Trace) -> list[tuple[Trace, Trace]]:
    """Lines as (bare, with terminator) traces.

    `str.splitlines` splits on more than '\\n', so its own output decides the
    boundaries rather than a hand-rolled scan. Offsets come from cumulative
    lengths, which is arithmetic on text this function already holds — not a
    lookup of one string inside another.
    """
    lines: list[tuple[Trace, Trace]] = []
    cursor = 0
    for piece in base.text.splitlines(keepends=True):
        whole = base.slice(cursor, cursor + len(piece))
        bare_pieces = piece.splitlines()
        bare_length = len(bare_pieces[0]) if bare_pieces else 0
        lines.append((base.slice(cursor, cursor + bare_length), whole))
        cursor += len(piece)
    return lines


def blocks_from_markdown(base: Trace) -> list[tuple[str | None, Trace]]:
    base = _rewrite(base, SHORTCODE, _single_space)
    blocks: list[tuple[str | None, Trace]] = []
    body: list[Trace] = []
    in_fence = False
    in_front_matter = False
    for index, (bare, whole) in enumerate(_split_lines(base)):
        line = bare.text
        if FRONT_MATTER.match(line) and (index == 0 or in_front_matter):
            in_front_matter = not in_front_matter
            continue
        if in_front_matter:
            continue
        if FENCE.match(line):
            in_fence = not in_fence
            body.append(whole)
            continue
        match = None if in_fence else ATX.match(line)
        if match is None:
            body.append(whole)
            continue
        joined = clean_markdown(_concat(body))
        if joined.text:
            blocks.append((None, joined))
        body = []
        start, stop = match.span(2)
        blocks.append((str(len(match.group(1))), clean_markdown(bare.slice(start, stop))))
    joined = clean_markdown(_concat(body))
    if joined.text:
        blocks.append((None, joined))
    return blocks


def assemble(blocks: list[tuple[str | None, Trace]]) -> list[TracedSection]:
    """Fold a flat heading/body stream into a heading-path section list.

    The join between two blocks is the one `insert` in this module. It is a
    space that the source does not contain anywhere, and `TrackedText` has no
    way to give it a source on purpose, which is why the unsourced character
    cannot creep back in by accident.
    """
    stack: list[tuple[int, str]] = []
    sections: list[TracedSection] = []
    heading = "lead"
    body: list[Trace] = []

    def flush() -> None:
        joined: list[Trace] = []
        for position, part in enumerate(body):
            if position:
                joined.append(_inserted(" "))
            joined.append(part)
        trace = normalise(_concat(joined))
        if len(trace.text) < MIN_TEXT_CHARS:
            return
        if heading.casefold() in EXCLUDED_HEADINGS:
            return
        path = tuple(name for _, name in stack) or (heading,)
        sections.append(TracedSection(path=path, heading=heading, trace=trace))

    for raw_level, trace in blocks:
        if raw_level is None:
            body.append(trace)
            continue
        flush()
        body = []
        level = int(raw_level)
        heading = trace.text or "untitled"
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
    flush()
    return sections


# --------------------------------------------------------------------------- #
# The document.
# --------------------------------------------------------------------------- #


def _unit_provenance(trace: Trace, payload: bytes) -> tuple[SpanMap, dict[str, Any]]:
    """Emit a unit's span-map and check it before anybody is allowed to use it.

    A map that `verify` rejects is withheld entirely: the unit reports no source
    span at all. Publishing a span the module's own checker refuses would be the
    same mistake as `_locate`, made one layer further in.
    """
    tracked = to_tracked_text(trace)
    span_map = tracked.map
    report = verify(span_map, payload, trace.text)
    if not report["ok"]:
        return span_map, {
            "source_span": None,
            "fully_sourced": False,
            "verified": False,
            "problems": report["problems"],
        }
    bounds = span_map.to_source(0, len(trace.text))
    return span_map, {
        "source_span": list(bounds) if bounds else None,
        "fully_sourced": span_map.is_fully_sourced(0, len(trace.text)),
        "verified": True,
        "problems": [],
    }


def provenance_document(
    *,
    source_family: str,
    source_id: str,
    version_id: str,
    payload: bytes,
    source_digest: str,
    known_at: str | None,
    valid_from: str | None,
    licence: str,
) -> dict[str, Any]:
    """The canonical document of section 3, plus a witness for every unit.

    Shape-compatible with `canonical_document`: everything it emits is emitted
    here under the same keys, so an existing consumer keeps working. The
    additions are per-unit `source_span`, `fully_sourced` and `span_map`, and a
    document-level `provenance` block carrying the totals — including the ones
    that are unflattering.
    """
    base, decode_replacements = _decode(payload)
    if source_family == "sec_edgar":
        blocks, anomalies = blocks_from_html(base)
    else:
        blocks, anomalies = blocks_from_markdown(base), 0
    sections = assemble(blocks)

    seen: dict[tuple[str, ...], int] = {}
    units: list[dict[str, Any]] = []
    fully_sourced = 0
    with_span = 0
    failed = []
    segments = 0
    inserted_runs = 0
    for ordinal, section in enumerate(sections):
        count = seen.get(section.path, 0)
        seen[section.path] = count + 1
        explicit = list(section.path)
        if count:
            explicit[-1] = explicit[-1] + "#" + str(count)
        span_map, witness = _unit_provenance(section.trace, payload)
        segments += len(span_map.segments)
        inserted_runs += len(span_map.unsourced_runs())
        if witness["fully_sourced"]:
            fully_sourced += 1
        if witness["source_span"] is not None:
            with_span += 1
        if not witness["verified"]:
            failed.append({"ordinal": ordinal, "problems": witness["problems"]})
        units.append(
            {
                "explicit_path": explicit,
                "heading": section.heading,
                "ordinal": ordinal,
                "text": section.text,
                "text_sha256": sha_text(section.text),
                "source_span": witness["source_span"],
                "fully_sourced": witness["fully_sourced"],
                "span_map": span_map.as_list(),
            }
        )

    return {
        "schema": SCHEMA,
        "source_family": source_family,
        "source_id": source_id,
        "version_id": version_id,
        "version_time": {"valid_from": valid_from, "known_at": known_at},
        "source_digest": source_digest,
        "license": licence,
        "units": units,
        "structure": {
            "order": ["/".join(unit["explicit_path"]) for unit in units],
            "block_count": len(units),
        },
        "provenance": {
            "schema": PROVENANCE_SCHEMA,
            "payload_bytes": len(payload),
            "units": len(units),
            "units_with_source_span": with_span,
            "units_fully_sourced": fully_sourced,
            "units_failed_verification": len(failed),
            "verification_failures": failed,
            "segments": segments,
            "inserted_runs": inserted_runs,
            "decode_replacements": decode_replacements,
            "parser_position_anomalies": anomalies,
            "divergences": list(DIVERGENCES),
            "observable_divergences": sorted(OBSERVABLE_DIVERGENCES),
        },
    }
