"""Registry failures. Every one of them is fail-closed: no silent fallback."""

from __future__ import annotations


class RegistryError(RuntimeError):
    """A registry step could not complete honestly."""


class SourceUnavailableError(RegistryError):
    """An official source could not be read (network, auth, or missing repo)."""


class SchemaValidationError(RegistryError):
    """A generated registry file does not satisfy its schema."""


__all__ = ["RegistryError", "SchemaValidationError", "SourceUnavailableError"]
