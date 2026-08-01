"""Canonical identity and hashing helpers used by every runtime contract."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the canonical encoder."""


def _normalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _normalize(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError("non-finite Decimal values are not canonical")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalizationError("datetime values must be timezone-aware")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"$bytes_sha256": hashlib.sha256(value).hexdigest(), "$bytes_size": len(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("non-finite float values are not canonical")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("canonical mapping keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, (set, frozenset)):
        members = [_normalize(item) for item in value]
        return sorted(
            members,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise CanonicalizationError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return stable UTF-8 JSON with strict key and numeric semantics."""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_hex(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def stable_id(namespace: str, *parts: Any) -> str:
    if not namespace or not namespace.replace("_", "").isalnum():
        raise ValueError("namespace must contain only alphanumeric characters and underscores")
    digest = canonical_sha256({"namespace": namespace, "parts": parts})
    return f"{namespace}_{digest[:32]}"


def require_sha256(value: str, *, field_name: str = "sha256") -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase 64-character sha256")
    return value


__all__ = [
    "CanonicalizationError",
    "canonical_json",
    "canonical_sha256",
    "require_sha256",
    "sha256_hex",
    "stable_id",
]
