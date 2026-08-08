import hashlib
import json

import pytest
from pathlib import Path

from stage_selective_recovery import stage_selective_recovery


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_model_specific_recovery_stages_only_exact_official_failure_routes(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "staged"
    cases = [
        ("parsebench", "parsebench-text", 0, 1, "deepseek-ocr-2"),
        ("olmocr-bench", "olmocr-formula", 2, 3, "paddleocr-vl-1.6"),
    ]
    plan_suites = []
    for suite in ("parsebench", "omnidocbench", "olmocr-bench"):
        parent_inputs = []
        shards = []
        for worker in range(4):
            planned = []
            for case_suite, case_id, primary, retry, _model in cases:
                if case_suite != suite or primary != worker:
                    continue
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
                planned.append({"case_id": case_id, "retry_worker_index": retry})
            shards.append({"worker_index": worker, "inputs": planned})
        parent = {
            "benchmark_id": suite,
            "dataset_revision": "revision",
            "source_count": max(1, len(parent_inputs)),
            "content_sha256": "sha256:" + "a" * 64,
            "inputs": parent_inputs,
        }
        _write(
            staged / "worker-00" / "suites" / suite / "parent-input-manifest.json",
            parent,
        )
        plan_suites.append({"benchmark_id": suite, "shards": shards})
    plan = tmp_path / "plan.json"
    _write(
        plan,
        {
            "worker_count": 4,
            "total_input_count": 5132,
            "plan_sha256": "sha256:" + "b" * 64,
            "suites": plan_suites,
        },
    )
    failures = tmp_path / "failures.json"
    _write(
        failures,
        {
            "routes": [
                {
                    "benchmark_id": suite,
                    "case_id": case_id,
                    "request_recovery": True,
                    "candidate_models": [model],
                    "failure_codes": ["B01" if "text" in case_id else "F01"],
                }
                for suite, case_id, _primary, _retry, model in cases
            ]
        },
    )

    deep_output = tmp_path / "deep"
    deep = stage_selective_recovery(
        failure_records=failures,
        staged_root=staged,
        shard_plan=plan,
        recovery_model="deepseek-ocr-2",
        output_root=deep_output,
    )
    assert deep["input_count"] == 1
    assert deep["different_worker_only"] is True
    assert (
        deep_output
        / "worker-01"
        / "suites"
        / "parsebench"
        / "inputs"
        / "parsebench-text.png"
    ).is_file()

    mineru = stage_selective_recovery(
        failure_records=failures,
        staged_root=staged,
        shard_plan=plan,
        recovery_model="mineru-3.4.4-vlm-quality-retry",
        output_root=tmp_path / "mineru",
    )
    assert mineru["input_count"] == 2

    health = tmp_path / "health.json"
    _write(
        health,
        {
            "schema": "folynta.public-core-operational-worker-health.v1",
            "eligible_retry_workers": [0, 2, 3],
            "quarantined_worker_indices": [1],
            "receipt_sha256": "sha256:" + "d" * 64,
        },
    )
    healthy_mineru = stage_selective_recovery(
        failure_records=failures,
        staged_root=staged,
        shard_plan=plan,
        recovery_model="mineru-3.4.4-vlm-quality-retry",
        output_root=tmp_path / "healthy-mineru",
        worker_health=health,
    )
    assert healthy_mineru["quarantined_worker_indices"] == [1]
    assert healthy_mineru["quarantine_rerouted_input_count"] == 1
    assert all(
        route["recovery_worker_index"] != 1 for route in healthy_mineru["routes"]
    )

    expanded_mineru = stage_selective_recovery(
        failure_records=failures,
        staged_root=staged,
        shard_plan=plan,
        recovery_model="mineru-3.4.4-vlm-quality-retry",
        output_root=tmp_path / "expanded-mineru",
        worker_health=health,
        additional_recovery_worker_indices=(4, 5, 6),
    )
    assert expanded_mineru["routing_policy"] == "expanded-quality-pool-v1"
    assert expanded_mineru["additional_recovery_worker_indices"] == [4, 5, 6]
    assert expanded_mineru["eligible_recovery_workers"] == [0, 2, 3, 4, 5, 6]
    assert all(
        route["recovery_worker_index"] != route["primary_worker_index"]
        for route in expanded_mineru["routes"]
    )
    expanded_manifests = sorted(
        (tmp_path / "expanded-mineru").glob(
            "worker-*/suites/*/shard-input-manifest.json"
        )
    )
    assert expanded_manifests
    for manifest_path in expanded_manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert 0 <= manifest["shard_index"] < manifest["shard_count"]


def _build_quality_fixture(tmp_path: Path) -> dict:
    """Two cases whose frozen primaries are workers 0 and 2."""
    staged = tmp_path / "staged"
    cases = [
        ("parsebench", "parsebench-a", 0, 1),
        ("olmocr-bench", "olmocr-b", 2, 3),
    ]
    plan_suites = []
    for suite in ("parsebench", "omnidocbench", "olmocr-bench"):
        parent_inputs, shards = [], []
        for worker in range(4):
            planned = []
            for case_suite, case_id, primary, retry in cases:
                if case_suite != suite or primary != worker:
                    continue
                content = case_id.encode()
                parent_inputs.append(
                    {
                        "case_id": case_id,
                        "input_relative_path": f"inputs/{case_id}.png",
                        "input_sha256": f"sha256:{hashlib.sha256(content).hexdigest()}",
                    }
                )
                source = (
                    staged / f"worker-{worker:02d}" / "suites" / suite
                    / "inputs" / f"{case_id}.png"
                )
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
                planned.append({"case_id": case_id, "retry_worker_index": retry})
            shards.append({"worker_index": worker, "inputs": planned})
        _write(
            staged / "worker-00" / "suites" / suite / "parent-input-manifest.json",
            {
                "benchmark_id": suite,
                "dataset_revision": "revision",
                "source_count": max(1, len(parent_inputs)),
                "content_sha256": "sha256:" + "a" * 64,
                "inputs": parent_inputs,
            },
        )
        plan_suites.append({"benchmark_id": suite, "shards": shards})
    plan = tmp_path / "plan.json"
    _write(plan, {
        "worker_count": 4, "total_input_count": 5132,
        "plan_sha256": "sha256:" + "b" * 64, "suites": plan_suites,
    })
    failures = tmp_path / "failures.json"
    _write(failures, {"routes": [
        {"benchmark_id": suite, "case_id": case_id, "request_recovery": True,
         "candidate_models": ["paddleocr-vl-1.6"], "failure_codes": ["B01"]}
        for suite, case_id, _p, _r in cases
    ]})
    health = tmp_path / "health.json"
    _write(health, {
        "schema": "folynta.public-core-operational-worker-health.v1",
        "eligible_retry_workers": [0, 3],
        "quarantined_worker_indices": [1, 2],
        "receipt_sha256": "sha256:" + "c" * 64,
    })
    return {"staged": staged, "plan": plan, "failures": failures, "health": health}


def test_staging_never_routes_to_a_worker_whose_pod_is_gone(tmp_path: Path) -> None:
    # Worker health says which workers were fit to retry. It cannot say which
    # Pods still exist: a primary Pod is collected and deleted once its shard is
    # merged, so trusting health alone stages work for Pods that are long gone.
    f = _build_quality_fixture(tmp_path)
    receipt = stage_selective_recovery(
        failure_records=f["failures"], staged_root=f["staged"], shard_plan=f["plan"],
        recovery_model="mineru-3.4.4-vlm-quality-retry",
        output_root=tmp_path / "restricted", worker_health=f["health"],
        additional_recovery_worker_indices=(4, 5, 6),
        available_recovery_worker_indices=(4, 5, 6),
    )

    assert set(receipt["eligible_recovery_workers"]) == {4, 5, 6}
    # Workers 0 and 3 were retry-eligible by health but their Pods are absent.
    assert receipt["recovery_workers_excluded_as_absent"] == [0, 3]
    assert all(int(r["recovery_worker_index"]) in {4, 5, 6} for r in receipt["routes"])


def test_staging_refuses_to_run_on_a_single_surviving_worker(tmp_path: Path) -> None:
    f = _build_quality_fixture(tmp_path)
    with pytest.raises(ValueError, match="fewer than two recovery workers remain"):
        stage_selective_recovery(
            failure_records=f["failures"], staged_root=f["staged"], shard_plan=f["plan"],
            recovery_model="mineru-3.4.4-vlm-quality-retry",
            output_root=tmp_path / "single", worker_health=f["health"],
            additional_recovery_worker_indices=(4,),
            available_recovery_worker_indices=(4,),
        )
