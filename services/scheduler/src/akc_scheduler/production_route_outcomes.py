"""Durable adapter from authorized scheduler routes to production outcomes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from akc_api.arena_models import ProductionRouteOutcome
from akc_api.arena_repository import (
    ProductionRouteOutcomeSpec,
    record_production_route_outcome,
)
from akc_api.models import ModelRegistry
from akc_parallel_runtime.identity import canonical_sha256
from akc_parallel_runtime.routing import AuthorizedRouteDecision, RoutingAuthorityMode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ProductionOutcomeStatus = Literal["EXECUTED", "FAILED", "ABSTAINED", "SHADOW_ONLY"]


class ProductionRouteOutcomeBindingError(ValueError):
    """Terminal evidence does not belong to the authorized selected route."""


@dataclass(frozen=True, slots=True)
class TerminalProviderRouteEvidence:
    """Measured terminal evidence emitted by the provider execution boundary."""

    outcome_id: uuid.UUID
    collection_id: uuid.UUID
    processing_job_id: uuid.UUID
    shard_id: str
    idempotency_key: str
    selected_recipe_id: str
    selected_worker_id: str
    selected_model_revision: str
    runtime_image_digest: str
    permission_snapshot_sha256: str
    route_receipt_sha256: str
    outcome_status: ProductionOutcomeStatus
    executable: bool
    trusted: bool | None
    latency_ms: int | None
    actual_cost_usd: Decimal | None
    selected_model_registry_id: uuid.UUID | None = None
    failure_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome_status not in {"EXECUTED", "FAILED", "ABSTAINED", "SHADOW_ONLY"}:
            raise ProductionRouteOutcomeBindingError("production outcome status is invalid")
        required = (
            self.idempotency_key,
            self.shard_id,
            self.selected_recipe_id,
            self.selected_worker_id,
            self.selected_model_revision,
            self.runtime_image_digest,
        )
        if any(not value.strip() for value in required):
            raise ProductionRouteOutcomeBindingError("terminal route identities are required")
        for field_name in ("permission_snapshot_sha256", "route_receipt_sha256"):
            value = getattr(self, field_name)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ProductionRouteOutcomeBindingError(
                    f"{field_name} must be a lowercase SHA-256 digest"
                )
        if self.outcome_status == "EXECUTED" and (
            not self.executable
            or self.selected_model_registry_id is None
            or self.trusted is None
            or self.latency_ms is None
            or self.actual_cost_usd is None
        ):
            raise ProductionRouteOutcomeBindingError(
                "executed outcomes require trust, latency, and actual cost evidence"
            )
        if self.outcome_status == "FAILED" and (
            not self.executable or not self.failure_reason_codes
        ):
            raise ProductionRouteOutcomeBindingError(
                "failed outcomes require execution and failure reasons"
            )
        if self.outcome_status == "ABSTAINED" and (
            self.executable or not self.failure_reason_codes
        ):
            raise ProductionRouteOutcomeBindingError(
                "abstained outcomes must be non-executable with reasons"
            )
        if self.outcome_status == "SHADOW_ONLY" and self.executable:
            raise ProductionRouteOutcomeBindingError("shadow-only outcomes cannot execute")
        if self.executable and self.selected_model_registry_id is None:
            raise ProductionRouteOutcomeBindingError(
                "provider execution requires an exact model registry identity"
            )
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ProductionRouteOutcomeBindingError("latency cannot be negative")
        if self.actual_cost_usd is not None and self.actual_cost_usd < 0:
            raise ProductionRouteOutcomeBindingError("actual cost cannot be negative")


def _decision_summary(decision: AuthorizedRouteDecision) -> dict[str, object] | None:
    counterfactual = decision.counterfactual
    if counterfactual is None:
        return None
    return {
        "executable": False,
        "policy_version": counterfactual.policy_version,
        "primary_recipe_id": counterfactual.primary.recipe.recipe_id,
        "primary_worker_id": counterfactual.primary.worker.worker_id,
        "secondary_recipe_id": (
            counterfactual.secondary.recipe.recipe_id if counterfactual.secondary else None
        ),
        "secondary_worker_id": (
            counterfactual.secondary.worker.worker_id if counterfactual.secondary else None
        ),
        "speculative": counterfactual.speculative,
        "reason_codes": list(counterfactual.reason_codes),
    }


def build_production_route_outcome_spec(
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    decision: AuthorizedRouteDecision,
    terminal: TerminalProviderRouteEvidence,
) -> ProductionRouteOutcomeSpec:
    """Bind one terminal provider result to the exact authorized route selection."""

    selected = decision.executable.primary
    if (
        terminal.selected_recipe_id != selected.recipe.recipe_id
        or terminal.selected_worker_id != selected.worker.worker_id
        or terminal.selected_model_revision != selected.recipe.model_revision
        or terminal.selected_model_revision != selected.worker.model_revision
        or terminal.runtime_image_digest != selected.recipe.runtime_image_digest
        or terminal.runtime_image_digest != selected.worker.runtime_image_digest
    ):
        raise ProductionRouteOutcomeBindingError(
            "terminal evidence identity differs from the authorized executable route"
        )
    authority = decision.authority
    decision_kind: Literal["DETERMINISTIC", "ADAPTIVE"] = (
        "ADAPTIVE" if authority.effective_mode is RoutingAuthorityMode.CANARY else "DETERMINISTIC"
    )
    policy_sha256 = authority.policy_artifact_sha256 or canonical_sha256(
        {
            "decision_kind": decision_kind,
            "policy_version": decision.executable.policy_version,
        }
    )
    fail_closed = tuple(sorted({*authority.reason_codes, *terminal.failure_reason_codes}))
    if terminal.outcome_status in {"FAILED", "ABSTAINED"} and not fail_closed:
        raise ProductionRouteOutcomeBindingError(
            "failed or abstained outcome lacks fail-closed reasons"
        )
    return ProductionRouteOutcomeSpec(
        id=terminal.outcome_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        collection_id=terminal.collection_id,
        processing_job_id=terminal.processing_job_id,
        shard_id=terminal.shard_id,
        idempotency_key=terminal.idempotency_key,
        requested_mode=authority.requested_mode.value,
        effective_mode=authority.effective_mode.value,
        decision_kind=decision_kind,
        executable=terminal.executable,
        outcome_status=terminal.outcome_status,
        selected_path=f"{selected.recipe.recipe_id}:{selected.worker.worker_id}",
        selected_model_registry_id=terminal.selected_model_registry_id,
        policy_version=decision.executable.policy_version,
        policy_sha256=policy_sha256,
        authority_envelope_sha256=canonical_sha256(decision),
        permission_snapshot_sha256=terminal.permission_snapshot_sha256,
        route_receipt_sha256=terminal.route_receipt_sha256,
        fail_closed_reason_codes=fail_closed,
        shadow_counterfactual=_decision_summary(decision),
        trusted=terminal.trusted,
        latency_ms=terminal.latency_ms,
        actual_cost_usd=terminal.actual_cost_usd,
    )


async def persist_terminal_production_route_outcome(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    decision: AuthorizedRouteDecision,
    terminal: TerminalProviderRouteEvidence,
) -> ProductionRouteOutcome:
    """Persist an idempotent terminal outcome through the sole API repository."""

    if terminal.selected_model_registry_id is not None:
        registry = await session.scalar(
            select(ModelRegistry).where(ModelRegistry.id == terminal.selected_model_registry_id)
        )
        if registry is None or (
            registry.revision != terminal.selected_model_revision
            or registry.runtime_image_digest != terminal.runtime_image_digest
        ):
            raise ProductionRouteOutcomeBindingError(
                "terminal provider identity differs from the selected model registry"
            )
    spec = build_production_route_outcome_spec(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        decision=decision,
        terminal=terminal,
    )
    return await record_production_route_outcome(session, spec)


__all__ = [
    "ProductionOutcomeStatus",
    "ProductionRouteOutcomeBindingError",
    "TerminalProviderRouteEvidence",
    "build_production_route_outcome_spec",
    "persist_terminal_production_route_outcome",
]
