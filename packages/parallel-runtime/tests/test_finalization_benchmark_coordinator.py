from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from akc_parallel_runtime import (
    AdaptiveShardPredictor,
    ArbitrationCandidate,
    Arbitrator,
    AttemptOutput,
    AttemptStatus,
    BenchmarkEnvironmentIdentity,
    BenchmarkUnitResult,
    DeterministicShardPlanner,
    DispatchSpec,
    EventJournal,
    FinalizationConflictError,
    FinalizationUnit,
    Finalizer,
    PageClass,
    PageDescriptor,
    ParallelCoordinator,
    ValidationPolicy,
    VerificationState,
    aggregate_repeat,
    verify_repeat_environment_identity,
)
from helpers import HASH_A, HASH_B, HASH_C, HASH_D, NOW, valid_observation


def unit(
    unit_id: str,
    state: VerificationState,
    *,
    required: bool = True,
    attempts: tuple[str, ...] = ("attempt-1",),
) -> FinalizationUnit:
    accepted = state in {
        VerificationState.VERIFIED,
        VerificationState.AUTHORITY_VERIFIED,
        VerificationState.CROSS_MODEL_VERIFIED,
        VerificationState.AUTO_REPAIRED,
    }
    return FinalizationUnit(
        unit_id=unit_id,
        state=state,
        prediction_sha256=HASH_A if accepted else None,
        source_refs=(f"source://{unit_id}",),
        provenance_attempt_ids=attempts if accepted else (),
        required=required,
        reason_codes=() if accepted else (f"{state.value}_reason",),
    )


def environment(**overrides: str) -> BenchmarkEnvironmentIdentity:
    values = {
        "runtime_image_digest": "sha256:image-a",
        "model_revision": "model@abc123",
        "gpu_class": "L40S",
        "cuda_version": "12.8",
        "prompt_sha256": HASH_A,
        "decoding_sha256": HASH_B,
        "dataset_sha256": HASH_C,
        "evaluator_revision": "evaluator@def456",
    }
    values.update(overrides)
    return BenchmarkEnvironmentIdentity(**values)


def test_finalization_includes_only_verified_states_and_fails_closed() -> None:
    result = Finalizer().finalize(
        document_version_id="docv-1",
        units=(
            unit("verified", VerificationState.VERIFIED),
            unit("authority", VerificationState.AUTHORITY_VERIFIED),
            unit("cross", VerificationState.CROSS_MODEL_VERIFIED),
            unit(
                "repaired",
                VerificationState.AUTO_REPAIRED,
                attempts=("base", "repair"),
            ),
            unit("unresolved", VerificationState.UNRESOLVED),
            unit("quarantined", VerificationState.QUARANTINED),
            unit("failed", VerificationState.FAILED),
        ),
        merge_sha256=HASH_D,
        occurred_at=NOW,
        idempotency_key="finalize-1",
    )
    assert result.publishable is False
    assert {item.unit_id for item in result.accepted_units} == {
        "verified",
        "authority",
        "cross",
        "repaired",
    }
    assert [item.unit_id for item in result.unresolved_manifest] == ["unresolved"]
    assert result.excluded_unit_ids == ("quarantined", "failed")
    assert set(result.billable_unit_ids) == {
        "verified",
        "authority",
        "cross",
        "repaired",
    }


def test_optional_unresolved_unit_can_be_exported_as_non_blocking_manifest() -> None:
    result = Finalizer().finalize(
        document_version_id="docv-1",
        units=(
            unit("verified", VerificationState.VERIFIED),
            unit("optional", VerificationState.UNRESOLVED, required=False),
        ),
        merge_sha256=HASH_D,
        occurred_at=NOW,
        idempotency_key="finalize-1",
    )
    assert result.publishable is True
    assert len(result.unresolved_manifest) == 1


def test_auto_repair_requires_base_and_repair_lineage() -> None:
    with pytest.raises(ValueError, match="base and repair"):
        unit("bad-repair", VerificationState.AUTO_REPAIRED)


def test_publishable_finalization_emits_event_and_is_idempotent() -> None:
    events = EventJournal()
    finalizer = Finalizer(events=events)
    arguments = {
        "document_version_id": "docv-1",
        "units": (unit("verified", VerificationState.VERIFIED),),
        "merge_sha256": HASH_D,
        "occurred_at": NOW,
        "idempotency_key": "finalize-1",
    }
    first = finalizer.finalize(**arguments)
    assert finalizer.finalize(**arguments) is first
    assert events.events()[0].event_type == "document.finalized.v1"
    with pytest.raises(FinalizationConflictError):
        finalizer.finalize(
            **{
                **arguments,
                "units": (unit("different", VerificationState.VERIFIED),),
            }
        )


def test_benchmark_three_repeats_require_identical_environment() -> None:
    identity = environment()
    assert verify_repeat_environment_identity((identity, identity, identity)) == identity.digest
    with pytest.raises(ValueError, match="identical environment"):
        verify_repeat_environment_identity(
            (identity, identity, environment(model_revision="model@changed"))
        )
    with pytest.raises(ValueError, match="exactly three"):
        verify_repeat_environment_identity((identity, identity))


def test_benchmark_aggregate_is_order_deterministic_and_repeat_isolated() -> None:
    identity = environment()
    a = BenchmarkUnitResult(1, "unit-a", identity.digest, HASH_A, Decimal("0.8"))
    b = BenchmarkUnitResult(1, "unit-b", identity.digest, HASH_B, Decimal("1.0"))
    left = aggregate_repeat((a, b), expected_environment=identity)
    right = aggregate_repeat((b, a), expected_environment=identity)
    assert left == right
    assert left.mean_score == Decimal("0.900000000000")
    assert a.artifact_namespace == "run-1/unit-a"
    with pytest.raises(ValueError, match="cannot be mixed"):
        aggregate_repeat(
            (a, replace(b, repeat_index=2)), expected_environment=identity
        )


def test_benchmark_aggregate_detects_environment_drift_and_duplicate_units() -> None:
    identity = environment()
    result = BenchmarkUnitResult(1, "unit-a", identity.digest, HASH_A, Decimal("0.8"))
    with pytest.raises(ValueError, match="environment drift"):
        aggregate_repeat(
            (replace(result, environment_sha256=HASH_D),),
            expected_environment=identity,
        )
    with pytest.raises(ValueError, match="unique"):
        aggregate_repeat((result, result), expected_environment=identity)
    with pytest.raises(ValueError, match="thread and process safe"):
        aggregate_repeat(
            (result,), expected_environment=replace(identity, evaluator_thread_safe=False)
        )
    with pytest.raises(ValueError, match="safe artifact path"):
        BenchmarkUnitResult(1, "../escape", identity.digest, HASH_A, Decimal("0.8"))


def test_coordinator_end_to_end_requires_validation_and_arbitration() -> None:
    events = EventJournal()
    coordinator = ParallelCoordinator(events=events)
    page = PageDescriptor(
        page_id="p1",
        index0=0,
        page_class=PageClass.NORMAL_SCAN,
        width_px=1000,
        height_px=1400,
        token_estimate=500,
        expected_output_tokens=300,
    )
    plan = DeterministicShardPlanner(AdaptiveShardPredictor()).plan(
        document_id="doc-1",
        document_version_id="docv-1",
        source_sha256=HASH_A,
        pages=(page,),
    )
    coordinator.record_plan(plan, occurred_at=NOW, idempotency_prefix="plan")
    spec = DispatchSpec(
        document_id="doc-1",
        document_version_id="docv-1",
        shard_id=plan.shards[0].shard_id,
        page_ids=("p1",),
        region_ids=(),
        parser_recipe="precision-v1",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        worker_id="worker-a",
        gpu_type="L40S",
        source_sha256=HASH_A,
        preprocessing_sha256=HASH_B,
        prompt_sha256=HASH_C,
        decoding_sha256=HASH_D,
    )
    dispatched = coordinator.dispatch(
        spec, occurred_at=NOW, idempotency_key="dispatch-1"
    )
    assert coordinator.dispatch(
        spec, occurred_at=NOW, idempotency_key="dispatch-1"
    ).attempt.attempt_id == dispatched.attempt.attempt_id
    coordinator.start(dispatched.attempt.attempt_id, occurred_at=NOW + timedelta(seconds=1))
    snapshot, validation = coordinator.receive_and_validate(
        dispatched.attempt.attempt_id,
        output=AttemptOutput(
            "s3://predictions/a.json", HASH_A, NOW + timedelta(seconds=2)
        ),
        observation=valid_observation(),
        policy=ValidationPolicy(expected_page_ids=("p1",)),
        occurred_at=NOW + timedelta(seconds=3),
        idempotency_key="candidate-1",
    )
    assert snapshot.status is AttemptStatus.VALIDATING
    assert validation.passed is True
    arbitration = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            ArbitrationCandidate(
                attempt_id=dispatched.attempt.attempt_id,
                prediction_sha256=HASH_A,
                hard_gate_pass=True,
                numeric_value=Decimal("100"),
                structure_fingerprint="shape-a",
                independent_family="authority",
                authority_exact=True,
                source_coverage=1,
                structure_score=1,
                cross_model_agreement=1,
                runtime_reliability=1,
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="prediction identity"):
        coordinator.accept_arbitrated(
            replace(arbitration, selected_prediction_sha256=HASH_B),
            occurred_at=NOW + timedelta(seconds=4),
            idempotency_key="accept-mismatch",
        )
    accepted = coordinator.accept_arbitrated(
        arbitration,
        occurred_at=NOW + timedelta(seconds=4),
        idempotency_key="accept-1",
    )
    assert accepted.winner.status is AttemptStatus.ACCEPTED
    assert [event.event_type for event in events.events()] == [
        "shard.planned.v1",
        "shard.dispatched.v1",
        "attempt.started.v1",
        "attempt.output.received.v1",
        "attempt.accepted.v1",
    ]


def test_coordinator_rejects_unresolved_or_prediction_identity_mismatch() -> None:
    coordinator = ParallelCoordinator()
    unresolved = Arbitrator().arbitrate_numeric(
        "cell-1",
        (
            ArbitrationCandidate(
                attempt_id="a1",
                prediction_sha256=HASH_A,
                hard_gate_pass=True,
                numeric_value=Decimal("100"),
                structure_fingerprint="shape",
                independent_family="same",
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="unresolved"):
        coordinator.accept_arbitrated(
            unresolved, occurred_at=NOW, idempotency_key="accept"
        )


def test_coordinator_rejects_unplanned_dispatch_and_scope_redefinition() -> None:
    coordinator = ParallelCoordinator()
    spec = DispatchSpec(
        document_id="doc-1",
        document_version_id="docv-1",
        shard_id="not-planned",
        page_ids=("p1",),
        region_ids=(),
        parser_recipe="precision-v1",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        worker_id="worker-a",
        gpu_type="L40S",
        source_sha256=HASH_A,
        preprocessing_sha256=HASH_B,
        prompt_sha256=HASH_C,
        decoding_sha256=HASH_D,
    )
    with pytest.raises(RuntimeError, match="unplanned"):
        coordinator.dispatch(spec, occurred_at=NOW, idempotency_key="dispatch")
