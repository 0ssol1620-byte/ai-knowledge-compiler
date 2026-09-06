"""Content-addressed derivation manifests and tenant-scoped cache semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

from .dependency import DependencyChannel

__all__ = [
    "ContentAddressedCache",
    "DerivationManifest",
    "ExecutionClass",
]


class ExecutionClass(StrEnum):
    PURE = "PURE"
    PINNED_STOCHASTIC = "PINNED_STOCHASTIC"
    IMPURE = "IMPURE"


def _digest(payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DerivationManifest:
    """Replay contract for one derived artifact.

    Evidence occurrence ids are always retained for provenance. They enter the
    cache key only when the computation declares locator/visual/structural
    sensitivity; a semantic-only artifact therefore survives a page move while
    still saying exactly which occurrence was observed when it was produced.
    """

    artifact_id: str
    tenant_id: str
    logical_unit_ids: tuple[str, ...] = ()
    evidence_occurrence_ids: tuple[str, ...] = ()
    source_content_hashes: tuple[str, ...] = ()
    dependency_channels: frozenset[DependencyChannel] = field(
        default_factory=lambda: frozenset({DependencyChannel.SEMANTIC})
    )
    parser: str = ""
    parser_version: str = ""
    model: str = ""
    model_version: str = ""
    config_fingerprint: str = ""
    calibration_artifact_id: str = ""
    recovery_trace_id: str = ""
    generation_id: str = ""
    execution_class: ExecutionClass = ExecutionClass.PURE
    stochastic_seed: int | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.tenant_id:
            raise ValueError("artifact_id and tenant_id are required")
        if not self.dependency_channels:
            raise ValueError("derivation must declare dependency channels")
        if self.execution_class is ExecutionClass.PINNED_STOCHASTIC:
            if self.stochastic_seed is None:
                raise ValueError("PINNED_STOCHASTIC derivations require a seed")
            if self.model and not self.model_version:
                raise ValueError("pinned stochastic model derivations require model_version")

    @property
    def reusable(self) -> bool:
        return self.execution_class is not ExecutionClass.IMPURE

    @property
    def lineage_fingerprint(self) -> str:
        return _digest(self.as_record())

    @property
    def cache_key(self) -> str:
        occurrence_sensitive = bool(
            self.dependency_channels
            & {
                DependencyChannel.LOCATOR,
                DependencyChannel.VISUAL,
                DependencyChannel.STRUCTURAL,
            }
        )
        payload = {
            "tenant_id": self.tenant_id,
            "logical_unit_ids": sorted(self.logical_unit_ids),
            "source_content_hashes": sorted(self.source_content_hashes),
            "evidence_occurrence_ids": (
                sorted(self.evidence_occurrence_ids) if occurrence_sensitive else []
            ),
            "dependency_channels": sorted(channel.value for channel in self.dependency_channels),
            "parser": self.parser,
            "parser_version": self.parser_version,
            "model": self.model,
            "model_version": self.model_version,
            "config_fingerprint": self.config_fingerprint,
            "calibration_artifact_id": self.calibration_artifact_id,
            "recovery_trace_id": self.recovery_trace_id,
            "execution_class": self.execution_class.value,
            "stochastic_seed": self.stochastic_seed,
        }
        return _digest(payload)

    def as_record(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "tenant_id": self.tenant_id,
            "logical_unit_ids": list(self.logical_unit_ids),
            "evidence_occurrence_ids": list(self.evidence_occurrence_ids),
            "source_content_hashes": list(self.source_content_hashes),
            "dependency_channels": sorted(channel.value for channel in self.dependency_channels),
            "parser": self.parser,
            "parser_version": self.parser_version,
            "model": self.model,
            "model_version": self.model_version,
            "config_fingerprint": self.config_fingerprint,
            "calibration_artifact_id": self.calibration_artifact_id,
            "recovery_trace_id": self.recovery_trace_id,
            "generation_id": self.generation_id,
            "execution_class": self.execution_class.value,
            "stochastic_seed": self.stochastic_seed,
            "cache_key": self.cache_key,
        }


T = TypeVar("T")


class ContentAddressedCache(Generic[T]):  # noqa: UP046 -- explicit TypeVar; PEP 695 syntax is not used elsewhere in this package
    """Minimal in-memory semantics shared by persistent cache adapters.

    Keys are tenant-scoped even though the manifest hash also includes tenant_id;
    the double boundary makes accidental cross-tenant lookup impossible for an
    adapter that later changes key layout.
    """

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], T] = {}

    def put(self, manifest: DerivationManifest, value: T) -> str:
        if not manifest.reusable:
            raise ValueError("IMPURE derivations must not enter reusable cache")
        key = manifest.cache_key
        self._items[(manifest.tenant_id, key)] = value
        return key

    def get(self, manifest: DerivationManifest) -> T | None:
        if not manifest.reusable:
            return None
        return self._items.get((manifest.tenant_id, manifest.cache_key))

    def delete_tenant(self, tenant_id: str) -> int:
        keys = [key for key in self._items if key[0] == tenant_id]
        for key in keys:
            del self._items[key]
        return len(keys)