"""The question-local coverage witness under MARKUP_SEMANTICS_V1.

Two things change from ``coverage_witness``, and nothing else does:

1. ``UNRESOLVED_SOURCE_FACT`` blocks completeness exactly as
   ``UNMODELED_SOURCE_FACT`` does. That is the third state's entire purpose — a
   construct whose meaning cannot be settled from local source is not ignorable,
   and treating it as ignorable would be the over-grant the policy exists to
   stop.
2. Markup found *inside* an admitted dependency is classified by the frozen
   markup policy rather than by P0d's attribute list.

The closure itself — roles, identifier following, line-scoped dependency
regions — is imported, not reimplemented. It was built against development
fixtures and its controls pass; rewriting it here would be a second instrument
pretending to be the same one.
"""

from __future__ import annotations

from typing import Any

from coverage_witness import (  # noqa: F401  (re-exported for callers)
    COMPLETE,
    DIRECT,
    MEMBER,
    ELEMENT_ROLES,
    EMBEDDED_MARKUP,
    INCOMPLETE,
    NO_DIRECT_SPAN,
    UNLOCATED_ELEMENT,
    UNMODELED_IN_CLOSURE,
    _HAS_TAG,
    build_witness as _build_closure,
)
from markup_policy import IGNORED, MODELED, UNMODELED, UNRESOLVED
from markup_semantics import blocks_completeness
from source_map import LOCATION_UNVERIFIABLE, LocatedSpan
from source_map_v2 import html_located

#: A distinct refusal reason, so the aggregate can separate "the source says
#: something this instrument cannot settle" from "the source says something
#: this instrument does not model at all". Collapsing them would hide which of
#: the two is actually driving eligibility.
UNRESOLVED_IN_CLOSURE = "UNRESOLVED_SOURCE_FACT_IN_CLOSURE"


#: The markup grammar, as ``source_map_v2.located_spans`` names it.
MARKUP_GRAMMAR = "markup:MARKUP_SEMANTICS_V1"

#: A span admitted because it lies inside the source region the atom occupies.
IN_ATOM_REGION = "inside the source region the atom occupies"


#: Shorter than this, a fragment is too common to locate anything.
_ANCHORING_MIN_CHARS = 8

#: The closure could not establish where in the source the atom lives, so no
#: statement about what surrounds it is possible. Refused, not guessed.
REGION_NOT_LOCALISABLE = "ATOM_SOURCE_REGION_NOT_LOCALISABLE"


def _region_of(
    elements: list[dict[str, Any]], spans: list[LocatedSpan], raw: str | None
) -> tuple[int, int] | None:
    """The source extent the atom and its envelope members occupy.

    Bounds are set only by fragments that occur **exactly once** in the source
    and are long enough to mean something. A three-character run that appears
    four hundred times cannot locate anything, and letting it set a bound
    stretches the region to the whole file — which would turn this back into the
    document-level rule Locality v2 exists to replace.
    """
    if raw is None:
        return None
    bounds: list[tuple[int, int]] = []
    for element in elements:
        if element["role"] not in {DIRECT, MEMBER}:
            continue
        if element["start"] is None or element["end"] is None:
            continue
        # read the fragment from the source rather than indexing every span:
        # an index rebuilt per question is a dictionary of the whole document,
        # thousands of times over, which is how this ran out of memory.
        fragment = raw[element["start"] : element["end"]].strip()
        if len(fragment) < _ANCHORING_MIN_CHARS or raw.count(fragment) != 1:
            continue
        bounds.append((element["start"], element["end"]))
    if not bounds:
        return None
    low = min(start for start, _ in bounds)
    high = max(end for _, end in bounds)
    return _extend_over_delimiting_markup(spans, low, high)


def _is_content_data(span: LocatedSpan) -> bool:
    return span.kind == "data" and bool((span.text or "").strip())


def _extend_over_delimiting_markup(
    spans: list[LocatedSpan], low: int, high: int
) -> tuple[int, int]:
    """Grow the region across the markup that delimits the atom's text.

    An atom's text is `<div class="..."><p>` *here* `</p></div>`, and the
    attributes that decide how that text is interpreted sit in the tags on
    either side of it, not inside it. A region bounded by the text alone
    examines the one construct that was never in doubt and none of the ones that
    were.

    Growth stops at the nearest character data that is not the atom's, because
    that belongs to a different unit and claiming it is this atom's region would
    be an over-reach in the other direction.
    """
    located = sorted(
        (span for span in spans if span.located), key=lambda span: (span.start, span.end)
    )
    if not located:
        return low, high
    inside = [index for index, span in enumerate(located) if span.start >= low and span.end <= high]
    if not inside:
        return low, high

    first, last = inside[0], inside[-1]
    index = first - 1
    while index >= 0 and not _is_content_data(located[index]):
        low = min(low, located[index].start)
        index -= 1
    index = last + 1
    while index < len(located) and not _is_content_data(located[index]):
        high = max(high, located[index].end)
        index += 1
    return low, high


def build_witness(
    spans: list[LocatedSpan],
    target_text: str,
    member_texts: list[str],
    fact_targets: Any = (),
    raw: str | None = None,
    canonical_text: str = "",
    grammar: str | None = None,
) -> dict[str, Any]:
    """The v1 closure, with embedded markup reclassified by the frozen policy.

    For markup there is one addition, and it is the difference between measuring
    coverage and measuring nothing. The v1 closure admits a span when its *text*
    appears in the atom, which for HTML admits character data and essentially
    nothing else: every tag and attribute inside the atom's own region falls
    outside the closure and is never examined. Under the old grammar that was
    invisible, because the character data was `UNMODELED` and blocked anyway.
    Under this policy the character data is `MODELED` when traceable, so the
    same closure would grant completeness to a document whose markup it never
    looked at — an over-grant produced by an improvement, which is the most
    dangerous kind.

    So for markup the closure also admits every span overlapping the source
    region the atom and its envelope members occupy. Widening a closure can only
    block, never grant, so the direction of the correction is fail-closed.
    """
    witness = _build_closure(spans, target_text, member_texts, fact_targets, raw)
    elements = [
        element
        for element in witness["elements"]
        if not str(element["kind"]).startswith(EMBEDDED_MARKUP)
    ]

    admitted = {(element["start"], element["end"]) for element in elements}

    region: tuple[int, int] | None = None
    if grammar == MARKUP_GRAMMAR:
        region = _region_of(elements, spans, raw)
        if region is not None:
            low, high = region
            for span in spans:
                if (span.start, span.end) in admitted or not span.overlaps(low, high):
                    continue
                admitted.add((span.start, span.end))
                elements.append(
                    {
                        **span.as_dict(),
                        "role": DIRECT,
                        "admitted_because": IN_ATOM_REGION,
                        "sample": span.text[:120],
                    }
                )
    # Only for markdown. In a markup document every construct is already a
    # classified event, so re-parsing each admitted span would re-derive what
    # the map produced — thousands of times per question, for nothing.
    derived: list[dict[str, Any]] = []
    for span in spans if grammar != MARKUP_GRAMMAR else ():
        if (span.start, span.end) not in admitted:
            continue
        if not _HAS_TAG.search(span.text or ""):
            continue
        for inner in html_located(span.text, canonical_text):
            if not blocks_completeness(inner.classification) or not inner.text.strip():
                continue
            derived.append(
                {
                    "start": span.start,
                    "end": span.end,
                    "kind": EMBEDDED_MARKUP + ":" + inner.kind,
                    "classification": inner.classification,
                    "location_state": span.location_state,
                    "fact": inner.fact,
                    "role": "reference_definition",
                    "admitted_because": (
                        "markup inside an admitted dependency, classified by "
                        "MARKUP_SEMANTICS_V1"
                    ),
                    "sample": inner.text[:120],
                }
            )
    elements.extend(derived)
    return {
        **witness,
        "elements": elements,
        "element_count": len(elements),
        "by_role": {
            role: sum(1 for element in elements if element["role"] == role)
            for role in ELEMENT_ROLES
        },
        "policy": "MARKUP_SEMANTICS_V1",
        "atom_source_region": list(region) if region else None,
        "region_required": grammar == MARKUP_GRAMMAR,
    }


def witness_status(witness: dict[str, Any], spans: list[LocatedSpan]) -> dict[str, Any]:
    """Grant or refuse, with UNRESOLVED blocking and counted on its own."""
    elements = witness["elements"]
    unmodeled = [e for e in elements if e["classification"] == UNMODELED]
    unresolved = [e for e in elements if e["classification"] == UNRESOLVED]
    unlocated_in_closure = [e for e in elements if e["location_state"] == LOCATION_UNVERIFIABLE]
    unlocated_anywhere = [s for s in spans if s.location_state == LOCATION_UNVERIFIABLE]
    direct = [e for e in elements if e["role"] == DIRECT]

    reasons: list[str] = []
    if not direct:
        reasons.append(NO_DIRECT_SPAN)
    if witness.get("region_required") and witness.get("atom_source_region") is None:
        # no unambiguous fragment placed the atom in the source, so nothing can
        # be said about what surrounds it
        reasons.append(REGION_NOT_LOCALISABLE)
    if unmodeled:
        reasons.append(UNMODELED_IN_CLOSURE)
    if unresolved:
        reasons.append(UNRESOLVED_IN_CLOSURE)
    if unlocated_in_closure or unlocated_anywhere:
        reasons.append(UNLOCATED_ELEMENT)

    return {
        "status": COMPLETE if not reasons else INCOMPLETE,
        "reasons": reasons,
        "policy": "MARKUP_SEMANTICS_V1",
        "unmodeled_in_closure": len(unmodeled),
        "unmodeled_samples": [e["sample"] for e in unmodeled[:4]],
        "unresolved_in_closure": len(unresolved),
        "unresolved_samples": [e["sample"] for e in unresolved[:4]],
        "unresolved_constructs": sorted(
            {str(e["kind"]) for e in unresolved}
        )[:12],
        "location_unverifiable_in_closure": len(unlocated_in_closure),
        "location_unverifiable_in_document": len(unlocated_anywhere),
        "atom_source_region": witness.get("atom_source_region"),
        "witness_element_count": witness["element_count"],
        "witness_by_role": witness["by_role"],
        "modeled_in_closure": sum(1 for e in elements if e["classification"] == MODELED),
        "ignored_in_closure": sum(1 for e in elements if e["classification"] == IGNORED),
    }
