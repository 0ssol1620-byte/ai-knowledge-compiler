"""Primitive immutable identities shared by every v6 benchmark artifact."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_FORBIDDEN_FLOATS = {"NaN", "Infinity", "-Infinity"}


class ContractError(ValueError):
    """Raised when evidence would be ambiguous, mutable, or fail-open."""


def _json_default(value: object) -> object:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic RFC-8259-compatible JSON bytes.

    Non-finite floats and implicit string coercion are rejected because either
    would make a signature implementation-dependent.
    """

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not canonical JSON: {exc}") from exc
    if any(token in encoded for token in _FORBIDDEN_FLOATS):
        raise ContractError("non-finite numeric values are forbidden")
    return encoded.encode("utf-8")


def canonical_sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def require_sha256(value: str, field: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field} must be an exact sha256:<64 lowercase hex> digest")
    return value


def require_commit(value: str, field: str) -> str:
    if not _COMMIT_RE.fullmatch(value):
        raise ContractError(f"{field} must be an exact 40- or 64-hex immutable commit")
    return value


def require_revision(value: str, field: str) -> str:
    if value.casefold() in {"main", "master", "latest", "stable", "head"}:
        raise ContractError(f"{field} may not be a mutable alias")
    if not _REVISION_RE.fullmatch(value):
        raise ContractError(f"{field} must be an exact 40- or 64-hex immutable revision")
    return value


def _freeze_string_map(values: Mapping[str, str]) -> Mapping[str, str]:
    normalized: dict[str, str] = {}
    for key, value in sorted(values.items()):
        if not isinstance(key, str) or not key.strip():
            raise ContractError("framework version keys must be non-empty strings")
        if not isinstance(value, str) or not value.strip():
            raise ContractError(f"framework version {key!r} must be pinned")
        if value.casefold() in {"latest", "main", "nightly", "unknown"}:
            raise ContractError(f"framework version {key!r} is mutable or unresolved")
        normalized[key] = value
    if not normalized:
        raise ContractError("at least one pinned framework version is required")
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class EnvironmentIdentity:
    """Identity shared by all three repeats of one candidate/suite cohort.

    The identity deliberately includes evaluator and dataset receipts even
    though ground truth remains unavailable to inference workers.  The flag is
    always required to be false, making accidental GT mounting a construction
    error rather than a later audit warning.
    """

    application_commit: str
    source_tree_sha256: str
    candidate_id: str
    model_repository: str
    model_revision: str
    model_manifest_sha256: str
    runtime_image_digest: str
    gpu_class: str
    gpu_count: int
    driver_version: str
    cuda_version: str
    framework_versions: Mapping[str, str]
    prompt_sha256: str
    decoding_sha256: str
    dataset_id: str
    dataset_revision: str
    dataset_manifest_sha256: str
    evaluator_repository: str
    evaluator_commit: str
    evaluator_manifest_sha256: str
    network_policy_sha256: str
    ground_truth_mounted_for_inference: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "application_commit",
            require_commit(self.application_commit, "application_commit"),
        )
        object.__setattr__(
            self,
            "source_tree_sha256",
            require_sha256(self.source_tree_sha256, "source_tree_sha256"),
        )
        if not self.candidate_id.strip():
            raise ContractError("candidate_id is required")
        if not self.model_repository.strip():
            raise ContractError("model_repository is required")
        object.__setattr__(
            self, "model_revision", require_revision(self.model_revision, "model_revision")
        )
        object.__setattr__(
            self,
            "model_manifest_sha256",
            require_sha256(self.model_manifest_sha256, "model_manifest_sha256"),
        )
        object.__setattr__(
            self,
            "runtime_image_digest",
            require_sha256(self.runtime_image_digest, "runtime_image_digest"),
        )
        if not self.gpu_class.strip() or self.gpu_count < 1:
            raise ContractError("a concrete GPU class and positive gpu_count are required")
        for field, value in (
            ("driver_version", self.driver_version),
            ("cuda_version", self.cuda_version),
            ("dataset_id", self.dataset_id),
            ("dataset_revision", self.dataset_revision),
            ("evaluator_repository", self.evaluator_repository),
        ):
            if not value.strip() or value.casefold() in {"latest", "unknown", "unresolved"}:
                raise ContractError(f"{field} must be pinned")
        object.__setattr__(self, "framework_versions", _freeze_string_map(self.framework_versions))
        for field in (
            "prompt_sha256",
            "decoding_sha256",
            "dataset_manifest_sha256",
            "evaluator_manifest_sha256",
            "network_policy_sha256",
        ):
            object.__setattr__(self, field, require_sha256(getattr(self, field), field))
        object.__setattr__(
            self, "evaluator_commit", require_commit(self.evaluator_commit, "evaluator_commit")
        )
        if self.ground_truth_mounted_for_inference:
            raise ContractError("ground truth must never be mounted in the inference environment")

    def to_dict(self) -> dict[str, object]:
        return {
            "application_commit": self.application_commit,
            "source_tree_sha256": self.source_tree_sha256,
            "candidate_id": self.candidate_id,
            "model_repository": self.model_repository,
            "model_revision": self.model_revision,
            "model_manifest_sha256": self.model_manifest_sha256,
            "runtime_image_digest": self.runtime_image_digest,
            "gpu_class": self.gpu_class,
            "gpu_count": self.gpu_count,
            "driver_version": self.driver_version,
            "cuda_version": self.cuda_version,
            "framework_versions": dict(self.framework_versions),
            "prompt_sha256": self.prompt_sha256,
            "decoding_sha256": self.decoding_sha256,
            "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "evaluator_repository": self.evaluator_repository,
            "evaluator_commit": self.evaluator_commit,
            "evaluator_manifest_sha256": self.evaluator_manifest_sha256,
            "network_policy_sha256": self.network_policy_sha256,
            "ground_truth_mounted_for_inference": self.ground_truth_mounted_for_inference,
        }

    @property
    def environment_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EnvironmentIdentity:
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise ContractError(f"invalid environment identity fields: {exc}") from exc
