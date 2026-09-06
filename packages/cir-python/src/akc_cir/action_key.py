"""CompilationActionKey — a build's identity, and the guards on reusing it (§6).

Two questions hide inside "can we skip this compilation?". The first is
identity: *which* build are we talking about? :func:`compute_action_key`
answers it by hashing everything that determines the output — every input
file digest plus the execution contract (compiler, parser, schema, policy,
permission scope, tenant, parameters) — into one deterministic hex key.
Canonical JSON means the same world always hashes to the same key, no matter
what order anyone lists the inputs in.

The second question is safety: *may* the cached answer be replayed today?
That is deliberately NOT settled by the key alone. Model and prompt revisions
are recorded but excluded from the hash — builds iterate over prompts far
faster than over schemas, and the cache should survive that churn — so
:func:`reuse_guard` re-checks them at replay time, together with everything
else that can drift while nobody is looking:

1. the entry still exists under exactly this key (MISSING_INPUT),
2. the stored bytes still match every receipted digest — filename, envelope,
   preimage and artifact are each recomputed, so swapped or forged entries
   fail (CORRUPT_ARTIFACT),
3. the policy revision still agrees (POLICY_CHANGED),
4. the requester still holds every permission scope the build ran under —
   narrowing a scope forbids replaying what broader permissions produced
   (PERMISSION_NARROWED),
5. the model revision still agrees (MODEL_CHANGED),
6. the prompt revision still agrees (PROMPT_CHANGED),
7. every input file on disk still hashes to its recorded digest; changed
   files are stale (STALE_DEP), vanished ones are missing (MISSING_INPUT),
8. every required validation carries evidence recorded as ``passed``
   (MISSING_INPUT without evidence, STALE_DEP for anything else).

:class:`ActionKeyStore` is the content-addressed store entries live in. Every
write goes through a temp file + ``os.replace`` two-step, so a concurrent
reader sees either the whole old entry or the whole new one — never a torn
half-entry. One key owns at most one entry; republishing replaces it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol

from .base import canonical_json, sha256_digest

__all__ = [
    "MISS",
    "ActionKeyStore",
    "ExecutionContract",
    "InputPair",
    "Miss",
    "ReuseDecision",
    "ReuseFailureReason",
    "compute_action_key",
    "reuse_guard",
    "ActionInput",
    "RevisionBinding",
    "CompilationActionKeyInput",
    "compilation_action_key",
]

type InputPair = tuple[str, str]

_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
_STORE_FORMAT: Final[str] = "akc.action-key-store.v1"
_PREIMAGE_KIND: Final[str] = "akc.compilation.action-key.v1"
_PREIMAGE_VERSION: Final[int] = 1
_READ_CHUNK: Final[int] = 1 << 20


class ReuseFailureReason(StrEnum):
    """Why the reuse guard refused to replay a cached build."""

    MISSING_INPUT = "missing_input"
    POLICY_CHANGED = "policy_changed"
    PERMISSION_NARROWED = "permission_narrowed"
    CORRUPT_ARTIFACT = "corrupt_artifact"
    STALE_DEP = "stale_dep"
    MODEL_CHANGED = "model_changed"
    PROMPT_CHANGED = "prompt_changed"


class Miss:
    """Sentinel a lookup returns when nothing usable lives under a key.

    Compare with ``is`` against :data:`MISS`; a bare tuple means real bytes.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "MISS"


MISS: Final[Miss] = Miss()


@dataclass(frozen=True)
class ExecutionContract:
    """Everything outside the input files that shapes a compiled artifact.

    ``model_revision`` and ``prompt_revision`` may be ``None`` for builds
    that never touch a model. ``permission_scope`` accepts any iterable of
    scope strings (a bare string counts as one scope) and is normalized to a
    frozenset; ``params`` is snapshotted behind a read-only mapping proxy so
    callers cannot mutate their way out of a sealed key.
    """

    compiler_revision: str
    parser_revision: str
    schema_revision: str
    policy_revision: str
    permission_scope: frozenset[str]
    tenant_id: str
    params: Mapping[str, Any] = field(default_factory=dict)
    model_revision: str | None = None
    prompt_revision: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("compiler_revision", self.compiler_revision),
            ("parser_revision", self.parser_revision),
            ("schema_revision", self.schema_revision),
            ("policy_revision", self.policy_revision),
            ("tenant_id", self.tenant_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ExecutionContract.{name} must be a non-empty string")
        raw_scope: Iterable[str] = self.permission_scope
        if isinstance(raw_scope, str):
            raw_scope = (raw_scope,)
        normalized_scope = frozenset(raw_scope)
        malformed = any(not scope.strip() for scope in normalized_scope)
        if not normalized_scope or malformed:
            raise ValueError("ExecutionContract.permission_scope must grant at least one scope")
        object.__setattr__(self, "permission_scope", normalized_scope)
        for name, revision in (
            ("model_revision", self.model_revision),
            ("prompt_revision", self.prompt_revision),
        ):
            if revision is not None and (not isinstance(revision, str) or not revision.strip()):
                raise ValueError(f"ExecutionContract.{name} must be None or a non-empty string")
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))


def compute_action_key(inputs: Sequence[InputPair], contract: ExecutionContract) -> str:
    """Hash the build's complete identity into one deterministic hex key.

    ``inputs`` are ``(path, sha256)`` pairs in any order — they are sorted,
    deduplicated and digest-normalized before hashing, so listing order can
    never move the key. Duplicate paths carrying different digests are a
    caller bug and are refused rather than silently resolved.
    """
    normalized = _normalize_inputs(inputs)
    try:
        text = _preimage_text(normalized, contract)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"action key inputs are not deterministically serializable: {exc}") from exc
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_digest(digest: str) -> str:
    if not isinstance(digest, str):
        raise ValueError(f"input digest must be a sha256 hex string, got {type(digest).__name__}")
    cleaned = digest.strip().lower()
    if cleaned.startswith("sha256:"):
        cleaned = cleaned.removeprefix("sha256:")
    if not _DIGEST_RE.fullmatch(cleaned):
        raise ValueError(f"input digest must be sha256 hex, got {digest!r}")
    return cleaned


def _normalize_inputs(inputs: Sequence[InputPair]) -> tuple[tuple[str, str], ...]:
    seen: dict[str, str] = {}
    for path, digest in inputs:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("input path must be a non-empty string")
        cleaned = _normalize_digest(digest)
        prior = seen.get(path)
        if prior is not None and prior != cleaned:
            raise ValueError(f"conflicting digests supplied for input {path!r}")
        seen[path] = cleaned
    return tuple(sorted(seen.items()))


def _contract_identity(contract: ExecutionContract) -> dict[str, Any]:
    """The key-covered half of the contract.

    ``model_revision`` / ``prompt_revision`` are left out on purpose: they are
    guarded at replay time (:func:`reuse_guard`) rather than baked into
    identity, so prompt iterations do not shred the cache.
    """
    return {
        "compiler_revision": contract.compiler_revision,
        "parser_revision": contract.parser_revision,
        "schema_revision": contract.schema_revision,
        "policy_revision": contract.policy_revision,
        "permission_scope": sorted(contract.permission_scope),
        "tenant_id": contract.tenant_id,
        "params": dict(contract.params),
    }


def _preimage_text(inputs: Sequence[InputPair], contract: ExecutionContract) -> str:
    preimage: dict[str, Any] = {
        "version": _PREIMAGE_VERSION,
        "kind": _PREIMAGE_KIND,
        "contract": _contract_identity(contract),
        "inputs": [[path, digest] for path, digest in _normalize_inputs(inputs)],
    }
    return canonical_json(preimage)


def _validated_key(key: str) -> str:
    cleaned = key.strip().lower()
    if not _DIGEST_RE.fullmatch(cleaned):
        raise ValueError(f"malformed action key: {key!r}")
    return cleaned


def _contract_from_guard(guard: Mapping[str, Any]) -> ExecutionContract:
    identity: Any = guard["contract"]
    return ExecutionContract(
        compiler_revision=identity["compiler_revision"],
        parser_revision=identity["parser_revision"],
        schema_revision=identity["schema_revision"],
        policy_revision=identity["policy_revision"],
        permission_scope=frozenset(str(scope) for scope in identity["permission_scope"]),
        tenant_id=identity["tenant_id"],
        params=identity.get("params", {}),
        model_revision=guard.get("model_revision"),
        prompt_revision=guard.get("prompt_revision"),
    )


class ActionKeyStore:
    """Content-addressed store: ``<root>/<key>.artifact`` + ``<root>/<key>.json``.

    The JSON envelope records the artifact digest, the exact key preimage and
    the guard metadata (full contract + input list + validation evidence), so
    integrity can be re-derived from the entry itself instead of trusted.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def envelope_path(self, key: str) -> Path:
        return self._root / f"{_validated_key(key)}.json"

    def artifact_path(self, key: str) -> Path:
        return self._root / f"{_validated_key(key)}.artifact"

    def put(
        self,
        key: str,
        artifact_bytes: bytes,
        receipt: Mapping[str, Any],
        *,
        contract: ExecutionContract | None = None,
        inputs: Sequence[InputPair] = (),
        validations: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """Publish ``(artifact_bytes, receipt)`` under ``key``, atomically.

        When ``contract`` is supplied the key is re-derived and cross-checked
        first — an entry whose label disagrees with its own provenance is
        refused at birth rather than stored as a future footgun. The blob is
        replaced before the envelope, making the envelope write the commit
        point: until it lands, the old entry stays whole or absent.
        """
        clean_key = _validated_key(key)
        preimage_text: str | None = None
        guard: dict[str, Any] | None = None
        if contract is not None:
            normalized = _normalize_inputs(inputs)
            expected = compute_action_key(normalized, contract)
            if expected != clean_key:
                raise ValueError(
                    f"action key mismatch: entry claims {clean_key[:12]}… but the "
                    f"contract hashes to {expected[:12]}…"
                )
            preimage_text = _preimage_text(normalized, contract)
            guard = {
                "contract": _contract_identity(contract),
                "model_revision": contract.model_revision,
                "prompt_revision": contract.prompt_revision,
                "inputs": [list(pair) for pair in normalized],
            }
        envelope: dict[str, Any] = {
            "format": _STORE_FORMAT,
            "key": clean_key,
            "artifact_sha256": sha256_digest(artifact_bytes),
            "preimage": preimage_text,
            "guard": guard,
            "validations": dict(validations) if validations else {},
            "receipt": dict(receipt),
        }
        try:
            envelope_text = json.dumps(
                envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        except (TypeError, ValueError) as exc:
            raise TypeError(f"receipt/validations must be JSON-serializable: {exc}") from exc
        self._write_atomic(self.artifact_path(clean_key), artifact_bytes)
        self._write_atomic(self.envelope_path(clean_key), envelope_text.encode("utf-8"))

    def get(self, key: str) -> tuple[bytes, dict[str, Any]] | Miss:
        """Return ``(artifact, envelope)`` or :data:`MISS`.

        Fast path only: bytes are read as stored, not verified. Call
        :meth:`verify_integrity` (or go through :func:`reuse_guard`) before
        trusting them.
        """
        clean_key = _validated_key(key)
        envelope: Any = None
        try:
            envelope = json.loads(self.envelope_path(clean_key).read_text(encoding="utf-8"))
            artifact = self.artifact_path(clean_key).read_bytes()
        except (OSError, ValueError):
            return MISS
        if not isinstance(envelope, dict):
            return MISS
        return artifact, envelope

    def verify_integrity(self, key: str) -> bool:
        """Recompute every layer of the entry: filename ↔ envelope ↔ preimage ↔ bytes.

        An entry verifies only when the artifact still hashes to the receipted
        digest AND the stored preimage hashes to this key AND re-deriving the
        key from the guard's own contract + inputs lands on the same value.
        Swapped blobs, forged envelopes and entries transplanted from other
        keys all break at least one link.
        """
        fetched = self.get(key)
        if isinstance(fetched, Miss):
            return False
        artifact, envelope = fetched
        clean_key = _validated_key(key)
        if envelope.get("key") != clean_key:
            return False
        if sha256_digest(artifact) != envelope.get("artifact_sha256"):
            return False
        preimage = envelope.get("preimage")
        if not isinstance(preimage, str):
            return False
        if hashlib.sha256(preimage.encode("utf-8")).hexdigest() != clean_key:
            return False
        guard = envelope.get("guard")
        if not isinstance(guard, dict):
            return False
        try:
            stored_contract = _contract_from_guard(guard)
            stored_inputs = [(str(path), str(digest)) for path, digest in guard["inputs"]]
        except (KeyError, TypeError, ValueError):
            return False
        return compute_action_key(stored_inputs, stored_contract) == clean_key

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        handle_fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle_fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise


@dataclass(frozen=True)
class ReuseDecision:
    """HIT with the goods, or MISS with the reason it was refused."""

    hit: bool
    reason: ReuseFailureReason | None
    detail: str
    artifact: bytes | None = None
    receipt: Mapping[str, Any] | None = None


def _miss(reason: ReuseFailureReason, detail: str) -> ReuseDecision:
    return ReuseDecision(hit=False, reason=reason, detail=detail)


def _file_digest(path: str) -> str | None:
    """Digest a dependency as it exists right now; ``None`` if unreadable."""
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def reuse_guard(
    key: str,
    contract: ExecutionContract,
    required_validations: Sequence[str],
    *,
    store: ActionKeyStore,
) -> ReuseDecision:
    """Decide whether the entry under ``key`` may be replayed for ``contract``.

    HIT demands every gate from the module docstring, checked in order — the
    first failure names the reason. An empty ``required_validations`` list
    waives gate 8 only; nothing else is negotiable.
    """
    fetched = store.get(key)
    if isinstance(fetched, Miss):
        return _miss(ReuseFailureReason.MISSING_INPUT, f"no intact entry under key {key[:12]}…")
    artifact, envelope = fetched

    if not store.verify_integrity(key):
        return _miss(
            ReuseFailureReason.CORRUPT_ARTIFACT,
            "stored bytes no longer match the receipted digests",
        )

    guard = envelope.get("guard")
    if not isinstance(guard, dict) or not isinstance(guard.get("contract"), dict):
        return _miss(
            ReuseFailureReason.MISSING_INPUT,
            "entry lacks the contract metadata needed to judge reuse safety",
        )
    stored = _contract_from_guard(guard)

    if stored.policy_revision != contract.policy_revision:
        return _miss(
            ReuseFailureReason.POLICY_CHANGED,
            f"policy moved: stored {stored.policy_revision!r} != requested "
            f"{contract.policy_revision!r}",
        )

    lost_scopes = sorted(stored.permission_scope - contract.permission_scope)
    if lost_scopes:
        return _miss(
            ReuseFailureReason.PERMISSION_NARROWED,
            f"scopes no longer granted since the build: {lost_scopes}",
        )

    if stored.model_revision != contract.model_revision:
        return _miss(
            ReuseFailureReason.MODEL_CHANGED,
            f"model moved: stored {stored.model_revision!r} != requested "
            f"{contract.model_revision!r}",
        )
    if stored.prompt_revision != contract.prompt_revision:
        return _miss(
            ReuseFailureReason.PROMPT_CHANGED,
            f"prompt moved: stored {stored.prompt_revision!r} != requested "
            f"{contract.prompt_revision!r}",
        )

    for path, digest in [(str(p), str(d)) for p, d in guard.get("inputs", [])]:
        current = _file_digest(path)
        if current is None:
            return _miss(
                ReuseFailureReason.MISSING_INPUT, f"input vanished since the build: {path}"
            )
        if current != digest:
            return _miss(ReuseFailureReason.STALE_DEP, f"input changed since the build: {path}")

    recorded_raw = envelope.get("validations")
    recorded: dict[str, Any] = recorded_raw if isinstance(recorded_raw, dict) else {}
    for kind in required_validations:
        record = recorded.get(kind)
        if not isinstance(record, dict):
            return _miss(
                ReuseFailureReason.MISSING_INPUT,
                f"no recorded evidence for required validation {kind!r}",
            )
        status = record.get("status")
        if status != "passed":
            return _miss(
                ReuseFailureReason.STALE_DEP,
                f"required validation {kind!r} is recorded as {status!r}, not 'passed'",
            )

    return ReuseDecision(
        hit=True,
        reason=None,
        detail="entry intact and every guard passed",
        artifact=artifact,
        receipt=envelope.get("receipt"),
    )


# Role-bound semantic action identity (USKC integration compatibility).
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
