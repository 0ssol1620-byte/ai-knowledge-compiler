from __future__ import annotations

import hashlib

import pytest
from akc_security import (
    CdrRequest,
    CdrResult,
    CdrStatus,
    UnavailableCdrAdapter,
    validate_cdr_result,
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_cdr_request_is_bound_to_the_immutable_original() -> None:
    original = b"synthetic-office-container"
    request = CdrRequest(
        filename="source.docx",
        mime_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        source_sha256=digest(original),
        payload=original,
    )
    assert request.source_sha256 == digest(original)

    with pytest.raises(ValueError, match="digest mismatch"):
        CdrRequest(
            filename="source.docx",
            mime_type=request.mime_type,
            source_sha256="0" * 64,
            payload=original,
        )


def test_sanitized_derivative_requires_independent_hash_and_provider_evidence() -> None:
    original = b"original"
    sanitized = b"sanitized derivative"
    result = validate_cdr_result(
        CdrResult(
            status=CdrStatus.SANITIZED,
            provider="synthetic-cdr",
            revision="ruleset-2026-07-30",
            sanitized_payload=sanitized,
            sanitized_sha256=digest(sanitized),
        ),
        source_sha256=digest(original),
        max_output_bytes=1024,
    )
    assert result.sanitized_sha256 == digest(sanitized)

    with pytest.raises(ValueError, match="must not impersonate"):
        validate_cdr_result(
            CdrResult(
                status=CdrStatus.SANITIZED,
                provider="synthetic-cdr",
                revision="ruleset-2026-07-30",
                sanitized_payload=original,
                sanitized_sha256=digest(original),
            ),
            source_sha256=digest(original),
            max_output_bytes=1024,
        )


@pytest.mark.asyncio
async def test_unconfigured_cdr_is_explicitly_fail_closed() -> None:
    original = b"original"
    adapter = UnavailableCdrAdapter()
    result = await adapter.sanitize(
        CdrRequest(
            filename="source.pdf",
            mime_type="application/pdf",
            source_sha256=digest(original),
            payload=original,
        )
    )
    assert result.status is CdrStatus.UNAVAILABLE
    assert not await adapter.ready()
