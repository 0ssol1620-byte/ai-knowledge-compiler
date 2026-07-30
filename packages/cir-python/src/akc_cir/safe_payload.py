"""Validation for public event/error metadata that must never carry document bodies."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

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
        "document",
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


def _canonical_key(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).casefold()


def _sensitive_key(value: str) -> bool:
    canonical = _canonical_key(value)
    return (
        canonical in _SENSITIVE_KEYS
        or canonical.endswith(("_api_key", "_credential", "_password", "_secret"))
        or canonical.startswith(("raw_output", "raw_text", "source_text"))
    )


def validate_public_payload(value: Any, *, path: str = "$") -> Any:
    """Recursively reject content, secrets, bytes, NaN, and unbounded strings."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _sensitive_key(text_key) and item is not None:
                raise ValueError(f"sensitive public payload key at {path}.{text_key}")
            result[text_key] = validate_public_payload(item, path=f"{path}.{text_key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 1000:
            raise ValueError(f"public payload sequence is too large at {path}")
        return [
            validate_public_payload(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        if len(value) > 2048:
            raise ValueError(f"public payload string is too long at {path}")
        return value
    if isinstance(value, (bytes, bytearray)):
        raise ValueError(f"binary public payload value is forbidden at {path}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite public payload number at {path}")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError(f"unsupported public payload type at {path}")
