"""No world state becomes ACTIVE while a stale artifact is labelled CURRENT.

This exists because the *planner* can produce a false-negative CURRENT
classification: a selective rebuild carried two artifacts forward as CURRENT
when their inputs had moved. It is worth being exact about what did and did not
follow from that, because the loose version of this sentence is a false claim.

No wrong world state was ever published. The confirmatory controller exited
non-zero on gate failure and the publish path already refused an equivalence or
integrity failure. What was missing is the case where **no full rebuild exists
to compare against** -- and avoiding the full rebuild is the entire point of
incremental recompilation, so that is the case that matters.

The chronology since is likewise on the record: the first version of this module
had its own blind spot, passing structural-only staleness because its
fingerprint covered unit content, which is exactly what a structural change
leaves alone. That was found by the change-space sweep and fixed here. A gate
that was wrong and is now right is a different thing from a gate that was never
wrong, and this file should not read as the second.

`verify_equivalence` already catches that, but only when a full rebuild is
available to compare against, and in production it is not: avoiding the full
rebuild is the entire point. An integrity check that only works when you did the
work anyway is not an integrity check.

So the gate here asks a question that needs no oracle. Every artifact the plan
called CURRENT declared which inputs it was built from; if the fingerprint of
those inputs still matches what the artifact was built against, carrying it over
is sound, and if it does not, the traversal missed it. That turns "the plan says
it is current" into "the inputs say it is current", and the second one is
checkable.

The order is fixed and each step is a precondition for the next:

    1. every change is accounted for   -- no seed lands outside the graph
    2. the recompile is complete       -- everything planned was actually built
    3. integrity holds                 -- equivalence when an oracle exists,
                                          input fingerprints when it does not
    4. no stale CURRENT artifact       -- the invariant this module is named for
    5. atomic promotion                -- and only then

Running them out of order would let a later step pass on state an earlier one
should have rejected: checking equivalence over an incomplete rebuild compares
against artifacts that were never produced, and promoting before either is the
defect itself.

Every refusal names the artifact and the reason. A gate that fails without
saying which artifact is one nobody can act on, and it will be switched off.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .dependency import DependencyChannel, DependencyGraph
from .recompilation import ArtifactState, EquivalenceReport, RecompilationPlan
from .semantic_diff import SemanticDiff

__all__ = [
    "GateOutcome",
    "GateStep",
    "PromotionGateReport",
    "artifact_input_fingerprint",
    "evaluate_promotion_gate",
]


class GateStep(StrEnum):
    """The ordered preconditions. The value is the name a receipt records."""

    CHANGES_ACCOUNTED = "all_affected_dependencies_accounted_for"
    RECOMPILE_COMPLETE = "recompile_complete"
    INTEGRITY = "equivalence_or_integrity_checks_pass"
    NO_STALE_CURRENT = "no_stale_current_artifacts"
    PROMOTABLE = "atomic_promotion_permitted"


class GateOutcome(StrEnum):
    PASS = "pass"  # noqa: S105 -- a gate verdict, not a credential
    FAIL = "fail"
    #: Reached only when an earlier step failed. Distinguished from a pass so a
    #: receipt cannot be read as "everything after the failure was checked".
    NOT_REACHED = "not_reached"


@dataclass(frozen=True, slots=True)
class StepResult:
    step: GateStep
    outcome: GateOutcome
    detail: str = ""
    offending: tuple[str, ...] = ()

    def as_record(self) -> dict[str, object]:
        return {
            "step": self.step.value,
            "outcome": self.outcome.value,
            "detail": self.detail,
            "offending": list(self.offending),
        }


@dataclass(frozen=True, slots=True)
class PromotionGateReport:
    steps: tuple[StepResult, ...] = ()
    checked_current_artifacts: int = 0
    unverifiable_current_artifacts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def promotable(self) -> bool:
        return all(step.outcome is GateOutcome.PASS for step in self.steps)

    @property
    def failures(self) -> tuple[StepResult, ...]:
        return tuple(s for s in self.steps if s.outcome is GateOutcome.FAIL)

    def as_record(self) -> dict[str, object]:
        return {
            "promotable": self.promotable,
            "steps": [step.as_record() for step in self.steps],
            "checked_current_artifacts": self.checked_current_artifacts,
            "unverifiable_current_artifacts": list(self.unverifiable_current_artifacts),
        }


def artifact_input_fingerprint(
    inputs: Sequence[str],
    unit_hashes: Mapping[str, str],
    *,
    structural: Mapping[str, object] | None = None,
) -> str:
    """A digest over the artifact's declared inputs and their current content.

    Order is preserved rather than sorted: an artifact aggregated over document
    position changes when its inputs are reordered, and sorting here would hide
    exactly the structural movement the dependency channels exist to track.

    A missing input hashes as an explicit absence marker rather than being
    skipped, so removing an input changes the fingerprint instead of silently
    producing the fingerprint of a shorter list.

    `structural` carries the *shape* facts the artifact consumed -- block count,
    reading order, heading path, table geometry -- for artifacts whose bytes
    depend on them. It is kept separate from the unit hashes because a
    structural change moves shape while leaving every unit's content
    byte-identical, and a fingerprint over content alone reads that as "nothing
    happened".

    This is not hypothetical. A sweep across the change space
    (``receipts/change-space-sweep-2026-08-19.json``) found that with the
    structural channel off, **every** structural-only change left a stale
    artifact, and the first version of this function passed all 400 of them: it
    was checking the one thing that had not moved. Passing `structural` is what
    makes the check able to see the change at all.
    """
    digest = hashlib.sha256()
    for name in inputs:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(unit_hashes.get(name, "<ABSENT>").encode("utf-8"))
        digest.update(b"\0")
    if structural is not None:
        digest.update(b"structural\0")
        for key in sorted(structural):
            digest.update(key.encode("utf-8"))
            digest.update(b"\0")
            digest.update(repr(structural[key]).encode("utf-8"))
            digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _declares_structural(graph: DependencyGraph, artifact: str) -> bool:
    """Whether any edge out of this artifact travels the structural channel."""
    return any(
        DependencyChannel.STRUCTURAL in edge.channels
        for edge in graph.edges_from(artifact)
    )


def evaluate_promotion_gate(
    *,
    diff: SemanticDiff,
    graph: DependencyGraph,
    plan: RecompilationPlan,
    rebuilt: Iterable[str],
    equivalence: EquivalenceReport | None = None,
    current_input_fingerprints: Mapping[str, str] | None = None,
    expected_input_fingerprints: Mapping[str, str] | None = None,
    structural_coverage: Collection[str] | None = None,
) -> PromotionGateReport:
    """Decide whether this build may be promoted, and say precisely why not.

    `current_input_fingerprints` is what each CURRENT artifact's inputs hash to
    *now*; `expected_input_fingerprints` is what they hashed to when it was
    built. Where both are present for an artifact, a mismatch means the plan
    called it current and its inputs disagree -- the traversal missed it.

    An artifact for which either is absent is counted as **unverifiable**, not
    as passing. Silence about an artifact is not evidence about it, and this
    module exists because a silent carry-over is what went wrong.

    `structural_coverage` names the artifacts whose fingerprints were computed
    with their shape facts included. Any CURRENT artifact that declares a
    STRUCTURAL dependency edge and is not named there is unverifiable for the
    same reason: its fingerprint was taken over content that a structural change
    does not touch, so a match proves nothing. Requiring the caller to say so,
    rather than inferring it from a fingerprint that looks fine either way, is
    the difference between this check and the one it replaced -- which passed
    400 of 400 structural-only stale artifacts.
    """
    steps: list[StepResult] = []
    rebuilt_set = set(rebuilt)
    # Held outside the step bodies so a refusal carries the same detail a pass
    # would. A gate that names the artifacts only when it succeeds is useless
    # precisely when it matters.
    unverifiable: list[str] = []
    checked = 0

    # --- 1. every change is accounted for ---------------------------------
    seeds = list(diff.changed_logical_ids)
    for change in diff.unresolved:
        seeds.extend(change.candidates)
        if change.logical_id:
            seeds.append(change.logical_id)
    unknown = (
        tuple(sorted(graph.impact_of(seeds).unknown_nodes)) if seeds else ()
    )
    if unknown:
        steps.append(
            StepResult(
                GateStep.CHANGES_ACCOUNTED,
                GateOutcome.FAIL,
                (
                    "a change names units the dependency graph does not contain, "
                    "so nothing can be said about what depends on them"
                ),
                unknown,
            )
        )
    else:
        steps.append(
            StepResult(
                GateStep.CHANGES_ACCOUNTED,
                GateOutcome.PASS,
                f"{len(seeds)} seed(s) all resolve in the graph",
            )
        )

    def skip_rest(from_index: int) -> PromotionGateReport:
        nonlocal_checked = checked
        remaining = [
            GateStep.RECOMPILE_COMPLETE,
            GateStep.INTEGRITY,
            GateStep.NO_STALE_CURRENT,
            GateStep.PROMOTABLE,
        ][from_index:]
        for step in remaining:
            steps.append(
                StepResult(
                    step,
                    GateOutcome.NOT_REACHED,
                    "an earlier precondition failed; this was never evaluated",
                )
            )
        return PromotionGateReport(
            steps=tuple(steps),
            checked_current_artifacts=nonlocal_checked,
            unverifiable_current_artifacts=tuple(sorted(unverifiable)),
        )

    if steps[-1].outcome is GateOutcome.FAIL:
        return skip_rest(0)

    # --- 2. the recompile is complete -------------------------------------
    planned = {t.artifact_id for t in plan.targets if t.state is not ArtifactState.CURRENT}
    not_built = tuple(sorted(planned - rebuilt_set))
    if not_built:
        steps.append(
            StepResult(
                GateStep.RECOMPILE_COMPLETE,
                GateOutcome.FAIL,
                "the plan marked these for rebuild and no rebuilt artifact was supplied",
                not_built,
            )
        )
        return skip_rest(1)
    steps.append(
        StepResult(
            GateStep.RECOMPILE_COMPLETE,
            GateOutcome.PASS,
            f"{len(planned)} planned artifact(s) were rebuilt",
        )
    )

    # --- 3. integrity ------------------------------------------------------
    if equivalence is not None:
        if equivalence.equivalent:
            steps.append(
                StepResult(
                    GateStep.INTEGRITY,
                    GateOutcome.PASS,
                    "the selective result matches a full rebuild",
                )
            )
        else:
            steps.append(
                StepResult(
                    GateStep.INTEGRITY,
                    GateOutcome.FAIL,
                    "the selective result does not match a full rebuild",
                    tuple(equivalence.diverged) + tuple(equivalence.stale_left_behind),
                )
            )
            return skip_rest(2)
    elif current_input_fingerprints is not None:
        # No oracle. The next step is then the only integrity evidence there is,
        # which is why it may not be skipped and why an unverifiable artifact
        # cannot count as verified.
        steps.append(
            StepResult(
                GateStep.INTEGRITY,
                GateOutcome.PASS,
                (
                    "no full-rebuild oracle; integrity rests on the input "
                    "fingerprints checked in the next step"
                ),
            )
        )
    else:
        steps.append(
            StepResult(
                GateStep.INTEGRITY,
                GateOutcome.FAIL,
                (
                    "a selective build was neither compared against a full "
                    "rebuild nor given input fingerprints. A missing check is "
                    "not a passing one"
                ),
            )
        )
        return skip_rest(2)

    # --- 4. no stale CURRENT artifact --------------------------------------
    current = [t.artifact_id for t in plan.targets if t.state is ArtifactState.CURRENT]
    stale_current: list[str] = []
    if current_input_fingerprints is not None and expected_input_fingerprints is not None:
        covered = set(structural_coverage or ())
        for artifact in current:
            now = current_input_fingerprints.get(artifact)
            was = expected_input_fingerprints.get(artifact)
            if now is None or was is None:
                unverifiable.append(artifact)
                continue
            if _declares_structural(graph, artifact) and artifact not in covered:
                # Its bytes depend on document shape; a content-only fingerprint
                # matches precisely when the structural change is invisible.
                unverifiable.append(artifact)
                continue
            checked = checked + 1
            if now != was:
                stale_current.append(artifact)
    elif equivalence is None:
        unverifiable.extend(current)

    if stale_current:
        steps.append(
            StepResult(
                GateStep.NO_STALE_CURRENT,
                GateOutcome.FAIL,
                (
                    "the plan called these current and their declared inputs have "
                    "changed since they were built; the traversal did not reach them"
                ),
                tuple(sorted(stale_current)),
            )
        )
        return skip_rest(3)
    if unverifiable and equivalence is None:
        steps.append(
            StepResult(
                GateStep.NO_STALE_CURRENT,
                GateOutcome.FAIL,
                (
                    "no fingerprint was supplied for these current artifacts, so "
                    "nothing establishes they are current. Fail closed: an "
                    "unchecked artifact is not a checked one"
                ),
                tuple(sorted(unverifiable)),
            )
        )
        return skip_rest(3)
    steps.append(
        StepResult(
            GateStep.NO_STALE_CURRENT,
            GateOutcome.PASS,
            (
                f"{checked} current artifact(s) verified against their inputs"
                if checked
                else "equivalence against a full rebuild covers the current set"
            ),
        )
    )

    steps.append(
        StepResult(
            GateStep.PROMOTABLE,
            GateOutcome.PASS,
            "every precondition passed, in order; the swap may proceed",
        )
    )
    return PromotionGateReport(
        steps=tuple(steps),
        checked_current_artifacts=checked,
        unverifiable_current_artifacts=tuple(sorted(unverifiable)),
    )
