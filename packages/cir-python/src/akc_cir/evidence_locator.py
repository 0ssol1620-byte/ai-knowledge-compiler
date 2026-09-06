"""EvidenceLocator v2 — the source-agnostic evidence anchor (blueprint §11).

The legacy page+bbox evidence of the current product is exactly the ``pdf``
variant, so this module is a **sibling** of :class:`akc_cir.models.SourceRef`,
never a replacement: ``CanonicalKnowledgeObject.hash`` digests ``source_refs``,
and adding a field there would re-hash every knowledge object already stored.

The wire shape is frozen in ``packages/contracts/schemas/evidence-locator.v2.schema.json``
(a verbatim copy of the campaign contract artifact). This file is its typed
transliteration: camelCase on the wire through the shared alias generator,
snake_case in Python, ``extra="forbid"`` and frozen like every other contract.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self

from pydantic import Field, RootModel, StringConstraints, model_validator

from .base import ContractModel, Sha256, canonical_json, sha256_digest
from .identity import evidence_id
from .models import BBox1000, SourceRef

__all__ = [
    "EVIDENCE_LOCATOR_SCHEMA",
    "AnyEvidenceLocator",
    "ApiLocator",
    "BaseEvidenceLocator",
    "CadLocator",
    "CodeLocator",
    "DatabaseLocator",
    "DocxLocator",
    "EmailLocator",
    "EvidenceLocator",
    "EvidenceLocatorUnion",
    "ImageLocator",
    "JsonLocator",
    "LineColSpan",
    "LocatorKind",
    "MediaLocator",
    "OffsetRange",
    "PdfLocator",
    "PptxLocator",
    "XlsxLocator",
    "XmlLocator",
    "anchor_id",
    "from_legacy",
    "locator_anchor_id",
    "parse_locator",
]

EVIDENCE_LOCATOR_SCHEMA: Final = "tavonel.evidence_locator.v2"


class LocatorKind(StrEnum):
    """Frozen vocabulary — ``contract/enums.v1.json`` ``LocatorKind``."""

    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    EMAIL = "email"
    JSON = "json"
    XML = "xml"
    CODE = "code"
    CAD = "cad"
    MEDIA = "media"
    DATABASE = "database"
    API = "api"


# Mirrors the frozen schema's $defs so a locator that validates here also
# validates there. Deliberately stricter in two places the schema documents as
# "enforced by code": BBox1000 positive area, and the media time ordering that
# SourceRef already enforces for the same pair of fields.
LocatorIdentifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
]
Excerpt = Annotated[str, StringConstraints(max_length=2000)]
A1Cell = Annotated[str, StringConstraints(pattern=r"^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}$")]
A1Range = Annotated[
    str,
    StringConstraints(pattern=r"^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}:\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}$"),
]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,64}$")]
JsonPointer = Annotated[str, StringConstraints(pattern=r"^(/([^/~]|~0|~1)*)*$")]
NonEmptyText = Annotated[str, StringConstraints(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveIndex = Annotated[int, Field(ge=1)]


class OffsetRange(ContractModel):
    """Codepoint offsets into a body of text."""

    start: NonNegativeInt
    end: NonNegativeInt


class LineColSpan(ContractModel):
    """1-based line, 0-based column span in a source file."""

    start_line: PositiveIndex
    start_col: NonNegativeInt
    end_line: PositiveIndex
    end_col: NonNegativeInt


class BaseEvidenceLocator(ContractModel):
    """Fields every locator carries (blueprint §11 ``BaseEvidenceLocator``)."""

    schema_version: Literal["tavonel.evidence_locator.v2"]
    locator_id: LocatorIdentifier
    source_version_id: LocatorIdentifier
    representation_id: LocatorIdentifier
    content_digest: Sha256 | None = None
    excerpt: Excerpt | None = None

    # The frozen schema types every optional as a string/integer with no null in
    # the union, so an absent field must be *omitted*, not serialized as null.
    # Defaulting the dump here rather than through a ``model_serializer`` is
    # deliberate: a wrap serializer collapses
    # ``model_json_schema(mode="serialization")`` to a bare object, and that
    # schema is what generates the TypeScript union.
    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        kwargs.setdefault("exclude_none", True)
        return super().model_dump_json(**kwargs)


class PdfLocator(BaseEvidenceLocator):
    locator_kind: Literal["pdf"]
    page: PositiveIndex
    bbox1000: BBox1000
    object_id: str | None = None

    def to_legacy(self, *, document_id: str) -> SourceRef:
        """The legacy :class:`SourceRef` this locator was built from.

        ``document_id`` is a parameter because the v2 union deliberately does
        not carry one: a locator binds to a SourceVersion, and the document ->
        source alias lives on ``Source``, not on the evidence anchor.
        """
        return SourceRef(
            document_id=document_id,
            document_version_id=self.source_version_id,
            page_index0=self.page - 1,
            page_number1=self.page,
            bbox1000=self.bbox1000,
            native_object_id=self.object_id,
        )


class ImageLocator(BaseEvidenceLocator):
    locator_kind: Literal["image"]
    bbox1000: BBox1000
    image_id: str | None = None


class DocxLocator(BaseEvidenceLocator):
    locator_kind: Literal["docx"]
    section_id: str | None = None
    paragraph_id: str | None = None
    run_id: str | None = None
    table_id: str | None = None
    cell_id: str | None = None
    comment_id: str | None = None
    footnote_id: str | None = None

    @model_validator(mode="after")
    def require_anchor(self) -> Self:
        if not (
            self.paragraph_id
            or (self.table_id and self.cell_id)
            or self.comment_id
            or self.footnote_id
        ):
            raise ValueError(
                "docx locator needs a paragraphId, a tableId+cellId pair, "
                "a commentId or a footnoteId"
            )
        return self


class XlsxLocator(BaseEvidenceLocator):
    locator_kind: Literal["xlsx"]
    workbook: str | None = None
    sheet: NonEmptyText
    cell: A1Cell | None = None
    range: A1Range | None = None
    formula: str | None = None
    named_range: str | None = None
    table_id: str | None = None
    chart_id: str | None = None

    @model_validator(mode="after")
    def require_anchor(self) -> Self:
        if not (self.cell or self.range or self.named_range or self.table_id or self.chart_id):
            raise ValueError("xlsx locator needs a cell, range, namedRange, tableId or chartId")
        return self


class PptxLocator(BaseEvidenceLocator):
    locator_kind: Literal["pptx"]
    slide_number1: PositiveIndex | None = None
    slide_id: str | None = None
    shape_id: str | None = None
    chart_id: str | None = None
    series_id: str | None = None
    text_range: OffsetRange | None = None

    @model_validator(mode="after")
    def require_anchor(self) -> Self:
        if self.slide_id is None and self.slide_number1 is None:
            raise ValueError("pptx locator needs a slideId or a slideNumber1")
        return self


class EmailLocator(BaseEvidenceLocator):
    locator_kind: Literal["email"]
    message_id: NonEmptyText
    thread_id: str | None = None
    mime_part: str | None = None
    body_offset: OffsetRange | None = None
    attachment_id: str | None = None


class JsonLocator(BaseEvidenceLocator):
    locator_kind: Literal["json"]
    pointer: JsonPointer


class XmlLocator(BaseEvidenceLocator):
    locator_kind: Literal["xml"]
    xpath: NonEmptyText
    node_id: str | None = None


class CodeLocator(BaseEvidenceLocator):
    locator_kind: Literal["code"]
    repository: str | None = None
    commit_sha: CommitSha
    file_path: NonEmptyText
    language: str | None = None
    symbol_id: str | None = None
    span: LineColSpan


class CadLocator(BaseEvidenceLocator):
    locator_kind: Literal["cad"]
    model_id: NonEmptyText
    entity_id: NonEmptyText
    layer: str | None = None
    assembly_path: tuple[str, ...] | None = None
    geometry_ref: str | None = None
    view_locator: str | None = None


class MediaLocator(BaseEvidenceLocator):
    locator_kind: Literal["media"]
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    speaker_id: str | None = None
    frame_number: NonNegativeInt | None = None
    track_id: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.start_ms > self.end_ms:
            raise ValueError("startMs must not exceed endMs")
        return self


class DatabaseLocator(BaseEvidenceLocator):
    locator_kind: Literal["database"]
    datasource_version: NonEmptyText
    table: NonEmptyText
    primary_key: dict[str, Any]
    field_path: str | None = None
    query_snapshot_digest: Sha256 | None = None

    @model_validator(mode="after")
    def require_primary_key(self) -> Self:
        if not self.primary_key:
            raise ValueError("database locator needs at least one primary key column")
        return self


class ApiLocator(BaseEvidenceLocator):
    locator_kind: Literal["api"]
    endpoint: NonEmptyText
    response_digest: Sha256
    field_path: str | None = None
    fetched_at: str | None = None


AnyEvidenceLocator = (
    PdfLocator
    | ImageLocator
    | DocxLocator
    | XlsxLocator
    | PptxLocator
    | EmailLocator
    | JsonLocator
    | XmlLocator
    | CodeLocator
    | CadLocator
    | MediaLocator
    | DatabaseLocator
    | ApiLocator
)
EvidenceLocator = Annotated[AnyEvidenceLocator, Field(discriminator="locator_kind")]


class EvidenceLocatorUnion(RootModel[EvidenceLocator]):
    """Schema/TS carrier for the union. Registered in ``akc_cir.schema``."""

    def model_dump(self, **kwargs: Any) -> Any:
        return self.root.model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        return self.root.model_dump_json(**kwargs)


def parse_locator(payload: Any) -> AnyEvidenceLocator:
    """Validate an untrusted wire payload into one locator variant."""
    return EvidenceLocatorUnion.model_validate(payload).root


def locator_anchor_id(locator: AnyEvidenceLocator) -> str:
    """Stable id for the anchored region, independent of id and excerpt.

    ``identity.evidence_id()`` (Protected Core) requires ``page_number1 >= 1``
    and so cannot express an XLSX cell or a JSON pointer. This is the
    non-paginated sibling; ``identity.py`` is untouched.
    """
    payload = locator.model_dump(mode="json", by_alias=True, exclude_none=True)
    payload.pop("locatorId", None)
    payload.pop("excerpt", None)
    return sha256_digest(canonical_json(payload))


def anchor_id(locator: AnyEvidenceLocator) -> str:
    """The anchor identity of one locator. **The locator kind decides** (§8.1).

    ``pdf`` is the one kind the product already has an evidence identity for,
    so it takes Protected Core's :func:`akc_cir.identity.evidence_id`: a v2
    ``pdf`` locator and the legacy ``SourceRef`` it wraps carry the *same*
    identity, which is the stored-identity compatibility founder resolution
    B-3 requires. Every other kind is non-paginated and takes
    :func:`locator_anchor_id`. This is decided, not proposed.

    ``evidence_id`` refuses a document version that is not a ``dv_`` id, and
    that refusal is passed through rather than caught: falling back to the
    path digest would issue a *second* identity for the same pdf anchor, which
    is the collision class the convention exists to prevent.

    The wire field ``locatorId`` is a record identifier, not this: it must be
    derivable for every ``sourceVersionId`` shape, including the campaign's
    ``documents.id`` alias, so :func:`from_legacy` defaults it from
    :func:`locator_anchor_id`. See ``docs/architecture/evidence-locator-v2.md``.
    """
    if isinstance(locator, PdfLocator):
        return evidence_id(
            document_version=locator.source_version_id,
            page_number1=locator.page,
            bbox1000=locator.bbox1000.as_tuple(),
        )
    return locator_anchor_id(locator)


def from_legacy(
    source_ref: SourceRef,
    *,
    representation_id: str,
    locator_id: str | None = None,
) -> PdfLocator:
    """Wrap today's page+bbox evidence as the ``pdf`` variant (blueprint §62 step 2).

    ``document_version_id -> sourceVersionId`` is the identity alias this
    campaign uses, mirroring the site's ``sourceId = documents.id``.
    """
    if source_ref.bbox1000 is None:
        raise ValueError(
            "a pdf locator requires bbox1000; a SourceRef without one cannot be "
            "wrapped and no box is invented to fill the gap"
        )
    # The pdf variant has no field for an image asset or a time range, and the
    # native parsers do emit those on FIGURE and media blocks. Dropping them
    # would make to_legacy() return something that is not the input, so the
    # wrap is refused instead: losing evidence silently is not a fallback.
    unmappable = [
        name
        for name in ("image_asset_id", "time_start_ms", "time_end_ms")
        if getattr(source_ref, name) is not None
    ]
    if unmappable:
        raise ValueError(
            f"the pdf locator variant carries no {', '.join(unmappable)}; wrapping this "
            "SourceRef would drop evidence, so it is refused rather than round-tripped lossily"
        )
    fields: dict[str, Any] = {
        "schema_version": EVIDENCE_LOCATOR_SCHEMA,
        "locator_kind": "pdf",
        "locator_id": "pending",
        "source_version_id": source_ref.document_version_id,
        "representation_id": representation_id,
        "page": source_ref.page_number1,
        "bbox1000": source_ref.bbox1000,
        "object_id": source_ref.native_object_id,
    }
    draft = PdfLocator(**fields)
    # Rebuilt rather than model_copy(update=...): model_copy skips validation,
    # so a caller-supplied locator_id would bypass LocatorIdentifier entirely.
    fields["locator_id"] = locator_anchor_id(draft) if locator_id is None else locator_id
    return PdfLocator(**fields)
