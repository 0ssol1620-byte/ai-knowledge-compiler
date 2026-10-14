"""Strict wire contracts for the Product-owned compile control plane."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Annotated, Literal

from akc_cir.base import ContractModel, Sha256
from akc_cir.models import BBox1000, BlockType
from pydantic import Field, StringConstraints, field_validator, model_validator

PRODUCT_CORE_REQUEST_SCHEMA = "tavonel.product_core.compile_request.v2"
PRODUCT_CORE_RESPONSE_SCHEMA = "tavonel.product_core.compile_response.v2"

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")]
BlueprintId = Literal[
    "corporate-filings",
    "course-materials",
    "generic-mixed-corpus",
    "legal-contracts",
    "personal-knowledge",
    "research-library",
    "technical-documentation",
]


class OcrRecognitionCandidate(ContractModel):
    engine_id: Literal["general-ppocrv6", "korean-ppocrv5"]
    model_sha256: Sha256
    text: Annotated[str, Field(min_length=1, max_length=2_000)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    polygon: Annotated[tuple[tuple[float, float], ...], Field(min_length=3, max_length=8)]

    @model_validator(mode="after")
    def exact_model_and_polygon(self) -> OcrRecognitionCandidate:
        models = {
            "general-ppocrv6": "sha256:6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
            "korean-ppocrv5": "sha256:cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
        }
        if self.model_sha256 != models[self.engine_id]:
            raise ValueError("OCR engine must bind to its exact reviewed model")
        if any(not isfinite(value) or value < 0 for point in self.polygon for value in point):
            raise ValueError("OCR polygon must contain finite nonnegative raster coordinates")
        return self


class OcrRecognitionConflict(ContractModel):
    source_sha256: Sha256
    region_id: Identifier
    page_index0: Annotated[int, Field(ge=0)]
    bbox1000: BBox1000
    candidates: tuple[OcrRecognitionCandidate, OcrRecognitionCandidate]

    @model_validator(mode="after")
    def distinct_raw_candidates(self) -> OcrRecognitionConflict:
        first, second = self.candidates
        if first.engine_id == second.engine_id or first.text == second.text:
            raise ValueError("OCR conflict requires distinct engines and raw texts")
        return self


class ProductCoreRegion(ContractModel):
    region_id: Identifier
    page_index0: Annotated[int, Field(ge=0)]
    page_number1: Annotated[int, Field(ge=1)]
    order: Annotated[int, Field(ge=0)]
    block_type: BlockType = BlockType.PARAGRAPH
    text: Annotated[str, Field(min_length=1, max_length=200_000)]
    bbox1000: BBox1000 | None = None
    native_object_id: Identifier | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    authority: Annotated[str, Field(min_length=1, max_length=80)] = "informal"
    # Preserve v2 document digests when no v3 evidence is present.
    recognition_conflict: OcrRecognitionConflict | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def bind_page_number(self) -> ProductCoreRegion:
        if self.page_number1 != self.page_index0 + 1:
            raise ValueError("pageNumber1 must equal pageIndex0 + 1")
        return self


class ProductCoreDocument(ContractModel):
    native_id: Identifier
    connector_type: Identifier
    source_id: Identifier | None = None
    source_version_id: Identifier | None = None
    immutable_object_key: Annotated[str, Field(min_length=1, max_length=1_024)]
    ocr_object_key: Annotated[str, Field(min_length=1, max_length=1_024)]
    content_sha256: Sha256
    title: Annotated[str, Field(min_length=1, max_length=500)]
    source_filename: Annotated[str, Field(min_length=1, max_length=500)]
    page_count: Annotated[int, Field(ge=1, le=100_000)]
    reader_revision: Sha256 | None = Field(default=None, exclude_if=lambda value: value is None)
    reader_binding_sha256: Sha256 | None = Field(default=None, exclude_if=lambda value: value is None)
    recognition_conflict_count: Annotated[int, Field(ge=0, le=128)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    regions: Annotated[tuple[ProductCoreRegion, ...], Field(min_length=1, max_length=100_000)]

    @field_validator("immutable_object_key", "ocr_object_key")
    @classmethod
    def safe_object_key(cls, value: str) -> str:
        if "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
            raise ValueError("object key must be a safe relative path")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("object key contains control characters")
        return value

    @model_validator(mode="after")
    def validate_regions(self) -> ProductCoreDocument:
        if len({self.reader_revision is None, self.reader_binding_sha256 is None,
                self.recognition_conflict_count is None}) != 1:
            raise ValueError("OCR reader revision, completed-read binding and count must travel together")
        conflict_count = sum(region.recognition_conflict is not None for region in self.regions)
        if conflict_count > 128 or (self.recognition_conflict_count is not None and
                                    self.recognition_conflict_count != conflict_count):
            raise ValueError("too many OCR recognition conflicts")
        if len({region.region_id for region in self.regions}) != len(self.regions):
            raise ValueError("region IDs must be unique within a document")
        anchors = {region.native_object_id or region.region_id for region in self.regions}
        if len(anchors) != len(self.regions):
            raise ValueError("effective region anchors must be unique within a document")
        if len({region.order for region in self.regions}) != len(self.regions):
            raise ValueError("region order values must be unique within a document")
        if max(region.page_number1 for region in self.regions) > self.page_count:
            raise ValueError("region page exceeds pageCount")
        for region in self.regions:
            conflict = region.recognition_conflict
            if conflict is None:
                continue
            if self.reader_revision is None or self.reader_binding_sha256 is None or self.recognition_conflict_count is None:
                raise ValueError("OCR v3 conflict requires qualified completed-read provenance")
            if (
                conflict.source_sha256 != self.content_sha256
                or conflict.region_id != region.region_id
                or conflict.page_index0 != region.page_index0
                or conflict.bbox1000 != region.bbox1000
                or not any(
                    region.text == candidate.text and region.confidence == candidate.confidence
                    for candidate in conflict.candidates
                )
            ):
                raise ValueError("OCR conflict must bind to the unchanged source region")
        return self


class PreviousUnit(ContractModel):
    logical_id: Identifier
    source_id: Identifier
    source_version_id: Identifier
    source_content_sha256: Sha256
    text: Annotated[str, Field(min_length=1, max_length=200_000)]
    document_path: tuple[str, ...]
    anchor: str
    neighbour_anchors: tuple[str, ...] = ()
    evidence_id: Identifier
    page_number1: Annotated[int, Field(ge=1)]
    authority: str | None = None
    identity_state: Literal["matched", "new", "unresolved"]


class PreviousWorldSnapshot(ContractModel):
    world_state_id: Identifier
    manifest_digest: Sha256
    units: Annotated[tuple[PreviousUnit, ...], Field(max_length=100_000)] = ()
    artifact_hashes: dict[str, Sha256] = Field(default_factory=dict)


class ProductCoreRoute(ContractModel):
    operation_class: Literal["initial_compile", "incremental_recompile", "verification_oracle"]
    quality_requirement: Literal["standard", "high_assurance"]
    max_cost_credits: Annotated[int, Field(ge=0, le=10_000)]
    max_latency_ms: Annotated[int, Field(ge=1_000, le=900_000)]
    privacy_policy: Literal["foundation_synthetic_only", "approved_customer_data"]


class ProductCoreCompileRequest(ContractModel):
    schema_version: Literal["tavonel.product_core.compile_request.v2"] = (
        "tavonel.product_core.compile_request.v2"
    )
    request_id: Identifier
    idempotency_key: Identifier
    tenant_id: Identifier
    workspace_id: Identifier
    collection_id: Identifier
    requested_at: datetime
    requested_blueprint: BlueprintId | None = None
    route: ProductCoreRoute
    documents: Annotated[tuple[ProductCoreDocument, ...], Field(min_length=1, max_length=500)]
    previous_active_world: PreviousWorldSnapshot | None = None

    @field_validator("requested_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requestedAt must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_scope_and_operation(self) -> ProductCoreCompileRequest:
        native_keys = {(document.connector_type, document.native_id) for document in self.documents}
        if len(native_keys) != len(self.documents):
            raise ValueError("connector/native IDs must be unique within a compile request")
        supplied_source_ids = [
            document.source_id for document in self.documents if document.source_id is not None
        ]
        if len(set(supplied_source_ids)) != len(supplied_source_ids):
            raise ValueError("supplied source IDs must be unique within a compile request")
        if self.route.operation_class == "initial_compile" and self.previous_active_world:
            raise ValueError("initial compile cannot carry a previous active world")
        if self.route.operation_class != "initial_compile" and not self.previous_active_world:
            raise ValueError("incremental and oracle compiles require a previous active world")
        return self


class CandidateArtifact(ContractModel):
    artifact_id: Identifier
    kind: Literal[
        "canonical_ir",
        "knowledge_model",
        "dependency_graph",
        "retrieval_index",
        "candidate_world",
    ]
    content_sha256: Sha256
    byte_length: Annotated[int, Field(ge=0)]


class CandidatePackageFile(ContractModel):
    path: Annotated[str, Field(min_length=1, max_length=240)]
    media_type: Annotated[str, Field(min_length=1, max_length=120)]
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Sha256
    content: Annotated[str, StringConstraints(strip_whitespace=False)]


class CandidatePackage(ContractModel):
    roots: tuple[str, ...]
    files: tuple[CandidatePackageFile, ...]
    signature_status: Literal["external_signer_required"] = "external_signer_required"


class ProductCoreReceipt(ContractModel):
    request_id: Identifier
    input_sha256: Sha256
    output_sha256: Sha256
    core_release_digest: Sha256
    matching_policy: Literal["legacy"] = "legacy"
    candidate_promotion: Literal[False] = False
    equivalence: Literal["passed", "failed", "not_run"]
    total_artifacts: Annotated[int, Field(ge=0)]
    rebuilt_artifacts: Annotated[int, Field(ge=0)]
    work_avoided_artifacts: Annotated[int, Field(ge=0)]


class CandidateWorld(ContractModel):
    world_state_id: Identifier
    parent_world_state_id: Identifier | None = None
    manifest_digest: Sha256
    lifecycle: Literal["candidate", "review_required", "rejected"]
    canonical_documents: tuple[dict[str, object], ...]
    canonical_knowledge_model: dict[str, object]
    units: tuple[PreviousUnit, ...]
    artifact_hashes: dict[str, Sha256]
    directory_plan: tuple[dict[str, object], ...]
    package: CandidatePackage
    validation: dict[str, object]
    diff: dict[str, object]
    impact: dict[str, object]
    recompilation: dict[str, object]
    review_reasons: tuple[str, ...] = ()


class ProductCoreCompileResponse(ContractModel):
    schema_version: Literal["tavonel.product_core.compile_response.v2"] = (
        "tavonel.product_core.compile_response.v2"
    )
    status: Literal["completed", "review_required", "rejected"]
    runtime: Literal["tavonel-python-core-v2"] = "tavonel-python-core-v2"
    candidate: CandidateWorld
    artifacts: tuple[CandidateArtifact, ...]
    receipt: ProductCoreReceipt
