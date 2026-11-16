"""V30 findings F30-03 (temporal) and F30-04 (dependency), U34 corrective work.

F30-03: a fact whose `recorded_at` is unknown is not *known* at any past moment.
F30-04: a directed cycle reached through sibling BFS branches is reported.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
