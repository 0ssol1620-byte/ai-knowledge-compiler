from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from akc_parallel_runtime import (
    IDEMPOTENT_OPERATIONS,
    PARALLEL_RUNTIME_EVENT_TYPES,
    PARALLEL_RUNTIME_TABLES,
    CanonicalizationError,
    EventConflictError,
    EventJournal,
    canonical_json,
    canonical_sha256,
    require_sha256,
    sha256_hex,
    stable_id,
)
from helpers import HASH_A, NOW


def test_canonical_json_is_order_and_set_deterministic() -> None:
    left = {"b": frozenset({"z", "a"}), "a": 1}
    right = {"a": 1, "b": frozenset({"a", "z"})}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_sha256(left) == canonical_sha256(right)


def test_canonical_json_preserves_decimal_and_aware_time() -> None:
    payload = canonical_json({"amount": Decimal("1.2300"), "at": NOW})
    assert '"1.2300"' in payload
    assert "+00:00" in payload


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), Decimal("NaN"), datetime(2026, 8, 1)],
)
def test_canonical_json_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json(value)


def test_bytes_are_represented_by_size_and_digest_not_content() -> None:
    encoded = canonical_json(b"sensitive payload")
    assert "sensitive payload" not in encoded
    assert sha256_hex(b"sensitive payload") in encoded


def test_stable_id_is_deterministic_and_namespaced() -> None:
    assert stable_id("attempt", "x", 1) == stable_id("attempt", "x", 1)
    assert stable_id("attempt", "x", 1).startswith("attempt_")
    assert stable_id("attempt", "x", 1) != stable_id("attempt", "x", 2)


@pytest.mark.parametrize("namespace", ["", "bad-name", "bad name", "!"])
def test_stable_id_rejects_invalid_namespace(namespace: str) -> None:
    with pytest.raises(ValueError):
        stable_id(namespace, "x")


def test_sha256_contract_is_strict_lowercase() -> None:
    assert require_sha256(HASH_A) == HASH_A
    with pytest.raises(ValueError):
        require_sha256(HASH_A.upper())
    with pytest.raises(ValueError):
        require_sha256("a" * 63)


def test_parallel_contract_lists_match_v6_masterplan() -> None:
    assert len(PARALLEL_RUNTIME_TABLES) == 9
    assert len(PARALLEL_RUNTIME_EVENT_TYPES) == 37
    assert {
        "recovery.planned.v1",
        "recovery.started.v1",
        "recovery.validated.v1",
        "region.verified.v1",
        "region.unresolved.v1",
        "worker.semantic.canary_failed.v1",
        "impact.replay.requested.v1",
        "final.accuracy.calculated.v1",
        "trust.receipt.issued.v1",
        "drift.detected.v1",
        "rollback.triggered.v1",
        "quality.finding.created.v1",
        "recovery.plan.created.v1",
        "recovery.attempt.started.v1",
        "recovery.candidate.generated.v1",
        "recovery.validation.completed.v1",
        "recovery.candidate.accepted.v1",
        "recovery.exhausted.v1",
        "knowledge.objects.invalidated.v1",
        "knowledge.objects.regenerated.v1",
        "package.trust_receipt.created.v1",
    } <= set(PARALLEL_RUNTIME_EVENT_TYPES)
    assert {
        "shard_dispatch",
        "hedge",
        "retry",
        "acceptance",
        "merge",
        "credit",
        "export",
    } == IDEMPOTENT_OPERATIONS


def test_event_journal_is_idempotent_and_orders_per_aggregate() -> None:
    journal = EventJournal()
    first = journal.append(
        event_type="shard.planned.v1",
        aggregate_id="shard-1",
        payload={"pages": ["p1"]},
        occurred_at=NOW,
        idempotency_key="plan-1",
    )
    assert journal.append(
        event_type="shard.planned.v1",
        aggregate_id="shard-1",
        payload={"pages": ["p1"]},
        occurred_at=NOW,
        idempotency_key="plan-1",
    ) is first
    second = journal.append(
        event_type="shard.dispatched.v1",
        aggregate_id="shard-1",
        payload={"attempt": "a1"},
        occurred_at=NOW,
        idempotency_key="dispatch-1",
    )
    other = journal.append(
        event_type="shard.planned.v1",
        aggregate_id="shard-2",
        payload={"pages": ["p2"]},
        occurred_at=NOW,
        idempotency_key="plan-2",
    )
    assert (first.sequence, second.sequence, other.sequence) == (1, 2, 1)
    defensive = first.payload
    defensive["pages"] = ["mutated"]
    assert first.payload == {"pages": ["p1"]}


def test_event_journal_rejects_idempotency_conflict() -> None:
    journal = EventJournal()
    journal.append(
        event_type="shard.planned.v1",
        aggregate_id="shard-1",
        payload={"pages": ["p1"]},
        occurred_at=NOW,
        idempotency_key="same",
    )
    with pytest.raises(EventConflictError):
        journal.append(
            event_type="shard.planned.v1",
            aggregate_id="shard-1",
            payload={"pages": ["p2"]},
            occurred_at=NOW,
            idempotency_key="same",
        )


def test_event_journal_rejects_unknown_or_naive_event() -> None:
    journal = EventJournal()
    with pytest.raises(ValueError):
        journal.append(
            event_type="invented.event.v1",
            aggregate_id="x",
            payload={},
            occurred_at=NOW,
            idempotency_key="x",
        )
    with pytest.raises(ValueError):
        journal.append(
            event_type="shard.planned.v1",
            aggregate_id="x",
            payload={},
            occurred_at=datetime(2026, 8, 1),
            idempotency_key="x",
        )


def test_event_journal_rejects_backdated_aggregate_event() -> None:
    journal = EventJournal()
    journal.append(
        event_type="shard.planned.v1",
        aggregate_id="s1",
        payload={},
        occurred_at=NOW,
        idempotency_key="first",
    )
    with pytest.raises(ValueError, match="chronological"):
        journal.append(
            event_type="shard.dispatched.v1",
            aggregate_id="s1",
            payload={},
            occurred_at=NOW - timedelta(seconds=1),
            idempotency_key="backdated",
        )
