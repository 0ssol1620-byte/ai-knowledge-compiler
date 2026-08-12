"""The dependency graph, and what a change makes stale.

Masterplan §15 and §16.1. The diff says which knowledge units changed; this says
what else stops being true as a result. It is the layer behind the product's
central screen -- *12 documents, 41 knowledge units, 8 RAG chunks, 2 agent
workflows affected* -- and behind the claim that only the affected part needs
rebuilding.

Two decisions shape the whole module.

**Edge direction is declared, not inferred.** An edge is always written the way
the sentence reads: `A DEPENDS_ON B`, `A CONSUMED_BY B`. But impact does not
always travel the way the arrow points. If a chunk depends on a clause, changing
the clause invalidates the chunk, so impact runs *backwards* along DEPENDS_ON
and forwards along CONSUMED_BY. Each edge type states its own direction rather
than leaving callers to work it out, because getting it backwards produces a
blast radius that is confidently wrong.

**A traversal that cannot explain itself is not usable.** Marking an artifact
stale is a bill for compute and a claim that someone's answer was wrong. Every
affected node comes back with the path that reached it, so the operator can see
*clause 4.2 → chunk 88 → workflow 3* rather than a number.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

__all__ = [
    "DependencyEdge",
    "DependencyGraph",
    "EdgeType",
    "ImpactPath",
    "ImpactReport",
    "Propagation",
]


class Propagation(StrEnum):
    """Which way staleness travels along an edge type."""

    #: `A DEPENDS_ON B` — B changing invalidates A, so impact runs target→source.
    UPSTREAM = "upstream"
    #: `A CONSUMED_BY B` — A changing invalidates B, so impact runs source→target.
    DOWNSTREAM = "downstream"
    #: Records history rather than dependence. Never propagates staleness.
    INERT = "inert"


class EdgeType(StrEnum):
    """§15's edge vocabulary."""

    DERIVED_FROM = "DERIVED_FROM"
    DEPENDS_ON = "DEPENDS_ON"
    SUPPORTS = "SUPPORTS"
    SUPERSEDES = "SUPERSEDES"
    REFERENCES = "REFERENCES"
    CONSUMED_BY = "CONSUMED_BY"
    EXPORTS_TO = "EXPORTS_TO"
    INVALIDATES = "INVALIDATES"

    @property
    def propagation(self) -> Propagation:
        return _PROPAGATION[self]


_PROPAGATION: dict[EdgeType, Propagation] = {
    # "this was made from that" — the source stops being current when the
    # target changes.
    EdgeType.DERIVED_FROM: Propagation.UPSTREAM,
    EdgeType.DEPENDS_ON: Propagation.UPSTREAM,
    # "this evidence supports that claim" — the claim is what goes stale.
    EdgeType.SUPPORTS: Propagation.DOWNSTREAM,
    # A reference is a pointer, not a dependence. A document mentioning another
    # does not become wrong when the other changes, and treating it as impact
    # would make every blast radius the size of the corpus.
    EdgeType.REFERENCES: Propagation.INERT,
    # History. `v3 SUPERSEDES v2` says what happened, not what breaks.
    EdgeType.SUPERSEDES: Propagation.INERT,
    EdgeType.CONSUMED_BY: Propagation.DOWNSTREAM,
    EdgeType.EXPORTS_TO: Propagation.DOWNSTREAM,
    EdgeType.INVALIDATES: Propagation.DOWNSTREAM,
}


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """One edge, optionally bounded in time.

    `valid_from` / `valid_to` carry §15's temporal columns: an edge that was
    retired last month must not propagate staleness in a query about today, and
    an edge that has not started yet must not either.
    """

    source_id: str
    target_id: str
    edge_type: EdgeType
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise ValueError("a dependency edge needs both ends")
        if self.source_id == self.target_id:
            raise ValueError(f"a node cannot depend on itself: {self.source_id}")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("edge valid_to precedes valid_from")

    def live_at(self, moment: datetime | None) -> bool:
        if moment is None:
            return True
        started = self.valid_from is None or moment >= self.valid_from
        not_retired = self.valid_to is None or moment < self.valid_to
        return started and not_retired


@dataclass(frozen=True, slots=True)
class ImpactPath:
    """How the traversal reached a node. The explanation, not decoration."""

    node_id: str
    depth: int
    via: tuple[tuple[str, EdgeType], ...]

    def describe(self) -> str:
        if not self.via:
            return f"{self.node_id} (changed directly)"
        hops = " -> ".join(f"{node} [{edge.value}]" for node, edge in self.via)
        return f"{hops} -> {self.node_id}"


@dataclass(frozen=True, slots=True)
class ImpactReport:
    changed: tuple[str, ...]
    affected: tuple[ImpactPath, ...] = ()
    truncated_at_depth: bool = False
    cycles_detected: tuple[tuple[str, ...], ...] = ()
    unknown_nodes: tuple[str, ...] = ()

    @property
    def affected_ids(self) -> tuple[str, ...]:
        return tuple(path.node_id for path in self.affected)

    def by_kind(self, kinds: dict[str, str]) -> dict[str, int]:
        """Count the blast radius per node kind, for the product's readout.

        A node whose kind is unknown is counted under `unknown` rather than
        dropped: a readout that silently omits what it could not classify
        understates the radius.
        """
        counts: dict[str, int] = {}
        for path in self.affected:
            kind = kinds.get(path.node_id, "unknown")
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def explain(self, node_id: str) -> str | None:
        for path in self.affected:
            if path.node_id == node_id:
                return path.describe()
        return None


class DependencyGraph:
    """An adjacency store with a traversal that terminates and explains itself.

    Postgres is where this lives in production (§15 names an adjacency table and
    a recursive CTE). This is the same semantics in memory, so the propagation
    rules and the cycle behaviour can be tested without a database.
    """

    def __init__(self, edges: Iterable[DependencyEdge] = ()) -> None:
        self._edges: list[DependencyEdge] = []
        self._out: dict[str, list[DependencyEdge]] = {}
        self._in: dict[str, list[DependencyEdge]] = {}
        self._nodes: set[str] = set()
        for edge in edges:
            self.add(edge)

    def add(self, edge: DependencyEdge) -> None:
        self._edges.append(edge)
        self._out.setdefault(edge.source_id, []).append(edge)
        self._in.setdefault(edge.target_id, []).append(edge)
        self._nodes.add(edge.source_id)
        self._nodes.add(edge.target_id)

    def __len__(self) -> int:
        return len(self._edges)

    @property
    def nodes(self) -> frozenset[str]:
        return frozenset(self._nodes)

    def _successors(
        self, node_id: str, moment: datetime | None
    ) -> list[tuple[str, EdgeType]]:
        """Nodes that go stale when `node_id` changes, with the edge that says so."""
        found: list[tuple[str, EdgeType]] = []
        for edge in self._out.get(node_id, ()):
            if edge.edge_type.propagation is Propagation.DOWNSTREAM and edge.live_at(moment):
                found.append((edge.target_id, edge.edge_type))
        for edge in self._in.get(node_id, ()):
            if edge.edge_type.propagation is Propagation.UPSTREAM and edge.live_at(moment):
                found.append((edge.source_id, edge.edge_type))
        # Sorted so two runs over the same graph return the same order, which is
        # what lets an impact report be compared against a previous one.
        return sorted(set(found))

    def impact_of(
        self,
        changed: Sequence[str],
        *,
        max_depth: int | None = None,
        as_of: datetime | None = None,
    ) -> ImpactReport:
        """Everything that stops being current because `changed` changed.

        Breadth-first, so the recorded path to each node is the shortest one --
        the most useful explanation rather than whichever the walk found first.
        A node reached again by a longer route is not re-reported.
        """
        seeds = list(dict.fromkeys(changed))
        unknown = tuple(node for node in seeds if node not in self._nodes)

        visited: set[str] = set(seeds)
        affected: list[ImpactPath] = []
        cycles: list[tuple[str, ...]] = []
        truncated = False

        queue: deque[tuple[str, int, tuple[tuple[str, EdgeType], ...], tuple[str, ...]]] = deque(
            (seed, 0, (), (seed,)) for seed in seeds
        )

        while queue:
            node, depth, via, lineage = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                if self._successors(node, as_of):
                    truncated = True
                continue
            for neighbour, edge_type in self._successors(node, as_of):
                if neighbour in lineage:
                    # Walking it again would not terminate, and the cycle is
                    # worth surfacing: a knowledge graph with a dependence loop
                    # cannot be recompiled in any order.
                    cycle = (*lineage[lineage.index(neighbour):], neighbour)
                    if cycle not in cycles:
                        cycles.append(cycle)
                    continue
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                trail = (*via, (node, edge_type))
                affected.append(ImpactPath(node_id=neighbour, depth=depth + 1, via=trail))
                queue.append((neighbour, depth + 1, trail, (*lineage, neighbour)))

        return ImpactReport(
            changed=tuple(seeds),
            affected=tuple(affected),
            truncated_at_depth=truncated,
            cycles_detected=tuple(cycles),
            unknown_nodes=unknown,
        )

    def provenance_of(
        self, node_id: str, *, max_depth: int | None = None, as_of: datetime | None = None
    ) -> tuple[str, ...]:
        """What this node was built from — the reverse question to impact.

        Impact answers "what breaks if this changes". This answers "where did
        this come from", which is the Evidence Inspector's question.
        """
        seen: set[str] = {node_id}
        order: list[str] = []
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        while queue:
            node, depth = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            upstream: list[str] = []
            for edge in self._out.get(node, ()):
                if edge.edge_type.propagation is Propagation.UPSTREAM and edge.live_at(as_of):
                    upstream.append(edge.target_id)
            for edge in self._in.get(node, ()):
                if edge.edge_type.propagation is Propagation.DOWNSTREAM and edge.live_at(as_of):
                    upstream.append(edge.source_id)
            for parent in sorted(set(upstream)):
                if parent in seen:
                    continue
                seen.add(parent)
                order.append(parent)
                queue.append((parent, depth + 1))
        return tuple(order)
