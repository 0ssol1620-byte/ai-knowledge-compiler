"""Raw-body authentication for the Product-Core service boundary."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from akc_cir.base import sha256_digest

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ProductCoreAuthenticationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class VerifiedTransport:
    request_id: str
    input_sha256: str
    timestamp: int


def sign_product_core_request(
    *, body: bytes, request_id: str, timestamp: int, secret: bytes
) -> dict[str, str]:
    """Return the exact headers a Product caller must send."""

    if len(secret) < 32:
        raise ValueError("Product-Core HMAC secret must contain at least 32 bytes")
    input_sha256 = sha256_digest(body)
    signature = hmac.new(
        secret,
        f"{timestamp}\n{request_id}\n{input_sha256}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-tavonel-core-timestamp": str(timestamp),
        "x-tavonel-core-request-id": request_id,
        "x-tavonel-input-sha256": input_sha256,
        "x-tavonel-core-signature": signature,
    }


def verify_product_core_request(
    *,
    body: bytes,
    headers: Mapping[str, str],
    secret: bytes,
    now: datetime | None = None,
    maximum_age_seconds: int = 300,
) -> VerifiedTransport:
    """Verify timestamp, digest and HMAC without parsing attacker-controlled JSON."""

    if len(secret) < 32:
        raise ProductCoreAuthenticationError("CORE_AUTH_NOT_CONFIGURED")
    lowered = {key.casefold(): value for key, value in headers.items()}
    request_id = lowered.get("x-tavonel-core-request-id", "")
    input_sha256 = lowered.get("x-tavonel-input-sha256", "")
    signature = lowered.get("x-tavonel-core-signature", "")
    raw_timestamp = lowered.get("x-tavonel-core-timestamp", "")
    if not request_id or len(request_id) > 256:
        raise ProductCoreAuthenticationError("CORE_REQUEST_ID_INVALID")
    try:
        timestamp = int(raw_timestamp)
    except ValueError as exc:
        raise ProductCoreAuthenticationError("CORE_TIMESTAMP_INVALID") from exc
    clock = now or datetime.now(tz=UTC)
    if abs(int(clock.timestamp()) - timestamp) > maximum_age_seconds:
        raise ProductCoreAuthenticationError("CORE_TIMESTAMP_EXPIRED")
    actual_digest = sha256_digest(body)
    if not hmac.compare_digest(input_sha256, actual_digest):
        raise ProductCoreAuthenticationError("CORE_INPUT_DIGEST_INVALID")
    if not _HEX64.fullmatch(signature):
        raise ProductCoreAuthenticationError("CORE_SIGNATURE_INVALID")
    expected = sign_product_core_request(
        body=body,
        request_id=request_id,
        timestamp=timestamp,
        secret=secret,
    )["x-tavonel-core-signature"]
    if not hmac.compare_digest(signature, expected):
        raise ProductCoreAuthenticationError("CORE_SIGNATURE_INVALID")
    return VerifiedTransport(
        request_id=request_id,
        input_sha256=input_sha256,
        timestamp=timestamp,
    )


__all__ = [
    "ProductCoreAuthenticationError",
    "VerifiedTransport",
    "sign_product_core_request",
    "verify_product_core_request",
]
