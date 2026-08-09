from __future__ import annotations

from datetime import timedelta

import pytest
from akc_parallel_runtime import (
    DiagnosisState,
    EndpointPool,
    EndpointPoolRegistry,
    FailureClass,
    FailureObservation,
    PoolConflictError,
    PoolWorker,
    RuntimeStack,
    WorkerHealthRegistry,
    WorkerState,
    WorkerType,
    diagnose_failure,
    evaluate_pool_capacity,
)
from helpers import NOW


def stack(image: str = "sha256:image-a") -> RuntimeStack:
    return RuntimeStack(
        runtime_image_digest=image,
        framework="paddle",
        cuda_version="12.8",
        serving_runtime="paddle-inference",
    )


def pool(**overrides: object) -> EndpointPool:
    values: dict[str, object] = {
        "pool_id": "pool-paddle-vl",
        "model_revision": "paddle-vl@abc123",
        "worker_type": WorkerType.ACTIVE_WARM,
        "runtime_stack": stack(),
        "capabilities": frozenset({"scan", "table"}),
        "minimum_workers": 1,
        "maximum_workers": 2,
    }
    values.update(overrides)
    return EndpointPool(**values)  # type: ignore[arg-type]


def worker(worker_id: str = "worker-1", **overrides: object) -> PoolWorker:
    values: dict[str, object] = {
        "worker_id": worker_id,
        "pool_id": "pool-paddle-vl",
        "model_revision": "paddle-vl@abc123",
        "runtime_stack": stack(),
        "gpu_type": "L40S",
    }
    values.update(overrides)
    return PoolWorker(**values)  # type: ignore[arg-type]


def test_active_warm_and_flex_pool_scaling_contracts() -> None:
    with pytest.raises(ValueError, match="active warm"):
        pool(minimum_workers=0)
    with pytest.raises(ValueError, match="scale-to-zero"):
        pool(worker_type=WorkerType.FLEX, minimum_workers=1)
    assert pool(
        worker_type=WorkerType.FLEX,
        minimum_workers=0,
        maximum_workers=4,
    ).minimum_workers == 0


def test_endpoint_pool_is_model_and_runtime_stack_isolated() -> None:
    registry = EndpointPoolRegistry()
    registry.register_pool(pool())
    attached = registry.attach_worker(worker())
    assert registry.attach_worker(worker()) is attached
    with pytest.raises(PoolConflictError, match="model revision"):
        registry.attach_worker(worker("worker-2", model_revision="wrong@revision"))
    with pytest.raises(PoolConflictError, match="runtime stack"):
        registry.attach_worker(worker("worker-2", runtime_stack=stack("sha256:other")))


def test_endpoint_pool_capacity_and_identity_are_immutable() -> None:
    registry = EndpointPoolRegistry()
    registry.register_pool(pool(maximum_workers=1))
    registry.attach_worker(worker("worker-1"))
    with pytest.raises(PoolConflictError, match="maximum"):
        registry.attach_worker(worker("worker-2"))
    with pytest.raises(PoolConflictError, match="cannot be mutated"):
        registry.register_pool(pool(maximum_workers=3))


def test_http_200_semantic_failure_is_rejected_as_semantic() -> None:
    diagnosis = diagnose_failure(
        FailureObservation(
            http_status=200,
            response_schema_valid=True,
            reason_codes=frozenset({"blank_page"}),
        )
    )
    assert diagnosis.state is DiagnosisState.SEMANTIC_FAILED
    assert diagnosis.failure_class is FailureClass.SEMANTIC
    assert diagnosis.candidate_accepted is False
    assert "reject_attempt" in diagnosis.actions


@pytest.mark.parametrize(
    "observation",
    [
        FailureObservation(503, True, frozenset()),
        FailureObservation(200, False, frozenset()),
        FailureObservation(200, True, frozenset({"oom"})),
        FailureObservation(
            200,
            True,
            frozenset({"model_checksum_mismatch", "numeric_mutation"}),
        ),
    ],
)
def test_infrastructure_failures_use_worker_retry_and_drain_path(
    observation: FailureObservation,
) -> None:
    diagnosis = diagnose_failure(observation)
    assert diagnosis.state is DiagnosisState.INFRASTRUCTURE_FAILED
    assert diagnosis.failure_class is FailureClass.INFRASTRUCTURE
    assert diagnosis.actions[0] == "retry_same_recipe_different_worker"


def test_unknown_failure_code_is_not_treated_as_success() -> None:
    diagnosis = diagnose_failure(
        FailureObservation(200, True, frozenset({"novel_model_corruption"}))
    )
    assert diagnosis.state is DiagnosisState.SEMANTIC_FAILED
    assert "unclassified_semantic_failure_fail_closed" in diagnosis.reason_codes


def test_only_clean_transport_and_no_findings_is_healthy() -> None:
    diagnosis = diagnose_failure(FailureObservation(200, True, frozenset()))
    assert diagnosis.state is DiagnosisState.HEALTHY
    assert diagnosis.failure_class is None
    assert diagnosis.candidate_accepted is True


def test_pool_capacity_deficit_counts_only_workers_that_can_take_new_work() -> None:
    # A pool that has lost workers to a provider reclaim or an external deletion
    # must be able to say how many replacements it needs. Nothing expressed that
    # before, so a shrinking pool degraded silently.
    pool = EndpointPool(
        pool_id="mineru-pool",
        model_revision="mineru-3.4.4@pinned",
        worker_type=WorkerType.ACTIVE_WARM,
        runtime_stack=RuntimeStack(
            runtime_image_digest="sha256:" + "1" * 64,
            framework="torch",
            cuda_version="12.8",
            serving_runtime="vllm",
        ),
        capabilities=frozenset({"document"}),
        minimum_workers=3,
        maximum_workers=6,
    )
    workers = tuple(
        PoolWorker(
            worker_id=f"worker-{index}",
            pool_id="mineru-pool",
            model_revision="mineru-3.4.4@pinned",
            runtime_stack=pool.runtime_stack,
            gpu_type="RTX 4090",
        )
        for index in range(3)
    )

    full = evaluate_pool_capacity(
        pool=pool,
        pool_workers=workers,
        serving_worker_ids=frozenset({"worker-0", "worker-1", "worker-2"}),
    )
    assert full.satisfied
    assert full.replacements_required == 0
    assert full.unavailable_worker_ids == ()

    lost = evaluate_pool_capacity(
        pool=pool,
        pool_workers=workers,
        serving_worker_ids=frozenset({"worker-1"}),
    )
    assert not lost.satisfied
    assert lost.replacements_required == 2
    assert lost.serving_worker_count == 1
    assert lost.unavailable_worker_ids == ("worker-0", "worker-2")


def test_terminated_worker_is_distinguished_from_a_quarantined_one() -> None:
    # Quarantine means "stop trusting it"; termination means "the resource is
    # gone". A caller deciding whether to wait or acquire a replacement needs
    # the difference, and only quarantine existed before.
    registry = WorkerHealthRegistry()
    registry.register(
        worker_id="worker-a",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        capabilities=frozenset({"scan"}),
        warm=True,
        registered_at=NOW,
    )
    assert registry.serving_workers() == ("worker-a",)

    transition = registry.terminate(
        "worker-a", occurred_at=NOW + timedelta(minutes=1), reason="provider_resource_deleted"
    )
    assert transition is not None
    assert transition.to_state is WorkerState.TERMINATED
    assert transition.reason_codes == ("provider_resource_deleted",)
    assert registry.serving_workers() == ()
    # Terminal and idempotent: a second call reports no further transition.
    assert registry.terminate(
        "worker-a", occurred_at=NOW + timedelta(minutes=2), reason="provider_resource_deleted"
    ) is None


def test_terminate_requires_a_reason_and_an_aware_timestamp() -> None:
    registry = WorkerHealthRegistry()
    registry.register(
        worker_id="worker-a",
        model_revision="model@abc123",
        runtime_image_digest="sha256:image-a",
        capabilities=frozenset({"scan"}),
        warm=True,
    )
    with pytest.raises(ValueError, match="termination requires a reason code"):
        registry.terminate("worker-a", occurred_at=NOW, reason="")
    with pytest.raises(ValueError, match="termination time must be timezone-aware"):
        registry.terminate(
            "worker-a", occurred_at=NOW.replace(tzinfo=None), reason="provider_resource_deleted"
        )
