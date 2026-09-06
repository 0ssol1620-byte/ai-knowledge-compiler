"""Changed source regions, and what the system says happened to each one.

SOURCE_FAITHFULNESS_HELDOUT_V1, sections 2 and 3.

P0d asked whether a whole document's source reaches the canonical state. This
asks the narrower and more answerable question a revision pair makes possible:
**when a region of source changes, does the system say what became of it?**

Three things are kept apart here on purpose, because folding any two of them
together is how a faithfulness measurement stops measuring anything:

``classification``
    what the frozen grammar predicts, from the construct alone. For content it
    consults the canonical text, because the frozen resolver already does; for
    everything else it is policy, blind to the compiled state.

``verification``
    whether the compiled state can actually carry that region. This is an
    observation about ``compiler/selective_build.py``, not an opinion. The
    compiler stores unit text, headings, explicit paths and document order. A
    facet with nowhere to live in that structure is not verified, and saying so
    is the point.

``visibility``
    whether the loss is declared. A fact the system declines to model and
    reports as incomplete is a limitation. The same fact inside a scope the
    system calls complete is a false statement about the world, and that — not
    the absence of the fact — is the silent drop this module exists to find.

Nothing here edits ``source_map``, ``source_map_v2``, ``markup_policy``,
``markup_semantics`` or ``source_spans``. Their digests are what
SOURCE_LOCALITY_V2 and MARKUP_SEMANTICS_V1 were sealed against; a new question
gets a new module, never an edit to a sealed instrument.
"""

from __future__ import annotations

import bisect
import difflib
import re
from typing import Any

from markup_policy import (
    ACCESSIBILITY,
    AUTHORITY_APPLICABILITY,
    CONTENT_LEXICAL,
    EXTERNAL_DEPENDENCY,
    IGNORED as POLICY_IGNORED,
    METADATA,
    MODELED as POLICY_MODELED,
    REFERENCE_LOCATOR,
    STRUCTURAL,
    TEMPORAL,
    UNMODELED as POLICY_UNMODELED,
    UNRESOLVED as POLICY_UNRESOLVED,
    VISUAL,
)
from source_map import LOCATION_VERIFIED, LocatedSpan
from source_map_v2 import located_spans
from source_spans import attribute_to_canonical

# --- the three states this protocol reports ----------------------------------

MODELED = "MODELED"
IGNORED = "IGNORED_BY_PREDECLARED_POLICY"
UNRESOLVED = "UNRESOLVED_SOURCE_FACT"
STATES = (MODELED, IGNORED, UNRESOLVED)

#: Not a state. A changed byte the position map does not cover at all, so
#: nothing in the system says anything about it. This is the hard failure the
#: protocol names: no state is exactly what a silent drop looks like from the
#: inside, and it must never be quietly renamed into one of the three.
UNCLASSIFIED = "UNCLASSIFIED_CHANGED_REGION"

#: The frozen policy carries four states. UNMODELED — "the grammar did not
#: classify this" — is reported as UNRESOLVED, which is the fail-closed
#: direction and which the frozen resolver already treats identically
#: (BLOCKS_COMPLETENESS). The four-state value is preserved on every row, so
#: this is a projection and not a reclassification. Collapsing either toward
#: IGNORED is forbidden and is not reachable through this table.
POLICY_TO_STATE = {
    POLICY_MODELED: MODELED,
    POLICY_IGNORED: IGNORED,
    POLICY_UNRESOLVED: UNRESOLVED,
    POLICY_UNMODELED: UNRESOLVED,
}

# --- verification outcomes ----------------------------------------------------

VERIFIED = "MODELED_CLAIM_VERIFIED"
UNVERIFIED = "MODELED_CLAIM_NOT_VERIFIED"
NOT_APPLICABLE = "NOT_A_MODELED_CLAIM"

FACET_ABSENT = "FACET_NOT_REPRESENTABLE_IN_COMPILED_STATE"
NOT_IN_STATE = "PROJECTION_ABSENT_FROM_COMPILED_STATE"
NO_PROJECTION = "REGION_HAS_NO_ALPHANUMERIC_PROJECTION"

SILENT_DROP = "SILENT_SOURCE_DROP"

#: What ``compiler/selective_build.py`` can actually hold, read off that module
#: rather than assumed. An artifact is built from a canonical unit's text, its
#: heading, its explicit path and its position in document order. That is the
#: entire vocabulary of the compiled state.
#:
#: A facet mapped to ``False`` here has nowhere to live in it. Recording that as
#: a declared map, rather than discovering it per row, is what makes the
#: headline count auditable: a reader can disagree with one line of this table
#: instead of with an aggregate.
FACET_IN_COMPILED_STATE: dict[str, bool] = {
    CONTENT_LEXICAL: True,
    STRUCTURAL: True,
    REFERENCE_LOCATOR: False,
    TEMPORAL: False,
    AUTHORITY_APPLICABILITY: False,
    METADATA: False,
    ACCESSIBILITY: False,
    VISUAL: False,
    EXTERNAL_DEPENDENCY: False,
}

#: Structural constructs the compiled state does represent. Everything else
#: structural — table spans, list ordinals, header scope — changes
#: interpretation without changing any of the four things an artifact carries.
STRUCTURAL_IN_STATE = frozenset(
    {"atx_heading", "setext_heading", "heading", "h1", "h2", "h3", "h4", "h5", "h6"}
)

_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


def fold(text: str) -> str:
    """Alphanumeric projection. The same folding ``source_spans`` uses.

    Deliberately loose in one direction only: it can say a region *did* reach
    the compiled state, never that it did not on a technicality of punctuation.
    Under a stricter probe the unverified share would be larger, never smaller.
    """
    return _NON_ALNUM.sub("", text).casefold()


# --- raw difference -----------------------------------------------------------


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def changed_ranges(before: str, after: str) -> dict[str, list[tuple[int, int]]]:
    """Character ranges that differ, on both sides.

    Both sides are returned because a pure deletion has no position in the newer
    revision. Scoring only the newer side would make "the source region vanished
    entirely" the one change this protocol could not see, which would be an
    embarrassing blind spot for a protocol about things vanishing.
    """
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    before_at = _line_offsets(before)
    after_at = _line_offsets(after)

    added: list[tuple[int, int]] = []
    deleted: list[tuple[int, int]] = []
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_block = before[before_at[i1] : before_at[i2]]
        after_block = after[after_at[j1] : after_at[j2]]
        refined = _refine(before_block, after_block)
        added.extend(
            (after_at[j1] + start, after_at[j1] + end) for start, end in refined["added"]
        )
        deleted.extend(
            (before_at[i1] + start, before_at[i1] + end) for start, end in refined["deleted"]
        )
    return {"added": added, "deleted": deleted}


#: Above this, a changed block is reported whole rather than refined character by
#: character. The refinement is quadratic in the worst case and a block this
#: large is a rewrite, not an edit. Reporting it whole is the conservative
#: direction: it can only widen what is examined.
_REFINE_CEILING = 20000


def _refine(before_block: str, after_block: str) -> dict[str, list[tuple[int, int]]]:
    """Narrow a changed line block to the characters that actually moved.

    Without this, a one-word edit marks its whole line changed, and every link,
    heading and attribute sharing that line is scored as a changed region. The
    counts would then be a function of line length rather than of the edit.
    """
    if max(len(before_block), len(after_block)) > _REFINE_CEILING:
        return {
            "added": [(0, len(after_block))] if after_block else [],
            "deleted": [(0, len(before_block))] if before_block else [],
        }
    added: list[tuple[int, int]] = []
    deleted: list[tuple[int, int]] = []
    inner = difflib.SequenceMatcher(None, before_block, after_block, autojunk=False)
    for tag, i1, i2, j1, j2 in inner.get_opcodes():
        if tag == "equal":
            continue
        if j2 > j1:
            added.append((j1, j2))
        if i2 > i1:
            deleted.append((i1, i2))
    return {"added": added, "deleted": deleted}


# --- spans --------------------------------------------------------------------


def side_spans(raw: str, suffix: str, unit_texts: list[str]) -> tuple[list[LocatedSpan], str]:
    """Located, policy-classified spans for one revision.

    Markdown prose is attributed to the canonical units exactly as P0d does it,
    using P0d's own function rather than a second copy of the rule. HTML and XML
    need no attribution step: the frozen resolver performs its own traceability
    check while it scans.
    """
    canonical_text = "\n".join(unit_texts)
    spans, grammar = located_spans(raw, suffix, canonical_text)
    if suffix == ".md":
        attribute_to_canonical(spans, unit_texts, [])
    return spans, grammar


def index_spans(spans: list[LocatedSpan]) -> tuple[list[int], list[LocatedSpan]]:
    """Verified spans sorted by start, with a parallel list of their starts.

    A linear scan per changed range is quadratic in (ranges x spans), and both
    grow with document size, so a large revision pair can stall for minutes on
    an overlap test that carries no judgement. The ordering is the same
    ordering; only the search changes.
    """
    located = sorted(
        (
            span
            for span in spans
            if span.location_state == LOCATION_VERIFIED
            and span.start is not None
            and span.end is not None
        ),
        key=lambda span: (span.start, span.end),
    )
    return [span.start for span in located], located


def _overlaps(
    index: tuple[list[int], list[LocatedSpan]], low: int, high: int
) -> list[LocatedSpan]:
    starts, located = index
    ceiling = max(high, low + 1)
    #: spans are non-overlapping by construction on both grammars, so the first
    #: candidate is the last one starting at or before `low`.
    position = max(0, bisect.bisect_right(starts, low) - 1)
    found: list[LocatedSpan] = []
    for span in located[position:]:
        if span.start >= ceiling:
            break
        if span.end > low:
            found.append(span)
    return found


def _facet_of(span: LocatedSpan) -> str | None:
    fact = span.fact or {}
    facet = fact.get("facet")
    return str(facet) if facet else None


def _value_of(span: LocatedSpan) -> str:
    """What to look for in the compiled state, for this region."""
    fact = span.fact or {}
    for key in ("title", "target", "identifier", "value", "name"):
        value = fact.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return span.text


# --- regions ------------------------------------------------------------------


def regions(
    raw: str, spans: list[LocatedSpan], ranges: list[tuple[int, int]], side: str
) -> list[dict[str, Any]]:
    """One row per changed region, each carrying exactly one of the three states.

    A changed byte that no verified span covers becomes an ``UNCLASSIFIED``
    row. That is the hard failure, and it is reached rather than avoided: an
    instrument that invented a state for uncovered bytes would pass its own gate
    by construction.
    """
    rows: list[dict[str, Any]] = []
    index = index_spans(spans)
    for low, high in ranges:
        covered: list[tuple[int, int]] = []
        for span in _overlaps(index, low, high):
            start, end = max(low, span.start), min(high, span.end)
            if end <= start and not (low == high and span.start <= low <= span.end):
                continue
            covered.append((start, end))
            policy_state = span.classification
            rows.append(
                {
                    "side": side,
                    "start": start,
                    "end": end,
                    "length": end - start,
                    "kind": str(span.kind),
                    "state": POLICY_TO_STATE.get(policy_state, UNCLASSIFIED),
                    "policy_state": policy_state,
                    "facet": _facet_of(span),
                    "projection": fold(_value_of(span)),
                    "sample": raw[start:end][:120],
                }
            )
        for gap_start, gap_end in _gaps(low, high, covered):
            rows.append(
                {
                    "side": side,
                    "start": gap_start,
                    "end": gap_end,
                    "length": gap_end - gap_start,
                    "kind": "not_covered_by_position_map",
                    "state": UNCLASSIFIED,
                    "policy_state": None,
                    "facet": None,
                    "projection": fold(raw[gap_start:gap_end]),
                    "sample": raw[gap_start:gap_end][:120],
                }
            )
    return rows


def _gaps(low: int, high: int, covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if high <= low:
        return [] if covered else [(low, high)]
    out: list[tuple[int, int]] = []
    cursor = low
    for start, end in sorted(covered):
        if start > cursor:
            out.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < high:
        out.append((cursor, high))
    return out


# --- verification -------------------------------------------------------------


def compiled_projection(document: dict[str, Any]) -> str:
    """Everything a compiled artifact can be built out of, folded into one string."""
    parts: list[str] = []
    for unit in document["units"]:
        parts.append(unit["text"])
        if unit.get("heading"):
            parts.append(str(unit["heading"]))
        parts.extend(str(step) for step in unit["explicit_path"])
    return fold(" ".join(parts))


def verify(row: dict[str, Any], projection: str) -> dict[str, Any]:
    """Can the compiled state carry this region? An observation, not an opinion."""
    if row["state"] != MODELED:
        return {"verification": NOT_APPLICABLE, "verification_reason": None}

    facet = row["facet"]
    representable = FACET_IN_COMPILED_STATE.get(facet, False) if facet else True
    if facet == STRUCTURAL and row["kind"] not in STRUCTURAL_IN_STATE:
        representable = False
    if not representable:
        return {"verification": UNVERIFIED, "verification_reason": FACET_ABSENT}

    probe = row["projection"]
    if not probe:
        return {"verification": UNVERIFIED, "verification_reason": NO_PROJECTION}
    if probe in projection:
        return {"verification": VERIFIED, "verification_reason": None}
    return {"verification": UNVERIFIED, "verification_reason": NOT_IN_STATE}


# --- roll-up ------------------------------------------------------------------


def blocks_local_completeness(row: dict[str, Any]) -> bool:
    """A region whose presence must stop a scope being called complete."""
    return row["state"] == UNRESOLVED or row["verification"] == UNVERIFIED


def classify_pair(
    *,
    before_raw: str,
    after_raw: str,
    before_document: dict[str, Any],
    after_document: dict[str, Any],
    suffix: str,
) -> dict[str, Any]:
    """Every changed region of one revision pair, classified and verified."""
    before_units = [unit["text"] for unit in before_document["units"]]
    after_units = [unit["text"] for unit in after_document["units"]]

    before_spans, grammar = side_spans(before_raw, suffix, before_units)
    after_spans, _ = side_spans(after_raw, suffix, after_units)

    ranges = changed_ranges(before_raw, after_raw)
    rows = regions(after_raw, after_spans, ranges["added"], "after")
    rows += regions(before_raw, before_spans, ranges["deleted"], "before")

    #: a deleted region is verified against the revision it was deleted FROM.
    #: Asking whether the newer compiled state carries it would score every
    #: deletion as a loss, which is not what a deletion is.
    after_projection = compiled_projection(after_document)
    before_projection = compiled_projection(before_document)
    for row in rows:
        row.update(
            verify(row, after_projection if row["side"] == "after" else before_projection)
        )

    counts: dict[str, int] = {state: 0 for state in (*STATES, UNCLASSIFIED)}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1

    return {
        "grammar": grammar,
        "region_count": len(rows),
        "by_state": counts,
        "unclassified": counts.get(UNCLASSIFIED, 0),
        "modeled_claims": sum(1 for row in rows if row["state"] == MODELED),
        "modeled_claims_verified": sum(1 for row in rows if row["verification"] == VERIFIED),
        "modeled_claims_unverified": sum(
            1 for row in rows if row["verification"] == UNVERIFIED
        ),
        "unverified_by_reason": _tally(
            row["verification_reason"] for row in rows if row["verification"] == UNVERIFIED
        ),
        "blocking_regions": sum(1 for row in rows if blocks_local_completeness(row)),
        "compiled_state_changed": (
            before_projection != after_projection
            or before_document["structure"]["order"] != after_document["structure"]["order"]
        ),
        "rows": rows,
        "spans": {"before": before_spans, "after": after_spans},
    }


def _tally(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
