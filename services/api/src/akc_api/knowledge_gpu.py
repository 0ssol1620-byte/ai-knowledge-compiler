"""Strict, evidence-bound contracts for durable knowledge GPU artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from akc_cir import (
    ConflictCandidate,
    DocumentClassification,
    KnowledgeBundle,
    KnowledgeNote,
    RelationAssertion,
)
from akc_quality import FindingSeverity, validate_knowledge_evidence
from pydantic import (
    AliasGenerator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
KNOWLEDGE_INPUT_SCHEMA_VERSION = "knowledge-input-1.0.0"
KNOWLEDGE_ARTIFACT_CONTRACT = "akc-knowledge-bundle-1.0.0"
KNOWLEDGE_PIPELINE_INPUT_SCHEMA_VERSION = "knowledge-pipeline-input-1.0.0"
KNOWLEDGE_PIPELINE_RESULT_SCHEMA_VERSION = "knowledge-pipeline-result-1.0.0"
KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT = "akc-knowledge-pipeline-stage-1.0.0"
type KnowledgeStage = Literal["A", "B", "C", "D"]
type RetrievalStatus = Literal["provider_unverified", "no_candidates", "ready"]

_INPUT_CONFIG = ConfigDict(extra="forbid", frozen=True)
_OUTPUT_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    populate_by_name=True,
    alias_generator=AliasGenerator(
        validation_alias=to_camel,
        serialization_alias=to_camel,
    ),
)


class KnowledgeSourceRef(BaseModel):
    model_config = _INPUT_CONFIG

    document_id: Annotated[str, Field(min_length=3, max_length=256)]
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    page_index0: Annotated[int, Field(ge=0)]
    page_number1: Annotated[int, Field(ge=1)]
    bbox1000: (
        tuple[
            Annotated[int, Field(ge=0, le=1000)],
            Annotated[int, Field(ge=0, le=1000)],
            Annotated[int, Field(ge=0, le=1000)],
            Annotated[int, Field(ge=0, le=1000)],
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_bbox(self) -> KnowledgeSourceRef:
        if self.bbox1000 is not None:
            x1, y1, x2, y2 = self.bbox1000
            if x1 >= x2 or y1 >= y2:
                raise ValueError("knowledge source bbox must have positive area")
        if self.page_number1 != self.page_index0 + 1:
            raise ValueError("knowledge source page numbering mismatch")
        return self


class KnowledgeInputBlock(BaseModel):
    """Legacy single-pass input retained for backward-compatible result admission."""

    model_config = _INPUT_CONFIG

    block_id: Annotated[str, Field(min_length=3, max_length=160)]
    text: Annotated[str, Field(min_length=1, max_length=1_000_000)]
    source_refs: Annotated[tuple[KnowledgeSourceRef, ...], Field(min_length=1, max_length=128)]


class KnowledgeInputEnvelope(BaseModel):
    """Legacy private object payload; new production work uses the staged pipeline."""

    model_config = _INPUT_CONFIG

    schema_version: str = KNOWLEDGE_INPUT_SCHEMA_VERSION
    document_id: Annotated[str, Field(min_length=3, max_length=256)]
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    title: Annotated[str, Field(min_length=1, max_length=500)]
    blocks: Annotated[tuple[KnowledgeInputBlock, ...], Field(min_length=1, max_length=10_000)]

    @field_validator("schema_version")
    @classmethod
    def exact_schema_version(cls, value: str) -> str:
        if value != KNOWLEDGE_INPUT_SCHEMA_VERSION:
            raise ValueError("unsupported knowledge input schema")
        return value

    @model_validator(mode="after")
    def unique_and_scoped_blocks(self) -> KnowledgeInputEnvelope:
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("knowledge input block IDs must be unique")
        for block in self.blocks:
            for source_ref in block.source_refs:
                if (
                    source_ref.document_id != self.document_id
                    or source_ref.document_version_id != self.document_version_id
                ):
                    raise ValueError("knowledge input source scope mismatch")
        return self


class StageABlockPreview(BaseModel):
    model_config = _INPUT_CONFIG

    block_id: Annotated[str, Field(min_length=3, max_length=160)]
    block_type: Annotated[str, Field(min_length=1, max_length=40)]
    page_number1: Annotated[int, Field(ge=1)]
    char_count: Annotated[int, Field(ge=1, le=10_000_000)]
    preview: Annotated[str, Field(min_length=1, max_length=240)]
    heading_path: Annotated[tuple[str, ...], Field(max_length=32)] = ()


class StageAHeading(BaseModel):
    model_config = _INPUT_CONFIG

    heading_id: Annotated[str, Field(min_length=3, max_length=160)]
    block_id: Annotated[str, Field(min_length=3, max_length=160)]
    level: Annotated[int, Field(ge=1, le=32)]
    title_preview: Annotated[str, Field(min_length=1, max_length=240)]
    parent_heading_id: Annotated[str | None, Field(max_length=160)] = None


class StageAInput(BaseModel):
    model_config = _INPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-input-1.0.0"] = "knowledge-pipeline-input-1.0.0"
    stage: Literal["A"] = "A"
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    document_id: Annotated[str, Field(min_length=3, max_length=256)]
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    title: Annotated[str, Field(min_length=1, max_length=500)]
    headings: Annotated[tuple[StageAHeading, ...], Field(max_length=2_000)] = ()
    blocks: Annotated[tuple[StageABlockPreview, ...], Field(min_length=1, max_length=10_000)]

    @model_validator(mode="after")
    def validate_map_input(self) -> StageAInput:
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("stage A block IDs must be unique")
        known = set(block_ids)
        heading_ids = {heading.heading_id for heading in self.headings}
        if len(heading_ids) != len(self.headings):
            raise ValueError("stage A heading IDs must be unique")
        if any(
            heading.block_id not in known
            or (
                heading.parent_heading_id is not None
                and heading.parent_heading_id not in heading_ids
            )
            for heading in self.headings
        ):
            raise ValueError("stage A heading scope mismatch")
        if any(not set(block.heading_path).issubset(heading_ids) for block in self.blocks):
            raise ValueError("stage A block heading path is invalid")
        return self


class StageBFragment(BaseModel):
    model_config = _INPUT_CONFIG

    fragment_id: Annotated[str, Field(min_length=3, max_length=200)]
    evidence_block_id: Annotated[str, Field(min_length=3, max_length=160)]
    text: Annotated[str, Field(min_length=1, max_length=64_000)]
    source_refs: Annotated[tuple[KnowledgeSourceRef, ...], Field(min_length=1, max_length=128)]


class StageBInput(BaseModel):
    model_config = _INPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-input-1.0.0"] = "knowledge-pipeline-input-1.0.0"
    stage: Literal["B"] = "B"
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    document_id: Annotated[str, Field(min_length=3, max_length=256)]
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    section_id: Annotated[str, Field(min_length=3, max_length=128)]
    section_title: Annotated[str, Field(min_length=1, max_length=500)]
    classification: DocumentClassification
    shard_index0: Annotated[int, Field(ge=0, le=9_999)]
    shard_count: Annotated[int, Field(ge=1, le=10_000)]
    fragments: Annotated[tuple[StageBFragment, ...], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def validate_section_input(self) -> StageBInput:
        if self.shard_index0 >= self.shard_count:
            raise ValueError("stage B shard index is outside shard count")
        fragment_ids = [fragment.fragment_id for fragment in self.fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("stage B fragment IDs must be unique")
        for fragment in self.fragments:
            for source_ref in fragment.source_refs:
                if (
                    source_ref.document_id != self.document_id
                    or source_ref.document_version_id != self.document_version_id
                ):
                    raise ValueError("stage B source scope mismatch")
        return self


class StageCEvidenceDescriptor(BaseModel):
    model_config = _INPUT_CONFIG

    block_id: Annotated[str, Field(min_length=3, max_length=160)]
    snippet: Annotated[str, Field(min_length=1, max_length=240)]
    snippet_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_snippet_hash(self) -> StageCEvidenceDescriptor:
        if hashlib.sha256(self.snippet.encode()).hexdigest() != self.snippet_sha256:
            raise ValueError("stage C evidence snippet hash mismatch")
        return self


class StageCClaimDescriptor(BaseModel):
    model_config = _INPUT_CONFIG

    text: Annotated[str, Field(min_length=1, max_length=500)]
    signature_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    evidence_block_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]

    @field_validator("evidence_block_ids")
    @classmethod
    def unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("stage C claim evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def validate_signature(self) -> StageCClaimDescriptor:
        payload = "\0".join((self.text, *self.evidence_block_ids)).encode()
        if hashlib.sha256(payload).hexdigest() != self.signature_sha256:
            raise ValueError("stage C claim signature mismatch")
        return self


class StageCCandidateEvidence(BaseModel):
    """Bounded semantic descriptor; never contains an unbounded note or document."""

    model_config = _INPUT_CONFIG

    candidate_id: Annotated[str, Field(min_length=3, max_length=128)]
    normalized_title: Annotated[str, Field(min_length=1, max_length=300)]
    note_type: Annotated[str, Field(min_length=1, max_length=60)]
    summary: Annotated[str, Field(max_length=2_000)] = ""
    aliases: Annotated[tuple[str, ...], Field(max_length=20)] = ()
    tags: Annotated[tuple[str, ...], Field(max_length=20)] = ()
    claims: Annotated[tuple[StageCClaimDescriptor, ...], Field(max_length=20)] = ()
    evidence_block_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=256)]
    evidence: Annotated[
        tuple[StageCEvidenceDescriptor, ...],
        Field(min_length=1, max_length=256),
    ]

    @model_validator(mode="after")
    def validate_semantic_evidence(self) -> StageCCandidateEvidence:
        if len(self.evidence_block_ids) != len(set(self.evidence_block_ids)):
            raise ValueError("stage C evidence IDs must be unique")
        available = set(self.evidence_block_ids)
        described = {item.block_id for item in self.evidence}
        if len(described) != len(self.evidence) or described != available:
            raise ValueError("stage C evidence descriptors are outside candidate scope")
        if any(not set(claim.evidence_block_ids).issubset(available) for claim in self.claims):
            raise ValueError("stage C claim is outside candidate evidence")
        return self


class StageCInput(BaseModel):
    model_config = _INPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-input-1.0.0"] = "knowledge-pipeline-input-1.0.0"
    stage: Literal["C"] = "C"
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    document_id: Annotated[str, Field(min_length=3, max_length=256)]
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    candidates: Annotated[
        tuple[StageCCandidateEvidence, ...],
        Field(min_length=1, max_length=1_000),
    ]

    @model_validator(mode="after")
    def unique_candidates(self) -> StageCInput:
        values = [candidate.candidate_id for candidate in self.candidates]
        if len(values) != len(set(values)):
            raise ValueError("stage C candidate IDs must be unique")
        return self


class StageDSourceCandidate(StageCCandidateEvidence):
    pass


class StageDRetrievalCandidate(BaseModel):
    model_config = _INPUT_CONFIG

    stable_id: Annotated[str, Field(min_length=3, max_length=240)]
    project_id: Annotated[str, Field(min_length=3, max_length=64)]
    title: Annotated[str, Field(min_length=1, max_length=300)]
    note_type: Annotated[str, Field(min_length=1, max_length=60)]
    summary: Annotated[str, Field(max_length=2_000)] = ""
    tags: Annotated[tuple[str, ...], Field(max_length=20)] = ()
    evidence_block_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=100)]
    evidence: Annotated[
        tuple[StageCEvidenceDescriptor, ...],
        Field(min_length=1, max_length=32),
    ]
    score: Annotated[float, Field(ge=-1, le=1)]
    source_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_retrieval_evidence(self) -> StageDRetrievalCandidate:
        available = set(self.evidence_block_ids)
        described = {item.block_id for item in self.evidence}
        if (
            len(available) != len(self.evidence_block_ids)
            or len(described) != len(self.evidence)
            or not described.issubset(available)
        ):
            raise ValueError("stage D retrieval evidence is invalid")
        return self


class StageDAclAttestation(BaseModel):
    model_config = _INPUT_CONFIG

    tenant_id: Annotated[str, Field(min_length=3, max_length=64)]
    allowed_project_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=50)]
    scope_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StageDInput(BaseModel):
    model_config = _INPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-input-1.0.0"] = "knowledge-pipeline-input-1.0.0"
    stage: Literal["D"] = "D"
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    tenant_id: Annotated[str, Field(min_length=3, max_length=64)]
    document_id: Annotated[str, Field(min_length=3, max_length=256)]
    document_version_id: Annotated[str, Field(min_length=3, max_length=256)]
    allowed_project_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=50)]
    acl_attestation: StageDAclAttestation
    source_candidates: Annotated[
        tuple[StageDSourceCandidate, ...],
        Field(min_length=1, max_length=1_000),
    ]
    retrieval_status: RetrievalStatus
    retrieval_candidates: Annotated[
        tuple[StageDRetrievalCandidate, ...],
        Field(max_length=15),
    ] = ()

    @model_validator(mode="after")
    def validate_acl_filtered_candidates(self) -> StageDInput:
        if len(self.allowed_project_ids) != len(set(self.allowed_project_ids)):
            raise ValueError("stage D allowed project IDs must be unique")
        source_ids = [candidate.candidate_id for candidate in self.source_candidates]
        retrieval_ids = [candidate.stable_id for candidate in self.retrieval_candidates]
        if len(source_ids) != len(set(source_ids)) or len(retrieval_ids) != len(set(retrieval_ids)):
            raise ValueError("stage D candidate IDs must be unique")
        allowed = set(self.allowed_project_ids)
        if (
            self.acl_attestation.tenant_id != self.tenant_id
            or self.acl_attestation.allowed_project_ids != self.allowed_project_ids
            or self.acl_attestation.scope_sha256
            != hashlib.sha256(
                "\0".join((self.tenant_id, *self.allowed_project_ids)).encode()
            ).hexdigest()
        ):
            raise ValueError("stage D ACL attestation scope mismatch")
        if any(candidate.project_id not in allowed for candidate in self.retrieval_candidates):
            raise ValueError("stage D retrieval candidate violates project ACL")
        if self.retrieval_status == "provider_unverified" and self.retrieval_candidates:
            raise ValueError("unverified retrieval cannot supply candidates")
        if self.retrieval_status == "no_candidates" and self.retrieval_candidates:
            raise ValueError("no-candidates retrieval status must be empty")
        if self.retrieval_status == "ready" and not self.retrieval_candidates:
            raise ValueError("ready retrieval status requires candidates")
        return self


type KnowledgeStageInput = StageAInput | StageBInput | StageCInput | StageDInput
_STAGE_INPUT_ADAPTER: TypeAdapter[KnowledgeStageInput] = TypeAdapter(
    Annotated[KnowledgeStageInput, Field(discriminator="stage")]
)


class StageASection(BaseModel):
    model_config = _OUTPUT_CONFIG

    section_id: Annotated[str, Field(min_length=3, max_length=128)]
    title: Annotated[str, Field(min_length=1, max_length=500)]
    block_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=10_000)]

    @field_validator("block_ids")
    @classmethod
    def unique_blocks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("stage A section block IDs must be unique")
        return value


class StageAResult(BaseModel):
    model_config = _OUTPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-result-1.0.0"]
    stage: Literal["A"]
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    classification: DocumentClassification
    sections: Annotated[tuple[StageASection, ...], Field(min_length=1, max_length=2_000)]


class StageBResult(BaseModel):
    model_config = _OUTPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-result-1.0.0"]
    stage: Literal["B"]
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    section_id: Annotated[str, Field(min_length=3, max_length=128)]
    notes: Annotated[tuple[KnowledgeNote, ...], Field(max_length=64)]
    relations: Annotated[tuple[RelationAssertion, ...], Field(max_length=512)]
    conflicts: Annotated[tuple[ConflictCandidate, ...], Field(max_length=256)]

    @model_validator(mode="after")
    def unique_note_ids(self) -> StageBResult:
        ids = [note.note_id for note in self.notes]
        if len(ids) != len(set(ids)):
            raise ValueError("stage B note IDs must be unique")
        return self


class StageCMergeGroup(BaseModel):
    model_config = _OUTPUT_CONFIG

    group_id: Annotated[str, Field(min_length=3, max_length=128)]
    canonical_candidate_id: Annotated[str, Field(min_length=3, max_length=128)]
    member_candidate_ids: Annotated[
        tuple[str, ...],
        Field(min_length=1, max_length=1_000),
    ]
    compared_candidate_ids: Annotated[
        tuple[str, ...],
        Field(min_length=1, max_length=1_000),
    ]
    evidence_block_ids: Annotated[
        tuple[str, ...],
        Field(min_length=1, max_length=10_000),
    ]
    reason: Annotated[str, Field(min_length=1, max_length=2_000)]
    parent_candidate_id: Annotated[str | None, Field(max_length=128)] = None

    @field_validator(
        "member_candidate_ids",
        "compared_candidate_ids",
        "evidence_block_ids",
    )
    @classmethod
    def unique_members(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("stage C merge evidence must be unique")
        return value


class StageCResult(BaseModel):
    model_config = _OUTPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-result-1.0.0"]
    stage: Literal["C"]
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    merge_groups: Annotated[
        tuple[StageCMergeGroup, ...],
        Field(min_length=1, max_length=1_000),
    ]


class StageDLinkProposal(BaseModel):
    model_config = _OUTPUT_CONFIG

    source_candidate_id: Annotated[str, Field(min_length=3, max_length=128)]
    target_stable_id: Annotated[str, Field(min_length=3, max_length=240)]
    relation: Annotated[str, Field(min_length=1, max_length=500)]
    reason: Annotated[str, Field(min_length=1, max_length=2_000)]
    evidence_block_ids: Annotated[
        tuple[str, ...],
        Field(min_length=1, max_length=256),
    ]
    confidence: Annotated[float, Field(ge=0, le=1)]

    @field_validator("evidence_block_ids")
    @classmethod
    def unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("stage D link evidence IDs must be unique")
        return value


class StageDResult(BaseModel):
    model_config = _OUTPUT_CONFIG

    schema_version: Literal["knowledge-pipeline-result-1.0.0"]
    stage: Literal["D"]
    unit_id: Annotated[str, Field(min_length=3, max_length=128)]
    retrieval_status: RetrievalStatus
    links: Annotated[tuple[StageDLinkProposal, ...], Field(max_length=1_000)]


type KnowledgeStageResult = StageAResult | StageBResult | StageCResult | StageDResult
_STAGE_RESULT_ADAPTER: TypeAdapter[KnowledgeStageResult] = TypeAdapter(
    Annotated[KnowledgeStageResult, Field(discriminator="stage")]
)


def canonical_json_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=False, exclude_none=True)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def knowledge_input_sha256(value: BaseModel) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def parse_knowledge_input(body: bytes) -> KnowledgeInputEnvelope:
    if not body or len(body) > 16 * 1024 * 1024:
        raise ValueError("knowledge_input_size_invalid")
    try:
        return KnowledgeInputEnvelope.model_validate_json(body)
    except (ValueError, TypeError) as exc:
        raise ValueError("knowledge_input_schema_invalid") from exc


def parse_knowledge_stage_input(body: bytes) -> KnowledgeStageInput:
    if not body or len(body) > 8 * 1024 * 1024:
        raise ValueError("knowledge_stage_input_size_invalid")
    try:
        value = json.loads(body)
        return _STAGE_INPUT_ADAPTER.validate_python(value)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ValueError("knowledge_stage_input_schema_invalid") from exc


def _validate_attestation(
    *,
    output_payload: dict[str, Any],
    expected_prompt_revision: str,
    expected_schema_sha256: str,
    expected_stage: KnowledgeStage | None = None,
    expected_unit_id: str | None = None,
) -> dict[str, Any]:
    if not _SHA256.fullmatch(expected_prompt_revision):
        raise ValueError("knowledge_prompt_revision_invalid")
    if not _SHA256.fullmatch(expected_schema_sha256):
        raise ValueError("knowledge_schema_sha256_invalid")
    provider_metrics = output_payload.get("provider_metrics")
    if not isinstance(provider_metrics, dict):
        raise ValueError("knowledge_provider_metrics_invalid")
    if provider_metrics.get("prompt_sha256") != expected_prompt_revision:
        raise ValueError("knowledge_prompt_revision_mismatch")
    if provider_metrics.get("knowledge_schema_sha256") != expected_schema_sha256:
        raise ValueError("knowledge_schema_revision_mismatch")
    if provider_metrics.get("unsupported_claim_count") != 0:
        raise ValueError("knowledge_unsupported_claim")
    if expected_stage is not None and provider_metrics.get("knowledge_stage") != expected_stage:
        raise ValueError("knowledge_stage_attestation_mismatch")
    if (
        expected_unit_id is not None
        and provider_metrics.get("knowledge_unit_id") != expected_unit_id
    ):
        raise ValueError("knowledge_unit_attestation_mismatch")
    return provider_metrics


def validate_knowledge_result(
    *,
    output_payload: dict[str, Any],
    input_body: bytes,
    expected_prompt_revision: str,
    expected_schema_sha256: str,
) -> KnowledgeBundle:
    """Admit the legacy single-pass AKMP bundle with complete document evidence."""

    knowledge_input = parse_knowledge_input(input_body)
    _validate_attestation(
        output_payload=output_payload,
        expected_prompt_revision=expected_prompt_revision,
        expected_schema_sha256=expected_schema_sha256,
    )
    bundle_value = output_payload.get("knowledge_bundle")
    if not isinstance(bundle_value, dict):
        raise ValueError("knowledge_bundle_missing")
    try:
        bundle = KnowledgeBundle.model_validate(bundle_value)
    except (ValueError, TypeError) as exc:
        raise ValueError("knowledge_bundle_schema_invalid") from exc
    if bundle.document_id != knowledge_input.document_id or not bundle.notes:
        raise ValueError("knowledge_bundle_scope_invalid")
    _validate_bundle_evidence(
        bundle,
        available={block.block_id for block in knowledge_input.blocks},
    )
    return bundle


def _validate_bundle_evidence(
    bundle: KnowledgeBundle,
    *,
    available: set[str],
) -> None:
    findings = validate_knowledge_evidence(bundle, available)
    if any(finding.severity == FindingSeverity.CRITICAL for finding in findings):
        raise ValueError("knowledge_evidence_invalid")
    for note in bundle.notes:
        note_evidence = set(note.evidence_block_ids)
        if any(not set(claim.source_block_ids).issubset(note_evidence) for claim in note.claims):
            raise ValueError("knowledge_claim_outside_note_evidence")
        if any(
            not set(candidate.source_block_ids).issubset(note_evidence)
            for candidate in note.related_note_candidates
        ):
            raise ValueError("knowledge_link_outside_note_evidence")
    for conflict in bundle.conflicts:
        if not set(conflict.evidence_block_ids).issubset(available):
            raise ValueError("knowledge_conflict_evidence_invalid")


def _validate_stage_a(result: StageAResult, stage_input: StageAInput) -> None:
    expected = {block.block_id for block in stage_input.blocks}
    observed = [block_id for section in result.sections for block_id in section.block_ids]
    if set(observed) != expected or len(observed) != len(set(observed)):
        raise ValueError("knowledge_stage_a_coverage_invalid")
    section_ids = [section.section_id for section in result.sections]
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("knowledge_stage_a_section_ids_invalid")
    if not set(result.classification.evidence_block_ids).issubset(expected):
        raise ValueError("knowledge_stage_a_classification_evidence_invalid")


def _validate_stage_b(result: StageBResult, stage_input: StageBInput) -> None:
    if result.section_id != stage_input.section_id:
        raise ValueError("knowledge_stage_b_section_mismatch")
    available = {fragment.evidence_block_id for fragment in stage_input.fragments}
    bundle = KnowledgeBundle(
        document_id=stage_input.document_id,
        notes=result.notes,
        relations=result.relations,
        conflicts=result.conflicts,
    )
    _validate_bundle_evidence(bundle, available=available)
    local_note_ids = {note.note_id for note in result.notes}
    if any(
        relation.subject not in local_note_ids or relation.object not in local_note_ids
        for relation in result.relations
    ):
        raise ValueError("knowledge_stage_b_relation_scope_invalid")


def _semantic_merge_supported(
    candidates: tuple[StageCCandidateEvidence, ...],
) -> bool:
    if len(candidates) < 2:
        return True
    normalized_values = [
        {
            value.casefold().strip()
            for value in (
                candidate.normalized_title,
                *candidate.aliases,
                *candidate.tags,
            )
            if value.strip()
        }
        for candidate in candidates
    ]
    signatures = [
        {claim.signature_sha256 for claim in candidate.claims} for candidate in candidates
    ]
    tokens = [
        {
            token
            for token in re.findall(
                r"[\w-]+",
                f"{candidate.normalized_title} {candidate.summary}".casefold(),
            )
            if len(token) >= 4
        }
        for candidate in candidates
    ]
    adjacency: dict[int, set[int]] = {index: set() for index in range(len(candidates))}
    for left in range(len(candidates)):
        for right in range(left + 1, len(candidates)):
            overlap = tokens[left] & tokens[right]
            union = tokens[left] | tokens[right]
            supported = bool(
                normalized_values[left] & normalized_values[right]
                or signatures[left] & signatures[right]
                or (len(overlap) >= 2 and union and len(overlap) / len(union) >= 0.5)
            )
            if supported:
                adjacency[left].add(right)
                adjacency[right].add(left)
    reachable = {0}
    pending = [0]
    while pending:
        current = pending.pop()
        for neighbor in adjacency[current] - reachable:
            reachable.add(neighbor)
            pending.append(neighbor)
    return len(reachable) == len(candidates)


def _validate_stage_c(result: StageCResult, stage_input: StageCInput) -> None:
    by_id = {candidate.candidate_id: candidate for candidate in stage_input.candidates}
    expected = set(by_id)
    members = [
        candidate_id for group in result.merge_groups for candidate_id in group.member_candidate_ids
    ]
    if set(members) != expected or len(members) != len(set(members)):
        raise ValueError("knowledge_stage_c_candidate_coverage_invalid")
    canonical = {group.canonical_candidate_id for group in result.merge_groups}
    group_ids = [group.group_id for group in result.merge_groups]
    if len(group_ids) != len(set(group_ids)):
        raise ValueError("knowledge_stage_c_group_ids_invalid")
    for group in result.merge_groups:
        if group.canonical_candidate_id not in group.member_candidate_ids:
            raise ValueError("knowledge_stage_c_canonical_member_invalid")
        if set(group.compared_candidate_ids) != set(group.member_candidate_ids):
            raise ValueError("knowledge_stage_c_comparison_scope_invalid")
        evidence = {
            block_id
            for candidate_id in group.member_candidate_ids
            for block_id in by_id[candidate_id].evidence_block_ids
        }
        if set(group.evidence_block_ids) != evidence:
            raise ValueError("knowledge_stage_c_merge_evidence_invalid")
        if group.reason.casefold().strip() in {
            "duplicate",
            "duplicates",
            "merge",
            "same",
            "similar",
        }:
            raise ValueError("knowledge_stage_c_merge_reason_invalid")
        if len(group.member_candidate_ids) > 1 and not _semantic_merge_supported(
            tuple(by_id[candidate_id] for candidate_id in group.member_candidate_ids)
        ):
            raise ValueError("knowledge_stage_c_merge_semantics_unsupported")
        if group.parent_candidate_id is not None and group.parent_candidate_id not in canonical:
            raise ValueError("knowledge_stage_c_parent_invalid")
        if group.parent_candidate_id == group.canonical_candidate_id:
            raise ValueError("knowledge_stage_c_parent_cycle")
    parents = {
        group.canonical_candidate_id: group.parent_candidate_id for group in result.merge_groups
    }
    for candidate_id in parents:
        seen: set[str] = set()
        current: str | None = candidate_id
        while current is not None:
            if current in seen:
                raise ValueError("knowledge_stage_c_parent_cycle")
            seen.add(current)
            current = parents.get(current)


def _validate_stage_d(result: StageDResult, stage_input: StageDInput) -> None:
    if result.retrieval_status != stage_input.retrieval_status:
        raise ValueError("knowledge_stage_d_retrieval_status_mismatch")
    if stage_input.retrieval_status != "ready" and result.links:
        raise ValueError("knowledge_stage_d_unverified_links_forbidden")
    sources = {
        candidate.candidate_id: set(candidate.evidence_block_ids)
        for candidate in stage_input.source_candidates
    }
    targets = {candidate.stable_id for candidate in stage_input.retrieval_candidates}
    identities: set[tuple[str, str, str]] = set()
    for link in result.links:
        if (
            link.source_candidate_id not in sources
            or link.target_stable_id not in targets
            or not set(link.evidence_block_ids).issubset(sources[link.source_candidate_id])
        ):
            raise ValueError("knowledge_stage_d_link_scope_invalid")
        identity = (
            link.source_candidate_id,
            link.target_stable_id,
            link.relation,
        )
        if identity in identities:
            raise ValueError("knowledge_stage_d_duplicate_link")
        identities.add(identity)


def validate_knowledge_stage_result(
    *,
    output_payload: dict[str, Any],
    input_body: bytes,
    expected_prompt_revision: str,
    expected_schema_sha256: str,
    expected_stage: KnowledgeStage,
    expected_unit_id: str,
) -> KnowledgeStageResult:
    """Admit one exact, bounded A-D result against its immutable input object."""

    stage_input = parse_knowledge_stage_input(input_body)
    if stage_input.stage != expected_stage or stage_input.unit_id != expected_unit_id:
        raise ValueError("knowledge_stage_input_attestation_mismatch")
    _validate_attestation(
        output_payload=output_payload,
        expected_prompt_revision=expected_prompt_revision,
        expected_schema_sha256=expected_schema_sha256,
        expected_stage=expected_stage,
        expected_unit_id=expected_unit_id,
    )
    result_value = output_payload.get("knowledge_stage_result")
    if not isinstance(result_value, dict):
        raise ValueError("knowledge_stage_result_missing")
    try:
        result = _STAGE_RESULT_ADAPTER.validate_python(result_value)
    except (ValueError, TypeError) as exc:
        raise ValueError("knowledge_stage_result_schema_invalid") from exc
    if result.stage != expected_stage or result.unit_id != expected_unit_id:
        raise ValueError("knowledge_stage_result_attestation_mismatch")
    if isinstance(result, StageAResult) and isinstance(stage_input, StageAInput):
        _validate_stage_a(result, stage_input)
    elif isinstance(result, StageBResult) and isinstance(stage_input, StageBInput):
        _validate_stage_b(result, stage_input)
    elif isinstance(result, StageCResult) and isinstance(stage_input, StageCInput):
        _validate_stage_c(result, stage_input)
    elif isinstance(result, StageDResult) and isinstance(stage_input, StageDInput):
        _validate_stage_d(result, stage_input)
    else:
        raise ValueError("knowledge_stage_result_type_mismatch")
    return result


def knowledge_stage_result_counts(
    result: KnowledgeStageResult,
) -> dict[str, int]:
    if isinstance(result, StageAResult):
        return {"section_count": len(result.sections)}
    if isinstance(result, StageBResult):
        return {
            "note_count": len(result.notes),
            "relation_count": len(result.relations),
            "conflict_count": len(result.conflicts),
        }
    if isinstance(result, StageCResult):
        return {"merge_group_count": len(result.merge_groups)}
    return {"link_count": len(result.links)}


__all__ = [
    "KNOWLEDGE_ARTIFACT_CONTRACT",
    "KNOWLEDGE_INPUT_SCHEMA_VERSION",
    "KNOWLEDGE_PIPELINE_ARTIFACT_CONTRACT",
    "KNOWLEDGE_PIPELINE_INPUT_SCHEMA_VERSION",
    "KNOWLEDGE_PIPELINE_RESULT_SCHEMA_VERSION",
    "KnowledgeInputBlock",
    "KnowledgeInputEnvelope",
    "KnowledgeSourceRef",
    "KnowledgeStage",
    "KnowledgeStageInput",
    "KnowledgeStageResult",
    "RetrievalStatus",
    "StageAInput",
    "StageAResult",
    "StageBFragment",
    "StageBInput",
    "StageBResult",
    "StageCCandidateEvidence",
    "StageCClaimDescriptor",
    "StageCEvidenceDescriptor",
    "StageCInput",
    "StageCMergeGroup",
    "StageCResult",
    "StageDAclAttestation",
    "StageDInput",
    "StageDLinkProposal",
    "StageDResult",
    "StageDRetrievalCandidate",
    "StageDSourceCandidate",
    "canonical_json_bytes",
    "knowledge_input_sha256",
    "knowledge_stage_result_counts",
    "parse_knowledge_input",
    "parse_knowledge_stage_input",
    "validate_knowledge_result",
    "validate_knowledge_stage_result",
]
