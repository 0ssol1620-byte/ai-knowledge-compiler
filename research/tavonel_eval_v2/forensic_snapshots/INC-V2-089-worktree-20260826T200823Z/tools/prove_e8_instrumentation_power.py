#!/usr/bin/env python3
"""Prove E8's instrument can fire, by making it fire. Development evidence.

Under the founder's ruling of 2026-08-23 (option b), E8 is a mandatory safety veto
that contributes nothing to the positive PASS arithmetic. That ruling creates an
obligation this tool discharges.

E8's seam is structurally closed: `run_pair` classifies an artifact as planned or
carried, never both, so `required_to_rebuild & carried_forward` is empty by
construction and the check reports zero violations with zero natural gate power on
any cohort. A clean reading from an instrument that could not have fired is
indistinguishable from a clean reading from a dead one. The only thing that tells
them apart is prior proof that the instrument CAN report non-zero.

So: inject real violations, at both stages, and require the raise.

Two boundaries this tool does not cross.

* **This is development evidence and it stays there.** Injected cases are never
  added to a held-out denominator, never counted as pairs, and never reported as
  gate power. They say the detector works. They say nothing about the corpus.
* **It proves the detector fires, not that the system is correct.** A working
  smoke alarm is not a fire-free building. E8's held-out zero still credits
  nothing, exactly as the ruling requires.

The scorer refuses to emit a PASS without the receipt this writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "compiler"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import execution_invariant as invariant  # noqa: E402
from common import now  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "e8-instrumentation-power"

#: (label, required_to_rebuild, executed, carried_forward).
#:
#: Each is a defect of the shape SFI2 exhibited: an artifact that had to be rebuilt,
#: whose rebuild was not executed, reused anyway. The names are synthetic. The 14
#: SFI2 cases are deliberately NOT used — a case that diagnosed a defect cannot
#: certify the detector for it, and these must remain injections rather than
#: replays.
INJECTIONS: tuple[tuple[str, set[str], set[str], set[str]], ...] = (
    (
        "single_artifact",
        {"section:a"},
        set(),
        {"section:a"},
    ),
    (
        "one_of_several_slips_through",
        {"section:a", "section:b", "section:c"},
        {"section:a", "section:c"},
        {"section:b"},
    ),
    (
        "deepest_hop_of_a_three_hop_chain",
        {"chain:a", "chain:b", "chain:c"},
        {"chain:a", "chain:b"},
        {"chain:c"},
    ),
    (
        "every_required_artifact_carried",
        {"section:a", "section:b"},
        set(),
        {"section:a", "section:b"},
    ),
)

#: A defect must be caught at BOTH stages. One scheduler defect reaching ACTIVE
#: state is what the second stage exists to prevent, so an instrument proven only
#: after execution leaves that path unwatched.
STAGES: tuple[str, ...] = (
    invariant.STAGE_POST_EXECUTION,
    invariant.STAGE_PRE_ACTIVATION,
)


def _controls() -> list[dict[str, Any]]:
    """Negative controls: clean inputs must NOT raise.

    Without these the receipt would be satisfied by a check that raises
    unconditionally, which is not a detector — it is an outage. A gate that fires
    on everything is as useless as one that fires on nothing, and only the pair of
    results distinguishes a real instrument from either.
    """
    rows: list[dict[str, Any]] = []
    for stage in STAGES:
        raised = False
        try:
            invariant.check_no_unexecuted_carry_forward(
                required_to_rebuild={"section:a", "section:b"},
                executed={"section:a", "section:b"},
                carried_forward={"section:z"},
                stage=stage,
            )
        except invariant.InvariantViolation:
            raised = True
        rows.append({"stage": stage, "raised": raised, "expected_raise": False})
    return rows


def run() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for label, required, executed, carried in INJECTIONS:
        for stage in STAGES:
            raised = False
            named: list[str] = []
            try:
                invariant.check_no_unexecuted_carry_forward(
                    required_to_rebuild=set(required),
                    executed=set(executed),
                    carried_forward=set(carried),
                    stage=stage,
                )
            except invariant.InvariantViolation as violation:
                raised = True
                #: the message must NAME the artifacts. A count cannot be checked
                #: against a rebuild.
                named = sorted(a for a in required & carried if a in str(violation))
            results.append(
                {
                    "injection": label,
                    "stage": stage,
                    "raised": raised,
                    "expected_raise": True,
                    "expected_violating_artifacts": sorted(required & carried),
                    "named_in_message": named,
                }
            )

    controls = _controls()
    raised_rows = [row for row in results if row["raised"]]
    missed = [row for row in results if not row["raised"]]
    unnamed = [
        row
        for row in raised_rows
        if set(row["named_in_message"]) != set(row["expected_violating_artifacts"])
    ]
    false_positives = [row for row in controls if row["raised"]]

    return {
        "schema": "tavonel.v2.e8_instrumentation_power.v1",
        "generated_at": now(),
        "split": "development",
        "endpoint": "E8_no_rebuild_required_artifact_carried_without_execution",
        "classification": "mandatory safety veto (founder ruling 2026-08-23, option b)",
        "stages": list(STAGES),
        "injections_total": len(results),
        "injections_raised": len(raised_rows),
        "injections_not_raised": len(missed),
        "injections_missed": missed,
        "violating_artifacts_not_named": unnamed,
        "controls_total": len(controls),
        "control_false_positives": len(false_positives),
        "results": results,
        "controls": controls,
        "what_this_establishes": (
            "E8's check raises InvariantViolation on an injected unexecuted carry, at "
            "both stages, and does not raise on clean input"
        ),
        "what_this_does_not_establish": [
            "that the system is correct. A working detector is not an absent defect.",
            "any held-out result. These injections are synthetic development "
            "fixtures and are never counted as pairs, denominators or gate power.",
            "that E8 has natural gate power. It does not: the seam is structurally "
            "closed, and a held-out zero still credits nothing.",
        ],
        "never_mixed_into_held_out_denominator": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-receipt", action="store_true")
    arguments = parser.parse_args(argv)

    body = run()
    proven = (
        body["injections_not_raised"] == 0
        and body["injections_raised"] == body["injections_total"]
        and body["control_false_positives"] == 0
        and not body["violating_artifacts_not_named"]
    )
    body["proven"] = proven

    if arguments.write_receipt:
        if not proven:
            print(
                "instrumentation power NOT proven; refusing to write a receipt that "
                "would let the scorer treat E8 as validated",
                file=sys.stderr,
            )
            print(json.dumps(body, indent=2, ensure_ascii=False))
            return 4
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))

    print(
        json.dumps(
            {
                "proven": proven,
                "injections_raised": body["injections_raised"],
                "injections_not_raised": body["injections_not_raised"],
                "control_false_positives": body["control_false_positives"],
                "receipt": body.get("receipt"),
            },
            indent=2,
        )
    )
    return 0 if proven else 4


if __name__ == "__main__":
    raise SystemExit(main())
