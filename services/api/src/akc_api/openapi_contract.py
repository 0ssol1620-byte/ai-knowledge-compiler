"""Reviewed OpenAPI refinements that must match runtime policy."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI

# Section 37 of the v4 authority requires an idempotency key for every
# collection create/finalize/compile/export/delete operation.  The handlers
# intentionally accept ``None`` so they can return the product error envelope
# with HTTP 428 instead of FastAPI's generic 422 validation response.  Mark the
# same header as required in OpenAPI here so generated clients do not model it
# as optional.
V4_IDEMPOTENCY_REQUIRED_OPERATIONS = frozenset(
    {
        ("post", "/v1/collections"),
        ("post", "/v1/collections/{collection_id}/sources/local"),
        ("post", "/v1/collections/{collection_id}/files/plan"),
        ("post", "/v1/collections/{collection_id}/upload/complete"),
        ("post", "/v1/collections/{collection_id}/preflight"),
        ("post", "/v1/collections/{collection_id}/compile"),
        ("post", "/v1/collections/{collection_id}/exports"),
        ("delete", "/v1/collections/{collection_id}"),
    }
)


def _mark_idempotency_key_required(operation: dict[str, Any]) -> None:
    parameters = operation.get("parameters")
    if not isinstance(parameters, list):
        raise RuntimeError("v4 idempotent operation has no OpenAPI parameters")
    for raw_parameter in parameters:
        if not isinstance(raw_parameter, dict):
            continue
        if raw_parameter.get("in") != "header" or raw_parameter.get("name") != (
            "Idempotency-Key"
        ):
            continue
        raw_parameter["required"] = True
        raw_parameter["schema"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "pattern": r"^[!-~]+$",
            "title": "Idempotency-Key",
        }
        operation.setdefault("responses", {}).setdefault(
            "428",
            {
                "description": "Idempotency-Key header is required",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": True,
                        }
                    }
                },
            },
        )
        return
    raise RuntimeError("v4 idempotent operation does not declare Idempotency-Key")


def install_v4_openapi_contract(app: FastAPI) -> None:
    """Bind fail-closed v4 collection requirements into generated OpenAPI."""

    original_openapi = app.openapi

    def reviewed_openapi() -> dict[str, Any]:
        document = original_openapi()
        paths = cast(dict[str, Any], document.get("paths", {}))
        for method, path in sorted(V4_IDEMPOTENCY_REQUIRED_OPERATIONS):
            path_item = paths.get(path)
            if not isinstance(path_item, dict):
                raise RuntimeError(f"v4 required OpenAPI path is missing: {path}")
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                raise RuntimeError(f"v4 required OpenAPI operation is missing: {method} {path}")
            _mark_idempotency_key_required(operation)
        return document

    cast(Any, app).openapi = reviewed_openapi


__all__ = ["V4_IDEMPOTENCY_REQUIRED_OPERATIONS", "install_v4_openapi_contract"]
