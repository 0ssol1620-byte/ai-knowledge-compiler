from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from akc_parallel_runtime import (
    AttemptKind,
    BackpressureSnapshot,
    CreditConflictError,
    CreditEntryType,
    CreditLedger,
    CreditLimitExceeded,
    EventJournal,
    FairPriorityQueue,
    HedgeConflictError,
    HedgeController,
    JobPriority,
    VerificationState,
    WorkerSelector,
    WorkItem,
    can_scale_down,
    evaluate_backpressure,
    size_aware_bin_pack,
    straggler_candidates,
)
from helpers import NOW, worker


def work(
    work_id: str,
    *,
    priority: JobPriority = JobPriority.BULK_BACKGROUND,
    seconds: float = 10,
    enqueued_delta: float = 0,
    sequence: int = 0,
    cache_key: str = "model@abc123",
) -> WorkItem:
    return WorkItem(
        work_id=work_id,
        shard_id=f"shard-{work_id}",
        priority=priority,
        estimated_seconds=seconds,
        required_capabilities=frozenset({"scan"}),
        model_cache_key=cache_key,
        enqueued_at=NOW + timedelta(seconds=enqueued_delta),
        sequence=sequence,
    )


def reserve(ledger: CreditLedger, amount: str = "10") -> str:
    return ledger.reserve(
        account_id="account-1",
        job_id="job-1",
        amount=Decimal(amount),
        occurred_at=NOW,
        idempotency_key="reserve-1",
    ).reservation_id


def test_queue_priority_and_size_order_are_deterministic() -> None:
    queue = FairPriorityQueue(aging_seconds=1_000)
    queue.put(work("bulk", priority=JobPriority.BULK_BACKGROUND, seconds=1, sequence=1))
    queue.put(work("interactive", priority=JobPriority.INTERACTIVE, seconds=20, sequence=2))
    queue.put(work("tiny-slow", priority=JobPriority.TINY_QUICK, seconds=5, sequence=3))
    queue.put(work("tiny-fast", priority=JobPriority.TINY_QUICK, seconds=1, sequence=4))
    assert [queue.pop(now=NOW).work_id for _ in range(4)] == [
        "tiny-fast",
        "tiny-slow",
        "interactive",
        "bulk",
    ]


def test_queue_aging_prevents_background_starvation() -> None:
    queue = FairPriorityQueue(aging_seconds=10)
    queue.put(
        work(
            "old-bulk",
            priority=JobPriority.BULK_BACKGROUND,
            enqueued_delta=-100,
        )
    )
    queue.put(work("new-interactive", priority=JobPriority.INTERACTIVE))
    assert queue.pop(now=NOW).work_id == "old-bulk"


def test_queue_rejects_mutating_same_work_identity() -> None:
    queue = FairPriorityQueue()
    queue.put(work("same", seconds=1))
    with pytest.raises(RuntimeError):
        queue.put(work("same", seconds=2))


def test_worker_selection_prefers_healthy_warm_cache_then_finish_time() -> None:
    item = work("x")
    selected = WorkerSelector.select(
        item,
        (
            worker("cold-fast", warm=False, cached=frozenset(), available=0),
            worker("warm-cached", warm=True, available=20),
            worker("warm-no-cache", warm=True, cached=frozenset(), available=0),
        ),
    )
    assert selected.worker_id == "warm-cached"


def test_size_aware_bin_pack_balances_largest_shards_first() -> None:
    assignments = size_aware_bin_pack(
        (
            work("a", seconds=10),
            work("b", seconds=9),
            work("c", seconds=2),
            work("d", seconds=1),
        ),
        ("w1", "w2"),
    )
    loads = sorted(sum(item.estimated_seconds for item in items) for items in assignments.values())
    assert loads == [11, 11]


def test_backpressure_admits_only_when_every_capacity_is_safe() -> None:
    healthy = BackpressureSnapshot(
        queue_depth=5,
        queue_high_watermark=10,
        presigned_url_seconds_remaining=600,
        estimated_work_seconds=100,
        object_cache_available=True,
        evaluator_capacity=4,
        database_capacity=2,
    )
    assert evaluate_backpressure(healthy).admitted is True
    blocked = BackpressureSnapshot(
        queue_depth=10,
        queue_high_watermark=10,
        presigned_url_seconds_remaining=120,
        estimated_work_seconds=100,
        object_cache_available=False,
        evaluator_capacity=0,
        database_capacity=0,
        cost_anomaly=True,
    )
    decision = evaluate_backpressure(blocked)
    assert decision.admitted is False
    assert set(decision.reason_codes) == {
        "cost_anomaly",
        "database_capacity_exhausted",
        "evaluator_capacity_exhausted",
        "object_cache_unavailable",
        "presigned_url_expiry_risk",
        "queue_high_watermark",
    }


def test_hedge_launches_only_above_p95_multiplier_and_is_idempotent() -> None:
    events = EventJournal()
    controller = HedgeController(events=events)
    below = controller.decide(
        original_attempt_id="a1",
        shard_id="s1",
        elapsed_seconds=120,
        predicted_p95_seconds=100,
        alternate_worker_id="w2",
        original_verified=False,
        occurred_at=NOW,
        idempotency_key="below",
    )
    assert below.launch is False
    above_args = {
        "original_attempt_id": "a1",
        "shard_id": "s1",
        "elapsed_seconds": 121,
        "predicted_p95_seconds": 100,
        "alternate_worker_id": "w2",
        "original_verified": False,
        "occurred_at": NOW,
        "idempotency_key": "above",
    }
    above = controller.decide(**above_args)
    assert above.launch is True
    assert controller.decide(**above_args) is above
    assert controller.decide(
        **{**above_args, "idempotency_key": "above-retry"}
    ) is above
    assert events.events()[-1].payload["duplicate_billable"] is False


def test_hedge_key_conflict_and_verified_short_circuit() -> None:
    controller = HedgeController()
    arguments = {
        "original_attempt_id": "a1",
        "shard_id": "s1",
        "elapsed_seconds": 200,
        "predicted_p95_seconds": 100,
        "alternate_worker_id": "w2",
        "original_verified": True,
        "occurred_at": NOW,
        "idempotency_key": "same",
    }
    assert controller.decide(**arguments).reason_code == "original_already_verified"
    with pytest.raises(HedgeConflictError):
        controller.decide(**{**arguments, "original_verified": False})


def test_straggler_replication_is_limited_to_last_ten_percent() -> None:
    assert straggler_candidates(
        total_shards=100,
        incomplete_elapsed_seconds={"slow": 101, "normal": 5},
        completed_latencies_seconds=(9, 10, 11),
    ) == ("slow",)
    assert straggler_candidates(
        total_shards=10,
        incomplete_elapsed_seconds={"a": 101, "b": 101},
        completed_latencies_seconds=(10,),
    ) == ()


def test_scale_down_requires_every_safety_condition() -> None:
    assert can_scale_down(
        queue_empty=True,
        in_flight=0,
        artifacts_uploaded=True,
        grace_window_elapsed=True,
        current_workers=2,
        minimum_workers=1,
    )
    assert not can_scale_down(
        queue_empty=True,
        in_flight=1,
        artifacts_uploaded=True,
        grace_window_elapsed=True,
        current_workers=2,
        minimum_workers=1,
    )


def test_credit_reservation_is_idempotent_and_conflict_safe() -> None:
    ledger = CreditLedger()
    first = ledger.reserve(
        account_id="a",
        job_id="j",
        amount=Decimal("10"),
        occurred_at=NOW,
        idempotency_key="reserve",
    )
    assert ledger.reserve(
        account_id="a",
        job_id="j",
        amount=Decimal("10"),
        occurred_at=NOW,
        idempotency_key="reserve",
    ) is first
    with pytest.raises(CreditConflictError):
        ledger.reserve(
            account_id="a",
            job_id="j",
            amount=Decimal("11"),
            occurred_at=NOW,
            idempotency_key="reserve",
        )


@pytest.mark.parametrize(
    "state",
    [VerificationState.UNRESOLVED, VerificationState.QUARANTINED, VerificationState.FAILED],
)
def test_unaccepted_states_are_never_billable(state: VerificationState) -> None:
    ledger = CreditLedger()
    reservation_id = reserve(ledger)
    result = ledger.settle_work(
        reservation_id=reservation_id,
        work_key="page-1",
        attempt_id="attempt-1",
        attempt_kind=AttemptKind.PRIMARY,
        verification_state=state,
        canonical_credits=Decimal("2"),
        occurred_at=NOW,
        idempotency_key=f"settle-{state.value}",
    )
    assert result.billable is False
    assert result.user_credits_charged == 0


def test_retry_winner_charges_logical_work_once_without_attempt_surcharge() -> None:
    ledger = CreditLedger()
    reservation_id = reserve(ledger)
    first = ledger.settle_work(
        reservation_id=reservation_id,
        work_key="page-1",
        attempt_id="retry-winner",
        attempt_kind=AttemptKind.RETRY,
        verification_state=VerificationState.AUTO_REPAIRED,
        canonical_credits=Decimal("2"),
        occurred_at=NOW,
        idempotency_key="settle-retry",
    )
    duplicate = ledger.settle_work(
        reservation_id=reservation_id,
        work_key="page-1",
        attempt_id="hedge-late",
        attempt_kind=AttemptKind.HEDGE,
        verification_state=VerificationState.VERIFIED,
        canonical_credits=Decimal("2"),
        occurred_at=NOW,
        idempotency_key="settle-hedge",
    )
    assert first.user_credits_charged == Decimal("2.000000")
    assert duplicate.user_credits_charged == 0
    assert duplicate.duplicate is True
    assert ledger.balance(reservation_id)[0] == Decimal("2.000000")


def test_concurrent_duplicate_settlement_charges_exactly_once() -> None:
    ledger = CreditLedger()
    reservation_id = reserve(ledger)

    def settle(index: int) -> Decimal:
        return ledger.settle_work(
            reservation_id=reservation_id,
            work_key="page-1",
            attempt_id=f"attempt-{index}",
            attempt_kind=AttemptKind.HEDGE if index else AttemptKind.PRIMARY,
            verification_state=VerificationState.VERIFIED,
            canonical_credits=Decimal("1"),
            occurred_at=NOW,
            idempotency_key=f"settle-{index}",
        ).user_credits_charged

    with ThreadPoolExecutor(max_workers=8) as executor:
        charges = tuple(executor.map(settle, range(32)))
    assert charges.count(Decimal("1.000000")) == 1
    assert sum(charges) == Decimal("1.000000")


def test_compute_telemetry_records_gpu_cost_but_zero_user_charge() -> None:
    ledger = CreditLedger()
    reservation_id = reserve(ledger)
    entry = ledger.record_compute_telemetry(
        reservation_id=reservation_id,
        attempt_id="hedge-1",
        attempt_kind=AttemptKind.HEDGE,
        gpu_seconds=Decimal("12.5"),
        provider_cost=Decimal("0.4"),
        occurred_at=NOW,
        idempotency_key="telemetry-1",
    )
    assert entry.entry_type is CreditEntryType.COMPUTE_TELEMETRY
    assert entry.amount == 0
    assert ledger.balance(reservation_id)[0] == 0


def test_credit_ceiling_and_release_are_enforced_exactly() -> None:
    ledger = CreditLedger()
    reservation_id = reserve(ledger, "2")
    with pytest.raises(CreditLimitExceeded):
        ledger.settle_work(
            reservation_id=reservation_id,
            work_key="too-large",
            attempt_id="attempt-1",
            attempt_kind=AttemptKind.PRIMARY,
            verification_state=VerificationState.VERIFIED,
            canonical_credits=Decimal("3"),
            occurred_at=NOW,
            idempotency_key="too-large",
        )
    release = ledger.release_remaining(
        reservation_id=reservation_id,
        occurred_at=NOW,
        idempotency_key="release",
    )
    assert release.amount == Decimal("2.000000")
    assert ledger.balance(reservation_id) == (
        Decimal("0"),
        Decimal("2.000000"),
        Decimal("0.000000"),
    )
