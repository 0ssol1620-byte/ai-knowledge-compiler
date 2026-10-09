"""Validate the scalar and collection shapes of persisted compiler records."""

from __future__ import annotations

from collections.abc import Mapping


def record_integer(value: object) -> int:
    if not isinstance(value, (int, float, str)):
        raise ValueError("compiler record integer must be numeric or a numeric string")
    return int(value)


def record_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError("compiler record sequence must contain strings")
    return tuple(str(item) for item in value)


def record_scope(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("compiler record scope must be a mapping")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise ValueError("compiler record scope keys and values must be strings")
    return {str(key): str(item) for key, item in value.items()}
