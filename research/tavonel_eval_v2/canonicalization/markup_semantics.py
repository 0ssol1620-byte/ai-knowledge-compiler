"""Resolve a markup construct to a state and a facet. Code, hashed separately.

The policy this consults lives in ``markup_policy`` and carries its own content
digest, so a change to the classification of one attribute is visible even when
this file is untouched, and a change to this resolution logic is visible even
when the policy is untouched. Sealing only one of the two was the loophole
INC-V2-010 named.

Resolution is total: every construct receives one of the four states. Nothing
falls through to a default that quietly means "fine".
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from markup_policy import (
    ATTRIBUTE_PREFIXES,
    ATTRIBUTES,
    CHARACTER_REFERENCES,
    EXTERNAL_DEPENDENCY,
    IGNORED,
    MODELED,
    POLICY,
    POLICY_ID,
    SYNTAX_RESIDUE,
    TAGS,
    TEXT_DATA,
    UNMODELED,
    UNRESOLVED,
    WHITESPACE_ONLY_DATA,
)

#: The three states that block question-local coverage completeness. UNRESOLVED
#: is deliberately among them: it is the third option that exists so a construct
#: with possible meaning is never forced into IGNORED.
BLOCKS_COMPLETENESS = (UNMODELED, UNRESOLVED)


def policy_digest() -> str:
    """A digest over the declared mapping, not over the file that holds it.

    Reformatting, re-ordering comments or rewrapping a justification leaves this
    unchanged. Reclassifying one attribute moves it. That is the property the
    seal needs, and a file-bytes hash does not have it.
    """
    blob = json.dumps(POLICY, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def schema_digest() -> str:
    """A digest over the shape a classification result takes."""
    schema = {
        "result": ["construct", "kind", "state", "facet", "why", "control_fact"],
        "states": list(BLOCKS_COMPLETENESS) + [MODELED, IGNORED],
        "policy_id": POLICY_ID,
    }
    blob = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _result(construct: str, kind: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "construct": construct,
        "kind": kind,
        "state": entry["state"],
        "facet": entry.get("facet"),
        "why": entry.get("why") or entry.get("means") or "",
        "control_fact": bool(entry.get("control_fact")),
    }


def classify_attribute(name: str, value: str | None = None) -> dict[str, Any]:
    """Classify one attribute. Unknown names are UNMODELED, never ignored."""
    lowered = name.lower()
    entry = ATTRIBUTES.get(lowered)
    if entry is not None:
        return _result(lowered, "attribute", entry)
    for prefix, prefixed in ATTRIBUTE_PREFIXES:
        if lowered.startswith(prefix):
            return _result(lowered, "attribute", prefixed)
    return _result(
        lowered,
        "attribute",
        {
            "state": UNMODELED,
            "facet": None,
            "why": (
                "not in the declared policy. An unknown attribute is surfaced, "
                "never assumed decorative — assuming is how the previous policy "
                "acquired fourteen wrong entries."
            ),
        },
    )


def classify_tag(name: str) -> dict[str, Any]:
    """Classify one element. Unknown elements are UNMODELED."""
    lowered = name.lower()
    entry = TAGS.get(lowered)
    if entry is not None:
        return _result(lowered, "tag", entry)
    return _result(
        lowered,
        "tag",
        {
            "state": UNMODELED,
            "facet": None,
            "why": "not in the declared policy; an unknown element may carry structure",
        },
    )


def classify_character_reference(text: str) -> dict[str, Any]:
    return _result(text, "character_reference", CHARACTER_REFERENCES)


def classify_text(text: str, *, preserved: bool = False) -> dict[str, Any]:
    """Character data. Whitespace between elements is ignorable; inside ``pre`` it is not."""
    if not preserved and not text.strip():
        return _result("whitespace", "text", WHITESPACE_ONLY_DATA)
    return _result(text[:40], "text", TEXT_DATA)


def classify_syntax_residue(text: str) -> dict[str, Any]:
    """Angle brackets and closing slashes only. Never a whole tag."""
    return _result(
        text,
        "syntax_residue",
        {
            "state": IGNORED,
            "facet": None,
            "why": (
                "the delimiter characters themselves. The element they delimit is "
                "classified separately and is usually STRUCTURAL; only the "
                "punctuation is residue."
            ),
        },
    )


def blocks_completeness(state: str) -> bool:
    return state in BLOCKS_COMPLETENESS


def summary() -> dict[str, Any]:
    """Counts by state and facet, for the protocol receipt."""
    by_state: dict[str, int] = {}
    by_facet: dict[str, int] = {}
    for source in (ATTRIBUTES, TAGS):
        for entry in source.values():
            by_state[entry["state"]] = by_state.get(entry["state"], 0) + 1
            facet = entry.get("facet")
            if facet:
                by_facet[facet] = by_facet.get(facet, 0) + 1
    return {
        "policy_id": POLICY_ID,
        "policy_digest": policy_digest(),
        "schema_digest": schema_digest(),
        "declared_attributes": len(ATTRIBUTES),
        "declared_tags": len(TAGS),
        "by_state": by_state,
        "by_facet": by_facet,
        "ignored_entries_all_carry_a_reason": all(
            entry.get("why") for source in (ATTRIBUTES, TAGS)
            for entry in source.values()
            if entry["state"] == IGNORED
        ),
    }
