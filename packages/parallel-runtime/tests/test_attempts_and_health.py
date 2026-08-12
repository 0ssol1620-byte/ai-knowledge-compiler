from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta
from decimal import Decimal

import pytest
from akc_parallel_runtime import (
    AttemptConflictError,
    AttemptKind,
    AttemptOutput,
    AttemptStatus,
    AttemptStore,
    CostRecord,
    EventJournal,
    ImmutableAttemptError,
    InfrastructureObservation,
    InvalidAttemptTransition,
    SemanticObservation,
    WorkerHealthRegistry,
    WorkerRegistrationConflict,
    WorkerState,
)
from helpers import HASH_A, HASH_B, HASH_C, HASH_D, NOW


def create_root(
    store: AttemptStore,
    key: str = "root-1",
    *,
    worker_id: str = "worker-a",
    shard_id: str = "shard-1",
) -> str:
    return store.create_root(
        idempotency_key=key,
        document_id="doc-1",
        document_version_id="docv-1",
        shard_id=shard_id,
        page_ids=("p1",),
        region_ids=(),
        parser_recipe="precision-v1",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        worker_id=worker_id,
        gpu_type="L40S",
        source_sha256=HASH_A,
        preprocessing_sha256=HASH_B,
        prompt_sha256=HASH_C,
        decoding_sha256=HASH_D,
        created_at=NOW,
    ).attempt.attempt_id


def validate_attempt(
    store: AttemptStore,
    attempt_id: str,
    *,
    prediction_hash: str = HASH_A,
) -> None:
    store.transition(
        attempt_id,
        expected_status=AttemptStatus.CREATED,
        to_status=AttemptStatus.QUEUED,
        occurred_at=NOW,
        reason_code="dispatched",
    )
    store.transition(
        attempt_id,
        expected_status=AttemptStatus.QUEUED,
        to_status=AttemptStatus.RUNNING,
        occurred_at=NOW + timedelta(seconds=1),
        reason_code="started",
    )
    store.attach_output(
        attempt_id,
        AttemptOutput(
            prediction_uri=f"s3://predictions/{attempt_id}.json",
            prediction_sha256=prediction_hash,
            completed_at=NOW + timedelta(seconds=2),
            cost=CostRecord(gpu_seconds=Decimal("2"), provider_cost=Decimal("0.1")),
        ),
        idempotency_key=f"output:{attempt_id}",
    )
    store.record_validation(
        attempt_id,
        validation_digest=HASH_D,
        passed=True,
        occurred_at=NOW + timedelta(seconds=3),
    )


def register(registry: WorkerHealthRegistry, worker_id: str = "worker-a") -> None:
    registry.register(
        worker_id=worker_id,
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        capabilities=frozenset({"scan", "table"}),
        warm=True,
        cached_models=frozenset({"model@abc123"}),
    )


def infrastructure(**overrides: bool) -> InfrastructureObservation:
    values = {
        "ping": True,
        "process": True,
        "gpu": True,
        "ram": True,
        "disk": True,
        "model_loaded": True,
        "cuda_ready": True,
        "request_response": True,
        "heartbeat": True,
        "model_identity_matches": True,
        "checksum_matches": True,
        "memory_slope_exceeded": False,
        "latency_p99_spike": False,
    }
    values.update(overrides)
    return InfrastructureObservation(observed_at=NOW, **values)


def semantic(index: int, **overrides: object) -> SemanticObservation:
    values: dict[str, object] = {
        "attempt_id": f"attempt-{index}",
        "shard_id": f"shard-{index}",
        "observed_at": NOW + timedelta(seconds=index),
        "validator_passed": True,
        "source_coverage": 1.0,
    }
    values.update(overrides)
    return SemanticObservation(**values)  # type: ignore[arg-type]


def test_attempt_creation_is_exactly_once_and_immutable() -> None:
    store = AttemptStore()
    attempt_id = create_root(store)
    assert create_root(store) == attempt_id
    snapshot = store.get(attempt_id)
    with pytest.raises(FrozenInstanceError):
        snapshot.attempt.worker_id = "mutated"  # type: ignore[misc]
    with pytest.raises(AttemptConflictError):
        create_root(store, worker_id="worker-b")


def test_attempt_state_machine_rejects_skips_and_stale_expected_state() -> None:
    store = AttemptStore()
    attempt_id = create_root(store)
    with pytest.raises(InvalidAttemptTransition):
        store.transition(
            attempt_id,
            expected_status=AttemptStatus.CREATED,
            to_status=AttemptStatus.ACCEPTED,
            occurred_at=NOW,
            reason_code="skip",
        )
    store.transition(
        attempt_id,
        expected_status=AttemptStatus.CREATED,
        to_status=AttemptStatus.QUEUED,
        occurred_at=NOW,
        reason_code="queued",
    )
    with pytest.raises(AttemptConflictError):
        store.transition(
            attempt_id,
            expected_status=AttemptStatus.CREATED,
            to_status=AttemptStatus.QUEUED,
            occurred_at=NOW,
            reason_code="stale",
        )


def test_attempt_transitions_cannot_move_backwards_in_time() -> None:
    store = AttemptStore()
    attempt_id = create_root(store)
    with pytest.raises(InvalidAttemptTransition, match="chronological"):
        store.transition(
            attempt_id,
            expected_status=AttemptStatus.CREATED,
            to_status=AttemptStatus.QUEUED,
            occurred_at=NOW - timedelta(seconds=1),
            reason_code="backdated",
        )


def test_output_and_validation_digest_cannot_be_replaced() -> None:
    store = AttemptStore()
    attempt_id = create_root(store)
    validate_attempt(store, attempt_id)
    with pytest.raises(ImmutableAttemptError):
        store.attach_output(
            attempt_id,
            AttemptOutput(
                prediction_uri="s3://predictions/changed.json",
                prediction_sha256=HASH_B,
                completed_at=NOW + timedelta(seconds=2),
            ),
            idempotency_key="changed",
        )
    with pytest.raises(ImmutableAttemptError):
        store.record_validation(
            attempt_id,
            validation_digest=HASH_C,
            passed=True,
            occurred_at=NOW + timedelta(seconds=4),
        )


def test_acceptance_requires_validation_and_first_verified_wins() -> None:
    store = AttemptStore()
    first = create_root(store, "first", shard_id="shared")
    second = create_root(store, "second", worker_id="worker-b", shard_id="shared")
    with pytest.raises(InvalidAttemptTransition):
        store.accept(first, occurred_at=NOW, idempotency_key="too-early")
    validate_attempt(store, first, prediction_hash=HASH_A)
    validate_attempt(store, second, prediction_hash=HASH_B)
    winner = store.accept(
        first,
        occurred_at=NOW + timedelta(seconds=4),
        idempotency_key="accept-first",
    )
    challenger = store.accept(
        second,
        occurred_at=NOW + timedelta(seconds=4),
        idempotency_key="accept-second",
    )
    assert winner.accepted_new is True
    assert challenger.accepted_new is False
    assert challenger.winner.attempt.attempt_id == first
    assert challenger.challenger is not None
    assert challenger.challenger.status is AttemptStatus.SUPERSEDED
    assert store.accept(
        second,
        occurred_at=NOW + timedelta(seconds=5),
        idempotency_key="accept-second",
    ) is challenger


def test_retry_and_hedge_are_new_idempotent_children_with_full_lineage() -> None:
    store = AttemptStore()
    root = create_root(store)
    child = store.create_child(
        root,
        kind=AttemptKind.HEDGE,
        idempotency_key="hedge-1",
        parser_recipe="precision-v1",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        worker_id="worker-b",
        gpu_type="L40S",
        preprocessing_sha256=HASH_B,
        prompt_sha256=HASH_C,
        decoding_sha256=HASH_D,
        created_at=NOW + timedelta(seconds=2),
    )
    assert store.create_child(
        root,
        kind=AttemptKind.HEDGE,
        idempotency_key="hedge-1",
        parser_recipe="precision-v1",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        worker_id="worker-b",
        gpu_type="L40S",
        preprocessing_sha256=HASH_B,
        prompt_sha256=HASH_C,
        decoding_sha256=HASH_D,
        created_at=NOW + timedelta(seconds=2),
    ).attempt.attempt_id == child.attempt.attempt_id
    lineage = store.lineage(root)
    assert len(lineage) == 2
    assert child.attempt.root_attempt_id == root
    assert child.attempt.parent_attempt_id == root
    assert child.attempt.attempt_id != root


def test_rejected_semantic_output_can_never_be_accepted() -> None:
    store = AttemptStore()
    attempt_id = create_root(store)
    validate_attempt(store, attempt_id)
    # Use a fresh attempt because a validation receipt is immutable.
    rejected = create_root(store, "rejected", worker_id="worker-b", shard_id="shard-2")
    store.transition(
        rejected,
        expected_status=AttemptStatus.CREATED,
        to_status=AttemptStatus.QUEUED,
        occurred_at=NOW,
        reason_code="queued",
    )
    store.transition(
        rejected,
        expected_status=AttemptStatus.QUEUED,
        to_status=AttemptStatus.RUNNING,
        occurred_at=NOW,
        reason_code="started",
    )
    store.attach_output(
        rejected,
        AttemptOutput("s3://prediction/rejected", HASH_B, NOW + timedelta(seconds=1)),
        idempotency_key="rejected-output",
    )
    snapshot = store.record_validation(
        rejected,
        validation_digest=HASH_C,
        passed=False,
        occurred_at=NOW + timedelta(seconds=2),
        failure_reason="blank_page",
    )
    assert snapshot.status is AttemptStatus.REJECTED
    with pytest.raises(InvalidAttemptTransition):
        store.accept(rejected, occurred_at=NOW + timedelta(seconds=3), idempotency_key="bad")
    with pytest.raises(AttemptConflictError, match="failed to passed"):
        store.record_validation(
            rejected,
            validation_digest=HASH_C,
            passed=True,
            occurred_at=NOW + timedelta(seconds=4),
        )


def test_attempt_store_emits_declared_lifecycle_events() -> None:
    journal = EventJournal()
    store = AttemptStore(events=journal)
    attempt_id = create_root(store)
    validate_attempt(store, attempt_id)
    store.accept(attempt_id, occurred_at=NOW + timedelta(seconds=4), idempotency_key="accept")
    assert [event.event_type for event in journal.events()] == [
        "attempt.started.v1",
        "attempt.output.received.v1",
        "attempt.accepted.v1",
    ]


def test_quarantined_winner_releases_shard_for_verified_replay() -> None:
    journal = EventJournal()
    store = AttemptStore(events=journal)
    first = create_root(store, "first", shard_id="shared")
    validate_attempt(store, first, prediction_hash=HASH_A)
    store.accept(
        first,
        occurred_at=NOW + timedelta(seconds=4),
        idempotency_key="accept-first",
    )
    store.quarantine(
        first,
        occurred_at=NOW + timedelta(seconds=5),
        reason_code="canary_failure_influence_analysis",
    )
    replay = create_root(
        store,
        "replay",
        worker_id="worker-b",
        shard_id="shared",
    )
    validate_attempt(store, replay, prediction_hash=HASH_B)
    accepted = store.accept(
        replay,
        occurred_at=NOW + timedelta(seconds=6),
        idempotency_key="accept-replay",
    )
    assert accepted.accepted_new is True
    assert accepted.winner.attempt.attempt_id == replay
    assert store.get(first).status is AttemptStatus.QUARANTINED
    assert [
        event.event_type for event in journal.events() if event.event_type == "attempt.accepted.v1"
    ] == ["attempt.accepted.v1", "attempt.accepted.v1"]


def test_worker_registration_identity_is_immutable() -> None:
    registry = WorkerHealthRegistry()
    register(registry)
    register(registry)
    with pytest.raises(WorkerRegistrationConflict):
        registry.register(
            worker_id="worker-a",
            model_revision="different",
            runtime_image_digest="sha256:image-a",
            capabilities=frozenset({"scan", "table"}),
            warm=True,
        )


def test_model_identity_or_checksum_mismatch_quarantines_immediately() -> None:
    events = EventJournal()
    registry = WorkerHealthRegistry(events=events)
    register(registry)
    snapshot = registry.record_infrastructure(
        "worker-a", infrastructure(model_identity_matches=False)
    )
    assert snapshot.state is WorkerState.QUARANTINED
    assert events.events()[-1].event_type == "worker.quarantined.v1"


def test_infrastructure_probe_or_memory_slope_drains_worker() -> None:
    registry = WorkerHealthRegistry()
    register(registry)
    snapshot = registry.record_infrastructure(
        "worker-a", infrastructure(ping=False, memory_slope_exceeded=True)
    )
    assert snapshot.state is WorkerState.DRAINING


def test_three_consecutive_schema_failures_drain_semantically() -> None:
    registry = WorkerHealthRegistry()
    register(registry)
    for index in range(3):
        snapshot = registry.record_semantic(
            "worker-a",
            semantic(index, validator_passed=False, schema_failure=True),
        )
    assert snapshot.state is WorkerState.DRAINING
    assert "consecutive_schema_failures" in registry.transitions("worker-a")[-1].reason_codes


def test_two_consecutive_repetitions_drain_semantically() -> None:
    registry = WorkerHealthRegistry()
    register(registry)
    registry.record_semantic(
        "worker-a", semantic(1, validator_passed=False, repetition=True)
    )
    snapshot = registry.record_semantic(
        "worker-a", semantic(2, validator_passed=False, repetition=True)
    )
    assert snapshot.state is WorkerState.DRAINING


def test_critical_numeric_failure_requires_canary_reproduction_for_quarantine() -> None:
    registry = WorkerHealthRegistry()
    register(registry)
    degraded = registry.record_semantic(
        "worker-a",
        semantic(1, validator_passed=False, critical_numeric_failure=True),
    )
    assert degraded.state is WorkerState.DEGRADED
    quarantined = registry.record_semantic(
        "worker-a",
        semantic(
            2,
            validator_passed=False,
            critical_numeric_failure=True,
            canary_reproduced=True,
        ),
    )
    assert quarantined.state is WorkerState.QUARANTINED


def test_quarantine_influence_analysis_separates_pending_and_accepted() -> None:
    registry = WorkerHealthRegistry()
    register(registry)
    registry.record_attempt(
        "worker-a", attempt_id="a-running", shard_id="s1", status=AttemptStatus.RUNNING
    )
    registry.record_attempt(
        "worker-a", attempt_id="a-running", shard_id="s1", status=AttemptStatus.ACCEPTED
    )
    registry.record_attempt(
        "worker-a", attempt_id="a-accepted", shard_id="s2", status=AttemptStatus.ACCEPTED
    )
    registry.record_attempt(
        "worker-a", attempt_id="a-rejected", shard_id="s3", status=AttemptStatus.REJECTED
    )
    registry.record_semantic(
        "worker-a", semantic(1, canary_fixture_failed=True, validator_passed=False)
    )
    impact = registry.quarantine_impact("worker-a")
    assert impact.pending_attempt_ids == ()
    assert impact.accepted_attempt_ids_for_analysis == ("a-running", "a-accepted")
    assert impact.shard_ids_to_replay == ("s1", "s2")


def test_silent_infrastructure_channel_drains_then_quarantines() -> None:
    # Every other transition needs an observation to arrive. This covers the
    # case where none does, which is how a wedged control channel hid three
    # healthy-but-unreachable workers for five and a half hours in a live run.
    registry = WorkerHealthRegistry(
        signal_stale_after=timedelta(minutes=5),
        signal_silent_after=timedelta(minutes=20),
    )
    registry.register(
        worker_id="worker-a",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        capabilities=frozenset({"scan"}),
        warm=True,
        registered_at=NOW,
    )

    assert registry.evaluate_liveness(NOW + timedelta(minutes=4)) == ()
    assert registry.snapshot("worker-a").state is WorkerState.HEALTHY

    drained = registry.evaluate_liveness(NOW + timedelta(minutes=6))
    assert [item.to_state for item in drained] == [WorkerState.DRAINING]
    assert drained[0].reason_codes == ("infrastructure_signal_stale",)

    quarantined = registry.evaluate_liveness(NOW + timedelta(minutes=25))
    assert [item.to_state for item in quarantined] == [WorkerState.QUARANTINED]
    assert quarantined[0].reason_codes == ("infrastructure_signal_silent",)


def test_liveness_sweep_leaves_a_worker_that_keeps_signalling_alone() -> None:
    registry = WorkerHealthRegistry(
        signal_stale_after=timedelta(minutes=5),
        signal_silent_after=timedelta(minutes=20),
    )
    register(registry)
    for minute in (3, 6, 9, 12, 15, 18, 21, 24):
        observed_at = NOW + timedelta(minutes=minute)
        registry.record_infrastructure(
            "worker-a",
            InfrastructureObservation(
                observed_at=observed_at,
                ping=True,
                process=True,
                gpu=True,
                ram=True,
                disk=True,
                model_loaded=True,
                cuda_ready=True,
                request_response=True,
                heartbeat=True,
                model_identity_matches=True,
                checksum_matches=True,
            ),
        )
        assert registry.evaluate_liveness(observed_at) == ()

    assert registry.snapshot("worker-a").state is WorkerState.HEALTHY


def test_worker_without_a_liveness_baseline_is_reported_not_silently_passed() -> None:
    # register() without registered_at gives the sweep nothing to measure. That
    # must surface as an explicitly unmonitored worker rather than as health.
    registry = WorkerHealthRegistry()
    register(registry)

    assert registry.evaluate_liveness(NOW + timedelta(hours=6)) == ()
    assert registry.unmonitored_workers() == ("worker-a",)

    registry.record_infrastructure("worker-a", infrastructure())
    assert registry.unmonitored_workers() == ()
    silenced = registry.evaluate_liveness(NOW + timedelta(hours=6))
    assert [item.to_state for item in silenced] == [WorkerState.QUARANTINED]


def test_liveness_thresholds_must_be_ordered_and_positive() -> None:
    with pytest.raises(ValueError, match="stale signal threshold must be positive"):
        WorkerHealthRegistry(signal_stale_after=timedelta(0))
    with pytest.raises(ValueError, match="silent signal threshold must exceed"):
        WorkerHealthRegistry(
            signal_stale_after=timedelta(minutes=10),
            signal_silent_after=timedelta(minutes=10),
        )


def test_liveness_evaluation_requires_a_timezone_aware_clock() -> None:
    registry = WorkerHealthRegistry()
    register(registry)
    with pytest.raises(ValueError, match="liveness evaluation time must be timezone-aware"):
        registry.evaluate_liveness(NOW.replace(tzinfo=None))
