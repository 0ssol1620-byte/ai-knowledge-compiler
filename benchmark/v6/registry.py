"""Candidate registry loader with immutable-identity and license gates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from .contracts import ContractError, require_revision, require_sha256

_EXECUTABLE_STATES = {"ready_for_external_run", "external_run_complete"}
_ALLOWED_EXECUTION_STATES = {
    "identity_pending",
    "artifact_manifest_and_runtime_pending",
    "artifact_manifest_runtime_and_license_pending",
    "credential_and_policy_pending",
    "control_plane_only",
    *_EXECUTABLE_STATES,
}
_LICENSE_READY = {"approved", "approved_with_conditions"}
_REQUIRED_TIERS = {"A", "B", "C"}
_ALLOWED_KINDS = {
    "parser",
    "deterministic",
    "api_comparator",
    "multimodal_baseline",
    "knowledge_compiler",
    "agent",
}


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    candidate_id: str
    tier: str
    kind: str
    role: str
    required: bool
    execution_state: str
    repository: str | None
    revision: str | None
    artifact_sha256: str | None
    runtime_recipe: str | None
    runtime_source_repository: str | None
    runtime_source_revision: str | None
    license_id: str
    license_status: str
    commercial_use: str
    promotion_eligible: bool
    conditions: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> CandidateSpec:
        candidate_id = str(raw.get("id", "")).strip()
        tier = str(raw.get("tier", "")).strip().upper()
        kind = str(raw.get("kind", "")).strip()
        role = str(raw.get("role", "")).strip()
        if not candidate_id or not role:
            raise ContractError("candidate id and role are required")
        if tier not in {"A", "B", "C", "D", "E", "K"}:
            raise ContractError(f"candidate {candidate_id}: invalid tier {tier!r}")
        if kind not in _ALLOWED_KINDS:
            raise ContractError(f"candidate {candidate_id}: invalid kind {kind!r}")

        identity = raw.get("identity")
        if not isinstance(identity, Mapping):
            raise ContractError(f"candidate {candidate_id}: identity mapping is required")
        repository = _optional_string(identity.get("repository"))
        revision = _optional_string(identity.get("revision"))
        artifact_sha256 = _optional_string(identity.get("artifact_sha256"))
        runtime_recipe = _optional_string(identity.get("runtime_recipe"))
        runtime_source_repository = _optional_string(identity.get("runtime_source_repository"))
        runtime_source_revision = _optional_string(identity.get("runtime_source_revision"))
        if revision is not None:
            require_revision(revision, f"{candidate_id}.revision")
        if artifact_sha256 is not None:
            require_sha256(artifact_sha256, f"{candidate_id}.artifact_sha256")
        if runtime_source_revision is not None:
            require_revision(
                runtime_source_revision,
                f"{candidate_id}.runtime_source_revision",
            )

        license_value = raw.get("license")
        if not isinstance(license_value, Mapping):
            raise ContractError(f"candidate {candidate_id}: license mapping is required")
        license_id = str(license_value.get("id", "")).strip()
        license_status = str(license_value.get("status", "")).strip()
        commercial_use = str(license_value.get("commercial_use", "")).strip()
        if not license_id or license_status not in {
            "approved",
            "approved_with_conditions",
            "review_required",
            "prohibited",
        }:
            raise ContractError(f"candidate {candidate_id}: invalid license decision")
        if commercial_use not in {
            "allowed",
            "conditional",
            "research_only",
            "unknown",
            "prohibited",
        }:
            raise ContractError(f"candidate {candidate_id}: invalid commercial_use value")

        execution_state = str(raw.get("execution_state", "identity_pending")).strip()
        if execution_state not in _ALLOWED_EXECUTION_STATES:
            raise ContractError(
                f"candidate {candidate_id}: invalid execution_state {execution_state!r}"
            )
        promotion_eligible = bool(raw.get("promotion_eligible", False))
        required = bool(raw.get("required", False))
        conditions_raw = raw.get("conditions", [])
        if not isinstance(conditions_raw, list) or not all(
            isinstance(item, str) and item.strip() for item in conditions_raw
        ):
            raise ContractError(f"candidate {candidate_id}: conditions must be non-empty strings")

        if (execution_state in _EXECUTABLE_STATES or promotion_eligible) and (
            repository is None
            or revision is None
            or artifact_sha256 is None
            or runtime_recipe is None
        ):
            raise ContractError(f"candidate {candidate_id}: executable identity is incomplete")
        if promotion_eligible:
            if license_status not in _LICENSE_READY or commercial_use not in {
                "allowed",
                "conditional",
            }:
                raise ContractError(
                    f"candidate {candidate_id}: promotion requires an approved commercial license"
                )
            if execution_state != "external_run_complete":
                raise ContractError(
                    f"candidate {candidate_id}: promotion requires completed external runs"
                )
        if license_status == "prohibited" and execution_state in _EXECUTABLE_STATES:
            raise ContractError(
                f"candidate {candidate_id}: prohibited license cannot be executable"
            )

        return cls(
            candidate_id=candidate_id,
            tier=tier,
            kind=kind,
            role=role,
            required=required,
            execution_state=execution_state,
            repository=repository,
            revision=revision,
            artifact_sha256=artifact_sha256,
            runtime_recipe=runtime_recipe,
            runtime_source_repository=runtime_source_repository,
            runtime_source_revision=runtime_source_revision,
            license_id=license_id,
            license_status=license_status,
            commercial_use=commercial_use,
            promotion_eligible=promotion_eligible,
            conditions=tuple(conditions_raw),
        )

    @property
    def identity_complete(self) -> bool:
        return all((self.repository, self.revision, self.artifact_sha256, self.runtime_recipe))

    @property
    def model_revision_pinned(self) -> bool:
        return self.repository is not None and self.revision is not None


class CandidateRegistry:
    def __init__(
        self,
        *,
        schema_version: str,
        candidates: Mapping[str, CandidateSpec],
        required_ids: tuple[str, ...],
    ) -> None:
        self.schema_version = schema_version
        self._candidates = MappingProxyType(dict(candidates))
        self.required_ids = required_ids

    @classmethod
    def load(cls, path: Path) -> CandidateRegistry:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ContractError(f"cannot load candidate registry: {exc}") from exc
        if not isinstance(raw, Mapping) or str(raw.get("schema_version", "")) != "6.0.0":
            raise ContractError("candidate registry schema_version must be 6.0.0")
        rows = raw.get("candidates")
        if not isinstance(rows, list) or not rows:
            raise ContractError("candidate registry must contain candidates")
        candidates: dict[str, CandidateSpec] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ContractError("candidate registry rows must be mappings")
            candidate = CandidateSpec.from_mapping(row)
            if candidate.candidate_id in candidates:
                raise ContractError(f"duplicate candidate id: {candidate.candidate_id}")
            candidates[candidate.candidate_id] = candidate

        required_ids_raw = raw.get("required_candidate_ids")
        if not isinstance(required_ids_raw, list) or not all(
            isinstance(value, str) for value in required_ids_raw
        ):
            raise ContractError("required_candidate_ids must be a string list")
        required_ids = tuple(required_ids_raw)
        missing = sorted(set(required_ids) - candidates.keys())
        if missing:
            raise ContractError(f"required candidates missing from registry: {missing}")
        mismatched = sorted(
            candidate_id for candidate_id in required_ids if not candidates[candidate_id].required
        )
        if mismatched:
            raise ContractError(f"required candidates are not marked required: {mismatched}")
        tier_required = {
            item.candidate_id
            for item in candidates.values()
            if item.tier in _REQUIRED_TIERS and item.required
        }
        if not tier_required.issubset(set(required_ids)):
            raise ContractError(
                "every required Tier A/B/C candidate must appear in required_candidate_ids"
            )
        return cls(schema_version="6.0.0", candidates=candidates, required_ids=required_ids)

    def get(self, candidate_id: str) -> CandidateSpec:
        try:
            return self._candidates[candidate_id]
        except KeyError as exc:
            raise ContractError(f"unknown candidate: {candidate_id}") from exc

    @property
    def candidates(self) -> tuple[CandidateSpec, ...]:
        return tuple(self._candidates[key] for key in sorted(self._candidates))

    @property
    def externally_blocked_required_ids(self) -> tuple[str, ...]:
        return tuple(
            candidate_id
            for candidate_id in self.required_ids
            if not self._candidates[candidate_id].promotion_eligible
        )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
