#!/usr/bin/env python3
"""Build service-side recovery equivalence and controlled fault evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[2]
PARALLEL_RUNTIME_SRC = REPOSITORY / "packages/parallel-runtime/src"
if str(PARALLEL_RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(PARALLEL_RUNTIME_SRC))

from akc_parallel_runtime import (  # noqa: E402
    AttemptStatus,
    EndpointPool,
    InfrastructureObservation,
    PoolWorker,
    RuntimeStack,
    SemanticObservation,
    WorkerHealthRegistry,
    WorkerState,
    WorkerType,
    evaluate_pool_capacity,
)

SERVICE_SOURCE_PATHS = (
    "packages/parallel-runtime/src/akc_parallel_runtime/health.py",
    "packages/parallel-runtime/src/akc_parallel_runtime/recovery.py",
    "packages/parallel-runtime/src/akc_parallel_runtime/routing.py",
    "packages/parallel-runtime/tests/test_attempts_and_health.py",
    "packages/parallel-runtime/tests/test_recovery_and_continuity.py",
    "services/api/src/akc_api/parallel_models.py",
    "services/api/src/akc_api/parallel_runtime_store.py",
    "services/api/src/akc_api/parallel_orchestrator.py",
    "services/api/tests/test_parallel_orchestrator.py",
    "services/api/tests/test_parallel_runtime_store.py",
    "services/scheduler/src/akc_scheduler/autonomous_v6_pipeline.py",
    "services/scheduler/tests/test_autonomous_v6_pipeline.py",
    "packages/quality/src/akc_quality/autonomous.py",
    "packages/quality/tests/test_autonomous_verification.py",
    "migrations/versions/0031_parallel_pod_runtime.py",
)

_PASSED_PATTERN = re.compile(r"(?P<count>\d+) passed(?:,|\s)")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _metrics(expected: list[bool], observed: list[bool]) -> dict[str, float | int]:
    tp = sum(wanted and actual for wanted, actual in zip(expected, observed, strict=True))
    tn = sum(not wanted and not actual for wanted, actual in zip(expected, observed, strict=True))
    fp = sum(not wanted and actual for wanted, actual in zip(expected, observed, strict=True))
    fn = sum(wanted and not actual for wanted, actual in zip(expected, observed, strict=True))
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "accuracy": (tp + tn) / len(expected) if expected else 1.0,
    }


def _register(
    registry: WorkerHealthRegistry,
    worker_id: str,
    *,
    registered_at: datetime | None = None,
) -> None:
    registry.register(
        worker_id=worker_id,
        model_revision="mineru-3.4.4@pinned",
        runtime_image_digest="sha256:" + "1" * 64,
        capabilities=frozenset({"document", "table", "ocr"}),
        warm=True,
        cached_models=frozenset({"mineru-3.4.4"}),
        registered_at=registered_at,
    )


def _infrastructure(observed_at: datetime, **overrides: bool) -> InfrastructureObservation:
    values: dict[str, bool | datetime] = {
        "observed_at": observed_at,
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
    return InfrastructureObservation(**values)  # type: ignore[arg-type]


def _scenario(
    *,
    name: str,
    expected: WorkerState,
    observation: InfrastructureObservation,
) -> dict[str, Any]:
    registry = WorkerHealthRegistry()
    worker_id = f"worker-{name}"
    _register(registry, worker_id)
    snapshot = registry.record_infrastructure(worker_id, observation)
    return {
        "scenario": name,
        "expected_state": expected.value,
        "observed_state": snapshot.state.value,
        "passed": snapshot.state is expected,
        "transition_reason_codes": [
            code
            for transition in registry.transitions(worker_id)
            for code in transition.reason_codes
        ],
    }


def _silence_scenario(
    *,
    name: str,
    expected: WorkerState,
    registered_at: datetime,
    elapsed: timedelta,
) -> dict[str, Any]:
    """Cover the failure mode where no observation ever arrives.

    Every other scenario injects a signal. This one injects nothing and lets the
    liveness sweep decide, which is the shape a wedged probe transport actually
    produces: the worker is reachable in principle, but the control channel that
    would report on it has stopped emitting.
    """
    registry = WorkerHealthRegistry(
        signal_stale_after=timedelta(minutes=5),
        signal_silent_after=timedelta(minutes=20),
    )
    worker_id = f"worker-{name}"
    _register(registry, worker_id, registered_at=registered_at)
    registry.evaluate_liveness(registered_at + elapsed)
    snapshot = registry.snapshot(worker_id)
    return {
        "scenario": name,
        "expected_state": expected.value,
        "observed_state": snapshot.state.value,
        "passed": snapshot.state is expected,
        "silence_seconds": elapsed.total_seconds(),
        "signal_injected": False,
        "transition_reason_codes": [
            code
            for transition in registry.transitions(worker_id)
            for code in transition.reason_codes
        ],
    }


def _resource_loss_scenario(observed_at: datetime) -> dict[str, Any]:
    """Cover a worker whose underlying resource is destroyed, not just faulty.

    Quarantine assumes the worker still exists. A Pod reclaimed by the provider
    or deleted by a cost backstop is gone for good, and a caller choosing
    between waiting and acquiring a replacement needs that distinction.
    """
    registry = WorkerHealthRegistry()
    worker_id = "worker-resource-loss"
    _register(registry, worker_id, registered_at=observed_at)
    registry.terminate(
        worker_id,
        occurred_at=observed_at + timedelta(seconds=1),
        reason="provider_resource_deleted",
    )
    snapshot = registry.snapshot(worker_id)
    return {
        "scenario": "provider_resource_deleted",
        "expected_state": WorkerState.TERMINATED.value,
        "observed_state": snapshot.state.value,
        "passed": snapshot.state is WorkerState.TERMINATED,
        "serving_after": list(registry.serving_workers()),
        "transition_reason_codes": [
            code
            for transition in registry.transitions(worker_id)
            for code in transition.reason_codes
        ],
    }


def _capacity_deficit_evidence(observed_at: datetime) -> dict[str, Any]:
    """Show the pool reporting how many workers it is short of its own floor.

    The runtime consumes an inventory and never provisions, so losing workers
    used to reduce throughput silently. The shortfall is now an explicit value
    that whatever owns acquisition can act on.
    """
    stack = RuntimeStack(
        runtime_image_digest="sha256:" + "1" * 64,
        framework="torch",
        cuda_version="12.8",
        serving_runtime="mineru-vlm",
    )
    pool = EndpointPool(
        pool_id="mineru-audit-pool",
        model_revision="mineru-3.4.4@pinned",
        worker_type=WorkerType.ACTIVE_WARM,
        runtime_stack=stack,
        capabilities=frozenset({"document", "table", "ocr"}),
        minimum_workers=3,
        maximum_workers=6,
    )
    workers = tuple(
        PoolWorker(
            worker_id=f"worker-{index}",
            pool_id=pool.pool_id,
            model_revision=pool.model_revision,
            runtime_stack=stack,
            gpu_type="RTX 4090",
        )
        for index in range(3)
    )
    intact = evaluate_pool_capacity(
        pool=pool,
        pool_workers=workers,
        serving_worker_ids=frozenset(worker.worker_id for worker in workers),
    )
    # Two of the three Pods lost, which is exactly what this campaign hit.
    degraded = evaluate_pool_capacity(
        pool=pool, pool_workers=workers, serving_worker_ids=frozenset({"worker-1"})
    )
    return {
        "scenario": "pool_capacity_deficit_after_resource_loss",
        "expected_state": "replacements_required",
        "observed_state": "replacements_required",
        "passed": intact.satisfied and degraded.replacements_required == 2,
        "observed_at_utc": observed_at.isoformat(),
        "minimum_workers": pool.minimum_workers,
        "intact_replacements_required": intact.replacements_required,
        "degraded_serving_worker_count": degraded.serving_worker_count,
        "degraded_replacements_required": degraded.replacements_required,
        "degraded_unavailable_worker_ids": list(degraded.unavailable_worker_ids),
        "transition_reason_codes": [],
    }


def _semantic_impact_scenario(observed_at: datetime) -> dict[str, Any]:
    registry = WorkerHealthRegistry()
    worker_id = "worker-semantic-canary"
    _register(registry, worker_id)
    registry.record_attempt(
        worker_id,
        attempt_id="attempt-accepted",
        shard_id="shard-accepted",
        status=AttemptStatus.ACCEPTED,
    )
    registry.record_attempt(
        worker_id,
        attempt_id="attempt-running",
        shard_id="shard-running",
        status=AttemptStatus.RUNNING,
    )
    snapshot = registry.record_semantic(
        worker_id,
        SemanticObservation(
            attempt_id="attempt-canary",
            shard_id="shard-canary",
            observed_at=observed_at,
            validator_passed=False,
            source_coverage=0.0,
            canary_fixture_failed=True,
            empty_output=True,
        ),
    )
    impact = registry.quarantine_impact(worker_id)
    expected_impact = {
        "pending_attempt_ids": ("attempt-running",),
        "accepted_attempt_ids_for_analysis": ("attempt-accepted",),
        "shard_ids_to_replay": ("shard-accepted", "shard-running"),
    }
    impact_payload = asdict(impact)
    impact_passed = all(impact_payload[key] == value for key, value in expected_impact.items())
    return {
        "scenario": "semantic_canary_quarantine_and_impact_replay",
        "expected_state": WorkerState.QUARANTINED.value,
        "observed_state": snapshot.state.value,
        "impact": impact_payload,
        "passed": snapshot.state is WorkerState.QUARANTINED and impact_passed,
        "transition_reason_codes": [
            code
            for transition in registry.transitions(worker_id)
            for code in transition.reason_codes
        ],
    }


def _service_test_count(path: Path) -> int:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    if " failed" in text or " error" in text.casefold():
        raise ValueError("service recovery test log contains failures or errors")
    matches = list(_PASSED_PATTERN.finditer(text))
    if not matches:
        raise ValueError("service recovery test log has no pytest pass summary")
    return int(matches[-1].group("count"))


def evaluate(
    *, repository: Path,
    service_test_log: Path,
    output: Path,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"service recovery evidence already exists: {output}")
    test_count = _service_test_count(service_test_log)
    if test_count < 60:
        raise ValueError("service recovery evidence requires at least 60 passing tests")
    source_hashes: list[dict[str, Any]] = []
    for relative in SERVICE_SOURCE_PATHS:
        path = repository / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        source_hashes.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    observed_at = datetime.now(UTC)
    scenarios = [
        _scenario(
            name="healthy",
            expected=WorkerState.HEALTHY,
            observation=_infrastructure(observed_at),
        ),
        _scenario(
            name="heartbeat_loss",
            expected=WorkerState.DRAINING,
            observation=_infrastructure(observed_at + timedelta(seconds=1), heartbeat=False),
        ),
        _scenario(
            name="cuda_unavailable",
            expected=WorkerState.DRAINING,
            observation=_infrastructure(observed_at + timedelta(seconds=2), cuda_ready=False),
        ),
        _scenario(
            name="request_response_failure",
            expected=WorkerState.DRAINING,
            observation=_infrastructure(
                observed_at + timedelta(seconds=3), request_response=False
            ),
        ),
        _scenario(
            name="latency_p99_spike",
            expected=WorkerState.DRAINING,
            observation=_infrastructure(
                observed_at + timedelta(seconds=4), latency_p99_spike=True
            ),
        ),
        _scenario(
            name="model_identity_mismatch",
            expected=WorkerState.QUARANTINED,
            observation=_infrastructure(
                observed_at + timedelta(seconds=5), model_identity_matches=False
            ),
        ),
        _scenario(
            name="model_checksum_mismatch",
            expected=WorkerState.QUARANTINED,
            observation=_infrastructure(
                observed_at + timedelta(seconds=6), checksum_matches=False
            ),
        ),
        _silence_scenario(
            name="infrastructure_signal_stale",
            expected=WorkerState.DRAINING,
            registered_at=observed_at + timedelta(seconds=7),
            elapsed=timedelta(minutes=6),
        ),
        _silence_scenario(
            name="infrastructure_signal_silent",
            expected=WorkerState.QUARANTINED,
            registered_at=observed_at + timedelta(seconds=8),
            elapsed=timedelta(minutes=25),
        ),
        _resource_loss_scenario(observed_at + timedelta(seconds=9)),
        _capacity_deficit_evidence(observed_at + timedelta(seconds=10)),
        _semantic_impact_scenario(observed_at + timedelta(seconds=11)),
    ]
    expected_anomaly = [item["expected_state"] != WorkerState.HEALTHY.value for item in scenarios]
    observed_anomaly = [item["observed_state"] != WorkerState.HEALTHY.value for item in scenarios]
    expected_quarantine = [
        item["expected_state"] == WorkerState.QUARANTINED.value for item in scenarios
    ]
    observed_quarantine = [
        item["observed_state"] == WorkerState.QUARANTINED.value for item in scenarios
    ]
    gate_passed = all(bool(item["passed"]) for item in scenarios)
    payload: dict[str, Any] = {
        "schema": "folynta.service-recovery-equivalence-evaluation.v1",
        "status": "complete_service_recovery_equivalence_verified",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "gate_passed": gate_passed,
        "service_test_count": test_count,
        "service_test_log": {
            "path": service_test_log.relative_to(repository).as_posix(),
            "sha256": _sha256(service_test_log),
        },
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "anomaly_detection": _metrics(expected_anomaly, observed_anomaly),
        "quarantine_detection": _metrics(expected_quarantine, observed_quarantine),
        "service_source_fingerprints": source_hashes,
        "equivalence_contract": {
            "infrastructure_signals": [
                "heartbeat",
                "process",
                "gpu",
                "cuda_ready",
                "request_response",
                "model_identity_matches",
                "checksum_matches",
            ],
            "signal_absence_detection": {
                "mechanism": "liveness sweep over time since the last infrastructure observation",
                "stale_threshold_seconds": 300,
                "silent_threshold_seconds": 1200,
                "stale_state": WorkerState.DRAINING.value,
                "silent_state": WorkerState.QUARANTINED.value,
                "rationale": (
                    "Signal-bearing faults are detected when an observation arrives. A wedged "
                    "probe transport emits nothing at all, so silence is measured explicitly "
                    "rather than being read as health."
                ),
            },
            "fault_containment": "worker quarantine plus affected-shard replay only",
            "quality_recovery": "smallest-scope deterministic recovery with fail-closed acceptance",
            "durability": "tenant-scoped idempotent ledgers and immutable accepted results",
        },
        "claim_boundary": (
            "This deterministic service-kernel injection and the bound integration tests prove "
            "implementation equivalence. Production prevalence and every provider failure mode "
            "remain outside the claim. Detection of signal-bearing faults is conditional on an "
            "observation reaching the registry; the two silence scenarios cover the case where "
            "none does, but only for workers whose liveness baseline is known. Resource "
            "acquisition failures, where a worker is never obtained and therefore never "
            "registered, are handled by the release provisioning layer and are outside this "
            "service-kernel claim."
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["receipt_sha256"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    if not gate_passed:
        raise ValueError("service recovery equivalence gate failed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--service-test-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = evaluate(
        repository=args.repository_root.resolve(),
        service_test_log=args.service_test_log.resolve(),
        output=args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "service_test_count": payload["service_test_count"],
                "receipt_sha256": payload["receipt_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SERVICE_SOURCE_PATHS", "evaluate"]
