"""Deterministic tenant feature-flag resolution."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import FeatureFlag

ONTOLOGY_EXPORT_FLAG = "ontology_export"
EXISTING_VAULT_MERGE_FLAG = "existing_vault_merge"
CHART_DESCRIPTION_FLAG = "chart_description"


def cohort_enabled(
    *,
    tenant_id: uuid.UUID,
    key: str,
    enabled: bool,
    percent: int,
    subject_id: uuid.UUID | None = None,
) -> bool:
    if not enabled:
        return False
    # 0 means nobody, not everybody. It is the first rung of the v4 rollout
    # ladder 0 -> 5 -> 25 -> 50 -> 100, where a flag is created switched on so
    # its row exists and its cohort is empty until it is deliberately widened.
    # Folding 0 in with 100 made that rung open the gate to the whole tenant.
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    rollout_subject = subject_id or tenant_id
    bucket = (
        int.from_bytes(
            hashlib.sha256(f"{tenant_id}:{rollout_subject}:{key}".encode()).digest()[:4],
            "big",
        )
        % 100
    )
    return bucket < percent


def conditions_match(
    conditions: Mapping[str, Any],
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    document_type: str | None = None,
) -> bool:
    """Evaluate the bounded rollout-condition vocabulary, failing closed."""

    if not conditions:
        return True
    allowed = {"tenant_ids", "user_ids", "document_types"}
    if set(conditions) - allowed:
        return False

    def matches_uuid_list(name: str, value: uuid.UUID | None) -> bool:
        configured = conditions.get(name)
        if configured is None:
            return True
        if (
            not isinstance(configured, Sequence)
            or isinstance(configured, (str, bytes, bytearray))
            or not configured
            or value is None
        ):
            return False
        normalized: set[uuid.UUID] = set()
        try:
            for item in configured:
                normalized.add(uuid.UUID(str(item)))
        except (TypeError, ValueError, AttributeError):
            return False
        return value in normalized

    if not matches_uuid_list("tenant_ids", tenant_id):
        return False
    if not matches_uuid_list("user_ids", user_id):
        return False

    configured_document_types = conditions.get("document_types")
    if configured_document_types is not None:
        if (
            not isinstance(configured_document_types, Sequence)
            or isinstance(configured_document_types, (str, bytes, bytearray))
            or not configured_document_types
            or document_type is None
            or any(
                not isinstance(item, str) or not item.strip() for item in configured_document_types
            )
        ):
            return False
        normalized_document_types = {item.strip().casefold() for item in configured_document_types}
        if document_type.strip().casefold() not in normalized_document_types:
            return False
    return True


async def feature_enabled(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    key: str,
    user_id: uuid.UUID | None = None,
    document_type: str | None = None,
    lock: bool = False,
) -> bool:
    statement = select(FeatureFlag).where(
        FeatureFlag.key == key,
        or_(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.tenant_id.is_(None),
        ),
    )
    if lock:
        statement = statement.with_for_update()
    rows = list((await session.scalars(statement)).all())
    if not rows:
        return False
    # Global defaults are applied first; a tenant row is authoritative.
    rows.sort(
        key=lambda row: (
            row.tenant_id is not None,
            row.updated_at,
            str(row.id),
        )
    )
    effective = False
    for row in rows:
        effective = conditions_match(
            row.conditions if isinstance(row.conditions, dict) else {},
            tenant_id=tenant_id,
            user_id=user_id,
            document_type=document_type,
        ) and cohort_enabled(
            tenant_id=tenant_id,
            subject_id=user_id,
            key=key,
            enabled=row.enabled,
            percent=row.rollout_percent,
        )
    return effective
