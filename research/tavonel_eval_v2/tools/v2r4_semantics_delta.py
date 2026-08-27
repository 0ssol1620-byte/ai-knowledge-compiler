#!/usr/bin/env python3
"""V2R4_ALLOWED_DELTA_V1 -- the truthful successor contract for V2R3R1 -> V2R4.

WHY THIS EXISTS RATHER THAN `v2r3r1_semantics.py`

The V2R4 protocol claimed its attestation would record

    "the V2R3R1 -> V2R4 scientific projection is IDENTICAL"

and that claim is FALSE. Running the existing checker against the two protocols
refuses, and the first difference it reports is `/cohort/floor_is_not_lowered:
absent in parent` -- a field V2R4 added precisely to say the floor did not move.

`v2r3r1_semantics.py` was built for a different question. V2R3 -> V2R3R1 carried
the SAME UNSCORED 300 pairs forward exactly, and for an exact carry-forward
scientific equivalence has to be exact: any difference at all means the
successor is not asking the parent's question about the parent's material.

V2R4 is not that. Fresh protocol id, fresh cohort, no carry-forward, full-eight
executable grading, and new spent populations that must now be excluded. Exact
protocol equality is neither true nor required, and forcing it would mean either
lying about the transition or weakening the old checker until it stopped
detecting the thing it was built to detect.

So the old checker is PRESERVED UNTOUCHED -- it is historical evidence for the
carry-forward decision -- and this one proves the weaker, true statement:

    SCIENTIFIC_CORE_PRESERVED_WITH_PREDECLARED_HYGIENE_DELTAS

HOW IT DECIDES

Both protocols are flattened to leaf paths. Then, in order:

1. Any difference inside a PRESERVED_CORE path REFUSES. This is the scientific
   core: the eight invariants' semantics, the ignored-facet policy, the
   expectation oracle, the facet channels, the fail-closed rules, the floors, the
   vacuity rule, zero tolerance.
2. Any remaining difference not covered by an ALLOWED_DELTA declaration REFUSES.
   Control 15 falls out of this: deleting a declaration while leaving its delta
   in place turns the delta uncovered.
3. Any ALLOWED_DELTA declaration covering ZERO real differences REFUSES.
   Control 16 falls out of this: a wildcard added "just in case" is dead
   permission, and dead permission is what a later edit slips through.
4. Any ALLOWED_DELTA whose path reaches into PRESERVED_CORE REFUSES at
   declaration time, before a single difference is examined. There is no
   `/invariants/*`, no `/cohort/*`, no `/execution/*`.

`requires_all_of` is compared as a SET of clause texts rather than positionally,
because inserting one clause shifts every later index and would report eight
differences where there is one insertion. A clause REMOVED from the parent's set
is a core change and refuses -- unless it is declared as an exact rename, which
is a one-for-one substitution named on both sides.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools",):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

from common import rel  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.v2r4_allowed_delta.v1"
CONTRACT_ID = "V2R4_ALLOWED_DELTA_V1"
STEM = "identity-change-migration-closure-v2r4-allowed-delta"

PARENT = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml"
SUCCESSOR = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.yaml"

VERDICT_HELD = "SCIENTIFIC_CORE_PRESERVED_WITH_PREDECLARED_HYGIENE_DELTAS"
VERDICT_REFUSED = "SCIENTIFIC_CORE_NOT_PRESERVED"

Path_ = tuple[str, ...]


class DeltaRefused(RuntimeError):
    """The successor changed something the core forbids, or changed it undeclared."""


# ---------------------------------------------------------------------------
# the scientific core -- byte-identical, or refuse
#
# Every entry is an EXACT path prefix. Nothing here is a wildcard over a whole
# block, and `_require_no_delta_reaches_the_core` proves at import that no
# allowed delta overlaps any of them.

PRESERVED_CORE: tuple[Path_, ...] = (
    #: The seven invariants V2R4 does not touch, whole.
    ("invariants", "INVARIANT_1_identity_decisions_unchanged"),
    ("invariants", "INVARIANT_2_identity_fold_remains_identity_only"),
    ("invariants", "INVARIANT_3_expectation_is_independent"),
    ("invariants", "INVARIANT_4_changed_facet_resolves_typed_or_failclosed"),
    ("invariants", "INVARIANT_5_never_silently_unchanged"),
    ("invariants", "INVARIANT_6_ambiguous_identity_stays_unresolved"),
    ("invariants", "INVARIANT_7_only_predeclared_ignores"),
    #: INVARIANT_8's own semantics, minus the populations list and the prose that
    #: describes it. The obligation does not move; the enumeration of already-
    #: spent cohorts does, which is what a successor with new spent predecessors
    #: means.
    ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "population"),
    ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "met_when"),
    ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "v1_is_read_for_ids_only"),
    #: INVARIANT_6's machinery: the corrected five-clause effective disposition,
    #: the resolver surface, the independent quarantine oracle, the composition.
    ("effective_identity_disposition",),
    ("quarantine_channel",),
    ("contract_consistency_gate",),
    #: The ignored-facet policy, the oracle, the channels, the fail-closed rule.
    ("predeclared_ignored_facets",),
    ("expectation_oracle",),
    ("facet_channels",),
    ("unresolved_fail_closed",),
    ("diff_level",),
    ("why_L4",),
    ("root_normalisation",),
    #: The floors, unchanged and never lowered to reach feasibility.
    ("cohort_sufficiency",),
    #: Zero tolerance and vacuity.
    ("vacuity_rule",),
    ("pass_rule", "no_threshold"),
    ("pass_rule", "a_pass_does_not_retire_v1s_fail"),
    #: The standing evidence rules the successor inherits whole.
    ("supersedes_nothing",),
    ("v1_standing",),
    ("retrospective_evidence",),
    ("legacy_is_not_ground_truth",),
    ("anti_fitting",),
    ("declared_blind_spots",),
    #: The row-shape contract a changed instrument could quietly relax.
    ("manifest_contract", "rows_key"),
    ("manifest_contract", "required_row_fields"),
    ("manifest_contract", "required_side_fields"),
    ("manifest_contract", "accepted_lineage_id_aliases"),
    ("manifest_contract", "accepted_row_key_aliases"),
    ("manifest_contract", "recorded_raw_digest_key"),
    ("manifest_contract", "recorded_canonical_digest_key"),
    ("manifest_contract", "canonical_digest_convention_key"),
    #: The sentence the whole V2R3 episode turned on.
    ("freeze", "no_post_freeze_change"),
)

#: `pass_rule/requires_all_of` is compared as a SET, elsewhere. Named here so
#: `_flatten` can skip it rather than emit shifted-index noise.
SET_COMPARED: tuple[Path_, ...] = (("pass_rule", "requires_all_of"),)

#: Clauses replaced one-for-one. A removal from the parent's pass rule is a core
#: change; a RENAME is a removal plus an addition that mean the same obligation,
#: and it is legal only when both halves are named here.
CLAUSE_RENAMES: tuple[tuple[str, str, str], ...] = (
    (
        "all eight invariants MET",
        "every declared invariant's verdict is MET",
        "the count becomes the DECLARED SET, which the domain-equality clause "
        "makes precise. Strictly stronger: 'all eight' is satisfied by eight "
        "wrong names, 'every declared' is not.",
    ),
)


# ---------------------------------------------------------------------------
# the only permitted deltas, each by exact path


@dataclass(frozen=True)
class AllowedDelta:
    """One predeclared difference, with the category that licenses it."""

    path: Path_
    category: str
    reason: str


#: The nine categories the founder's ruling permits, and nothing else. A
#: difference is legal only if some entry below covers its path.
ALLOWED_DELTAS: tuple[AllowedDelta, ...] = (
    # 1. administrative identity
    #
    # `status`, `split`, `predecessor`, `background` and `release` are NOT here.
    # V2R4 carries all five forward byte-for-byte, so a declaration for them would
    # license nothing -- and the dead-permission rule below refuses exactly that.
    # They were declared in the first draft of this contract on the assumption
    # they would move; the checker is what established that they do not.
    AllowedDelta(("schema",), "administrative", "the successor's schema id"),
    AllowedDelta(("protocol_id",), "administrative", "the successor's identity"),
    AllowedDelta(
        ("authorised_by",),
        "administrative",
        "the successor is authorised by a later founder ruling",
    ),
    AllowedDelta(("parent_protocol",), "administrative", "lineage metadata"),
    AllowedDelta(
        ("protocol_delta",),
        "administrative",
        "the successor's own description of what it changed",
    ),
    # 2. carry-forward removal -- V2R4 uses genuinely fresh material
    AllowedDelta(
        ("carry_forward",),
        "carry_forward_removed",
        "V2R3R1 inherited an UNSCORED frozen universe exactly. Those 300 pairs "
        "have now been scored and their INVARIANT_6 outcome read, so there is "
        "nothing left to carry: they are SPENT and appear in the exclusion set.",
    ),
    AllowedDelta(
        ("cohort", "path_taken"),
        "carry_forward_removed",
        "EXACT_CARRY_FORWARD_OF_AN_UNSCORED_FROZEN_UNIVERSE becomes FRESH_ACQUISITION",
    ),
    AllowedDelta(
        ("cohort", "why_not_a_carry_forward"),
        "carry_forward_removed",
        "why the parent's route is unavailable to this study",
    ),
    AllowedDelta(
        ("cohort", "floor_is_not_lowered"),
        "carry_forward_removed",
        "restates the unchanged floor for a study that now acquires. The floor "
        "itself is in PRESERVED_CORE under cohort_sufficiency and cannot move.",
    ),
    # 3. fresh acquisition / frame / enumerator plumbing
    AllowedDelta(("cohort", "frame"), "fresh_plumbing", "this chain's own frame module"),
    AllowedDelta(("cohort", "enumerated_by"), "fresh_plumbing", "this chain's own enumerator"),
    AllowedDelta(("manifest_contract", "path"), "fresh_plumbing", "this chain's own manifest"),
    AllowedDelta(
        ("manifest_contract", "owner_tool"), "fresh_plumbing", "this chain's own enumerator"
    ),
    AllowedDelta(
        ("manifest_contract", "acquisition_manifest"),
        "fresh_plumbing",
        "this chain acquires into its own corpus and reads no predecessor's",
    ),
    AllowedDelta(
        ("manifest_contract", "acquisition_manifest_is_inherited"),
        "fresh_plumbing",
        "the inherited-corpus clause is replaced by this chain's own",
    ),
    AllowedDelta(
        ("manifest_contract", "acquisition_manifest_is_this_chains_own"),
        "fresh_plumbing",
        "its replacement",
    ),
    AllowedDelta(
        ("manifest_contract", "enumeration_schema"),
        "fresh_plumbing",
        "this chain's own enumeration schema id",
    ),
    AllowedDelta(
        ("execution", "preconditions_that_must_all_be_PROVEN_before_the_single_run"),
        "fresh_plumbing",
        "the rung names this chain's gate verifies. The execution CONTRACT -- "
        "no_preview, scored_once -- is compared elsewhere and unchanged.",
    ),
    # 4. full-eight executable grading instrumentation
    AllowedDelta(
        ("scorer_acceptance",),
        "full_eight_grading",
        "V2R3R1's instrument graded ONE invariant against a pass rule naming "
        "eight. The module list is exactly what that repair changes.",
    ),
    AllowedDelta(
        ("pass_rule", "the_scorer_produces_the_verdict"),
        "full_eight_grading",
        "there is no interpretation step after execution; the scorer emits `overall` itself",
    ),
    AllowedDelta(
        ("pass_rule", "receipt_shape"),
        "full_eight_grading",
        "the receipt must carry `overall`, `pairs_resolved` and all eight blocks",
    ),
    AllowedDelta(
        ("pass_rule", "what_a_pass_authorises"),
        "full_eight_grading",
        "a pass now covers all eight invariants rather than a single endpoint",
    ),
    AllowedDelta(
        ("pass_rule", "what_a_fail_means"),
        "full_eight_grading",
        "names V2R4 rather than V2; the rule itself is unchanged",
    ),
    AllowedDelta(
        ("pass_rule", "a_pass_does_not_absorb_v2r3r1s_i6"),
        "full_eight_grading",
        "V2R3R1's I6 endpoint stays separate, valid, preserved evidence",
    ),
    # 5. the invariant-domain equality guard
    AllowedDelta(
        ("companion_attestations", "rungs", "domain_attestation"),
        "invariant_domain_guard",
        "the attestation INC-V2-067 did not have: declared == graded == receipt, "
        "with the graded set obtained by EXECUTING the grader",
    ),
    # 6. migration-closure acceptance receipt plumbing
    AllowedDelta(
        ("freeze", "the_acceptance_is_bound_by_path_and_digest_not_by_stem"),
        "acceptance_plumbing",
        "downstream gates bind this study by path and sha256, never by stem glob (INC-V2-069)",
    ),
    # 7. INVARIANT_8 hygiene -- populations spent AFTER the parent was written
    AllowedDelta(
        ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "statement"),
        "i8_hygiene",
        "extends 'no pair any earlier closure measured' to include declared confirmatory burns",
    ),
    AllowedDelta(
        ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "executable_meaning"),
        "i8_hygiene",
        "the populations are now named as a set and compared by set equality",
    ),
    AllowedDelta(
        ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "the_declared_populations"),
        "i8_hygiene",
        "V2R3R1's 300 and VBC1's burned material became spent after the parent "
        "protocol was written. A population that became spent later is exactly "
        "what a successor's hygiene extension is for.",
    ),
    AllowedDelta(
        ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "also_reported"),
        "i8_hygiene",
        "one more zero-denominator report, for the newly spent population",
    ),
    AllowedDelta(
        ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "violation"),
        "i8_hygiene",
        "the violation clause names the wider set. Direction is STRENGTHENING: "
        "every population the parent excluded is still excluded.",
    ),
    AllowedDelta(
        ("invariants", "INVARIANT_8_sfi2_cases_cannot_certify", "can_come_back_red_because"),
        "i8_hygiene",
        "two more red controls, for the new population and for a dropped proof",
    ),
    AllowedDelta(
        ("exclusion_policy",),
        "i8_hygiene",
        "the same widening applied at the enumerator, so the rows never enter",
    ),
    # 8. SFI3 cross-study root reservation -- containers, never future material
    AllowedDelta(
        (
            "invariants",
            "INVARIANT_8_sfi2_cases_cannot_certify",
            "sfi3_is_deliberately_not_one_of_them",
        ),
        "sfi3_reservation",
        "records why SFI3 is NOT an INVARIANT_8 population: its cohort does not "
        "exist yet and requiring it made a circular gate. Separation moved to "
        "SFI3_ROOT_RESERVATION_V1, on container identity.",
    ),
    # 9. freeze / attestation namespace and new receipt stems
    AllowedDelta(("freeze", "stems"), "namespace", "this chain's own stems"),
    AllowedDelta(("freeze", "tool"), "namespace", "this chain's own freezer"),
    AllowedDelta(
        ("freeze", "every_stem_is_this_chains_own"),
        "namespace",
        "why a successor never writes into a predecessor's stem namespace",
    ),
    AllowedDelta(
        ("freeze", "rung_0_under_exact_carry_forward"),
        "namespace",
        "the carry-forward degenerate rung 0 is gone",
    ),
    AllowedDelta(
        ("freeze", "rung_0_is_an_acquisition_frame_again"),
        "namespace",
        "rung 0 carries its original obligation in full again",
    ),
    AllowedDelta(
        ("freeze", "no_selection_for_outcome"),
        "namespace",
        "restates, for an acquiring study, the selection prohibition the parent "
        "had by construction",
    ),
    AllowedDelta(
        ("companion_attestations", "rungs", "frame_attestation"),
        "namespace",
        "rung 0 attests an acquisition frame and the reservation binding, not an "
        "exact carry-forward",
    ),
    AllowedDelta(
        ("companion_attestations", "rungs", "protocol_attestation"),
        "namespace",
        "the projection equality it records is this contract rather than the "
        "parent's exact-equality one",
    ),
    AllowedDelta(
        ("companion_attestations", "rungs", "universe_attestation"),
        "namespace",
        "binds the wider population set and the reservation instead of a future "
        "SFI3 acquisition receipt",
    ),
    AllowedDelta(
        ("companion_attestations", "the_gate_must_consume_them"),
        "namespace",
        "names this chain's gate",
    ),
    AllowedDelta(
        ("companion_attestations", "the_scorer_may_not_call_the_base_gate"),
        "namespace",
        "names this chain's gate",
    ),
    AllowedDelta(
        ("companion_attestations", "a_v2r3r1_measurement_that_already_exists_refuses"),
        "namespace",
        "renamed for this chain",
    ),
    AllowedDelta(
        ("companion_attestations", "a_v2r4_measurement_that_already_exists_refuses"),
        "namespace",
        "its replacement",
    ),
)

#: Every category any declaration may claim. A category outside this set is a
#: permission nobody granted.
PERMITTED_CATEGORIES: frozenset[str] = frozenset(
    {
        "administrative",
        "carry_forward_removed",
        "fresh_plumbing",
        "full_eight_grading",
        "invariant_domain_guard",
        "acceptance_plumbing",
        "i8_hygiene",
        "sfi3_reservation",
        "namespace",
    }
)


def _under(path: Path_, prefix: Path_) -> bool:
    return path[: len(prefix)] == prefix


def _require_no_delta_reaches_the_core() -> None:
    """No allowed delta may overlap the scientific core, in either direction.

    Checked at import, before any protocol is read, so a wildcard that would
    have swallowed an invariant fails on the declaration rather than on the day
    someone edits one.
    """
    problems: list[str] = []
    for delta in ALLOWED_DELTAS:
        if delta.category not in PERMITTED_CATEGORIES:
            problems.append(f"{'/'.join(delta.path)} claims category {delta.category!r}")
        for core in PRESERVED_CORE:
            if _under(core, delta.path) or _under(delta.path, core):
                problems.append(f"{'/'.join(delta.path)} overlaps the core path /{'/'.join(core)}")
    if problems:
        raise DeltaRefused(
            "an allowed-delta declaration reaches into the scientific core:\n  "
            + "\n  ".join(problems)
        )


_require_no_delta_reaches_the_core()


# ---------------------------------------------------------------------------
# flattening and comparison


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DeltaRefused(f"{path} does not exist; there is nothing to compare")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _flatten(value: Any, prefix: Path_ = ()) -> Iterator[tuple[Path_, Any]]:
    """Leaf paths, with the set-compared blocks emitted whole."""
    if any(prefix == where for where in SET_COMPARED):
        yield prefix, value
        return
    if isinstance(value, dict):
        for key in value:
            yield from _flatten(value[key], (*prefix, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, (*prefix, f"[{index}]"))
    else:
        yield prefix, value


def differences(parent: dict[str, Any], successor: dict[str, Any]) -> list[Path_]:
    """Every leaf path where the two protocols disagree, added or removed.

    The SET_COMPARED paths are withheld here and decided by `_pass_rule_clauses`
    instead. They are not exempt -- they are compared by a rule this one cannot
    express, and leaving them in would report a single inserted clause as an
    undeclared difference at a path no category should ever cover.
    """
    left = dict(_flatten(parent))
    right = dict(_flatten(successor))
    out = set(left) ^ set(right)
    out |= {path for path in set(left) & set(right) if left[path] != right[path]}
    return sorted(path for path in out if not any(_under(path, where) for where in SET_COMPARED))


def _pass_rule_clauses(parent: dict[str, Any], successor: dict[str, Any]) -> dict[str, Any]:
    """The pass rule as a SET, with renames resolved one for one.

    Positional comparison would report eight differences for a single insertion,
    and a reader could not tell an inserted clause from a rewritten one.
    """
    before = list((parent.get("pass_rule") or {}).get("requires_all_of") or [])
    after = list((successor.get("pass_rule") or {}).get("requires_all_of") or [])

    renamed_from = {old: new for old, new, _ in CLAUSE_RENAMES}
    resolved = [renamed_from.get(clause, clause) for clause in before]

    removed = [clause for clause in resolved if clause not in after]
    if removed:
        raise DeltaRefused(
            f"the pass rule dropped {removed}. A clause removed from the parent's "
            "rule is a weakening of the acceptance rule, and no hygiene category "
            "licenses one. Declare it in CLAUSE_RENAMES if it was replaced "
            "one-for-one by an equivalent or stronger clause."
        )
    added = [clause for clause in after if clause not in resolved]
    return {
        "clauses_before": len(before),
        "clauses_after": len(after),
        "nothing_removed": True,
        "added": added,
        "renamed": [{"from": old, "to": new, "why": why} for old, new, why in CLAUSE_RENAMES],
        "compared_as": "a set of clause texts, never positionally",
    }


def _require_renames_are_real(parent: dict[str, Any], successor: dict[str, Any]) -> None:
    """A declared rename whose halves are not actually there is dead permission."""
    before = set((parent.get("pass_rule") or {}).get("requires_all_of") or [])
    after = set((successor.get("pass_rule") or {}).get("requires_all_of") or [])
    problems = [
        f"{old!r} -> {new!r}"
        for old, new, _ in CLAUSE_RENAMES
        if old not in before or new not in after
    ]
    if problems:
        raise DeltaRefused(
            f"declared clause renames that did not happen: {problems}. A rename "
            "nobody made is permission standing open for an edit that has not "
            "been reviewed."
        )


# ---------------------------------------------------------------------------
# the proof


def _where(path: Path) -> str:
    """Repo-relative when the protocol is in the tree, absolute when it is not.

    A red control drives this checker against a mutated protocol written to a
    temporary directory, which is deliberately outside the repository. `rel()`
    raises there, and a checker that crashes on a path it can still hash would
    make the red controls untestable at exactly the point they matter. What binds
    the receipt is the digest below, not this label.
    """
    try:
        return rel(path)
    except ValueError:
        return str(Path(path).resolve()).replace("\\", "/")


def prove_allowed_delta(
    parent: Path | None = None, successor: Path | None = None
) -> dict[str, Any]:
    """The successor preserves the core and differs only where predeclared."""
    parent_path = parent or PARENT
    successor_path = successor or SUCCESSOR
    left = load(parent_path)
    right = load(successor_path)

    found = differences(left, right)

    core_breaches = [path for path in found if any(_under(path, core) for core in PRESERVED_CORE)]
    if core_breaches:
        raise DeltaRefused(
            "the scientific core is not preserved:\n  "
            + "\n  ".join("/" + "/".join(path) for path in core_breaches[:20])
            + f"\n({len(core_breaches)} path(s) total). No hygiene category "
            "licenses a change here."
        )

    accepted: list[dict[str, Any]] = []
    uncovered: list[Path_] = []
    used: set[Path_] = set()
    for path in found:
        covering = next((delta for delta in ALLOWED_DELTAS if _under(path, delta.path)), None)
        if covering is None:
            uncovered.append(path)
            continue
        used.add(covering.path)
        accepted.append(
            {
                "path": "/" + "/".join(path),
                "category": covering.category,
                "declared_at": "/" + "/".join(covering.path),
            }
        )
    if uncovered:
        raise DeltaRefused(
            "the successor differs where nothing declared it may:\n  "
            + "\n  ".join("/" + "/".join(path) for path in uncovered[:20])
            + f"\n({len(uncovered)} path(s) total). Either the change does not "
            "belong in V2R4, or its category has to be declared and reviewed."
        )

    unused = sorted(
        "/" + "/".join(delta.path) for delta in ALLOWED_DELTAS if delta.path not in used
    )
    if unused:
        raise DeltaRefused(
            f"allowed-delta declarations covering no actual difference: {unused}. "
            "Dead permission is what a later edit slips through unreviewed, so a "
            "declaration that is not needed is removed rather than kept spare."
        )

    _require_renames_are_real(left, right)
    pass_rule = _pass_rule_clauses(left, right)

    by_category: dict[str, int] = {}
    for row in accepted:
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1

    return {
        "schema": SCHEMA,
        "contract_id": CONTRACT_ID,
        "verdict": VERDICT_HELD,
        "held": True,
        "parent": _where(parent_path),
        "successor": _where(successor_path),
        "core_paths_preserved": ["/" + "/".join(core) for core in PRESERVED_CORE],
        "core_breaches": [],
        "accepted_deltas": accepted,
        "accepted_delta_count": len(accepted),
        "by_category": by_category,
        "declarations_used": sorted("/" + "/".join(path) for path in used),
        "pass_rule": pass_rule,
        "not_identical_and_does_not_claim_to_be": (
            "V2R3 -> V2R3R1 carried the SAME UNSCORED 300 pairs forward, so exact "
            "scientific equality was both true and required there. V2R4 is a fresh "
            "cohort under a fresh protocol id with full-eight grading, so exact "
            "equality is neither. `v2r3r1_semantics.py` is preserved untouched as "
            "evidence for the carry-forward decision it was built for."
        ),
        "no_wildcards": (
            "every declaration is an exact path. There is no /invariants/*, no "
            "/cohort/*, no /execution/*, and `_require_no_delta_reaches_the_core` "
            "proves at import that none overlaps the core."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, default=None)
    parser.add_argument("--successor", type=Path, default=None)
    parser.add_argument(
        "--write", action="store_true", default=False, help="write an immutable receipt"
    )
    args = parser.parse_args(argv)

    try:
        body = prove_allowed_delta(args.parent, args.successor)
    except DeltaRefused as error:
        print(json.dumps({"verdict": VERDICT_REFUSED, "why": str(error)}, indent=1))
        return 4
    if args.write:
        body["provenance"] = write_immutable(
            STEM, body, tool=Path(__file__).resolve(), protocol=None
        )
    print(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
