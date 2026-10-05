"""Coordinate facts preserve cells; headers and formula values remain unresolved."""

from __future__ import annotations

import copy

import pytest
from akc_cir.base import canonical_json, sha256_digest
from akc_cir.identity import document_version_id, source_id
from akc_product_core.api import create_product_core_app
from akc_product_core.native_cir import parse_native_request
from akc_product_core.native_facts import (
    FormulaExpression,
    NativeFactsDraft,
    SourceCellValue,
    project_native_facts,
)
from fastapi.testclient import TestClient

from .test_product_core_native_cir import (
    RELEASE,
    SECRET,
    _body,
    _fixture,
    _rebind_cir_hashes,
    _signed,
)


def _payload(kind: str = "normal", *, headers: int | None = None, inferred: bool = False) -> dict:
    payload = _fixture(kind)
    block = next(
        block
        for block in payload["documents"][0]["canonicalDocument"]["blocks"]
        if "table" in block
    )
    if headers is not None:
        block["table"]["headerRowCount"] = headers
        block["qualityFlags"] = ["header_row_inferred"] if inferred else []
        block["table"]["qualityFlags"] = ["header_row_inferred"] if inferred else []
    _rebind_cir_hashes(payload)
    return payload


def _facts(draft: NativeFactsDraft):
    return [
        cell
        for document in draft.documents
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    ]


@pytest.mark.parametrize(
    "kind", ["normal", "merged", "unicode", "zero", "duplicate-header", "locator", "formula"]
)
def test_every_existing_cell_and_complete_cir_survive(kind: str) -> None:
    payload = _payload(kind)
    request = parse_native_request(_body(payload))
    draft = project_native_facts(request)
    encoded = canonical_json(draft)
    restored = NativeFactsDraft.model_validate_json(encoded)
    assert canonical_json(restored) == encoded == canonical_json(project_native_facts(request))
    assert restored.input_sha256 == sha256_digest(canonical_json(request))
    assert canonical_json(restored.canonical_documents[0]) == canonical_json(
        request.documents[0].canonical_document
    )
    original = [
        cell
        for block in request.documents[0].canonical_document.blocks
        if block.table
        for cell in block.table.cells
    ]
    facts = _facts(restored)
    assert len(facts) == len(original) == len(restored.evidence)
    assert [
        (
            cell.cell_id,
            cell.raw_text,
            cell.normalized_text,
            cell.value_type,
            cell.row_span,
            cell.column_span,
        )
        for cell in facts
    ] == [
        (
            cell.id,
            cell.raw_text,
            cell.normalized_text,
            cell.value_type,
            cell.row_span,
            cell.column_span,
        )
        for cell in original
    ]
    by_id = {item.evidence_id: item for item in restored.evidence}
    for fact, cell in zip(facts, original, strict=True):
        assert by_id[fact.evidence_id].source_refs == cell.source_refs
        assert fact.native_address == cell.source_refs[0].native_object_id
    assert restored.status == "review_required"
    assert restored.approval_status == "unbound" and restored.candidate_promotion is False
    assert all(not table.header_bindings for doc in restored.documents for table in doc.tables)


def test_zero_matrix_with_no_headers_keeps_all_numeric_zero_cells() -> None:
    payload = _payload(headers=0)
    table = next(
        block["table"]
        for block in payload["documents"][0]["canonicalDocument"]["blocks"]
        if "table" in block
    )
    for cell in table["cells"]:
        cell.update(rawText="0", normalizedText="0", valueType="number")
    _rebind_cir_hashes(payload)
    draft = project_native_facts(parse_native_request(_body(payload)))
    facts = _facts(draft)
    assert len(facts) == 4
    assert all(
        isinstance(cell.observation, SourceCellValue) and cell.observation.value == "0"
        for cell in facts
    )
    assert draft.documents[0].tables[0].header_status == "unknown"
    assert draft.documents[0].tables[0].producer_header_row_count == 0


@pytest.mark.parametrize("inferred,expected", [(True, "unknown"), (False, "ambiguous")])
def test_duplicate_headers_never_overwrite_or_bind(inferred: bool, expected: str) -> None:
    draft = project_native_facts(
        parse_native_request(_body(_payload("duplicate-header", headers=1, inferred=inferred)))
    )
    table = draft.documents[0].tables[0]
    assert table.header_status == expected
    assert table.header_bindings == ()
    labels = table.rows[0].cells
    assert [cell.raw_text for cell in labels] == ["Label", "Label"]
    assert labels[0].evidence_id != labels[1].evidence_id
    assert len(_facts(draft)) == 4


@pytest.mark.parametrize("case", ["blank", "merged"])
def test_unproven_blank_and_merged_header_candidates_are_ambiguous(case: str) -> None:
    payload = _payload("merged" if case == "merged" else "normal", headers=1)
    if case == "blank":
        block = next(
            block
            for block in payload["documents"][0]["canonicalDocument"]["blocks"]
            if "table" in block
        )
        block["table"]["cells"][0].update(rawText="", normalizedText="")
        _rebind_cir_hashes(payload)
    table = project_native_facts(parse_native_request(_body(payload))).documents[0].tables[0]
    assert table.header_status == "ambiguous" and table.header_bindings == ()


def test_isolated_d8_and_header_tab_zero_are_original_coordinate_facts() -> None:
    for kind in ["locator", "normal"]:
        payload = _payload(kind, headers=0)
        block = next(
            block
            for block in payload["documents"][0]["canonicalDocument"]["blocks"]
            if "table" in block
        )
        if kind == "locator":
            block["table"]["cells"] = [
                cell
                for cell in block["table"]["cells"]
                if cell["sourceRefs"][0]["nativeObjectId"].endswith("/D8")
            ]
        else:
            block.update(rawText="Header\n\t0", normalizedText="Header\n\t0")
        _rebind_cir_hashes(payload)
        facts = _facts(project_native_facts(parse_native_request(_body(payload))))
        zeros = [cell for cell in facts if cell.raw_text == "0"]
        assert len(zeros) == 1 and zeros[0].observation == SourceCellValue(value="0")
        if kind == "locator":
            assert len(facts) == 1
            assert (
                zeros[0].native_address,
                zeros[0].absolute_row1,
                zeros[0].row_index0,
                zeros[0].column_index0,
            ) == ("xlsx/sheet/0000/cell/D8", 8, 1, 1)


@pytest.mark.parametrize(
    "cached,unavailable", [(False, False), (True, False), (True, True), (False, True)]
)
def test_formulas_never_observe_expression_numbers_or_cached_zero(
    cached: bool, unavailable: bool
) -> None:
    payload = _payload("formula", headers=0)
    block = next(
        block
        for block in payload["documents"][0]["canonicalDocument"]["blocks"]
        if "table" in block
    )
    cell = next(cell for cell in block["table"]["cells"] if cell.get("formula"))
    if cached:
        cell.update(normalizedText="0", valueType="number")
        cell["qualityFlags"] = [
            flag for flag in cell["qualityFlags"] if flag != "formula_cached_value_missing"
        ]
    if unavailable:
        cell.pop("formula")
        cell["rawText"] = ""
        cell["qualityFlags"].append("formula_text_unavailable")
    _rebind_cir_hashes(payload)
    draft = project_native_facts(parse_native_request(_body(payload)))
    formula = next(item for item in _facts(draft) if item.cell_id == cell["id"])
    assert isinstance(formula.observation, FormulaExpression)
    assert formula.observation.evaluated is False
    assert formula.observation.expression == (None if unavailable else "=1+2")
    assert formula.observation.expression_status == ("unavailable" if unavailable else "available")
    assert formula.observation.cached_text_informational == ("0" if cached else None)
    assert "value" not in formula.observation.model_dump(mode="json", by_alias=True)
    assert "NATIVE_FORMULA_NOT_OBSERVED" in draft.review_reasons
    if unavailable:
        assert "NATIVE_FORMULA_EXPRESSION_UNAVAILABLE" in draft.review_reasons


def test_merge_anchor_once_and_no_covered_or_absent_cells() -> None:
    draft = project_native_facts(parse_native_request(_body(_payload("merged", headers=0))))
    facts = _facts(draft)
    assert len(facts) == 3
    assert [
        (cell.native_address.rsplit("/", 1)[-1], cell.row_span, cell.column_span) for cell in facts
    ] == [("A1", 1, 2), ("A2", 1, 1), ("B2", 1, 1)]


@pytest.mark.parametrize(
    "mutation",
    [
        "dangling",
        "duplicate-evidence",
        "duplicate-fact",
        "wrong-ref",
        "value",
        "scope",
        "version",
        "digest",
        "headers",
        "duplicate-document",
        "document-order",
    ],
)
def test_draft_rejects_duplicate_dangling_and_altered_bindings(mutation: str) -> None:
    draft = project_native_facts(
        parse_native_request(_body(_payload("duplicate-header", headers=0)))
    )
    payload = draft.model_dump(mode="json", by_alias=True, exclude_none=True)
    cells = payload["documents"][0]["tables"][0]["rows"][0]["cells"]
    if mutation == "dangling":
        cells[0]["evidenceId"] = "native_evidence_dangling"
    elif mutation == "duplicate-evidence":
        payload["evidence"].append(copy.deepcopy(payload["evidence"][0]))
    elif mutation == "duplicate-fact":
        cells.append(copy.deepcopy(cells[0]))
    elif mutation == "wrong-ref":
        payload["evidence"][0]["sourceRefs"][0]["nativeObjectId"] = "xlsx/sheet/0000/cell/B1"
    elif mutation == "value":
        cells[0]["observation"]["value"] = "forged"
    elif mutation == "scope":
        payload["workspaceId"] = "other-workspace"
    elif mutation == "version":
        payload["documents"][0]["sourceVersionId"] = "other-version"
    elif mutation == "digest":
        payload["documents"][0]["cirSha256"] = RELEASE
    elif mutation == "headers":
        payload["documents"][0]["tables"][0]["headerBindings"] = ["guessed"]
    elif mutation == "duplicate-document":
        payload["documents"].append(copy.deepcopy(payload["documents"][0]))
        payload["canonicalDocuments"].append(copy.deepcopy(payload["canonicalDocuments"][0]))
    elif mutation == "document-order":
        payload["inputDocumentOrder"].append(payload["inputDocumentOrder"][0])
    with pytest.raises(ValueError):
        NativeFactsDraft.model_validate_json(canonical_json(payload))


@pytest.mark.parametrize("mutation", ["scope", "version", "digest", "nested"])
def test_projection_revalidates_even_model_copies_and_nested_mutation(mutation: str) -> None:
    request = parse_native_request(_body(_payload()))
    if mutation == "scope":
        request = request.model_copy(update={"tenant_id": "wrong-tenant"})
    elif mutation == "version":
        document = request.documents[0].model_copy(update={"source_version_id": "wrong-version"})
        request = request.model_copy(update={"documents": (document,)})
    elif mutation == "digest":
        document = request.documents[0].model_copy(update={"cir_sha256": RELEASE})
        request = request.model_copy(update={"documents": (document,)})
    else:
        request.documents[0].canonical_document.metadata["sheets"][0]["name"] = "mutated"
    with pytest.raises(ValueError):
        project_native_facts(request)


def test_output_and_request_bounds_remain_enforced(monkeypatch) -> None:
    import akc_product_core.native_cir as native
    import akc_product_core.native_facts as facts

    request = parse_native_request(_body(_payload()))
    with monkeypatch.context() as patch:
        patch.setattr(native, "MAX_NATIVE_REQUEST_BYTES", 1)
        with pytest.raises(ValueError, match="request byte limit"):
            project_native_facts(request)
    with monkeypatch.context() as patch:
        patch.setattr(facts, "MAX_NATIVE_FACTS_OUTPUT_BYTES", 1)
        with pytest.raises(ValueError, match="output byte limit"):
            project_native_facts(request)


def test_projection_does_not_change_http_gate_or_v2() -> None:
    request = parse_native_request(_body(_payload()))
    project_native_facts(request)
    body = canonical_json(request).encode()
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    response = client.post("/v3/native-cir/compile", content=body, headers=_signed(body))
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"
    assert client.app.state.product_core_service._cache == {}
    assert client.post("/v2/compile", content=body, headers=_signed(body)).status_code == 422


@pytest.mark.parametrize("raw,available", [("=1+2", True), ("0", False)])
def test_formula_flags_without_formula_field_do_not_turn_display_into_value(
    raw: str, available: bool
) -> None:
    payload = _payload("formula", headers=0)
    block = next(
        block
        for block in payload["documents"][0]["canonicalDocument"]["blocks"]
        if "table" in block
    )
    cell = next(cell for cell in block["table"]["cells"] if cell.get("formula"))
    cell.pop("formula")
    cell.update(
        rawText=raw,
        normalizedText="0",
        valueType="number",
        qualityFlags=["formula_preserved_not_executed"],
    )
    _rebind_cir_hashes(payload)
    draft = project_native_facts(parse_native_request(_body(payload)))
    fact = next(fact for fact in _facts(draft) if fact.cell_id == cell["id"])
    assert isinstance(fact.observation, FormulaExpression)
    assert fact.observation.expression == ("=1+2" if available else None)
    assert fact.observation.cached_text_informational == "0"
    assert fact.observation.evaluated is False
    tampered = draft.model_dump(mode="json", by_alias=True, exclude_none=True)
    row = next(
        row
        for row in tampered["documents"][0]["tables"][0]["rows"]
        if any(item["cellId"] == cell["id"] for item in row["cells"])
    )
    item = next(item for item in row["cells"] if item["cellId"] == cell["id"])
    item["observation"] = {"kind": "source_cell_value", "value": "3"}
    with pytest.raises(ValueError, match="altered"):
        NativeFactsDraft.model_validate_json(canonical_json(tampered))


def test_deterministic_document_table_row_cell_order_with_input_order_binding() -> None:
    first = _payload("normal", headers=0)
    second = _payload("unicode", headers=0)
    envelope = second["documents"][0]
    envelope["nativeId"] = "another-book"
    envelope["sourceId"] = source_id(
        tenant_id=first["tenantId"],
        connector_type=envelope["connectorType"],
        native_id="another-book",
    )
    envelope["sourceVersionId"] = document_version_id(
        source=envelope["sourceId"], content_sha256=envelope["contentSha256"]
    )
    cir = envelope["canonicalDocument"]
    cir.update(documentId=envelope["sourceId"], documentVersionId=envelope["sourceVersionId"])
    for block in cir["blocks"]:
        refs = list(block["sourceRefs"])
        if "table" in block:
            refs.extend(block["table"]["sourceRefs"])
            refs.extend(ref for cell in block["table"]["cells"] for ref in cell["sourceRefs"])
            block["table"]["cells"].reverse()
        for ref in refs:
            ref.update(
                documentId=envelope["sourceId"], documentVersionId=envelope["sourceVersionId"]
            )
    _rebind_cir_hashes(second)
    first["documents"].append(envelope)
    first["documents"].sort(key=lambda item: item["sourceId"], reverse=True)
    request = parse_native_request(_body(first))
    draft = project_native_facts(request)
    assert draft.input_sha256 == sha256_digest(canonical_json(request))
    assert draft.input_document_order == tuple(doc.source_version_id for doc in request.documents)
    assert [doc.source_id for doc in draft.documents] == sorted(
        doc.source_id for doc in request.documents
    )
    for doc in draft.documents:
        for table in doc.tables:
            positions = [
                (cell.row_index0, cell.column_index0) for row in table.rows for cell in row.cells
            ]
            assert positions == sorted(positions)
    assert canonical_json(draft) == canonical_json(project_native_facts(request))
    assert canonical_json(
        NativeFactsDraft.model_validate_json(canonical_json(draft))
    ) == canonical_json(draft)
