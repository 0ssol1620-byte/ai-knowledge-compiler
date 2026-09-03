"""Process-local RunPod credential selection with secret-safe metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from benchmark.v6.contracts import ContractError

RUNPOD_KEY_ENV: Final = "RUNPOD_API_KEY"
RUNPOD_FALLBACK_KEY_ENV: Final = "RUNPOD_API_KEY_FALLBACK"

__all__ = [
    "RUNPOD_FALLBACK_KEY_ENV",
    "RUNPOD_KEY_ENV",
    "RunPodCredentialSet",
]


def _validate(value: str, *, label: str) -> str:
    key = value.strip()
    if not key:
        return ""
    if any(character.isspace() for character in key):
        raise ContractError(f"{label} is malformed")
    return key


@dataclass(frozen=True, slots=True, repr=False)
class RunPodCredentialSet:
    """One primary and at most one fallback key, never printable as values."""

    _keys: tuple[str, ...]

    @classmethod
    def from_environment(cls, *, required: bool = True) -> RunPodCredentialSet:
        primary = _validate(os.environ.get(RUNPOD_KEY_ENV, ""), label=RUNPOD_KEY_ENV)
        fallback = _validate(
            os.environ.get(RUNPOD_FALLBACK_KEY_ENV, ""), label=RUNPOD_FALLBACK_KEY_ENV
        )
        keys: list[str] = []
        for value in (primary, fallback):
            if value and value not in keys:
                keys.append(value)
        if required and not keys:
            raise ContractError("RUNPOD_API_KEY is required when provider access is enabled")
        return cls(tuple(keys))

    @property
    def primary(self) -> str:
        if not self._keys:
            raise ContractError("RunPod credential set is empty")
        return self._keys[0]

    @property
    def fallback(self) -> str | None:
        return self._keys[1] if len(self._keys) > 1 else None

    @property
    def candidates(self) -> tuple[str, ...]:
        """Ordered process-local candidates. Values must never be serialized."""
        return self._keys

    @property
    def count(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return f"RunPodCredentialSet(count={self.count}, secrets='[REDACTED]')"