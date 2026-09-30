"""Immutable reference verification at the signed HTTP candidate boundary."""

import json

import pytest
from akc_cir.base import canonical_json
from akc_product_core.api import create_product_core_app
from fastapi.testclient import TestClient

from .test_product_core_api import SECRET, _signed
from .test_product_core_bridge import RELEASE, _document, _request


def _compile_with_keys(source: str | None = None, ocr: str | None = None) -> dict:
    document = _document("policy", "Records must be retained for 30 days.")
    changes = {}
    if source is not None:
        changes["immutable_object_key"] = source
    if ocr is not None:
        changes["ocr_object_key"] = ocr
    request = _request((document.model_copy(update=changes),), request_id="immutable-check")
    body = canonical_json(request.model_dump(mode="json", by_alias=True)).encode()
    with TestClient(
        create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE)
    ) as client:
        response = client.post(
            "/v2/compile", content=body, headers=_signed(body, request.request_id)
        )
    assert response.status_code == 200
    return response.json()


def test_digest_bound_input_check_is_in_http_receipt_and_package() -> None:
    result = _compile_with_keys()
    assert result["candidate"]["validation"]["immutableInputsOnly"] is True
    report = next(
        file
        for file in result["candidate"]["package"]["files"]
        if file["path"] == "validation/report.json"
    )
    assert json.loads(report["content"])["immutableInputsOnly"] is True
    assert "IMMUTABLE_INPUT_BINDING_INVALID" not in result["candidate"]["reviewReasons"]


@pytest.mark.parametrize("field", ["source", "ocr"])
@pytest.mark.parametrize(
    "mutation", ["mutable", "tenant", "workspace", "document", "digest", "nested"]
)
def test_unbound_input_cannot_claim_immutable_or_be_promotable(field: str, mutation: str) -> None:
    document = _document("policy", "Records must be retained for 30 days.")
    key = document.immutable_object_key if field == "source" else document.ocr_object_key
    parts = key.split("/")
    index = {"mutable": 0, "tenant": 1, "workspace": 2, "document": 3, "digest": 4}.get(mutation)
    if index is not None:
        parts[index] = "different"
    else:
        parts.insert(-1, "nested")
    result = _compile_with_keys(**{field: "/".join(parts)})
    assert result["candidate"]["validation"]["immutableInputsOnly"] is False
    assert result["candidate"]["validation"]["status"] != "passed"
    assert result["candidate"]["lifecycle"] == "review_required"
    assert "IMMUTABLE_INPUT_BINDING_INVALID" in result["candidate"]["reviewReasons"]


def test_source_and_ocr_alias_cannot_claim_immutable() -> None:
    document = _document("policy", "Records must be retained for 30 days.")
    result = _compile_with_keys(ocr=document.immutable_object_key)
    assert result["candidate"]["validation"]["immutableInputsOnly"] is False


def test_logical_source_may_differ_from_upload_revision_object_id() -> None:
    document = _document("policy", "Records must be retained for 30 days.")
    result = _compile_with_keys(
        source=document.immutable_object_key.replace("/policy/", "/upload-uuid/"),
        ocr=document.ocr_object_key.replace("/policy/", "/upload-uuid/"),
    )
    assert result["candidate"]["validation"]["immutableInputsOnly"] is True
