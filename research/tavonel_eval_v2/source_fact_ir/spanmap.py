"""Native provenance: a span-map built by construction, never by searching.

Founder ruling, 2026-08-23:

    Replace retrospective text-location with native provenance propagation.
    raw source span -> parsed node span -> canonical transformation span-map ->
    SourceFact/CanonicalAtom witness. Source witnesses must survive markup
    stripping, whitespace normalisation, entity decoding and block composition
    BY CONSTRUCTION, not by searching canonical text back inside raw bytes.

SFI1 failed because the previous design searched. `_locate` took a unit's
canonical text and looked for it in the raw payload with three tolerant
strategies. It worked 121,065 times and failed 1,284 times, and the failures were
not a tuning problem — they were a category error. The canonicaliser strips
markup, collapses whitespace, decodes entities and joins blocks, so by the time
the text exists there is nothing left to search for. Searching harder finds the
wrong bytes, and a provenance span that is wrong is worse than one that is
absent, because the absent one is visible.

The fix is to stop throwing the information away. The canonicaliser knows exactly
which bytes it is reading at the moment it emits each character. This module is
the ledger it writes that into.

    TrackedText   accumulates canonical text while recording, per emitted run,
                  the source byte range it came from.
    SpanMap       the immutable result: output offsets -> source byte offsets.
    compose       chains maps when a pipeline runs in stages (raw -> decoded ->
                  canonical), so a multi-stage transformation still answers in
                  raw source bytes.

The one invariant everything else rests on: **`to_source` never guesses.** A
region of output with no source — a separator inserted when two blocks are joined
— returns None rather than the span of a neighbour. An honest None is a
`RECOGNIZED_BUT_UNREPRESENTED` fact the study can count. A confident wrong answer
is a silent mis-attribution that nothing downstream can detect, which is the
failure this whole programme exists to make impossible.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass

#: How an output run relates to its source.
COPY = "copy"        # emitted verbatim from those bytes
REPLACE = "replace"  # emitted instead of those bytes (entity decode, whitespace collapse)
INSERT = "insert"    # emitted from nothing (a join separator); has NO source
KINDS = (COPY, REPLACE, INSERT)


@dataclass(frozen=True)
class Segment:
    """One contiguous run of output and the source bytes behind it.

    `source_start`/`source_end` are byte offsets into the ORIGINAL raw payload,
    always — never into a decoded string, never into an intermediate stage. A
    span that cannot be checked against the bytes on disk is a claim about the
    parser rather than about the source.
    """

    out_start: int
    out_end: int
    source_start: int
    source_end: int
    kind: str

    def __post_init__(self) -> None:
        if self.out_end < self.out_start:
            raise ValueError(f"output span is not a span: {self.out_start}..{self.out_end}")
        if self.kind not in KINDS:
            raise ValueError(f"unknown segment kind {self.kind!r}")
        if self.kind == INSERT:
            if (self.source_start, self.source_end) != (-1, -1):
                raise ValueError(
                    "an inserted run has no source. Giving it one would attribute "
                    "text the source never contained to bytes it did."
                )
        elif self.source_end < self.source_start:
            raise ValueError(
                f"source span is not a span: {self.source_start}..{self.source_end}"
            )

    @property
    def has_source(self) -> bool:
        return self.kind != INSERT

    def as_dict(self) -> dict[str, object]:
        return {
            "out_start": self.out_start,
            "out_end": self.out_end,
            "source_start": self.source_start if self.has_source else None,
            "source_end": self.source_end if self.has_source else None,
            "kind": self.kind,
        }


class SpanMap:
    """Output offsets to source byte offsets. Immutable, searchable in log time."""

    __slots__ = ("_length", "_segments", "_starts")

    def __init__(self, segments: Iterable[Segment]) -> None:
        ordered = tuple(sorted(segments, key=lambda item: (item.out_start, item.out_end)))
        previous = 0
        for segment in ordered:
            if segment.out_start < previous:
                raise ValueError(
                    "segments overlap in the output. Two sources for one character "
                    "means one of them is wrong and nothing says which."
                )
            previous = segment.out_end
        self._segments = ordered
        self._starts = [segment.out_start for segment in ordered]
        self._length = ordered[-1].out_end if ordered else 0

    def __len__(self) -> int:
        return self._length

    @property
    def segments(self) -> tuple[Segment, ...]:
        return self._segments

    def covering(self, out_start: int, out_end: int) -> tuple[Segment, ...]:
        """Every segment overlapping the half-open output range."""
        if out_end <= out_start:
            return ()
        index = max(bisect.bisect_right(self._starts, out_start) - 1, 0)
        found: list[Segment] = []
        for segment in self._segments[index:]:
            if segment.out_start >= out_end:
                break
            if segment.out_end > out_start:
                found.append(segment)
        return tuple(found)

    def to_source(self, out_start: int, out_end: int) -> tuple[int, int] | None:
        """The minimal source byte range behind an output range, or None.

        None means *this output has no source* — every segment behind it was
        inserted. It is never a shrug: the caller turns it into a fail-closed
        fact, and a fail-closed fact is countable in a way a wrong span is not.
        """
        sourced = [segment for segment in self.covering(out_start, out_end) if segment.has_source]
        if not sourced:
            return None
        return (
            min(segment.source_start for segment in sourced),
            max(segment.source_end for segment in sourced),
        )

    def is_fully_sourced(self, out_start: int, out_end: int) -> bool:
        """True when every character in the range came from somewhere.

        Distinct from `to_source` being non-None, and the distinction matters:
        a unit whose text is half inserted still has a source span, and calling
        that span its provenance would overstate what is known about it.
        """
        covered = self.covering(out_start, out_end)
        if not covered:
            return False
        cursor = out_start
        for segment in covered:
            if segment.out_start > cursor:
                return False  # a gap: output nothing claims to have produced
            if not segment.has_source:
                return False
            cursor = max(cursor, segment.out_end)
        return cursor >= out_end

    def compose(self, later: SpanMap) -> SpanMap:
        """Chain `self` (raw -> middle) with `later` (middle -> final).

        Used when canonicalisation runs in stages. Each final segment is split
        against whatever middle segments it covers, so the result maps final
        output straight to raw bytes and no stage's offsets survive into the
        answer.
        """
        composed: list[Segment] = []
        for segment in later.segments:
            if not segment.has_source:
                composed.append(segment)
                continue
            #: `segment.source_*` are offsets into the MIDDLE text, which is
            #: `self`'s output. Resolve them through self.
            for part in self.covering(segment.source_start, segment.source_end):
                if not part.has_source:
                    continue
                composed.append(
                    Segment(
                        out_start=segment.out_start,
                        out_end=segment.out_end,
                        source_start=part.source_start,
                        source_end=part.source_end,
                        kind=COPY if segment.kind == COPY and part.kind == COPY else REPLACE,
                    )
                )
        #: several middle parts can back one final run; merge them so the map
        #: stays non-overlapping in the output.
        merged: dict[tuple[int, int], list[Segment]] = {}
        for segment in composed:
            merged.setdefault((segment.out_start, segment.out_end), []).append(segment)
        flattened = [
            Segment(
                out_start=key[0],
                out_end=key[1],
                source_start=min(item.source_start for item in group)
                if group[0].has_source
                else -1,
                source_end=max(item.source_end for item in group) if group[0].has_source else -1,
                kind=group[0].kind if len({item.kind for item in group}) == 1 else REPLACE,
            )
            for key, group in sorted(merged.items())
        ]
        return SpanMap(flattened)

    def as_list(self) -> list[dict[str, object]]:
        return [segment.as_dict() for segment in self._segments]

    def unsourced_runs(self) -> tuple[tuple[int, int], ...]:
        """Output ranges with no source. Reported, so they can be counted."""
        return tuple(
            (segment.out_start, segment.out_end)
            for segment in self._segments
            if not segment.has_source
        )


class TrackedText:
    """Build canonical text and its provenance in one pass.

    A canonicaliser writes through this instead of concatenating strings. Every
    emission names the source bytes it came from, at the moment the emitter still
    knows them — which is the entire difference between this design and the one
    that failed.

    The API is deliberately small and has no `write(text)` without a source. To
    emit text from nothing you must call `insert`, and saying so is the point:
    the separator between two joined blocks genuinely has no source, and a
    canonicaliser that could add it silently would reintroduce the untraceable
    character by accident.
    """

    __slots__ = ("_length", "_parts", "_segments")

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._segments: list[Segment] = []
        self._length = 0

    def __len__(self) -> int:
        return self._length

    def _emit(self, text: str, source_start: int, source_end: int, kind: str) -> None:
        if not text:
            return
        self._parts.append(text)
        self._segments.append(
            Segment(
                out_start=self._length,
                out_end=self._length + len(text),
                source_start=source_start,
                source_end=source_end,
                kind=kind,
            )
        )
        self._length += len(text)

    def copy(self, text: str, source_start: int, source_end: int) -> None:
        """Text emitted verbatim from those bytes."""
        self._emit(text, source_start, source_end, COPY)

    def replace(self, text: str, source_start: int, source_end: int) -> None:
        """Text emitted INSTEAD of those bytes.

        Entity decoding (`&amp;` -> `&`), whitespace collapsing (a newline run ->
        one space), typographic folding. The output differs from the input and
        the provenance is exact anyway, which is what makes normalisation
        survivable.
        """
        self._emit(text, source_start, source_end, REPLACE)

    def insert(self, text: str) -> None:
        """Text from nothing. Block separators, and very little else."""
        self._emit(text, -1, -1, INSERT)

    def mark(self) -> int:
        """The current output offset, for bracketing a region as it is written."""
        return self._length

    @property
    def text(self) -> str:
        return "".join(self._parts)

    @property
    def map(self) -> SpanMap:
        return SpanMap(self._segments)

    def span_of(self, out_start: int, out_end: int) -> tuple[int, int] | None:
        return self.map.to_source(out_start, out_end)

    def source_span(self) -> tuple[int, int] | None:
        """The whole accumulated text's source range."""
        return self.map.to_source(0, self._length)


def verify(span_map: SpanMap, raw: bytes, text: str) -> dict[str, object]:
    """Check a map against the bytes it claims to describe.

    Not a formality. A map is only worth having if something can refuse it, and
    the failures worth catching are exactly the ones a searching implementation
    produced silently: a span past the end of the payload, a COPY segment whose
    bytes do not decode to the text it claims, output no segment accounts for.
    """
    problems: list[dict[str, object]] = []
    covered = 0
    for segment in span_map.segments:
        covered += segment.out_end - segment.out_start
        if not segment.has_source:
            continue
        if segment.source_end > len(raw) or segment.source_start < 0:
            problems.append(
                {"segment": segment.as_dict(), "why": "source span outside the payload"}
            )
            continue
        if segment.kind != COPY:
            continue
        emitted = text[segment.out_start : segment.out_end]
        actual = raw[segment.source_start : segment.source_end].decode("utf-8", "replace")
        if emitted != actual:
            problems.append(
                {
                    "segment": segment.as_dict(),
                    "why": "a copy segment's bytes do not decode to the text it claims",
                    "emitted": emitted[:60],
                    "found": actual[:60],
                }
            )
    return {
        "segments": len(span_map.segments),
        "output_length": len(text),
        "output_covered": covered,
        "fully_covered": covered == len(text),
        "unsourced_runs": len(span_map.unsourced_runs()),
        "problems": problems,
        "ok": not problems and covered == len(text),
    }
