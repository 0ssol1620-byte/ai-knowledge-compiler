from __future__ import annotations

import uuid
from typing import Any

from akc_api.database import _request_context_hint
from akc_api.security import generate_api_key
from akc_api.settings import Settings
from starlette.requests import Request


def _request(raw_key: str) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/v1/projects",
        "raw_path": b"/v1/projects",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {raw_key}".encode())],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    return Request(scope)


def test_current_api_key_keeps_unique_display_prefix_and_rls_hint() -> None:
    tenant_id = uuid.uuid4()

    first, first_prefix, _ = generate_api_key(tenant_id)
    second, second_prefix, _ = generate_api_key(tenant_id)

    assert first != second
    assert first_prefix != second_prefix
    assert len(first_prefix) == len(second_prefix) == 24
    assert first.startswith(first_prefix)
    assert second.startswith(second_prefix)
    assert _request_context_hint(_request(first), Settings(env="test")) == (
        tenant_id,
        None,
    )


def test_legacy_api_key_hint_remains_narrowing_compatible() -> None:
    tenant_id = uuid.uuid4()
    legacy = f"akc_live_{tenant_id.hex}_legacy_random_with_underscores"

    assert _request_context_hint(_request(legacy), Settings(env="test")) == (
        tenant_id,
        None,
    )
