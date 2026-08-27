#!/usr/bin/env python3
"""Seal the composite instrument identity, and run the markup controls.

INC-V2-011 recorded that P4f defined instrument identity as a single tool digest
while simultaneously requiring a markup-policy change. Those cannot both hold. A
successor protocol therefore defines identity as a **composition**:

    source-map code digest
  + witness code digest
  + markup-semantics policy digest
  + schema digest

All four are frozen before any result. A change to any one moves the composite,
so policy semantics can no longer drift behind an unchanged tool hash and
resolution logic can no longer drift behind an unchanged policy.

The eight markup controls run here, in the same execution that computes the
seal, so the sealed identity is one that has been shown to behave.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))

from common import NS, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from markup_controls import (  # noqa: E402
    CONTROLS,
    NEGATIVE_DIRECTION_CONTROL,
    POSITIVE_DIRECTION_CONTROLS,
    THIRD_STATE_CONTROL,
)
from markup_policy import ATTRIBUTES, IGNORED, MODELED, TAGS, UNMODELED, UNRESOLVED  # noqa: E402
from markup_semantics import (  # noqa: E402
    classify_attribute,
    classify_character_reference,
    classify_tag,
    policy_digest,
    schema_digest,
    summary,
)

PROTOCOL = NS / "protocols" / "MARKUP_SEMANTICS_V1.yaml"
SOURCE_MAP = NS / "canonicalization" / "source_map.py"
WITNESS = NS / "canonicalization" / "coverage_witness.py"
SEMANTICS = NS / "canonicalization" / "markup_semantics.py"
POLICY_FILE = NS / "canonicalization" / "markup_policy.py"
CONTROLS_FILE = NS / "canonicalization" / "markup_controls.py"


def classify(control: dict[str, Any]) -> dict[str, Any]:
    kind = control["kind"]
    if kind == "attribute":
        return classify_attribute(control["construct"])
    if kind == "tag":
        return classify_tag(control["construct"])
    return classify_character_reference(control["construct"])


def run_controls() -> dict[str, Any]:
    results = []
    for control in CONTROLS:
        got = classify(control)
        results.append(
            {
                "name": control["name"],
                "construct": control["construct"],
                "differs_in": control["differs_in"],
                "same_visible_tokens": control["same_visible_tokens"],
                "expected_state": control["expect_state"],
                "expected_facet": control["expect_facet"],
                "observed_state": got["state"],
                "observed_facet": got["facet"],
                "agrees": got["state"] == control["expect_state"]
                and got["facet"] == control["expect_facet"],
                "control_fact": got["control_fact"],
                "guards": control["guards"],
            }
        )
    by_name = {result["name"]: result for result in results}
    return {
        "results": results,
        "all_agree": all(result["agrees"] for result in results),
        "three_directions": {
            "modeled": all(by_name[name]["agrees"] for name in POSITIVE_DIRECTION_CONTROLS),
            "unresolved": by_name[THIRD_STATE_CONTROL]["agrees"],
            "ignored": by_name[NEGATIVE_DIRECTION_CONTROL]["agrees"],
            "passed": (
                all(by_name[name]["agrees"] for name in POSITIVE_DIRECTION_CONTROLS)
                and by_name[THIRD_STATE_CONTROL]["agrees"]
                and by_name[NEGATIVE_DIRECTION_CONTROL]["agrees"]
            ),
        },
    }


def composite_identity() -> dict[str, Any]:
    parts = {
        "source_map_code": sha_file(SOURCE_MAP),
        "witness_code": sha_file(WITNESS),
        "markup_semantics_code": sha_file(SEMANTICS),
        "markup_policy": policy_digest(),
        "schema": schema_digest(),
    }
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return {
        "parts": parts,
        "composite": "sha256:" + sha256(blob.encode("utf-8")).hexdigest(),
        "definition": (
            "source-map code digest + witness code digest + markup-semantics "
            "policy digest + schema digest. A change to any one moves the "
            "composite, which is what INC-V2-011 requires."
        ),
        "policy_digest_is_over": "the declared mapping, not the file bytes",
    }


def main() -> int:
    started = now()
    controls = run_controls()
    identity = composite_identity()
    stats = summary()

    # the probe must name a construct the policy declares NOWHERE — not by name
    # and not by prefix. The first attempt used a ``data-`` name, which the
    # policy DOES declare (as UNRESOLVED, by prefix rule), so it tested nothing.
    # See the conformance note in the ledger.
    unknown_attribute = classify_attribute("binding")
    unknown_tag = classify_tag("policyref")
    totality = all(
        classify_attribute(name)["state"] in {MODELED, IGNORED, UNRESOLVED, UNMODELED}
        for name in list(ATTRIBUTES) + ["totally-unknown"]
    ) and all(
        classify_tag(name)["state"] in {MODELED, IGNORED, UNRESOLVED, UNMODELED}
        for name in list(TAGS) + ["totally-unknown"]
    )

    gates = {
        "G_MS1_CONTROLS": {"passed": controls["all_agree"], "count": len(CONTROLS)},
        "G_MS1_THREE_DIRECTIONS": {
            "passed": controls["three_directions"]["passed"],
            "detail": controls["three_directions"],
        },
        "G_MS1_EVERY_IGNORE_HAS_A_REASON": {"passed": stats["ignored_entries_all_carry_a_reason"]},
        "G_MS1_RESOLUTION_IS_TOTAL": {"passed": totality},
        "G_MS1_UNKNOWN_IS_NOT_IGNORED": {
            "passed": unknown_attribute["state"] == UNMODELED and unknown_tag["state"] == UNMODELED,
            "unknown_attribute": unknown_attribute["state"],
            "unknown_tag": unknown_tag["state"],
        },
        "G_MS1_POLICY_SEALED_SEPARATELY": {
            "passed": identity["parts"]["markup_policy"]
            != identity["parts"]["markup_semantics_code"],
            "policy_digest": identity["parts"]["markup_policy"],
            "code_digest": identity["parts"]["markup_semantics_code"],
        },
        "G_MS1_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }
    verdict = "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL"

    body: dict[str, Any] = {
        "schema": "tavonel.v2.markup_semantics.v1",
        "protocol": "MARKUP_SEMANTICS_V1",
        "started_at": started,
        "ended_at": now(),
        "programme_status": "PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT YET ESTABLISHED",
        "instrument_identity": identity,
        "policy_summary": stats,
        "controls": controls,
        "sources": {
            "policy": rel(POLICY_FILE),
            "semantics": rel(SEMANTICS),
            "controls": rel(CONTROLS_FILE),
        },
        "predecessors_read_only": {
            "P0d": "PASS on its own gates; result stands under its declared grammar",
            "SOURCE_LOCALITY_V2": "PASS; eligible Q1 = 5; not re-scored",
            "P4e": "Core PASS 12/12; not re-scored",
            "P4f": "SUPERSEDED_BEFORE_EXECUTION, never run, preserved unmodified",
        },
        "incidents": ["INC-V2-010", "INC-V2-011"],
        "gates": gates,
        "verdict": verdict,
        "gpu_authorised_by_this_result": False,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable(
        "markup-semantics-v1", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "controls_all_agree": controls["all_agree"],
                "three_directions": controls["three_directions"]["passed"],
                "composite_identity": identity["composite"],
                "policy_digest": identity["parts"]["markup_policy"],
                "schema_digest": identity["parts"]["schema"],
                "declared": {
                    "attributes": stats["declared_attributes"],
                    "tags": stats["declared_tags"],
                },
                "by_state": stats["by_state"],
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
