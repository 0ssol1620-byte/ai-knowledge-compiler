"""Frozen controls for the changed-region instrument. SOURCE_FAITHFULNESS_HELDOUT_V1 §5.

A run in which the grammar happened to classify everything reads exactly like a
run in which the residue check does not work. These fixtures make the difference
observable, and two of them are burned on purpose:

``burned_reference_target_only``
    the INC-V2-006 shape. Only a link target moves. The grammar calls the region
    MODELED and the compiled state does not carry it. If the instrument reports
    this as a clean pair, the instrument is broken and every held-out number it
    produces is worthless.

``burned_short_block_dropped``
    the canonicaliser discards a block shorter than its minimum text length. The
    source changed, the compiled state has no unit at all, and nothing about the
    markup is unusual. A faithfulness instrument that only watches markup misses
    this entirely.

The adversarial fixtures are the other half. An instrument that flags emphasis
markers or whitespace as losses would produce a large, alarming and meaningless
number, which is a different way of being useless.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical_document import canonical_document  # noqa: E402
from source_map import LOCATION_UNVERIFIABLE, LocatedSpan  # noqa: E402
from changed_regions import (  # noqa: E402
    IGNORED,
    MODELED,
    UNCLASSIFIED,
    UNRESOLVED,
    UNVERIFIED,
    VERIFIED,
    classify_pair,
    regions,
)

#: Long enough to clear canonical_document's minimum text length, except where a
#: fixture is deliberately short.
FILLER = (
    "This paragraph is written long enough to clear the canonicaliser minimum "
    "text length so that the unit actually exists and the comparison is about "
    "the construct under test rather than about a dropped block."
)


def _document(text: str, family: str) -> dict[str, Any]:
    return canonical_document(
        source_family=family,
        source_id="control",
        version_id="v",
        payload=text.encode("utf-8"),
        source_digest="sha256:control",
        known_at=None,
        valid_from=None,
        licence="control",
    )


def _pair(before: str, after: str, suffix: str) -> dict[str, Any]:
    family = "git_docs" if suffix == ".md" else "sec_edgar"
    return classify_pair(
        before_raw=before,
        after_raw=after,
        before_document=_document(before, family),
        after_document=_document(after, family),
        suffix=suffix,
    )


_MD_LINK_BEFORE = "# Retention\n\nSee [the guide](https://example.com/old) for details. " + FILLER + "\n"
_MD_LINK_AFTER = _MD_LINK_BEFORE.replace("example.com/old", "example.com/new")

_MD_PROSE_BEFORE = "# Retention\n\nSamples are kept for 30 days. " + FILLER + "\n"
_MD_PROSE_AFTER = _MD_PROSE_BEFORE.replace("30 days", "90 days")

_MD_HEADING_BEFORE = "# Retention policy\n\n" + FILLER + "\n"
_MD_HEADING_AFTER = "# Retention schedule\n\n" + FILLER + "\n"

_MD_EMPH_BEFORE = "# Retention\n\nSome **bold** words. " + FILLER + "\n"
_MD_EMPH_AFTER = _MD_EMPH_BEFORE.replace("**bold**", "*bold*")

_MD_WS_BEFORE = "# Retention\n\n" + FILLER + "\n"
_MD_WS_AFTER = "# Retention\n\n" + FILLER + "   \n"

_MD_COMMENT_BEFORE = "# Retention\n\n<!-- editors: check this -->\n\n" + FILLER + "\n"
_MD_COMMENT_AFTER = "# Retention\n\n<!-- editors: rechecked, fine -->\n\n" + FILLER + "\n"

_MD_DELETE_BEFORE = "# Retention\n\n" + FILLER + "\n\nSecond block. " + FILLER + "\n"
_MD_DELETE_AFTER = "# Retention\n\n" + FILLER + "\n"

#: The short block needs its own heading. Blocks under one heading are joined
#: before the length test, so a short paragraph following a long one is carried
#: by its neighbour and nothing is dropped.
_MD_SHORT_BEFORE = "# Retention\n\n" + FILLER + "\n\n## Note\n\nKept 30 days.\n"
_MD_SHORT_AFTER = "# Retention\n\n" + FILLER + "\n\n## Note\n\nKept 90 days.\n"

_HTML_HREF_BEFORE = (
    "<html><body><h1>Retention</h1>"
    '<p>See <a href="https://example.com/old">the guide</a>. ' + FILLER + "</p></body></html>"
)
_HTML_HREF_AFTER = _HTML_HREF_BEFORE.replace("example.com/old", "example.com/new")

_HTML_TEXT_BEFORE = (
    "<html><body><h1>Retention</h1><p>Samples are kept for 30 days. " + FILLER + "</p></body></html>"
)
_HTML_TEXT_AFTER = _HTML_TEXT_BEFORE.replace("30 days", "90 days")

_HTML_COLSPAN_BEFORE = (
    "<html><body><h1>Limits</h1><table><tr><th colspan=\"2\">Limits</th></tr>"
    "<tr><td>Retention</td><td>30</td></tr></table><p>" + FILLER + "</p></body></html>"
)
_HTML_COLSPAN_AFTER = _HTML_COLSPAN_BEFORE.replace('colspan="2"', 'colspan="3"')

#: No natural fixture reached UNCLASSIFIED. The HTML scanner assigns a verified
#: position to every event it emits — declarations, processing instructions,
#: CDATA, duplicate attributes, NUL bytes and unbalanced angle brackets were all
#: tried and all came back located. The one route left is the scanner's own
#: parse-failure span, which it emits with no position at all.
#:
#: So the reachability control constructs exactly that span and drives the
#: region assembler with it. A gate whose failure state cannot be reached proves
#: nothing; a gate reachable only through a parse failure is a different and
#: better fact, and it is stated here rather than implied.
_PARSE_FAILURE_TEXT = "<html><body><p>" + FILLER + "</p></body></html>"


def _parse_failure_regions() -> dict[str, Any]:
    """Drive the region assembler with the span the scanner emits when it cannot parse."""
    span = LocatedSpan(
        None, None, "parse_failure", "UNMODELED_SOURCE_FACT", "", None,
        LOCATION_UNVERIFIABLE, "constructed reachability control",
    )
    rows = regions(_PARSE_FAILURE_TEXT, [span], [(0, len(_PARSE_FAILURE_TEXT))], "after")
    for row in rows:
        row.update({"verification": "NOT_A_MODELED_CLAIM", "verification_reason": None})
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return {
        "rows": rows,
        "by_state": counts,
        "region_count": len(rows),
        "modeled_claims": 0,
        "modeled_claims_unverified": 0,
        "blocking_regions": 0,
        "compiled_state_changed": False,
        "unclassified": counts.get(UNCLASSIFIED, 0),
    }


def _states(result: dict[str, Any]) -> set[str]:
    return {row["state"] for row in result["rows"]}


def _verifications(result: dict[str, Any]) -> set[str]:
    return {row["verification"] for row in result["rows"] if row["state"] == MODELED}


CONTROLS: list[dict[str, Any]] = [
    {
        "name": "burned_reference_target_only",
        "kind": "burned_positive",
        "why": (
            "INC-V2-006 on a fixture. Only the link target moves; the compiled "
            "state cannot carry it and must not be reported as clean."
        ),
        "run": lambda: _pair(_MD_LINK_BEFORE, _MD_LINK_AFTER, ".md"),
        "expect": lambda r: (
            r["modeled_claims_unverified"] >= 1
            and r["compiled_state_changed"] is False
            and r["unclassified"] == 0
        ),
    },
    {
        "name": "burned_short_block_dropped",
        "kind": "burned_positive",
        "why": (
            "the canonicaliser discards blocks below its minimum text length. "
            "The source changed and no unit exists to carry it."
        ),
        "run": lambda: _pair(_MD_SHORT_BEFORE, _MD_SHORT_AFTER, ".md"),
        "expect": lambda r: r["blocking_regions"] >= 1,
    },
    {
        "name": "burned_html_href_only",
        "kind": "burned_positive",
        "why": "the same loss in the markup grammar, where the facet map is what catches it",
        "run": lambda: _pair(_HTML_HREF_BEFORE, _HTML_HREF_AFTER, ".html"),
        "expect": lambda r: r["modeled_claims_unverified"] >= 1 or r["blocking_regions"] >= 1,
    },
    {
        "name": "positive_prose_value_change_is_verified",
        "kind": "positive",
        "why": "a number inside prose does reach the compiled state and must verify",
        "run": lambda: _pair(_MD_PROSE_BEFORE, _MD_PROSE_AFTER, ".md"),
        "expect": lambda r: (
            VERIFIED in _verifications(r)
            and r["compiled_state_changed"] is True
            and r["unclassified"] == 0
        ),
    },
    {
        "name": "positive_heading_change_is_verified",
        "kind": "positive",
        "why": "headings are one of the four things a compiled artifact carries",
        "run": lambda: _pair(_MD_HEADING_BEFORE, _MD_HEADING_AFTER, ".md"),
        "expect": lambda r: (
            VERIFIED in _verifications(r) and r["compiled_state_changed"] is True
        ),
    },
    {
        "name": "positive_html_text_change_is_verified",
        "kind": "positive",
        "why": "character data traceable into canonical text verifies in the markup grammar too",
        "run": lambda: _pair(_HTML_TEXT_BEFORE, _HTML_TEXT_AFTER, ".html"),
        "expect": lambda r: (
            VERIFIED in _verifications(r) and r["compiled_state_changed"] is True
        ),
    },
    {
        "name": "negative_html_comment_change_is_ignored",
        "kind": "negative",
        "why": "an editorial comment is declared non-semantic by the frozen policy",
        "run": lambda: _pair(_MD_COMMENT_BEFORE, _MD_COMMENT_AFTER, ".md"),
        "expect": lambda r: (
            IGNORED in _states(r)
            and MODELED not in _states(r)
            and r["unclassified"] == 0
        ),
    },
    {
        "name": "adversarial_emphasis_markers_are_not_a_loss",
        "kind": "adversarial",
        "why": (
            "an instrument that scores punctuation as a lost fact produces a "
            "large alarming number that means nothing"
        ),
        "run": lambda: _pair(_MD_EMPH_BEFORE, _MD_EMPH_AFTER, ".md"),
        "expect": lambda r: r["modeled_claims_unverified"] == 0 and r["unclassified"] == 0,
    },
    {
        "name": "adversarial_trailing_whitespace_is_not_a_loss",
        "kind": "adversarial",
        "why": "whitespace folds away under the frozen projection and must not register",
        "run": lambda: _pair(_MD_WS_BEFORE, _MD_WS_AFTER, ".md"),
        "expect": lambda r: r["modeled_claims_unverified"] == 0 and r["unclassified"] == 0,
    },
    {
        "name": "adversarial_structural_attribute_is_seen_not_ignored",
        "kind": "adversarial",
        "why": (
            "colspan changes which header a cell belongs to. INC-V2-010 records "
            "the old policy calling it presentation; it must not be IGNORED here."
        ),
        "run": lambda: _pair(_HTML_COLSPAN_BEFORE, _HTML_COLSPAN_AFTER, ".html"),
        "expect": lambda r: any(
            row["state"] != IGNORED for row in r["rows"] if "colspan" in row["sample"]
        )
        or r["blocking_regions"] >= 1,
    },
    {
        "name": "deletion_is_seen_on_the_side_it_happened",
        "kind": "positive",
        "why": (
            "a deleted region has no position in the newer revision. Scoring only "
            "the newer side would blind this protocol to whole blocks vanishing."
        ),
        "run": lambda: _pair(_MD_DELETE_BEFORE, _MD_DELETE_AFTER, ".md"),
        "expect": lambda r: any(row["side"] == "before" for row in r["rows"]),
    },
    {
        "name": "unclassified_is_reachable",
        "kind": "reachability",
        "why": (
            "the hard-failure state must be producible, or the gate that forbids "
            "it passes by construction. No natural fixture reached it; the "
            "scanner's own parse-failure span is the route, and it is exercised "
            "directly rather than claimed."
        ),
        "run": _parse_failure_regions,
        "expect": lambda r: r["by_state"].get(UNCLASSIFIED, 0) >= 1,
    },
]


def run_controls() -> dict[str, Any]:
    rows = []
    for control in CONTROLS:
        try:
            result = control["run"]()
            passed = bool(control["expect"](result))
            detail = {
                "by_state": result["by_state"],
                "modeled_claims": result["modeled_claims"],
                "modeled_claims_unverified": result["modeled_claims_unverified"],
                "blocking_regions": result["blocking_regions"],
                "compiled_state_changed": result["compiled_state_changed"],
                "unclassified": result["unclassified"],
            }
        except Exception as error:  # a control that crashes is a failed control
            passed = False
            detail = {"error": "%s: %s" % (type(error).__name__, error)}
        rows.append(
            {
                "name": control["name"],
                "kind": control["kind"],
                "why": control["why"],
                "passed": passed,
                "detail": detail,
            }
        )
    return {
        "controls": rows,
        "total": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "all_passed": all(row["passed"] for row in rows),
        "failed": [row["name"] for row in rows if not row["passed"]],
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_controls(), indent=2, ensure_ascii=False))
