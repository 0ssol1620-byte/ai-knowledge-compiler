"""Closed native-CIR v1 contract and offline draft serialization.

This is not an intake approval, parser, semantic compiler, or promotion path.
The existing shared transport secret cannot qualify a processing caller.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from akc_cir.base import ContractModel, Sha256, canonical_json, sha256_digest
from akc_cir.identity import document_version_id, source_id
from akc_cir.models import BlockOrigin, BlockType, CanonicalDocument, ContentLayer, SourceRef
from pydantic import Field, field_validator, model_validator

from .contracts import CandidatePackage, CandidatePackageFile, Identifier, ProductCoreDocument

NATIVE_REQUEST_SCHEMA = "tavonel.product_core.native_cir_request.v1"
NATIVE_RESPONSE_SCHEMA = "tavonel.product_core.native_cir_draft.v1"
MAX_NATIVE_REQUEST_BYTES = 32 * 1024 * 1024  # Never exceed the existing transport fence.
MAX_NATIVE_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_NATIVE_CIR_BYTES = 8 * 1024 * 1024
MAX_NATIVE_BLOCKS = 10_000
MAX_NATIVE_CELLS = 100_000
_LOCATOR = re.compile(
    r"^xlsx/sheet/([0-9]{4})(?:/(cell|range)/([A-Z]+[1-9][0-9]*(?::[A-Z]+[1-9][0-9]*)?))?$"
)
_A1 = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


def _coordinate(value: str) -> tuple[int, int]:
    match = _A1.fullmatch(value)
    if match is None:
        raise ValueError("invalid XLSX coordinate")
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord("A") + 1
    row = int(match[2])
    if row > 100_000 or column > 1_024:
        raise ValueError("XLSX coordinate exceeds parser bounds")
    return row, column


def _preflight(value: Any) -> None:
    """Fence dimensions before CanonicalTable's occupied-grid validation."""
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > 32:
            raise ValueError("native CIR nesting limit")
        if isinstance(node, dict):
            stack.extend((item, depth + 1) for item in node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend((item, depth + 1) for item in node)
    if not isinstance(value, dict):
        raise ValueError("canonicalDocument must be a canonical JSON object")
    blocks = value.get("blocks")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= MAX_NATIVE_BLOCKS:
        raise ValueError("native block limit")
    cells = 0
    area = 0
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("invalid native block")
        table = block.get("table")
        if table is None:
            continue
        if not isinstance(table, dict):
            raise ValueError("invalid native table")
        rows, columns = table.get("rowCount"), table.get("columnCount")
        if type(rows) is not int or type(columns) is not int:
            raise ValueError("table dimensions must be integers")
        if not 1 <= rows <= 100_000 or not 1 <= columns <= 1_024:
            raise ValueError("table dimensions exceed parser bounds")
        area += rows * columns
        entries = table.get("cells")
        if not isinstance(entries, list):
            raise ValueError("invalid native cells")
        cells += len(entries)
        if cells > MAX_NATIVE_CELLS or area > MAX_NATIVE_CELLS:
            raise ValueError("native cell/grid limit")
        for cell in entries:
            if not isinstance(cell, dict):
                raise ValueError("invalid native cell")
            for key in ("rowIndex0", "columnIndex0", "rowSpan", "columnSpan"):
                if type(cell.get(key)) is not int:
                    raise ValueError("cell coordinates and spans must be integers")
    if len(canonical_json(value).encode("utf-8")) > MAX_NATIVE_CIR_BYTES:
        raise ValueError("native CIR byte limit")


class NativeCIRDocument(ContractModel):
    native_id: Identifier
    connector_type: Identifier
    source_id: Identifier
    source_version_id: Identifier
    immutable_object_key: Annotated[str, Field(min_length=1, max_length=1_024)]
    cir_object_key: Annotated[str, Field(min_length=1, max_length=1_024)]
    content_sha256: Sha256
    cir_sha256: Sha256
    # An immutable receipt reference is required but is NEVER proof of approval.
    processing_receipt_id: Identifier
    canonical_document: CanonicalDocument

    @field_validator("immutable_object_key", "cir_object_key")
    @classmethod
    def safe_key(cls, value: str) -> str:
        return ProductCoreDocument.safe_object_key(value)

    @field_validator("canonical_document", mode="before")
    @classmethod
    def bounded_cir(cls, value: Any) -> CanonicalDocument:
        if isinstance(value, CanonicalDocument):
            value = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        _preflight(value)
        document = CanonicalDocument.model_validate(value)
        if canonical_json(value) != canonical_json(document):
            raise ValueError("CIR must use the exact canonical wire representation")
        return document

    @model_validator(mode="after")
    def validate_native(self) -> NativeCIRDocument:
        doc = self.canonical_document
        if doc.schema_version != "cir-1.0.0" or doc.content_layer != ContentLayer.STRUCTURED:
            raise ValueError("unsupported native CIR version/layer")
        if (
            doc.document_id != self.source_id
            or doc.document_version_id != self.source_version_id
            or doc.source_sha256 != self.content_sha256
            or sha256_digest(canonical_json(doc)) != self.cir_sha256
        ):
            raise ValueError("native CIR identity or digest mismatch")
        if doc.model_runs or doc.metadata.get("assets"):
            raise ValueError("this slice does not carry model runs or embedded assets")
        if (
            doc.metadata.get("documentType") != "xlsx"
            or doc.metadata.get("nativeParser") != "akc-native-parsers"
            or doc.metadata.get("nativeParserVersion") != "1.2.0"
            or not doc.source_filename.casefold().endswith(".xlsx")
        ):
            raise ValueError("unsupported native producer/format")
        sheets = doc.metadata.get("sheets")
        if not isinstance(sheets, list) or not 1 <= len(sheets) <= 512:
            raise ValueError("native sheet metadata required")
        for index, sheet in enumerate(sheets):
            if (
                not isinstance(sheet, dict)
                or type(sheet.get("pageIndex0")) is not int
                or sheet["pageIndex0"] != index
                or not isinstance(sheet.get("name"), str)
                or not sheet["name"]
                or not isinstance(sheet.get("state"), str)
                or sheet.get("state") not in {"visible", "hidden", "veryHidden"}
            ):
                raise ValueError("invalid sheet identity")
        if len({sheet["name"] for sheet in sheets}) != len(sheets):
            raise ValueError("duplicate sheet names")
        ids: set[str] = set()
        anchors: set[str] = set()
        table_sheets: set[int] = set()
        sheet_heading_ids = {
            block.source_refs[0].page_index0: block.id
            for block in doc.blocks
            if block.type == BlockType.HEADING
        }
        parents = {block.id: block.parent_id for block in doc.blocks}
        checked_parents: set[str] = set()
        for block in doc.blocks:
            lineage: set[str] = set()
            parent: str | None = block.id
            while parent is not None and parent not in checked_parents:
                if parent in lineage:
                    raise ValueError("cyclic native parents")
                lineage.add(parent)
                parent = parents[parent]
            checked_parents.update(lineage)
            if block.id in ids:
                raise ValueError("duplicate native ID")
            ids.add(block.id)
            if block.origin != BlockOrigin.NATIVE_EXTRACTED:
                raise ValueError("native origin required")
            if block.content_layer != ContentLayer.STRUCTURED or block.model_run_ids:
                raise ValueError("native structured blocks required")
            locator = self._ref(block.source_refs, sheets)
            if locator in anchors:
                raise ValueError("duplicate block locator")
            anchors.add(locator)
            if block.type == BlockType.HEADING:
                if locator != f"xlsx/sheet/{block.source_refs[0].page_index0:04d}":
                    raise ValueError("sheet heading locator required")
                if block.raw_text != sheets[block.source_refs[0].page_index0]["name"]:
                    raise ValueError("sheet heading name mismatch")
            elif block.type == BlockType.TABLE and block.table is not None:
                sheet_index = block.source_refs[0].page_index0
                if sheet_index in table_sheets:
                    raise ValueError("native XLSX permits only one canonical table per sheet")
                table_sheets.add(sheet_index)
                if block.parent_id != sheet_heading_ids.get(sheet_index):
                    raise ValueError("native table parent must be its sheet heading")
                table = block.table
                if table.id in ids or self._ref(table.source_refs, sheets) != locator:
                    raise ValueError("duplicate table ID or table locator mismatch")
                ids.add(table.id)
                match = _LOCATOR.fullmatch(locator)
                if match is None or match[2] != "range" or ":" not in match[3]:
                    raise ValueError("table range locator required")
                start, end = (_coordinate(item) for item in match[3].split(":"))
                if (end[0] - start[0] + 1, end[1] - start[1] + 1) != (
                    table.row_count,
                    table.column_count,
                ):
                    raise ValueError("table dimensions do not match original range")
                cell_anchors: set[str] = set()
                for cell in table.cells:
                    cell_locator = self._ref(cell.source_refs, sheets)
                    cell_match = _LOCATOR.fullmatch(cell_locator)
                    if (
                        cell.id in ids
                        or cell_locator in cell_anchors
                        or cell.origin != BlockOrigin.NATIVE_EXTRACTED
                        or cell_match is None
                        or cell_match[2] != "cell"
                        or cell_match[1] != match[1]
                        or _coordinate(cell_match[3])
                        != (start[0] + cell.row_index0, start[1] + cell.column_index0)
                    ):
                        raise ValueError("invalid or duplicate native cell identity/locator")
                    ids.add(cell.id)
                    cell_anchors.add(cell_locator)
            else:
                raise ValueError("this slice accepts XLSX headings and tables only")
            material = {
                "type": block.type.value,
                "rawText": block.raw_text,
                "normalizedText": block.normalized_text,
                "markdown": block.markdown,
                "sanitizedHtml": block.sanitized_html,
                "table": block.table.model_dump(mode="json", by_alias=True, exclude_none=True)
                if block.table is not None
                else None,
            }
            if sha256_digest(canonical_json(material)) != block.content_hash:
                raise ValueError("native block content hash mismatch")
        headings = [block for block in doc.blocks if block.type == BlockType.HEADING]
        if len(headings) != len(sheets):
            raise ValueError("each native sheet requires one heading")
        return self

    def _ref(self, refs: tuple[SourceRef, ...], sheets: list[Any]) -> str:
        if len(refs) != 1:
            raise ValueError("this producer requires one original locator")
        ref = refs[0]
        match = _LOCATOR.fullmatch(ref.native_object_id or "")
        if (
            ref.document_id != self.source_id
            or ref.document_version_id != self.source_version_id
            or ref.bbox1000 is not None
            or ref.image_asset_id is not None
            or ref.time_start_ms is not None
            or ref.time_end_ms is not None
            or match is None
            or int(match[1]) != ref.page_index0
            or ref.page_index0 >= len(sheets)
        ):
            raise ValueError("native locator identity mismatch or fabricated geometry")
        return ref.native_object_id or ""


class NativeCIRRequest(ContractModel):
    schema_version: Literal["tavonel.product_core.native_cir_request.v1"]
    request_id: Identifier
    idempotency_key: Identifier
    tenant_id: Identifier
    workspace_id: Identifier
    collection_id: Identifier
    requested_at: datetime
    documents: Annotated[tuple[NativeCIRDocument, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def bind_scope(self) -> NativeCIRRequest:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requestedAt must be timezone-aware")
        seen: set[str] = set()
        seen_native_ids: set[str] = set()
        total_cells = total_bytes = 0
        for document in self.documents:
            source = source_id(
                tenant_id=self.tenant_id,
                connector_type=document.connector_type,
                native_id=document.native_id,
            )
            if source in seen or source != document.source_id:
                raise ValueError("duplicate or incorrect native source identity")
            seen.add(source)
            native_ids = [block.id for block in document.canonical_document.blocks]
            for block in document.canonical_document.blocks:
                if block.table is not None:
                    native_ids.append(block.table.id)
                    native_ids.extend(cell.id for cell in block.table.cells)
            if seen_native_ids.intersection(native_ids):
                raise ValueError("duplicate native IDs across documents")
            seen_native_ids.update(native_ids)
            if (
                document.source_version_id
                != document_version_id(source=source, content_sha256=document.content_sha256)
                or document.canonical_document.tenant_id != self.tenant_id
            ):
                raise ValueError("native tenant/version mismatch")
            keys = [document.immutable_object_key.split("/"), document.cir_object_key.split("/")]
            if (
                any(len(key) != 6 for key in keys)
                or keys[0][:-1] != keys[1][:-1]
                or any(
                    key[:3] != ["immutable", self.tenant_id, self.workspace_id]
                    or key[4] != document.content_sha256[7:]
                    for key in keys
                )
                or keys[0][-1] != "source.xlsx"
                or keys[1][-1] != "native-cir.json"
            ):
                raise ValueError("native immutable input binding mismatch")
            total_bytes += len(canonical_json(document.canonical_document).encode("utf-8"))
            total_cells += sum(
                len(block.table.cells)
                for block in document.canonical_document.blocks
                if block.table is not None
            )
        if total_bytes > MAX_NATIVE_CIR_BYTES or total_cells > MAX_NATIVE_CELLS:
            raise ValueError("aggregate native CIR limit")
        return self


def parse_native_request(body: bytes) -> NativeCIRRequest:
    if len(body) > MAX_NATIVE_REQUEST_BYTES:
        raise ValueError("native request byte limit")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON property")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON constant")

    try:
        text = body.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        return NativeCIRRequest.model_validate(value)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid native JSON") from exc


class NativeCIRDraft(ContractModel):
    schema_version: Literal["tavonel.product_core.native_cir_draft.v1"] = (
        "tavonel.product_core.native_cir_draft.v1"
    )
    status: Literal["review_required"] = "review_required"
    candidate_promotion: Literal[False] = False
    request_id: Identifier
    input_sha256: Sha256
    package_sha256: Sha256
    package: CandidatePackage
    review_reasons: tuple[str, ...] = ("NATIVE_PROCESSING_APPROVAL_UNBOUND",)


def serialize_native_draft(request: NativeCIRRequest) -> NativeCIRDraft:
    """Offline validation/serialization only. It does not qualify the caller."""
    body = canonical_json(request).encode("utf-8")
    request = parse_native_request(body)  # Revalidate copies and mutable nested metadata.
    files = []
    for document in sorted(request.documents, key=lambda item: item.source_id):
        content = canonical_json(document.canonical_document) + "\n"
        files.append(
            CandidatePackageFile(
                path=f"canonical/documents/{document.source_version_id}.json",
                media_type="application/json",
                size_bytes=len(content.encode("utf-8")),
                sha256=sha256_digest(content),
                content=content,
            )
        )
    manifest = (
        canonical_json(
            {
                "schemaVersion": "tavonel.native_cir_package.v1",
                "tenantId": request.tenant_id,
                "workspaceId": request.workspace_id,
                "collectionId": request.collection_id,
                "documents": [
                    {
                        **document.model_dump(
                            mode="json", by_alias=True, exclude={"canonical_document"}
                        ),
                        "path": f"canonical/documents/{document.source_version_id}.json",
                    }
                    for document in sorted(request.documents, key=lambda item: item.source_id)
                ],
                "files": [
                    {"path": file.path, "sha256": file.sha256, "sizeBytes": file.size_bytes}
                    for file in files
                ],
                "approvalStatus": "unbound",
                "candidatePromotion": False,
            }
        )
        + "\n"
    )
    files.append(
        CandidatePackageFile(
            path="provenance/native-cir-manifest.json",
            media_type="application/json",
            size_bytes=len(manifest.encode("utf-8")),
            sha256=sha256_digest(manifest),
            content=manifest,
        )
    )
    package = CandidatePackage(roots=("canonical", "provenance"), files=tuple(files))
    package_bytes = canonical_json(package).encode("utf-8")
    if len(package_bytes) > MAX_NATIVE_PACKAGE_BYTES:
        raise ValueError("native package byte limit")
    return NativeCIRDraft(
        request_id=request.request_id,
        input_sha256=sha256_digest(body),
        package_sha256=sha256_digest(package_bytes),
        package=package,
    )
