"""Pareto frontier: a hand-checked set (masterplan section 28.3)."""

from __future__ import annotations

from arena.reports.pareto import ParetoPoint, non_dominated


def test_strictly_better_point_dominates() -> None:
    points = [
        ParetoPoint(system="cheap_and_good", x_cost=1.0, y_quality=0.9),
        ParetoPoint(system="expensive_and_worse", x_cost=2.0, y_quality=0.8),
    ]
    result = non_dominated(points)
    assert result == {"cheap_and_good": True, "expensive_and_worse": False}


def test_hand_checked_frontier_of_four_points() -> None:
    # A: cheapest, mediocre quality -> frontier (nobody cheaper or equal-and-better).
    # B: mid cost, best quality -> frontier.
    # C: same cost as B, strictly worse quality -> dominated by B.
    # D: most expensive, worst quality -> dominated by everyone.
    points = [
        ParetoPoint(system="A", x_cost=10.0, y_quality=0.5),
        ParetoPoint(system="B", x_cost=20.0, y_quality=0.9),
        ParetoPoint(system="C", x_cost=20.0, y_quality=0.6),
        ParetoPoint(system="D", x_cost=30.0, y_quality=0.4),
    ]
    result = non_dominated(points)
    assert result == {"A": True, "B": True, "C": False, "D": False}


def test_identical_points_both_survive() -> None:
    points = [
        ParetoPoint(system="A", x_cost=5.0, y_quality=0.7),
        ParetoPoint(system="B", x_cost=5.0, y_quality=0.7),
    ]
    result = non_dominated(points)
    assert result == {"A": True, "B": True}


def test_single_point_is_always_non_dominated() -> None:
    result = non_dominated([ParetoPoint(system="only", x_cost=1.0, y_quality=1.0)])
    assert result == {"only": True}


def test_empty_input_returns_empty_result() -> None:
    assert non_dominated([]) == {}


def test_lower_cost_same_quality_dominates() -> None:
    points = [
        ParetoPoint(system="cheaper", x_cost=1.0, y_quality=0.5),
        ParetoPoint(system="pricier", x_cost=2.0, y_quality=0.5),
    ]
    result = non_dominated(points)
    assert result == {"cheaper": True, "pricier": False}
