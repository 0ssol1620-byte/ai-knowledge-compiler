"""Collision-safe compilation action identity.

The action key is deliberately separate from persistent cache/storage adapters.
It binds semantic input roles and repeated-input order explicitly, so swapping
inputs cannot collide merely because the same set of hashes is present.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

__all__ = [
    "ActionInput",
    "CompilationActionKeyInput",
    "RevisionBinding",
    "compilation_action_key",
]


def _canonical_sha256(payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class ActionInput:
    """One immutable action input bound to its semantic slot."""

    role: str
    artifact_hash: str
    ordinal: int = 0

    def __post_init__(self) -> None:
        if not self.role.strip() or not self.artifact_hash.strip():
            raise ValueError("action input role and artifact_hash are required")
        if self.ordinal < 0:
            raise ValueError("action input ordinal must be non-negative")

    def as_record(self) -> dict[str, object]:
        return {
            "role": self.role,
            "ordinal": self.ordinal,
            "artifact_hash": self.artifact_hash,
        }


@dataclass(frozen=True, slots=True, order=True)
class RevisionBinding:
    """Named component/revision binding included in action identity."""

    role: str
    name: str
    revision: str
    ordinal: int = 0

    def __post_init__(self) -> None:
        if not self.role.strip() or not self.name.strip() or not self.revision.strip():
            raise ValueError("revision binding role, name and revision are required")
        if self.ordinal < 0:
            raise ValueError("revision binding ordinal must be non-negative")

    def as_record(self) -> dict[str, object]:
        return {
            "role": self.role,
            "ordinal": self.ordinal,
            "name": self.name,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class CompilationActionKeyInput:
    """Complete deterministic identity for a compiler action.

    Tuple construction order is not semantic. Repeated semantic order is encoded
    by ``ordinal``. This makes independent callers converge on the same key while
    still distinguishing operand order and input roles.
    """

    tenant_id: str
    workspace_id: str
    action_type: str
    inputs: tuple[ActionInput, ...]
    components: tuple[RevisionBinding, ...] = ()
    prompt_schemas: tuple[RevisionBinding, ...] = ()
    policy_revision: str = ""
    recipe_revision: str = ""
    permission_scope_hash: str = ""
    deterministic_parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not self.tenant_id.strip()
            or not self.workspace_id.strip()
            or not self.action_type.strip()
        ):
            raise ValueError("tenant_id, workspace_id and action_type are required")
        if not self.inputs:
            raise ValueError("at least one role-bound action input is required")
        _require_unique_slots(self.inputs, label="action input")
        _require_unique_slots(self.components, label="component")
        _require_unique_slots(self.prompt_schemas, label="prompt schema")

    def as_payload(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "action_type": self.action_type,
            "inputs": [
                item.as_record()
                for item in sorted(
                    self.inputs,
                    key=lambda item: (item.role, item.ordinal, item.artifact_hash),
                )
            ],
            "components": [
                item.as_record()
                for item in sorted(
                    self.components,
                    key=lambda item: (item.role, item.ordinal, item.name, item.revision),
                )
            ],
            "prompt_schemas": [
                item.as_record()
                for item in sorted(
                    self.prompt_schemas,
                    key=lambda item: (item.role, item.ordinal, item.name, item.revision),
                )
            ],
            "policy_revision": self.policy_revision,
            "recipe_revision": self.recipe_revision,
            "permission_scope_hash": self.permission_scope_hash,
            "deterministic_parameters": dict(self.deterministic_parameters),
        }


class _Slotted(Protocol):
    """The two fields a role/ordinal uniqueness check reads.

    Declared read-only, because the members it stands for live on frozen
    dataclasses: a mutable attribute in a Protocol is not satisfied by one.
    """

    @property
    def role(self) -> str: ...

    @property
    def ordinal(self) -> int: ...


def _require_unique_slots(items: Sequence[_Slotted], *, label: str) -> None:
    slots = [(item.role, item.ordinal) for item in items]
    if len(slots) != len(set(slots)):
        raise ValueError(f"{label} role/ordinal slots must be unique")


def compilation_action_key(value: CompilationActionKeyInput) -> str:
    """Return the canonical SHA-256 key for one compilation action."""

    return _canonical_sha256(value.as_payload())
