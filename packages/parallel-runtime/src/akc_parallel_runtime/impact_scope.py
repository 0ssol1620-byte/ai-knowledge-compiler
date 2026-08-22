"""Lineage-driven selective replay planning."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LineageEdge:
    source_id: str
    derived_id: str


def impacted_descendants(
    changed_ids: tuple[str, ...], edges: tuple[LineageEdge, ...]
) -> tuple[str, ...]:
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph[edge.source_id].append(edge.derived_id)
    seen = set(changed_ids)
    queue = deque(sorted(changed_ids))
    while queue:
        current = queue.popleft()
        for child in sorted(graph[current]):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return tuple(sorted(seen - set(changed_ids)))


__all__ = ["LineageEdge", "impacted_descendants"]
