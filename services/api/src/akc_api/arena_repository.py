"""Sole persistence boundary for Arena research and production route receipts."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.arena_models import (
    ArenaCampaign,
    ArenaCampaignStateEvent,
    ArenaCase,
    ArenaRun,
    ArenaScore,
    ProductionRouteOutcome,
)
from akc_api.models import Collection, ModelRegistry, ProcessingJob, Project

TerminalRunStatus = Literal[
    "SUCCESS", "PROVIDER_ERROR", "TRUNCATED", "INVALID_OUTPUT", "CANCELLED"
]
TerminalCampaignStatus = Literal["FINALIZED", "FAILED", "CANCELLED"]


class ArenaPersistenceError(RuntimeError):
    """Base persistence boundary failure."""


class ArenaConflict(ArenaPersistenceError):
    """An idempotency or immutable identity conflict."""


class ArenaTransitionError(ArenaPersistenceError):
    """A campaign or run transition violated its state machine."""


class ArenaPrivacyBoundaryError(ArenaPersistenceError):
    """Production data attempted to cross into the research namespace."""


@dataclass(frozen=True, slots=True)
class ArenaCaseSpec:
    id: uuid.UUID
    campaign_id: uuid.UUID
    document_family_id: str
    page_or_document_id: str
    split: Literal["CALIBRATION", "EVAL", "ROUTER_TRAIN", "ROUTER_HOLDOUT"]
    origin: str
    slice_labels: tuple[str, ...]
    risk_class: Literal["LOW", "MEDIUM", "HIGH"]
    source_artifact_ref: str
    source_artifact_sha256: str
    truth_ref: str | None
    license_ref: str


@dataclass(frozen=True, slots=True)
class ArenaRunSpec:
    id: uuid.UUID
    campaign_id: uuid.UUID
    case_id: uuid.UUID
    model_registry_id: uuid.UUID
    idempotency_key: str
    exact_model_id: str
    exact_model_revision: str
    input_track: Literal["STANDARD_IMAGE", "NATIVE_PROVIDER", "NATIVE_LOCAL"]
    prompt_track: Literal["STANDARD", "PROVIDER_OPTIMIZED"]
    batch_mode: bool
    prompt_sha256: str
    schema_sha256: str
    settings_sha256: str
    input_artifact_ref: str
    input_artifact_sha256: str
    price_snapshot_ref: str
    price_snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class ArenaRunOutcome:
    status: TerminalRunStatus
    latency_ms: int
    input_units: dict[str, Any]
    output_units: dict[str, Any]
    actual_cost_usd: Decimal
    terminal_receipt_sha256: str
    raw_output_artifact_ref: str | None = None
    raw_output_sha256: str | None = None
    normalized_output_artifact_ref: str | None = None
    normalized_output_sha256: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ArenaScoreSpec:
    evaluator_id: str
    evaluator_revision: str
    metric_name: str
    evaluator_artifact_ref: str
    evaluator_artifact_sha256: str
    receipt_ref: str
    receipt_sha256: str
    value: float | None = None
    severity: Literal["INFO", "WARNING", "CRITICAL"] | None = None


@dataclass(frozen=True, slots=True)
class ProductionRouteOutcomeSpec:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    collection_id: uuid.UUID
    processing_job_id: uuid.UUID
    shard_id: str
    idempotency_key: str
    requested_mode: str
    effective_mode: str
    decision_kind: Literal["DETERMINISTIC", "ADAPTIVE"]
    executable: bool
    outcome_status: Literal["EXECUTED", "FAILED", "ABSTAINED", "SHADOW_ONLY"]
    selected_path: str | None
    selected_model_registry_id: uuid.UUID | None
    policy_version: str
    policy_sha256: str
    authority_envelope_sha256: str
    permission_snapshot_sha256: str
    route_receipt_sha256: str
    fail_closed_reason_codes: tuple[str, ...]
    shadow_counterfactual: dict[str, Any] | None
    trusted: bool | None
    latency_ms: int | None
    actual_cost_usd: Decimal | None


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ArenaConflict(f"{field} must be a lowercase sha256")


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise ArenaConflict(f"{field} is required")


def _same(row: object, expected: Mapping[str, object]) -> bool:
    return all(getattr(row, key) == value for key, value in expected.items())


async def _append_campaign_event(
    session: AsyncSession,
    campaign: ArenaCampaign,
    *,
    from_status: str | None,
    to_status: str,
    receipt_sha256: str,
) -> None:
    _require_sha256(receipt_sha256, "transition_receipt_sha256")
    sequence = await session.scalar(
        select(func.coalesce(func.max(ArenaCampaignStateEvent.sequence), -1)).where(
            ArenaCampaignStateEvent.campaign_id == campaign.id
        )
    )
    session.add(
        ArenaCampaignStateEvent(
            campaign_id=campaign.id,
            sequence=int(sequence or 0) + 1 if sequence != -1 else 0,
            from_status=from_status,
            to_status=to_status,
            transition_receipt_sha256=receipt_sha256,
        )
    )


async def create_campaign(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    name: str,
    corpus_manifest_sha256: str,
    protocol_version: str,
    protocol_sha256: str,
) -> ArenaCampaign:
    """Create or replay one immutable campaign identity in DRAFT."""

    _require_text(name, "name")
    _require_text(protocol_version, "protocol_version")
    _require_sha256(corpus_manifest_sha256, "corpus_manifest_sha256")
    _require_sha256(protocol_sha256, "protocol_sha256")
    identity = {
        "name": name,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "protocol_version": protocol_version,
        "protocol_sha256": protocol_sha256,
    }
    existing = await session.get(ArenaCampaign, campaign_id)
    if existing is not None:
        if not _same(existing, identity):
            raise ArenaConflict("campaign id was reused for a different immutable identity")
        return existing
    campaign = ArenaCampaign(id=campaign_id, **identity)
    session.add(campaign)
    await session.flush()
    await _append_campaign_event(
        session,
        campaign,
        from_status=None,
        to_status="DRAFT",
        receipt_sha256=_canonical_sha256({"campaign_id": campaign_id, **identity}),
    )
    await session.flush()
    return campaign


def _case_identity(spec: ArenaCaseSpec) -> dict[str, object]:
    labels = sorted(set(spec.slice_labels))
    return {
        "campaign_id": spec.campaign_id,
        "document_family_id": spec.document_family_id,
        "page_or_document_id": spec.page_or_document_id,
        "split": spec.split,
        "origin": spec.origin,
        "slice_labels": labels,
        "risk_class": spec.risk_class,
        "source_artifact_ref": spec.source_artifact_ref,
        "source_artifact_sha256": spec.source_artifact_sha256,
        "truth_ref": spec.truth_ref,
        "license_ref": spec.license_ref,
    }


async def add_case(session: AsyncSession, spec: ArenaCaseSpec) -> ArenaCase:
    """Add a case only while the campaign manifest is still mutable."""

    _require_sha256(spec.source_artifact_sha256, "source_artifact_sha256")
    for field in (
        "document_family_id",
        "page_or_document_id",
        "origin",
        "source_artifact_ref",
        "license_ref",
    ):
        _require_text(str(getattr(spec, field)), field)
    identity = _case_identity(spec)
    manifest_sha = _canonical_sha256(identity)
    existing = await session.get(ArenaCase, spec.id)
    if existing is not None:
        expected = {**identity, "case_manifest_sha256": manifest_sha}
        if not _same(existing, expected):
            raise ArenaConflict("case id was reused for a different immutable identity")
        return existing
    campaign = await session.get(ArenaCampaign, spec.campaign_id, with_for_update=True)
    if campaign is None:
        raise ArenaConflict("campaign does not exist")
    if campaign.status != "DRAFT":
        raise ArenaTransitionError("campaign cases are immutable after freeze")
    case = ArenaCase(id=spec.id, **identity, case_manifest_sha256=manifest_sha)
    session.add(case)
    await session.flush()
    return case


async def freeze_campaign(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    expected_manifest_sha256: str,
    transition_receipt_sha256: str,
) -> ArenaCampaign:
    """Freeze the manifest after enforcing calibration/evaluation family isolation."""

    _require_sha256(expected_manifest_sha256, "expected_manifest_sha256")
    campaign = await session.get(ArenaCampaign, campaign_id, with_for_update=True)
    if campaign is None:
        raise ArenaConflict("campaign does not exist")
    if campaign.corpus_manifest_sha256 != expected_manifest_sha256:
        raise ArenaConflict("campaign manifest hash changed before freeze")
    if campaign.status == "FROZEN":
        return campaign
    if campaign.status != "DRAFT":
        raise ArenaTransitionError(f"cannot freeze campaign from {campaign.status}")
    cases = list(
        (
            await session.scalars(
                select(ArenaCase).where(ArenaCase.campaign_id == campaign_id)
            )
        ).all()
    )
    if not cases:
        raise ArenaTransitionError("cannot freeze an empty campaign")
    calibration = {case.document_family_id for case in cases if case.split == "CALIBRATION"}
    held_out = {
        case.document_family_id
        for case in cases
        if case.split in {"EVAL", "ROUTER_HOLDOUT"}
    }
    overlap = sorted(calibration & held_out)
    if overlap:
        raise ArenaConflict(f"calibration and held-out document families overlap: {overlap}")
    campaign.status = "FROZEN"
    campaign.frozen_at = _now()
    await _append_campaign_event(
        session,
        campaign,
        from_status="DRAFT",
        to_status="FROZEN",
        receipt_sha256=transition_receipt_sha256,
    )
    await session.flush()
    return campaign


async def start_campaign(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    transition_receipt_sha256: str,
) -> ArenaCampaign:
    campaign = await session.get(ArenaCampaign, campaign_id, with_for_update=True)
    if campaign is None:
        raise ArenaConflict("campaign does not exist")
    if campaign.status == "RUNNING":
        return campaign
    if campaign.status != "FROZEN":
        raise ArenaTransitionError(f"cannot start campaign from {campaign.status}")
    campaign.status = "RUNNING"
    campaign.started_at = _now()
    await _append_campaign_event(
        session,
        campaign,
        from_status="FROZEN",
        to_status="RUNNING",
        receipt_sha256=transition_receipt_sha256,
    )
    await session.flush()
    return campaign


def _run_identity(spec: ArenaRunSpec) -> dict[str, object]:
    return asdict(spec)


async def start_run(session: AsyncSession, spec: ArenaRunSpec) -> ArenaRun:
    """Persist one exactly pinned run, idempotent within its campaign."""

    for field in (
        "prompt_sha256",
        "schema_sha256",
        "settings_sha256",
        "input_artifact_sha256",
        "price_snapshot_sha256",
    ):
        _require_sha256(str(getattr(spec, field)), field)
    identity = _run_identity(spec)
    replay = await session.scalar(
        select(ArenaRun).where(
            ArenaRun.campaign_id == spec.campaign_id,
            ArenaRun.idempotency_key == spec.idempotency_key,
        )
    )
    if replay is not None:
        if not _same(replay, identity):
            raise ArenaConflict("run idempotency key was reused for a different identity")
        return replay
    existing_id = await session.get(ArenaRun, spec.id)
    if existing_id is not None:
        raise ArenaConflict("run id was reused with a different idempotency key")
    campaign = await session.get(ArenaCampaign, spec.campaign_id)
    if campaign is None or campaign.status not in {"FROZEN", "RUNNING"}:
        raise ArenaTransitionError("runs require a frozen or running campaign")
    case = await session.get(ArenaCase, spec.case_id)
    if case is None or case.campaign_id != spec.campaign_id:
        raise ArenaConflict("run case is not part of the campaign")
    registry = await session.get(ModelRegistry, spec.model_registry_id)
    if registry is None:
        raise ArenaConflict("model registry entry does not exist")
    if registry.model_id != spec.exact_model_id or registry.revision != spec.exact_model_revision:
        raise ArenaConflict("exact model identity does not match the registry snapshot")
    run = ArenaRun(**identity)
    session.add(run)
    await session.flush()
    return run


def _outcome_values(outcome: ArenaRunOutcome) -> dict[str, object]:
    return {
        "status": outcome.status,
        "latency_ms": outcome.latency_ms,
        "input_units": outcome.input_units,
        "output_units": outcome.output_units,
        "actual_cost_usd": outcome.actual_cost_usd,
        "terminal_receipt_sha256": outcome.terminal_receipt_sha256,
        "raw_output_artifact_ref": outcome.raw_output_artifact_ref,
        "raw_output_sha256": outcome.raw_output_sha256,
        "normalized_output_artifact_ref": outcome.normalized_output_artifact_ref,
        "normalized_output_sha256": outcome.normalized_output_sha256,
        "error_code": outcome.error_code,
    }


async def complete_run(
    session: AsyncSession, *, run_id: uuid.UUID, outcome: ArenaRunOutcome
) -> ArenaRun:
    """Write the complete terminal outcome once; exact replays are harmless."""

    _require_sha256(outcome.terminal_receipt_sha256, "terminal_receipt_sha256")
    if outcome.latency_ms < 0 or outcome.actual_cost_usd < 0:
        raise ArenaConflict("latency and actual cost must be non-negative")
    if outcome.status == "SUCCESS":
        required = (
            outcome.raw_output_artifact_ref,
            outcome.raw_output_sha256,
            outcome.normalized_output_artifact_ref,
            outcome.normalized_output_sha256,
        )
        if any(value is None for value in required) or outcome.error_code is not None:
            raise ArenaConflict("successful runs require raw and normalized artifacts")
    elif not outcome.error_code:
        raise ArenaConflict("non-success outcomes require an error_code")
    for field in ("raw_output_sha256", "normalized_output_sha256"):
        value = getattr(outcome, field)
        if value is not None:
            _require_sha256(value, field)
    run = await session.get(ArenaRun, run_id, with_for_update=True)
    if run is None:
        raise ArenaConflict("run does not exist")
    values = _outcome_values(outcome)
    if run.status != "RUNNING":
        if not _same(run, values):
            raise ArenaConflict("terminal run outcome is immutable")
        return run
    for key, value in values.items():
        setattr(run, key, value)
    run.completed_at = _now()
    await session.flush()
    return run


async def record_score(
    session: AsyncSession, *, run_id: uuid.UUID, score: ArenaScoreSpec
) -> ArenaScore:
    """Append an evaluator receipt only after the run is terminal."""

    _require_sha256(score.evaluator_artifact_sha256, "evaluator_artifact_sha256")
    _require_sha256(score.receipt_sha256, "receipt_sha256")
    if score.value is None and score.severity is None:
        raise ArenaConflict("score requires a value or severity")
    run = await session.get(ArenaRun, run_id)
    if run is None or run.status == "RUNNING":
        raise ArenaTransitionError("scores require a terminal run")
    key = (run_id, score.evaluator_id, score.evaluator_revision, score.metric_name)
    values = asdict(score)
    existing = await session.get(ArenaScore, key)
    if existing is not None:
        if not _same(existing, values):
            raise ArenaConflict("evaluator metric identity is append-only")
        return existing
    row = ArenaScore(run_id=run_id, **values)
    session.add(row)
    await session.flush()
    return row


async def finish_campaign(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    status: TerminalCampaignStatus,
    terminal_receipt_sha256: str,
) -> ArenaCampaign:
    """Seal a campaign only after every started run has a complete outcome."""

    _require_sha256(terminal_receipt_sha256, "terminal_receipt_sha256")
    campaign = await session.get(ArenaCampaign, campaign_id, with_for_update=True)
    if campaign is None:
        raise ArenaConflict("campaign does not exist")
    if campaign.status in {"FINALIZED", "FAILED", "CANCELLED"}:
        if (
            campaign.status != status
            or campaign.terminal_receipt_sha256 != terminal_receipt_sha256
        ):
            raise ArenaConflict("terminal campaign outcome is immutable")
        return campaign
    if campaign.status != "RUNNING":
        raise ArenaTransitionError(f"cannot finish campaign from {campaign.status}")
    count_rows = (
        await session.execute(
            select(ArenaRun.status, func.count(ArenaRun.id))
            .where(ArenaRun.campaign_id == campaign_id)
            .group_by(ArenaRun.status)
        )
    ).all()
    counts: dict[str, int] = {row[0]: row[1] for row in count_rows}
    if not counts:
        raise ArenaTransitionError("cannot finish a campaign with no runs")
    if counts.get("RUNNING", 0):
        raise ArenaTransitionError("cannot finish while runs are incomplete")
    campaign.status = status
    campaign.finalized_at = _now()
    campaign.terminal_receipt_sha256 = terminal_receipt_sha256
    campaign.outcome_counts = {str(key): int(value) for key, value in sorted(counts.items())}
    await _append_campaign_event(
        session,
        campaign,
        from_status="RUNNING",
        to_status=status,
        receipt_sha256=terminal_receipt_sha256,
    )
    await session.flush()
    return campaign


def _production_values(spec: ProductionRouteOutcomeSpec) -> dict[str, object]:
    values = asdict(spec)
    values["fail_closed_reason_codes"] = list(spec.fail_closed_reason_codes)
    return values


async def record_production_route_outcome(
    session: AsyncSession, spec: ProductionRouteOutcomeSpec
) -> ProductionRouteOutcome:
    """Store a permissioned route result without creating research eligibility.

    ``workspace_id`` binds to the existing tenant-scoped ``projects`` table.
    No source/customer artifact reference is accepted by this API.
    """

    for field in (
        "policy_sha256",
        "authority_envelope_sha256",
        "permission_snapshot_sha256",
        "route_receipt_sha256",
    ):
        _require_sha256(str(getattr(spec, field)), field)
    _require_text(spec.shard_id, "shard_id")
    if spec.outcome_status == "EXECUTED" and (
        not spec.executable
        or not spec.selected_path
        or spec.trusted is None
        or spec.latency_ms is None
        or spec.actual_cost_usd is None
    ):
        raise ArenaConflict("executed route outcomes require complete result accounting")
    if spec.outcome_status in {"FAILED", "ABSTAINED"} and not spec.fail_closed_reason_codes:
        raise ArenaConflict("failed or abstained routes require fail-closed reason codes")
    if spec.latency_ms is not None and spec.latency_ms < 0:
        raise ArenaConflict("latency must be non-negative")
    if spec.actual_cost_usd is not None and spec.actual_cost_usd < 0:
        raise ArenaConflict("actual cost must be non-negative")
    project = await session.scalar(
        select(Project.id).where(
            Project.tenant_id == spec.tenant_id,
            Project.id == spec.workspace_id,
        )
    )
    if project is None:
        raise ArenaPrivacyBoundaryError("workspace is outside the permissioned tenant")
    collection = await session.scalar(
        select(Collection).where(
            Collection.tenant_id == spec.tenant_id,
            Collection.id == spec.collection_id,
            Collection.project_id == spec.workspace_id,
            Collection.status != "PURGED",
        )
    )
    if collection is None:
        raise ArenaPrivacyBoundaryError("collection is outside the permissioned workspace")
    processing_job = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.tenant_id == spec.tenant_id,
            ProcessingJob.id == spec.processing_job_id,
            ProcessingJob.project_id == spec.workspace_id,
        )
    )
    if processing_job is None or str(
        processing_job.requested_options.get("collection_id", "")
    ) != str(spec.collection_id):
        raise ArenaPrivacyBoundaryError("processing job is not bound to the collection")
    values = _production_values(spec)
    replay = await session.scalar(
        select(ProductionRouteOutcome).where(
            ProductionRouteOutcome.tenant_id == spec.tenant_id,
            ProductionRouteOutcome.workspace_id == spec.workspace_id,
            ProductionRouteOutcome.idempotency_key == spec.idempotency_key,
        )
    )
    if replay is not None:
        if not _same(replay, values):
            raise ArenaConflict("production outcome idempotency key was reused")
        return replay
    if await session.get(ProductionRouteOutcome, spec.id) is not None:
        raise ArenaConflict("production outcome id was reused")
    row = ProductionRouteOutcome(**values, research_use_allowed=False)
    session.add(row)
    await session.flush()
    return row


__all__ = [
    "ArenaCaseSpec",
    "ArenaConflict",
    "ArenaPersistenceError",
    "ArenaPrivacyBoundaryError",
    "ArenaRunOutcome",
    "ArenaRunSpec",
    "ArenaScoreSpec",
    "ArenaTransitionError",
    "ProductionRouteOutcomeSpec",
    "add_case",
    "complete_run",
    "create_campaign",
    "finish_campaign",
    "freeze_campaign",
    "record_production_route_outcome",
    "record_score",
    "start_campaign",
    "start_run",
]
