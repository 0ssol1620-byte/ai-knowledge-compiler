"""Authenticated read-side for persisted production routing receipts."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.arena_models import ProductionRouteOutcome
from akc_api.database import get_session
from akc_api.models import Collection, ProcessingJob
from akc_api.project_access import require_project_access
from akc_api.security import Principal, get_principal

router = APIRouter(prefix="/v1", tags=["route-outcomes"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductionRouteOutcomeResponse(_WireModel):
    """Sanitized workspace receipt; internal estimates and prompts never cross this DTO."""

    outcome_id: uuid.UUID
    collection_id: uuid.UUID
    processing_job_id: uuid.UUID
    shard_id: Annotated[str, Field(min_length=1, max_length=200)]
    requested_mode: Annotated[str, Field(min_length=1, max_length=32)]
    effective_mode: Annotated[str, Field(min_length=1, max_length=32)]
    decision_kind: Literal["DETERMINISTIC", "ADAPTIVE"]
    executable: bool
    outcome_status: Literal["EXECUTED", "FAILED", "ABSTAINED", "SHADOW_ONLY"]
    selected_path: Annotated[str, Field(min_length=1, max_length=160)] | None
    policy_version: Annotated[str, Field(min_length=1, max_length=120)]
    policy_sha256: Sha256
    authority_envelope_sha256: Sha256
    permission_snapshot_sha256: Sha256
    route_receipt_sha256: Sha256
    fail_closed_reason_codes: tuple[Annotated[str, Field(min_length=1, max_length=120)], ...]
    trusted: bool | None
    latency_ms: Annotated[int, Field(ge=0)] | None
    actual_cost_usd: Annotated[Decimal, Field(ge=0)] | None
    created_at: datetime


def _unavailable(code: str) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": code})


def _valid_outcome(row: ProductionRouteOutcome) -> bool:
    digests = (
        row.policy_sha256,
        row.authority_envelope_sha256,
        row.permission_snapshot_sha256,
        row.route_receipt_sha256,
    )
    if row.research_use_allowed or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in digests
    ):
        return False
    reasons = row.fail_closed_reason_codes
    if (
        not isinstance(row.shard_id, str)
        or not row.shard_id.strip()
        or not isinstance(reasons, list)
        or any(not isinstance(code, str) or not code.strip() for code in reasons)
    ):
        return False
    if row.outcome_status == "EXECUTED":
        return bool(
            row.executable
            and row.selected_path
            and row.trusted is not None
            and row.latency_ms is not None
            and row.actual_cost_usd is not None
        )
    if row.outcome_status == "FAILED":
        return row.executable and bool(row.fail_closed_reason_codes)
    if row.outcome_status == "ABSTAINED":
        return not row.executable and bool(row.fail_closed_reason_codes)
    return row.outcome_status == "SHADOW_ONLY" and not row.executable


@router.get(
    "/collections/{collection_id}/route-outcomes/latest",
    response_model=ProductionRouteOutcomeResponse,
)
async def latest_production_route_outcome(
    collection_id: uuid.UUID,
    processing_job_id: Annotated[uuid.UUID, Query()],
    principal: PrincipalDep,
    session: SessionDep,
) -> ProductionRouteOutcomeResponse:
    """Return the latest real shard outcome for one authorized collection job."""

    try:
        collection = await session.scalar(
            select(Collection).where(
                Collection.tenant_id == principal.tenant_id,
                Collection.id == collection_id,
                Collection.status != "PURGED",
            )
        )
    except SQLAlchemyError as exc:
        raise _unavailable("ROUTE_OUTCOME_STORE_UNAVAILABLE") from exc
    if collection is None:
        raise HTTPException(status_code=404, detail={"code": "ROUTE_OUTCOME_NOT_FOUND"})
    try:
        await require_project_access(
            session,
            principal=principal,
            project_id=collection.project_id,
            capability="read",
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise _unavailable("ROUTE_OUTCOME_STORE_UNAVAILABLE") from exc
    try:
        processing_job = await session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == principal.tenant_id,
                ProcessingJob.id == processing_job_id,
                ProcessingJob.project_id == collection.project_id,
            )
        )
        if processing_job is None or str(
            processing_job.requested_options.get("collection_id", "")
        ) != str(collection.id):
            raise HTTPException(status_code=404, detail={"code": "ROUTE_OUTCOME_NOT_FOUND"})
        outcome = await session.scalar(
            select(ProductionRouteOutcome)
            .where(
                ProductionRouteOutcome.tenant_id == principal.tenant_id,
                ProductionRouteOutcome.workspace_id == collection.project_id,
                ProductionRouteOutcome.collection_id == collection.id,
                ProductionRouteOutcome.processing_job_id == processing_job.id,
            )
            .order_by(ProductionRouteOutcome.created_at.desc(), ProductionRouteOutcome.id.desc())
            .limit(1)
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise _unavailable("ROUTE_OUTCOME_STORE_UNAVAILABLE") from exc
    if outcome is None:
        raise HTTPException(status_code=404, detail={"code": "ROUTE_OUTCOME_NOT_FOUND"})
    if not _valid_outcome(outcome):
        raise _unavailable("ROUTE_OUTCOME_INTEGRITY_UNAVAILABLE")
    try:
        return ProductionRouteOutcomeResponse(
            outcome_id=outcome.id,
            collection_id=outcome.collection_id,
            processing_job_id=outcome.processing_job_id,
            shard_id=outcome.shard_id,
            requested_mode=outcome.requested_mode,
            effective_mode=outcome.effective_mode,
            decision_kind=outcome.decision_kind,
            executable=outcome.executable,
            outcome_status=outcome.outcome_status,
            selected_path=outcome.selected_path,
            policy_version=outcome.policy_version,
            policy_sha256=outcome.policy_sha256,
            authority_envelope_sha256=outcome.authority_envelope_sha256,
            permission_snapshot_sha256=outcome.permission_snapshot_sha256,
            route_receipt_sha256=outcome.route_receipt_sha256,
            fail_closed_reason_codes=tuple(outcome.fail_closed_reason_codes),
            trusted=outcome.trusted,
            latency_ms=outcome.latency_ms,
            actual_cost_usd=outcome.actual_cost_usd,
            created_at=outcome.created_at,
        )
    except ValidationError as exc:
        raise _unavailable("ROUTE_OUTCOME_INTEGRITY_UNAVAILABLE") from exc


__all__ = ["ProductionRouteOutcomeResponse", "latest_production_route_outcome", "router"]
