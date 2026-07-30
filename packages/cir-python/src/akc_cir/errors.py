"""Safe public error envelope."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, cast

from pydantic import Field, StringConstraints, field_validator

from .base import ContractModel, StableId
from .safe_payload import validate_public_payload


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_SIGNATURE_MISMATCH = "FILE_SIGNATURE_MISMATCH"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_MALICIOUS = "FILE_MALICIOUS"
    ARCHIVE_UNSAFE = "ARCHIVE_UNSAFE"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"  # noqa: S105  # nosec B105
    INVALID_PASSWORD = "INVALID_PASSWORD"  # noqa: S105  # nosec B105
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    URL_BLOCKED = "URL_BLOCKED"
    ROUTE_UNAVAILABLE = "ROUTE_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_INVALID_OUTPUT = "PROVIDER_INVALID_OUTPUT"
    QUALITY_REVIEW_REQUIRED = "QUALITY_REVIEW_REQUIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorEnvelope(ContractModel):
    schema_version: str = "error-1.0.0"
    code: ErrorCode
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]
    retryable: bool = False
    trace_id: StableId
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def reject_sensitive_details(cls, value: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], validate_public_payload(value))
