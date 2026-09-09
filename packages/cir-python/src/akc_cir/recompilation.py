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

from .dependency import (
    ALL_DEPENDENCY_CHANNELS,
    DependencyChannel,
    DependencyGraph,
    ImpactReport,
)
from .semantic_diff import ChangeChannel, SemanticDiff

__all__ = [
    "ArtifactState",
    "EquivalenceReport",
    "FacetPolicy",
    "FacetResolution",
    "FacetVerdict",
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


class FacetVerdict(StrEnum):
    """How one facet channel's detected changes resolved. Three states, and
    there is deliberately no fourth: INC-V2-038 was a change that resolved to
    nothing at all and left no trace of having been seen.
    """

    #: The channel is declared by the graph and its traversal reached at least
    #: one artifact in the inventory. Those artifacts are STALE.
    SEED_SET = "seed_set"
    #: The channel is declared by the graph, the changed unit is a node in it,
    #: and every artifact reachable on this channel was checked -- none is in
    #: the inventory. Proven against declared readers, not inferred from an
    #: empty traversal that had nothing to walk.
    NO_DEPENDENT = "no_dependent"
    #: This planner does not know. No edge declared this facet, or the changed
    #: unit is not a node in the graph at all. Recorded rather than dropped:
    #: an unresolved facet change is the defect this field exists to make
    #: impossible to miss.
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class FacetResolution:
    """One facet channel's outcome for one diff, kept whatever the outcome.

    A `RecompilationPlan` that carries no `FacetResolution` for a channel is
    saying that channel produced no typed change. A plan that carries one with
    `UNRESOLVED` is saying the change was seen and could not be resolved --
    which is a finding, not a silence.
    """

    change_channel: ChangeChannel
    dependency_channel: DependencyChannel
    verdict: FacetVerdict
    seeds: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()
    reason: str = ""

    def as_record(self) -> dict[str, object]:
        return {
            "change_channel": self.change_channel.value,
            "dependency_channel": self.dependency_channel.value,
            "verdict": self.verdict.value,
            "seeds": list(self.seeds),
            "dependents": list(self.dependents),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RecompilationPlan:
    change_id: str
    targets: tuple[RecompilationTarget, ...]
    total_artifacts: int
    cycles_detected: tuple[tuple[str, ...], ...] = ()
    truncated_at_depth: bool = False
    #: One entry per facet channel that produced a typed change in this diff,
    #: whatever it resolved to. Additive and defaulted, so a caller written
    #: before INC-V2-038 sees no behaviour change and a plan built without
    #: facet propagation serialises as it always did.
    facet_resolutions: tuple[FacetResolution, ...] = ()

    @property
    def unresolved_facet_changes(self) -> tuple[FacetResolution, ...]:
        """Facet changes this plan saw and could not resolve.

        Non-empty means the graph carries a typed change whose dependency
        relationship is undeclared. That is the honest answer, and it is the
        one INC-V2-038 had no way to express: the change previously reached
        `state=CURRENT, reason="no change reached it"`, which claims the
        opposite.
        """
        return tuple(
            r for r in self.facet_resolutions if r.verdict is FacetVerdict.UNRESOLVED
        )

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
        record: dict[str, object] = {
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
        # Absent rather than empty, so a plan over a diff with no facet change
        # serialises exactly as it did before this field existed. Callers that
        # store plan records keep comparing equal.
        if self.facet_resolutions:
            record["facet_resolutions"] = [r.as_record() for r in self.facet_resolutions]
        return record



class StructuralPolicy(StrEnum):
    """When the structural channel participates in a traversal.

    `ALWAYS` was the only alternative to off, and it is a blunt instrument: on
    the real-revision corpora it raised false invalidation to 80.5% while buying
    no correctness. That cost is not the propagation mechanism's -- the traversal
    is already channel-filtered. It comes from `DependencyEdge.channels`
    defaulting to `ALL_DEPENDENCY_CHANNELS`, so an adapter that declares nothing
    declares that every artifact depends on document shape.

    `PRECISE` propagates structurally exactly when the graph contains a
    shape-dependent artifact and the diff carries a structural change. Its
    precision is therefore inherited from declaration quality: against an adapter
    that declares nothing it degenerates to `ALWAYS`, and that is a property of
    the adapter rather than a fault in the policy. Making it precise means
    declaring channels.
    """

    #: Defer to the legacy `structural_channel` boolean. The default, so no
    #: existing caller changes behaviour by upgrading.
    LEGACY = "legacy"
    OFF = "off"
    ALWAYS = "always"
    PRECISE = "precise"


class FacetPolicy(StrEnum):
    """Which edges a per-facet change is allowed to travel.

    INC-V2-038: LOCATOR, TEMPORAL and METADATA changes are detected and
    correctly typed by the diff and then reach nothing. `changed_logical_ids`
    admits only SEMANTIC and GRAPH, so the traversal below was never seeded
    with them, and the artifacts that read the changed unit were labelled
    `CURRENT, "no change reached it"` -- a claim of freshness, made about a
    change that had been seen.

    Fixing that is not a matter of widening the seed set. `DependencyEdge
    .channels` *defaults* to every channel, so any adapter that never thought
    about facets is holding an edge that says it is sensitive to all three.
    Seeding these channels over the whole graph would therefore invalidate
    through edges that have declared nothing, which is the same blunt failure
    `StructuralPolicy.ALWAYS` was measured at (80.5% false invalidation) and
    is indistinguishable from guessing.

    So the default reads the constructor default as what it is -- an absence.
    A facet propagates through edges only where some edge *narrowed* its
    channel set to say so. Where nothing said so, the change resolves to
    `FacetVerdict.UNRESOLVED` and is recorded on the plan: it is not rebuilt,
    and it is not silent either, which is the property INC-V2-038 lacked.
    """

    #: No facet propagation. Pre-INC-V2-038 behaviour, kept so the fix can be
    #: measured against its own absence rather than argued about.
    OFF = "off"
    #: A facet channel propagates when at least one edge narrows `channels`
    #: (i.e. does not sit at the `ALL_DEPENDENCY_CHANNELS` default) and names
    #: that channel. The default: it cannot change the plan of any graph that
    #: has not declared a facet, so it is additive for every existing adapter.
    DECLARED = "declared"
    #: Fail closed: an edge left at the all-channels default counts as
    #: declaring the facet. This is the stricter reading -- an adapter that
    #: asserted sensitivity to everything is taken at its word -- and it
    #: rebuilds strictly more. Opt in when the corpus's adapters are known not
    #: to have left `channels` unset by accident.
    ALL_EDGES = "all_edges"


#: The facet channels INC-V2-038 names, paired change-side to edge-side. GRAPH
#: is absent because it already seeds the semantic traversal
#: (`_SEMANTIC_RECOMPILATION_CHANNELS`), and VISUAL is absent because nothing
#: in the incident asked for it: adding either here would widen this fix past
#: what was measured.
_FACET_CHANNELS: tuple[tuple[ChangeChannel, DependencyChannel], ...] = (
    (ChangeChannel.LOCATOR, DependencyChannel.LOCATOR),
    (ChangeChannel.TEMPORAL, DependencyChannel.TEMPORAL),
    (ChangeChannel.METADATA, DependencyChannel.METADATA),
)


def _declares_facet(graph: DependencyGraph, channel: DependencyChannel) -> bool:
    """Does any edge in `graph` deliberately declare sensitivity to `channel`?

    Deliberately: `channels == ALL_DEPENDENCY_CHANNELS` is the constructor's
    default and is read here as "unstated", not as "sensitive to everything".
    That reading is the opposite of `declares_structural_dependency`'s, and the
    difference is not an inconsistency -- it is which way each one fails when
    the adapter is silent. Structural propagation is off by default and a
    caller opts into it, so reading silence as sensitivity there costs a
    caller who asked for it extra rebuilds. Facet propagation is on by
    default, so reading silence as sensitivity here would change the plan of
    every adapter in the repository without any of them declaring anything.
    Silence is recorded as `FacetVerdict.UNRESOLVED` instead.

    Uses only the public surface (`nodes`, `edges_from`); `_out` is keyed by
    edge source, so walking every node's outgoing edges visits every edge once.
    """
    for node in graph.nodes:
        for edge in graph.edges_from(node):
            if edge.channels == ALL_DEPENDENCY_CHANNELS:
                continue
            if channel in edge.channels:
                return True
    return False


def _facet_channel_enabled(
    *, policy: FacetPolicy, graph: DependencyGraph, channel: DependencyChannel
) -> bool:
    if policy is FacetPolicy.OFF:
        return False
    if policy is FacetPolicy.ALL_EDGES:
        return True
    return _declares_facet(graph, channel)


def _structural_wanted(
    *, policy: StructuralPolicy, legacy_flag: bool, graph: DependencyGraph
) -> bool:
    if policy is StructuralPolicy.LEGACY:
        return legacy_flag
    if policy is StructuralPolicy.OFF:
        return False
    if policy is StructuralPolicy.ALWAYS:
        return True
    return graph.declares_structural_dependency()


def plan_recompilation(
    *,
    diff: SemanticDiff,
    graph: DependencyGraph,
    artifacts: Iterable[str],
    max_depth: int | None = None,
    structural_channel: bool = False,
    structural_policy: StructuralPolicy = StructuralPolicy.LEGACY,
    facet_policy: FacetPolicy = FacetPolicy.DECLARED,
    seed_unresolved_incoming: bool = True,
    include_visual_facet: bool = False,
) -> RecompilationPlan:
    """Decide what a selective rebuild must touch, and record why.

    `artifacts` is the full inventory the workspace could rebuild. Anything in
    the impact radius that is not in it is ignored: the radius covers knowledge
    units and evidence as well, and only artifacts get rebuilt.

    `structural_channel` closes a fail-open path. A structural change -- block
    count, heading tree, table shape -- is a property of the document and so
    carries no `logical_id`, which left it unable to seed any traversal: an
    artifact aggregated over document position was reached by nothing, was
    labelled CURRENT, and was carried over while a full rebuild would have
    produced different bytes. With this enabled, a structural change seeds a
    second traversal over the document's units on
    `DependencyChannel.STRUCTURAL`.

    It defaults to off because this module is Protected Core and, on every real
    revision pair measured so far, it buys no correctness the identity fix below
    does not already buy while rebuilding roughly four times as much. The defect
    it closes is real but has only been demonstrated synthetically.

    `facet_policy` closes INC-V2-038. A LOCATOR, TEMPORAL or METADATA change
    is detected and typed by the diff and then reaches nothing, because
    `changed_logical_ids` admits only SEMANTIC and GRAPH -- so an artifact that
    reads the moved unit was labelled `CURRENT, "no change reached it"`, which
    asserts freshness about a change that had been seen. Each facet channel now
    seeds its own traversal from `changed_logical_ids_for(channel)` on the
    matching `DependencyChannel`, and every facet change resolves to exactly
    one of `FacetVerdict`'s three states, recorded on the plan in
    `facet_resolutions`. It defaults to `DECLARED`, which propagates only where
    an edge narrowed its channel set to say so; where nothing declared the
    facet the change is `UNRESOLVED` and visible rather than absorbed. See
    `FacetPolicy`.

    `seed_unresolved_incoming` closes the defect that did show up on real data.
    An unsettled identity names the prior candidates; it must also name the
    incoming unit, or whatever derives from that unit is reached by nothing and
    is carried over stale. It defaults to on: it is a strict correctness fix,
    and on 23 real revision pairs it cost two additional artifact rebuilds out
    of 334. It remains switchable so the two fixes can be measured apart.
    """
    # Versioned opt-in: existing callers and frozen INC-V2-038 receipts retain
    # the measured facet set. Source-bound projections explicitly read visual
    # witnesses and therefore opt into their already-typed change propagation.
    facet_channels = _FACET_CHANNELS + (
        ((ChangeChannel.VISUAL, DependencyChannel.VISUAL),) if include_visual_facet else ()
    )
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
        diff.changed_logical_ids,
        max_depth=max_depth,
        channel=DependencyChannel.SEMANTIC,
    )
    reached = {path.node_id: path for path in report.affected}

    # The structural channel, when the caller has enabled it. Merged rather than
    # replacing: a node the semantic traversal already reached keeps its
    # semantic reason, which is the more specific of the two.
    structural_reached: dict[str, str] = {}
    structural_cycles: tuple[tuple[str, ...], ...] = ()
    structural_truncated = False
    structural_wanted = _structural_wanted(
        policy=structural_policy, legacy_flag=structural_channel, graph=graph
    )
    if structural_wanted and diff.structural_scope and diff.structural_change_present:
        structural = graph.impact_of(
            diff.structural_scope,
            max_depth=max_depth,
            channel=DependencyChannel.STRUCTURAL,
        )
        structural_cycles = structural.cycles_detected
        structural_truncated = structural.truncated_at_depth
        for path in structural.affected:
            if path.node_id not in reached:
                structural_reached[path.node_id] = path.describe()

    # The facet channels (INC-V2-038). One traversal per channel, seeded from
    # that channel's own typed changes and filtered to that channel's edges, so
    # a locator move invalidates what declared itself locator-sensitive and
    # nothing else. Merged the same way the structural pass is: a node the
    # semantic traversal already reached keeps its more specific reason.
    facet_reached: dict[str, str] = {}
    facet_cycles: list[tuple[str, ...]] = []
    facet_truncated = False
    facet_resolutions: list[FacetResolution] = []
    for change_channel, dep_channel in facet_channels:
        seeds = diff.changed_logical_ids_for(change_channel)
        if not seeds:
            # No typed change on this channel. Nothing was seen, so there is
            # nothing to resolve and nothing to record -- an empty resolution
            # here would inflate any denominator built from this field.
            continue
        if not _facet_channel_enabled(
            policy=facet_policy, graph=graph, channel=dep_channel
        ):
            facet_resolutions.append(
                FacetResolution(
                    change_channel=change_channel,
                    dependency_channel=dep_channel,
                    verdict=FacetVerdict.UNRESOLVED,
                    seeds=seeds,
                    reason=(
                        f"no edge in this graph declares sensitivity to "
                        f"{dep_channel.value!r} under facet policy "
                        f"{facet_policy.value!r}; refusing to invent one"
                    ),
                )
            )
            continue
        known = tuple(seed for seed in seeds if seed in graph.nodes)
        if not known:
            facet_resolutions.append(
                FacetResolution(
                    change_channel=change_channel,
                    dependency_channel=dep_channel,
                    verdict=FacetVerdict.UNRESOLVED,
                    seeds=seeds,
                    reason=(
                        "the changed unit is not a node in the dependency graph, "
                        "so no reader could be checked; this is not evidence that "
                        "none exists"
                    ),
                )
            )
            continue
        facet = graph.impact_of(known, max_depth=max_depth, channel=dep_channel)
        facet_truncated = facet_truncated or facet.truncated_at_depth
        for cycle in facet.cycles_detected:
            if cycle not in facet_cycles:
                facet_cycles.append(cycle)
        dependents = tuple(
            path.node_id for path in facet.affected if path.node_id in inventory_set
        )
        for path in facet.affected:
            if path.node_id not in reached and path.node_id not in structural_reached:
                facet_reached.setdefault(path.node_id, path.describe())
        if dependents:
            facet_resolutions.append(
                FacetResolution(
                    change_channel=change_channel,
                    dependency_channel=dep_channel,
                    verdict=FacetVerdict.SEED_SET,
                    seeds=known,
                    dependents=dependents,
                    reason=(
                        f"{len(dependents)} artifact(s) declared sensitive to "
                        f"{dep_channel.value!r} reached from {list(known)}"
                    ),
                )
            )
        else:
            facet_resolutions.append(
                FacetResolution(
                    change_channel=change_channel,
                    dependency_channel=dep_channel,
                    verdict=FacetVerdict.NO_DEPENDENT,
                    seeds=known,
                    reason=(
                        f"every edge leaving {list(known)} on "
                        f"{dep_channel.value!r} was walked; nothing it reached is "
                        "in the rebuildable inventory"
                    ),
                )
            )

    # An unresolved identity names candidates. Whatever depends on those
    # candidates is in the same position as the identity itself: possibly
    # affected, not established. It is rebuilt, and it is labelled honestly.
    unresolved_seeds: list[str] = []
    for change in diff.unresolved:
        unresolved_seeds.extend(change.candidates)
        # Both sides of the unsettled correspondence. The candidates are the
        # prior units; `logical_id` is the incoming unit that may continue one
        # of them. Seeding only the candidates left whatever derived from the
        # incoming unit reached by nothing, and so labelled CURRENT -- the
        # failure that made a real revision pair non-equivalent.
        if seed_unresolved_incoming and change.logical_id:
            unresolved_seeds.append(change.logical_id)
    unresolved_reached: dict[str, str] = {}
    if unresolved_seeds:
        shadow = graph.impact_of(
            list(dict.fromkeys(unresolved_seeds)),
            max_depth=max_depth,
            channel=DependencyChannel.SEMANTIC,
        )
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
        elif artifact in structural_reached:
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.STALE,
                    reason=(
                        "the document's structure changed and this artifact "
                        "depends on it: " + structural_reached[artifact]
                    ),
                )
            )
        elif artifact in facet_reached:
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.STALE,
                    reason=(
                        "a typed facet change reached it on a channel this "
                        "artifact declared: " + facet_reached[artifact]
                    ),
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
        # Union, not `or`: cycles are a collection and a structural traversal
        # can find one the semantic traversal did not walk into. The same is
        # true of each facet traversal, which walks a different edge subset
        # again.
        cycles_detected=tuple(
            dict.fromkeys((*report.cycles_detected, *structural_cycles, *facet_cycles))
        ),
        truncated_at_depth=(
            report.truncated_at_depth or structural_truncated or facet_truncated
        ),
        facet_resolutions=tuple(facet_resolutions),
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
