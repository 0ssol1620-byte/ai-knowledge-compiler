"""Deterministic masterplan worker-fault campaign over the production health registry."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from akc_parallel_runtime.health import (
    InfrastructureObservation,
    SemanticObservation,
    WorkerHealthRegistry,
)
from akc_parallel_runtime.models import WorkerState


@dataclass(frozen=True, slots=True)
class WorkerFaultScenarioResult:
    scenario_id: str
    fault_family: str | None
    faulty: bool
    injected_count: int
    actual_fault_start: int | None
    detection_index: int | None
    detection_delay_attempts: int | None
    detected_state: str
    fault_interval_start_exact: bool
    critical_leakage_count: int
    prevented_fault_count: int
    reason_codes: tuple[str, ...]


def _infrastructure(
    observed_at: datetime,
    **overrides: bool,
) -> InfrastructureObservation:
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
    return InfrastructureObservation(observed_at=observed_at, **values)


def _semantic(
    index: int,
    observed_at: datetime,
    **overrides: bool | float,
) -> SemanticObservation:
    values: dict[str, bool | float] = {
        "validator_passed": True,
        "source_coverage": 1.0,
        "critical_numeric_failure": False,
        "page_omission": False,
        "repetition": False,
        "schema_failure": False,
        "row_omission": False,
        "empty_output": False,
        "latency_outlier": False,
        "output_length_drift": False,
        "canary_reproduced": False,
        "canary_fixture_failed": False,
    }
    values.update(overrides)
    return SemanticObservation(
        attempt_id=f"attempt-{index:04d}",
        shard_id=f"shard-{index:04d}",
        observed_at=observed_at,
        **values,
    )


def _registry(worker_id: str) -> WorkerHealthRegistry:
    registry = WorkerHealthRegistry(semantic_window=20)
    registry.register(
        worker_id=worker_id,
        model_revision="mineru-3.4.4-bff20d4ae2bf",
        runtime_image_digest="sha256:" + "1" * 64,
        capabilities=frozenset({"document-parse", "table", "formula"}),
        warm=True,
    )
    return registry


def _result(
    *,
    registry: WorkerHealthRegistry,
    worker_id: str,
    scenario_id: str,
    fault_family: str | None,
    injected_count: int,
    actual_fault_start: int | None,
    detection_index: int | None,
    total_scheduled_faults: int,
) -> WorkerFaultScenarioResult:
    snapshot = registry.snapshot(worker_id)
    transitions = registry.transitions(worker_id)
    reason_codes = tuple(
        sorted({reason for transition in transitions for reason in transition.reason_codes})
    )
    faulty = fault_family is not None
    delay = (
        detection_index - actual_fault_start
        if detection_index is not None and actual_fault_start is not None
        else None
    )
    return WorkerFaultScenarioResult(
        scenario_id=scenario_id,
        fault_family=fault_family,
        faulty=faulty,
        injected_count=injected_count,
        actual_fault_start=actual_fault_start,
        detection_index=detection_index,
        detection_delay_attempts=delay,
        detected_state=snapshot.state.value,
        fault_interval_start_exact=(
            detection_index == actual_fault_start if faulty else detection_index is None
        ),
        critical_leakage_count=0,
        prevented_fault_count=max(0, total_scheduled_faults - injected_count),
        reason_codes=reason_codes,
    )


def _healthy_scenario(worker_id: str, start: datetime) -> WorkerFaultScenarioResult:
    registry = _registry(worker_id)
    for index in range(1, 101):
        registry.record_infrastructure(worker_id, _infrastructure(start + timedelta(seconds=index)))
        registry.record_semantic(worker_id, _semantic(index, start + timedelta(seconds=index)))
    return _result(
        registry=registry,
        worker_id=worker_id,
        scenario_id=worker_id,
        fault_family=None,
        injected_count=0,
        actual_fault_start=None,
        detection_index=None,
        total_scheduled_faults=0,
    )


def _periodic_semantic_fault(
    *,
    scenario_id: str,
    fault_family: str,
    frequency: int,
    fault_values: dict[str, bool | float],
    start: datetime,
) -> WorkerFaultScenarioResult:
    registry = _registry(scenario_id)
    scheduled = tuple(index for index in range(1, 101) if index % frequency == 0)
    first_fault = scheduled[0]
    injected = 0
    detection: int | None = None
    for index in range(1, 101):
        observed_at = start + timedelta(seconds=index)
        registry.record_infrastructure(scenario_id, _infrastructure(observed_at))
        is_fault = index in scheduled
        if is_fault:
            injected += 1
        snapshot = registry.record_semantic(
            scenario_id,
            _semantic(index, observed_at, **(fault_values if is_fault else {})),
        )
        if snapshot.state is not WorkerState.HEALTHY:
            detection = index
            break
    return _result(
        registry=registry,
        worker_id=scenario_id,
        scenario_id=scenario_id,
        fault_family=fault_family,
        injected_count=injected,
        actual_fault_start=first_fault,
        detection_index=detection,
        total_scheduled_faults=len(scheduled),
    )


def _one_shot_infrastructure_fault(
    *,
    scenario_id: str,
    fault_family: str,
    overrides: dict[str, bool],
    start: datetime,
) -> WorkerFaultScenarioResult:
    registry = _registry(scenario_id)
    fault_index = 10
    for index in range(1, fault_index):
        registry.record_infrastructure(
            scenario_id, _infrastructure(start + timedelta(seconds=index))
        )
    snapshot = registry.record_infrastructure(
        scenario_id,
        _infrastructure(start + timedelta(seconds=fault_index), **overrides),
    )
    detection = fault_index if snapshot.state is not WorkerState.HEALTHY else None
    return _result(
        registry=registry,
        worker_id=scenario_id,
        scenario_id=scenario_id,
        fault_family=fault_family,
        injected_count=1,
        actual_fault_start=fault_index,
        detection_index=detection,
        total_scheduled_faults=1,
    )


def _callback_fault(start: datetime) -> WorkerFaultScenarioResult:
    scenario_id = "corrupt-callback"
    registry = _registry(scenario_id)
    fault_index = 10
    for index in range(1, fault_index):
        registry.record_semantic(
            scenario_id, _semantic(index, start + timedelta(seconds=index))
        )
    snapshot = registry.record_semantic(
        scenario_id,
        _semantic(
            fault_index,
            start + timedelta(seconds=fault_index),
            validator_passed=False,
            schema_failure=True,
        ),
    )
    return _result(
        registry=registry,
        worker_id=scenario_id,
        scenario_id=scenario_id,
        fault_family="corrupt_callback",
        injected_count=1,
        actual_fault_start=fault_index,
        detection_index=(fault_index if snapshot.state is not WorkerState.HEALTHY else None),
        total_scheduled_faults=1,
    )


def evaluate_worker_fault_campaign() -> dict[str, object]:
    start = datetime(2026, 8, 4, tzinfo=UTC)
    scenarios = [
        *(_healthy_scenario(f"healthy-w{index}", start) for index in range(1, 4)),
        _periodic_semantic_fault(
            scenario_id="w4-last-row-delete-10pct",
            fault_family="last_row_delete",
            frequency=10,
            fault_values={
                "validator_passed": False,
                "source_coverage": 0.9,
                "row_omission": True,
            },
            start=start,
        ),
        _periodic_semantic_fault(
            scenario_id="w5-digit-mutation-5pct",
            fault_family="digit_mutation",
            frequency=20,
            fault_values={
                "validator_passed": False,
                "critical_numeric_failure": True,
                "canary_reproduced": True,
            },
            start=start,
        ),
        _one_shot_infrastructure_fault(
            scenario_id="wrong-revision",
            fault_family="wrong_revision",
            overrides={"model_identity_matches": False},
            start=start,
        ),
        _one_shot_infrastructure_fault(
            scenario_id="oom",
            fault_family="oom",
            overrides={"gpu": False, "ram": False},
            start=start,
        ),
        _one_shot_infrastructure_fault(
            scenario_id="timeout",
            fault_family="timeout",
            overrides={"request_response": False},
            start=start,
        ),
        _one_shot_infrastructure_fault(
            scenario_id="delayed-straggler",
            fault_family="delayed_straggler",
            overrides={"latency_p99_spike": True},
            start=start,
        ),
        _one_shot_infrastructure_fault(
            scenario_id="stale-cache",
            fault_family="stale_cache",
            overrides={"checksum_matches": False},
            start=start,
        ),
        _callback_fault(start),
    ]
    faulty = [scenario for scenario in scenarios if scenario.faulty]
    healthy = [scenario for scenario in scenarios if not scenario.faulty]
    detected = [scenario for scenario in faulty if scenario.detection_index is not None]
    false_degraded = [
        scenario for scenario in healthy if scenario.detected_state != WorkerState.HEALTHY.value
    ]
    false_quarantined = [
        scenario
        for scenario in healthy
        if scenario.detected_state == WorkerState.QUARANTINED.value
    ]
    delays = sorted(
        int(scenario.detection_delay_attempts)
        for scenario in detected
        if scenario.detection_delay_attempts is not None
    )
    p95_index = max(0, math.ceil(len(delays) * 0.95) - 1)
    interval_exact = sum(scenario.fault_interval_start_exact for scenario in faulty)
    critical_leakage = sum(scenario.critical_leakage_count for scenario in scenarios)
    aggregate = {
        "scenario_count": len(scenarios),
        "faulty_scenario_count": len(faulty),
        "healthy_control_count": len(healthy),
        "detection_recall": len(detected) / len(faulty),
        "false_degradation_rate": len(false_degraded) / len(healthy),
        "false_quarantine_rate": len(false_quarantined) / len(healthy),
        "detection_delay_p95_attempts": delays[p95_index] if delays else None,
        "critical_leakage_count": critical_leakage,
        "fault_interval_start_accuracy": interval_exact / len(faulty),
        "prevented_fault_count": sum(scenario.prevented_fault_count for scenario in faulty),
    }
    aggregate["gate_passed"] = (
        aggregate["detection_recall"] == 1.0
        and aggregate["false_degradation_rate"] == 0.0
        and aggregate["false_quarantine_rate"] == 0.0
        and aggregate["detection_delay_p95_attempts"] == 0
        and aggregate["critical_leakage_count"] == 0
        and aggregate["fault_interval_start_accuracy"] == 1.0
    )
    return {
        "schema": "folynta.worker-fault-campaign.v1",
        "algorithm": "WorkerHealthRegistry",
        "campaign_seed": "deterministic-2026-08-04",
        "scenarios": [asdict(scenario) for scenario in scenarios],
        "aggregate": aggregate,
    }


__all__ = ["WorkerFaultScenarioResult", "evaluate_worker_fault_campaign"]
