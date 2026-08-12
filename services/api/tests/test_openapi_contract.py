from __future__ import annotations

from typing import Any

from akc_api.main import create_app
from akc_api.openapi_contract import V4_IDEMPOTENCY_REQUIRED_OPERATIONS


def _idempotency_parameter(operation: dict[str, Any]) -> dict[str, Any]:
    return next(
        parameter
        for parameter in operation["parameters"]
        if parameter.get("in") == "header" and parameter.get("name") == "Idempotency-Key"
    )


def test_v4_collection_idempotency_contract_is_required_and_bounded() -> None:
    document = create_app().openapi()

    for method, path in V4_IDEMPOTENCY_REQUIRED_OPERATIONS:
        operation = document["paths"][path][method]
        parameter = _idempotency_parameter(operation)
        assert parameter == {
            "name": "Idempotency-Key",
            "in": "header",
            "required": True,
            "schema": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
                "pattern": r"^[!-~]+$",
                "title": "Idempotency-Key",
            },
        }
        assert operation["responses"]["428"]["description"] == (
            "Idempotency-Key header is required"
        )


def test_v4_masterplan_api_surface_is_present() -> None:
    paths = create_app().openapi()["paths"]
    required = {
        ("post", "/v1/collections"),
        ("post", "/v1/collections/{collection_id}/sources/local"),
        ("post", "/v1/collections/{collection_id}/files/plan"),
        ("get", "/v1/collections/{collection_id}/upload"),
        ("post", "/v1/collections/{collection_id}/upload/complete"),
        ("post", "/v1/collections/{collection_id}/preflight"),
        ("get", "/v1/collections/{collection_id}/estimate"),
        ("post", "/v1/collections/{collection_id}/compile"),
        ("get", "/v1/collections/{collection_id}/events"),
        ("get", "/v1/collections/{collection_id}/integrity"),
        ("get", "/v1/collections/{collection_id}/knowledge"),
        ("post", "/v1/collections/{collection_id}/exports"),
        ("get", "/v1/exports/{export_id}/download"),
        ("delete", "/v1/collections/{collection_id}"),
    }

    assert all(path in paths and method in paths[path] for method, path in required)
