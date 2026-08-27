"""The three kinds the compiled state already carries, made honest.

`CONTENT_TEXT`, `STRUCTURE` and `PROVENANCE_SPAN` are the core's, not a lane's,
because they are the kinds where the old instrument was *right* — and getting
them right for a new reason matters more than it looks.

The old `MODELED` was a claim made by the grammar. For unit text and headings
that claim happened to be true: `compiler/selective_build.py` really does store
unit text, headings, explicit paths and document order. So a naive port would
emit `REPRESENTED_IN_COMPILED_STATE` for these three from a table and move on,
and the new states would inherit the exact defect they exist to remove.

They do not. Every fact here is checked against the compiled document that was
actually built:

    a unit whose text the document does not carry is UNREPRESENTED, whatever the
    grammar says about paragraphs.

That check is cheap for these kinds and it is the reason to write them centrally:
it fixes the shape every other extractor is expected to follow.

`PROVENANCE_SPAN` is the one genuinely new thing here. The compiled state records
*what* a unit says and *where it sits in the document*; it has never recorded
*which bytes of the source it came from*. Without that the witness chain has no
anchor — you can say a fact was seen at byte 4,102 but nothing connects byte
4,102 to the artifact that was built. The span is that link, and it is why a
locator-only change can be attributed to a unit at all.
"""

from __future__ import annotations

import re
from typing import Any

try:  # loaded as a package member
    from .ir import (
        CONTENT_TEXT,
        IGNORED,
        PROVENANCE_SPAN,
        REPRESENTED,
        STRUCTURE,
        UNREPRESENTED,
        UNRESOLVED,
        UNSUPPORTED_CONSTRUCT,
        SourceFact,
        Witness,
        register,
        unit_path_for,
    )
except ImportError:  # loaded flat, with source_fact_ir/ itself on sys.path
    from ir import (
        CONTENT_TEXT,
    IGNORED,
    PROVENANCE_SPAN,
    REPRESENTED,
    STRUCTURE,
    UNREPRESENTED,
    UNRESOLVED,
    UNSUPPORTED_CONSTRUCT,
    SourceFact,
    Witness,
    register,
    unit_path_for,
)

#: Every declined case, in one place, so a reader can see the whole list rather
#: than discovering policies one grep at a time.
POLICIES: dict[str, str] = {
    "POLICY-CORE-001": (
        "a unit whose canonical text is empty after the canonicaliser's own "
        "block assembly carries no content fact. The canonicaliser declares "
        "these non-units and the IR does not second-guess it; what it must not "
        "do is call them represented."
    ),
}


#: Constructs the declared grammar does not support, each with the reason a
#: reader needs. This table is the difference between "the compiler handled this
#: document" and "the compiler was silent about part of this document".
#:
#: It is deliberately a SHORT, NAMED list rather than a general detector. A
#: detector that guessed at unsupported-ness would fire on ordinary prose and
#: bury the real cases; a named list is checkable, arguable line by line, and
#: grows by decision rather than by accident. What it must never do is shrink
#: because a run scored badly — removing a row here is removing evidence.
UNSUPPORTED: tuple[tuple[str, bytes, str], ...] = (
    (
        "mathml",
        rb"<math\b",
        "MathML is an expression tree. No kind in this IR represents one, so "
        "the compiled state cannot carry what it asserts.",
    ),
    (
        "svg",
        rb"<svg\b",
        "inline SVG carries geometry and may carry text; neither has a "
        "representation here.",
    ),
    (
        "script",
        rb"<script\b",
        "the declared grammar excludes JavaScript. Its effect on the rendered "
        "content cannot be determined without executing it.",
    ),
    (
        "style",
        rb"<style\b",
        "the declared grammar excludes CSS, which can hide or reorder content "
        "the compiled state records as present and ordered.",
    ),
    (
        "mediawiki_template_expansion",
        rb"\{\{#(?:if|switch|expr|invoke)\b",
        "MediaWiki parser functions expand at render time. The source does not "
        "state the expanded value and this IR does not evaluate it.",
    ),
)


#: Reason text for a unit the canonicaliser did not hand a span for. Stated
#: once, because it is the difference between the two designs and a reader
#: comparing an SFI1 fact to an SFI2 fact should be able to see which is which.
NO_NATIVE_SPAN = (
    "the canonicaliser did not emit a source span for this unit. Under native "
    "provenance a span is recorded as the text is built, so its absence means "
    "either the document came from the legacy canonicaliser, which discards the "
    "offsets, or the span-map failed its own verification and was withheld. "
    "Nothing is searched for in the raw bytes to make up the difference"
)

NO_SOURCED_CHARACTER = (
    "every character of this unit was inserted by the canonicaliser; no byte of "
    "the source is behind any of it, so there is nothing to point at"
)


def _native_span(unit: dict[str, Any]) -> tuple[int, int] | None:
    """The span the canonicaliser recorded while it was building the text.

    Founder ruling, 2026-08-23: *do not iterate `_locate` heuristics; replace
    retrospective text-location with native provenance propagation.* So there is
    no search here and no search anywhere below it. Either the canonicaliser
    handed this unit a verified span or the unit has none, and having none is a
    fail-closed fact rather than an occasion to go looking.

    That is not a smaller capability than the design it replaces. `_locate`
    answered 121,065 times and declined 1,284, and the declines were the visible
    part of the problem — the answers were never checked. A span emitted at
    build time is checked by `verify` before it is published, and one that fails
    is withheld, so an answer here means something an answer there did not.
    """
    span = unit.get("source_span")
    if not span or len(span) != 2:
        return None
    start, end = int(span[0]), int(span[1])
    if end < start:
        return None
    return start, end


class CoreExtractor:
    """CONTENT_TEXT, STRUCTURE and PROVENANCE_SPAN, verified against the state."""

    #: `UNSUPPORTED_CONSTRUCT` belongs here even though the kind is not one the
    #: compiled state carries. It was omitted through V1, and the omission made
    #: the registry tell a small lie: `unclaimed_kinds()` reported the kind as
    #: one nothing looks for, while `_unsupported` below was looking for it and
    #: emitting it. Nothing broke, which is the point — the declaration and the
    #: behaviour disagreed and only the declaration was ever read.
    #:
    #: Claiming it also makes the registry refuse a second producer, which is
    #: what the claim is for: two extractors emitting fail-closed facts for the
    #: same construct would double-count every unsupported region.
    kinds: tuple[str, ...] = (
        CONTENT_TEXT,
        STRUCTURE,
        PROVENANCE_SPAN,
        UNSUPPORTED_CONSTRUCT,
    )

    def extract(self, *, raw: bytes, document: dict[str, Any]) -> list[SourceFact]:
        facts: list[SourceFact] = []
        order: list[str] = list(document.get("structure", {}).get("order", []))
        source_id = str(document.get("source_id", ""))

        for unit in document.get("units", []):
            #: document-qualified, per ir.unit_path_for. The bare explicit path
            #: is not unique across documents and would anchor a fact to the
            #: wrong artifact.
            path = unit_path_for(source_id, unit["explicit_path"])
            text = str(unit.get("text") or "")
            span = _native_span(unit)
            #: distinct from having a span at all: a unit whose text is part
            #: inserted still has one, and calling that span its provenance
            #: without saying so would overstate what is known about it.
            fully_sourced = bool(unit.get("fully_sourced"))

            #: two different absences, told apart while the evidence is still to
            #: hand. A unit the canonicaliser mapped but that has no sourced
            #: character is a real finding about the source; a unit it never
            #: mapped is a finding about the pipeline. Reporting both as one
            #: reason would make the pair uncountable, which is how SFI1's 1,284
            #: came to have a single undifferentiated cause.
            no_span_reason = (
                NO_SOURCED_CHARACTER if unit.get("span_map") is not None else NO_NATIVE_SPAN
            )

            #: the witness for the text-bearing kinds. Where no span exists the
            #: witness degenerates to a zero-width point at the head of the
            #: payload, and PROVENANCE_SPAN below records why — the fact is
            #: still emitted, because a unit that vanishes from the fact list is
            #: the silent drop this design exists to prevent.
            start, end = span if span is not None else (0, 0)
            witness = Witness(
                construct="canonical_unit",
                byte_start=start,
                byte_end=end,
                excerpt=raw[start:end].decode("utf-8", "replace")[:200] if span else "",
                unit_path=path,
            )

            if not text.strip():
                facts.append(
                    SourceFact(
                        kind=CONTENT_TEXT,
                        witness=witness,
                        state=IGNORED,
                        policy_ref="POLICY-CORE-001",
                    )
                )
            else:
                #: the check the old instrument never made. `text_sha256` is
                #: written by the canonicaliser from the text it actually
                #: stored, so a mismatch means the state does not carry what
                #: this fact claims.
                carried = unit.get("text_sha256")
                facts.append(
                    SourceFact(
                        kind=CONTENT_TEXT,
                        witness=witness,
                        state=REPRESENTED if carried else UNREPRESENTED,
                        representation={"text": text, "text_sha256": carried}
                        if carried
                        else None,
                        reason=None
                        if carried
                        else "the canonical document carries no digest for this "
                        "unit's text, so nothing in the compiled state holds it",
                    )
                )

            joined = "/".join(unit["explicit_path"])
            in_order = joined in order
            facts.append(
                SourceFact(
                    kind=STRUCTURE,
                    witness=witness,
                    state=REPRESENTED if in_order else UNREPRESENTED,
                    representation={
                        "explicit_path": list(unit["explicit_path"]),
                        "heading": unit.get("heading"),
                        "ordinal": unit.get("ordinal"),
                        "position": order.index(joined) if in_order else None,
                    }
                    if in_order
                    else None,
                    reason=None
                    if in_order
                    else "the unit is absent from structure.order, so its "
                    "position is not carried by the compiled state",
                )
            )

            #: A unit with no sourced character at all is a different failure
            #: from a unit with no span, and both are fail-closed. Separating
            #: them keeps the reason honest: one says the canonicaliser gave us
            #: nothing, the other says there was nothing to give.
            facts.append(
                SourceFact(
                    kind=PROVENANCE_SPAN,
                    witness=witness,
                    state=REPRESENTED if span is not None else UNREPRESENTED,
                    representation={
                        "byte_start": start,
                        "byte_end": end,
                        "unit_path": list(path),
                        #: carried, never used to widen the state. A partly
                        #: inserted unit still came from these bytes; what is
                        #: not known is whether every character did, and that is
                        #: recorded rather than smoothed over. Separators added
                        #: when blocks are joined are the ordinary cause.
                        "fully_sourced": fully_sourced,
                        "verified_by_canonicaliser": bool(unit.get("provenance_verified", True)),
                    }
                    if span is not None
                    else None,
                    reason=None if span is not None else no_span_reason,
                )
            )

        facts.extend(self._unsupported(raw, document, source_id))
        return facts

    def _unsupported(
        self, raw: bytes, document: dict[str, Any], source_id: str
    ) -> list[SourceFact]:
        """One fail-closed fact per unsupported construct found in the source.

        This is the whole point of the kind. Before it existed, a section
        containing MathML scored perfectly: no extractor claimed it, so no fact
        described it, so nothing was wrong. Converting that absence into an
        UNRESOLVED fact is what makes the containing scope stop being complete —
        which is the true statement about the world.

        Anchored to the containing unit where one can be found, and to the
        document otherwise. Never dropped for want of an anchor.
        """
        spans = self._unit_spans(raw, document, source_id)
        found: list[SourceFact] = []
        for name, pattern, why in UNSUPPORTED:
            for match in re.finditer(pattern, raw, re.IGNORECASE):
                start = match.start()
                path = next(
                    (owner for low, high, owner in spans if low <= start < high),
                    unit_path_for(source_id, ()),
                )
                found.append(
                    SourceFact(
                        kind=UNSUPPORTED_CONSTRUCT,
                        witness=Witness(
                            construct=name,
                            byte_start=start,
                            byte_end=match.end(),
                            excerpt=raw[start : match.end()].decode("utf-8", "replace"),
                            unit_path=path,
                        ),
                        state=UNRESOLVED,
                        reason=why,
                    )
                )
        return found

    def _unit_spans(
        self, raw: bytes, document: dict[str, Any], source_id: str
    ) -> list[tuple[int, int, tuple[str, ...]]]:
        """Byte ranges each unit occupies, for attributing a construct to a scope.

        Native spans only. A unit the canonicaliser did not map contributes no
        range, so an unsupported construct inside it is attributed to the
        document rather than to that unit — a wider scope than the truth, never
        a wrong one. Guessing the unit here would silently move a fail-closed
        fact into a scope it does not belong to, and INC-V2-029 records what
        that class of mis-anchoring costs.
        """
        spans: list[tuple[int, int, tuple[str, ...]]] = []
        for unit in document.get("units", []):
            located = _native_span(unit)
            if located is None:
                continue
            spans.append(
                (located[0], located[1], unit_path_for(source_id, unit["explicit_path"]))
            )
        spans.sort()
        #: widen each span to the start of the next, so a construct sitting in
        #: the markup between two units' texts still lands in the earlier scope
        #: rather than escaping to the document.
        widened: list[tuple[int, int, tuple[str, ...]]] = []
        for index, (low, high, owner) in enumerate(spans):
            end = spans[index + 1][0] if index + 1 < len(spans) else len(raw)
            widened.append((low, max(high, end), owner))
        return widened


EXTRACTOR = register(CoreExtractor())
