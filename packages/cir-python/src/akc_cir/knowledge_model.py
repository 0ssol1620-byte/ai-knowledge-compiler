"""Canonical, renderer-neutral knowledge model for deployable packages.

Folders and application views are deliberately absent: they are projections of
this model, never its source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from .base import ContractModel, Sha256, StableId, canonical_json, sha256_digest
from .models import SourceRef


class KnowledgeObjectKind(StrEnum):
    COLLECTION = "collection"
    DOCUMENT = "document"
    DOCUMENT_VERSION = "document_version"
    PAGE = "page"
    REGION = "region"
    BLOCK = "block"
    TABLE = "table"
    FIGURE = "figure"
    NOTE = "note"
    ENTITY = "entity"
    RELATION = "relation"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    ASSET = "asset"
    ONTOLOGY_TERM = "ontology_term"
    EXPORT_ARTIFACT = "export_artifact"
    VALIDATION_RECORD = "validation_record"


class KnowledgeOrigin(StrEnum):
    SOURCE_EXPLICIT = "source_explicit"
    STRUCTURED_DERIVED = "structured_derived"
    RULE_DERIVED = "rule_derived"
    MODEL_INFERRED = "model_inferred"
    NATIVE_EXTRACTED = "native_extracted"
    VISUAL_EXTRACTED = "visual_extracted"
    AUTHORITY_RECONSTRUCTED = "authority_reconstructed"


class KnowledgeVerificationState(StrEnum):
    VERIFIED = "verified"
    AUTHORITY_VERIFIED = "authority_verified"
    AUTO_REPAIRED = "auto_repaired"
    VERIFIED_WITH_WARNING = "verified_with_warning"
    UNRESOLVED = "unresolved"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


_PROMOTED_STATES = {
    KnowledgeVerificationState.VERIFIED,
    KnowledgeVerificationState.AUTHORITY_VERIFIED,
    KnowledgeVerificationState.AUTO_REPAIRED,
    KnowledgeVerificationState.VERIFIED_WITH_WARNING,
}


def _object_digest_payload(
    *,
    stable_id: str,
    tenant_id: str,
    collection_id: str,
    kind: KnowledgeObjectKind,
    source_refs: Sequence[SourceRef],
    origin: KnowledgeOrigin,
    verification_state: KnowledgeVerificationState,
    created_by_activity: str,
    version: int,
    links: Sequence[str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "stableId": stable_id,
        "tenantId": tenant_id,
        "collectionId": collection_id,
        "kind": kind.value,
        "sourceRefs": [
            item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in source_refs
        ],
        "origin": origin.value,
        "verificationState": verification_state.value,
        "createdByActivity": created_by_activity,
        "version": version,
        "links": list(links),
        "payload": dict(payload),
    }


class CanonicalKnowledgeObject(ContractModel):
    """One immutable object carrying every v4 provenance invariant."""

    stable_id: StableId
    tenant_id: StableId
    collection_id: StableId
    kind: KnowledgeObjectKind
    source_refs: tuple[SourceRef, ...]
    origin: KnowledgeOrigin
    verification_state: KnowledgeVerificationState
    created_by_activity: StableId
    version: int = Field(ge=1)
    hash: Sha256
    links: tuple[StableId, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_refs")
    @classmethod
    def require_source_provenance(
        cls,
        value: tuple[SourceRef, ...],
    ) -> tuple[SourceRef, ...]:
        if not value:
            raise ValueError("canonical knowledge objects require source provenance")
        return value

    @field_validator("links")
    @classmethod
    def unique_links(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("canonical knowledge object links must be unique")
        return value

    @model_validator(mode="after")
    def verify_policy_and_hash(self) -> CanonicalKnowledgeObject:
        if (
            self.kind is KnowledgeObjectKind.RELATION
            and self.origin is KnowledgeOrigin.MODEL_INFERRED
            and self.verification_state in _PROMOTED_STATES
        ):
            raise ValueError("model-inferred relations cannot enter the verified graph")
        expected = sha256_digest(
            canonical_json(
                _object_digest_payload(
                    stable_id=self.stable_id,
                    tenant_id=self.tenant_id,
                    collection_id=self.collection_id,
                    kind=self.kind,
                    source_refs=self.source_refs,
                    origin=self.origin,
                    verification_state=self.verification_state,
                    created_by_activity=self.created_by_activity,
                    version=self.version,
                    links=self.links,
                    payload=self.payload,
                )
            )
        )
        if self.hash != expected:
            raise ValueError("canonical knowledge object hash is not reproducible")
        return self


def build_knowledge_object(
    *,
    stable_id: str,
    tenant_id: str,
    collection_id: str,
    kind: KnowledgeObjectKind,
    source_refs: Sequence[SourceRef],
    origin: KnowledgeOrigin,
    verification_state: KnowledgeVerificationState,
    created_by_activity: str,
    version: int,
    links: Sequence[str] = (),
    payload: Mapping[str, Any] | None = None,
) -> CanonicalKnowledgeObject:
    """Create an object whose digest covers identity, lineage, state and payload."""

    normalized_payload = dict(payload or {})
    digest = sha256_digest(
        canonical_json(
            _object_digest_payload(
                stable_id=stable_id,
                tenant_id=tenant_id,
                collection_id=collection_id,
                kind=kind,
                source_refs=source_refs,
                origin=origin,
                verification_state=verification_state,
                created_by_activity=created_by_activity,
                version=version,
                links=links,
                payload=normalized_payload,
            )
        )
    )
    return CanonicalKnowledgeObject(
        stable_id=stable_id,
        tenant_id=tenant_id,
        collection_id=collection_id,
        kind=kind,
        source_refs=tuple(source_refs),
        origin=origin,
        verification_state=verification_state,
        created_by_activity=created_by_activity,
        version=version,
        hash=digest,
        links=tuple(links),
        payload=normalized_payload,
    )


class CanonicalKnowledgeModel(ContractModel):
    schema_version: str = "canonical-knowledge-1.0.0"
    tenant_id: StableId
    collection_id: StableId
    objects: tuple[CanonicalKnowledgeObject, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> CanonicalKnowledgeModel:
        if not self.objects:
            raise ValueError("canonical knowledge model cannot be empty")
        identifiers = [item.stable_id for item in self.objects]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("canonical knowledge object IDs must be unique")
        if any(
            item.tenant_id != self.tenant_id or item.collection_id != self.collection_id
            for item in self.objects
        ):
            raise ValueError("canonical knowledge object scope mismatch")
        known = set(identifiers)
        missing = sorted(
            {link for item in self.objects for link in item.links if link not in known}
        )
        if missing:
            raise ValueError(f"canonical knowledge links reference unknown objects: {missing}")
        if not any(item.kind is KnowledgeObjectKind.COLLECTION for item in self.objects):
            raise ValueError("canonical knowledge model requires a collection root")
        return self


__all__ = [
    "CanonicalKnowledgeModel",
    "CanonicalKnowledgeObject",
    "KnowledgeObjectKind",
    "KnowledgeOrigin",
    "KnowledgeVerificationState",
    "build_knowledge_object",
]
