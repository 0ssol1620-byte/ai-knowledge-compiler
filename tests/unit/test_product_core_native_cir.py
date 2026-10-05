"""Tiny existing-parser fixtures and the closed native transport boundary."""

from __future__ import annotations

import copy
import io
from datetime import UTC, datetime

import pytest
from akc_cir.base import canonical_json, sha256_digest
from akc_cir.identity import document_version_id, source_id
from akc_cir.models import CanonicalDocument
from akc_native_parsers import ParseContext, parse_non_pdf_to_cir
from akc_product_core.api import ProductCoreService, create_product_core_app
from akc_product_core.auth import sign_product_core_request
from akc_product_core.native_cir import (
    NATIVE_REQUEST_SCHEMA,
    NativeCIRDraft,
    parse_native_request,
    serialize_native_draft,
)
from fastapi.testclient import TestClient
from openpyxl import Workbook

SECRET = b"synthetic-native-contract-test-secret-32-bytes"
RELEASE = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _fixture(kind: str = "normal") -> dict:
    book = Workbook()
    book.properties.created = NOW
    book.properties.modified = NOW
    sheet = book.active
    sheet.title = "한글 Ω" if kind == "unicode" else "Data"
    if kind == "locator":
        sheet["C7"] = "Header"
        sheet["D8"] = 0
    else:
        sheet.append(["Label", "Label" if kind == "duplicate-header" else "Value"])
        sheet.append(["  e\u0301 한글  " if kind == "unicode" else "Metric", 0])
        if kind == "merged":
            sheet.merge_cells("A1:B1")
        if kind == "formula":
            sheet["B3"] = "=1+2"
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    # Pin container timestamps so workbook bytes, identities and fixtures are deterministic.
    import zipfile

    fixed = io.BytesIO()
    with zipfile.ZipFile(buffer) as original, zipfile.ZipFile(fixed, "w") as target:
        for entry in original.infolist():
            entry.date_time = (2026, 1, 1, 0, 0, 0)
            content = original.read(entry.filename)
            if entry.filename == "docProps/core.xml":
                import re

                content = re.sub(
                    rb"(<dcterms:modified[^>]*>)[^<]+",
                    rb"\g<1>2026-10-05T00:00:00Z",
                    content,
                )
            target.writestr(entry, content)
    data = fixed.getvalue()
    digest = sha256_digest(data)
    source = source_id(tenant_id="tenant-native", connector_type="foundation-r2", native_id="book")
    version = document_version_id(source=source, content_sha256=digest)
    document = parse_non_pdf_to_cir(
        filename="fixture.xlsx",
        declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data=data,
        context=ParseContext(
            tenant_id="tenant-native",
            document_id=source,
            document_version_id=version,
            created_at=NOW,
        ),
    )
    prefix = f"immutable/tenant-native/workspace-native/upload/{digest[7:]}"
    return {
        "schemaVersion": NATIVE_REQUEST_SCHEMA,
        "requestId": "native-fixture",
        "idempotencyKey": "idem-native-fixture",
        "tenantId": "tenant-native",
        "workspaceId": "workspace-native",
        "collectionId": "collection-native",
        "requestedAt": NOW.isoformat(),
        "documents": [
            {
                "nativeId": "book",
                "connectorType": "foundation-r2",
                "sourceId": source,
                "sourceVersionId": version,
                "contentSha256": digest,
                "immutableObjectKey": prefix + "/source.xlsx",
                "cirObjectKey": prefix + "/native-cir.json",
                "processingReceiptId": "unverified-synthetic-receipt",
                "cirSha256": sha256_digest(canonical_json(document)),
                "canonicalDocument": document.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            }
        ],
    }


def _body(payload: dict) -> bytes:
    return canonical_json(payload).encode("utf-8")


def _signed(body: bytes, request_id: str = "native-fixture") -> dict[str, str]:
    return sign_product_core_request(
        body=body,
        request_id=request_id,
        timestamp=int(datetime.now(tz=UTC).timestamp()),
        secret=SECRET,
    )


@pytest.mark.parametrize(
    "kind", ["normal", "merged", "unicode", "zero", "duplicate-header", "locator", "formula"]
)
def test_parser_cir_and_package_roundtrip(kind: str) -> None:
    payload = _fixture(kind)
    request = parse_native_request(_body(payload))
    draft = serialize_native_draft(request)
    restored = NativeCIRDraft.model_validate_json(canonical_json(draft))
    file = restored.package.files[0]
    assert file.sha256 == sha256_digest(file.content)
    assert file.size_bytes == len(file.content.encode("utf-8"))
    assert restored.package_sha256 == sha256_digest(canonical_json(restored.package))
    assert restored.candidate_promotion is False
    assert restored.package.signature_status == "external_signer_required"
    cir = CanonicalDocument.model_validate_json(file.content)
    assert (
        cir.model_dump(mode="json", by_alias=True, exclude_none=True)
        == payload["documents"][0]["canonicalDocument"]
    )
    cells = [cell for block in cir.blocks if block.table for cell in block.table.cells]
    assert any(cell.raw_text == "0" for cell in cells)
    assert all(ref.bbox1000 is None for cell in cells for ref in cell.source_refs)
    if kind == "unicode":
        assert any(cell.raw_text == "  e\u0301 한글  " for cell in cells)
    if kind == "merged":
        assert any(cell.column_span == 2 for cell in cells)
    if kind == "locator":
        assert {cell.source_refs[0].native_object_id for cell in cells} == {
            "xlsx/sheet/0000/cell/C7",
            "xlsx/sheet/0000/cell/D8",
        }
    if kind == "formula":
        assert any(cell.formula == "=1+2" and cell.raw_text == "=1+2" for cell in cells)


def test_http_gate_never_qualifies_shared_secret_or_receipt() -> None:
    payload = _fixture()
    body = _body(payload)
    service = ProductCoreService(
        hmac_secret=SECRET, core_release_digest=RELEASE, allow_customer_data=True
    )
    assert service.validate_native_draft(body=body, headers=_signed(body)) == (
        403,
        {"code": "CORE_NATIVE_PROCESSING_DISABLED"},
    )
    assert service._cache == {}
    assert service.validate_native_draft(body=body, headers={})[0] == 401
    assert service.validate_native_draft(body=body, headers=_signed(body, "wrong"))[0] == 401
    assert service.validate_native_draft(body=body + b" ", headers=_signed(body))[0] == 401
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    result = client.post("/v3/native-cir/compile", content=body, headers=_signed(body))
    assert result.status_code == 403
    assert result.headers["cache-control"] == "no-store"
    assert client.post("/v2/compile", content=body, headers=_signed(body)).status_code == 422


@pytest.mark.parametrize(
    "mutation",
    [
        "mixed",
        "boolean",
        "version",
        "tenant",
        "source",
        "digest",
        "duplicate-document",
        "duplicate-block",
        "duplicate-cell",
        "no-provenance",
        "wrong-ref",
        "geometry",
        "overlap",
        "dimension",
        "oversize-grid",
        "locator",
        "origin",
        "parent-cycle",
        "metadata",
        "object-scope",
        "content-hash",
        "missing-receipt",
    ],
)
def test_rejects_ambiguous_unbound_and_malformed_inputs(mutation: str) -> None:
    payload = _fixture()
    envelope = payload["documents"][0]
    cir = envelope["canonicalDocument"]
    table_block = next(block for block in cir["blocks"] if "table" in block)
    table = table_block["table"]
    cell = table["cells"][0]
    if mutation == "mixed":
        envelope["regions"] = []
    elif mutation == "boolean":
        payload["approved"] = True
    elif mutation == "version":
        cir["schemaVersion"] = "cir-2.0.0"
    elif mutation == "tenant":
        cir["tenantId"] = "other-tenant"
    elif mutation == "source":
        envelope["sourceId"] = "other-source"
    elif mutation == "digest":
        envelope["contentSha256"] = RELEASE
    elif mutation == "duplicate-document":
        payload["documents"].append(copy.deepcopy(envelope))
    elif mutation == "duplicate-block":
        cir["blocks"].append(copy.deepcopy(cir["blocks"][0]))
    elif mutation == "duplicate-cell":
        table["cells"][1]["id"] = cell["id"]
    elif mutation == "no-provenance":
        cell["sourceRefs"] = []
    elif mutation == "wrong-ref":
        cell["sourceRefs"][0]["documentVersionId"] = "wrong-version"
    elif mutation == "geometry":
        cell["sourceRefs"][0]["bbox1000"] = [0, 0, 1, 1]
    elif mutation == "overlap":
        table["cells"][1]["columnIndex0"] = 0
    elif mutation == "dimension":
        table["columnCount"] = 1
    elif mutation == "oversize-grid":
        table["rowCount"] = 100_000
        table["columnCount"] = 1_024
    elif mutation == "locator":
        cell["sourceRefs"][0]["nativeObjectId"] = "xlsx/sheet/0001/cell/A1"
    elif mutation == "origin":
        cell["origin"] = "ocr_extracted"
    elif mutation == "parent-cycle":
        table_block["parentId"] = table_block["id"]
    elif mutation == "metadata":
        cir["metadata"]["sheets"][0]["pageIndex0"] = 1
    elif mutation == "object-scope":
        envelope["cirObjectKey"] = envelope["cirObjectKey"].replace("workspace-native", "other")
    elif mutation == "content-hash":
        table_block["contentHash"] = RELEASE
    elif mutation == "missing-receipt":
        del envelope["processingReceiptId"]
    # Rebind digest so nested invariants cannot be accidentally tested only by the envelope hash.
    envelope["cirSha256"] = sha256_digest(canonical_json(cir))
    with pytest.raises(ValueError):
        parse_native_request(_body(payload))


def test_duplicate_json_nonfinite_and_wire_coercion_rejected() -> None:
    body = _body(_fixture())
    with pytest.raises(ValueError):
        parse_native_request(
            body.replace(
                b'"requestId":"native-fixture"',
                b'"requestId":"native-fixture","requestId":"native-fixture"',
            )
        )
    with pytest.raises(ValueError):
        parse_native_request(body.replace(b'"pageIndex0":0', b'"pageIndex0":NaN'))
    with pytest.raises(ValueError):
        parse_native_request(body.replace(b'"rowSpan":1', b'"rowSpan":true'))
    payload = _fixture()
    request = parse_native_request(_body(payload))
    request.documents[0].canonical_document.metadata["sheets"][0]["name"] = "tampered"
    with pytest.raises(ValueError):
        serialize_native_draft(request)


def test_fixture_is_deterministic() -> None:
    assert _body(_fixture("unicode")) == _body(_fixture("unicode"))


def test_size_fences_are_closed_at_request_cir_and_package(monkeypatch) -> None:
    import akc_product_core.api as api
    import akc_product_core.native_cir as native

    payload = _fixture()
    body = _body(payload)
    request = parse_native_request(body)
    with monkeypatch.context() as patch:
        patch.setattr(native, "MAX_NATIVE_REQUEST_BYTES", len(body) - 1)
        with pytest.raises(ValueError, match="request byte limit"):
            parse_native_request(body)
    with monkeypatch.context() as patch:
        patch.setattr(native, "MAX_NATIVE_CIR_BYTES", 1)
        with pytest.raises(ValueError, match="byte limit"):
            parse_native_request(body)
    with monkeypatch.context() as patch:
        patch.setattr(native, "MAX_NATIVE_PACKAGE_BYTES", 1)
        with pytest.raises(ValueError, match="package byte limit"):
            serialize_native_draft(request)
    with monkeypatch.context() as patch:
        patch.setattr(api, "MAX_REQUEST_BYTES", len(body) - 1)
        client = TestClient(
            create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE)
        )
        assert client.post("/v3/native-cir/compile", content=body).status_code == 413


def test_aggregate_budget_and_no_approval_header_escape(monkeypatch) -> None:
    import akc_product_core.native_cir as native

    payload = _fixture()
    first = payload["documents"][0]
    second = copy.deepcopy(first)
    second["nativeId"] = "book-two"
    second["sourceId"] = source_id(
        tenant_id=payload["tenantId"], connector_type=second["connectorType"], native_id="book-two"
    )
    second["sourceVersionId"] = document_version_id(
        source=second["sourceId"], content_sha256=second["contentSha256"]
    )
    cir = second["canonicalDocument"]
    cir["documentId"] = second["sourceId"]
    cir["documentVersionId"] = second["sourceVersionId"]
    for block in cir["blocks"]:
        refs = list(block["sourceRefs"])
        table = block.get("table")
        if table is not None:
            refs.extend(table["sourceRefs"])
            refs.extend(ref for cell in table["cells"] for ref in cell["sourceRefs"])
        for ref in refs:
            ref["documentId"] = second["sourceId"]
            ref["documentVersionId"] = second["sourceVersionId"]
        material = {
            "type": block["type"],
            "rawText": block.get("rawText"),
            "normalizedText": block.get("normalizedText"),
            "markdown": block.get("markdown"),
            "sanitizedHtml": block.get("sanitizedHtml"),
            "table": table,
        }
        block["contentHash"] = sha256_digest(canonical_json(material))
    second["cirSha256"] = sha256_digest(canonical_json(cir))
    # Identical source bytes have identical native block IDs: reject instead of merging silently.
    payload["documents"].append(second)
    with pytest.raises(ValueError, match="duplicate native IDs across documents"):
        parse_native_request(_body(payload))
    body = _body(_fixture())
    service = ProductCoreService(hmac_secret=SECRET, core_release_digest=RELEASE)
    headers = {**_signed(body), "x-native-approved": "true", "x-processing-caller": "trusted"}
    assert service.validate_native_draft(body=body, headers=headers)[0] == 403
    with monkeypatch.context() as patch:
        patch.setattr(native, "MAX_NATIVE_CELLS", 1)
        with pytest.raises(ValueError, match="cell/grid limit"):
            parse_native_request(body)


@pytest.mark.parametrize("state", [[], {}, ["visible"], {"value": "visible"}, None, 0, True])
def test_signed_malformed_sheet_state_is_422_without_reflecting_input(state) -> None:
    payload = _fixture()
    envelope = payload["documents"][0]
    cir = envelope["canonicalDocument"]
    cir["metadata"]["sheets"][0]["state"] = state
    envelope["cirSha256"] = sha256_digest(canonical_json(cir))
    body = _body(payload)
    with pytest.raises(ValueError, match="invalid sheet identity"):
        parse_native_request(body)
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    result = client.post("/v3/native-cir/compile", content=body, headers=_signed(body))
    assert result.status_code == 422
    assert result.json() == {"code": "CORE_NATIVE_CIR_INVALID"}
    assert result.headers["cache-control"] == "no-store"
    assert client.app.state.product_core_service._cache == {}


def _rebind_cir_hashes(payload: dict) -> None:
    envelope = payload["documents"][0]
    cir = envelope["canonicalDocument"]
    for block in cir["blocks"]:
        material = {
            "type": block["type"],
            "rawText": block.get("rawText"),
            "normalizedText": block.get("normalizedText"),
            "markdown": block.get("markdown"),
            "sanitizedHtml": block.get("sanitizedHtml"),
            "table": block.get("table"),
        }
        block["contentHash"] = sha256_digest(canonical_json(material))
    envelope["cirSha256"] = sha256_digest(canonical_json(cir))


def test_rejects_distinct_overlapping_tables_with_contradictory_native_cells() -> None:
    payload = _fixture()
    cir = payload["documents"][0]["canonicalDocument"]
    original = next(block for block in cir["blocks"] if "table" in block)
    duplicate = copy.deepcopy(original)
    duplicate["id"] = "blk_conflicting_table"
    duplicate["order"] = 2
    duplicate["table"]["id"] = "tbl_conflicting_table"
    duplicate["table"]["columnCount"] = 3
    for ref in (*duplicate["sourceRefs"], *duplicate["table"]["sourceRefs"]):
        ref["nativeObjectId"] = "xlsx/sheet/0000/range/A1:C2"
    for index, cell in enumerate(duplicate["table"]["cells"]):
        cell["id"] = f"cell_conflicting_{index}"
    duplicate["table"]["cells"][0]["rawText"] = "contradictory source value"
    duplicate["table"]["cells"][0]["normalizedText"] = "contradictory source value"
    cir["blocks"].append(duplicate)
    _rebind_cir_hashes(payload)
    body = _body(payload)
    with pytest.raises(ValueError, match="only one canonical table per sheet"):
        parse_native_request(body)
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    result = client.post("/v3/native-cir/compile", content=body, headers=_signed(body))
    assert result.status_code == 422
    assert result.json() == {"code": "CORE_NATIVE_CIR_INVALID"}
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("parent", [None, "another-sheet", "another-table"])
def test_table_parent_must_be_its_own_sheet_heading(parent: str | None) -> None:
    payload = _fixture()
    cir = payload["documents"][0]["canonicalDocument"]
    table_block = next(block for block in cir["blocks"] if "table" in block)
    if parent in {"another-sheet", "another-table"}:
        cir["metadata"]["sheets"].append({"pageIndex0": 1, "name": "Other", "state": "visible"})
        heading = copy.deepcopy(cir["blocks"][0])
        heading.update(
            id="blk_other_sheet",
            order=2,
            rawText="Other",
            normalizedText="Other",
            markdown="## Other",
        )
        heading["sourceRefs"][0].update(
            pageIndex0=1, pageNumber1=2, nativeObjectId="xlsx/sheet/0001"
        )
        cir["blocks"].append(heading)
        if parent == "another-sheet":
            table_block["parentId"] = heading["id"]
        else:
            other_table = copy.deepcopy(table_block)
            other_table.update(id="blk_other_table", order=3, parentId=heading["id"])
            other_table["table"]["id"] = "tbl_other_table"
            refs = [*other_table["sourceRefs"], *other_table["table"]["sourceRefs"]]
            for index, cell in enumerate(other_table["table"]["cells"]):
                cell["id"] = f"cell_other_{index}"
                refs.extend(cell["sourceRefs"])
            for ref in refs:
                ref.update(pageIndex0=1, pageNumber1=2)
                ref["nativeObjectId"] = ref["nativeObjectId"].replace("sheet/0000", "sheet/0001")
            cir["blocks"].append(other_table)
            table_block["parentId"] = other_table["id"]
    else:
        table_block.pop("parentId")
    _rebind_cir_hashes(payload)
    body = _body(payload)
    with pytest.raises(ValueError, match="table parent must be its sheet heading"):
        parse_native_request(body)
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    result = client.post("/v3/native-cir/compile", content=body, headers=_signed(body))
    assert result.status_code == 422
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"]
)
def test_signed_utf16_and_utf32_requests_are_rejected(encoding: str) -> None:
    body = canonical_json(_fixture()).encode(encoding)
    with pytest.raises(ValueError):
        parse_native_request(body)
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    result = client.post("/v3/native-cir/compile", content=body, headers=_signed(body))
    assert result.status_code == 422
    assert result.json() == {"code": "CORE_NATIVE_CIR_INVALID"}
    assert result.headers["cache-control"] == "no-store"


def test_signed_invalid_utf8_is_rejected_and_valid_utf8_stays_closed() -> None:
    valid = _body(_fixture("unicode"))
    invalid = valid + b"\xff"
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    rejected = client.post("/v3/native-cir/compile", content=invalid, headers=_signed(invalid))
    assert rejected.status_code == 422
    assert rejected.headers["cache-control"] == "no-store"
    closed = client.post("/v3/native-cir/compile", content=valid, headers=_signed(valid))
    assert closed.status_code == 403
    assert closed.json() == {"code": "CORE_NATIVE_PROCESSING_DISABLED"}
    assert closed.headers["cache-control"] == "no-store"
