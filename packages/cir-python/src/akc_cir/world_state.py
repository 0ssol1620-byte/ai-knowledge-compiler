"""Publishing a compiled world, all at once or not at all.

Masterplan §N22.2 and §N22.3, and invariant 13: *새 world state는 원자적으로
publish한다. 부분 성공 state를 agent가 보지 못하게 한다.*

The failure this prevents is specific and it is not "an error". A selective
recompile touches four artifacts out of six. Halfway through publishing, an agent
asks a question and gets two rebuilt answers and two stale ones, consistent with
neither the old world nor the new. Nothing raises, nothing logs, and the answer is
wrong in a way that cannot be reproduced afterwards because the intermediate state
no longer exists.

So the published thing is a *pointer*, and the only mutating operation is moving
it. §N22.2: the current published state is never edited. A candidate is built
alongside it, checked, and then the pointer swaps -- one write, which either
happened or did not.

§N22.3's eight steps are a sequence, not a list, and two of the orderings carry
weight:

**Verification precedes the swap, always.** Checksums, validation and the
equivalence check all run against the candidate while nothing is reading it. A
system that publishes and then verifies has already served the bad state to
whoever asked in between.

**The outbox write is inside the transaction.** §N26.1: an event written after the
commit can be lost between them, and an event written before it can announce a
publish that then rolls back. Either way a downstream consumer's view stops
matching the database, which is the thing the whole protocol exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .recompilation import EquivalenceReport, RecompilationPlan

__all__ = [
    "PublicationManifest",
    "PublishRefused",
    "PublishResult",
    "ValidationReceipt",
    "WorldState",
    "WorldStateRegistry",
    "WorldStateStatus",
    "publication_manifest",
]


class WorldStateStatus(StrEnum):
    """§73.10's status column. Only one ACTIVE per workspace, ever."""

    BUILDING = "BUILDING"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class PublishRefused(RuntimeError):
    """A publish that would break an invariant does not happen quietly."""


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    """What was checked, and whether it passed. §N22.3 step 3.

    `equivalence` is optional because a full rebuild has nothing to compare
    against -- but a *selective* build without one cannot be published, and
    `WorldStateRegistry.publish` enforces that rather than trusting the caller.
    """

    receipt_id: str
    checksums_verified: bool
    permission_checked: bool
    integrity_passed: bool
    equivalence: EquivalenceReport | None = None
    notes: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.checksums_verified
            and self.permission_checked
            and self.integrity_passed
            and (self.equivalence is None or self.equivalence.equivalent)
        )

    def failures(self) -> tuple[str, ...]:
        found: list[str] = []
        if not self.checksums_verified:
            found.append("artifact checksums were not verified")
        if not self.permission_checked:
            found.append("the permission check did not run")
        if not self.integrity_passed:
            found.append("integrity validation failed")
        if self.equivalence is not None and not self.equivalence.equivalent:
            found.append(
                "the selective build does not match a full rebuild: "
                f"{len(self.equivalence.diverged)} artifact(s) diverged, "
                f"{len(self.equivalence.stale_left_behind)} left stale"
            )
        return tuple(found)


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    """§N22.3 step 4. What this world state contains, as one hash.

    The manifest hash is what makes a published state citable. An answer that
    says "compiled at 14:02" cannot be checked; one that names a manifest hash can
    be, and the artifacts behind it either hash to it or they do not.
    """

    world_state_id: str
    compiler_version: str
    artifact_hashes: Mapping[str, str]
    manifest_hash: str

    def verify(self, artifacts: Mapping[str, str]) -> tuple[str, ...]:
        """Artifacts whose content does not match what the manifest recorded."""
        mismatched = [
            name
            for name, expected in sorted(self.artifact_hashes.items())
            if artifacts.get(name) != expected
        ]
        missing = [
            name for name in sorted(self.artifact_hashes) if name not in artifacts
        ]
        return tuple(dict.fromkeys(mismatched + missing))


def publication_manifest(
    *,
    world_state_id: str,
    compiler_version: str,
    artifact_hashes: Mapping[str, str],
) -> PublicationManifest:
    """Hash the whole set, order-independently.

    Sorted keys and a separator-free canonical encoding, so two builds that
    produced the same artifacts in a different order produce the same manifest
    hash. Without that, a manifest hash would change on nothing and stop being
    evidence of anything.
    """
    payload = json.dumps(
        {
            "compiler_version": compiler_version,
            "artifacts": dict(sorted(artifact_hashes.items())),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return PublicationManifest(
        world_state_id=world_state_id,
        compiler_version=compiler_version,
        artifact_hashes=dict(artifact_hashes),
        manifest_hash=digest,
    )


@dataclass(frozen=True, slots=True)
class WorldState:
    """§73.10's row."""

    world_state_id: str
    workspace_id: str
    status: WorldStateStatus
    compiler_version: str
    built_at: datetime
    parent_world_state_id: str | None = None
    change_set_id: str | None = None
    activated_at: datetime | None = None
    manifest: PublicationManifest | None = None
    validation_receipt_id: str | None = None


@dataclass(frozen=True, slots=True)
class PublishResult:
    world_state: WorldState
    previous_world_state_id: str | None
    outbox: tuple[Mapping[str, object], ...] = field(default_factory=tuple)


class WorldStateRegistry:
    """One workspace's world states, with the pointer as the only mutable thing.

    In production this is Postgres: §73.10's table with a unique partial index on
    `status = 'ACTIVE'` per workspace, and §N22.3 step 5's serializable
    transaction. This is the same semantics in memory so the ordering rules and
    the race behaviour can be tested without a database -- the index is what makes
    two concurrent publishes impossible, and `publish` reproduces its effect by
    re-reading the candidate's status before swapping.
    """

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self._states: dict[str, WorldState] = {}
        self._current_id: str | None = None
        self._history: list[str] = []

    # -- reads ------------------------------------------------------------

    @property
    def current(self) -> WorldState | None:
        """What a reader sees. Never a candidate, never a half-built state."""
        return self._states.get(self._current_id) if self._current_id else None

    def get(self, world_state_id: str) -> WorldState | None:
        return self._states.get(world_state_id)

    @property
    def history(self) -> tuple[str, ...]:
        return tuple(self._history)

    def active_count(self) -> int:
        return sum(
            1 for s in self._states.values() if s.status is WorldStateStatus.ACTIVE
        )

    # -- writes -----------------------------------------------------------

    def stage(
        self,
        *,
        world_state_id: str,
        compiler_version: str,
        built_at: datetime,
        change_set_id: str | None = None,
    ) -> WorldState:
        """§N22.2 -- build alongside, never into, the published state."""
        if world_state_id in self._states:
            raise PublishRefused(f"{world_state_id} already exists")
        candidate = WorldState(
            world_state_id=world_state_id,
            workspace_id=self.workspace_id,
            status=WorldStateStatus.CANDIDATE,
            compiler_version=compiler_version,
            built_at=built_at,
            parent_world_state_id=self._current_id,
            change_set_id=change_set_id,
        )
        self._states[world_state_id] = candidate
        return candidate

    def publish(
        self,
        world_state_id: str,
        *,
        manifest: PublicationManifest,
        receipt: ValidationReceipt,
        artifacts: Mapping[str, str],
        activated_at: datetime,
        plan: RecompilationPlan | None = None,
    ) -> PublishResult:
        """§N22.3's eight steps, in order, with the swap last.

        `plan` being present means this was a selective build, and a selective
        build without an equivalence check is refused. §N22.4 says a mismatch
        blocks the publish; a missing check is not a pass, it is the absence of
        the thing that would have caught the mismatch.
        """
        candidate = self._states.get(world_state_id)
        if candidate is None:
            raise PublishRefused(f"{world_state_id} was never staged")
        if candidate.status is not WorldStateStatus.CANDIDATE:
            # Step 5, and what the unique partial index enforces in Postgres: a
            # second publisher re-reads the row and finds it is no longer a
            # candidate.
            raise PublishRefused(
                f"{world_state_id} is {candidate.status.value}, not a candidate; "
                "another publish already claimed it"
            )

        # Step 2 -- verify the artifacts are what the manifest says, before
        # anything can read them.
        mismatched = manifest.verify(artifacts)
        if mismatched:
            self._reject(world_state_id)
            raise PublishRefused(
                f"artifact checksum mismatch for {', '.join(mismatched)}; "
                "publishing would serve content the manifest does not describe"
            )

        # Step 3 -- validation must have passed, and must have covered
        # equivalence when the build was selective.
        if plan is not None and receipt.equivalence is None:
            self._reject(world_state_id)
            raise PublishRefused(
                "a selective build has no equivalence check. A missing check is "
                "not a passing one -- it is the absence of what would have caught "
                "a stale artifact."
            )
        if not receipt.passed:
            self._reject(world_state_id)
            raise PublishRefused(
                "validation did not pass: " + "; ".join(receipt.failures())
            )

        previous_id = self._current_id
        if previous_id:
            previous = self._states[previous_id]
            self._states[previous_id] = _with(
                previous, status=WorldStateStatus.SUPERSEDED
            )

        published = _with(
            candidate,
            status=WorldStateStatus.ACTIVE,
            activated_at=activated_at,
            manifest=manifest,
            validation_receipt_id=receipt.receipt_id,
        )
        self._states[world_state_id] = published

        # Steps 6 and 7 together. The pointer move and the outbox row are one
        # write in production; separating them lets a consumer see a publish the
        # database rolled back, or miss one it kept.
        self._current_id = world_state_id
        self._history.append(world_state_id)

        event = {
            "type": "world_state.published",
            "workspace_id": self.workspace_id,
            "world_state_id": world_state_id,
            "previous_world_state_id": previous_id,
            "manifest_hash": manifest.manifest_hash,
            "validation_receipt_id": receipt.receipt_id,
        }
        return PublishResult(
            world_state=published,
            previous_world_state_id=previous_id,
            outbox=(event,),
        )

    def rollback(self, *, to: str, at: datetime) -> PublishResult:
        """§N22.5 -- move the pointer back. Source history is not deleted.

        The target must be a state that was published before, not any staged
        candidate: rolling *forward* onto something that never passed validation
        would use the rollback path to publish an unvalidated state.
        """
        target = self._states.get(to)
        if target is None:
            raise PublishRefused(f"{to} does not exist")
        if to not in self._history:
            raise PublishRefused(
                f"{to} was never published; rolling back to it would publish an "
                "unvalidated state through the rollback path"
            )
        if to == self._current_id:
            raise PublishRefused(f"{to} is already current")

        previous_id = self._current_id
        if previous_id:
            self._states[previous_id] = _with(
                self._states[previous_id], status=WorldStateStatus.ROLLED_BACK
            )
        restored = _with(target, status=WorldStateStatus.ACTIVE, activated_at=at)
        self._states[to] = restored
        self._current_id = to
        self._history.append(to)

        return PublishResult(
            world_state=restored,
            previous_world_state_id=previous_id,
            outbox=(
                {
                    "type": "world_state.rolled_back",
                    "workspace_id": self.workspace_id,
                    "world_state_id": to,
                    "from_world_state_id": previous_id,
                },
            ),
        )

    def _reject(self, world_state_id: str) -> None:
        self._states[world_state_id] = _with(
            self._states[world_state_id], status=WorldStateStatus.REJECTED
        )


def _with(state: WorldState, **changes: object) -> WorldState:
    fields = {
        "world_state_id": state.world_state_id,
        "workspace_id": state.workspace_id,
        "status": state.status,
        "compiler_version": state.compiler_version,
        "built_at": state.built_at,
        "parent_world_state_id": state.parent_world_state_id,
        "change_set_id": state.change_set_id,
        "activated_at": state.activated_at,
        "manifest": state.manifest,
        "validation_receipt_id": state.validation_receipt_id,
    }
    fields.update(changes)
    return WorldState(**fields)  # type: ignore[arg-type]


def dirty_set(
    *,
    changed_logical_ids: Sequence[str],
    plan: RecompilationPlan,
    inventory: Iterable[str],
) -> tuple[str, ...]:
    """§N22.1's chain, ending at the artifacts a build must touch.

        changed source/evidence → changed logical units → typed propagation
        → dirty artifacts → rebuild plan

    Thin on purpose: the propagation is `dependency.impact_of` and the plan is
    `recompilation.plan_recompilation`. This exists so the chain has a name and
    so an artifact outside the inventory cannot enter the dirty set -- the impact
    radius covers knowledge units and evidence too, and only artifacts rebuild.
    """
    known = set(inventory)
    _ = changed_logical_ids
    return tuple(artifact for artifact in plan.to_rebuild if artifact in known)
