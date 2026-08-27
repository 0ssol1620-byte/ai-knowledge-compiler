"""Exact stale-consumption tracing over the typed dependency graph.

This is the narrow B14 embodiment. It does not attempt to patent or reinvent
logging. A consumption receipt records which governed units a prior answer or
agent action actually consumed. Those exact relations become ``CONSUMED_BY``
edges. When a semantic/temporal change propagates through the normal dependency
graph, this module identifies only the prior receipts that the typed impact path
reaches and preserves the path explaining why each receipt is at risk.

No notification, re-execution, write-MCP, or automated downstream remediation is
performed here. Those are policy layers over this evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from .dependency import (
    DependencyChannel,
    DependencyEdge,
    DependencyGraph,
    EdgeType,
    ImpactPath,
)

__all__ = [
    "ConsumptionReceipt",
    "StaleConsumptionRisk",
    "consumption_dependency_edges",
    "trace_stale_consumptions",
]


@dataclass(frozen=True, slots=True)
class ConsumptionReceipt:
    consumption_id: str
    world_state_id: str
    consumed_unit_ids: tuple[str, ...]
    answer_claim_ids: tuple[str, ...] = ()
    response_hash: str = ""
    principal_ref: str = ""
    downstream_action_ref: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.consumption_id or not self.world_state_id:
            raise ValueError("consumption_id and world_state_id are required")
        if not self.consumed_unit_ids:
            raise ValueError("a consumption receipt must name at least one consumed unit")
        if len(self.consumed_unit_ids) != len(set(self.consumed_unit_ids)):
            raise ValueError("consumed_unit_ids must be unique")

    @property
    def dependency_node_id(self) -> str:
        return f"consumption:{self.consumption_id}"


@dataclass(frozen=True, slots=True)
class StaleConsumptionRisk:
    consumption_id: str
    source_world_state_id: str
    candidate_world_state_id: str
    affected_node_id: str
    reason_path: str
    changed_ids: tuple[str, ...]
    downstream_action_ref: str | None = None

    def as_record(self) -> dict[str, object]:
        return {
            "consumption_id": self.consumption_id,
            "source_world_state_id": self.source_world_state_id,
            "candidate_world_state_id": self.candidate_world_state_id,
            "affected_node_id": self.affected_node_id,
            "reason_path": self.reason_path,
            "changed_ids": list(self.changed_ids),
            "downstream_action_ref": self.downstream_action_ref,
            "status": "STALE_RISK",
        }


def consumption_dependency_edges(
    receipt: ConsumptionReceipt,
    *,
    channels: frozenset[DependencyChannel] = frozenset(
        {DependencyChannel.SEMANTIC, DependencyChannel.TEMPORAL}
    ),
) -> tuple[DependencyEdge, ...]:
    """Materialize exact consumed-unit → receipt lineage as typed edges."""

    return tuple(
        DependencyEdge(
            source_id=unit_id,
            target_id=receipt.dependency_node_id,
            edge_type=EdgeType.CONSUMED_BY,
            channels=channels,
        )
        for unit_id in receipt.consumed_unit_ids
    )


def _path_map(paths: Iterable[ImpactPath]) -> dict[str, ImpactPath]:
    return {path.node_id: path for path in paths}


def trace_stale_consumptions(
    *,
    changed_ids: Sequence[str],
    graph: DependencyGraph,
    receipts: Sequence[ConsumptionReceipt],
    candidate_world_state_id: str,
    as_of: datetime | None = None,
    channel: DependencyChannel = DependencyChannel.SEMANTIC,
) -> tuple[StaleConsumptionRisk, ...]:
    """Return exact prior consumptions reached by typed change propagation.

    A receipt that merely existed at the time is not marked. It must have an
    explicit ``CONSUMED_BY`` path in ``graph``. This avoids turning temporal
    coincidence into a claim that an answer actually depended on a changed unit.
    """

    report = graph.impact_of(
        list(dict.fromkeys(changed_ids)),
        as_of=as_of,
        channel=channel,
    )
    reached = _path_map(report.affected)
    changed = tuple(dict.fromkeys(changed_ids))

    risks: list[StaleConsumptionRisk] = []
    for receipt in sorted(receipts, key=lambda item: item.consumption_id):
        path = reached.get(receipt.dependency_node_id)
        if path is None:
            continue
        risks.append(
            StaleConsumptionRisk(
                consumption_id=receipt.consumption_id,
                source_world_state_id=receipt.world_state_id,
                candidate_world_state_id=candidate_world_state_id,
                affected_node_id=path.node_id,
                reason_path=path.describe(),
                changed_ids=changed,
                downstream_action_ref=receipt.downstream_action_ref,
            )
        )
    return tuple(risks)
