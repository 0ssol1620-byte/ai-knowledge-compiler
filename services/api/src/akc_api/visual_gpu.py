"""Strict, page-scoped admission contract for visual parser results."""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from typing import Annotated, Any, Literal

from akc_cir import CanonicalTable
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

VISUAL_ARTIFACT_CONTRACT = "akc-visual-page-1.0.0"
VISUAL_RESULT_SCHEMA_VERSION = "1.0"
VISUAL_RASTER_MAX_BYTES = 32 * 1024 * 1024
VISUAL_RASTER_MAX_DIMENSION = 20_000
VISUAL_RASTER_MAX_PIXELS = 40_000_000
VISUAL_PROMPT_REVISION = (
    "sha256:"
    + hashlib.sha256(
        b"akc:paddleocr-vl:page-parse:strict-cir-visual-page-1.0.0"
    ).hexdigest()
)

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$"),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ImageDigest = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]

_RESULT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class VisualSourceRef(_StrictModel):
    document_id: Identifier
    document_version_id: Identifier
    page_index0: Annotated[int, Field(ge=0)]
    page_number1: Annotated[int, Field(ge=1)]
    bbox1000: tuple[
        Annotated[int, Field(ge=0, le=1000)],
        Annotated[int, Field(ge=0, le=1000)],
        Annotated[int, Field(ge=0, le=1000)],
        Annotated[int, Field(ge=0, le=1000)],
    ]

    @model_validator(mode="after")
    def validate_page_and_bbox(self) -> VisualSourceRef:
        if self.page_number1 != self.page_index0 + 1:
            raise ValueError("visual source page number mismatch")
        x1, y1, x2, y2 = self.bbox1000
        if x1 >= x2 or y1 >= y2:
            raise ValueError("visual source bbox must have positive area")
        return self


VisualTextBlockType = Literal[
    "title",
    "heading",
    "paragraph",
    "list",
    "caption",
    "code",
    "quote",
    "footnote",
    "header",
    "footer",
    "page_number",
    "unknown",
]


Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class _VisualBlockBase(_StrictModel):
    block_id: Identifier
    origin: Literal["ocr_extracted"]
    source_refs: Annotated[tuple[VisualSourceRef, ...], Field(min_length=1, max_length=128)]
    confidence: Confidence
    token_confidences: Annotated[
        tuple[Confidence, ...],
        Field(min_length=1, max_length=250_000),
    ]
    quality_flags: Annotated[tuple[Identifier, ...], Field(max_length=256)] = ()


class VisualTextBlock(_VisualBlockBase):
    type: VisualTextBlockType
    text: Annotated[str, Field(min_length=1, max_length=1_000_000)]


class VisualTableBlock(_VisualBlockBase):
    type: Literal["table"]
    text: Annotated[str, Field(max_length=1_000_000)] = ""
    table: CanonicalTable

    @model_validator(mode="after")
    def require_cell_confidence(self) -> VisualTableBlock:
        if any(
            cell.origin != "ocr_extracted" or cell.confidence is None
            for cell in self.table.cells
        ):
            raise ValueError("visual table cells require OCR origin and confidence")
        return self


class VisualFormulaBlock(_VisualBlockBase):
    type: Literal["formula"]
    text: Annotated[str, Field(max_length=1_000_000)] = ""
    formula_latex: Annotated[
        str,
        Field(alias="formulaLatex", min_length=1, max_length=1_000_000),
    ]


class VisualFigureBlock(_VisualBlockBase):
    type: Literal["figure"]
    text: Annotated[str, Field(max_length=1_000_000)] = ""
    image_asset_id: Identifier | None = Field(default=None, alias="imageAssetId")
    crop_provenance: Literal["source_bbox"] | None = Field(
        default=None,
        alias="cropProvenance",
    )

    @model_validator(mode="after")
    def require_image_or_crop(self) -> VisualFigureBlock:
        if self.image_asset_id is None and self.crop_provenance != "source_bbox":
            raise ValueError("visual figure requires imageAssetId or source bbox crop")
        return self


VisualBlock = Annotated[
    VisualTextBlock | VisualTableBlock | VisualFormulaBlock | VisualFigureBlock,
    Field(discriminator="type"),
]
_VISUAL_BLOCK_ADAPTER: TypeAdapter[VisualBlock] = TypeAdapter(VisualBlock)


class VisualVerification(_StrictModel):
    provider: Identifier
    model_revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40,64}$")]
    agreement: Confidence
    numeric_agreement: Confidence | None = None
    table_structure_agreement: Confidence | None = None
    formula_agreement: Confidence | None = None


class VisualPageResult(_StrictModel):
    ok: Literal[True]
    schema_version: Literal["1.0"]
    result_id: str
    job_id: Identifier
    tenant_id: Identifier
    provider: Identifier
    worker_kind: Literal["parser"]
    model_revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40,64}$")]
    runtime_image_digest: ImageDigest
    adapter_version: Identifier
    input_sha256: Sha256
    input_bytes: Annotated[int, Field(gt=0, le=VISUAL_RASTER_MAX_BYTES)]
    idempotency_key: Identifier
    idempotent_replay: bool
    blocks: Annotated[tuple[VisualBlock, ...], Field(min_length=1, max_length=10_000)]
    generated_claims: Annotated[tuple[dict[str, Any], ...], Field(max_length=0)] = ()
    warnings: Annotated[tuple[Identifier, ...], Field(max_length=256)] = ()
    provider_metrics: dict[str, Any]
    provider_raw: dict[str, Any]
    metrics: dict[str, int | float | str | bool | None]
    verification: VisualVerification | None = None

    @field_validator("result_id")
    @classmethod
    def validate_result_id(cls, value: str) -> str:
        if not _RESULT_ID.fullmatch(value):
            raise ValueError("invalid visual result id")
        return value

    @field_validator("provider_raw")
    @classmethod
    def forbid_raw_provider_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value:
            raise ValueError("raw visual provider payload must not cross the durable boundary")
        return value

    @field_validator("provider_metrics", "metrics")
    @classmethod
    def bound_metrics(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 64:
            raise ValueError("visual metrics exceed bounded contract")
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > 80
                or not (
                    item is None
                    or isinstance(item, (str, int, float, bool))
                )
                or (
                    isinstance(item, float)
                    and not math.isfinite(item)
                )
                or (isinstance(item, str) and len(item) > 160)
            ):
                raise ValueError("invalid visual metric")
        return value

    @model_validator(mode="after")
    def unique_blocks(self) -> VisualPageResult:
        identities = [block.block_id for block in self.blocks]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate visual block id")
        if sum(len(visual_block_text(block)) for block in self.blocks) > 1_000_000:
            raise ValueError("visual result text exceeds bounded page contract")
        if sum(len(block.token_confidences) for block in self.blocks) > 250_000:
            raise ValueError("visual result token confidence evidence exceeds bound")
        diagnostic_characters = sum(len(item) for item in self.warnings)
        diagnostic_characters += sum(
            len(item)
            for block in self.blocks
            for item in block.quality_flags
        )
        for metrics in (self.provider_metrics, self.metrics):
            diagnostic_characters += sum(
                len(key) + (len(item) if isinstance(item, str) else 0)
                for key, item in metrics.items()
            )
        if diagnostic_characters > 65_536:
            raise ValueError("visual result diagnostic evidence exceeds bound")
        return self


def visual_block_from_payload(value: dict[str, Any]) -> VisualBlock:
    """Parse one strict discriminated visual block for adapter/unit boundaries."""

    return _VISUAL_BLOCK_ADAPTER.validate_python(value)


def visual_block_text(block: VisualBlock) -> str:
    if isinstance(block, VisualFormulaBlock):
        return block.formula_latex
    if isinstance(block, VisualTableBlock):
        if block.text:
            return block.text
        ordered = sorted(
            block.table.cells,
            key=lambda cell: (cell.row_index0, cell.column_index0, cell.id),
        )
        return "\n".join(
            cell.normalized_text or cell.raw_text
            for cell in ordered
            if cell.normalized_text or cell.raw_text
        )
    return block.text


def visual_block_source_refs(
    block: VisualBlock,
) -> tuple[VisualSourceRef, ...]:
    return block.source_refs


def validate_visual_result(
    *,
    output_payload: dict[str, Any],
    expected_job_id: uuid.UUID,
    expected_tenant_id: uuid.UUID,
    expected_document_id: uuid.UUID,
    expected_document_version_id: str,
    expected_page_index0: int,
    expected_provider: str,
    expected_model_revision: str,
    expected_runtime_image_digest: str,
    expected_adapter_version: str,
    expected_input_sha256: str,
    expected_input_bytes: int,
    expected_idempotency_key: str,
    expected_image_asset_id: uuid.UUID | None = None,
) -> VisualPageResult:
    result = VisualPageResult.model_validate(output_payload)
    exact = {
        "job_id": str(expected_job_id),
        "tenant_id": str(expected_tenant_id),
        "provider": expected_provider,
        "model_revision": expected_model_revision,
        "runtime_image_digest": expected_runtime_image_digest,
        "adapter_version": expected_adapter_version,
        "input_sha256": f"sha256:{expected_input_sha256.removeprefix('sha256:')}",
        "input_bytes": expected_input_bytes,
        "idempotency_key": expected_idempotency_key,
    }
    for field, expected in exact.items():
        if getattr(result, field) != expected:
            raise ValueError(f"visual result {field} attestation mismatch")
    expected_document = str(expected_document_id)
    expected_page_number = expected_page_index0 + 1

    def require_source_scope(source_ref: Any) -> None:
        if (
            str(source_ref.document_id) != expected_document
            or str(source_ref.document_version_id) != expected_document_version_id
            or source_ref.page_index0 != expected_page_index0
            or source_ref.page_number1 != expected_page_number
        ):
            raise ValueError("visual result source/page attestation mismatch")

    for block in result.blocks:
        for source_ref in block.source_refs:
            require_source_scope(source_ref)
        if isinstance(block, VisualTableBlock):
            for table_source_ref in block.table.source_refs:
                require_source_scope(table_source_ref)
            for cell in block.table.cells:
                for cell_source_ref in cell.source_refs:
                    require_source_scope(cell_source_ref)
        if (
            isinstance(block, VisualFigureBlock)
            and block.image_asset_id is not None
            and (
                expected_image_asset_id is None
                or block.image_asset_id != str(expected_image_asset_id)
            )
        ):
            raise ValueError("visual result figure image asset attestation mismatch")
    if result.verification is not None and (
        result.verification.provider == result.provider
        and result.verification.model_revision == result.model_revision
    ):
        raise ValueError("visual verifier must be independent from the primary result")
    return result


def visual_attestation(
    result: VisualPageResult,
    *,
    page_id: uuid.UUID,
    page_index0: int,
    page_width_px: int,
    page_height_px: int,
    input_size_bytes: int,
) -> dict[str, int | str]:
    nested_source_ref_count = 0
    for block in result.blocks:
        nested_source_ref_count += len(block.source_refs)
        if isinstance(block, VisualTableBlock):
            nested_source_ref_count += len(block.table.source_refs)
            nested_source_ref_count += sum(
                len(cell.source_refs) for cell in block.table.cells
            )
    return {
        "artifact_contract": VISUAL_ARTIFACT_CONTRACT,
        "schema_version": VISUAL_RESULT_SCHEMA_VERSION,
        "page_id": str(page_id),
        "page_index0": page_index0,
        "page_width_px": page_width_px,
        "page_height_px": page_height_px,
        "input_size_bytes": input_size_bytes,
        "block_count": len(result.blocks),
        "source_ref_count": nested_source_ref_count,
        "confidence_count": sum(
            1 + len(block.token_confidences) for block in result.blocks
        ),
        "verification_present": int(result.verification is not None),
    }
