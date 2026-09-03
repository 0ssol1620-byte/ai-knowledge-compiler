#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "research" / "experiments" / "H1-A12-01"
SHARED = ROOT / "research" / "experiments" / "H1-A9-A12-SHARED-01"
PREREG = EXP / "preregistration-v2.json"
AUDIT_MD = EXP / "A12_RUNTIME_READINESS_AUDIT_2026-08-19.md"
CANDIDATES = ROOT / "benchmark" / "v6" / "candidate-registry.yaml"
POOLS = ROOT / "infra" / "runpod" / "v6" / "pool-registry.yaml"
SOURCE_RECEIPT = SHARED / "source-only-v1" / "receipt.json"
BUDGET = SHARED / "BUDGET_AND_REUSE_PLAN.json"
OUTPUT = EXP / "receipts" / "runtime-readiness-audit-2026-08-19.json"
INDEPENDENT = ("paddleocr-vl-1.6", "deepseek-ocr-2")
POOL_BY_CANDIDATE = {
    "paddleocr-vl-1.6": "parser-paddleocr-vl-1-6",
    "deepseek-ocr-2": "parser-deepseek-ocr-2",
}


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in items}


def exact_recipe_candidates() -> list[str]:
    hits: list[str] = []
    for base in (EXP, SHARED):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".json", ".yaml", ".yml"}:
                continue
            if path == OUTPUT:
                continue
            name = path.name.casefold()
            if "recipe" in name and ("same" in name or "ablation" in name or "mineru" in name):
                hits.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    return sorted(hits)


def main() -> int:
    # The output path was hardcoded. Re-running the audit after a gate changes is
    # the correct way to re-evaluate it, but overwriting the earlier receipt
    # would destroy the record of what the gates said before -- so the path is an
    # argument now and the default is unchanged for anything that called it.
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output: Path = args.output.resolve()

    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    candidates = yaml.safe_load(CANDIDATES.read_text(encoding="utf-8"))
    pools = yaml.safe_load(POOLS.read_text(encoding="utf-8"))
    source = json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))
    candidate_map = by_id(candidates["candidates"])
    pool_map = by_id(pools["pools"])

    independent: dict[str, Any] = {}
    runtime_ready = True
    licence_ready = True
    production_promotion = True
    for candidate_id in INDEPENDENT:
        candidate = candidate_map[candidate_id]
        pool = pool_map[POOL_BY_CANDIDATE[candidate_id]]
        candidate_runtime_ready = (
            candidate.get("execution_state") == "ready"
            and bool(candidate.get("identity", {}).get("runtime_recipe"))
            and bool(pool.get("enabled"))
            and pool.get("identity_state") == "ready"
            and bool(pool.get("image_digest"))
        )
        runtime_ready = runtime_ready and candidate_runtime_ready
        licence = candidate.get("license", {})
        candidate_licence_ready = (
            licence.get("status") == "approved" and licence.get("commercial_use") == "allowed"
        )
        licence_ready = licence_ready and candidate_licence_ready
        production_promotion = production_promotion and bool(candidate.get("promotion_eligible"))
        independent[candidate_id] = {
            "candidate_execution_state": candidate.get("execution_state"),
            "candidate_promotion_eligible": candidate.get("promotion_eligible"),
            "license": licence,
            "pool_id": pool.get("id"),
            "pool_enabled": pool.get("enabled"),
            "pool_identity_state": pool.get("identity_state"),
            "pool_image_digest": pool.get("image_digest"),
            "formal_runtime_ready": candidate_runtime_ready,
        }

    source_ready = (
        source.get("case_count") == 48
        and source.get("all_input_hashes_verified") is True
        and source.get("ground_truth_in_bundle") is False
        and source.get("ground_truth_mounted") is False
    )
    recipe_files = exact_recipe_candidates()
    exact_recipe_ready = bool(recipe_files)
    historical_reserve = budget.get("planning_reserve", {})
    estimated_under_nominal = max(
        float(value)
        for key, value in historical_reserve.items()
        if key.endswith("_usd") and isinstance(value, (int, float))
    ) <= float(prereg["gpu_budget"]["nominal_pilot_cap_usd"])

    blockers = []
    if not runtime_ready:
        blockers.append("formal_immutable_runtime_not_ready")
    if not source_ready:
        blockers.append("source_only_integrity_not_ready")
    if not exact_recipe_ready:
        blockers.append("exact_same_family_recipe_not_frozen")

    body: dict[str, Any] = {
        "schema": "tavonel.a12-runtime-readiness-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "experiment_id": "H1-A12-01",
        "evidence_class": "repository readiness audit; no A12 intervention outcome",
        "source_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
            for path in (PREREG, AUDIT_MD, CANDIDATES, POOLS, SOURCE_RECEIPT, BUDGET)
        },
        "gates": {
            "licence_ready": licence_ready,
            "source_only_ready": source_ready,
            "formal_immutable_runtime_ready": runtime_ready,
            "exact_same_family_recipe_ready": exact_recipe_ready,
            "historical_cost_reserve_under_nominal_cap": estimated_under_nominal,
            "provider_preflight_run": False,
            "provider_preflight_reason": (
                "not run because preregistered earlier stop-before-spend gates already fail"
            ),
        },
        "independent_candidates": independent,
        "exact_recipe_artifact_candidates": recipe_files,
        "source_only": {
            "case_count": source.get("case_count"),
            "all_input_hashes_verified": source.get("all_input_hashes_verified"),
            "ground_truth_in_bundle": source.get("ground_truth_in_bundle"),
            "ground_truth_mounted": source.get("ground_truth_mounted"),
            "archive_sha256": source.get("archive_sha256"),
        },
        "gpu_spend_authorized": not blockers,
        "incremental_gpu_spend_usd": 0.0,
        "blockers": blockers,
        "overall_state": (
            "READY_FOR_PROVIDER_PREFLIGHT" if not blockers else "BLOCKED_RUNTIME_AND_RECIPE"
        ),
        "production_promotion_eligible": production_promotion,
        "claim_boundary": (
            "Readiness evidence only. It authorizes no A12 empirical benefit claim and does not "
            "convert historical cost estimates into measured provider cost."
        ),
    }
    body["receipt_sha256"] = canonical_sha(body)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "overall_state": body["overall_state"],
        "blockers": blockers,
        "licence_ready": licence_ready,
        "source_only_ready": source_ready,
        "gpu_spend_authorized": body["gpu_spend_authorized"],
        "receipt": str(output.relative_to(ROOT)).replace("\\", "/"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
