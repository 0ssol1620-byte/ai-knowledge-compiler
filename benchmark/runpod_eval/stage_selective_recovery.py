#!/usr/bin/env python3
"""Stage exact official-failure cases for same-model or alternate-model recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

RECOVERY_MODELS = (
    "mineru-3.4.4-vlm-quality-retry",
    "paddleocr-vl-1.6",
    "deepseek-ocr-2",
)
SUITES = ("parsebench", "omnidocbench", "olmocr-bench")
PRIMARY_WORKER_INDICES = frozenset(range(4))
MAX_RECOVERY_WORKER_INDEX = 99


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _routes_for_model(payload: dict[str, Any], model: str) -> list[dict[str, Any]]:
    routes = []
    for route in payload.get("routes", []):
        if route.get("request_recovery") is not True:
            continue
        if model == "mineru-3.4.4-vlm-quality-retry" or model in route.get(
            "candidate_models", []
        ):
            routes.append(route)
    if not routes:
        raise ValueError(f"official failures contain no routes for {model}")
    return routes


def _plan_lookup(plan: dict[str, Any]) -> dict[tuple[str, str], tuple[int, int]]:
    lookup: dict[tuple[str, str], tuple[int, int]] = {}
    for suite in plan["suites"]:
        benchmark_id = str(suite["benchmark_id"])
        for shard in suite["shards"]:
            primary = int(shard["worker_index"])
            for item in shard["inputs"]:
                key = (benchmark_id, str(item["case_id"]))
                retry = int(item["retry_worker_index"])
                if key in lookup or retry == primary:
                    raise ValueError(f"invalid frozen quality-retry route: {key}")
                lookup[key] = (primary, retry)
    return lookup


def stage_selective_recovery(
    *,
    failure_records: Path,
    staged_root: Path,
    shard_plan: Path,
    recovery_model: str,
    output_root: Path,
    worker_health: Path | None = None,
    additional_recovery_worker_indices: tuple[int, ...] = (),
    available_recovery_worker_indices: tuple[int, ...] = (),
) -> dict[str, Any]:
    if recovery_model not in RECOVERY_MODELS:
        raise ValueError(f"unsupported recovery model: {recovery_model}")
    if output_root.exists():
        raise FileExistsError(f"selective recovery staging already exists: {output_root}")
    failures = _load(failure_records)
    plan = _load(shard_plan)
    if int(plan.get("worker_count", -1)) != 4 or int(plan.get("total_input_count", -1)) != 5132:
        raise ValueError("selective recovery requires the frozen 4-worker/5,132-case plan")
    route_lookup = _plan_lookup(plan)
    additional_workers = tuple(sorted(additional_recovery_worker_indices))
    if (
        len(additional_workers) != len(set(additional_workers))
        or any(
            worker in PRIMARY_WORKER_INDICES
            or not 0 <= worker <= MAX_RECOVERY_WORKER_INDEX
            for worker in additional_workers
        )
    ):
        raise ValueError("additional recovery worker indices must be unique values from 4 to 99")
    if additional_workers and recovery_model != "mineru-3.4.4-vlm-quality-retry":
        raise ValueError("additional recovery workers are only valid for MinerU quality retry")
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
            raise ValueError("fewer than two recovery-eligible workers")
        worker_health_sha256 = str(health.get("receipt_sha256"))
    eligible_recovery_workers = eligible_primary_workers | set(additional_workers)
    # Health says which workers were fit to retry; it cannot say which Pods
    # still exist. Primary Pods are collected and deleted once their shard is
    # merged, so a later recovery that trusts health alone routes work to Pods
    # that are long gone. When the caller knows the live pool, intersect.
    restricted_workers: list[int] = []
    if available_recovery_worker_indices:
        available = set(available_recovery_worker_indices)
        restricted_workers = sorted(eligible_recovery_workers - available)
        eligible_recovery_workers &= available
        if len(eligible_recovery_workers) < 2:
            raise ValueError(
                'fewer than two recovery workers remain after restricting to the live pool'
            )
    routes = _routes_for_model(failures, recovery_model)
    identities = [(str(route["benchmark_id"]), str(route["case_id"])) for route in routes]
    if len(identities) != len(set(identities)):
        raise ValueError("selective recovery routes contain duplicate cases")

    routed: list[dict[str, Any]] = []
    for route in routes:
        benchmark_id = str(route["benchmark_id"])
        case_id = str(route["case_id"])
        frozen = route_lookup.get((benchmark_id, case_id))
        if frozen is None:
            raise ValueError(f"official failure is absent from the frozen shard plan: {case_id}")
        primary, retry = frozen
        frozen_retry = retry
        rerouted_due_to_quarantine = False
        rerouted_due_to_capacity_expansion = False
        candidates = sorted(eligible_recovery_workers - {primary})
        if not candidates:
            raise ValueError(f"no healthy different-worker target for {case_id}")
        if additional_workers:
            routing_identity = ",".join(str(value) for value in candidates)
            digest = hashlib.sha256(
                (
                    f"{recovery_model}:{benchmark_id}:{case_id}:"
                    f"expanded-quality-pool-v1:{routing_identity}"
                ).encode()
            ).digest()
            retry = candidates[int.from_bytes(digest[:8], "big") % len(candidates)]
            rerouted_due_to_quarantine = frozen_retry not in eligible_primary_workers
            rerouted_due_to_capacity_expansion = retry != frozen_retry
        elif retry not in eligible_recovery_workers:
            digest = hashlib.sha256(
                f"{recovery_model}:{benchmark_id}:{case_id}:quality-reroute-v1".encode()
            ).digest()
            retry = candidates[int.from_bytes(digest[:8], "big") % len(candidates)]
            rerouted_due_to_quarantine = True
        routed.append(
            {
                **route,
                "primary_worker_index": primary,
                "frozen_recovery_worker_index": frozen_retry,
                "recovery_worker_index": retry,
                "rerouted_due_to_quarantine": rerouted_due_to_quarantine,
                "rerouted_due_to_capacity_expansion": (
                    rerouted_due_to_capacity_expansion
                ),
                "capacity_expansion_routing_applied": bool(additional_workers),
            }
        )

    output_root.mkdir(parents=True)
    workers: list[dict[str, Any]] = []
    staged_count = 0
    for retry_shard_index, retry_worker in enumerate(sorted(eligible_recovery_workers)):
        suite_receipts: list[dict[str, Any]] = []
        for suite in SUITES:
            selected = sorted(
                (
                    route
                    for route in routed
                    if route["benchmark_id"] == suite
                    and route["recovery_worker_index"] == retry_worker
                ),
                key=lambda route: str(route["case_id"]),
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
            by_case = {str(item["case_id"]): item for item in parent["inputs"]}
            suite_root = output_root / f"worker-{retry_worker:02d}" / "suites" / suite
            input_root = suite_root / "inputs"
            input_root.mkdir(parents=True)
            shutil.copy2(parent_path, suite_root / "parent-input-manifest.json")
            inputs: list[dict[str, Any]] = []
            for route in selected:
                case_id = str(route["case_id"])
                item = by_case[case_id]
                filename = Path(str(item["input_relative_path"])).name
                source = (
                    staged_root
                    / f"worker-{int(route['primary_worker_index']):02d}"
                    / "suites"
                    / suite
                    / "inputs"
                    / filename
                )
                target = input_root / filename
                if not source.is_file():
                    raise FileNotFoundError(source)
                os.link(source, target)
                manifest_item = dict(item)
                manifest_item["input_relative_path"] = f"inputs/{filename}"
                inputs.append(manifest_item)
                staged_count += 1
            manifest: dict[str, Any] = {
                "schema": "folynta.public-core-inference-shard.v1",
                "benchmark_id": suite,
                "dataset_revision": parent["dataset_revision"],
                "ground_truth_mounted": False,
                "source_count": parent["source_count"],
                "input_count": len(inputs),
                "complete_source_coverage": False,
                "complete_input_coverage": True,
                "parent_input_manifest_sha256": parent["content_sha256"],
                "campaign_plan_sha256": plan["plan_sha256"],
                "shard_manifest_sha256": _canonical_hash(
                    {
                        "recovery_model": recovery_model,
                        "benchmark_id": suite,
                        "worker_index": retry_worker,
                        "case_ids": [item["case_id"] for item in inputs],
                    }
                ),
                "shard_index": retry_shard_index,
                "shard_count": len(eligible_recovery_workers),
                "inputs": inputs,
            }
            manifest["content_sha256"] = _canonical_hash(manifest)
            (suite_root / "shard-input-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            suite_receipts.append(
                {
                    "benchmark_id": suite,
                    "input_count": len(inputs),
                    "manifest_sha256": manifest["content_sha256"],
                }
            )
        if suite_receipts:
            workers.append(
                {
                    "recovery_worker_index": retry_worker,
                    "input_count": sum(int(suite["input_count"]) for suite in suite_receipts),
                    "suites": suite_receipts,
                }
            )
    if staged_count != len(routes):
        raise ValueError("selective recovery staging coverage is incomplete")
    failure_records_sha256 = (
        f"sha256:{hashlib.sha256(failure_records.read_bytes()).hexdigest()}"
    )
    receipt = {
        "schema": "folynta.public-core-selective-recovery-staging.v1",
        "recovery_model": recovery_model,
        "failure_records_sha256": failure_records_sha256,
        "campaign_plan_sha256": plan["plan_sha256"],
        "input_count": staged_count,
        "different_worker_only": all(
            route["primary_worker_index"] != route["recovery_worker_index"]
            for route in routed
        ),
        "eligible_recovery_workers": sorted(eligible_recovery_workers),
        "recovery_workers_excluded_as_absent": restricted_workers,
        "eligible_primary_recovery_workers": sorted(eligible_primary_workers),
        "additional_recovery_worker_indices": list(additional_workers),
        "routing_policy": (
            "expanded-quality-pool-v1"
            if additional_workers
            else "frozen-or-quarantine-v1"
        ),
        "quarantined_worker_indices": quarantined_workers,
        "quarantine_rerouted_input_count": sum(
            bool(route["rerouted_due_to_quarantine"]) for route in routed
        ),
        "capacity_expansion_rerouted_input_count": sum(
            bool(route["rerouted_due_to_capacity_expansion"]) for route in routed
        ),
        "additional_worker_routed_input_count": sum(
            int(route["recovery_worker_index"]) in set(additional_workers)
            for route in routed
        ),
        "worker_health_receipt_sha256": worker_health_sha256,
        "routes": routed,
        "workers": workers,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    (output_root / "selective-recovery-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failure-records", type=Path, required=True)
    parser.add_argument("--staged-root", type=Path, required=True)
    parser.add_argument("--shard-plan", type=Path, required=True)
    parser.add_argument("--recovery-model", choices=RECOVERY_MODELS, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--worker-health", type=Path)
    parser.add_argument(
        "--additional-recovery-worker-index", action="append", type=int, default=[]
    )
    parser.add_argument(
        "--available-recovery-worker-index",
        action="append",
        type=int,
        default=[],
        help="restrict routing to worker indices whose Pods are actually live",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = stage_selective_recovery(
        failure_records=args.failure_records.resolve(),
        staged_root=args.staged_root.resolve(),
        shard_plan=args.shard_plan.resolve(),
        recovery_model=args.recovery_model,
        output_root=args.output_root.resolve(),
        worker_health=(args.worker_health.resolve() if args.worker_health else None),
        additional_recovery_worker_indices=tuple(
            args.additional_recovery_worker_index
        ),
        available_recovery_worker_indices=tuple(
            args.available_recovery_worker_index
        ),
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RECOVERY_MODELS", "stage_selective_recovery"]
