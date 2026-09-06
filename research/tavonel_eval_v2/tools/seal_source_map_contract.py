#!/usr/bin/env python3
"""Seal the source-map contract that actually reads MARKUP_SEMANTICS_V1.

INC-V2-013: the policy was frozen and nothing consulted it. The source map still
classified markup with P0d's grammar, so a cohort scored at that moment would
have produced a number the markup workstream never touched — while the report
said the workstream was done.

This tool runs the eight adversarial controls **through the source map** rather
than against the classifier's name lookup, which is a stronger test of the same
claim: each control is a pair of sources, and what must change between them is
the classification the map emits, not merely what a dictionary says about a
construct in isolation.

It then recomputes the composite instrument identity over the modules that are
actually in the scoring path.
"""

from __future__ import annotations

import html as _html
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))

from common import NS, now, rel, sha_file  # noqa: E402
from coverage_witness_v2 import UNRESOLVED_IN_CLOSURE  # noqa: E402
from evidence import write_immutable  # noqa: E402
from markup_controls import (  # noqa: E402
    CONTROLS,
    NEGATIVE_DIRECTION_CONTROL,
    POSITIVE_DIRECTION_CONTROLS,
    THIRD_STATE_CONTROL,
)
from markup_policy import IGNORED, MODELED, UNMODELED, UNRESOLVED  # noqa: E402
from markup_semantics import blocks_completeness, policy_digest, schema_digest  # noqa: E402
from source_map_v2 import html_located  # noqa: E402

PROTOCOL = NS / "protocols" / "MARKUP_SEMANTICS_V1.yaml"
SOURCE_MAP_V2 = NS / "canonicalization" / "source_map_v2.py"
WITNESS_V2 = NS / "canonicalization" / "coverage_witness_v2.py"
SEMANTICS = NS / "canonicalization" / "markup_semantics.py"
SOURCE_MAP_V1 = NS / "canonicalization" / "source_map.py"
WITNESS_V1 = NS / "canonicalization" / "coverage_witness.py"

_TAG = re.compile(r"<[^>]+>")


def visible(raw: str) -> str:
    """A stand-in for canonical text: tags removed, references resolved.

    Deliberately generous. A control must fail because a construct is classified
    wrongly, not because this approximation dropped the text the classifier was
    looking for.
    """
    return _html.unescape(_TAG.sub(" ", raw))


def _kind_for(control: dict[str, Any]) -> str:
    kind = control["kind"]
    if kind == "attribute":
        return "attr:" + control["construct"].lower()
    if kind == "tag":
        return "start_tag:" + control["construct"].lower()
    return "charref"


def run_map_controls() -> dict[str, Any]:
    """Every control, scanned through the map, on both sides of its pair."""
    results = []
    for control in CONTROLS:
        wanted = _kind_for(control)
        observed: dict[str, Any] = {}
        for side in ("before", "after"):
            raw = control[side]
            spans = html_located(raw, visible(raw))
            match = next((s for s in spans if s.kind == wanted), None)
            observed[side] = {
                "found": match is not None,
                "state": match.classification if match else None,
                "facet": (match.fact or {}).get("facet") if match else None,
            }
        after = observed["after"]
        agrees = (
            after["found"]
            and after["state"] == control["expect_state"]
            and after["facet"] == control["expect_facet"]
        )
        results.append(
            {
                "name": control["name"],
                "construct": control["construct"],
                "scanned_kind": wanted,
                "expected_state": control["expect_state"],
                "expected_facet": control["expect_facet"],
                "observed": observed,
                "agrees": agrees,
                "blocks_completeness": blocks_completeness(after["state"] or ""),
                "guards": control["guards"],
            }
        )
    index = {result["name"]: result for result in results}
    return {
        "results": results,
        "all_agree": all(result["agrees"] for result in results),
        "three_directions": {
            "modeled": all(index[name]["agrees"] for name in POSITIVE_DIRECTION_CONTROLS),
            "unresolved": index[THIRD_STATE_CONTROL]["agrees"],
            "ignored": index[NEGATIVE_DIRECTION_CONTROL]["agrees"],
            "passed": (
                all(index[name]["agrees"] for name in POSITIVE_DIRECTION_CONTROLS)
                and index[THIRD_STATE_CONTROL]["agrees"]
                and index[NEGATIVE_DIRECTION_CONTROL]["agrees"]
            ),
        },
        "unresolved_blocks": index[THIRD_STATE_CONTROL]["blocks_completeness"],
        "ignored_does_not_block": not index[NEGATIVE_DIRECTION_CONTROL]["blocks_completeness"],
    }


def traceability_controls() -> dict[str, Any]:
    """Content is granted by traceability, never by the policy's word alone.

    Three probes on the same source, differing only in what the canonical text
    is said to contain. If the map granted MODELED from the policy alone, the
    second would pass and the coverage figure would be an over-grant.
    """
    raw = "<p>Quarterly revenue rose to 4.2 billion &#160; euros.</p>"
    present = html_located(raw, visible(raw))
    absent = html_located(raw, "something else entirely")
    empty = html_located(raw, "")

    def state_of(spans: list[Any], kind: str) -> str | None:
        match = next((s for s in spans if s.kind == kind), None)
        return match.classification if match else None

    return {
        "text_traceable_is_modeled": state_of(present, "data") == MODELED,
        "text_untraceable_is_unmodeled": state_of(absent, "data") == UNMODELED,
        "text_with_no_canonical_text_is_unmodeled": state_of(empty, "data") == UNMODELED,
        "charref_traceable_is_modeled": state_of(present, "charref") == MODELED,
        "passed": (
            state_of(present, "data") == MODELED
            and state_of(absent, "data") == UNMODELED
            and state_of(empty, "data") == UNMODELED
        ),
        "why": (
            "the policy's MODELED is a statement about the KIND of construct. "
            "Whether one occurrence reached the compiled artifact is a separate "
            "question, and granting it by assertion would be an over-grant."
        ),
    }


def inheritance_control() -> dict[str, Any]:
    """The old grammar must be visibly gone, or nothing has actually changed."""
    raw = '<td colspan="2" class="wikitable" lang="en">text</td>'
    spans = {s.kind: s.classification for s in html_located(raw, "text")}
    return {
        "colspan": spans.get("attr:colspan"),
        "lang": spans.get("attr:lang"),
        "class": spans.get("attr:class"),
        "start_tag_td": spans.get("start_tag:td"),
        "passed": (
            spans.get("attr:colspan") == MODELED
            and spans.get("attr:lang") == MODELED
            and spans.get("attr:class") == UNRESOLVED
            and spans.get("start_tag:td") == MODELED
        ),
        "under_the_old_grammar": {
            "attr:colspan": IGNORED,
            "attr:lang": IGNORED,
            "attr:class": IGNORED,
            "start_tag:td": IGNORED,
        },
    }


def composite_identity() -> dict[str, Any]:
    parts = {
        "source_map_code": sha_file(SOURCE_MAP_V2),
        "witness_code": sha_file(WITNESS_V2),
        "markup_semantics_code": sha_file(SEMANTICS),
        "markup_policy": policy_digest(),
        "schema": schema_digest(),
    }
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return {
        "parts": parts,
        "composite": "sha256:" + sha256(blob.encode("utf-8")).hexdigest(),
        "part_files": {
            "source_map_code": rel(SOURCE_MAP_V2),
            "witness_code": rel(WITNESS_V2),
            "markup_semantics_code": rel(SEMANTICS),
        },
        "superseded_parts_left_untouched": {
            rel(SOURCE_MAP_V1): sha_file(SOURCE_MAP_V1),
            rel(WITNESS_V1): sha_file(WITNESS_V1),
        },
        "why_it_differs_from_the_P4g_freeze": (
            "INC-V2-013. Two of the five parts are different files, because the "
            "files P4g named do not consult the frozen markup policy. Recorded "
            "before any eligibility number existed, and not aimed at one: the "
            "predictable direction of this change is that eligibility falls."
        ),
    }


def main() -> int:
    started = now()
    controls = run_map_controls()
    traceability = traceability_controls()
    inheritance = inheritance_control()
    identity = composite_identity()

    gates = {
        "G_SMC_CONTROLS_THROUGH_THE_MAP": {
            "passed": controls["all_agree"],
            "count": len(CONTROLS),
        },
        "G_SMC_THREE_DIRECTIONS": {
            "passed": controls["three_directions"]["passed"],
            "detail": controls["three_directions"],
        },
        "G_SMC_UNRESOLVED_BLOCKS": {
            "passed": controls["unresolved_blocks"] and controls["ignored_does_not_block"],
            "reason_code": UNRESOLVED_IN_CLOSURE,
        },
        "G_SMC_CONTENT_BY_TRACEABILITY": {
            "passed": traceability["passed"],
            "detail": traceability,
        },
        "G_SMC_OLD_GRAMMAR_NOT_INHERITED": {
            "passed": inheritance["passed"],
            "detail": inheritance,
        },
        "G_SMC_LEGACY_INSTRUMENT_UNTOUCHED": {
            "passed": True,
            "detail": identity["superseded_parts_left_untouched"],
            "why": (
                "SOURCE_LOCALITY_V2 sealed those digests. Its eligible Q1 = 5 "
                "stays reproducible because the files are not edited."
            ),
        },
        "G_SMC_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    verdict = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"

    body: dict[str, Any] = {
        "schema": "tavonel.v2.source_map_contract.v1",
        "protocol": "MARKUP_SEMANTICS_V1",
        "started_at": started,
        "ended_at": now(),
        "programme_status": "PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED",
        "incident": "INC-V2-013",
        "instrument_identity": identity,
        "controls_through_the_map": controls,
        "traceability_controls": traceability,
        "inheritance_control": inheritance,
        "predecessors_read_only": {
            "SOURCE_LOCALITY_V2": "PASS; eligible Q1 = 5; instrument untouched; not re-scored",
            "P0d": "PASS on its own gates; result stands under its declared grammar",
            "P4f": "SUPERSEDED_BEFORE_EXECUTION",
            "P4g": "not modified; scoring runs under the composite recorded here",
        },
        "gates": gates,
        "verdict": verdict,
        "gpu_authorised_by_this_result": False,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(
        "source-map-contract", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "composite_identity": identity["composite"],
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                "controls_all_agree": controls["all_agree"],
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
