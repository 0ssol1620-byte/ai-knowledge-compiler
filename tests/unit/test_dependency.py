"""A blast radius is a bill for compute and a claim someone's answer was wrong.

So the tests are about the two ways it goes wrong: propagating the wrong
direction, which produces a confidently incorrect radius, and failing to
terminate or explain, which makes the radius unusable even when it is right.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from akc_cir.dependency import (
    DependencyEdge,
    DependencyGraph,
    EdgeType,
    Propagation,
)

JAN = datetime(2026, 1, 1, tzinfo=UTC)
JUN = datetime(2026, 6, 1, tzinfo=UTC)
DEC = datetime(2026, 12, 1, tzinfo=UTC)


def _graph(*edges: DependencyEdge) -> DependencyGraph:
    return DependencyGraph(edges)


# --------------------------------------------------------------------------
# Direction — the failure mode that produces a confidently wrong answer
# --------------------------------------------------------------------------


def test_a_chunk_that_depends_on_a_clause_goes_stale_when_the_clause_changes() -> None:
    graph = _graph(DependencyEdge("chunk_88", "ku_warranty", EdgeType.DEPENDS_ON))

    report = graph.impact_of(["ku_warranty"])

    assert report.affected_ids == ("chunk_88",)


def test_the_clause_does_not_go_stale_when_the_chunk_changes() -> None:
    """Impact runs against DEPENDS_ON. Running it forwards inverts the product."""
    graph = _graph(DependencyEdge("chunk_88", "ku_warranty", EdgeType.DEPENDS_ON))

    assert graph.impact_of(["chunk_88"]).affected_ids == ()


def test_a_consumer_goes_stale_when_what_it_consumed_changes() -> None:
    graph = _graph(DependencyEdge("chunk_88", "workflow_3", EdgeType.CONSUMED_BY))

    assert graph.impact_of(["chunk_88"]).affected_ids == ("workflow_3",)


def test_evidence_changing_makes_the_claim_it_supports_stale() -> None:
    graph = _graph(DependencyEdge("ev_17", "ku_warranty", EdgeType.SUPPORTS))

    assert graph.impact_of(["ev_17"]).affected_ids == ("ku_warranty",)


def test_a_mere_reference_does_not_propagate() -> None:
    """Otherwise every blast radius is the size of the corpus."""
    graph = _graph(DependencyEdge("doc_a", "doc_b", EdgeType.REFERENCES))

    assert graph.impact_of(["doc_b"]).affected_ids == ()
    assert graph.impact_of(["doc_a"]).affected_ids == ()


def test_supersedes_records_history_and_breaks_nothing() -> None:
    graph = _graph(DependencyEdge("policy_v3", "policy_v2", EdgeType.SUPERSEDES))

    assert graph.impact_of(["policy_v2"]).affected_ids == ()


def test_every_edge_type_declares_its_direction() -> None:
    for edge_type in EdgeType:
        assert isinstance(edge_type.propagation, Propagation)


# --------------------------------------------------------------------------
# The product's central screen
# --------------------------------------------------------------------------


def _warranty_graph() -> DependencyGraph:
    return _graph(
        DependencyEdge("ku_warranty", "ev_17", EdgeType.DERIVED_FROM),
        DependencyEdge("chunk_88", "ku_warranty", EdgeType.DEPENDS_ON),
        DependencyEdge("chunk_89", "ku_warranty", EdgeType.DEPENDS_ON),
        DependencyEdge("chunk_88", "workflow_3", EdgeType.CONSUMED_BY),
        DependencyEdge("ku_warranty", "vault_md", EdgeType.EXPORTS_TO),
    )


def test_a_clause_change_reaches_its_chunks_exports_and_workflows() -> None:
    report = _warranty_graph().impact_of(["ku_warranty"])

    assert set(report.affected_ids) == {"chunk_88", "chunk_89", "workflow_3", "vault_md"}


def test_the_readout_counts_the_radius_by_kind() -> None:
    report = _warranty_graph().impact_of(["ku_warranty"])
    kinds = {
        "chunk_88": "rag_chunk",
        "chunk_89": "rag_chunk",
        "workflow_3": "agent_workflow",
        "vault_md": "export",
    }

    assert report.by_kind(kinds) == {"rag_chunk": 2, "agent_workflow": 1, "export": 1}


def test_an_unclassified_node_is_counted_not_dropped() -> None:
    """A readout that silently omits what it could not classify understates."""
    report = _warranty_graph().impact_of(["ku_warranty"])

    counts = report.by_kind({"chunk_88": "rag_chunk"})

    assert counts["rag_chunk"] == 1
    assert counts["unknown"] == 3


def test_evidence_at_the_root_reaches_everything_downstream() -> None:
    report = _warranty_graph().impact_of(["ev_17"])

    assert "ku_warranty" in report.affected_ids
    assert "workflow_3" in report.affected_ids


# --------------------------------------------------------------------------
# Explanation — a number nobody can check is not a result
# --------------------------------------------------------------------------


def test_every_affected_node_carries_the_path_that_reached_it() -> None:
    report = _warranty_graph().impact_of(["ku_warranty"])

    explanation = report.explain("workflow_3")

    assert explanation is not None
    assert "ku_warranty" in explanation
    assert "chunk_88" in explanation
    assert "workflow_3" in explanation


def test_the_recorded_path_is_the_shortest_one() -> None:
    graph = _graph(
        DependencyEdge("b", "a", EdgeType.DEPENDS_ON),
        DependencyEdge("c", "b", EdgeType.DEPENDS_ON),
        DependencyEdge("c", "a", EdgeType.DEPENDS_ON),
    )

    report = graph.impact_of(["a"])

    assert next(p for p in report.affected if p.node_id == "c").depth == 1


def test_a_node_is_reported_once_however_many_routes_reach_it() -> None:
    graph = _graph(
        DependencyEdge("left", "root", EdgeType.DEPENDS_ON),
        DependencyEdge("right", "root", EdgeType.DEPENDS_ON),
        DependencyEdge("sink", "left", EdgeType.DEPENDS_ON),
        DependencyEdge("sink", "right", EdgeType.DEPENDS_ON),
    )

    report = graph.impact_of(["root"])

    assert report.affected_ids.count("sink") == 1


# --------------------------------------------------------------------------
# Termination — a graph the compiler cannot order must say so
# --------------------------------------------------------------------------


def test_a_cycle_terminates_instead_of_hanging() -> None:
    graph = _graph(
        DependencyEdge("b", "a", EdgeType.DEPENDS_ON),
        DependencyEdge("c", "b", EdgeType.DEPENDS_ON),
        DependencyEdge("a", "c", EdgeType.DEPENDS_ON),
    )

    report = graph.impact_of(["a"])

    assert set(report.affected_ids) == {"b", "c"}
    assert report.cycles_detected


def test_a_detected_cycle_names_its_members() -> None:
    graph = _graph(
        DependencyEdge("b", "a", EdgeType.DEPENDS_ON),
        DependencyEdge("a", "b", EdgeType.DEPENDS_ON),
    )

    report = graph.impact_of(["a"])

    assert any("a" in cycle and "b" in cycle for cycle in report.cycles_detected)


def test_a_self_edge_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="cannot depend on itself"):
        DependencyEdge("a", "a", EdgeType.DEPENDS_ON)


def test_an_edge_needs_both_ends() -> None:
    with pytest.raises(ValueError, match="needs both ends"):
        DependencyEdge("a", "", EdgeType.DEPENDS_ON)


# --------------------------------------------------------------------------
# Depth — a bounded walk says it was bounded
# --------------------------------------------------------------------------


def test_a_depth_limit_reports_that_it_truncated() -> None:
    graph = _graph(
        DependencyEdge("b", "a", EdgeType.DEPENDS_ON),
        DependencyEdge("c", "b", EdgeType.DEPENDS_ON),
        DependencyEdge("d", "c", EdgeType.DEPENDS_ON),
    )

    report = graph.impact_of(["a"], max_depth=2)

    assert set(report.affected_ids) == {"b", "c"}
    assert report.truncated_at_depth is True


def test_a_walk_that_reached_the_end_does_not_claim_truncation() -> None:
    graph = _graph(DependencyEdge("b", "a", EdgeType.DEPENDS_ON))

    assert graph.impact_of(["a"], max_depth=5).truncated_at_depth is False


# --------------------------------------------------------------------------
# Time — a retired edge does not carry staleness
# --------------------------------------------------------------------------


def test_an_edge_retired_before_the_query_does_not_propagate() -> None:
    graph = _graph(
        DependencyEdge("chunk", "clause", EdgeType.DEPENDS_ON, valid_from=JAN, valid_to=JUN)
    )

    assert graph.impact_of(["clause"], as_of=DEC).affected_ids == ()


def test_the_same_edge_propagates_inside_its_window() -> None:
    graph = _graph(
        DependencyEdge("chunk", "clause", EdgeType.DEPENDS_ON, valid_from=JAN, valid_to=DEC)
    )

    assert graph.impact_of(["clause"], as_of=JUN).affected_ids == ("chunk",)


def test_an_edge_that_has_not_started_does_not_propagate() -> None:
    graph = _graph(DependencyEdge("chunk", "clause", EdgeType.DEPENDS_ON, valid_from=JUN))

    assert graph.impact_of(["clause"], as_of=JAN).affected_ids == ()


def test_without_an_as_of_every_edge_counts() -> None:
    graph = _graph(
        DependencyEdge("chunk", "clause", EdgeType.DEPENDS_ON, valid_from=JAN, valid_to=JUN)
    )

    assert graph.impact_of(["clause"]).affected_ids == ("chunk",)


def test_an_inverted_validity_window_is_refused() -> None:
    with pytest.raises(ValueError, match="valid_to precedes valid_from"):
        DependencyEdge("a", "b", EdgeType.DEPENDS_ON, valid_from=DEC, valid_to=JAN)


# --------------------------------------------------------------------------
# Determinism and honesty about what the graph does not know
# --------------------------------------------------------------------------


def test_two_traversals_of_one_graph_agree() -> None:
    graph = _warranty_graph()

    assert graph.impact_of(["ku_warranty"]).affected_ids == (
        graph.impact_of(["ku_warranty"]).affected_ids
    )


def test_a_seed_the_graph_has_never_seen_is_reported_not_ignored() -> None:
    report = _warranty_graph().impact_of(["ku_warranty", "ku_ghost"])

    assert report.unknown_nodes == ("ku_ghost",)
    assert "ku_warranty" in report.changed


def test_seeds_are_not_listed_as_affected_by_themselves() -> None:
    report = _warranty_graph().impact_of(["ku_warranty"])

    assert "ku_warranty" not in report.affected_ids


# --------------------------------------------------------------------------
# Provenance — the reverse question
# --------------------------------------------------------------------------


def test_provenance_walks_back_to_the_source_evidence() -> None:
    graph = _warranty_graph()

    assert "ku_warranty" in graph.provenance_of("chunk_88")
    assert "ev_17" in graph.provenance_of("chunk_88")


def test_provenance_does_not_return_what_the_node_feeds() -> None:
    graph = _warranty_graph()

    assert "workflow_3" not in graph.provenance_of("chunk_88")
