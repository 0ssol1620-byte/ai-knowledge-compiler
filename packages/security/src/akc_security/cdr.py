"""Provider-neutral Content Disarm and Reconstruction contracts.

The original object is never replaced.  A successful adapter returns a new,
hash-bound derivative that callers store separately and use only for parsing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CdrStatus(StrEnum):
    SANITIZED = "sanitized"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CdrRequest:
    filename: str
    mime_type: str
    source_sha256: str
    payload: bytes

    def __post_init__(self) -> None:
        if not self.filename or len(self.filename) > 240:
            raise ValueError("invalid CDR filename")
        if not self.mime_type or len(self.mime_type) > 160:
            raise ValueError("invalid CDR MIME type")
        if not _SHA256.fullmatch(self.source_sha256):
            raise ValueError("invalid source SHA-256")
        if hashlib.sha256(self.payload).hexdigest() != self.source_sha256:
            raise ValueError("CDR source digest mismatch")


@dataclass(frozen=True, slots=True)
class CdrResult:
    status: CdrStatus
    provider: str
    revision: str
    sanitized_payload: bytes | None = None
    sanitized_sha256: str | None = None
    reason_code: str | None = None


class CdrAdapter(Protocol):
    async def sanitize(self, request: CdrRequest) -> CdrResult: ...

    async def ready(self) -> bool: ...

    async def aclose(self) -> None: ...


class UnavailableCdrAdapter:
    """Fail-closed adapter used when CDR is enabled without a provider."""

    async def sanitize(self, request: CdrRequest) -> CdrResult:
        del request
        return CdrResult(
            status=CdrStatus.UNAVAILABLE,
            provider="unavailable",
            revision="unconfigured",
            reason_code="CDR_UNAVAILABLE",
        )

    async def ready(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None


def validate_cdr_result(
    result: CdrResult,
    *,
    source_sha256: str,
    max_output_bytes: int,
) -> CdrResult:
    """Reject ambiguous or unverifiable provider responses."""

    if result.status is CdrStatus.SANITIZED:
        payload = result.sanitized_payload
        digest = result.sanitized_sha256
        if payload is None or digest is None:
            raise ValueError("CDR sanitized result is incomplete")
        if not payload or len(payload) > max_output_bytes:
            raise ValueError("CDR sanitized result size is invalid")
        if not _SHA256.fullmatch(digest):
            raise ValueError("CDR sanitized digest is invalid")
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("CDR sanitized digest mismatch")
        if digest == source_sha256:
            raise ValueError("CDR derivative must not impersonate the original")
        if not result.provider.strip() or not result.revision.strip():
            raise ValueError("CDR provider evidence is missing")
    elif result.sanitized_payload is not None or result.sanitized_sha256 is not None:
        raise ValueError("non-sanitized CDR result cannot contain a derivative")
    return result
