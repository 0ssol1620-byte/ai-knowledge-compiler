from __future__ import annotations

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
    WorkerType,
    diagnose_failure,
)


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
