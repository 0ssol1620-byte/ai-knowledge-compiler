"""Internal shared-journal boundary; no backend is activated by this module.

Implementations must serialize acquisition, renewal, restore epoch changes and
checkpoint commits in the SAME shared transactional authority. Clock readings
come from that authority. A separate preflight token check is insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class CompileBinding:
    tenant_id: str
    workspace_id: str
    idempotency_key: str
    work_digest: str
    release_digest: str


@dataclass(frozen=True)
class CompileLease:
    binding: CompileBinding
    owner: str
    epoch: str
    generation: int


class LeaseRejected(Exception):
    """Ownership expired, changed, or belongs to another immutable binding."""


class FencedCompileStore(Protocol):
    """Contract for a future shared journal, independent of Foundation promotion.

    acquire binds immutable work/release, rejects a live owner (including the
    caller), then increments persisted generation and installs a lease. renew
    cannot revive an expired lease. Both require positive bounded durations.
    commit_checkpoint validates current owner/epoch/generation and expiry and
    writes in ONE transaction; completed checkpoint keys are immutable. Identical
    retries are idempotent, conflicting payloads fail. Candidate commits require
    reducer validation and completeness checks in addition to fencing.

    Restore must assign a never-reused deployment epoch before writes resume;
    generations alone cannot fence workers holding a post-snapshot generation.
    Tombstones must preserve generation/binding when retention deletes payloads.
    """

    def acquire(self, binding: CompileBinding, *, owner: str, ttl_seconds: int) -> CompileLease: ...

    def renew(self, lease: CompileLease, *, ttl_seconds: int) -> None: ...

    def commit_checkpoint(
        self,
        lease: CompileLease,
        *,
        kind: Literal["fragment", "candidate"],
        checkpoint_key: str,
        payload: bytes,
    ) -> None: ...
