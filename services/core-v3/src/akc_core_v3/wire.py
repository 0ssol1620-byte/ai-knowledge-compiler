"""The signed envelope both v3 compile paths share.

Extracted when the initial-compile path arrived, because the alternative was two
copies of an HMAC check. Two copies of a signature check do not stay identical:
one gets a fix and the other keeps the bug, and the one that keeps it is
whichever has fewer tests.

The order of the checks is part of the contract, not an implementation detail.
A caller distinguishes "your clock is wrong" from "your key is wrong" by the code
it gets back, so the sequence below -- shape, then freshness, then body digest,
then signature, then payload -- is fixed and asserted by the refusal tests.

Nothing here knows what a compile is. It returns a parsed request or raises, and
each service adds the checks its own operation class requires.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import Any

REQUEST_SCHEMA = "tavonel.product_core.compile_request.v3"
RESPONSE_SCHEMA = "tavonel.product_core.compile_response.v3"
RUNTIME = "tavonel-python-core-v2"

#: The signature covers these three, joined by newlines, exactly as the client
#: builds them in `dispatchProductCoreRevision`.
SIGNED_FIELDS = ("timestamp", "requestId", "inputSha256")

#: Requests older than this are refused whatever their signature says. A valid
#: signature on a replayed body is still a replay.
MAX_CLOCK_SKEW_SECONDS = 300


class CompileRefused(RuntimeError):
    """A refusal with a code the Product can act on."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def require(condition: object, code: str, status: int = 400) -> None:
    if not condition:
        raise CompileRefused(code, status)


def check_release_digest(core_release_digest: str) -> None:
    require(
        core_release_digest.startswith("sha256:") and len(core_release_digest) == 71,
        "CORE_V3_RELEASE_DIGEST_INVALID",
        500,
    )


def verify_envelope(
    *,
    secret: bytes,
    now: Callable[[], float],
    headers: Mapping[str, str],
    body: bytes,
    operation_class: str,
) -> dict[str, Any]:
    """Authenticate the request and return it parsed, or raise `CompileRefused`."""
    lower = {key.lower(): value for key, value in headers.items()}
    timestamp = lower.get("x-tavonel-core-timestamp", "")
    request_id = lower.get("x-tavonel-core-request-id", "")
    input_sha256 = lower.get("x-tavonel-input-sha256", "")
    signature = lower.get("x-tavonel-core-signature", "")
    require(timestamp.isdigit(), "CORE_V3_TIMESTAMP_INVALID", 401)
    require(request_id, "CORE_V3_REQUEST_ID_MISSING", 401)
    require(
        abs(now() - int(timestamp)) <= MAX_CLOCK_SKEW_SECONDS,
        "CORE_V3_TIMESTAMP_OUT_OF_WINDOW",
        401,
    )
    expected = "sha256:" + sha256(body).hexdigest()
    require(hmac.compare_digest(input_sha256, expected), "CORE_V3_INPUT_DIGEST_MISMATCH", 401)
    expected_signature = hmac.new(
        secret,
        f"{timestamp}\n{request_id}\n{input_sha256}".encode(),
        sha256,
    ).hexdigest()
    require(hmac.compare_digest(signature, expected_signature), "CORE_V3_SIGNATURE_INVALID", 401)
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CompileRefused("CORE_V3_BODY_NOT_JSON", 400) from error
    require(isinstance(parsed, dict), "CORE_V3_BODY_NOT_JSON")
    request: dict[str, Any] = parsed
    require(request.get("schemaVersion") == REQUEST_SCHEMA, "CORE_V3_SCHEMA_UNSUPPORTED")
    require(request.get("requestId") == request_id, "CORE_V3_REQUEST_ID_MISMATCH", 401)
    route = request.get("route") or {}
    require(
        route.get("operationClass") == operation_class,
        "CORE_V3_OPERATION_CLASS_UNSUPPORTED",
    )
    return request
