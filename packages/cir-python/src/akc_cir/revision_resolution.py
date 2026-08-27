"""Recompute governed knowledge resolution after a source revision.

This module is the narrow B15 vertical slice. The protected authority, temporal,
dependency, recompilation and world-state modules already implement their local
invariants; the missing behavior was the composition that asks, after a source
revision, whether authority/applicability/valid-time resolution changed and what
that makes stale.

No database or production publish is performed here. A changed resolution may
stage an in-memory CANDIDATE world through the existing ``WorldStateRegistry``;
it is never activated by this module. The normal manifest/validation/equivalence
publish gate remains mandatory and separate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .authority import ClaimContext, ScopedClaim, rank_claims, resolve_authority
from .dependency import DependencyChannel, DependencyGraph, ImpactPath
from .recompilation import ArtifactState, RecompilationPlan, RecompilationTarget
from .world_state import WorldState, WorldStateRegistry

__all__ = [
    "ResolutionDimension",
    "ResolutionRecomputeResult",
    "ResolutionSnapshot",
    "recompute_revision_resolution",
]


class ResolutionDimension(StrEnum):
    AUTHORITY = "AUTHORITY"
    APPLICABILITY = "APPLICABILITY"
    VALID_TIME = "VALID_TIME"


@dataclass(frozen=True, slots=True)
class ResolutionSnapshot:
    """Auditable outcome of recomputing one governed subject."""

    status: str
    selected_claim_id: str | None
    selected_value: str | None
    applicable_claim_ids: tuple[str, ...]
    authority_fingerprint: str
    applicability_fingerprint: str
    valid_time_fingerprint: str
    required_review: bool
    reason: str

    @classmethod
    def from_claims(
        cls,
        claims: Sequence[ScopedClaim],
        context: ClaimContext,
    ) -> ResolutionSnapshot:
        resolution = resolve_authority(claims, context)
        ranked = rank_claims(claims, context)
        applicable = tuple(claim.claim_id for _, claim in ranked)
        return cls(
            status=resolution.status.value,
            selected_claim_id=(resolution.claim.claim_id if resolution.claim else None),
            selected_value=(resolution.claim.value if resolution.claim else None),
            applicable_claim_ids=applicable,
            authority_fingerprint=_fingerprint(
                [
                    {
                        "claim_id": claim.claim_id,
                        "authority": int(claim.authority),
                        "source_status": int(claim.source_status),
                    }
                    for _, claim in ranked
                ]
            ),
            applicability_fingerprint=_fingerprint(
                [
                    {
                        "claim_id": claim.claim_id,
                        "scope": sorted(claim.scope.items()),
                    }
                    for _, claim in ranked
                ]
            ),
            valid_time_fingerprint=_fingerprint(
                [
                    {
                        "claim_id": claim.claim_id,
                        "valid_from": _iso(claim.valid_from),
                        "valid_to": _iso(claim.valid_to),
                    }
                    for claim in sorted(claims, key=lambda item: item.claim_id)
                ]
            ),
            required_review=resolution.required_review,
            reason=resolution.reason,
        )


@dataclass(frozen=True, slots=True)
class ResolutionRecomputeResult:
    logical_id: str
    change_id: str
    before: ResolutionSnapshot
    after: ResolutionSnapshot
    changed_dimensions: tuple[ResolutionDimension, ...]
    plan: RecompilationPlan
    candidate_world: WorldState | None
    blocked_on_review: bool

    @property
    def changed(self) -> bool:
        return bool(self.changed_dimensions)

    def as_record(self) -> dict[str, object]:
        return {
            "logical_id": self.logical_id,
            "change_id": self.change_id,
            "changed_dimensions": [item.value for item in self.changed_dimensions],
            "before_status": self.before.status,
            "before_claim_id": self.before.selected_claim_id,
            "after_status": self.after.status,
            "after_claim_id": self.after.selected_claim_id,
            "rebuild": list(self.plan.to_rebuild),
            "candidate_world_state_id": (
                self.candidate_world.world_state_id if self.candidate_world else None
            ),
            "candidate_world_status": (
                self.candidate_world.status.value if self.candidate_world else None
            ),
            "blocked_on_review": self.blocked_on_review,
            "publish_authorized": False,
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _change_id(
    logical_id: str,
    before: ResolutionSnapshot,
    after: ResolutionSnapshot,
    dimensions: Sequence[ResolutionDimension],
) -> str:
    return "rsv_" + _fingerprint(
        {
            "logical_id": logical_id,
            "before": {
                "status": before.status,
                "claim": before.selected_claim_id,
                "authority": before.authority_fingerprint,
                "applicability": before.applicability_fingerprint,
                "valid_time": before.valid_time_fingerprint,
            },
            "after": {
                "status": after.status,
                "claim": after.selected_claim_id,
                "authority": after.authority_fingerprint,
                "applicability": after.applicability_fingerprint,
                "valid_time": after.valid_time_fingerprint,
            },
            "dimensions": [item.value for item in dimensions],
        }
    ).split(":", 1)[1][:32]


def _dimensions(
    before: ResolutionSnapshot,
    after: ResolutionSnapshot,
) -> tuple[ResolutionDimension, ...]:
    changed: list[ResolutionDimension] = []
    if (
        before.status != after.status
        or before.selected_claim_id != after.selected_claim_id
        or before.authority_fingerprint != after.authority_fingerprint
    ):
        changed.append(ResolutionDimension.AUTHORITY)
    if before.applicability_fingerprint != after.applicability_fingerprint:
        changed.append(ResolutionDimension.APPLICABILITY)
    if before.valid_time_fingerprint != after.valid_time_fingerprint:
        changed.append(ResolutionDimension.VALID_TIME)
    return tuple(changed)


def _impact_paths(
    *,
    logical_id: str,
    dimensions: Sequence[ResolutionDimension],
    graph: DependencyGraph,
    as_of: datetime,
) -> dict[str, tuple[ResolutionDimension, ImpactPath]]:
    reached: dict[str, tuple[ResolutionDimension, ImpactPath]] = {}
    for dimension in dimensions:
        # Authority/applicability change which semantic claim governs. Valid-time
        # changes use the temporal channel so temporal-insensitive projections are
        # not rebuilt merely because a date moved.
        channel = (
            DependencyChannel.TEMPORAL
            if dimension is ResolutionDimension.VALID_TIME
            else DependencyChannel.SEMANTIC
        )
        report = graph.impact_of([logical_id], as_of=as_of, channel=channel)
        for path in report.affected:
            reached.setdefault(path.node_id, (dimension, path))
    return reached


def _plan(
    *,
    change_id: str,
    artifacts: Iterable[str],
    reached: dict[str, tuple[ResolutionDimension, ImpactPath]],
) -> RecompilationPlan:
    inventory = list(dict.fromkeys(artifacts))
    targets: list[RecompilationTarget] = []
    for artifact in inventory:
        hit = reached.get(artifact)
        if hit is None:
            targets.append(
                RecompilationTarget(
                    artifact_id=artifact,
                    state=ArtifactState.CURRENT,
                    reason="governed resolution change did not reach this artifact",
                )
            )
            continue
        dimension, path = hit
        targets.append(
            RecompilationTarget(
                artifact_id=artifact,
                state=ArtifactState.STALE,
                reason=f"{dimension.value}: {path.describe()}",
                depth=path.depth,
                path=path.describe(),
            )
        )
    return RecompilationPlan(
        change_id=change_id,
        targets=tuple(targets),
        total_artifacts=len(inventory),
    )


def recompute_revision_resolution(
    *,
    logical_id: str,
    before_claims: Sequence[ScopedClaim],
    after_claims: Sequence[ScopedClaim],
    context: ClaimContext,
    graph: DependencyGraph,
    artifacts: Iterable[str],
    world_registry: WorldStateRegistry | None = None,
    candidate_world_state_id: str | None = None,
    compiler_version: str = "",
    built_at: datetime | None = None,
) -> ResolutionRecomputeResult:
    """Recompute authority/applicability/time and plan the resulting dirty set.

    If a world registry and candidate id are supplied, a CANDIDATE is staged only
    after an actual governed-resolution change. This function never validates or
    publishes it; the existing world-state publish gate remains the sole path to
    ACTIVE.
    """

    before = ResolutionSnapshot.from_claims(before_claims, context)
    after = ResolutionSnapshot.from_claims(after_claims, context)
    dimensions = _dimensions(before, after)
    change_id = _change_id(logical_id, before, after, dimensions)
    reached = _impact_paths(
        logical_id=logical_id,
        dimensions=dimensions,
        graph=graph,
        as_of=context.as_of,
    )
    plan = _plan(change_id=change_id, artifacts=artifacts, reached=reached)

    candidate: WorldState | None = None
    if dimensions and world_registry is not None and candidate_world_state_id is not None:
        candidate = world_registry.stage(
            world_state_id=candidate_world_state_id,
            compiler_version=compiler_version or "resolution-recompute",
            built_at=built_at or context.as_of,
            change_set_id=change_id,
        )

    return ResolutionRecomputeResult(
        logical_id=logical_id,
        change_id=change_id,
        before=before,
        after=after,
        changed_dimensions=dimensions,
        plan=plan,
        candidate_world=candidate,
        blocked_on_review=after.required_review,
    )
