#!/usr/bin/env python3
"""Pre-freeze rehearsal for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.

A scorer that has never been shown to fail has not been shown to work. This
drives EVERY ONE of the eight invariants red INDEPENDENTLY, then drives the
whole closure green, and refuses to report the scorer rehearsable unless both
directions hold for all eight.

WHY BOTH DIRECTIONS, AND WHY INDEPENDENTLY

INC-V2-067 is what a partially-exercised instrument costs: a frozen pass rule
named eight invariants, the instrument graded one, and a 300-pair corpus was
spent before anybody could tell. Nothing in that chain had ever driven the
other seven -- red or green -- so there was no run in which their absence would
have shown.

Independently matters as much as completely. A driver that turns the whole
result red proves that SOMETHING failed, not that INVARIANT_4 can fail. So each
red run below asserts three things together:

    the target invariant reads VIOLATED
    every OTHER invariant still reads MET
    the overall verdict is FAIL

The middle assertion is the one that makes the first mean anything. Without it a
driver that broke the input shape entirely would pass this rehearsal while
proving nothing about the invariant it claims to exercise.

SYNTHETIC MATERIAL ONLY

Nothing here reads V2R4's cohort, and it could not: this runs BEFORE acquisition,
which is the only time a rehearsal can be honest. Every lineage id it constructs
carries the `REHEARSAL_PREFIX`, and `_require_synthetic` refuses any population
that does not -- so a later edit that points this at real material fails rather
than quietly burning it.

The rehearsal receipt is NOT a closure result. It grades no cohort, certifies
nothing, and appears in no denominator. It answers one question: may this scorer
be frozen?
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "source_fact_ir"):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import invariant_domain as dom  # noqa: E402
import v2r4_grading as grading  # noqa: E402
from common import now  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r4_rehearsal.v1"
STEM = "identity-change-migration-closure-v2r4-rehearsal"

#: Every synthetic lineage carries this. `_require_synthetic` refuses anything
#: that does not, so a later edit pointing this rehearsal at real material fails
#: instead of spending it.
REHEARSAL_PREFIX = "rehearsal:synthetic:"

MATERIAL = "SYNTHETIC_ONLY_NO_V2R4_COHORT_IS_READ"

REHEARSABLE = "SCORER_REHEARSABLE"
REFUSED = "SCORER_NOT_REHEARSABLE"


class RehearsalRefused(RuntimeError):
    """The rehearsal could not be conducted honestly, so no verdict is reported."""


# ---------------------------------------------------------------------------
# the synthetic population


def _pair(lineage: str) -> dict[str, Any]:
    """One V1-shaped per-pair measurement with every population non-empty.

    Non-empty everywhere on purpose: an invariant whose population is zero reads
    UNPROVEN, and an UNPROVEN neighbour would hide whether a red driver was
    specific to its target.
    """
    return {
        "lineage_id": lineage,
        "family": "git_docs",
        "matched_pair_count": 4,
        "changed_facet_observations": 3,
        "unresolved_facet_observations": 2,
        "unresolved_without_a_production_fail_closed_behaviour": 0,
        "ambiguity_observations": 1,
        "change_equivalent_observations": 0,
        "legacy_modified_count": 0,
        "new_modified_count": 0,
        "violations": {f"INVARIANT_{n}": [] for n in range(1, 9)},
    }


def _extra(lineage: str) -> dict[str, Any]:
    """V2R3's effective-surface clauses (c), (d) and (e) for one pair."""
    return {
        "lineage_id": lineage,
        "family": "git_docs",
        "c": {"violations": [], "observations": 5},
        "d": {"violations": [], "observations": 7},
        "e": {"violations": [], "observations": 2},
        "unsettled_identities": 0,
        "census": {},
    }


def clean_proofs() -> dict[str, Any]:
    """A disjointness proof for every one of V2R4's declared spent populations.

    Built from `REQUIRED_DISJOINTNESS` rather than typed out, so a population
    added to the declaration appears here without an edit -- and, more to the
    point, cannot be silently missing from it.
    """
    return {key: {"holds": True, "overlap": []} for key in grading.REQUIRED_DISJOINTNESS}


def green_inputs(pair_count: int = 3) -> dict[str, Any]:
    """A synthetic population on which all eight invariants are MET."""
    lineages = [f"{REHEARSAL_PREFIX}{index:03d}" for index in range(pair_count)]
    body = grading.null_grading_inputs()
    body.update(
        {
            "pairs": [_pair(lineage) for lineage in lineages],
            "extra": [_extra(lineage) for lineage in lineages],
            "fold": {
                "violations": [],
                "observations": 12,
                "lossiness_witnesses": 3,
                "per_class": {},
            },
            "independence": {
                "violations": [],
                "observations": 4,
                "modules_inspected": ["expected_change_status.py"],
                "signature": "sha256:" + "0" * 64,
            },
            "mapping": {
                "violations": [],
                "observations": 72,
                "combinations_evaluated": 72,
            },
            #: Through `disjointness_from`, not hand-built: that function is what
            #: proves the SET of populations proved equals the set declared, and
            #: a rehearsal that bypassed it would never exercise the check.
            "disjointness": grading.disjointness_from(clean_proofs()),
        }
    )
    return body


def _require_synthetic(inputs: dict[str, Any]) -> None:
    """No real lineage may reach this harness, in either population."""
    for key in ("pairs", "extra"):
        for row in inputs.get(key) or []:
            lineage = str(row.get("lineage_id", ""))
            if not lineage.startswith(REHEARSAL_PREFIX):
                raise RehearsalRefused(
                    f"{key} carries {lineage!r}, which is not synthetic. A rehearsal "
                    "over real material would spend it: outcomes observed here can "
                    "never be prospective again."
                )


# ---------------------------------------------------------------------------
# one driver per invariant
#
# Each takes the green inputs and makes exactly one invariant fail. They are
# written against the SOURCE of each invariant's violations rather than against
# the result, so a driver cannot pass by editing the verdict it is supposed to
# be earning.

_WHY = {"why": "rehearsal driver: a synthetic violation, not a real finding"}


def _violate_pair(inputs: dict[str, Any], ordinal: int) -> dict[str, Any]:
    inputs["pairs"][0]["violations"][f"INVARIANT_{ordinal}"] = [_WHY]
    return inputs


def _drive_1(inputs: dict[str, Any]) -> dict[str, Any]:
    return _violate_pair(inputs, 1)


def _drive_2(inputs: dict[str, Any]) -> dict[str, Any]:
    inputs["fold"]["violations"] = [_WHY]
    return inputs


def _drive_3(inputs: dict[str, Any]) -> dict[str, Any]:
    inputs["independence"]["violations"] = [_WHY]
    return inputs


def _drive_4(inputs: dict[str, Any]) -> dict[str, Any]:
    return _violate_pair(inputs, 4)


def _drive_5(inputs: dict[str, Any]) -> dict[str, Any]:
    inputs["mapping"]["violations"] = [_WHY]
    return inputs


def _drive_6(inputs: dict[str, Any]) -> dict[str, Any]:
    """Through clause (d) -- one of the three V2R3 added and V1 cannot see.

    Driving I6 through a clause V1 already had would rehearse the wrong half of
    the join: the whole reason V2R3 exists is the effective surface.
    """
    inputs["extra"][0]["d"]["violations"] = [_WHY]
    return inputs


def _drive_7(inputs: dict[str, Any]) -> dict[str, Any]:
    return _violate_pair(inputs, 7)


def _drive_8(inputs: dict[str, Any]) -> dict[str, Any]:
    """Through a real overlap, not a hand-written violation row.

    INVARIANT_8's violations come from the disjointness proofs, so the honest
    driver is a universe that actually overlaps a spent cohort.
    """
    proofs = clean_proofs()
    spent = sorted(grading.REQUIRED_DISJOINTNESS)[0]
    proofs[spent] = {"holds": False, "overlap": [f"{REHEARSAL_PREFIX}overlap"]}
    inputs["disjointness"] = grading.disjointness_from(proofs)
    return inputs


#: Keyed by full identifier, never by ordinal. Set equality against
#: `invariant_domain.CANONICAL_INVARIANTS` is checked before anything runs: a
#: dict of eight drivers naming eight wrong invariants would satisfy a count.
RED_DRIVERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    dom.CANONICAL_INVARIANTS[0]: _drive_1,
    dom.CANONICAL_INVARIANTS[1]: _drive_2,
    dom.CANONICAL_INVARIANTS[2]: _drive_3,
    dom.CANONICAL_INVARIANTS[3]: _drive_4,
    dom.CANONICAL_INVARIANTS[4]: _drive_5,
    dom.CANONICAL_INVARIANTS[5]: _drive_6,
    dom.CANONICAL_INVARIANTS[6]: _drive_7,
    dom.CANONICAL_INVARIANTS[7]: _drive_8,
}


def require_driver_domain() -> dict[str, Any]:
    """One driver per graded invariant, compared as SET EQUALITY.

    Not a count. The graded side is obtained by EXECUTING the grading function on
    a null population, for the same reason the freeze rung is: a module can carry
    a tuple naming eight and aggregate one.
    """
    graded = set(grading.graded_domain())
    driven = set(RED_DRIVERS)
    if graded != driven:
        raise RehearsalRefused(
            "the rehearsal does not drive what the scorer grades.\n"
            f"  graded but never driven red: {sorted(graded - driven)}\n"
            f"  driven but not graded:       {sorted(driven - graded)}\n"
            "An invariant nothing has ever driven red is an invariant nothing has "
            "shown can fail."
        )
    return {
        "graded": sorted(graded),
        "driven": sorted(driven),
        "equal": True,
        "compared": "set equality on full identifiers, never a count",
    }


# ---------------------------------------------------------------------------
# the two directions


def drive_green(pair_count: int = 3) -> dict[str, Any]:
    """All eight MET over a non-empty synthetic population, overall PASS."""
    inputs = green_inputs(pair_count)
    _require_synthetic(inputs)
    body = grading.grade(**inputs)

    verdicts = {name: block["verdict"] for name, block in body["invariants"].items()}
    not_met = sorted(name for name, verdict in verdicts.items() if verdict != dom.MET)
    receipt_domain_held = True
    receipt_problem = None
    try:
        dom.require_receipt_domain(body)
    except dom.ContractBroken as error:
        receipt_domain_held = False
        receipt_problem = str(error)

    held = not not_met and body["overall"] == dom.PASS and receipt_domain_held
    return {
        "direction": "green",
        "held": held,
        "overall": body["overall"],
        "pairs_resolved": body["pairs_resolved"],
        "verdicts": verdicts,
        "not_met": not_met,
        "receipt_domain_held": receipt_domain_held,
        "receipt_problem": receipt_problem,
        "why_it_matters": (
            "a rehearsal of eight red directions and no green one proves the "
            "scorer can refuse, not that it can ever accept"
        ),
    }


def drive_red(invariant: str) -> dict[str, Any]:
    """One invariant VIOLATED, the other seven still MET, overall FAIL."""
    if invariant not in RED_DRIVERS:
        raise RehearsalRefused(f"no red driver for {invariant!r}")
    inputs = RED_DRIVERS[invariant](copy.deepcopy(green_inputs()))
    _require_synthetic(inputs)
    body = grading.grade(**inputs)

    verdicts = {name: block["verdict"] for name, block in body["invariants"].items()}
    target = verdicts.get(invariant)
    collateral = sorted(
        name for name, verdict in verdicts.items() if name != invariant and verdict != dom.MET
    )
    held = target == dom.VIOLATED and not collateral and body["overall"] == dom.FAIL
    return {
        "direction": "red",
        "invariant": invariant,
        "held": held,
        "target_verdict": target,
        "overall": body["overall"],
        "collateral_damage": collateral,
        "violations": len(body["invariants"][invariant].get("violations") or []),
        "why_collateral_is_checked": (
            "a driver that turns the whole result red proves something failed, not "
            "that THIS invariant can fail. The other seven staying MET is what "
            "makes the target's VIOLATED mean what it says."
        ),
    }


# ---------------------------------------------------------------------------
# assembly


def rehearse(pair_count: int = 3) -> dict[str, Any]:
    """Both directions for all eight, and the domain equality that binds them."""
    domain = require_driver_domain()
    three_way = grading.require_domain()

    reds = [drive_red(name) for name in sorted(RED_DRIVERS)]
    green = drive_green(pair_count)

    failed_reds = sorted(row["invariant"] for row in reds if not row["held"])
    verdict = REHEARSABLE if not failed_reds and green["held"] else REFUSED

    return {
        "schema": SCHEMA,
        "protocol_id": grading.PROTOCOL_ID,
        "material": MATERIAL,
        "started": now(),
        "verdict": verdict,
        "driver_domain": domain,
        "acceptance_domain": three_way,
        "red_directions": reds,
        "green_direction": green,
        "red_directions_that_did_not_hold": failed_reds,
        "invariants_driven_red": len(reds),
        "this_is_not_a_closure_result": (
            "it grades no cohort, certifies nothing, and appears in no "
            "denominator. It answers one question: may this scorer be frozen?"
        ),
        "what_a_refusal_means": (
            "the scorer may not be frozen. An invariant that has never been "
            "driven red is an invariant nothing has shown can fail, and INC-V2-067 "
            "is what that costs when the corpus is already spent."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        type=int,
        default=3,
        help="synthetic pairs in the green population (never real material)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="write an immutable rehearsal receipt",
    )
    args = parser.parse_args(argv)

    try:
        body = rehearse(args.pairs)
    except (RehearsalRefused, dom.DomainRefused, grading.GradingRefused) as error:
        print(json.dumps({"verdict": REFUSED, "why": str(error)}, indent=1))
        return 4

    if args.write:
        body["provenance"] = write_immutable(
            STEM, body, tool=Path(__file__).resolve(), protocol=None
        )
    print(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False))
    return 0 if body["verdict"] == REHEARSABLE else 4


if __name__ == "__main__":
    raise SystemExit(main())
