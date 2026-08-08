#!/usr/bin/env python3
"""Stage failed public-core cases for mandatory different-worker retry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
PRIMARY_WORKER_INDICES = frozenset(range(4))
MAX_RETRY_WORKER_INDEX = 99


@dataclass(frozen=True, slots=True)
class WorkerResult:
    worker_index: int
    result_root: Path


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _plan_lookup(plan: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for suite in plan["suites"]:
        benchmark_id = str(suite["benchmark_id"])
        for shard in suite["shards"]:
            primary = int(shard["worker_index"])
            for item in shard["inputs"]:
                key = (benchmark_id, str(item["case_id"]))
                if key in lookup:
                    raise ValueError(f"duplicate shard-plan case: {key}")
                retry = int(item["retry_worker_index"])
                if retry == primary or retry not in range(4):
                    raise ValueError(f"invalid different-worker retry route: {key}")
                lookup[key] = {**item, "primary_worker_index": primary}
    return lookup


def stage_operational_retries(
    *,
    worker_results: tuple[WorkerResult, ...],
    staged_root: Path,
    shard_plan: Path,
    output_root: Path,
    worker_health: Path | None = None,
    additional_retry_worker_indices: tuple[int, ...] = (),
    partial_primary_worker_indices: tuple[int, ...] = (),
    explicit_retry_routes: dict[int, tuple[int, ...]] | None = None,
) -> dict[str, Any]:
    workers = sorted(worker_results, key=lambda value: value.worker_index)
    selected_primaries = (
        tuple(sorted(partial_primary_worker_indices))
        if partial_primary_worker_indices
        else tuple(range(4))
    )
    if (
        len(selected_primaries) != len(set(selected_primaries))
        or any(index not in PRIMARY_WORKER_INDICES for index in selected_primaries)
        or [worker.worker_index for worker in workers] != list(selected_primaries)
    ):
        raise ValueError(
            "worker results must exactly match the selected frozen primary indices"
        )
    if output_root.exists():
        raise FileExistsError(f"retry staging already exists: {output_root}")
    plan = _load(shard_plan)
    if int(plan.get("worker_count", -1)) != 4 or int(plan.get("total_input_count", -1)) != 5132:
        raise ValueError("retry planner requires the frozen 4-worker/5,132-case plan")
    planned = _plan_lookup(plan)
    additional_workers = tuple(sorted(additional_retry_worker_indices))
    if (
        len(additional_workers) != len(set(additional_workers))
        or any(
            worker in PRIMARY_WORKER_INDICES
            or not 0 <= worker <= MAX_RETRY_WORKER_INDEX
            for worker in additional_workers
        )
    ):
        raise ValueError("additional retry worker indices must be unique values from 4 to 99")
    eligible_primary_workers = set(PRIMARY_WORKER_INDICES)
    quarantined_workers: list[int] = []
    worker_health_sha256: str | None = None
    if worker_health is not None:
        health = _load(worker_health)
        if health.get("schema") != "folynta.public-core-operational-worker-health.v1":
            raise ValueError("unsupported operational worker health receipt")
        eligible_primary_workers = {
            int(value) for value in health.get("eligible_retry_workers", [])
        }
        quarantined_workers = sorted(
            int(value) for value in health.get("quarantined_worker_indices", [])
        )
        if eligible_primary_workers | set(quarantined_workers) != PRIMARY_WORKER_INDICES:
            raise ValueError("worker health receipt does not partition all workers")
        if eligible_primary_workers & set(quarantined_workers):
            raise ValueError("worker health receipt has overlapping states")
        if len(eligible_primary_workers) + len(additional_workers) < 2:
            raise ValueError("fewer than two retry-eligible workers; replacements required")
        worker_health_sha256 = str(health.get("receipt_sha256"))
    eligible_retry_workers = eligible_primary_workers | set(additional_workers)
    normalized_routes: dict[int, tuple[int, ...]] = {}
    if explicit_retry_routes is not None:
        if set(explicit_retry_routes) != set(selected_primaries):
            raise ValueError("explicit retry routes must cover every selected primary")
        for primary, values in explicit_retry_routes.items():
            targets = tuple(sorted(values))
            if (
                not targets
                or len(targets) != len(set(targets))
                or primary in targets
                or any(target not in eligible_retry_workers for target in targets)
            ):
                raise ValueError("explicit retry route contains an unavailable target")
            normalized_routes[primary] = targets
        routed_workers = {
            target for targets in normalized_routes.values() for target in targets
        }
    else:
        routed_workers = set(eligible_retry_workers)

    failures: list[dict[str, Any]] = []
    for worker in workers:
        for suite in SUITES:
            summary_path = worker.result_root / suite / "run-summary.json"
            summary = _load(summary_path)
            runs = summary.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError(f"worker summary must contain baseline repeat 1: {summary_path}")
            for case in runs[0].get("cases", []):
                case_id = str(case["case_id"])
                route = planned.get((suite, case_id))
                if route is None or int(route["primary_worker_index"]) != worker.worker_index:
                    raise ValueError(
                        "runtime case is not bound to its primary worker: "
                        f"{suite}/{case_id}"
                    )
                if str(case.get("status")) == "failed":
                    frozen_retry = int(route["retry_worker_index"])
                    retry_worker = frozen_retry
                    rerouted_due_to_quarantine = False
                    rerouted_due_to_capacity_expansion = False
                    candidates = sorted(
                        normalized_routes.get(
                            worker.worker_index,
                            tuple(eligible_retry_workers - {worker.worker_index}),
                        )
                    )
                    if not candidates:
                        raise ValueError(
                            "no healthy different-worker retry target for "
                            f"{suite}/{case_id}"
                        )
                    if normalized_routes:
                        routing_identity = ",".join(str(value) for value in candidates)
                        digest = hashlib.sha256(
                            (
                                f"{suite}:{case_id}:explicit-primary-route-map-v1:"
                                f"{routing_identity}"
                            ).encode()
                        ).digest()
                        retry_worker = candidates[
                            int.from_bytes(digest[:8], "big") % len(candidates)
                        ]
                        rerouted_due_to_quarantine = (
                            frozen_retry not in eligible_primary_workers
                        )
                        rerouted_due_to_capacity_expansion = retry_worker != frozen_retry
                    elif additional_workers:
                        routing_identity = ",".join(str(value) for value in candidates)
                        digest = hashlib.sha256(
                            (
                                f"{suite}:{case_id}:expanded-retry-pool-v1:"
                                f"{routing_identity}"
                            ).encode()
                        ).digest()
                        retry_worker = candidates[
                            int.from_bytes(digest[:8], "big") % len(candidates)
                        ]
                        rerouted_due_to_quarantine = (
                            frozen_retry not in eligible_primary_workers
                        )
                        rerouted_due_to_capacity_expansion = retry_worker != frozen_retry
                    elif retry_worker not in eligible_retry_workers:
                        digest = hashlib.sha256(
                            f"{suite}:{case_id}:quarantine-reroute-v1".encode()
                        ).digest()
                        retry_worker = candidates[
                            int.from_bytes(digest[:8], "big") % len(candidates)
                        ]
                        rerouted_due_to_quarantine = True
                    failures.append(
                        {
                            "benchmark_id": suite,
                            "case_id": case_id,
                            "primary_worker_index": worker.worker_index,
                            "frozen_retry_worker_index": frozen_retry,
                            "retry_worker_index": retry_worker,
                            "rerouted_due_to_quarantine": rerouted_due_to_quarantine,
                            "rerouted_due_to_capacity_expansion": (
                                rerouted_due_to_capacity_expansion
                            ),
                            "capacity_expansion_routing_applied": bool(
                                additional_workers
                            ),
                            "primary_run_summary": str(summary_path),
                        }
                    )
                elif str(case.get("status")) != "completed":
                    raise ValueError(f"unsupported runtime status: {suite}/{case_id}")

    output_root.mkdir(parents=True)
    staged = 0
    worker_payloads: list[dict[str, Any]] = []
    for retry_shard_index, retry_worker in enumerate(sorted(routed_workers)):
        worker_root = output_root / f"worker-{retry_worker:02d}"
        worker_suites: list[dict[str, Any]] = []
        for suite in SUITES:
            selected = sorted(
                (
                    item
                    for item in failures
                    if item["benchmark_id"] == suite
                    and item["retry_worker_index"] == retry_worker
                ),
                key=lambda item: str(item["case_id"]),
            )
            if not selected:
                continue
            parent_path = (
                staged_root
                / "worker-00"
                / "suites"
                / suite
                / "parent-input-manifest.json"
            )
            parent = _load(parent_path)
            parent_by_case = {str(item["case_id"]): item for item in parent["inputs"]}
            suite_root = worker_root / "suites" / suite
            input_root = suite_root / "inputs"
            input_root.mkdir(parents=True)
            shutil.copy2(parent_path, suite_root / "parent-input-manifest.json")
            manifest_inputs: list[dict[str, Any]] = []
            primary_workers: set[int] = set()
            for retry in selected:
                case_id = str(retry["case_id"])
                parent_item = parent_by_case[case_id]
                primary = int(retry["primary_worker_index"])
                primary_workers.add(primary)
                filename = Path(str(parent_item["input_relative_path"])).name
                source = (
                    staged_root
                    / f"worker-{primary:02d}"
                    / "suites"
                    / suite
                    / "inputs"
                    / filename
                )
                target = input_root / filename
                if not source.is_file():
                    raise FileNotFoundError(source)
                os.link(source, target)
                item = dict(parent_item)
                item["input_relative_path"] = f"inputs/{filename}"
                manifest_inputs.append(item)
                staged += 1
            manifest: dict[str, Any] = {
                "schema": "folynta.public-core-inference-shard.v1",
                "benchmark_id": suite,
                "dataset_revision": parent["dataset_revision"],
                "ground_truth_mounted": False,
                "source_count": parent["source_count"],
                "input_count": len(manifest_inputs),
                "complete_source_coverage": False,
                "complete_input_coverage": True,
                "parent_input_manifest_sha256": parent["content_sha256"],
                "campaign_plan_sha256": plan["plan_sha256"],
                "shard_manifest_sha256": _canonical_hash(
                    {
                        "benchmark_id": suite,
                        "retry_worker_index": retry_worker,
                        "case_ids": [item["case_id"] for item in manifest_inputs],
                    }
                ),
                "shard_index": retry_shard_index,
                "shard_count": len(routed_workers),
                "inputs": manifest_inputs,
            }
            manifest["content_sha256"] = _canonical_hash(manifest)
            manifest_path = suite_root / "shard-input-manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            worker_suites.append(
                {
                    "benchmark_id": suite,
                    "input_count": len(manifest_inputs),
                    "primary_worker_indices": sorted(primary_workers),
                    "manifest_sha256": manifest["content_sha256"],
                }
            )
        if worker_suites:
            worker_payloads.append(
                {
                    "retry_worker_index": retry_worker,
                    "input_count": sum(int(item["input_count"]) for item in worker_suites),
                    "suites": worker_suites,
                }
            )

    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-operational-retry-plan.v1",
        "campaign_plan_sha256": plan["plan_sha256"],
        "failed_input_count": len(failures),
        "staged_input_count": staged,
        "different_worker_only": all(
            item["primary_worker_index"] != item["retry_worker_index"] for item in failures
        ),
        "eligible_retry_workers": sorted(routed_workers),
        "available_retry_workers": sorted(eligible_retry_workers),
        "eligible_primary_retry_workers": sorted(eligible_primary_workers),
        "additional_retry_worker_indices": list(additional_workers),
        "routing_policy": (
            "explicit-primary-route-map-v1"
            if normalized_routes
            else (
                "expanded-retry-pool-v1"
                if additional_workers
                else "frozen-or-quarantine-v1"
            )
        ),
        "primary_worker_scope": list(selected_primaries),
        "complete_primary_scope": selected_primaries == tuple(range(4)),
        "explicit_retry_routes": {
            str(primary): list(targets)
            for primary, targets in sorted(normalized_routes.items())
        },
        "quarantined_worker_indices": quarantined_workers,
        "quarantine_rerouted_input_count": sum(
            bool(item["rerouted_due_to_quarantine"]) for item in failures
        ),
        "capacity_expansion_rerouted_input_count": sum(
            bool(item["rerouted_due_to_capacity_expansion"]) for item in failures
        ),
        "additional_worker_routed_input_count": sum(
            int(item["retry_worker_index"]) in set(additional_workers) for item in failures
        ),
        "worker_health_receipt_sha256": worker_health_sha256,
        "failures": failures,
        "workers": worker_payloads,
    }
    if staged != len(failures):
        raise ValueError("retry staging does not exactly cover runtime failures")
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    (output_root / "retry-plan-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def _worker_result(value: str) -> WorkerResult:
    try:
        index, path = value.split("=", 1)
        return WorkerResult(int(index), Path(path))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("worker result must be INDEX=PATH") from exc


def _retry_route(value: str) -> tuple[int, tuple[int, ...]]:
    try:
        primary_raw, targets_raw = value.split("=", 1)
        targets = tuple(int(item) for item in targets_raw.split(",") if item)
        if not targets:
            raise ValueError
        return int(primary_raw), targets
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "retry route must be PRIMARY=TARGET[,TARGET...]"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-result", action="append", type=_worker_result, required=True)
    parser.add_argument("--staged-root", type=Path, required=True)
    parser.add_argument("--shard-plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--worker-health", type=Path)
    parser.add_argument(
        "--additional-retry-worker-index", action="append", type=int, default=[]
    )
    parser.add_argument(
        "--partial-primary-worker-index", action="append", type=int, default=[]
    )
    parser.add_argument("--retry-route", action="append", type=_retry_route, default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    explicit_routes: dict[int, tuple[int, ...]] | None = None
    if args.retry_route:
        explicit_routes = {}
        for primary, targets in args.retry_route:
            if primary in explicit_routes:
                raise ValueError(f"duplicate explicit retry route for primary {primary}")
            explicit_routes[primary] = targets
    receipt = stage_operational_retries(
        worker_results=tuple(args.worker_result),
        staged_root=args.staged_root.resolve(),
        shard_plan=args.shard_plan.resolve(),
        output_root=args.output_root.resolve(),
        worker_health=(args.worker_health.resolve() if args.worker_health else None),
        additional_retry_worker_indices=tuple(args.additional_retry_worker_index),
        partial_primary_worker_indices=tuple(args.partial_primary_worker_index),
        explicit_retry_routes=explicit_routes,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WorkerResult", "stage_operational_retries"]
