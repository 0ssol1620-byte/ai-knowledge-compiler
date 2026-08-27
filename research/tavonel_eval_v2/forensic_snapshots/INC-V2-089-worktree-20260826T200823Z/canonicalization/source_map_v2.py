"""The source-map contract that consults MARKUP_SEMANTICS_V1.

``source_map`` (Locality v2) classified markup with P0d's grammar: every start
tag, end tag, entity reference and character reference IGNORED by default, and
fourteen semantic attributes ignored as "presentation". ``INC-V2-010`` recorded
why that is wrong. ``MARKUP_SEMANTICS_V1`` fixed the *policy* — and nothing read
it, which is ``INC-V2-013``.

This module is the missing half: the same forward-built position map, with every
construct classified by the frozen policy instead of by the old attribute list.

``source_map`` and ``source_spans`` are both left untouched, so
``SOURCE_LOCALITY_V2``'s instrument is byte-identical and its eligible-Q1 = 5
remains reproducible. Changing an instrument by writing a new module with its own
digest is the whole point; editing the old one would move a sealed result.

**Content constructs are not classified by policy alone.** The policy says a
character reference and character data are `MODELED` / `CONTENT_LEXICAL`, and
that is a statement about their *kind*. Whether a particular occurrence actually
reached the compiled artifact is a different question, and answering it by
assertion would be an over-grant — the exact failure the anti-fitting rules
forbid. So text and references are MODELED when they are traceable into the
canonical text of that revision and `UNMODELED_SOURCE_FACT` when they are not.
Structural, reference, metadata and accessibility constructs are classified by
policy alone, because their effect is on interpretation rather than on a string
that could be looked for.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from html.entities import html5
from typing import Any

from markup_policy import MODELED, UNMODELED
from markup_semantics import (
    classify_attribute,
    classify_character_reference,
    classify_tag,
    classify_text,
)
from source_map import (
    LOCATION_UNVERIFIABLE,
    LOCATION_VERIFIED,
    LocatedSpan,
    _line_offsets,
    markdown_located,
)
from source_spans import _HTML_REFERENCE_ATTRS

#: Whitespace normalisation used on both sides of a traceability check.
#: Deliberately does NOT include the non-breaking space. Folding it would make
#: every `&#160;` unfindable in the canonical text and so silently unmodelled —
#: and folding it on the source side too would make the check pass for free.
#: Left alone, the reference is modelled exactly when the canonicaliser really
#: carried the character through, which is the question being asked.
_WHITESPACE = re.compile("[ \t\r\n\f\v]+")

#: How much of a long text run must be found before it counts as traceable. A
#: run can be split across canonical units, so the whole run is not required;
#: the head is, and it is long enough that a coincidence is not plausible.
_TRACE_PREFIX = 40


def normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _traceable(fragment: str, canonical: str) -> bool:
    if not canonical:
        return False
    needle = normalise(fragment)
    if not needle:
        return False
    return needle[:_TRACE_PREFIX] in canonical


def _character_for(kind: str, name: str) -> str:
    """The character a reference produces, or empty if it produces none."""
    try:
        if kind == "charref":
            code = int(name[1:], 16) if name[:1].lower() == "x" else int(name)
            return chr(code)
        return html5.get(name + ";") or html5.get(name) or ""
    except (ValueError, OverflowError):
        return ""


class _SemanticScanner(HTMLParser):
    """Positions as in Locality v2; classification from the frozen policy."""

    def __init__(self, raw: str, canonical: str) -> None:
        super().__init__(convert_charrefs=False)
        self.raw = raw
        self.canonical = canonical
        self.lines = _line_offsets(raw)
        self.events: list[dict[str, Any]] = []
        self._preserve = 0

    def _offset(self) -> int | None:
        line, column = self.getpos()
        if line < 1 or line > len(self.lines):
            return None
        return self.lines[line - 1] + column

    def _record(
        self,
        kind: str,
        verdict: dict[str, Any],
        fact: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "start": self._offset(),
                "kind": kind,
                "classification": verdict["state"],
                "facet": verdict.get("facet"),
                "control_fact": verdict.get("control_fact", False),
                "why": verdict.get("why", ""),
                "fact": fact,
            }
        )

    # -- handlers -------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"pre", "textarea"}:
            self._preserve += 1
        self._record("start_tag:" + lowered, classify_tag(lowered))
        for name, value in attrs:
            attribute = name.lower()
            verdict = classify_attribute(attribute, value)
            fact: dict[str, Any] | None = {"tag": lowered, "attribute": attribute}
            if attribute in _HTML_REFERENCE_ATTRS:
                fact = {
                    "reference_kind": _HTML_REFERENCE_ATTRS[attribute],
                    "target": value,
                    "tag": lowered,
                    "attribute": attribute,
                }
            elif value is not None:
                fact["value"] = value[:200]
            self._record("attr:" + attribute, verdict, fact)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in {"pre", "textarea"}:
            self._preserve = max(self._preserve - 1, 0)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"pre", "textarea"}:
            self._preserve = max(self._preserve - 1, 0)
        self._record("end_tag:" + lowered, classify_tag(lowered))

    def handle_data(self, data: str) -> None:
        verdict = classify_text(data, preserved=bool(self._preserve))
        if verdict["state"] == MODELED and not _traceable(data, self.canonical):
            verdict = {
                **verdict,
                "state": UNMODELED,
                "why": (
                    "character data present in the source that is not traceable "
                    "into the canonical text of this revision"
                ),
            }
        self._record("data", verdict, {"sample": data[:120]})

    def _reference(self, kind: str, name: str) -> None:
        verdict = classify_character_reference("&" + ("#" if kind == "charref" else "") + name + ";")
        produced = _character_for(kind, name)
        # containment of the produced character itself. No escape for
        # whitespace-producing references: an empty needle is contained in
        # everything, which would grant them all unconditionally.
        if verdict["state"] == MODELED and not (produced and produced in self.canonical):
            verdict = {
                **verdict,
                "state": UNMODELED,
                "why": "a reference whose character is not traceable into the canonical text",
            }
        self._record(kind, verdict, {"name": name, "produces": produced})

    def handle_entityref(self, name: str) -> None:
        self._reference("entityref", name)

    def handle_charref(self, name: str) -> None:
        self._reference("charref", name)

    def handle_comment(self, data: str) -> None:
        self._record(
            "comment",
            {
                "state": "IGNORED_BY_DECLARED_POLICY",
                "facet": None,
                "why": (
                    "an SGML comment is not delivered to the declared consumer and "
                    "changes no facet of the compiled artifact"
                ),
            },
        )

    def handle_decl(self, decl: str) -> None:
        self._record(
            "decl",
            {
                "state": "IGNORED_BY_DECLARED_POLICY",
                "facet": None,
                "why": "a doctype declares a grammar, not content, structure or reference",
            },
        )

    def handle_pi(self, data: str) -> None:
        self._record(
            "processing_instruction",
            {
                "state": "UNRESOLVED_SOURCE_FACT",
                "facet": "EXTERNAL_DEPENDENCY_EXECUTION",
                "why": (
                    "a processing instruction names a transformation this "
                    "instrument cannot evaluate. Not ignorable and not modelled."
                ),
            },
        )

    def unknown_decl(self, data: str) -> None:
        self._record(
            "unknown_decl",
            {"state": UNMODELED, "facet": None, "why": "an unrecognised declaration"},
        )


def html_located(raw: str, canonical_text: str = "") -> list[LocatedSpan]:
    """Located spans for HTML or XML, classified by the frozen markup policy."""
    scanner = _SemanticScanner(raw, normalise(canonical_text))
    try:
        scanner.feed(raw)
        scanner.close()
    except Exception as error:
        return [
            LocatedSpan(
                None,
                None,
                "parse_failure",
                UNMODELED,
                "",
                None,
                LOCATION_UNVERIFIABLE,
                type(error).__name__,
            )
        ]

    events = scanner.events
    spans: list[LocatedSpan] = []
    for index, event in enumerate(events):
        start = event["start"]
        end = None
        for following in events[index + 1 :]:
            if following["start"] is not None:
                end = following["start"]
                break
        if end is None:
            end = len(raw)
        verified = start is not None and end is not None and 0 <= start <= end <= len(raw)
        fact = dict(event["fact"] or {})
        fact.setdefault("facet", event["facet"])
        fact.setdefault("control_fact", event["control_fact"])
        spans.append(
            LocatedSpan(
                start if verified else None,
                end if verified else None,
                event["kind"],
                event["classification"],
                raw[start:end] if verified else "",
                fact,
                LOCATION_VERIFIED if verified else LOCATION_UNVERIFIABLE,
                event["why"] if not verified else None,
            )
        )
    return spans


def located_spans(raw: str, suffix: str, canonical_text: str = "") -> tuple[list[LocatedSpan], str]:
    """Dispatch by source kind. Markdown keeps its own grammar, unchanged."""
    if suffix == ".md":
        return markdown_located(raw), "markdown"
    return html_located(raw, canonical_text), "markup:MARKUP_SEMANTICS_V1"
