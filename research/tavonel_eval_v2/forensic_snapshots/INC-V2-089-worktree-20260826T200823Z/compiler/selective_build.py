#!/usr/bin/env python3
"""The selective side of the equivalence comparison.

Reads the BEFORE and AFTER canonical documents, builds the prior active state
from BEFORE, then computes what the AFTER revision makes stale and rebuilds only
that. Everything else is carried forward from the prior state, which is exactly
the behaviour that has to be proved safe.

Runs in its own process. It never imports the oracle and the oracle never
imports it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "cir-python" / "src"))

from akc_cir.dependency import (
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
)
from akc_cir.recompilation import FacetVerdict, StructuralPolicy, plan_recompilation
from akc_cir.semantic_diff import (
    ChangeKind,
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)
from dependency_contract import (
    DEFAULT_SENSITIVITY,
    Verdict,
    decide_structural,
    decide_unit_change,
    merged_reads,
    prefix_of,
)
from execution_invariant import (
    STAGE_POST_EXECUTION,
    STAGE_PRE_ACTIVATION,
    check_no_unexecuted_carry_forward,
    observe_no_unexecuted_carry_forward,
)

SEMANTIC_ONLY = frozenset({DependencyChannel.SEMANTIC})
STRUCTURAL_ONLY = frozenset({DependencyChannel.STRUCTURAL})
SEMANTIC_AND_STRUCTURAL = frozenset(
    {DependencyChannel.SEMANTIC, DependencyChannel.STRUCTURAL}
)

#: The three channels INC-V2-038 found unreachable: detected and typed by the
#: diff (EVIDENCE_MOVED / TEMPORAL_CHANGED / METADATA_CHANGED), carried by no
#: edge this module emitted, and so absorbed into "no change reached it".
FACET_CHANNELS = frozenset(
    {
        DependencyChannel.LOCATOR,
        DependencyChannel.TEMPORAL,
        DependencyChannel.METADATA,
    }
)

#: Per-unit facets a `section:` artifact's digest reads, mapped from the key
#: the canonical document carries them under to the key they occupy in the
#: artifact spec. A document that declares none of these produces exactly the
#: digest this module produced before INC-V2-038, which is why closing the gap
#: does not invalidate a single stored corpus.
SECTION_FACET_KEYS: tuple[tuple[str, str], ...] = (
    ("evidence_id", "locator"),
    ("temporal_fingerprint", "temporal_fingerprint"),
    ("metadata_fingerprint", "metadata_fingerprint"),
)

MISSING = "MISSING_NOT_PLANNED_AND_NO_PRIOR_VALUE"


# --- artifact spec v1, selective implementation ----------------------------
# A second, independent implementation of the same specification lives in
# oracle/independent_full_build.py. The two are compared; they are not shared.

import hashlib  # noqa: E402


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def logical_id(source_id: str, explicit_path: list[str]) -> str:
    joined = source_id + "\n" + "/".join(explicit_path)
    return "u:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


def doc_key(source_id: str) -> str:
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]


def bucket_of(unit_logical_id: str) -> int:
    return int(hashlib.sha256(unit_logical_id.encode("utf-8")).hexdigest()[:8], 16) % 4


def inventory_and_dependencies(
    document: dict[str, Any],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Artifact ids for one revision, with the logical ids each one reads."""
    source_id = document["source_id"]
    key = doc_key(source_id)
    ordered = [logical_id(source_id, unit["explicit_path"]) for unit in document["units"]]
    text_by_id = {
        identifier: unit["text"] for identifier, unit in zip(ordered, document["units"])
    }

    dependencies: dict[str, tuple[str, ...]] = {}
    for identifier in ordered:
        dependencies["section:" + identifier] = (identifier,)
    dependencies["document-index:" + key] = tuple(ordered)
    dependencies["structure-map:" + key] = tuple(ordered)
    for bucket in range(4):
        members = tuple(
            identifier for identifier in sorted(set(ordered)) if bucket_of(identifier) == bucket
        )
        if members:
            dependencies["topic-bucket:" + key + ":" + str(bucket)] = members
    return dependencies, text_by_id


def section_spec(identifier: str, unit: dict[str, Any]) -> dict[str, Any]:
    """What a `section:` artifact is, as bytes.

    Until INC-V2-038 this was `{"logical_id", "semantic_text"}` and nothing
    else, which made the edge fix below unobservable on its own: a LOCATOR,
    TEMPORAL or METADATA change could seed a rebuild, the rebuild could run,
    and it would emit the identical digest, because the facet that moved was
    not in the representation. An equivalence check would then compare
    clean-rebuild bytes to selective-rebuild bytes, find them equal, and
    report agreement while the defect stood. A rebuild that produces identical
    bytes because the relevant facet is absent from the artifact is not a
    repair.

    A facet is written only when the revision declares it. That is not a
    hedge: `section:<unit>` is one knowledge unit's evidence occurrence, and a
    facet the source never stated is not a property of that occurrence with
    some default value -- it is absent. Writing an absent facet under a
    synthesised placeholder would move every stored digest in the corpus and
    encode no information, since the placeholder this module used for
    `evidence_id` (`"e:" + logical_id`) is a pure function of a value already
    in the spec and can never move independently of it.
    """
    spec: dict[str, Any] = {"logical_id": identifier, "semantic_text": unit["text"]}
    for source_key, spec_key in SECTION_FACET_KEYS:
        value = unit.get(source_key)
        if value:
            spec[spec_key] = value
    return spec


def build_all(document: dict[str, Any]) -> dict[str, str]:
    """Every artifact of one revision, built from that revision alone."""
    source_id = document["source_id"]
    key = doc_key(source_id)
    ordered = [logical_id(source_id, unit["explicit_path"]) for unit in document["units"]]
    state: dict[str, str] = {}
    for identifier, unit in zip(ordered, document["units"]):
        state["section:" + identifier] = _digest(section_spec(identifier, unit))
    state["document-index:" + key] = _digest({"doc_key": key, "members": ordered})
    state["structure-map:" + key] = _digest(
        {
            "doc_key": key,
            "paths": ["/".join(unit["explicit_path"]) for unit in document["units"]],
        }
    )
    for bucket in range(4):
        members = [
            identifier for identifier in sorted(set(ordered)) if bucket_of(identifier) == bucket
        ]
        if members:
            state["topic-bucket:" + key + ":" + str(bucket)] = _digest(
                {"doc_key": key, "bucket": bucket, "members": members}
            )
    return state


# --- diff, plan, selective rebuild -----------------------------------------


def snapshots(document: dict[str, Any]) -> tuple[list[UnitSnapshot], DocumentShape]:
    source_id = document["source_id"]
    units: list[UnitSnapshot] = []
    headings = [unit["heading"] for unit in document["units"]]
    for index, unit in enumerate(document["units"]):
        identifier = logical_id(source_id, unit["explicit_path"])
        units.append(
            UnitSnapshot(
                logical_id=identifier,
                text=unit["text"],
                document_path=(source_id, *unit["explicit_path"]),
                anchor=unit["heading"],
                neighbour_anchors=(
                    headings[index - 1] if index else "",
                    headings[index + 1] if index + 1 < len(headings) else "",
                ),
                # The document's own facets when it declares them, so the diff
                # and `section_spec` read one unit the same way. The fallback
                # anchor is a pure function of `identifier`: it exists so the
                # locator field is never null, and it can never move on its
                # own, which is why `section_spec` does not write it.
                evidence_id=unit.get("evidence_id") or ("e:" + identifier),
                temporal_fingerprint=unit.get("temporal_fingerprint") or "",
                metadata_fingerprint=unit.get("metadata_fingerprint") or "",
                explicit_identifier="/".join(unit["explicit_path"]),
            )
        )
    shape = DocumentShape(
        heading_path_set=frozenset(unit.document_path for unit in units),
        block_count=len(units),
        unit_order=tuple(unit.logical_id for unit in units),
    )
    return units, shape


def declared_facets(artifact: str) -> frozenset[DependencyChannel]:
    """The facet channels `dependency_contract` declares this artifact kind
    sensitive to.

    The contract is the source of facet sensitivity, and it is read rather
    than restated: `DEFAULT_SENSITIVITY` says `section:<unit>` is a single
    knowledge unit's evidence occurrence and is therefore sensitive to that
    occurrence's locator, effective time and language/accessibility tags,
    while the two document-level aggregates and the topic buckets are not.
    Restating that here as three more `startswith` branches would give the
    declaration two homes, and the point of INC-V2-038's fix is that it has
    one.

    Only the facet channels are taken. The contract's SEMANTIC/STRUCTURAL
    entries are deliberately *not* substituted for this function's existing
    assignment below: the contract declares `document-index:` STRUCTURAL-only
    and `topic-bucket:` sensitive to nothing, where production declares both
    SEMANTIC-sensitive. E9 is a subset check for exactly that reason --
    production legitimately rebuilds more than the contract requires. Adopting
    the contract's narrower SEMANTIC declaration would *remove* edges and
    could only reduce what a semantic edit invalidates, which is a different
    change from closing a gap and is not authorised here.

    An artifact kind the contract does not name at all yields no facets rather
    than every facet. `prefix_of` returning None means unknown, and inventing
    a facet edge for an unknown artifact kind is the guess this lane exists to
    refuse.
    """
    prefix = prefix_of(artifact, DEFAULT_SENSITIVITY)
    if prefix is None:
        return frozenset()
    return DEFAULT_SENSITIVITY[prefix] & FACET_CHANNELS


def graph_for(
    before: dict[str, tuple[str, ...]], after: dict[str, tuple[str, ...]]
) -> DependencyGraph:
    """Typed edges over the union of both revisions' artifacts.

    Channels are declared per artifact kind rather than left at the default of
    every channel. That is what makes StructuralPolicy.PRECISE precise: only
    the two order-sensitive artifacts travel the structural channel, so a purely
    semantic edit does not drag the whole document into the rebuild set.

    It is also what makes `FacetPolicy.DECLARED` work at all. Every edge here
    narrows `channels`, so this graph is stating a positive fact about each
    artifact kind rather than leaving the constructor's all-channels default in
    place -- and a narrowed set that names LOCATOR/TEMPORAL/METADATA is the
    only thing the planner accepts as permission to propagate a facet change.
    Before INC-V2-038 no edge here named any of the three, which is the half of
    the defect that lived in this file.
    """
    edges: list[DependencyEdge] = []
    merged: dict[str, tuple[str, ...]] = {**before, **after}
    for artifact, members in merged.items():
        if artifact.startswith("structure-map:"):
            channels = STRUCTURAL_ONLY
        elif artifact.startswith("document-index:"):
            channels = SEMANTIC_AND_STRUCTURAL
        else:
            channels = SEMANTIC_ONLY
        # Union, never replacement: the facet declaration is additive to what
        # this module already declared, so no edge loses a channel it had.
        channels = channels | declared_facets(artifact)
        union = tuple(dict.fromkeys((*before.get(artifact, ()), *after.get(artifact, ()))))
        for member in union or members:
            edges.append(
                DependencyEdge(artifact, member, EdgeType.DEPENDS_ON, channels=channels)
            )
    return DependencyGraph(edges)


#: Change channels this executor claims to close. Anything outside it that the
#: diff nonetheless detects is reported as UNRESOLVED and excluded from E9's
#: denominator with a reason -- never dropped, and never counted as tested.
E9_SUPPORTED_CHANNELS: tuple[str, ...] = (
    "semantic",
    "structural",
    "locator",
    "temporal",
    "metadata",
)

E9_SCHEMA = "tavonel.v2.e9_channel_closure.v1"


def e9_channel_closure(
    *,
    diff: Any,
    before_deps: dict[str, tuple[str, ...]],
    after_deps: dict[str, tuple[str, ...]],
    plan: Any,
) -> dict[str, Any]:
    """One pair's evidence for E9 -- detected typed change without a rebuild
    request -- in a shape a held-out study can aggregate over.

    The expected side is the *declarative contract*
    (`dependency_contract.decide_unit_change` / `.decide_structural`, which run
    their own `DependencyGraph.impact_of` traversal over their own declared
    sensitivity table). It is never derived from the plan: `RecompilationPlan
    .to_rebuild` is `dict.fromkeys(stale + unresolved)`, so comparing a planner
    -derived expectation against the planner would be an algebraic identity
    that passes whatever the executor does. The actual side is
    `plan.to_rebuild`. `silent` is `expected - actual`, and it names artifacts;
    a count alone cannot be audited.

    `could_have_exhibited` is the gate-power denominator, and it means one
    specific thing: **this pair contained a detected typed change whose
    contract verdict is a non-empty seed set, so a silent disappearance was
    reachable here.** It is not "this pair was judged" and not "a violation
    occurred". A pair with no typed change, or one whose every channel resolved
    to NO_DEPENDENT (nothing was expected, so nothing could go missing) or to
    UNRESOLVED (the contract declined to decide), has no power and must not
    enter the denominator -- inflating it is precisely how an untested endpoint
    reports as well-tested. `channels_detected` is reported alongside so a
    looser denominator remains computable without re-running anything.
    """
    reads = merged_reads(before_deps, after_deps)
    actual = frozenset(plan.to_rebuild)
    planner_verdicts = {
        resolution.change_channel.value: resolution.verdict.value
        for resolution in plan.facet_resolutions
    }

    by_channel: dict[str, list[Any]] = {}
    for change in diff.changes:
        by_channel.setdefault(change.channel.value, []).append(change)

    per_channel: list[dict[str, Any]] = []
    expected_all: set[str] = set()

    for name in sorted(by_channel):
        if name in ("unchanged", "unresolved"):
            # Not a typed change. `unresolved` is the diff declining to settle
            # an identity, which `plan_recompilation` already fails closed on
            # by its own separate path; counting it here would double-count it
            # as a channel closure question.
            continue
        if name == "structural":
            decisions = [decide_structural(diff, graph_reads=reads)]
        else:
            decisions = [
                decide_unit_change(change, graph_reads=reads)
                for change in by_channel[name]
            ]

        expected = set()
        for decision in decisions:
            expected |= set(decision.dependents)
        if any(d.verdict is Verdict.SEED_SET for d in decisions):
            contract_verdict = Verdict.SEED_SET.value
        elif any(d.verdict is Verdict.UNRESOLVED for d in decisions):
            contract_verdict = Verdict.UNRESOLVED.value
        else:
            contract_verdict = Verdict.NO_DEPENDENT.value

        counted = bool(expected) and contract_verdict == Verdict.SEED_SET.value
        if counted:
            reason = "a non-empty contract seed set makes a disappearance reachable"
        elif contract_verdict == Verdict.UNRESOLVED.value:
            reason = "excluded: " + (decisions[0].reason or "contract returned UNRESOLVED")
        else:
            reason = (
                "excluded: contract proved NO_DEPENDENT against the declared "
                "readers, so nothing could go missing"
            )

        expected_all |= expected
        per_channel.append(
            {
                "change_channel": name,
                "supported": name in E9_SUPPORTED_CHANNELS,
                "contract_verdict": contract_verdict,
                # Empty for SEMANTIC/STRUCTURAL: the planner resolves those on
                # its own long-standing path and records no FacetResolution
                # for them. Absence here is not a missing verdict.
                "planner_facet_verdict": planner_verdicts.get(name, ""),
                "seeds": sorted({d.subject for d in decisions}),
                "expected": sorted(expected),
                "actual": sorted(actual & expected) if expected else [],
                "silent": sorted(expected - actual),
                "counted_in_denominator": counted,
                "reason": reason,
            }
        )

    silent = sorted(expected_all - actual)
    could = any(entry["counted_in_denominator"] for entry in per_channel)
    if could:
        no_power_reason = ""
    elif not per_channel:
        no_power_reason = "no typed change was detected in this pair"
    else:
        no_power_reason = (
            "typed changes were detected ("
            + ", ".join(str(e["change_channel"]) for e in per_channel)
            + ") but none produced a non-empty contract seed set"
        )

    return {
        "schema": E9_SCHEMA,
        "could_have_exhibited": could,
        "no_power_reason": no_power_reason,
        "channels_detected": [entry["change_channel"] for entry in per_channel],
        "expected": sorted(expected_all),
        "actual": sorted(actual),
        "silent": silent,
        "silent_disappearance": bool(silent),
        "unresolved_facet_changes": [
            resolution.as_record()
            for resolution in plan.facet_resolutions
            if resolution.verdict is FacetVerdict.UNRESOLVED
        ],
        "per_channel": per_channel,
    }


@dataclass(frozen=True, slots=True)
class PlanInputs:
    """Everything the selective path decided, before it executed anything.

    Extracted so a judge can ask the declarative dependency contract what
    SHOULD have been seeded by `diff`, and compare that against what the
    planner actually seeded (`planned`), without recomputing the diff from the
    same documents by hand. A hand-recomputed diff is a second implementation
    of the same step, and two implementations of one step is how a comparison
    quietly stops describing the thing it claims to describe.

    The detected change (`diff`) is deliberately production's own. E9 asks
    whether every change production DETECTED reached a rebuild request; taking
    the detection from anywhere else would be measuring a different system. It
    is the EXPECTATION -- which artifacts a detected change should seed -- that
    must come from the contract and never from the planner.
    """

    diff: Any
    before_deps: dict[str, tuple[str, ...]]
    after_deps: dict[str, tuple[str, ...]]
    planned: frozenset[str]
    inventory: tuple[str, ...]
    #: Carried so run_pair's identity arithmetic keeps its denominator without
    #: re-deriving the snapshots it was computed from.
    after_units: tuple[Any, ...]
    #: The plan object itself, for consumers that need more than the seeded set
    #: (E9 reads its per-artifact reasons).
    plan: Any


def plan_inputs(before: dict[str, Any], after: dict[str, Any]) -> PlanInputs:
    """The diff, the dependency maps and the plan, with nothing built yet."""
    before_deps, _ = inventory_and_dependencies(before)
    after_deps, _ = inventory_and_dependencies(after)

    before_units, before_shape = snapshots(before)
    after_units, after_shape = snapshots(after)

    diff = diff_documents(
        before_sha256=before["source_digest"],
        after_sha256=after["source_digest"],
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=after["source_id"],
    )

    graph = graph_for(before_deps, after_deps)
    union_inventory = sorted({*before_deps, *after_deps})
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=union_inventory,
        structural_policy=StructuralPolicy.PRECISE,
    )
    return PlanInputs(
        diff=diff,
        before_deps=before_deps,
        after_deps=after_deps,
        planned=frozenset(plan.to_rebuild),
        inventory=tuple(union_inventory),
        after_units=tuple(after_units),
        plan=plan,
    )


def run_pair(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    inputs = plan_inputs(before, after)
    diff = inputs.diff
    before_deps = inputs.before_deps
    after_deps = inputs.after_deps

    prior_state = build_all(before)
    after_full = build_all(after)
    planned = set(inputs.planned)

    final: dict[str, str] = {}
    rebuilt: list[str] = []
    carried: list[str] = []
    unplanned_missing: list[str] = []
    for artifact in sorted(after_deps):
        if artifact in planned:
            # A real rebuild reads the AFTER revision. The selective path is
            # allowed to read the source it is compiling; what it must not do is
            # read the oracle.
            final[artifact] = after_full[artifact]
            rebuilt.append(artifact)
        elif artifact in prior_state:
            final[artifact] = prior_state[artifact]
            carried.append(artifact)
        else:
            # Not planned and no prior value. The plan missed a new artifact.
            # Recorded and left visibly wrong rather than quietly filled in.
            final[artifact] = MISSING
            unplanned_missing.append(artifact)

    # Stage 1 of 2: right after the classification loop decided, per artifact,
    # whether a rebuild was executed (``rebuilt``) or the prior value was
    # carried forward (``carried``). This catches a scheduler defect where the
    # plan named an artifact for rebuild and the loop nonetheless classified
    # it as carried-forward.
    check_no_unexecuted_carry_forward(
        required_to_rebuild=planned,
        executed=set(rebuilt),
        carried_forward=set(carried),
        stage=STAGE_POST_EXECUTION,
    )
    # Non-raising sibling of the check above, same inputs: a clean pass here
    # is only meaningful when ``could_have_exhibited`` is True. This engine's
    # classification loop makes ``planned`` and ``carried`` disjoint by
    # construction (an artifact is appended to ``rebuilt`` XOR ``carried``,
    # never both), so ``could_have_exhibited`` is expected to read False on
    # every natural pair -- that is the honest reading of this seam today,
    # not a defect in the observation.
    post_execution_observation = observe_no_unexecuted_carry_forward(
        required_to_rebuild=planned,
        executed=set(rebuilt),
        carried_forward=set(carried),
        stage=STAGE_POST_EXECUTION,
    )

    retired = sorted(set(before_deps) - set(after_deps))

    unnecessary = [
        artifact
        for artifact in rebuilt
        if artifact in prior_state and prior_state[artifact] == after_full[artifact]
    ]

    identity = {
        "unresolved": len(diff.unresolved),
        "new": sum(1 for change in diff.changes if change.kind is ChangeKind.UNIT_ADDED),
        "removed": sum(
            1 for change in diff.changes if change.kind is ChangeKind.UNIT_REMOVED
        ),
        "modified": sum(
            1 for change in diff.changes if change.kind is ChangeKind.MODIFIED_CLAIM
        ),
    }
    identity["continuation"] = max(
        0, len(inputs.after_units) - identity["new"] - identity["unresolved"]
    )

    # Stage 2 of 2: right before ``final`` is handed back as the state this
    # revision activates/promotes to. Independently re-derived from the
    # ``final`` state dict itself -- not from the ``rebuilt``/``carried``
    # bookkeeping lists checked above -- so a defect that desyncs the
    # bookkeeping from what ``final`` actually holds is still caught. An
    # artifact only counts as executed-with-proof here when its activated
    # value is byte-equal to ``after_full``, the independently computed full
    # rebuild of the AFTER revision; this is the only equivalence proof this
    # engine can currently produce; it cannot prove ``after_full`` itself is
    # correct (that is the SFI2/oracle comparison another lane owns).
    proven_equivalent = {
        artifact
        for artifact in rebuilt
        if final.get(artifact) == after_full.get(artifact)
    }
    check_no_unexecuted_carry_forward(
        required_to_rebuild=planned,
        executed=proven_equivalent,
        carried_forward=set(carried) | (set(rebuilt) - proven_equivalent),
        stage=STAGE_PRE_ACTIVATION,
    )
    # Same non-raising sibling at the second stage. Because
    # ``proven_equivalent`` is always equal to ``set(rebuilt)`` here (``final``
    # was assigned directly from ``after_full`` in the classification loop,
    # so the comparison below is an identity, not an independent proof), this
    # stage's ``carried_forward`` collapses to ``set(carried)`` -- the same
    # disjoint-by-construction set as stage 1. Its ``could_have_exhibited`` is
    # therefore also expected to read False on every natural pair: this
    # stage's equivalence proof carries no statistical power today, and this
    # observation is what makes that visible instead of silently passing.
    pre_activation_observation = observe_no_unexecuted_carry_forward(
        required_to_rebuild=planned,
        executed=proven_equivalent,
        carried_forward=set(carried) | (set(rebuilt) - proven_equivalent),
        stage=STAGE_PRE_ACTIVATION,
    )

    return {
        "source_id": after["source_id"],
        "engine": "selective",
        "pid": os.getpid(),
        "change_id": diff.change_id,
        "detected_change_kinds": sorted({change.kind.value for change in diff.changes}),
        "structural_change_present": diff.structural_change_present,
        "identity_outcomes": identity,
        "unresolved_present": bool(diff.unresolved),
        "affected_subgraph": sorted(inputs.planned),
        "artifact_inventory": sorted(after_deps),
        "selective_rebuild_set": rebuilt,
        "carried_forward_set": carried,
        "retired_set": retired,
        "unplanned_missing": unplanned_missing,
        "unnecessary_rebuild_set": unnecessary,
        "rebuilt_fraction": len(rebuilt) / len(after_deps) if after_deps else 0.0,
        "work_avoided_fraction": len(carried) / len(after_deps) if after_deps else 0.0,
        "state": final,
        "state_hash": _digest(final),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        # Additive field: counts from the non-raising invariant observations,
        # not a replacement for any existing key. Consumers that do not know
        # about it are unaffected.
        "carry_observations": [
            post_execution_observation.as_record(),
            pre_activation_observation.as_record(),
        ],
        # Additive, same shape of addition as `carry_observations` above: E9's
        # per-pair evidence, with its own power denominator. Aggregation into
        # the executor summary block is `compiler.rebuild_equivalence`'s, not
        # this module's.
        "e9_channel_closure": e9_channel_closure(
            diff=diff, before_deps=before_deps, after_deps=after_deps, plan=inputs.plan
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    result = run_pair(before, after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"state_hash": result["state_hash"], "pid": result["pid"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
