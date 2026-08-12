"""Region-scoped recovery attempts and stale-output promotion fences."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Literal

from akc_quality import AgentFinding, RecoveryStage
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    Block,
    CollectionRegion,
    CollectionRegionAttempt,
    PageAttempt,
    VerificationRecord,
    utcnow,
)

RegionAttemptStatus = Literal[
    "verified",
    "authority_verified",
    "auto_repaired",
    "verified_with_warning",
    "unresolved",
    "quarantined",
    "rejected",
    "failed",
]
_PROMOTABLE = frozenset(
    {"verified", "authority_verified", "auto_repaired", "verified_with_warning"}
)
_REGION_STATUS = {
    "verified": "verified",
    "authority_verified": "verified",
    "auto_repaired": "auto_repaired",
    "verified_with_warning": "verified_with_warning",
    "unresolved": "unresolved",
    "quarantined": "quarantined",
    "rejected": "rejected",
    "failed": "unresolved",
}


class RegionPromotionError(ValueError):
    """A recovery output is stale, unscoped, or lacks verifiable evidence."""


class RegionOutputCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: uuid.UUID
    route: Annotated[str, Field(min_length=1, max_length=80)]
    status: RegionAttemptStatus
    source_block_id: uuid.UUID
    source_block_content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_page_attempt_id: uuid.UUID
    output_text: Annotated[str | None, Field(default=None, max_length=1_000_000)]
    output_sha256: Annotated[str | None, Field(default=None, pattern=r"^[0-9a-f]{64}$")]
    recovery_stage: RecoveryStage
    independent_signal_count: Annotated[int, Field(ge=0, le=16)]
    findings: Annotated[tuple[AgentFinding, ...], Field(max_length=64)] = ()
    reason_codes: Annotated[tuple[str, ...], Field(max_length=64)] = ()
    parser_revision: Annotated[str, Field(min_length=1, max_length=200)]
    model_revision: Annotated[str, Field(min_length=1, max_length=200)]
    provider_revision: Annotated[str, Field(min_length=1, max_length=200)]
    attestation_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_output_and_route(self) -> RegionOutputCandidate:
        if self.route == "manual_review":
            raise ValueError("manual review is not a region recovery route")
        if self.status in _PROMOTABLE:
            if not self.output_text or not self.output_text.strip() or self.output_sha256 is None:
                raise ValueError("promotable region output requires text and digest")
            actual = hashlib.sha256(self.output_text.encode("utf-8")).hexdigest()
            if actual != self.output_sha256:
                raise ValueError("region output digest mismatch")
            if self.independent_signal_count < 2:
                raise ValueError("promotable region output requires two independent signals")
        elif self.output_text is not None or self.output_sha256 is not None:
            raise ValueError("non-promotable region attempt cannot publish output")
        return self


def _summary(candidate: RegionOutputCandidate) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "promotion_fence": "source-page-attempt-and-block-hash-v1",
        "source_block_id": str(candidate.source_block_id),
        "source_block_content_hash": candidate.source_block_content_hash,
        "source_page_attempt_id": str(candidate.source_page_attempt_id),
        "output_text": candidate.output_text,
        "output_sha256": candidate.output_sha256,
        "recovery_stage": candidate.recovery_stage.value,
        "independent_signal_count": candidate.independent_signal_count,
        "findings": [finding.model_dump(mode="json") for finding in candidate.findings],
        "reason_codes": list(candidate.reason_codes),
        "parser_revision": candidate.parser_revision,
        "model_revision": candidate.model_revision,
        "provider_revision": candidate.provider_revision,
        "attestation_sha256": candidate.attestation_sha256,
    }


async def record_region_output_attempt(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    region_id: uuid.UUID,
    candidate: RegionOutputCandidate,
) -> CollectionRegionAttempt:
    """Append one terminal attempt and promote only against its exact source base."""

    expected_summary = _summary(candidate)
    existing = await session.scalar(
        select(CollectionRegionAttempt).where(
            CollectionRegionAttempt.tenant_id == tenant_id,
            CollectionRegionAttempt.collection_id == collection_id,
            CollectionRegionAttempt.id == candidate.attempt_id,
        )
    )
    if existing is not None:
        if (
            existing.region_id != region_id
            or existing.route != candidate.route
            or existing.status != candidate.status
            or existing.validator_summary != expected_summary
        ):
            raise RegionPromotionError("region attempt id was reused with different evidence")
        return existing

    region = await session.scalar(
        select(CollectionRegion)
        .where(
            CollectionRegion.tenant_id == tenant_id,
            CollectionRegion.collection_id == collection_id,
            CollectionRegion.id == region_id,
        )
        .with_for_update()
    )
    if region is None or region.page_id is None or region.document_id is None:
        raise RegionPromotionError("region scope or page provenance is missing")
    if region.stable_key != f"block:{candidate.source_block_id}":
        raise RegionPromotionError("region is not bound to the candidate source block")
    block = await session.scalar(
        select(Block).where(
            Block.tenant_id == tenant_id,
            Block.id == candidate.source_block_id,
            Block.document_id == region.document_id,
            Block.page_id == region.page_id,
        )
    )
    if block is None or block.content_hash != candidate.source_block_content_hash:
        raise RegionPromotionError("source block changed before region promotion")
    if block.user_locked:
        raise RegionPromotionError("user-locked block cannot receive autonomous region output")
    source_attempt = await session.scalar(
        select(PageAttempt).where(
            PageAttempt.tenant_id == tenant_id,
            PageAttempt.id == candidate.source_page_attempt_id,
            PageAttempt.page_id == region.page_id,
        )
    )
    latest_page_attempt_number = await session.scalar(
        select(func.max(PageAttempt.attempt_number)).where(
            PageAttempt.tenant_id == tenant_id,
            PageAttempt.page_id == region.page_id,
        )
    )
    if (
        source_attempt is None
        or source_attempt.status not in {"COMPLETED", "UNRESOLVED", "QUARANTINED"}
        or source_attempt.attempt_number != latest_page_attempt_number
    ):
        raise RegionPromotionError("source page attempt is stale or non-terminal")
    latest_region_attempt_number = int(
        await session.scalar(
            select(func.max(CollectionRegionAttempt.attempt_number)).where(
                CollectionRegionAttempt.tenant_id == tenant_id,
                CollectionRegionAttempt.collection_id == collection_id,
                CollectionRegionAttempt.region_id == region_id,
            )
        )
        or 0
    )
    attempt = CollectionRegionAttempt(
        id=candidate.attempt_id,
        tenant_id=tenant_id,
        collection_id=collection_id,
        region_id=region_id,
        attempt_number=latest_region_attempt_number + 1,
        route=candidate.route,
        status=candidate.status,
        validator_summary=expected_summary,
        completed_at=utcnow(),
    )
    session.add(attempt)
    region.status = _REGION_STATUS[candidate.status]
    await session.flush()
    verification_status = (
        candidate.status
        if candidate.status != "failed"
        else "unresolved"
    )
    session.add(
        VerificationRecord(
            tenant_id=tenant_id,
            collection_id=collection_id,
            region_id=region_id,
            status=verification_status,
            validator_revision="region-promotion-fence-v1",
            evidence={
                "region_attempt_id": str(attempt.id),
                "attempt_number": attempt.attempt_number,
                "promotion_fence": expected_summary["promotion_fence"],
                "source_page_attempt_id": str(candidate.source_page_attempt_id),
                "source_block_id": str(candidate.source_block_id),
                "source_block_content_hash": candidate.source_block_content_hash,
                "output_sha256": candidate.output_sha256,
                "attestation_sha256": candidate.attestation_sha256,
            },
        )
    )
    await session.flush()
    return attempt


def promoted_region_text_by_block(
    regions: Iterable[CollectionRegion],
    attempts: Iterable[CollectionRegionAttempt],
    *,
    blocks: Iterable[Block] | None = None,
    latest_page_attempts: Mapping[uuid.UUID, PageAttempt] | None = None,
) -> dict[uuid.UUID, str]:
    """Project only the latest fenced, promotable output for each source block.

    Semantic/final projections must pass ``blocks`` and ``latest_page_attempts``.
    The optional form is retained for read-only compatibility callers that only
    inspect an already persisted attempt; it does not re-prove current source
    freshness.
    """

    if (blocks is None) != (latest_page_attempts is None):
        raise ValueError("strict region projection requires blocks and page attempts together")

    region_by_id = {region.id: region for region in regions}
    block_by_id = {block.id: block for block in blocks} if blocks is not None else None
    latest: dict[uuid.UUID, CollectionRegionAttempt] = {}
    for attempt in attempts:
        current = latest.get(attempt.region_id)
        if current is None or attempt.attempt_number > current.attempt_number:
            latest[attempt.region_id] = attempt
    outputs: dict[uuid.UUID, str] = {}
    for region_id, attempt in latest.items():
        region = region_by_id.get(region_id)
        if region is None or attempt.status not in _PROMOTABLE:
            continue
        summary = attempt.validator_summary
        if summary.get("promotion_fence") != "source-page-attempt-and-block-hash-v1":
            continue
        try:
            block_id = uuid.UUID(str(summary["source_block_id"]))
        except (KeyError, ValueError):
            continue
        if region.stable_key != f"block:{block_id}":
            continue
        if block_by_id is not None and latest_page_attempts is not None:
            block = block_by_id.get(block_id)
            if (
                block is None
                or block.user_locked
                or block.page_id is None
                or block.page_id != region.page_id
                or block.document_id != region.document_id
                or summary.get("source_block_content_hash") != block.content_hash
            ):
                continue
            latest_page_attempt = latest_page_attempts.get(block.page_id)
            if (
                latest_page_attempt is None
                or summary.get("source_page_attempt_id") != str(latest_page_attempt.id)
            ):
                continue
        text = summary.get("output_text")
        digest = summary.get("output_sha256")
        if (
            not isinstance(text, str)
            or not text.strip()
            or digest != hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            continue
        outputs[block_id] = text
    return outputs


__all__ = [
    "RegionOutputCandidate",
    "RegionPromotionError",
    "promoted_region_text_by_block",
    "record_region_output_attempt",
]
