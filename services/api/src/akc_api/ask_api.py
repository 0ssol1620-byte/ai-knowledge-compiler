"""POST /v1/ask — the §22.3 answer compiler exposed over HTTP.

An ask is a question compiled against a published world, not a search and not
a chat. The endpoint is deliberately thin wiring around
:func:`akc_cir.answer_compiler.compile_answer`: it authenticates the session,
resolves the ACTIVE world from the local world-state store, hands the query
and the snapshot's claims to the compiler, and returns whatever the compiler
decided — including its refusals.

Two fail-closed properties carry over unchanged from the core:

* **A missing world is a finding, not an error.** No store configured, an
  empty directory, zero ACTIVE snapshots, two of them claiming ACTIVE at once
  — every one of these compiles to ``UNRESOLVED`` with a reason that names
  what was actually found. Nothing here may guess which world is published,
  because serving a stale world as current is the one failure §N22 exists to
  make impossible.
* **A refused answer carries nothing.** When the outcome is NOT_AUTHORIZED
  the response has no claim ids and no evidence occurrences; naming them is
  itself the disclosure §22.1 forbids.

The store format is a directory of JSON snapshots, one per world state::

    <world_store_dir>/ws_20260824_001.json

Each snapshot records its publication manifest hash (recomputed and verified
on read, so a hand-edited artifact hash fails closed), its validation
receipt, and the claims extracted against it. Snapshots are replayed through
the real ``WorldStateRegistry.stage``/``publish`` gates rather than trusted
as data — a snapshot whose receipt did not pass cannot come back as ACTIVE.

Consumption receipts (§21.5) are wired through the :class:`ReceiptSink`
protocol: deployments may inject a recorder on ``app.state.receipt_sink``.
The unconfigured default records nowhere, so asking never depends on lineage
storage being up.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Protocol, cast

from akc_cir import (
    AnswerOutcome,
    AuthorityClass,
    ClaimContext,
    CompiledAnswer,
    DraftClaim,
    PublishRefused,
    QueryIntent,
    ScopedClaim,
    SourceStatus,
    ValidationReceipt,
    WorldStateRegistry,
    WorldStateStatus,
    classify_intent,
    compile_answer,
    publication_manifest,
)
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from akc_api.security import Principal, get_principal
from akc_api.settings import Settings

router = APIRouter(prefix="/v1", tags=["ask"])

PrincipalDep = Annotated[Principal, Depends(get_principal)]

#: The only snapshot schema this module knows how to read. A file written in
#: any other version is unreadable by definition, and an unreadable file in
#: the store fails the whole lookup closed rather than being skipped -- a
#: silently skipped snapshot could be the ACTIVE one.
SNAPSHOT_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Local world-state store
# ---------------------------------------------------------------------------


class SnapshotValidationReceipt(BaseModel):
    """The §N22.3 validation receipt as recorded beside the snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str
    checksums_verified: bool
    permission_checked: bool
    integrity_passed: bool


class SnapshotClaim(BaseModel):
    """One claim extracted inside a world state, plus its evidence pointer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    subject: str
    value: str
    authority: AuthorityClass = AuthorityClass.INFORMAL
    source_status: SourceStatus = SourceStatus.ACTIVE
    scope: dict[str, str] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    recorded_at: datetime | None = None
    required_permission: str | None = None
    evidence_id: str | None = None
    #: Which world the extraction ran against. Required explicitly: defaulting
    #: it to the containing snapshot would hide exactly the mismatch the
    #: freshness auditor exists to catch.
    extracted_world_state_id: str

    @field_validator("authority", mode="before")
    @classmethod
    def _authority_by_name(cls, value: object) -> object:
        if isinstance(value, str) and value in AuthorityClass.__members__:
            return AuthorityClass[value]
        return value

    @field_validator("source_status", mode="before")
    @classmethod
    def _source_status_by_name(cls, value: object) -> object:
        if isinstance(value, str) and value in SourceStatus.__members__:
            return SourceStatus[value]
        return value


class WorldSnapshotDocument(BaseModel):
    """One published world state, serialized for the local store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    workspace_id: str
    world_state_id: str
    status: WorldStateStatus
    compiler_version: str
    built_at: datetime
    activated_at: datetime | None = None
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    manifest_hash: str
    validation_receipt: SnapshotValidationReceipt
    claims: list[SnapshotClaim] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _supported_schema_version(cls, value: int) -> int:
        if value != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported snapshot schema version {value}")
        return value

    def recomputed_manifest(self) -> str:
        """The manifest hash the recorded artifacts actually hash to."""
        return publication_manifest(
            world_state_id=self.world_state_id,
            compiler_version=self.compiler_version,
            artifact_hashes=self.artifact_hashes,
        ).manifest_hash


@dataclass(frozen=True, slots=True)
class WorldResolution:
    """What the store lookup found, or exactly why it refused."""

    snapshot: WorldSnapshotDocument | None
    refusal_reason: str = ""


def _read_snapshot(path: Path) -> WorldSnapshotDocument:
    document = WorldSnapshotDocument.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
    if document.recomputed_manifest() != document.manifest_hash:
        raise ValueError(
            "manifest hash does not match the recorded artifact hashes"
        )
    return document


def _resolve_world(
    store_dir: Path | None,
    requested_world_state_id: str | None,
) -> WorldResolution:
    """Find the answerable world, failing closed on every ambiguous state.

    Any unreadable snapshot poisons the whole lookup: the file that will not
    parse could be the ACTIVE one, and answering from the readable remainder
    is how a stale world gets served as current. Multiple ACTIVE claims get
    the same treatment -- §73.10 allows one ACTIVE per workspace, ever.
    """
    if store_dir is None:
        return WorldResolution(
            None, "the world store directory is not configured"
        )
    if not store_dir.is_dir():
        return WorldResolution(None, "the configured world store directory does not exist")

    snapshots: list[WorldSnapshotDocument] = []
    broken: list[str] = []
    for path in sorted(store_dir.glob("*.json")):
        try:
            snapshots.append(_read_snapshot(path))
        except (OSError, ValueError) as exc:
            broken.append(f"{path.name}: {exc}")
    if broken:
        named = "; ".join(broken[:3])
        return WorldResolution(
            None, f"the world store contains unreadable snapshots ({named})"
        )

    active = [s for s in snapshots if s.status is WorldStateStatus.ACTIVE]
    if len(active) > 1:
        ids = ", ".join(sorted(s.world_state_id for s in active))
        return WorldResolution(
            None,
            f"{len(active)} snapshots claim ACTIVE ({ids}); "
            "refusing to guess which world is published",
        )
    active_id = active[0].world_state_id if active else None

    if requested_world_state_id is not None:
        pinned = next(
            (
                s
                for s in snapshots
                if s.world_state_id == requested_world_state_id
            ),
            None,
        )
        if pinned is None:
            return WorldResolution(
                None,
                f"requested world state {requested_world_state_id} "
                "was not found in the store",
            )
        if pinned.world_state_id != active_id:
            return WorldResolution(
                None,
                f"requested world state {requested_world_state_id} is "
                f"{pinned.status.value}, not the ACTIVE world",
            )
        chosen = pinned
    elif active:
        chosen = active[0]
    else:
        return WorldResolution(None, "no ACTIVE world state is published")
    return WorldResolution(chosen)


def _rebuild_registry(snapshot: WorldSnapshotDocument) -> WorldStateRegistry:
    """Replay a stored snapshot through the real publication gates.

    stage + publish is not ceremony here: publish refuses to produce an
    ACTIVE state unless the recorded receipt passed, so a snapshot with a
    failed or forged receipt cannot be promoted back into existence on read.
    """
    registry = WorldStateRegistry(workspace_id=snapshot.workspace_id)
    registry.stage(
        world_state_id=snapshot.world_state_id,
        compiler_version=snapshot.compiler_version,
        built_at=snapshot.built_at,
    )
    receipt_record = snapshot.validation_receipt
    registry.publish(
        snapshot.world_state_id,
        manifest=publication_manifest(
            world_state_id=snapshot.world_state_id,
            compiler_version=snapshot.compiler_version,
            artifact_hashes=snapshot.artifact_hashes,
        ),
        receipt=ValidationReceipt(
            receipt_id=receipt_record.receipt_id,
            checksums_verified=receipt_record.checksums_verified,
            permission_checked=receipt_record.permission_checked,
            integrity_passed=receipt_record.integrity_passed,
        ),
        artifacts=dict(snapshot.artifact_hashes),
        activated_at=snapshot.activated_at or snapshot.built_at,
    )
    return registry


# ---------------------------------------------------------------------------
# Consumption receipt seam (§21.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AskConsumptionRecord:
    """What was consumed by answering one ask.

    The full ConsumptionReceipt lives elsewhere; this is the ask-side record
    a sink can build on, carrying enough to chain consumed-world lineage
    without leaking claim content into storage the asker never sees.
    """

    query: str
    intent: str
    outcome: str
    claim_ids: tuple[str, ...]
    world_state_id: str
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    answered_at: datetime


class ReceiptSink(Protocol):
    """Where consumption records go. Injected via ``app.state.receipt_sink``."""

    async def record(self, record: AskConsumptionRecord) -> None: ...


class NoopReceiptSink:
    """The unconfigured default: answering must not depend on lineage I/O."""

    async def record(self, record: AskConsumptionRecord) -> None:
        _ = record
        return None


NOOP_RECEIPT_SINK = NoopReceiptSink()


def get_receipt_sink(request: Request) -> ReceiptSink:
    """The app-injected sink, or the no-op when nothing was configured."""
    sink: object | None = getattr(request.app.state, "receipt_sink", None)
    if sink is None:
        return NOOP_RECEIPT_SINK
    return cast(ReceiptSink, sink)


ReceiptSinkDep = Annotated[ReceiptSink, Depends(get_receipt_sink)]


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """Body of POST /v1/ask."""

    query: str = Field(min_length=1, max_length=4000)
    #: Optional pin. Present, it must name the ACTIVE snapshot itself --
    #: asking against a candidate or superseded world resolves to UNRESOLVED
    #: rather than compiling answers against an unpublished world.
    world_state_id: str | None = Field(default=None, min_length=1, max_length=200)


class AskEvidenceOccurrence(BaseModel):
    """One citation, wire-shaped. Source status rides along by name."""

    claim_id: str
    evidence_id: str
    source_status: str


class AskResponse(BaseModel):
    """§22.3's CompiledAnswer, wire-shaped."""

    outcome: AnswerOutcome
    claim_ids: list[str]
    evidence: list[AskEvidenceOccurrence]
    world_state_id: str
    intent: QueryIntent
    reason: str


def _unresolved(intent: QueryIntent, reason: str) -> CompiledAnswer:
    """The empty answer, shaped exactly like the compiler's own refusals."""
    return CompiledAnswer(
        claim_ids=(),
        world_state_id="",
        evidence_occurrences=(),
        outcome=AnswerOutcome.UNRESOLVED,
        intent=intent,
        reason=reason,
    )


def _to_response(answer: CompiledAnswer) -> AskResponse:
    return AskResponse(
        outcome=answer.outcome,
        claim_ids=list(answer.claim_ids),
        evidence=[
            AskEvidenceOccurrence(
                claim_id=occurrence.claim_id,
                evidence_id=occurrence.evidence_id,
                source_status=occurrence.source_status.name,
            )
            for occurrence in answer.evidence_occurrences
        ],
        world_state_id=answer.world_state_id,
        intent=answer.intent,
        reason=answer.reason,
    )


@router.post("/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    principal: PrincipalDep,
    request: Request,
    sink: ReceiptSinkDep,
) -> AskResponse:
    """Compile a question against the locally published world state.

    Requires an authenticated session. Every store-level refusal comes back
    as a 200 UNRESOLVED finding with its reason; only missing credentials
    short-circuit to 401, because who is asking decides what they may see.
    """
    settings: Settings = request.app.state.settings
    resolution = _resolve_world(settings.world_store_dir, payload.world_state_id)
    intent = classify_intent(payload.query)

    answer: CompiledAnswer
    if resolution.snapshot is None:
        answer = _unresolved(intent, resolution.refusal_reason)
    else:
        try:
            registry = _rebuild_registry(resolution.snapshot)
        except PublishRefused as exc:
            answer = _unresolved(
                intent,
                "the recorded world state failed its own publication gates: " f"{exc}",
            )
        else:
            # No retrieval layer sits in front of the compiler yet: every
            # claim in the ACTIVE snapshot is the draft set, and authority
            # resolution -- not keyword matching -- decides what applies.
            drafts = [
                DraftClaim(
                    claim=ScopedClaim(
                        claim_id=claim.claim_id,
                        subject=claim.subject,
                        value=claim.value,
                        authority=claim.authority,
                        source_status=claim.source_status,
                        scope=dict(claim.scope),
                        valid_from=claim.valid_from,
                        valid_to=claim.valid_to,
                        recorded_at=claim.recorded_at,
                        required_permission=claim.required_permission,
                        evidence_id=claim.evidence_id,
                    ),
                    world_state_id=claim.extracted_world_state_id,
                )
                for claim in resolution.snapshot.claims
            ]
            context = ClaimContext(
                subject=f"user:{principal.user_id}",
                as_of=datetime.now(UTC),
                # A claim's required_permission matches any role or scope the
                # session actually holds; anything else is invisible to it.
                permissions=principal.roles | principal.scopes,
            )
            answer = compile_answer(payload.query, drafts, registry, context)

    await sink.record(
        AskConsumptionRecord(
            query=payload.query,
            intent=answer.intent.value,
            outcome=answer.outcome.value,
            claim_ids=answer.claim_ids,
            world_state_id=answer.world_state_id,
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            answered_at=datetime.now(UTC),
        )
    )
    return _to_response(answer)


__all__ = [
    "NOOP_RECEIPT_SINK",
    "SNAPSHOT_SCHEMA_VERSION",
    "AskConsumptionRecord",
    "AskRequest",
    "AskResponse",
    "NoopReceiptSink",
    "ReceiptSink",
    "WorldSnapshotDocument",
    "ask",
    "get_receipt_sink",
    "router",
]
