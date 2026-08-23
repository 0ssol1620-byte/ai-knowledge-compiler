"""The world store: where published worlds live between runs.

§N22.2 says the published state is never edited -- a candidate is built
alongside it and the pointer moves. On disk that translates directly: each
world state is an immutable JSON file under ``worlds/``, its claim table under
``claims/``, and the *only* thing a reader is told to trust is
``pointer.json``, which is swapped with one ``os.replace`` after the world it
names is fully written. A reader either sees the old pointer or the new one,
never a half-published world.

Everything persisted here is deterministic: the claim table carries no wall
clock (``recorded_at`` comes from documents, ``built_at`` from a counter), so
recompiling the same tree reproduces the same bytes and the §44 oracle
comparison is a hash equality, not an approximation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from akc_cir.world_state import (
    PublicationManifest,
    PublishResult,
    ValidationReceipt,
    WorldStateRegistry,
)

__all__ = [
    "StoredWorld",
    "WorldStore",
]

_STORE_VERSION = 1
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def next_deterministic_time(sequence: int) -> datetime:
    """A clock that only moves when a world is published, never with the wall."""
    return _EPOCH + timedelta(hours=max(0, sequence))


def _write_json_atomic(path: Path, payload: object) -> None:
    """Write ``payload`` so a crash mid-write can never be observed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class StoredWorld:
    """One world state as persisted: its row, receipt, artifacts and claims."""

    world_state_id: str
    workspace_id: str
    manifest: PublicationManifest
    receipt: ValidationReceipt
    artifact_hashes: dict[str, str]
    claims: dict[str, dict[str, object]]
    evidence_index: dict[str, dict[str, object]]
    review_queue: tuple[dict[str, object], ...]
    cursor: dict[str, str]  # rel_path -> sha256
    built_at: datetime


class WorldStore:
    """Filesystem-backed world history for one workspace."""

    def __init__(self, root: Path, *, workspace_id: str) -> None:
        self.root = root
        self.workspace_id = workspace_id
        self.base = root / f"workspace-{workspace_id}"
        self.base.mkdir(parents=True, exist_ok=True)
        meta = _read_json(self.base / "meta.json")
        if meta is None:
            self._sequence = 0
        else:
            assert isinstance(meta, dict)
            self._sequence = int(meta["sequence"])

    # -- reads ------------------------------------------------------------

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def next_world_state_id(self) -> str:
        return f"WS-{self._sequence + 1}"

    def active_world_state_id(self) -> str | None:
        pointer = _read_json(self.base / "pointer.json")
        if pointer is None:
            return None
        assert isinstance(pointer, dict)
        return pointer.get("active_world_state_id")  # type: ignore[return-value]

    def load_world(self, world_state_id: str | None = None) -> StoredWorld | None:
        """Load the pointed-at world, or a specific one by id."""
        target = world_state_id or self.active_world_state_id()
        if target is None:
            return None
        world = _read_json(self.base / "worlds" / f"{target}.json")
        claims = _read_json(self.base / "claims" / f"{target}.json")
        if not isinstance(world, dict) or not isinstance(claims, dict):
            return None
        return StoredWorld(
            world_state_id=target,
            workspace_id=self.workspace_id,
            manifest=_manifest_from(world["manifest"]),
            receipt=_receipt_from(world["receipt"]),
            artifact_hashes=dict(world["artifact_hashes"]),
            claims=dict(claims["claims"]),
            evidence_index=dict(claims["evidence_index"]),
            review_queue=tuple(claims.get("review_queue", ())),
            cursor=dict(claims["cursor"]),
            built_at=datetime.fromisoformat(world["built_at"]),
        )

    def load_registry(self) -> WorldStateRegistry:
        """Rebuild a live registry by replaying every stored publish in order.

        Replay goes through ``stage`` + ``publish`` rather than trusting the
        stored rows, so a history that could not have been produced by the
        real registry fails to load instead of silently loading.
        """
        registry = WorldStateRegistry(self.workspace_id)
        pointer = self.active_world_state_id()
        if pointer is None:
            return registry
        history = self._history_ids()
        for world_state_id in history:
            world = _read_json(self.base / "worlds" / f"{world_state_id}.json")
            claims = _read_json(self.base / "claims" / f"{world_state_id}.json")
            if not isinstance(world, dict) or not isinstance(claims, dict):
                continue
            built_at = datetime.fromisoformat(world["built_at"])
            registry.stage(
                world_state_id=world_state_id,
                compiler_version=world["compiler_version"],
                built_at=built_at,
            )
            registry.publish(
                world_state_id,
                manifest=_manifest_from(world["manifest"]),
                receipt=_receipt_from(world["receipt"]),
                artifacts=dict(world["artifact_hashes"]),
                activated_at=datetime.fromisoformat(world["activated_at"]),
            )
        return registry

    def _history_ids(self) -> list[str]:
        worlds_dir = self.base / "worlds"
        if not worlds_dir.exists():
            return []

        def sequence_of(world_state_id: str) -> int:
            suffix = world_state_id.rsplit("-", 1)[-1]
            return int(suffix) if suffix.isdigit() else 0

        return sorted(
            (path.stem for path in worlds_dir.glob("WS-*.json")),
            key=sequence_of,
        )

    # -- writes -----------------------------------------------------------

    def publish(
        self,
        *,
        registry: WorldStateRegistry,
        world_state_id: str,
        compiler_version: str,
        manifest: PublicationManifest,
        receipt: ValidationReceipt,
        artifacts: dict[str, str],
        claims: dict[str, dict[str, object]],
        evidence_index: dict[str, dict[str, object]],
        review_queue: tuple[dict[str, object], ...],
        cursor: dict[str, str],
    ) -> PublishResult:
        """Persist a candidate world, then swap the pointer. In that order."""
        self._sequence += 1
        built_at = next_deterministic_time(self._sequence)
        result = registry.publish(
            world_state_id,
            manifest=manifest,
            receipt=receipt,
            artifacts=artifacts,
            activated_at=built_at,
        )
        state = result.world_state
        _write_json_atomic(
            self.base / "meta.json",
            {"version": _STORE_VERSION, "sequence": self._sequence, "workspace_id": self.workspace_id},
        )
        _write_json_atomic(
            self.base / "worlds" / f"{world_state_id}.json",
            {
                "world_state_id": state.world_state_id,
                "workspace_id": state.workspace_id,
                "compiler_version": compiler_version,
                "built_at": built_at.isoformat(),
                "activated_at": state.activated_at.isoformat() if state.activated_at else None,
                "parent_world_state_id": state.parent_world_state_id,
                "manifest": {
                    "world_state_id": manifest.world_state_id,
                    "compiler_version": manifest.compiler_version,
                    "artifact_hashes": dict(manifest.artifact_hashes),
                    "manifest_hash": manifest.manifest_hash,
                },
                "receipt": {
                    "receipt_id": receipt.receipt_id,
                    "checksums_verified": receipt.checksums_verified,
                    "permission_checked": receipt.permission_checked,
                    "integrity_passed": receipt.integrity_passed,
                    "equivalence": (
                        receipt.equivalence.as_record() if receipt.equivalence else None
                    ),
                },
                "artifact_hashes": dict(artifacts),
            },
        )
        _write_json_atomic(
            self.base / "claims" / f"{world_state_id}.json",
            {
                "claims": claims,
                "evidence_index": evidence_index,
                "review_queue": list(review_queue),
                "cursor": cursor,
            },
        )
        # The pointer moves last and in one replace: this is §N22.2's swap.
        _write_json_atomic(
            self.base / "pointer.json",
            {"active_world_state_id": world_state_id},
        )
        return result


def _manifest_from(raw: object) -> PublicationManifest:
    assert isinstance(raw, dict)
    return PublicationManifest(
        world_state_id=raw["world_state_id"],
        compiler_version=raw["compiler_version"],
        artifact_hashes=dict(raw["artifact_hashes"]),
        manifest_hash=raw["manifest_hash"],
    )


def _receipt_from(raw: object) -> ValidationReceipt:
    assert isinstance(raw, dict)
    equivalence_raw = raw.get("equivalence")
    equivalence = None
    if equivalence_raw is not None:
        from akc_cir.recompilation import EquivalenceReport

        equivalence = EquivalenceReport(
            equivalent=bool(equivalence_raw["equivalent"]),
            compared=int(equivalence_raw["compared"]),
            diverged=tuple(equivalence_raw["diverged"]),
            missing_from_selective=tuple(equivalence_raw["missing_from_selective"]),
            unexpectedly_rebuilt=tuple(equivalence_raw["unexpectedly_rebuilt"]),
            stale_left_behind=tuple(equivalence_raw["stale_left_behind"]),
        )
    return ValidationReceipt(
        receipt_id=raw["receipt_id"],
        checksums_verified=bool(raw["checksums_verified"]),
        permission_checked=bool(raw["permission_checked"]),
        integrity_passed=bool(raw["integrity_passed"]),
        equivalence=equivalence,
    )
