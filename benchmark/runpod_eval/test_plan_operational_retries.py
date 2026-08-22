from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plan_operational_retries import SUITES, WorkerResult, stage_operational_retries


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_failed_cases_are_staged_only_on_the_frozen_different_worker(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    results = tmp_path / "results"
    plan_suites = []
    for suite_index, suite in enumerate(SUITES):
        parent_inputs = []
        shards = []
        for worker in range(4):
            case_id = f"{suite}-{worker}"
            content = f"{suite}-{worker}".encode()
            digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
            item = {
                "case_id": case_id,
                "input_relative_path": f"inputs/{case_id}.png",
                "input_sha256": digest,
            }
            parent_inputs.append(item)
            source = (
                staged
                / f"worker-{worker:02d}"
                / "suites"
                / suite
                / "inputs"
                / f"{case_id}.png"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            shards.append(
                {
                    "worker_index": worker,
                    "inputs": [{"case_id": case_id, "retry_worker_index": (worker + 1) % 4}],
                }
            )
            failed = (suite_index == 0 and worker == 0) or (suite_index == 1 and worker == 1)
            _write(
                results / f"worker-{worker:02d}" / suite / "run-summary.json",
                {
                    "runs": [
                        {
                            "repeat_index": 1,
                            "cases": [
                                {
                                    "case_id": case_id,
                                    "status": "failed" if failed else "completed",
                                }
                            ],
                        }
                    ]
                },
            )
        parent = {
            "benchmark_id": suite,
            "dataset_revision": "revision",
            "source_count": 4,
            "content_sha256": "sha256:" + "a" * 64,
            "inputs": parent_inputs,
        }
        for worker in range(4):
            _write(
                staged / f"worker-{worker:02d}" / "suites" / suite / "parent-input-manifest.json",
                parent,
            )
        plan_suites.append({"benchmark_id": suite, "shards": shards})

    plan_path = tmp_path / "plan.json"
    _write(
        plan_path,
        {
            "worker_count": 4,
            "total_input_count": 5132,
            "plan_sha256": "sha256:" + "b" * 64,
            "suites": plan_suites,
        },
    )
    output = tmp_path / "retry"
    receipt = stage_operational_retries(
        worker_results=tuple(
            WorkerResult(worker, results / f"worker-{worker:02d}") for worker in range(4)
        ),
        staged_root=staged,
        shard_plan=plan_path,
        output_root=output,
    )

    assert receipt["failed_input_count"] == 2
    assert receipt["staged_input_count"] == 2
    assert receipt["different_worker_only"] is True
    parse_retry = output / "worker-01" / "suites" / "parsebench"
    omni_retry = output / "worker-02" / "suites" / "omnidocbench"
    assert (parse_retry / "inputs" / "parsebench-0.png").read_bytes() == b"parsebench-0"
    assert (omni_retry / "inputs" / "omnidocbench-1.png").read_bytes() == b"omnidocbench-1"
    assert not (output / "worker-00").exists()


def test_quarantined_frozen_target_is_deterministically_rerouted(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    results = tmp_path / "results"
    plan_suites = []
    for suite in SUITES:
        parent_inputs = []
        shards = []
        for worker in range(4):
            case_id = f"{suite}-{worker}"
            content = case_id.encode()
            digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
            item = {
                "case_id": case_id,
                "input_relative_path": f"inputs/{case_id}.png",
                "input_sha256": digest,
            }
            parent_inputs.append(item)
            source = (
                staged
                / f"worker-{worker:02d}"
                / "suites"
                / suite
                / "inputs"
                / f"{case_id}.png"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            shards.append(
                {
                    "worker_index": worker,
                    "inputs": [{"case_id": case_id, "retry_worker_index": 1}],
                }
                if worker != 1
                else {
                    "worker_index": worker,
                    "inputs": [{"case_id": case_id, "retry_worker_index": 0}],
                }
            )
            _write(
                results / f"worker-{worker:02d}" / suite / "run-summary.json",
                {
                    "runs": [
                        {
                            "repeat_index": 1,
                            "cases": [
                                {
                                    "case_id": case_id,
                                    "status": "failed" if worker == 0 else "completed",
                                }
                            ],
                        }
                    ]
                },
            )
        parent = {
            "benchmark_id": suite,
            "dataset_revision": "revision",
            "source_count": 4,
            "content_sha256": "sha256:" + "a" * 64,
            "inputs": parent_inputs,
        }
        for worker in range(4):
            _write(
                staged / f"worker-{worker:02d}" / "suites" / suite / "parent-input-manifest.json",
                parent,
            )
        plan_suites.append({"benchmark_id": suite, "shards": shards})

    plan_path = tmp_path / "plan.json"
    _write(
        plan_path,
        {
            "worker_count": 4,
            "total_input_count": 5132,
            "plan_sha256": "sha256:" + "b" * 64,
            "suites": plan_suites,
        },
    )
    health_path = tmp_path / "health.json"
    _write(
        health_path,
        {
            "schema": "folynta.public-core-operational-worker-health.v1",
            "eligible_retry_workers": [0, 2, 3],
            "quarantined_worker_indices": [1],
            "receipt_sha256": "sha256:" + "c" * 64,
        },
    )

    receipt = stage_operational_retries(
        worker_results=tuple(
            WorkerResult(worker, results / f"worker-{worker:02d}") for worker in range(4)
        ),
        staged_root=staged,
        shard_plan=plan_path,
        output_root=tmp_path / "retry",
        worker_health=health_path,
    )

    assert receipt["failed_input_count"] == 3
    assert receipt["quarantine_rerouted_input_count"] == 3
    assert receipt["quarantined_worker_indices"] == [1]
    assert all(item["retry_worker_index"] in {2, 3} for item in receipt["failures"])
    assert all(item["rerouted_due_to_quarantine"] for item in receipt["failures"])


def test_expansion_workers_receive_deterministically_balanced_retries(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    results = tmp_path / "results"
    plan_suites = []
    expected_failures = 0
    for suite in SUITES:
        parent_inputs = []
        shards = []
        for worker in range(4):
            shard_inputs = []
            cases = []
            for ordinal in range(30):
                case_id = f"{suite}-{worker}-{ordinal:02d}"
                content = case_id.encode()
                item = {
                    "case_id": case_id,
                    "input_relative_path": f"inputs/{case_id}.png",
                    "input_sha256": f"sha256:{hashlib.sha256(content).hexdigest()}",
                }
                parent_inputs.append(item)
                source = (
                    staged
                    / f"worker-{worker:02d}"
                    / "suites"
                    / suite
                    / "inputs"
                    / f"{case_id}.png"
                )
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
                shard_inputs.append(
                    {"case_id": case_id, "retry_worker_index": (worker + 1) % 4}
                )
                cases.append({"case_id": case_id, "status": "failed"})
                expected_failures += 1
            shards.append({"worker_index": worker, "inputs": shard_inputs})
            _write(
                results / f"worker-{worker:02d}" / suite / "run-summary.json",
                {"runs": [{"repeat_index": 1, "cases": cases}]},
            )
        parent = {
            "benchmark_id": suite,
            "dataset_revision": "revision",
            "source_count": len(parent_inputs),
            "content_sha256": "sha256:" + "a" * 64,
            "inputs": parent_inputs,
        }
        for worker in range(4):
            _write(
                staged
                / f"worker-{worker:02d}"
                / "suites"
                / suite
                / "parent-input-manifest.json",
                parent,
            )
        plan_suites.append({"benchmark_id": suite, "shards": shards})

    plan_path = tmp_path / "plan.json"
    _write(
        plan_path,
        {
            "worker_count": 4,
            "total_input_count": 5132,
            "plan_sha256": "sha256:" + "b" * 64,
            "suites": plan_suites,
        },
    )
    health_path = tmp_path / "health.json"
    _write(
        health_path,
        {
            "schema": "folynta.public-core-operational-worker-health.v1",
            "eligible_retry_workers": [0, 2, 3],
            "quarantined_worker_indices": [1],
            "receipt_sha256": "sha256:" + "c" * 64,
        },
    )
    receipt = stage_operational_retries(
        worker_results=tuple(
            WorkerResult(worker, results / f"worker-{worker:02d}")
            for worker in range(4)
        ),
        staged_root=staged,
        shard_plan=plan_path,
        output_root=tmp_path / "retry",
        worker_health=health_path,
        additional_retry_worker_indices=(4, 5, 6),
    )

    routed = {
        int(worker["retry_worker_index"]): int(worker["input_count"])
        for worker in receipt["workers"]
    }
    assert receipt["failed_input_count"] == expected_failures
    assert receipt["routing_policy"] == "expanded-retry-pool-v1"
    assert receipt["additional_retry_worker_indices"] == [4, 5, 6]
    assert receipt["additional_worker_routed_input_count"] > 0
    assert set(routed) == {0, 2, 3, 4, 5, 6}
    assert max(routed.values()) - min(routed.values()) < expected_failures * 0.2
    assert all(
        item["retry_worker_index"] != item["primary_worker_index"]
        for item in receipt["failures"]
    )


def test_completed_primary_subset_can_be_prefetched_to_explicit_expansion_routes(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "staged"
    results = tmp_path / "results"
    plan_suites = []
    for suite in SUITES:
        parent_inputs = []
        shards = []
        for worker in range(4):
            case_id = f"{suite}-{worker}"
            content = case_id.encode()
            item = {
                "case_id": case_id,
                "input_relative_path": f"inputs/{case_id}.png",
                "input_sha256": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
            parent_inputs.append(item)
            source = (
                staged
                / f"worker-{worker:02d}"
                / "suites"
                / suite
                / "inputs"
                / f"{case_id}.png"
            )
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            shards.append(
                {
                    "worker_index": worker,
                    "inputs": [
                        {"case_id": case_id, "retry_worker_index": (worker + 1) % 4}
                    ],
                }
            )
            if worker in {1, 2}:
                _write(
                    results / f"worker-{worker:02d}" / suite / "run-summary.json",
                    {
                        "runs": [
                            {
                                "repeat_index": 1,
                                "cases": [{"case_id": case_id, "status": "failed"}],
                            }
                        ]
                    },
                )
        parent = {
            "benchmark_id": suite,
            "dataset_revision": "revision",
            "source_count": 4,
            "content_sha256": "sha256:" + "a" * 64,
            "inputs": parent_inputs,
        }
        _write(
            staged / "worker-00" / "suites" / suite / "parent-input-manifest.json",
            parent,
        )
        plan_suites.append({"benchmark_id": suite, "shards": shards})

    plan_path = tmp_path / "plan.json"
    _write(
        plan_path,
        {
            "worker_count": 4,
            "total_input_count": 5132,
            "plan_sha256": "sha256:" + "b" * 64,
            "suites": plan_suites,
        },
    )
    receipt = stage_operational_retries(
        worker_results=tuple(
            WorkerResult(worker, results / f"worker-{worker:02d}")
            for worker in (1, 2)
        ),
        staged_root=staged,
        shard_plan=plan_path,
        output_root=tmp_path / "prefetch",
        additional_retry_worker_indices=(4, 5, 6),
        partial_primary_worker_indices=(1, 2),
        explicit_retry_routes={1: (4, 5, 6), 2: (4, 5, 6)},
    )

    assert receipt["primary_worker_scope"] == [1, 2]
    assert receipt["complete_primary_scope"] is False
    assert receipt["routing_policy"] == "explicit-primary-route-map-v1"
    assert receipt["failed_input_count"] == 6
    assert {item["retry_worker_index"] for item in receipt["failures"]} <= {4, 5, 6}
    assert all(
        item["primary_worker_index"] in {1, 2} for item in receipt["failures"]
    )
    manifests = sorted((tmp_path / "prefetch").glob("worker-*/suites/*/shard-input-manifest.json"))
    assert manifests
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert 0 <= manifest["shard_index"] < manifest["shard_count"]
