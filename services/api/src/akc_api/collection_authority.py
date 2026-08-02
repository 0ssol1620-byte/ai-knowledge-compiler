"""Verified, idempotent authority-fact ingestion for v4 collections."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from akc_quality import (
    AuthorityNumericFact,
    DartXbrlProvenance,
    NumericAuthorityMerge,
    NumericCellKey,
    NumericDiagnosticMatch,
    NumericGeometryResult,
    ParserNumericCell,
    SecInlineXbrlProvenance,
    match_numeric_geometry,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    AuditEvent,
    AuthorityFact,
    AuthorityMapping,
    Collection,
    CollectionRegion,
    VerificationRecord,
    utcnow,
)

AuthoritySourceKind = Literal["dart", "sec", "native_pdf", "html_xml"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SOURCE_BYTES = 100 * 1024 * 1024
_MAX_FACTS = 100_000


class AuthorityIngestionError(ValueError):
    """A provider receipt is incomplete, inconsistent, or non-deterministic."""


class AuthorityFactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stable_key: Annotated[str, Field(min_length=1, max_length=200)]
    normalized_value: Decimal
    unit: Annotated[str | None, Field(default=None, max_length=80)]
    currency: Annotated[str | None, Field(default=None, max_length=12)]
    period: Annotated[str | None, Field(default=None, max_length=80)]
    context: dict[str, Any]
    source_locator: dict[str, Any]

    @field_validator("normalized_value")
    @classmethod
    def finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("authority value must be finite")
        return value

    @field_validator("context", "source_locator")
    @classmethod
    def bounded_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("authority provenance must be canonical JSON") from exc
        if len(encoded) > 32_768:
            raise ValueError("authority provenance exceeds 32 KiB")
        return value


class VerifiedAuthorityReceipt(BaseModel):
    """Immutable bytes and exact facts returned by an approved source adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: AuthoritySourceKind
    source_revision: Annotated[str, Field(min_length=1, max_length=240)]
    source_bytes: Annotated[bytes, Field(min_length=1, max_length=_MAX_SOURCE_BYTES)]
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    adapter_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")]
    adapter_revision: Annotated[str, Field(min_length=1, max_length=120)]
    verification_status: Literal["source_bytes_verified"]
    facts: Annotated[tuple[AuthorityFactPayload, ...], Field(min_length=1, max_length=_MAX_FACTS)]

    @model_validator(mode="after")
    def verify_source_digest_and_keys(self) -> VerifiedAuthorityReceipt:
        actual = hashlib.sha256(self.source_bytes).hexdigest()
        if actual != self.source_sha256:
            raise ValueError("authority source digest mismatch")
        keys = [fact.stable_key for fact in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("authority stable keys must be unique in one receipt")
        return self


class AuthorityIngestionAdapter(Protocol):
    adapter_id: str

    async def fetch(self, *, collection_id: uuid.UUID) -> VerifiedAuthorityReceipt: ...


@dataclass(frozen=True, slots=True)
class AuthorityIngestionResult:
    collection_id: uuid.UUID
    source_kind: str
    source_revision: str
    source_sha256: str
    inserted_count: int
    reused_count: int
    fact_ids: tuple[uuid.UUID, ...]
    audit_event_id: uuid.UUID
    ingestion_key: str


@dataclass(frozen=True, slots=True)
class AuthorityGeometryMaterializationResult:
    collection_id: uuid.UUID
    state: str
    matched_count: int
    rejected_count: int
    superseded_count: int
    mapping_ids: tuple[uuid.UUID, ...]
    audit_event_id: uuid.UUID
    materialization_key: str
    numeric_result: NumericGeometryResult


def _date(value: object) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _validate_numeric_provenance(
    source_kind: AuthoritySourceKind,
    fact: AuthorityFactPayload,
) -> None:
    if source_kind not in {"dart", "sec"}:
        return
    context = fact.context
    locator = fact.source_locator
    unit = fact.unit or context.get("unit")
    try:
        key = NumericCellKey(
            entity_id=str(context["entity_id"]),
            statement=str(context["statement"]),
            concept=str(context["concept"]),
            period_start=_date(context.get("period_start")),
            period_end=_date(context.get("period_end")),
            instant=_date(context.get("instant")),
            unit=str(unit),
            scale=int(context.get("scale", 1)),
            dimensions=dict(context.get("dimensions", {})),
            page=int(context["page"]),
            row_key=str(context["row_key"]),
            column_key=str(context["column_key"]),
        )
        common = {
            "entity_id": key.entity_id,
            "fact_period_start": key.period_start,
            "fact_period_end": key.period_end,
            "fact_instant": key.instant,
        }
        provenance = (
            DartXbrlProvenance(
                **common,
                receipt_number=str(locator["receipt_number"]),
                report_code=str(locator["report_code"]),
                xml_fact_id=str(locator["xml_fact_id"]),
                xml_document_uri=str(locator["xml_document_uri"]),
                pdf_document_uri=str(locator["pdf_document_uri"]),
            )
            if source_kind == "dart"
            else SecInlineXbrlProvenance(
                **common,
                accession_number=str(locator["accession_number"]),
                form=str(locator["form"]),
                inline_xbrl_fact_id=str(locator["inline_xbrl_fact_id"]),
                filing_html_uri=str(locator["filing_html_uri"]),
            )
        )
        AuthorityNumericFact(
            fact_id=fact.stable_key,
            key=key,
            xbrl_label=str(context["xbrl_label"]),
            value=fact.normalized_value,
            provenance=provenance,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityIngestionError(
            f"{source_kind} fact lacks exact numeric provenance: {fact.stable_key}"
        ) from exc


def _authority_numeric_fact(row: AuthorityFact) -> AuthorityNumericFact:
    """Rebuild the strict matcher contract from one verified durable fact."""

    context = row.context
    locator = row.source_locator
    unit = row.unit or context.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        raise AuthorityIngestionError(f"authority fact unit is missing: {row.stable_key}")
    try:
        key = NumericCellKey(
            entity_id=str(context["entity_id"]),
            statement=str(context["statement"]),
            concept=str(context["concept"]),
            period_start=_date(context.get("period_start")),
            period_end=_date(context.get("period_end")),
            instant=_date(context.get("instant")),
            unit=unit,
            scale=int(context.get("scale", 1)),
            dimensions=dict(context.get("dimensions", {})),
            page=int(context["page"]),
            row_key=str(context["row_key"]),
            column_key=str(context["column_key"]),
        )
        common = {
            "entity_id": key.entity_id,
            "fact_period_start": key.period_start,
            "fact_period_end": key.period_end,
            "fact_instant": key.instant,
        }
        provenance = (
            DartXbrlProvenance(
                **common,
                receipt_number=str(locator["receipt_number"]),
                report_code=str(locator["report_code"]),
                xml_fact_id=str(locator["xml_fact_id"]),
                xml_document_uri=str(locator["xml_document_uri"]),
                pdf_document_uri=str(locator["pdf_document_uri"]),
            )
            if row.source_kind == "dart"
            else SecInlineXbrlProvenance(
                **common,
                accession_number=str(locator["accession_number"]),
                form=str(locator["form"]),
                inline_xbrl_fact_id=str(locator["inline_xbrl_fact_id"]),
                filing_html_uri=str(locator["filing_html_uri"]),
            )
        )
        return AuthorityNumericFact(
            fact_id=str(row.id),
            key=key,
            xbrl_label=str(context["xbrl_label"]),
            value=Decimal(row.normalized_value),
            provenance=provenance,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityIngestionError(
            f"authority fact cannot enter geometry matching: {row.stable_key}"
        ) from exc


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping_geometry(cell: ParserNumericCell) -> dict[str, Any]:
    payload = cell.model_dump(mode="json")
    # Validate the durable representation before it can become semantic input.
    ParserNumericCell.model_validate(payload)
    return payload


async def materialize_authority_geometry(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    parser_cells: tuple[ParserNumericCell, ...],
    region_ids_by_parser_cell_id: Mapping[str, uuid.UUID],
) -> AuthorityGeometryMaterializationResult:
    """Atomically reconcile one complete collection-wide numeric geometry batch.

    The batch is deliberately complete-scope: every previously active mapping is
    superseded before the new hard-gate result is projected. A partial or failed
    match therefore cannot leave stale publishable authority behind.
    """

    cell_ids = tuple(cell.parser_cell_id for cell in parser_cells)
    if not parser_cells or len(set(cell_ids)) != len(cell_ids):
        raise AuthorityIngestionError("authority geometry batch requires unique parser cells")
    if set(cell_ids) != set(region_ids_by_parser_cell_id):
        raise AuthorityIngestionError("every parser cell requires exactly one scoped region")

    collection = await session.scalar(
        select(Collection).where(
            Collection.tenant_id == tenant_id,
            Collection.id == collection_id,
        )
    )
    if collection is None:
        raise AuthorityIngestionError("authority geometry collection scope does not exist")

    fact_rows = list(
        await session.scalars(
            select(AuthorityFact).where(
                AuthorityFact.tenant_id == tenant_id,
                AuthorityFact.collection_id == collection_id,
                AuthorityFact.status == "verified",
            )
        )
    )
    if not fact_rows:
        raise AuthorityIngestionError("authority geometry requires verified authority facts")
    if any(row.source_kind not in {"dart", "sec"} for row in fact_rows):
        raise AuthorityIngestionError("numeric geometry accepts only DART or SEC authority")

    requested_region_ids = set(region_ids_by_parser_cell_id.values())
    region_rows = list(
        await session.scalars(
            select(CollectionRegion).where(
                CollectionRegion.tenant_id == tenant_id,
                CollectionRegion.collection_id == collection_id,
                CollectionRegion.id.in_(tuple(requested_region_ids)),
            )
        )
    )
    if {row.id for row in region_rows} != requested_region_ids:
        raise AuthorityIngestionError("authority geometry region scope is incomplete")
    non_terminal = sorted(
        row.stable_key
        for row in region_rows
        if row.status not in {"verified", "auto_repaired", "verified_with_warning"}
    )
    if non_terminal:
        raise AuthorityIngestionError(
            "authority geometry requires verified regions: " + ", ".join(non_terminal)
        )

    facts = tuple(_authority_numeric_fact(row) for row in fact_rows)
    numeric_result = match_numeric_geometry(facts, parser_cells)
    materialization_state = numeric_result.state.value.casefold()
    fact_row_by_id = {str(row.id): row for row in fact_rows}
    cell_by_id = {cell.parser_cell_id: cell for cell in parser_cells}

    existing_rows = list(
        await session.scalars(
            select(AuthorityMapping).where(
                AuthorityMapping.tenant_id == tenant_id,
                AuthorityMapping.collection_id == collection_id,
            )
        )
    )
    existing_by_pair = {(row.authority_fact_id, row.region_id): row for row in existing_rows}
    superseded = 0
    for row in existing_rows:
        if row.mapping_status == "matched":
            row.mapping_status = "rejected"
            row.evidence = {
                **row.evidence,
                "superseded": True,
                "superseded_reason": "complete_scope_geometry_reconciliation",
            }
            superseded += 1
    existing_verifications = list(
        await session.scalars(
            select(VerificationRecord).where(
                VerificationRecord.tenant_id == tenant_id,
                VerificationRecord.collection_id == collection_id,
                VerificationRecord.validator_revision == "authority-geometry-matcher-v4",
            )
        )
    )
    for verification in existing_verifications:
        if verification.status == "authority_verified":
            verification.status = "rejected"
            verification.evidence = {
                **verification.evidence,
                "superseded": True,
                "superseded_reason": "complete_scope_geometry_reconciliation",
            }

    projected: list[AuthorityMapping] = []
    accepted = numeric_result.publishable_matches
    diagnostics = numeric_result.diagnostic_matches
    rejected_matches: tuple[NumericAuthorityMerge | NumericDiagnosticMatch, ...] = (
        *(match for match in numeric_result.matches if match not in accepted),
        *diagnostics,
    )
    matches_to_project: tuple[NumericAuthorityMerge | NumericDiagnosticMatch, ...] = (
        *accepted,
        *rejected_matches,
    )
    for match in matches_to_project:
        fact_row = fact_row_by_id[match.authority_fact_id]
        cell = cell_by_id[match.parser_cell_id]
        region_id = region_ids_by_parser_cell_id[cell.parser_cell_id]
        pair = (fact_row.id, region_id)
        mapping_row = existing_by_pair.get(pair)
        if mapping_row is None:
            mapping_row = AuthorityMapping(
                tenant_id=tenant_id,
                collection_id=collection_id,
                authority_fact_id=fact_row.id,
                region_id=region_id,
                mapping_status="rejected",
                geometry={},
                evidence={},
            )
            session.add(mapping_row)
            existing_by_pair[pair] = mapping_row
        is_publishable = match in accepted
        signals = match.signals.model_dump(mode="json")
        mapping_row.mapping_status = "matched" if is_publishable else "rejected"
        mapping_row.score = Decimal(str(match.signals.total))
        mapping_row.geometry = _mapping_geometry(cell)
        mapping_row.evidence = {
            "matcher_revision": "akc-quality.numeric-geometry@v4",
            "batch_state": materialization_state,
            "hard_gate": numeric_result.hard_gate.model_dump(mode="json"),
            "reason_codes": list(numeric_result.reason_codes),
            "signals": signals,
            "mismatch_codes": [code.value for code in match.mismatch_codes],
            "authority_source_sha256": fact_row.source_sha256,
            "parser_cell_sha256": _canonical_sha256(cell.model_dump(mode="json")),
        }
        projected.append(mapping_row)
    await session.flush()

    verification_ids: set[uuid.UUID] = set()
    for row in projected:
        if row.mapping_status != "matched" or row.region_id in verification_ids:
            continue
        verification_ids.add(row.region_id)
        evidence = {
            "authority_mapping_id": str(row.id),
            "authority_fact_id": str(row.authority_fact_id),
            "geometry_sha256": _canonical_sha256(row.geometry),
            "hard_gate": numeric_result.hard_gate.model_dump(mode="json"),
        }
        evidence_sha256 = _canonical_sha256(evidence)
        prior = next(
            (
                verification
                for verification in existing_verifications
                if verification.region_id == row.region_id
            ),
            None,
        )
        if prior is None:
            verification = VerificationRecord(
                tenant_id=tenant_id,
                collection_id=collection_id,
                region_id=row.region_id,
                status="authority_verified",
                validator_revision="authority-geometry-matcher-v4",
                evidence={**evidence, "evidence_sha256": evidence_sha256},
            )
            session.add(verification)
            existing_verifications.append(verification)
        else:
            prior.status = "authority_verified"
            if prior.evidence.get("evidence_sha256") != evidence_sha256:
                prior.evidence = {**evidence, "evidence_sha256": evidence_sha256}

    materialization_basis = {
        "tenant_id": str(tenant_id),
        "collection_id": str(collection_id),
        "facts": sorted(
            (str(row.id), row.source_sha256, row.stable_key) for row in fact_rows
        ),
        "cells": sorted(
            (
                cell.parser_cell_id,
                str(region_ids_by_parser_cell_id[cell.parser_cell_id]),
                _canonical_sha256(cell.model_dump(mode="json")),
            )
            for cell in parser_cells
        ),
        "result": numeric_result.model_dump(mode="json"),
    }
    materialization_key = _canonical_sha256(materialization_basis)
    target_id = f"authority-geometry:{materialization_key}"
    audit_row = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "collection.authority_geometry_materialized",
            AuditEvent.target_type == "collection",
            AuditEvent.target_id == target_id,
        )
    )
    if audit_row is None:
        audit_row = AuditEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="collection.authority_geometry_materialized",
            target_type="collection",
            target_id=target_id,
            metadata_json={
                "collection_id": str(collection_id),
                "state": materialization_state,
                "matched_count": len(accepted),
                "rejected_count": len(rejected_matches),
                "superseded_count": superseded,
                "hard_gate": numeric_result.hard_gate.model_dump(mode="json"),
                "reason_codes": list(numeric_result.reason_codes),
            },
        )
        session.add(audit_row)
        await session.flush()

    return AuthorityGeometryMaterializationResult(
        collection_id=collection_id,
        state=materialization_state,
        matched_count=len(accepted),
        rejected_count=len(rejected_matches),
        superseded_count=superseded,
        mapping_ids=tuple(row.id for row in projected),
        audit_event_id=audit_row.id,
        materialization_key=materialization_key,
        numeric_result=numeric_result,
    )


def _fact_values(
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    receipt: VerifiedAuthorityReceipt,
    payload: AuthorityFactPayload,
    fact_id: uuid.UUID,
) -> dict[str, Any]:
    return {
        "id": fact_id,
        "tenant_id": tenant_id,
        "collection_id": collection_id,
        "source_kind": receipt.source_kind,
        "stable_key": payload.stable_key,
        "normalized_value": format(payload.normalized_value, "f"),
        "unit": payload.unit,
        "currency": payload.currency,
        "period": payload.period,
        "context": payload.context,
        "source_locator": {
            **payload.source_locator,
            "source_revision": receipt.source_revision,
            "adapter_id": receipt.adapter_id,
            "adapter_revision": receipt.adapter_revision,
        },
        "source_sha256": receipt.source_sha256,
        "status": "verified",
        "created_at": utcnow(),
    }


def _same_fact(row: AuthorityFact, expected: dict[str, Any]) -> bool:
    return all(
        getattr(row, field) == expected[field]
        for field in (
            "normalized_value",
            "unit",
            "currency",
            "period",
            "context",
            "source_locator",
            "status",
        )
    )


async def ingest_verified_authority(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    adapter: AuthorityIngestionAdapter,
) -> AuthorityIngestionResult:
    """Fetch one verified receipt and idempotently materialize its facts."""

    collection = await session.scalar(
        select(Collection).where(
            Collection.tenant_id == tenant_id,
            Collection.id == collection_id,
        )
    )
    if collection is None:
        raise AuthorityIngestionError("authority collection scope does not exist")
    receipt = await adapter.fetch(collection_id=collection_id)
    if adapter.adapter_id != receipt.adapter_id:
        raise AuthorityIngestionError("authority adapter identity differs from receipt")
    for payload in receipt.facts:
        _validate_numeric_provenance(receipt.source_kind, payload)

    inserted = 0
    reused = 0
    rows: list[AuthorityFact] = []
    dialect = session.bind.dialect.name if session.bind is not None else ""
    for payload in receipt.facts:
        expected = _fact_values(
            tenant_id=tenant_id,
            collection_id=collection_id,
            receipt=receipt,
            payload=payload,
            fact_id=uuid.uuid4(),
        )
        statement: Any = None
        if dialect == "postgresql":
            statement = postgresql_insert(AuthorityFact).values(**expected).on_conflict_do_nothing(
                index_elements=("collection_id", "source_kind", "stable_key", "source_sha256")
            )
        elif dialect == "sqlite":
            statement = sqlite_insert(AuthorityFact).values(**expected).on_conflict_do_nothing(
                index_elements=("collection_id", "source_kind", "stable_key", "source_sha256")
            )
        if statement is not None:
            await session.execute(statement)
        else:
            existing = await session.scalar(
                select(AuthorityFact).where(
                    AuthorityFact.collection_id == collection_id,
                    AuthorityFact.source_kind == receipt.source_kind,
                    AuthorityFact.stable_key == payload.stable_key,
                    AuthorityFact.source_sha256 == receipt.source_sha256,
                )
            )
            if existing is None:
                session.add(AuthorityFact(**expected))
        row = await session.scalar(
            select(AuthorityFact).where(
                AuthorityFact.tenant_id == tenant_id,
                AuthorityFact.collection_id == collection_id,
                AuthorityFact.source_kind == receipt.source_kind,
                AuthorityFact.stable_key == payload.stable_key,
                AuthorityFact.source_sha256 == receipt.source_sha256,
            )
        )
        if row is None:
            raise AuthorityIngestionError("authority fact upsert did not persist")
        inserted += int(row.id == expected["id"])
        if not _same_fact(row, expected):
            raise AuthorityIngestionError(
                f"authority receipt is non-deterministic for {payload.stable_key}"
            )
        rows.append(row)
    reused = len(rows) - inserted

    ingestion_key = hashlib.sha256(
        f"{tenant_id}:{collection_id}:{receipt.source_kind}:{receipt.source_sha256}".encode()
    ).hexdigest()
    audit_target = f"authority-ingestion:{ingestion_key}"
    audit_row = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "collection.authority_ingested",
            AuditEvent.target_type == "collection",
            AuditEvent.target_id == audit_target,
        )
    )
    if audit_row is None:
        audit_row = AuditEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="collection.authority_ingested",
            target_type="collection",
            target_id=audit_target,
            metadata_json={
                "collection_id": str(collection_id),
                "source_kind": receipt.source_kind,
                "source_revision": receipt.source_revision,
                "source_sha256": receipt.source_sha256,
                "adapter_id": receipt.adapter_id,
                "adapter_revision": receipt.adapter_revision,
                "fact_count": len(rows),
                "verification_status": receipt.verification_status,
            },
        )
        session.add(audit_row)
        await session.flush()
    return AuthorityIngestionResult(
        collection_id=collection_id,
        source_kind=receipt.source_kind,
        source_revision=receipt.source_revision,
        source_sha256=receipt.source_sha256,
        inserted_count=inserted,
        reused_count=reused,
        fact_ids=tuple(row.id for row in rows),
        audit_event_id=audit_row.id,
        ingestion_key=ingestion_key,
    )


__all__ = [
    "AuthorityFactPayload",
    "AuthorityGeometryMaterializationResult",
    "AuthorityIngestionAdapter",
    "AuthorityIngestionError",
    "AuthorityIngestionResult",
    "VerifiedAuthorityReceipt",
    "ingest_verified_authority",
    "materialize_authority_geometry",
]
