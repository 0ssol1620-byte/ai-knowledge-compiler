"""Reusable parse key: reuse is exact, tenant-scoped and accepted-only (U33, S07)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .identity import canonical_sha256, require_sha256, stable_id
from .models import ACCEPTED_VERIFICATION_STATES, VerificationState


@dataclass(frozen=True, slots=True)
class ReusableParseKey:
    tenant_scope: str
    source_sha256: str
    sanitized_recipe_sha256: str
    adapter_version: str
    model_digest: str
    ir_schema: str

    def __post_init__(self) -> None:
        for name in ("tenant_scope", "adapter_version", "model_digest", "ir_schema"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        require_sha256(self.source_sha256, field_name="source_sha256")
        require_sha256(self.sanitized_recipe_sha256, field_name="sanitized_recipe_sha256")

    @property
    def digest(self) -> str:
        return canonical_sha256({name: getattr(self, name) for name in self.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class ParseArtifactRecord:
    artifact_ref: str
    source_instance_ids: tuple[str, ...]


@dataclass(slots=True)
class ParseArtifactIndex:
    """In-memory reference. Persistence and the product integration are out of scope."""

    _artifacts: dict[str, str] = field(default_factory=dict)
    _instances: dict[str, dict[str, None]] = field(default_factory=dict)

    def put(
        self,
        key: ReusableParseKey,
        *,
        artifact_ref: str,
        verification_state: VerificationState,
        source_name: str,
    ) -> str:
        """Store an accepted artifact; return this source name's instance id."""
        if verification_state not in ACCEPTED_VERIFICATION_STATES:
            raise ValueError(f"unverified artifact is not reusable: {verification_state}")
        if not artifact_ref or not source_name:
            raise ValueError("artifact_ref and source_name are required")
        digest = key.digest
        existing = self._artifacts.setdefault(digest, artifact_ref)
        if existing != artifact_ref:
            raise ValueError("a different artifact is already stored under this key")
        instance_id = stable_id("srcinst", key.tenant_scope, key.source_sha256, source_name)
        self._instances.setdefault(digest, {})[instance_id] = None
        return instance_id

    def get(self, key: ReusableParseKey) -> ParseArtifactRecord | None:
        digest = key.digest
        ref = self._artifacts.get(digest)
        if ref is None:
            return None
        return ParseArtifactRecord(ref, tuple(self._instances[digest]))
