#!/usr/bin/env python3
"""SFIR6's charter freeze. A confirmatory repair, and the gates that keep it one.

SFIR5 applied the capacity criterion and failed. That makes SFIR6 the most
dangerous protocol in this programme so far, because everyone now knows what the
answer was, and every parameter is a chance to make it come out differently.

So the gates here are not mainly about what SFIR6 does. They are about what it
must still be after a defect has been repaired with the outcome already known:

    the frame is unchanged        -- roots, caps, salt, ordering, thresholds
    the repairs are unconditional -- wrong for every input, not just for this one
    the predecessor is preserved  -- SFIR5 is not rescored or superseded
    the verdict is taken as it comes

One gate is deliberately the inverse of SFIR5's. SFIR5 proved its batching was
identical to its predecessor's, and passed, and the batching had never worked
(INC-V2-106). SFIR6 therefore must NOT claim equivalence: it declares new
batching and is refused if it claims otherwise. Equivalence to an ancestor is not
a correctness argument, and this is the gate that stops the study making that
argument twice.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir4_protocol as protocol  # noqa: E402
import sfir5_charter as charter5  # noqa: E402
import sfir5_transport as t5  # noqa: E402
import sfir6_protocol as p6  # noqa: E402
import sfir6_transport  # noqa: E402, F401  -- the transport this charter freezes
import sfir6_wikipedia as wiki  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V6"
CHARTER_SCHEMA = "tavonel.sfir6.design_charter_freeze.v1"
CHARTER_YAML = NS / "protocols" / f"{PROTOCOL_ID}_DESIGN_CHARTER.yaml"
SFIR5_OUTCOME = NS / "receipts" / "sfir5-capacity-outcome.json"
CANARY = NS / "receipts" / "sfir6-adapter-canary.json"

SFIR6Refused = charter5.SFIR5Refused


def require_frame_unchanged(document: Mapping[str, Any]) -> dict[str, Any]:
    """The frame is read from the live modules, never from the document.

    This is the gate that stops `git_docs` quietly gaining a root. It compares
    the charter's declaration against `sources_sfir4` and `sfir4_protocol` as
    they will actually run, so editing either is what turns it red -- a charter
    that merely *says* nothing changed would otherwise be self-certifying.
    """
    block = document.get("unchanged_from_sfir5")
    if not isinstance(block, Mapping):
        raise SFIR6Refused("SFIR6 charter does not declare what it leaves unchanged")
    actual = {
        "git_roots": len(sources.declared_roots("git_docs")),
        "ecfr_roots": len(sources.declared_roots("regulation_ecfr")),
        "wikipedia_roots": len(sources.declared_roots("encyclopedia_wikipedia")),
    }
    declared = {key: block.get(key) for key in actual}
    if declared != actual:
        raise SFIR6Refused(
            f"the declared frame is not the frame that will run: charter {declared}, "
            f"modules {actual}. A root added after SFIR5's result is an "
            "outcome-conditioned redesign, not an instrument repair."
        )
    frozen = (NS / "tools" / "sfir4_protocol.py").read_text(encoding="utf-8")
    if "count < 750 or quota < 600" not in frozen:
        raise SFIR6Refused("the capacity criterion has moved in the frozen module")
    if (
        block.get("minimum_c_per_family") != 750
        or block.get("minimum_q_per_family") != 600
        or block.get("quota_formula") != "Q_f=min(1000,floor(0.8*C_f))"
        or block.get("no_git_root_is_added_after_seeing_293") is not True
    ):
        raise SFIR6Refused("SFIR6 charter restates the criterion incorrectly")
    return {
        **actual,
        "selection_salt_sha256": hashlib.sha256(sources.SELECTION_SALT.encode("utf-8")).hexdigest(),
    }


def require_repairs_are_unconditional(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every declared repair must be wrong for every input, not just for this one.

    The distinction the paper's §10.2 rests on: an unconditional defect has one
    right answer whichever way the census comes out, and a tuning parameter does
    not. With SFIR5's outcome already known, a repair that fails this test is a
    parameter chosen by the failure.
    """
    repairs = document.get("repairs")
    if not isinstance(repairs, list) or not repairs:
        raise SFIR6Refused("SFIR6 charter declares no repairs")
    known = {"INC-V2-106", "INC-V2-107"}
    declared = {row.get("id") for row in repairs if isinstance(row, Mapping)}
    if declared != known:
        raise SFIR6Refused(
            f"SFIR6 repairs exactly {sorted(known)}; charter declares {sorted(declared)}. "
            "A third repair appearing after the outcome is known needs its own scrutiny."
        )
    for row in repairs:
        if not str(row.get("why_unconditional") or "").strip():
            raise SFIR6Refused(f"repair {row.get('id')} does not say why it is unconditional")
    return [dict(row) for row in repairs]


def require_predecessor_preserved(document: Mapping[str, Any]) -> dict[str, Any]:
    """SFIR5 stands. It is not rescored, and its numbers are not carried across."""
    block = document.get("predecessor_result_preserved")
    if not isinstance(block, Mapping):
        raise SFIR6Refused("SFIR6 charter does not preserve SFIR5's result")
    if not SFIR5_OUTCOME.is_file():
        raise SFIR6Refused("SFIR5's outcome receipt is absent")
    outcome = json.loads(SFIR5_OUTCOME.read_text(encoding="utf-8"))
    expected = {
        "regulation_ecfr": "VALID_CAPACITY_MEASUREMENT_PASS",
        "git_docs": "VALID_CAPACITY_MEASUREMENT_FAIL",
        "encyclopedia_wikipedia": "NOT_MEASURED_INSTRUMENT_DEFECT",
    }
    if {key: block.get(key) for key in expected} != expected:
        raise SFIR6Refused("SFIR6 charter misstates SFIR5's per-family disposition")
    if (
        block.get("sfir5_is_not_rescored") is not True
        or block.get("sfir5_numbers_are_not_copied_into_sfir6") is not True
    ):
        raise SFIR6Refused("SFIR6 charter does not undertake to leave SFIR5 alone")
    if outcome.get("state") != "CAPACITY_CRITERION_APPLIED_AND_FAILED":
        raise SFIR6Refused("SFIR5's outcome receipt is not the one this charter describes")
    return {
        "path": charter5.protocol_relative(SFIR5_OUTCOME),
        "sha256": protocol.sha_file(SFIR5_OUTCOME),
        "state": outcome["state"],
    }


def require_batching_is_not_justified_by_equivalence(document: Mapping[str, Any]) -> dict[str, Any]:
    """The inverse of SFIR5's gate, and the reason it exists.

    SFIR5 declared `new_batching_introduced_by_sfir5: false` and a gate verified
    the sizes matched the frozen adapter. It passed. The batching had never
    worked. A check comparing a successor to an ancestor cannot find a defect
    they share, so SFIR6 is refused if it makes that argument: it must declare
    new batching, say why, and point at evidence that is not the predecessor.
    """
    block = document.get("batching_policy")
    if not isinstance(block, Mapping):
        raise SFIR6Refused("SFIR6 charter declares no batching policy")
    if block.get("new_batching_introduced_by_sfir6") is not True:
        raise SFIR6Refused(
            "SFIR6 must declare new batching. Inheriting the predecessor's unchanged "
            "is precisely what INC-V2-106 was."
        )
    if block.get("rvlimit_is_never_sent_with_more_than_one_page") is not True:
        raise SFIR6Refused("SFIR6 charter does not forbid the request shape that failed")
    if not CANARY.is_file():
        raise SFIR6Refused("the adapter canary has not been run against the live endpoint")
    canary = json.loads(CANARY.read_text(encoding="utf-8"))
    if canary.get("state") != "ADAPTER_CANARY_PASS":
        raise SFIR6Refused("the adapter canary did not pass")
    gates = {row["gate"] for row in canary.get("checks", [])}
    required = {
        "pass_1_batched_latest_revision",
        "pass_2_batched_parent_revisions",
        "sfir5_request_shape_still_refused_by_the_live_endpoint",
    }
    if not required <= gates:
        raise SFIR6Refused(f"the canary is missing gates: {sorted(required - gates)}")
    if block.get("population_unchanged") is not True or block.get("ordering_unchanged") is not True:
        raise SFIR6Refused("new batching may not change the population or the ordering")
    return {
        "form": block.get("form"),
        "canary": {"path": charter5.protocol_relative(CANARY), "sha256": protocol.sha_file(CANARY)},
    }


def require_verdict_taken_as_it_comes(document: Mapping[str, Any]) -> dict[str, Any]:
    block = document.get("verdict_policy")
    if (
        not isinstance(block, Mapping)
        or block.get("all_three_families_remeasured") is not True
        or block.get("no_family_result_is_reused_from_sfir5") is not True
        or block.get("verdict_taken_from_sfir6_whatever_it_says") is not True
        or block.get("if_git_fails_again_the_criterion_fails") is not True
        or block.get("lowering_a_threshold_or_adding_a_root_on_failure_is_forbidden") is not True
    ):
        raise SFIR6Refused("SFIR6 charter does not commit to taking its verdict as it comes")
    return dict(block)


def load(charter_yaml: Path = CHARTER_YAML) -> dict[str, Any]:
    if not charter_yaml.is_file():
        raise SFIR6Refused("SFIR6 charter is absent")
    document = yaml.safe_load(charter_yaml.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("protocol_id") != PROTOCOL_ID
        or document.get("state") != "PROSPECTIVE_PRE_CENSUS"
        or document.get("result_blind_design") is not True
        or document.get("succeeds") != charter5.PROTOCOL_ID
    ):
        raise SFIR6Refused("SFIR6 charter header is incomplete or drifted")
    return document


def freeze(destination: Path, generated_at: str, charter_yaml: Path = CHARTER_YAML) -> Path:
    document = load(charter_yaml)
    carried = charter5.require_carried_forward(document)
    frame = require_frame_unchanged(document)
    repairs = require_repairs_are_unconditional(document)
    predecessor = require_predecessor_preserved(document)
    batching = require_batching_is_not_justified_by_equivalence(document)
    verdict = require_verdict_taken_as_it_comes(document)
    sfir4_bounds = charter5.require_sfir4_bounds_untouched(document)
    base = NS.parents[1]
    core: dict[str, Any] = {
        "schema": CHARTER_SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "generated_at": generated_at,
        "state": "FROZEN_PRE_CENSUS",
        "charter": protocol.exact_ref(base, charter_yaml),
        "carried_forward_by_reference": carried,
        "frame_unchanged": frame,
        "repairs": repairs,
        "predecessor_result_preserved": predecessor,
        "batching": batching,
        "verdict_policy": verdict,
        "sfir4_retry_bounds_unmodified": sfir4_bounds,
        "toolchain": {
            name: protocol.exact_ref(base, NS / "tools" / f"{name}.py")
            for name in (
                "sfir6_wikipedia",
                "sfir6_transport",
                "sfir6_protocol",
                "sfir6_charter",
                "sfir6_canary",
                "probe_sfir6_capacity",
                "sfir5_transport",
                "probe_sfir4_capacity",
            )
        }
        | {"sources_sfir4": protocol.exact_ref(base, NS / "acquisition" / "sources_sfir4.py")},
        "transport_bounds": {
            "host_min_interval_seconds": dict(t5.HOST_MIN_INTERVAL_SECONDS),
            "max_total_wall_clock_seconds": t5.MAX_TOTAL_WALL_CLOCK_SECONDS,
            "max_total_requests": t5.MAX_TOTAL_REQUESTS,
            "max_ids_per_wikipedia_request": wiki.MAX_IDS_PER_REQUEST,
        },
        "corrected_pagination_fields": sorted(p6.CORRECTED_PAGINATION_FIELDS),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    core["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return protocol.write_immutable(destination, core)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from common import now

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination", type=Path, default=NS / "receipts" / "sfir6-design-charter-freeze.json"
    )
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args(argv)
    try:
        path = freeze(args.destination, args.generated_at or now())
    except SFIR6Refused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2), file=sys.stderr)
        return 4
    print(json.dumps({"state": "SEALED", "path": path.as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
