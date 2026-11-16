"""V30 findings F30-03 (temporal) and F30-04 (dependency), U34 corrective work.

F30-03: a fact whose `recorded_at` is unknown is not *known* at any past moment.
F30-04: a directed cycle reached through sibling BFS branches is reported.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from itertools import pairwise

import pytest
from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType
from akc_cir.temporal import (
    TemporalFact,
    TemporalPolicy,
    TemporalSource,
    TemporalTimeline,
    replay_context,
)

JAN1 = datetime(2026, 1, 1, tzinfo=UTC)
JAN2 = datetime(2026, 1, 2, tzinfo=UTC)
JAN3 = datetime(2026, 1, 3, tzinfo=UTC)


def _fact(lid: str, value: str, **kw) -> TemporalFact:
    kw.setdefault("valid_from", JAN1)
    kw.setdefault("temporal_source", TemporalSource.EXPLICIT)
    return TemporalFact(lid, value, **kw)


# --------------------------------------------------------------------------
# F30-03
# --------------------------------------------------------------------------


def test_unrecorded_fact_is_not_known_in_a_historical_query() -> None:
    timeline = TemporalTimeline([_fact("undated", "v")])
    answer = timeline.as_of(valid_at=JAN2, known_at=JAN2)
    assert answer.values == ()
    assert answer.excluded_unrecorded == ("undated",)
    # reported separately from "no stated validity"
    assert answer.excluded_unknown == ()
    assert "no recorded time" in answer.describe()


def test_unrecorded_fact_is_not_known_with_known_at_only() -> None:
    timeline = TemporalTimeline([_fact("undated", "v")])
    assert timeline.as_of(known_at=JAN2).values == ()
    assert not _fact("undated", "v").known_at(JAN2)


def test_unrecorded_fact_is_still_served_in_current_mode() -> None:
    timeline = TemporalTimeline([_fact("undated", "v")])
    assert timeline.as_of(valid_at=JAN2).values == ("v",)
    assert timeline.as_of().values == ("v",)
    assert timeline.as_of(valid_at=JAN2).excluded_unrecorded == ()


def test_replay_context_excludes_unrecorded_and_filters_the_report() -> None:
    timeline = TemporalTimeline(
        [
            _fact("undated", "v"),
            _fact("other", "w"),
            _fact("recorded", "r", recorded_at=JAN1),
        ]
    )
    answer = replay_context(timeline, at=JAN2)
    assert answer.values == ("r",)
    assert answer.excluded_unrecorded == ("undated", "other")
    narrowed = replay_context(timeline, at=JAN2, logical_ids=["undated"])
    assert narrowed.values == ()
    assert narrowed.excluded_unrecorded == ("undated",)


def test_unrecorded_and_unknown_validity_are_reported_apart() -> None:
    timeline = TemporalTimeline(
        [
            TemporalFact("no-validity", "x", recorded_at=JAN1),
            _fact("undated", "v"),
        ]
    )
    answer = timeline.as_of(valid_at=JAN2, known_at=JAN2, policy=TemporalPolicy.EXCLUDE_UNKNOWN)
    assert answer.excluded_unknown == ("no-validity",)
    assert answer.excluded_unrecorded == ("undated",)


def test_recorded_after_the_cutoff_is_excluded_and_not_called_unrecorded() -> None:
    timeline = TemporalTimeline([_fact("late", "v", recorded_at=JAN3)])
    answer = timeline.as_of(valid_at=JAN2, known_at=JAN2)
    assert answer.values == ()
    assert answer.excluded_unrecorded == ()


# --------------------------------------------------------------------------
# F30-04
# --------------------------------------------------------------------------


def _graph(pairs: list[tuple[str, str]], et: EdgeType = EdgeType.SUPPORTS) -> DependencyGraph:
    return DependencyGraph([DependencyEdge(a, b, et) for a, b in pairs])


def test_sibling_branch_cycle_is_reported() -> None:
    graph = _graph([("root", "b"), ("root", "c"), ("b", "c"), ("c", "b")])
    report = graph.impact_of(["root"])
    assert report.affected_ids == ("b", "c")
    assert [p.depth for p in report.affected] == [1, 1]
    assert report.cycles_detected == (("b", "c", "b"),)


def test_disconnected_cycle_inside_the_affected_set_is_reported() -> None:
    # p <-> q is reached from two different siblings; it is not on any one path.
    graph = _graph([("root", "m"), ("root", "n"), ("m", "p"), ("n", "q"), ("p", "q"), ("q", "p")])
    report = graph.impact_of(["root"])
    assert set(report.affected_ids) == {"m", "n", "p", "q"}
    assert report.cycles_detected == (("p", "q", "p"),)


def test_lineage_cycle_is_not_duplicated_by_the_scc_pass() -> None:
    graph = _graph([("root", "b"), ("b", "c"), ("c", "b")])
    assert graph.impact_of(["root"]).cycles_detected == (("b", "c", "b"),)


def test_acyclic_diamond_reports_no_cycle() -> None:
    graph = _graph([("root", "l"), ("root", "r"), ("l", "s"), ("r", "s")])
    report = graph.impact_of(["root"])
    assert report.cycles_detected == ()
    assert set(report.affected_ids) == {"l", "r", "s"}


@pytest.mark.parametrize(
    "edge_type, reverse",
    [
        (EdgeType.SUPPORTS, False),
        (EdgeType.CONSUMED_BY, False),
        (EdgeType.EXPORTS_TO, False),
        (EdgeType.INVALIDATES, False),
        (EdgeType.DEPENDS_ON, True),
        (EdgeType.DERIVED_FROM, True),
    ],
)
def test_sibling_cycle_under_every_propagating_spelling(edge_type: EdgeType, reverse: bool) -> None:
    pairs = [("root", "b"), ("root", "c"), ("b", "c"), ("c", "b")]
    if reverse:  # upstream edges are written the way the sentence reads
        pairs = [(b, a) for a, b in pairs]
    report = _graph(pairs, edge_type).impact_of(["root"])
    assert set(report.affected_ids) == {"b", "c"}
    assert report.cycles_detected == (("b", "c", "b"),)


@pytest.mark.parametrize("edge_type", [EdgeType.REFERENCES, EdgeType.SUPERSEDES])
def test_inert_relation_loop_is_not_a_dependency_cycle(edge_type: EdgeType) -> None:
    graph = DependencyGraph(
        [
            DependencyEdge("root", "b", EdgeType.SUPPORTS),
            DependencyEdge("root", "c", EdgeType.SUPPORTS),
            DependencyEdge("b", "c", edge_type),
            DependencyEdge("c", "b", edge_type),
        ]
    )
    assert graph.impact_of(["root"]).cycles_detected == ()


def test_scc_pass_respects_as_of() -> None:
    graph = DependencyGraph(
        [
            DependencyEdge("root", "b", EdgeType.SUPPORTS),
            DependencyEdge("root", "c", EdgeType.SUPPORTS),
            DependencyEdge("b", "c", EdgeType.SUPPORTS),
            DependencyEdge("c", "b", EdgeType.SUPPORTS, valid_to=JAN2),
        ]
    )
    assert graph.impact_of(["root"], as_of=JAN3).cycles_detected == ()
    assert graph.impact_of(["root"], as_of=JAN1).cycles_detected == (("b", "c", "b"),)


def test_scc_pass_is_iterative_on_a_deep_graph() -> None:
    n = 2000  # past the default recursion limit if the pass were recursive
    pairs = [(f"n{i}", f"n{i + 1}") for i in range(n)] + [(f"n{n}", "n1")]
    report = _graph(pairs).impact_of(["n0"])
    assert len(report.affected) == n
    assert len(report.cycles_detected) == 1


# --------------------------------------------------------------------------
# F30-04 follow-up: every reported cycle is a real walk, never a sorted list
# --------------------------------------------------------------------------


def _live_edges(graph: DependencyGraph, moment: datetime | None = None) -> set[tuple[str, str]]:
    return {(a, b) for a in graph.nodes for b, _ in graph._successors(a, moment)}


def _assert_real_cycle(cycle: tuple[str, ...], live: set[tuple[str, str]]) -> None:
    assert len(cycle) >= 2 and cycle[0] == cycle[-1]
    for hop in pairwise(cycle):
        assert hop in live, f"{hop} is not a dependency edge in {cycle}"


def test_three_node_sibling_scc_reports_real_walks() -> None:
    # sorted members (a, b, c) would print a -> b -> c, but there is no a->b or b->c edge
    graph = _graph(
        [("root", "a"), ("root", "b"), ("root", "c"), ("a", "c"), ("c", "b"), ("b", "a")]
    )
    report = graph.impact_of(["root"])
    live = _live_edges(graph)
    assert report.cycles_detected
    for cycle in report.cycles_detected:
        _assert_real_cycle(cycle, live)
    assert report.cycles_detected == (("a", "c", "b", "a"),)


def _random_graph(seed: int) -> DependencyGraph:
    rng = random.Random(seed)
    names = [f"n{i}" for i in range(rng.randint(3, 9))]
    pairs = {(rng.choice(names), rng.choice(names)) for _ in range(rng.randint(2, 18))}
    edges = [DependencyEdge(a, b, EdgeType.SUPPORTS) for a, b in sorted(pairs) if a != b]
    return DependencyGraph(edges)


def _acyclic_graph(seed: int) -> DependencyGraph:
    rng = random.Random(seed)
    names = [f"n{i}" for i in range(8)]
    draws = [(rng.choice(names), rng.choice(names)) for _ in range(14)]
    pairs = {(a, b) for a, b in draws if a < b}
    return DependencyGraph([DependencyEdge(a, b, EdgeType.SUPPORTS) for a, b in sorted(pairs)])


def _reachable(graph: DependencyGraph, seed: str) -> set[str]:
    seen, todo = {seed}, [seed]
    while todo:
        for nxt, _ in graph._successors(todo.pop(), None):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def _sccs(graph: DependencyGraph, nodes: set[str]) -> list[set[str]]:
    reach = {n: _reachable(graph, n) & nodes for n in nodes}
    comps = {frozenset(m for m in nodes if m in reach[n] and n in reach[m]) for n in nodes}
    return [set(c) for c in comps if len(c) > 1]


@pytest.mark.parametrize("seed", range(300))
def test_every_reported_cycle_is_a_real_walk_on_random_graphs(seed: int) -> None:
    graph = _random_graph(seed)
    live = _live_edges(graph)
    for root in sorted(graph.nodes)[:2]:
        report = graph.impact_of([root])
        covered = set()
        for cycle in report.cycles_detected:
            _assert_real_cycle(cycle, live)
            covered.update(cycle)
        reached = {root, *report.affected_ids}
        for component in _sccs(graph, reached):
            assert component <= covered


@pytest.mark.parametrize("seed", range(50))
def test_dags_report_no_cycle(seed: int) -> None:
    graph = _acyclic_graph(seed)
    for root in sorted(graph.nodes):
        assert graph.impact_of([root]).cycles_detected == ()
