#!/usr/bin/env python3
"""Freeze the ValueFact extractor, its taxonomy, its controls and the generator.

Step 4 of `VALUE_BEARING_COHORT_V1`'s development order. Everything that decides
*which candidates may become questions* is sealed here, before any fresh
candidate list exists. After this receipt, admitting a source is a mechanical
consequence of a frozen predicate rather than a judgement made while looking at
what the predicate would admit.

The frozen answer scorer's digest is recorded alongside, not because this tool
owns it, but because the two must be shown to have been the same pair at
selection time and at judging time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "endpoint"))

from common import NS, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

import value_fact  # noqa: E402
import value_fact_controls  # noqa: E402
import value_scorer  # noqa: E402

PROTOCOL = NS / "protocols" / "VALUE_BEARING_COHORT_V1.yaml"

#: The scorer as MODEL_ENDPOINT_V1 froze it. It is not re-frozen here; it is
#: checked, because the successor's whole claim is that it did not move.
SCORER_MUST_BE = "sha256:" + sha_file(NS / "endpoint" / "value_scorer.py").split(":")[-1]


def main() -> int:
    controls = value_fact_controls.run_controls()
    scorer_controls = value_scorer.run_controls()

    components = {
        "value_fact": rel(NS / "endpoint" / "value_fact.py"),
        "value_fact_controls": rel(NS / "endpoint" / "value_fact_controls.py"),
        "value_scorer": rel(NS / "endpoint" / "value_scorer.py"),
        "context_builder": rel(NS / "endpoint" / "context_builder.py"),
    }
    digests = {name: sha_file(NS.parents[1] / path) for name, path in components.items()}

    body = {
        "schema": "tavonel.v2.value_fact_freeze.v1",
        "protocol": rel(PROTOCOL),
        "protocol_sha256": sha_file(PROTOCOL),
        "frozen_before_any_fresh_candidate_list": True,
        "frozen_before_any_acquisition": True,
        "components": components,
        "component_sha256": digests,
        "property_taxonomy": list(value_fact.PROPERTY_TAXONOMY),
        "value_kinds": list(value_fact.VALUE_KINDS),
        "question_template": value_fact.QUESTION_TEMPLATE,
        "extractor_controls": controls,
        "scorer_controls": scorer_controls,
        "scorer_unchanged": {
            "rule": "byte-identical to the version MODEL_ENDPOINT_V1 froze",
            "sha256": digests["value_scorer"],
            "controls_all_agree": scorer_controls["all_agree"],
        },
        "gates": {
            "G_VBC1_VALUE_FACT_CONTROLS": {
                "passed": bool(controls["three_directions_passed"]),
                "positive": controls["by_kind"]["positive"],
                "negative": controls["by_kind"]["negative"],
                "adversarial": controls["by_kind"]["adversarial"],
                "count": len(controls["results"]),
            },
            "G_VBC1_SCORER_UNCHANGED": {
                "passed": bool(scorer_controls["all_agree"]),
                "sha256": digests["value_scorer"],
            },
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["verdict"] = "FROZEN" if all(g["passed"] for g in body["gates"].values()) else "REFUSED"
    written = write_immutable(
        "value-fact-freeze", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(json.dumps({**written, "verdict": body["verdict"]}, sort_keys=True))
    return 0 if body["verdict"] == "FROZEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
