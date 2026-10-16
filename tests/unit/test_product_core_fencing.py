"""Executable reference contract, NOT a distributed storage implementation."""

from dataclasses import dataclass, replace
from typing import Literal

import pytest
from akc_product_core.fencing import CompileBinding, CompileLease, FencedCompileStore, LeaseRejected


@dataclass
class _Row:
    binding: CompileBinding
    generation: int = 0
    lease: CompileLease | None = None
    expires: int = 0


class _ReferenceStore:
    """Single-threaded state machine with manually advanced authority time."""

    def __init__(self) -> None:
        self.now = 0
        self.epoch = "initial"
        self.rows: dict[tuple[str, str, str], _Row] = {}
        self.payloads: dict[tuple[CompileBinding, str, str], bytes] = {}

    @staticmethod
    def key(binding: CompileBinding) -> tuple[str, str, str]:
        return binding.tenant_id, binding.workspace_id, binding.idempotency_key

    @staticmethod
    def duration(ttl_seconds: int) -> None:
        if not 1 <= ttl_seconds <= 300:
            raise ValueError("lease duration outside reference policy")

    def acquire(self, binding: CompileBinding, *, owner: str, ttl_seconds: int) -> CompileLease:
        self.duration(ttl_seconds)
        if not owner:
            raise ValueError("owner required")
        row = self.rows.setdefault(self.key(binding), _Row(binding))
        if row.binding != binding:
            raise LeaseRejected("immutable binding conflict")
        if row.lease and row.lease.epoch == self.epoch and row.expires > self.now:
            raise LeaseRejected("already held")
        row.generation += 1
        row.lease = CompileLease(binding, owner, self.epoch, row.generation)
        row.expires = self.now + ttl_seconds
        return row.lease

    def current(self, lease: CompileLease) -> _Row:
        row = self.rows.get(self.key(lease.binding))
        if (
            row is None or row.lease != lease or lease.epoch != self.epoch
            or row.expires <= self.now
        ):
            raise LeaseRejected("stale or expired")
        return row

    def renew(self, lease: CompileLease, *, ttl_seconds: int) -> None:
        self.duration(ttl_seconds)
        self.current(lease).expires = self.now + ttl_seconds

    def commit_checkpoint(
        self, lease: CompileLease, *, kind: Literal["fragment", "candidate"],
        checkpoint_key: str, payload: bytes,
    ) -> None:
        self.current(lease)
        key = (lease.binding, kind, checkpoint_key)
        if key in self.payloads and self.payloads[key] != payload:
            raise LeaseRejected("checkpoint conflict")
        self.payloads[key] = payload


def _binding() -> CompileBinding:
    return CompileBinding("tenant", "workspace", "job", "work", "release")


def _commit(store: FencedCompileStore, lease: CompileLease, payload: bytes = b"fragment") -> None:
    store.commit_checkpoint(lease, kind="fragment", checkpoint_key="doc", payload=payload)


def test_stale_fencing_token_cannot_commit() -> None:
    store = _ReferenceStore()
    first = store.acquire(_binding(), owner="worker-a", ttl_seconds=10)
    store.now = 10
    second = store.acquire(_binding(), owner="worker-b", ttl_seconds=10)
    assert second.generation == first.generation + 1
    with pytest.raises(LeaseRejected):
        _commit(store, first)
    _commit(store, second)
    assert list(store.payloads.values()) == [b"fragment"]


def test_expiry_cannot_be_renewed_or_committed_at_boundary() -> None:
    store = _ReferenceStore()
    lease = store.acquire(_binding(), owner="worker", ttl_seconds=10)
    store.now = 9
    store.renew(lease, ttl_seconds=10)
    store.now = 19
    with pytest.raises(LeaseRejected):
        store.renew(lease, ttl_seconds=10)
    with pytest.raises(LeaseRejected):
        _commit(store, lease)
    assert not store.payloads


def test_live_owner_cannot_acquire_even_with_same_owner_name() -> None:
    store = _ReferenceStore()
    store.acquire(_binding(), owner="worker", ttl_seconds=10)
    for owner in ("worker", "another"):
        with pytest.raises(LeaseRejected):
            store.acquire(_binding(), owner=owner, ttl_seconds=10)


@pytest.mark.parametrize("field", ["work_digest", "release_digest"])
def test_takeover_preserves_immutable_work_binding(field: str) -> None:
    store = _ReferenceStore()
    store.acquire(_binding(), owner="old", ttl_seconds=1)
    store.now = 1
    with pytest.raises(LeaseRejected):
        store.acquire(replace(_binding(), **{field: "changed"}), owner="new", ttl_seconds=1)


def test_restore_epoch_fences_even_reused_generation_and_owner() -> None:
    store = _ReferenceStore()
    before = store.acquire(_binding(), owner="worker", ttl_seconds=10)
    store.rows[store.key(_binding())].generation = 0  # Restored older snapshot.
    store.epoch = "restore-unique-epoch"
    after = store.acquire(_binding(), owner="worker", ttl_seconds=10)
    assert after.generation == before.generation
    with pytest.raises(LeaseRejected):
        _commit(store, before)
    _commit(store, after)


def test_lease_scope_and_owner_cannot_be_forged() -> None:
    store = _ReferenceStore()
    lease = store.acquire(_binding(), owner="worker", ttl_seconds=10)
    for forged in (
        replace(lease, owner="other"), replace(lease, generation=2),
        replace(lease, binding=replace(lease.binding, tenant_id="other")),
        replace(lease, binding=replace(lease.binding, workspace_id="other")),
    ):
        with pytest.raises(LeaseRejected):
            _commit(store, forged)


def test_checkpoint_retry_is_immutable_and_rejection_preserves_state() -> None:
    store = _ReferenceStore()
    lease = store.acquire(_binding(), owner="worker", ttl_seconds=10)
    _commit(store, lease)
    _commit(store, lease)
    with pytest.raises(LeaseRejected):
        _commit(store, lease, b"different")
    assert list(store.payloads.values()) == [b"fragment"]


@pytest.mark.parametrize("ttl", [0, -1, 301])
def test_invalid_duration_does_not_create_work(ttl: int) -> None:
    store = _ReferenceStore()
    with pytest.raises(ValueError):
        store.acquire(_binding(), owner="worker", ttl_seconds=ttl)
    assert not store.rows
