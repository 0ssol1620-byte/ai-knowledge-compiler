"""Fail-closed telemetry redaction for document-processing systems."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from akc_cir import ContractModel

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "body",
        "content",
        "cookie",
        "credential",
        "decrypted",
        "document_text",
        "password",
        "prompt",
        "raw_output",
        "raw_text",
        "secret",
        "source_text",
        "token",
    }
)
_FILENAME_KEYS = frozenset({"filename", "file_name", "source_filename", "source_file"})
_PSEUDONYM_KEYS = frozenset(
    {"tenant_id", "user_id", "document_id", "document_version_id", "project_id", "job_id"}
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b")
_SECRET_TOKEN = re.compile(
    r"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b",
    re.IGNORECASE,
)
_LONG_DIGITS = re.compile(r"(?<!\d)\d{9,19}(?!\d)")


class TelemetryPolicy(ContractModel):
    max_string_length: int = 256
    redact_filenames: bool = True
    pseudonymize_identifiers: bool = True
    strip_url_query: bool = True


def _canonical_key(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", key).casefold()


def _is_sensitive_key(key: str) -> bool:
    return (
        key in _SENSITIVE_KEYS
        or key.endswith(("_api_key", "_credential", "_password", "_secret"))
        or key.startswith(("raw_output", "raw_text", "source_text"))
    )


def _pseudonym(value: object, key: bytes | None) -> str:
    if key is None:
        return "[ID]"
    digest = hmac.new(key, str(value).encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"id_{digest}"


def _redact_string(value: str, policy: TelemetryPolicy) -> str:
    result = _BEARER.sub(REDACTED, value)
    result = _JWT.sub(REDACTED, result)
    result = _SECRET_TOKEN.sub(REDACTED, result)
    result = _EMAIL.sub("[EMAIL]", result)
    result = _LONG_DIGITS.sub("[NUMBER]", result)
    if policy.strip_url_query and result.startswith(("https://", "http://")):
        parts = urlsplit(result)
        result = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if len(result) > policy.max_string_length:
        result = result[: policy.max_string_length] + "…[TRUNCATED]"
    return result


def redact_telemetry(
    value: Any,
    *,
    policy: TelemetryPolicy | None = None,
    pseudonym_key: bytes | None = None,
) -> Any:
    policy = policy or TelemetryPolicy()
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            canonical = _canonical_key(text_key)
            if _is_sensitive_key(canonical):
                output[text_key] = REDACTED
            elif policy.redact_filenames and canonical in _FILENAME_KEYS:
                output[text_key] = "[FILENAME]"
            elif policy.pseudonymize_identifiers and canonical in _PSEUDONYM_KEYS:
                output[text_key] = _pseudonym(item, pseudonym_key)
            else:
                output[text_key] = redact_telemetry(
                    item,
                    policy=policy,
                    pseudonym_key=pseudonym_key,
                )
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            redact_telemetry(item, policy=policy, pseudonym_key=pseudonym_key) for item in value
        ]
    if isinstance(value, str):
        return _redact_string(value, policy)
    if isinstance(value, bytes):
        return "[BYTES]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"[{type(value).__name__.upper()}]"


def contains_obvious_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            canonical = _canonical_key(str(key))
            if _is_sensitive_key(canonical) and item != REDACTED:
                return True
            if contains_obvious_secret(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_obvious_secret(item) for item in value)
    if isinstance(value, str):
        return bool(_BEARER.search(value) or _JWT.search(value) or _SECRET_TOKEN.search(value))
    return False
