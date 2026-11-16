from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Thread

import pytest
from akc_parallel_runtime import (
    ArbitrationBasis,
    ArbitrationDecision,
    AttemptConflictError,
    AttemptError,
    AttemptKind,
    AttemptOutput,
    AttemptStatus,
    AttemptStore,
    CostRecord,
    CreditEntryType,
    CreditLedger,
    InvalidAttemptTransition,
    ParallelCoordinator,
    VerificationState,
    select_first_verified,
)
from akc_parallel_runtime.coordinator import SettlementRequest
from akc_parallel_runtime.first_verified import VerifiedCandidate
from akc_parallel_runtime.identity import canonical_sha256
from helpers import HASH_A, HASH_B, HASH_C, HASH_D, NOW

SHARD = "shard-1"


def root(store: AttemptStore, key: str = "root") -> str:
    return store.create_root(
        idempotency_key=key,
        document_id="doc-1",
        document_version_id="docv-1",
        shard_id=SHARD,
        page_ids=("p1",),
        region_ids=(),
        parser_recipe="precision-v1",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        worker_id=f"worker-{key}",
        gpu_type="L40S",
        source_sha256=HASH_A,
        preprocessing_sha256=HASH_B,
        prompt_sha256=HASH_C,
        decoding_sha256=HASH_D,
        created_at=NOW,
    ).attempt.attempt_id


def hedge(store: AttemptStore, parent: str, key: str) -> str:
    return store.create_child(
        parent,
        kind=AttemptKind.HEDGE,
        idempotency_key=key,
        parser_recipe="precision-v1",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        worker_id=f"worker-{key}",
        gpu_type="L40S",
        preprocessing_sha256=HASH_B,
        prompt_sha256=HASH_C,
        decoding_sha256=HASH_D,
        created_at=NOW + timedelta(seconds=1),
    ).attempt.attempt_id


def step(store: AttemptStore, attempt_id: str, frm: AttemptStatus, to: AttemptStatus) -> None:
    store.transition(
        attempt_id,
        expected_status=frm,
        to_status=to,
        occurred_at=NOW + timedelta(seconds=2),
        reason_code="test",
    )


def run(store: AttemptStore, attempt_id: str) -> None:
    step(store, attempt_id, AttemptStatus.CREATED, AttemptStatus.QUEUED)
    step(store, attempt_id, AttemptStatus.QUEUED, AttemptStatus.RUNNING)


def output(prediction: str = HASH_A, **cost: Decimal) -> AttemptOutput:
    return AttemptOutput(
        f"s3://predictions/{prediction[:6]}.json",
        prediction,
        NOW + timedelta(seconds=3),
        cost=CostRecord(**cost),
    )


def validate(
    store: AttemptStore, attempt_id: str, *, passed: bool, prediction: str = HASH_A
) -> None:
    run(store, attempt_id)
    store.attach_output(attempt_id, output(prediction), idempotency_key=f"out-{attempt_id}")
    store.record_validation(
        attempt_id,
        validation_digest=prediction,
        passed=passed,
        occurred_at=NOW + timedelta(seconds=4),
    )


def decision(attempt_id: str, prediction: str = HASH_A) -> ArbitrationDecision:
    return ArbitrationDecision(
        decision_id="d",
        scope_id="cell",
        selected_attempt_id=attempt_id,
        selected_prediction_sha256=prediction,
        basis=ArbitrationBasis.AUTHORITY_EXACT,
        verification_state=VerificationState.VERIFIED,
        accepted=True,
        billable=True,
        reason_codes=(),
        considered_attempt_ids=(attempt_id,),
        excluded_hard_gate_attempt_ids=(),
        decision_sha256=HASH_A,
    )


def accept(store: AttemptStore, attempt_id: str, key: str = "k"):
    return store.accept(attempt_id, occurred_at=NOW + timedelta(seconds=5), idempotency_key=key)


def test_validation_failed_attempt_cannot_be_accepted_even_if_first() -> None:
    store = AttemptStore()
    a = root(store)
    validate(store, a, passed=False)
    assert store.get(a).status is AttemptStatus.REJECTED
    with pytest.raises(InvalidAttemptTransition):
        accept(store, a)


def test_faster_unverified_attempt_loses_to_slower_verified_one() -> None:
    store = AttemptStore()
    fast = root(store, "fast")
    slow = root(store, "slow")
    validate(store, fast, passed=False, prediction=HASH_B)
    validate(store, slow, passed=True)
    with pytest.raises(InvalidAttemptTransition):
        accept(store, fast, "fast")
    assert accept(store, slow, "slow").accepted_new is True
    # offline helper agrees: eligibility needs zero hard failures
    early = VerifiedCandidate("fast", NOW, 5, 1, HASH_B)
    late = VerifiedCandidate("slow", NOW + timedelta(seconds=9), 5, 0, HASH_A)
    assert select_first_verified((early, late)) == late


def test_winner_supersedes_live_siblings_and_returns_them_for_cancel() -> None:
    store = AttemptStore()
    winner = root(store, "w")
    running = hedge(store, winner, "h-run")
    queued = hedge(store, winner, "h-queue")
    done = hedge(store, winner, "h-out")
    validate(store, winner, passed=True)
    run(store, running)
    step(store, queued, AttemptStatus.CREATED, AttemptStatus.QUEUED)
    run(store, done)
    store.attach_output(done, output(HASH_B), idempotency_key="out-done")
    accept(store, winner)
    cancel = store.supersede_siblings(SHARD, winner, NOW + timedelta(seconds=6))
    assert set(cancel) == {running, queued, done}
    assert all(store.get(i).status is AttemptStatus.SUPERSEDED for i in cancel)
    assert store.get(winner).status is AttemptStatus.ACCEPTED


def test_supersede_siblings_replay_is_a_noop_and_needs_the_accepted_winner() -> None:
    store = AttemptStore()
    winner = root(store, "w")
    sibling = hedge(store, winner, "h")
    run(store, sibling)
    with pytest.raises(AttemptConflictError):
        store.supersede_siblings(SHARD, winner, NOW + timedelta(seconds=6))
    validate(store, winner, passed=True)
    accept(store, winner)
    first = store.supersede_siblings(SHARD, winner, NOW + timedelta(seconds=6))
    n = len(store.get(sibling).transitions)
    again = store.supersede_siblings(SHARD, winner, NOW + timedelta(seconds=7))
    assert first == again == (sibling,)
    assert len(store.get(sibling).transitions) == n
    assert store.get(sibling).transitions[-1].reason_code == "superseded_by_verified_winner"
    with pytest.raises(AttemptConflictError):
        store.supersede_siblings("other-shard", winner, NOW + timedelta(seconds=7))


def test_late_output_on_superseded_attempt_is_refused() -> None:
    store = AttemptStore()
    winner = root(store, "w")
    loser = hedge(store, winner, "h")
    run(store, loser)
    validate(store, winner, passed=True)
    accept(store, winner)
    store.supersede_siblings(SHARD, winner, NOW + timedelta(seconds=6))
    with pytest.raises(InvalidAttemptTransition):
        store.attach_output(loser, output(HASH_B), idempotency_key="late")
    assert store.get(loser).output is None


def test_winner_charged_once_and_hedge_loser_gets_zero_charge_plus_telemetry() -> None:
    ledger = CreditLedger()
    reservation = ledger.reserve(
        account_id="a", job_id="j", amount=Decimal("10"), occurred_at=NOW, idempotency_key="r"
    ).reservation_id
    coordinator = ParallelCoordinator(credits=ledger)
    store = coordinator.attempts
    winner = root(store, "w")
    loser = hedge(store, winner, "h")
    run(store, loser)
    store.attach_output(
        loser,
        output(HASH_B, gpu_seconds=Decimal("3"), provider_cost=Decimal("0.5")),
        idempotency_key="out-loser",
    )
    silent = hedge(store, winner, "h2")
    run(store, silent)
    validate(store, winner, passed=True)
    request = SettlementRequest(reservation, "page-1", Decimal("2"))
    result = coordinator.accept_arbitrated(
        decision(winner),
        occurred_at=NOW + timedelta(seconds=6),
        idempotency_key="acc",
        settlement=request,
    )
    assert set(result.cancel_attempt_ids) == {loser, silent}
    assert store.get(loser).status is AttemptStatus.SUPERSEDED
    replay = coordinator.accept_arbitrated(
        decision(winner),
        occurred_at=NOW + timedelta(seconds=7),
        idempotency_key="acc",
        settlement=request,
    )
    assert set(replay.cancel_attempt_ids) == {loser, silent}
    assert ledger.balance(reservation)[0] == Decimal("2.000000")
    telemetry = [
        e
        for e in ledger.entries(reservation)
        if e.entry_type is CreditEntryType.COMPUTE_TELEMETRY
    ]
    # only the loser with a recorded output has measured cost; the RUNNING one gets no row
    assert [(e.attempt_id, e.amount) for e in telemetry] == [(loser, Decimal("0"))]
    assert telemetry[0].metadata_sha256 == canonical_sha256(
        {
            "attempt_kind": "hedge",
            "gpu_seconds": Decimal("3.000000"),
            "provider_cost": Decimal("0.500000"),
            "user_credits": "0.000000",
        }
    )


def test_settlement_without_ledger_or_ledger_without_settlement_raises() -> None:
    plain = ParallelCoordinator()
    winner = root(plain.attempts, "w")
    validate(plain.attempts, winner, passed=True)
    request = SettlementRequest("r", "page-1", Decimal("2"))
    with pytest.raises(RuntimeError, match="without a credit ledger"):
        plain.accept_arbitrated(
            decision(winner), occurred_at=NOW, idempotency_key="acc", settlement=request
        )
    assert plain.attempts.get(winner).status is not AttemptStatus.ACCEPTED
    funded = ParallelCoordinator(credits=CreditLedger())
    winner2 = root(funded.attempts, "w")
    validate(funded.attempts, winner2, passed=True)
    with pytest.raises(RuntimeError, match="no settlement"):
        funded.accept_arbitrated(decision(winner2), occurred_at=NOW, idempotency_key="acc")


def test_eight_threads_racing_accept_produce_exactly_one_accepted() -> None:
    store = AttemptStore()
    ids = [root(store, f"r{i}") for i in range(8)]
    for i, attempt_id in enumerate(ids):
        validate(store, attempt_id, passed=True, prediction=f"{i:064x}")
    barrier = Barrier(8)
    results: list[bool] = []
    errors: list[BaseException] = []

    def go(attempt_id: str) -> None:
        barrier.wait()
        try:
            results.append(accept(store, attempt_id, f"k-{attempt_id}").accepted_new)
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=go, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results.count(True) == 1
    statuses = [store.get(i).status for i in ids]
    assert statuses.count(AttemptStatus.ACCEPTED) == 1
    assert statuses.count(AttemptStatus.SUPERSEDED) == 7


def test_arbitration_decision_naming_a_rejected_attempt_raises() -> None:
    coordinator = ParallelCoordinator()
    bad = root(coordinator.attempts, "bad")
    validate(coordinator.attempts, bad, passed=False)
    with pytest.raises(RuntimeError, match="failed validation"):
        coordinator.accept_arbitrated(
            decision(bad), occurred_at=NOW + timedelta(seconds=6), idempotency_key="acc"
        )
    assert coordinator.attempts.get(bad).status is AttemptStatus.REJECTED
    assert issubclass(InvalidAttemptTransition, AttemptError)
