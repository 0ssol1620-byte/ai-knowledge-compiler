"""Evidence-bound knowledge layer contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import field_validator, model_validator

from .base import Confidence, ContractModel, NonEmptyStr, StableId
from .models import BlockOrigin


class NoteType(StrEnum):
    CONCEPT = "concept"
    DOCUMENT = "document"
    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    GLOSSARY = "glossary"
    QUESTION = "question"
    MOC = "moc"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    AUTO_WITH_WARNINGS = "auto_with_warnings"
    USER_VERIFIED = "user_verified"
    REJECTED = "rejected"


class AssertionStatus(StrEnum):
    EXTRACTED = "extracted"
    AI_SUMMARIZED = "ai_summarized"
    AI_INFERRED = "ai_inferred"
    USER_VERIFIED = "user_verified"


class Claim(ContractModel):
    text: NonEmptyStr
    origin: BlockOrigin
    source_block_ids: tuple[StableId, ...]
    confidence: Confidence

    @field_validator("source_block_ids")
    @classmethod
    def require_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("factual claims require source block IDs")
        return value


class RelatedNoteCandidate(ContractModel):
    target_id: StableId
    relation: NonEmptyStr
    reason: NonEmptyStr
    source_block_ids: tuple[StableId, ...]
    confidence: Confidence

    @field_validator("source_block_ids")
    @classmethod
    def require_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("related note candidates require evidence")
        return value


class KnowledgeNote(ContractModel):
    note_id: StableId
    title: NonEmptyStr
    note_type: NoteType
    content_origin: BlockOrigin
    evidence_block_ids: tuple[StableId, ...]
    summary: str | None = None
    claims: tuple[Claim, ...]
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    related_note_candidates: tuple[RelatedNoteCandidate, ...] = ()
    review_status: ReviewStatus = ReviewStatus.PENDING

    @field_validator("evidence_block_ids")
    @classmethod
    def require_note_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("knowledge notes require evidence block IDs")
        return value

    @model_validator(mode="after")
    def require_substance(self) -> KnowledgeNote:
        if not self.claims and not self.summary:
            raise ValueError("knowledge note requires a summary or evidence-bound claims")
        return self


class RelationAssertion(ContractModel):
    id: StableId
    subject: StableId
    predicate: NonEmptyStr
    object: StableId
    assertion_status: AssertionStatus
    confidence: Confidence
    evidence_block_ids: tuple[StableId, ...]
    review_status: ReviewStatus = ReviewStatus.PENDING

    @field_validator("evidence_block_ids")
    @classmethod
    def require_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("relations require evidence block IDs")
        return value


class ConflictDimension(StrEnum):
    VERSION_OR_TIME = "version_or_time"
    CONTRADICTORY_CLAIM = "contradictory_claim"
    DEFINITION = "definition"
    NUMERIC_VALUE = "numeric_value"
    OTHER = "other"


class ConflictCandidate(ContractModel):
    id: StableId
    statement_a: dict[str, Any]
    statement_b: dict[str, Any]
    dimension: ConflictDimension
    resolution: str = "unresolved"
    requires_review: bool = True
    evidence_block_ids: tuple[StableId, ...]

    @field_validator("evidence_block_ids")
    @classmethod
    def require_two_evidence_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) < 2:
            raise ValueError("conflicts require evidence from at least two blocks")
        return value


class DocumentContains(ContractModel):
    tables: bool = False
    formulas: bool = False
    figures: bool = False
    citations: bool = False
    personal_data: bool = False


class DocumentClassification(ContractModel):
    document_type: NonEmptyStr
    secondary_types: tuple[str, ...] = ()
    language: NonEmptyStr
    languages: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    domain: tuple[str, ...] = ()
    structure_profile: NonEmptyStr
    risk_tier: str
    contains: DocumentContains
    evidence_block_ids: tuple[StableId, ...]
    confidence: Confidence

    @field_validator("evidence_block_ids")
    @classmethod
    def require_classification_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("classification requires evidence")
        return value


class KnowledgeBundle(ContractModel):
    schema_version: str = "knowledge-1.0.0"
    document_id: StableId
    notes: tuple[KnowledgeNote, ...]
    relations: tuple[RelationAssertion, ...] = ()
    conflicts: tuple[ConflictCandidate, ...] = ()

    @field_validator("notes")
    @classmethod
    def unique_note_ids(cls, value: tuple[KnowledgeNote, ...]) -> tuple[KnowledgeNote, ...]:
        ids = [note.note_id for note in value]
        if len(ids) != len(set(ids)):
            raise ValueError("note IDs must be unique")
        return value
