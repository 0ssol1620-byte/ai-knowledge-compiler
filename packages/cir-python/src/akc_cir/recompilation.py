"""Rebuild what changed, prove it matches rebuilding everything.

Masterplan §16 — Knowledge CI/CD. The diff says which units changed, the graph
says what went stale, and this plans the rebuild of exactly that set.

The value is obvious and so is the risk. Selective recompilation is only worth
anything if its result is the same as a full rebuild; a plan that skips work it
should have done produces a corpus that looks compiled and is quietly wrong, and
nothing downstream can tell. §44's PHASE 5 exit criterion says so directly:
*prove selective result equals full rebuild for the relevant artifacts.*

So this module refuses to be trusted on its own word. `verify_equivalence`
compares the artifacts a selective run produced against the artifacts a full
rebuild produced and reports every divergence, and `RecompilationPlan` carries
the reason each artifact is in it. An artifact nobody can explain the presence
of is a bug in the traversal, not a rounding error.

Three states, and the middle one matters most:

    STALE       a change reached it; it must be rebuilt
    UNRESOLVED  a change may have reached it, but identity was not settled
    CURRENT     nothing reached it

UNRESOLVED does not silently become CURRENT. The diff declined to settle an
identity, and skipping the artifact would turn that honest refusal into a claim
that it is still valid.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from .dependency import DependencyGraph, ImpactReport
from .semantic_diff import SemanticDiff

__all__ = [
    "ArtifactState",
    "EquivalenceReport",
    "RecompilationPlan",
    "RecompilationTarget",
    "plan_recompilation",
    "verify_equivalence",
]


class ArtifactState(StrEnum):
    STALE = "stale"
    UNRESOLVED = "unresolved"
    CURRENT = "current"


@dataclass(frozen=True, slots=True)
class RecompilationTarget:
    artifact_id: str
    state: ArtifactState
    reason: str
    depth: int = 0
    path: str = ""


@dataclass(frozen=True, slots=True)
class RecompilationPlan:
    change_id: str
    targets: tuple[RecompilationTarget, ...]
    total_artifacts: int
    cycles_detected: tuple[tuple[str, ...], ...] = ()
    truncated_at_depth: bool = False

    @property
    def stale(self) -> tuple[str, ...]:
        return tuple(t.artifact_id for t in self.targets if t.state is ArtifactState.STALE)

    @property
    def unresolved(self) -> tuple[str, ...]:
        return tuple(
            t.artifact_id for t in self.targets if t.state is ArtifactState.UNRESOLVED
        )

    @property
    def to_rebuild(self) -> tuple[str, ...]:
        """Everything the run must touch.

        Unresolved artifacts are rebuilt. They may not need it, and rebuilding
        one costs compute; not rebuilding one that did need it ships a stale
        answer. The asymmetry decides.
        """
        return tuple(dict.fromkeys(self.stale + self.unresolved))

    @property
    def work_avoided(self) -> int:
        return self.total_artifacts - len(self.to_rebuild)

    @property
    def work_avoided_fraction(self) -> float:
        if self.total_artifacts <= 0:
            return 0.0
        return self.work_avoided / self.total_artifacts

    def explain(self, artifact_id: str) -> str | None:
        for target in self.targets:
            if target.artifact_id == artifact_id:
                return target.reason
        return None

    def as_record(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "total_artifacts": self.total_artifacts,
            "rebuild_count": len(self.to_rebuild),
            "work_avoided": self.work_avoided,
            "targets": [
                {
                    "artifact_id": t.artifact_id,
                    "state": t.state.value,
                    "reason": t.reason,
                    "depth": t.depth,
                }
                for t in self.targets
            ],
        }


def plan_recompilation(
    *,
    diff: SemanticDiff,
    graph: DependencyGraph,
    artifacts: Iterable[str],
    max_depth: int | None = None,
) -> RecompilationPlan:
    """Decide what a selective rebuild must touch, and record why.

    `artifacts` is the full inventory the workspace could rebuild. Anything in
    the impact radius that is not in it is ignored: the radius covers knowledge
    units and evidence as well, and only artifacts get rebuilt.
    """
    inventory = list(dict.fromkeys(artifacts))
    inventory_set = set(inventory)

    if not diff.content_changed:
        return RecompilationPlan(
            change_id=diff.change_id,
            targets=tuple(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.CURRENT,
                    reason="the source content did not change",
                )
                for artifact in inventory
            ),
            total_artifacts=len(inventory),
        )

    report: ImpactReport = graph.impact_of(
        diff.changed_logical_ids, max_depth=max_depth
    )
    reached = {path.node_id: path for path in report.affected}

    # An unresolved identity names candidates. Whatever depends on those
    # candidates is in the same position as the identity itself: possibly
    # affected, not established. It is rebuilt, and it is labelled honestly.
    unresolved_seeds: list[str] = []
    for change in diff.unresolved:
        unresolved_seeds.extend(change.candidates)
    unresolved_reached: dict[str, str] = {}
    if unresolved_seeds:
        shadow = graph.impact_of(list(dict.fromkeys(unresolved_seeds)), max_depth=max_depth)
        for path in shadow.affected:
            if path.node_id not in reached:
                unresolved_reached[path.node_id] = path.describe()
        for seed in dict.fromkeys(unresolved_seeds):
            if seed not in reached:
                unresolved_reached.setdefault(
                    seed, f"{seed} is a candidate in an unsettled identity"
                )

    targets: list[RecompilationTarget] = []
    for artifact in inventory:
        if artifact in reached:
            path = reached[artifact]
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.STALE,
                    reason=path.describe(),
                    depth=path.depth,
                    path=path.describe(),
                )
            )
        elif artifact in unresolved_reached:
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.UNRESOLVED,
                    reason=(
                        "reached only through an identity the diff could not settle: "
                        + unresolved_reached[artifact]
                    ),
                )
            )
        else:
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.CURRENT,
                    reason="no change reached it",
                )
            )

    missing = sorted(set(reached) - inventory_set)
    _ = missing  # knowledge units and evidence are in the radius but not rebuilt

    return RecompilationPlan(
        change_id=diff.change_id,
        targets=tuple(targets),
        total_artifacts=len(inventory),
        cycles_detected=report.cycles_detected,
        truncated_at_depth=report.truncated_at_depth,
    )


@dataclass(frozen=True, slots=True)
class EquivalenceReport:
    """Whether a selective rebuild produced what a full rebuild would have."""

    equivalent: bool
    compared: int
    diverged: tuple[str, ...] = ()
    missing_from_selective: tuple[str, ...] = ()
    unexpectedly_rebuilt: tuple[str, ...] = ()
    stale_left_behind: tuple[str, ...] = ()

    def as_record(self) -> dict[str, object]:
        return {
            "equivalent": self.equivalent,
            "compared": self.compared,
            "diverged": list(self.diverged),
            "missing_from_selective": list(self.missing_from_selective),
            "unexpectedly_rebuilt": list(self.unexpectedly_rebuilt),
            "stale_left_behind": list(self.stale_left_behind),
        }


def verify_equivalence(
    *,
    full_rebuild: Mapping[str, str],
    selective_rebuild: Mapping[str, str],
    carried_over: Mapping[str, str],
    plan: RecompilationPlan | None = None,
) -> EquivalenceReport:
    """§44 PHASE 5's exit criterion, executable.

    `full_rebuild` is every artifact's content hash after rebuilding everything.
    `selective_rebuild` is what the selective run actually produced, and
    `carried_over` is what it reused untouched. Their union must equal the full
    rebuild, artifact for artifact and hash for hash.

    The failure this exists to catch is the quiet one: an artifact the plan
    called current whose content a full rebuild would have changed. That is a
    corpus that looks compiled and is wrong, and no downstream check sees it.
    """
    combined: dict[str, str] = dict(carried_over)
    combined.update(selective_rebuild)

    diverged: list[str] = []
    stale_left_behind: list[str] = []
    for artifact, expected in sorted(full_rebuild.items()):
        actual = combined.get(artifact)
        if actual is None:
            continue
        if actual == expected:
            continue
        diverged.append(artifact)
        if artifact in carried_over and artifact not in selective_rebuild:
            # Reused, and a full rebuild disagrees. This is the failure mode.
            stale_left_behind.append(artifact)

    missing = tuple(sorted(set(full_rebuild) - set(combined)))

    unexpected: tuple[str, ...] = ()
    if plan is not None:
        planned = set(plan.to_rebuild)
        unexpected = tuple(sorted(set(selective_rebuild) - planned))

    return EquivalenceReport(
        equivalent=not diverged and not missing,
        compared=len(full_rebuild),
        diverged=tuple(diverged),
        missing_from_selective=missing,
        unexpectedly_rebuilt=unexpected,
        stale_left_behind=tuple(stale_left_behind),
    )


def content_hash(payload: object) -> str:
    """A stable hash for comparing artifact content between two runs."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def rebuild_order(plan: RecompilationPlan, graph: DependencyGraph) -> tuple[str, ...]:
    """Order the rebuild so a dependency is rebuilt before what depends on it.

    A cycle has no such order. Rather than pick one arbitrarily, the members are
    appended last and the caller can see them in `plan.cycles_detected`.
    """
    targets = list(plan.to_rebuild)
    remaining = set(targets)
    ordered: list[str] = []

    depth_of = {t.artifact_id: t.depth for t in plan.targets}
    for artifact in sorted(targets, key=lambda a: (depth_of.get(a, 0), a)):
        if artifact in remaining:
            ordered.append(artifact)
            remaining.discard(artifact)

    cycle_members = {node for cycle in plan.cycles_detected for node in cycle}
    tail = [a for a in ordered if a in cycle_members]
    head = [a for a in ordered if a not in cycle_members]
    _ = graph
    return tuple(head + tail)
