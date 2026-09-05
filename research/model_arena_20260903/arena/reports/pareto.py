"""Pareto frontier over cost and quality (masterplan section 28.3).

One frontier per benchmark: ``x`` is a cost-like number the campaign wants
low (``$/1,000 pages`` or GPU seconds/page), ``y`` is a quality-like number
the campaign wants high. A point is *dominated* when another point is at
least as good on both axes and strictly better on one — the classic
definition, computed here rather than eyeballed off a scatter plot so the
"non-dominated" label in a report means something reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ParetoPoint", "non_dominated"]


@dataclass(frozen=True, slots=True)
class ParetoPoint:
    system: str
    x_cost: float
    y_quality: float


def _dominates(a: ParetoPoint, b: ParetoPoint) -> bool:
    """Does ``a`` dominate ``b``? Lower cost, higher quality, at least one strict."""

    not_worse = a.x_cost <= b.x_cost and a.y_quality >= b.y_quality
    strictly_better = a.x_cost < b.x_cost or a.y_quality > b.y_quality
    return not_worse and strictly_better


def non_dominated(points: list[ParetoPoint]) -> dict[str, bool]:
    """``{system: True}`` if non-dominated, ``{system: False}`` if dominated.

    Ties (identical cost and quality) are treated as mutually non-dominating,
    so two systems that land on exactly the same point both survive.
    """

    result: dict[str, bool] = {}
    for candidate in points:
        dominated = any(
            _dominates(other, candidate) for other in points if other.system != candidate.system
        )
        result[candidate.system] = not dominated
    return result
