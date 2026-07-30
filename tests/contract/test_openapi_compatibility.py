from __future__ import annotations

from scripts.check_openapi_compat import breaking_changes, current_openapi


def _spec(request_schema: dict, response_schema: dict) -> dict:
    return {
        "openapi": "3.1.0",
        "paths": {
            "/v1/example": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": request_schema}},
                    },
                    "responses": {
                        "200": {"content": {"application/json": {"schema": response_schema}}}
                    },
                }
            }
        },
    }


def test_breaking_detector_catches_request_tightening_and_response_removal() -> None:
    baseline = _spec(
        {
            "type": "object",
            "properties": {"optional": {"type": "string"}},
        },
        {
            "type": "object",
            "required": ["stable"],
            "properties": {"stable": {"type": "string"}},
        },
    )
    candidate = _spec(
        {
            "type": "object",
            "required": ["optional"],
            "properties": {"optional": {"type": "string"}},
        },
        {"type": "object", "properties": {}},
    )

    changes = breaking_changes(baseline, candidate)
    assert any("new required request field" in change for change in changes)
    assert any("required response field removed" in change for change in changes)
    assert any("response field removed" in change for change in changes)


def test_current_openapi_is_stable_against_frozen_baseline() -> None:
    from scripts.check_openapi_compat import BASELINE

    baseline = __import__("json").loads(BASELINE.read_text(encoding="utf-8"))
    assert breaking_changes(baseline, current_openapi()) == []
