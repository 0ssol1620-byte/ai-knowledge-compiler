"""Offline coordinate facts with unresolved headers and unevaluated formulas."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Annotated, Any, Literal

from akc_cir.base import ContractModel, Sha256, StableId, canonical_json, sha256_digest
from akc_cir.models import CanonicalCell, CanonicalDocument, CellValueType, SourceRef, VerbatimText
from pydantic import Field, field_validator, model_validator

from .contracts import Identifier
from .native_cir import NativeCIRRequest, _preflight, parse_native_request

NATIVE_FACTS_SCHEMA = "tavonel.product_core.native_facts_draft.v1"
NATIVE_FACTS_PROJECTION = "tavonel.native_cell_facts.v1"
MAX_NATIVE_FACTS_OUTPUT_BYTES = 32 * 1024 * 1024
_CELL_ADDRESS = re.compile(r"^xlsx/sheet/[0-9]{4}/cell/[A-Z]+([1-9][0-9]*)$")


class SourceCellValue(ContractModel):
    kind: Literal["source_cell_value"] = "source_cell_value"
    value: VerbatimText


class FormulaExpression(ContractModel):
    kind: Literal["formula_expression"] = "formula_expression"
    evaluated: Literal[False] = False
    expression_status: Literal["available", "unavailable"]
    expression: VerbatimText | None = None
    cached_text_informational: VerbatimText | None = None


class NativeCellFact(ContractModel):
    fact_id: Identifier
    evidence_id: Identifier
    cell_id: StableId
    native_address: StableId
    absolute_row1: Annotated[int, Field(ge=1)]
    row_index0: Annotated[int, Field(ge=0)]
    column_index0: Annotated[int, Field(ge=0)]
    row_span: Annotated[int, Field(ge=1)]
    column_span: Annotated[int, Field(ge=1)]
    value_type: CellValueType | None = None
    raw_text: VerbatimText
    normalized_text: VerbatimText
    observation: Annotated[SourceCellValue | FormulaExpression, Field(discriminator="kind")]


class NativeFactRow(ContractModel):
    row_index0: Annotated[int, Field(ge=0)]
    absolute_row1: Annotated[int, Field(ge=1)]
    cells: tuple[NativeCellFact, ...]


class NativeFactTable(ContractModel):
    table_id: StableId
    block_id: StableId
    block_content_sha256: Sha256
    source_refs: tuple[SourceRef, ...]
    producer_header_row_count: Annotated[int, Field(ge=0)]
    header_status: Literal["unknown", "ambiguous"]
    header_bindings: tuple[()] = ()
    review_reasons: tuple[str, ...]
    rows: tuple[NativeFactRow, ...]


class NativeFactDocument(ContractModel):
    native_id: Identifier
    connector_type: Identifier
    source_id: Identifier
    source_version_id: Identifier
    immutable_object_key: str
    cir_object_key: str
    content_sha256: Sha256
    cir_sha256: Sha256
    processing_receipt_id: Identifier
    tables: tuple[NativeFactTable, ...]


class NativeCellEvidence(ContractModel):
    evidence_id: Identifier
    fact_id: Identifier
    document_id: StableId
    document_version_id: StableId
    cir_sha256: Sha256
    cell_id: StableId
    table_id: StableId
    block_id: StableId
    block_content_sha256: Sha256
    source_refs: tuple[SourceRef, ...]


def _observation(cell: CanonicalCell) -> SourceCellValue | FormulaExpression:
    formula_flagged = any("formula" in flag for flag in cell.quality_flags)
    if cell.formula is None and not formula_flagged:
        return SourceCellValue(value=cell.raw_text)
    expression = cell.formula
    if (
        expression is None
        and "formula_text_unavailable" not in cell.quality_flags
        and cell.raw_text.startswith("=")
    ):
        expression = cell.raw_text
    cache = None
    if (
        "formula_cached_value_missing" not in cell.quality_flags
        and cell.value_type is not None
        and cell.normalized_text != expression
    ):
        cache = cell.normalized_text
    return FormulaExpression(
        expression_status="available" if expression is not None else "unavailable",
        expression=expression,
        cached_text_informational=cache,
    )


def _project(
    request: NativeCIRRequest,
) -> tuple[tuple[NativeFactDocument, ...], tuple[NativeCellEvidence, ...], tuple[str, ...]]:
    documents = []
    evidence = []
    reasons = {"NATIVE_PROCESSING_APPROVAL_UNBOUND", "NATIVE_TABLE_SEMANTICS_UNRESOLVED"}
    for envelope in sorted(request.documents, key=lambda item: item.source_id):
        tables = []
        blocks = sorted(
            (block for block in envelope.canonical_document.blocks if block.table is not None),
            key=lambda block: (block.source_refs[0].page_index0, block.order, block.id),
        )
        for block in blocks:
            table = block.table
            assert table is not None  # Filtered above; validated CIR remains authoritative.
            table_reasons = {"NATIVE_HEADERS_UNVERIFIED"}
            header_status = "unknown"
            if table.header_row_count == 0:
                table_reasons.add("NATIVE_HEADER_ROW_NOT_DECLARED")
            elif "header_row_inferred" in (*table.quality_flags, *block.quality_flags):
                table_reasons.add("NATIVE_HEADER_ROW_INFERRED")
            else:
                candidates = [
                    cell for cell in table.cells if cell.row_index0 < table.header_row_count
                ]
                labels = [cell.normalized_text for cell in candidates]
                if (
                    any(not label.strip() for label in labels)
                    or len(labels) != len(set(labels))
                    or any(cell.row_span > 1 or cell.column_span > 1 for cell in candidates)
                ):
                    header_status = "ambiguous"
                    table_reasons.add("NATIVE_HEADER_CANDIDATES_AMBIGUOUS")
            rows: defaultdict[int, list[NativeCellFact]] = defaultdict(list)
            for cell in sorted(
                table.cells, key=lambda item: (item.row_index0, item.column_index0, item.id)
            ):
                ref = cell.source_refs[0]
                address = ref.native_object_id or ""
                match = _CELL_ADDRESS.fullmatch(address)
                if match is None:
                    raise ValueError("native cell address missing")
                digest = sha256_digest(
                    canonical_json(
                        {
                            "projectionVersion": NATIVE_FACTS_PROJECTION,
                            "tenantId": request.tenant_id,
                            "workspaceId": request.workspace_id,
                            "collectionId": request.collection_id,
                            "documentId": envelope.source_id,
                            "documentVersionId": envelope.source_version_id,
                            "cirSha256": envelope.cir_sha256,
                            "blockId": block.id,
                            "blockContentSha256": block.content_hash,
                            "tableId": table.id,
                            "cellId": cell.id,
                            "sourceRefs": [
                                item.model_dump(mode="json", by_alias=True, exclude_none=True)
                                for item in cell.source_refs
                            ],
                        }
                    )
                )[7:]
                fact_id, evidence_id = f"native_fact_{digest}", f"native_evidence_{digest}"
                observation = _observation(cell)
                if isinstance(observation, FormulaExpression):
                    table_reasons.add("NATIVE_FORMULA_NOT_OBSERVED")
                    if observation.expression_status == "unavailable":
                        table_reasons.add("NATIVE_FORMULA_EXPRESSION_UNAVAILABLE")
                rows[cell.row_index0].append(
                    NativeCellFact(
                        fact_id=fact_id,
                        evidence_id=evidence_id,
                        cell_id=cell.id,
                        native_address=address,
                        absolute_row1=int(match[1]),
                        row_index0=cell.row_index0,
                        column_index0=cell.column_index0,
                        row_span=cell.row_span,
                        column_span=cell.column_span,
                        value_type=cell.value_type,
                        raw_text=cell.raw_text,
                        normalized_text=cell.normalized_text,
                        observation=observation,
                    )
                )
                evidence.append(
                    NativeCellEvidence(
                        evidence_id=evidence_id,
                        fact_id=fact_id,
                        document_id=envelope.source_id,
                        document_version_id=envelope.source_version_id,
                        cir_sha256=envelope.cir_sha256,
                        cell_id=cell.id,
                        table_id=table.id,
                        block_id=block.id,
                        block_content_sha256=block.content_hash,
                        source_refs=cell.source_refs,
                    )
                )
            reasons.update(table_reasons)
            tables.append(
                NativeFactTable(
                    table_id=table.id,
                    block_id=block.id,
                    block_content_sha256=block.content_hash,
                    source_refs=table.source_refs,
                    producer_header_row_count=table.header_row_count,
                    header_status=header_status,
                    review_reasons=tuple(sorted(table_reasons)),
                    rows=tuple(
                        NativeFactRow(
                            row_index0=index,
                            absolute_row1=cells[0].absolute_row1,
                            cells=tuple(cells),
                        )
                        for index, cells in sorted(rows.items())
                    ),
                )
            )
        documents.append(
            NativeFactDocument(
                **envelope.model_dump(
                    mode="python", by_alias=False, exclude={"canonical_document"}
                ),
                tables=tuple(tables),
            )
        )
    return tuple(documents), tuple(evidence), tuple(sorted(reasons))


class NativeFactsDraft(ContractModel):
    schema_version: Literal["tavonel.product_core.native_facts_draft.v1"] = (
        "tavonel.product_core.native_facts_draft.v1"
    )
    projection_version: Literal["tavonel.native_cell_facts.v1"] = "tavonel.native_cell_facts.v1"
    status: Literal["review_required"] = "review_required"
    approval_status: Literal["unbound"] = "unbound"
    candidate_promotion: Literal[False] = False
    request_id: Identifier
    idempotency_key: Identifier
    requested_at: datetime
    input_sha256: Sha256
    tenant_id: Identifier
    workspace_id: Identifier
    collection_id: Identifier
    input_document_order: tuple[Identifier, ...]
    canonical_documents: tuple[CanonicalDocument, ...]
    documents: tuple[NativeFactDocument, ...]
    evidence: tuple[NativeCellEvidence, ...]
    review_reasons: tuple[str, ...]

    @field_validator("canonical_documents", mode="before")
    @classmethod
    def bounded_canonical_documents(cls, value: Any) -> tuple[dict[str, Any], ...]:
        if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 16:
            raise ValueError("native canonical document count limit")
        documents = []
        # Preflight every document before Pydantic can construct any table grid.
        for document in value:
            if isinstance(document, CanonicalDocument):
                document = document.model_dump(mode="json", by_alias=True, exclude_none=True)
            if not isinstance(document, dict):
                raise ValueError("canonicalDocument must be a canonical JSON object")
            _preflight(document)
            documents.append(document)
        return tuple(documents)

    @model_validator(mode="after")
    def bind_projection(self) -> NativeFactsDraft:
        if len(canonical_json(self).encode("utf-8")) > MAX_NATIVE_FACTS_OUTPUT_BYTES:
            raise ValueError("native facts output byte limit")
        cir_by_version = {doc.document_version_id: doc for doc in self.canonical_documents}
        if len(cir_by_version) != len(self.canonical_documents):
            raise ValueError("duplicate canonical documents")
        if len(self.documents) != len(self.canonical_documents):
            raise ValueError("facts must cover all canonical documents")
        if len(self.input_document_order) != len(cir_by_version) or set(
            self.input_document_order
        ) != set(cir_by_version):
            raise ValueError("native input document order is duplicated or incomplete")
        envelopes = {}
        for document in self.documents:
            cir = cir_by_version.get(document.source_version_id)
            if cir is None:
                raise ValueError("facts refer to missing canonical document")
            envelopes[document.source_version_id] = {
                **document.model_dump(mode="json", by_alias=True, exclude={"tables"}),
                "canonicalDocument": cir.model_dump(mode="json", by_alias=True, exclude_none=True),
            }
        if len(envelopes) != len(self.documents) or set(envelopes) != set(cir_by_version):
            raise ValueError("duplicate or missing document facts")
        request = parse_native_request(
            canonical_json(
                {
                    "schemaVersion": "tavonel.product_core.native_cir_request.v1",
                    "requestId": self.request_id,
                    "idempotencyKey": self.idempotency_key,
                    "requestedAt": self.requested_at.isoformat(),
                    "tenantId": self.tenant_id,
                    "workspaceId": self.workspace_id,
                    "collectionId": self.collection_id,
                    "documents": [envelopes[version] for version in self.input_document_order],
                }
            ).encode("utf-8")
        )
        if sha256_digest(canonical_json(request)) != self.input_sha256:
            raise ValueError("native facts canonical input digest mismatch")
        expected_documents, expected_evidence, expected_reasons = _project(request)
        if (
            self.documents != expected_documents
            or self.evidence != expected_evidence
            or self.review_reasons != expected_reasons
            or self.canonical_documents
            != tuple(
                document.canonical_document
                for document in sorted(request.documents, key=lambda item: item.source_id)
            )
        ):
            raise ValueError("native facts/evidence are duplicated, dangling or altered")
        return self


def project_native_facts(request: NativeCIRRequest) -> NativeFactsDraft:
    """Project original cells only; no semantic compiler, parser, I/O or approval."""
    body = canonical_json(request).encode("utf-8")
    request = parse_native_request(body)
    # The digest describes the canonical request, independent of JSON whitespace.
    body = canonical_json(request).encode("utf-8")
    documents, evidence, reasons = _project(request)
    return NativeFactsDraft(
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        requested_at=request.requested_at,
        input_sha256=sha256_digest(body),
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        collection_id=request.collection_id,
        input_document_order=tuple(document.source_version_id for document in request.documents),
        canonical_documents=tuple(
            document.canonical_document
            for document in sorted(request.documents, key=lambda item: item.source_id)
        ),
        documents=documents,
        evidence=evidence,
        review_reasons=reasons,
    )
