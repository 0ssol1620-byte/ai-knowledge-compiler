"""Authentication and idempotency tests for the Product-Core HTTP boundary."""

from __future__ import annotations

from datetime import UTC, datetime

from akc_cir.base import canonical_json
from akc_product_core.api import create_product_core_app
from akc_product_core.auth import sign_product_core_request
from fastapi.testclient import TestClient
from test_product_core_bridge import RELEASE, _document, _request

SECRET = b"foundation-product-core-test-secret-32-bytes-minimum"


def _signed(body: bytes, request_id: str) -> dict[str, str]:
    timestamp = int(datetime.now(tz=UTC).timestamp())
    return {
        "content-type": "application/json",
        **sign_product_core_request(
            body=body,
            request_id=request_id,
            timestamp=timestamp,
            secret=SECRET,
        ),
    }


def _body(request_id: str, *, text: str = "Revenue is 100 million won.") -> bytes:
    request = _request((_document("filing-a", text),), request_id=request_id)
    return canonical_json(
        request.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()


def test_signed_compile_is_candidate_only_and_exact_replay_is_idempotent() -> None:
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    body = _body("api-compile-1")
    headers = _signed(body, "api-compile-1")

    first = client.post("/v2/compile", content=body, headers=headers)
    replay = client.post("/v2/compile", content=body, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["receipt"]["candidatePromotion"] is False
    assert first.json()["receipt"]["matchingPolicy"] == "legacy"
    assert first.headers["cache-control"] == "no-store"


def test_body_tampering_and_request_id_mismatch_fail_authentication() -> None:
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    body = _body("api-compile-2")
    headers = _signed(body, "api-compile-2")

    tampered = client.post("/v2/compile", content=body + b" ", headers=headers)
    mismatch = client.post(
        "/v2/compile",
        content=body,
        headers=_signed(body, "different-request-id"),
    )

    assert tampered.status_code == 401
    assert tampered.json()["code"] == "CORE_INPUT_DIGEST_INVALID"
    assert mismatch.status_code == 401
    assert mismatch.json()["code"] == "CORE_REQUEST_ID_MISMATCH"


def test_same_idempotency_key_cannot_be_reused_for_different_input() -> None:
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    first = _body("api-compile-3", text="Revenue is 100 million won.")
    changed_request = _request(
        (_document("filing-a", "Revenue is 120 million won."),),
        request_id="api-compile-3b",
    ).model_copy(update={"idempotency_key": "idem-api-compile-3"})
    changed = canonical_json(
        changed_request.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()

    accepted = client.post("/v2/compile", content=first, headers=_signed(first, "api-compile-3"))
    conflict = client.post(
        "/v2/compile", content=changed, headers=_signed(changed, "api-compile-3b")
    )

    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CORE_IDEMPOTENCY_CONFLICT"


def test_customer_data_policy_is_disabled_by_default() -> None:
    client = TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))
    request = _request(
        (_document("filing-a", "Revenue is 100 million won."),),
        request_id="api-compile-4",
    )
    request = request.model_copy(
        update={
            "route": request.route.model_copy(update={"privacy_policy": "approved_customer_data"})
        }
    )
    body = canonical_json(
        request.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()

    response = client.post("/v2/compile", content=body, headers=_signed(body, "api-compile-4"))

    assert response.status_code == 403
    assert response.json()["code"] == "CORE_CUSTOMER_DATA_DISABLED"
