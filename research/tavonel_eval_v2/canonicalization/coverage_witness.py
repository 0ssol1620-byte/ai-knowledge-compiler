"""The source-coverage witness for one question.

Locality v1 asked a single question — is there an unmodeled span between the
first and last modeled span of the atoms in scope? — and admitted in its own
docstring that this can **over-grant**: a link reference definition sitting at
the foot of a file, which the target atom depends on, falls outside the interval
and was never examined.

Locality v2 replaces the interval with an explicit, recorded artifact. For each
target atom the witness is the **dependency closure** over

1. the atom's direct raw-source span,
2. the source spans of every envelope member atom,
3. reference and link definitions the atom uses,
4. include, import and directive targets and their arguments,
5. anchor, citation and reference dependencies,
6. the source spans that produced the atom's canonical facts.

``QUESTION_LOCAL_COVERAGE_COMPLETE`` is granted only when every element of that
set is ``MODELED`` or ``IGNORED_BY_DECLARED_POLICY`` and the count of
``UNMODELED_SOURCE_FACT`` is zero. An element whose position could not be proven
is ``LOCATION_UNVERIFIABLE`` and blocks completeness on its own — an unlocatable
element cannot be shown to be outside the closure, so it is treated as inside.

The witness is written out, not merely consulted. A closure that only ever
existed inside a boolean cannot be argued with.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from source_map import LOCATION_UNVERIFIABLE, LocatedSpan, html_located
from source_spans import IGNORED, MODELED, UNMODELED

COMPLETE = "QUESTION_LOCAL_COVERAGE_COMPLETE"
INCOMPLETE = "QUESTION_LOCAL_COVERAGE_INCOMPLETE"

#: Why a witness refused completeness. Recorded per question so the aggregate
#: can be read by cause rather than as one number.
UNMODELED_IN_CLOSURE = "UNMODELED_SOURCE_FACT_IN_CLOSURE"
UNLOCATED_ELEMENT = "LOCATION_UNVERIFIABLE_IN_DOCUMENT"
NO_DIRECT_SPAN = "NO_DIRECT_SPAN_FOR_TARGET_ATOM"

#: Reference syntax the closure follows out of the atom's own text. Each entry
#: names a dependency that can live anywhere in the file, which is the whole
#: reason the interval rule was insufficient.
_REFERENCE_USE = re.compile(r"\[[^\]]*\]\[(?P<id>[^\]]+)\]")
_SHORTCUT_USE = re.compile(r"(?<!\!)\[(?P<id>[^\]\[]+)\]\[\]")
_ANCHOR_USE = re.compile(r"\]\(#(?P<id>[\w-]+)\)")
_INCLUDE_USE = re.compile(r"\{\{[<%]-?\s*(?P<name>[\w./-]+)(?P<args>[^}]*?)-?[>%]\}\}")

#: A dependency the closure admits but whose *content* is not in this source.
#: An include or import names a file the canonical state never saw, so nothing
#: about its coverage has been established. Treating it as MODELED because the
#: directive itself parsed would be reporting that the instrument read the
#: signpost and calling it the road.
UNRESOLVED_INCLUDE = "UNRESOLVED_INCLUDE_TARGET"

#: Markup embedded inside an admitted element — most often inside a reference
#: definition's target. The markdown grammar classifies the definition as a
#: whole and does not look inside it, which is how the out-of-range control
#: first slipped through.
EMBEDDED_MARKUP = "EMBEDDED_MARKUP_IN_DEPENDENCY"

_HAS_TAG = re.compile(r"<[A-Za-z][^>]*>")

DIRECT = "direct_atom_span"
MEMBER = "envelope_member_span"
REFERENCE_DEFINITION = "reference_definition"
DIRECTIVE_TARGET = "directive_or_include_target"
ANCHOR_DEPENDENCY = "anchor_or_citation_dependency"
FACT_SOURCE = "canonical_fact_source_span"

ELEMENT_ROLES = (
    DIRECT,
    MEMBER,
    REFERENCE_DEFINITION,
    DIRECTIVE_TARGET,
    ANCHOR_DEPENDENCY,
    FACT_SOURCE,
)


def _identifiers(text: str) -> set[str]:
    """Reference identifiers the text uses, by any of the syntaxes above."""
    found = {match.group("id").strip().casefold() for match in _REFERENCE_USE.finditer(text)}
    found |= {match.group("id").strip().casefold() for match in _SHORTCUT_USE.finditer(text)}
    found |= {match.group("id").strip().casefold() for match in _ANCHOR_USE.finditer(text)}
    return {identifier for identifier in found if identifier}


def _directive_names(text: str) -> set[str]:
    return {match.group("name").strip().casefold() for match in _INCLUDE_USE.finditer(text)}


def _span_identifier(span: LocatedSpan) -> str | None:
    fact = span.fact or {}
    for key in ("identifier", "name", "id"):
        value = fact.get(key)
        if value:
            return str(value).strip().casefold()
    if span.kind == "link_reference_def":
        match = re.match(r"^[ \t]{0,3}\[(?P<id>[^\]]+)\]:", span.text)
        if match:
            return match.group("id").strip().casefold()
    return None


def _line_extent(raw: str, start: int, end: int) -> tuple[int, int]:
    """Widen an interval to the whole lines it touches.

    A reference definition is a line-scoped construct, and the grammar's span
    for it stops at the first whitespace inside its target. Taking the lines the
    dependency occupies is not a guess about where it is — it is the syntactic
    unit the source itself defines — and without it the closure follows the
    definition's identifier while missing the region that identifier points at.
    That is precisely how the out-of-range control first passed when it should
    have failed.
    """
    low = raw.rfind(chr(10), 0, start) + 1
    high = raw.find(chr(10), max(end - 1, start))
    return low, (len(raw) if high == -1 else high + 1)


def build_witness(
    spans: list[LocatedSpan],
    target_text: str,
    member_texts: list[str],
    fact_targets: Iterable[str] = (),
    raw: str | None = None,
) -> dict[str, Any]:
    """The closure, as an explicit artifact.

    Membership is by role, and every element records which role admitted it, so
    a later reader can see *why* a span was examined rather than only that it
    was.
    """
    elements: list[dict[str, Any]] = []
    seen: set[int] = set()

    def admit(span: LocatedSpan, role: str, why: str) -> None:
        key = id(span)
        if key in seen:
            return
        seen.add(key)
        elements.append(
            {
                **span.as_dict(),
                "role": role,
                "admitted_because": why,
                "sample": span.text[:120],
            }
        )

    scope_texts = [t for t in [target_text, *member_texts] if t]
    wanted_ids = set()
    wanted_directives = set()
    for text in scope_texts:
        wanted_ids |= _identifiers(text)
        wanted_directives |= _directive_names(text)
    wanted_targets = {str(t).strip().casefold() for t in fact_targets if t}

    # 1 and 2 — the atom's own span and its envelope members', by containment
    for span in spans:
        if not span.text.strip():
            continue
        stripped = span.text.strip()
        if target_text and stripped in target_text:
            admit(span, DIRECT, "span text appears in the target atom")
        elif any(stripped in text for text in member_texts):
            admit(span, MEMBER, "span text appears in an envelope member atom")

    # 3, 4 and 5 — dependencies that may live anywhere in the file
    for span in spans:
        identifier = _span_identifier(span)
        fact = span.fact or {}
        kind = str(fact.get("reference_kind") or "")
        if identifier and identifier in wanted_ids:
            role = (
                REFERENCE_DEFINITION
                if span.kind in {"link_reference_def", "attr:href", "attr:id"}
                or kind in {"link_definition", "hyperlink"}
                else ANCHOR_DEPENDENCY
            )
            admit(span, role, "definition of an identifier the atom uses: " + identifier)
        elif identifier and identifier in wanted_directives:
            admit(span, DIRECTIVE_TARGET, "directive the atom invokes: " + identifier)
        elif kind in {"include", "directive"} and identifier in wanted_directives:
            admit(span, DIRECTIVE_TARGET, "include or directive target used by the atom")

    # a dependency occupies a syntactic region, not just the span the grammar
    # matched. Widen to whole lines and admit everything overlapping.
    if raw is not None:
        dependency_roles = {REFERENCE_DEFINITION, DIRECTIVE_TARGET, ANCHOR_DEPENDENCY}
        regions = [
            _line_extent(raw, span.start, span.end)
            for span in spans
            if id(span) in seen and span.located
            and next(
                (e["role"] for e in elements if e["start"] == span.start and e["end"] == span.end),
                None,
            )
            in dependency_roles
        ]
        for low, high in regions:
            for span in spans:
                if id(span) in seen or not span.overlaps(low, high):
                    continue
                admit(
                    span,
                    REFERENCE_DEFINITION,
                    "inside the syntactic region of a dependency the atom uses",
                )

    # dependencies admitted above may themselves hide uncovered source. Two
    # cases, both found by the development controls rather than by inspection.
    derived: list[dict[str, Any]] = []
    for span in spans:
        if id(span) not in seen:
            continue
        fact = span.fact or {}
        kind = str(fact.get("reference_kind") or "")
        if kind == "include":
            derived.append(
                {
                    "start": span.start,
                    "end": span.end,
                    "kind": UNRESOLVED_INCLUDE,
                    "classification": UNMODELED,
                    "location_state": span.location_state,
                    "fact": fact,
                    "role": DIRECTIVE_TARGET,
                    "admitted_because": (
                        "the include names content that is not in this source, so "
                        "its coverage is unestablished"
                    ),
                    "sample": str(fact.get("target") or span.text)[:120],
                }
            )
        if _HAS_TAG.search(span.text or ""):
            for inner in html_located(span.text):
                if inner.classification == UNMODELED and inner.text.strip():
                    derived.append(
                        {
                            "start": span.start,
                            "end": span.end,
                            "kind": EMBEDDED_MARKUP + ":" + inner.kind,
                            "classification": UNMODELED,
                            "location_state": span.location_state,
                            "fact": inner.fact,
                            "role": REFERENCE_DEFINITION,
                            "admitted_because": (
                                "markup inside an admitted dependency that the "
                                "outer grammar does not classify"
                            ),
                            "sample": inner.text[:120],
                        }
                    )
    elements.extend(derived)

    # 6 — spans that produced a canonical fact the atom carries
    for span in spans:
        fact = span.fact or {}
        target = str(fact.get("target") or "").strip().casefold()
        if target and target in wanted_targets:
            admit(span, FACT_SOURCE, "produced a canonical fact carried by the atom")

    return {
        "elements": elements,
        "element_count": len(elements),
        "by_role": {
            role: sum(1 for element in elements if element["role"] == role)
            for role in ELEMENT_ROLES
        },
        "identifiers_followed": sorted(wanted_ids),
        "directives_followed": sorted(wanted_directives),
    }


def witness_status(
    witness: dict[str, Any], spans: list[LocatedSpan]
) -> dict[str, Any]:
    """Grant or refuse local completeness, with the reason recorded.

    Refusal reasons are enumerated rather than collapsed, because the aggregate
    this feeds is read by cause: an eligibility figure driven by unlocatable
    markup means something different from one driven by genuine unmodeled facts,
    and a single count could not tell them apart.
    """
    elements = witness["elements"]
    unmodeled = [e for e in elements if e["classification"] == UNMODELED]
    unlocated_in_closure = [
        e for e in elements if e["location_state"] == LOCATION_UNVERIFIABLE
    ]
    unlocated_anywhere = [
        span for span in spans if span.location_state == LOCATION_UNVERIFIABLE
    ]
    direct = [e for e in elements if e["role"] == DIRECT]

    reasons: list[str] = []
    if not direct:
        reasons.append(NO_DIRECT_SPAN)
    if unmodeled:
        reasons.append(UNMODELED_IN_CLOSURE)
    if unlocated_in_closure or unlocated_anywhere:
        # an unlocatable element cannot be shown to sit outside the closure, so
        # it is treated as inside it
        reasons.append(UNLOCATED_ELEMENT)

    return {
        "status": COMPLETE if not reasons else INCOMPLETE,
        "reasons": reasons,
        "unmodeled_in_closure": len(unmodeled),
        "unmodeled_samples": [e["sample"] for e in unmodeled[:4]],
        "location_unverifiable_in_closure": len(unlocated_in_closure),
        "location_unverifiable_in_document": len(unlocated_anywhere),
        "witness_element_count": witness["element_count"],
        "witness_by_role": witness["by_role"],
        "modeled_in_closure": sum(
            1 for e in elements if e["classification"] == MODELED
        ),
        "ignored_in_closure": sum(1 for e in elements if e["classification"] == IGNORED),
    }
