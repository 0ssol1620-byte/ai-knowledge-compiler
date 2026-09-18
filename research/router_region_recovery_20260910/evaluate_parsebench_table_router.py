"""Score frozen localized table refusals after sealing runtime dispositions."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPLAY = ROOT / "research/router_replay_20260908"
ORACLE = ROOT / "research/router_oracle_20260908"
for module_root in (HERE, REPLAY, ORACLE):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

import features as F  # type: ignore[import-not-found]  # noqa: E402
from bind import load_json, sha256_file  # type: ignore[import-not-found]  # noqa: E402
from evaluate_region_router_replay import (  # noqa: E402
    missing_events,
    paired_bootstrap,
)

EXPECTED_TARGETS = "sha256:1c55470e8a21c96e583dc3289a332c18125faf63115d5bec85b96c0e3c14bb79"
EXPECTED_DISPOSITIONS = (
    "sha256:19d8dfc4136ceaed3c58f2b51f625473bafe404a505dea9d33ace74a050dce5a"
)
EXPECTED_PAGES = 503
EXPECTED_TARGETS_COUNT = 4
PRIMARY = "mineru_vlm"
SPECIALIST = "paddleocr_vl_1_6"
BOOTSTRAP_REPLICATES = 5000
BOOTSTRAP_SEED = "TAVONEL-PARSEBENCH-TABLE-LOCAL-REFUSAL-20260910-V1"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def seal_runtime_policy(
    targets_path: Path, dispositions_path: Path
) -> dict[str, frozenset[str]]:
    if digest(targets_path) != EXPECTED_TARGETS:
        raise ValueError("TABLE_ROUTER_TARGETS_MISMATCH")
    if digest(dispositions_path) != EXPECTED_DISPOSITIONS:
        raise ValueError("TABLE_ROUTER_DISPOSITIONS_MISMATCH")
    targets = {
        str(row["case_key"]): row
        for row in (
            json.loads(line) for line in targets_path.read_text(encoding="utf-8").splitlines()
        )
    }
    dispositions = {
        str(row["case_key"]): row
        for row in (
            json.loads(line)
            for line in dispositions_path.read_text(encoding="utf-8").splitlines()
        )
    }
    if (
        len(targets) != EXPECTED_TARGETS_COUNT
        or set(targets) != set(dispositions)
        or any(row.get("status") != "unresolved" for row in dispositions.values())
    ):
        raise ValueError("TABLE_ROUTER_RUNTIME_POLICY_INVALID")
    policy: dict[str, frozenset[str]] = {}
    for _case_key, row in targets.items():
        unit_key = row.get("unit_key")
        hashes = row.get("critical_token_hashes")
        if (
            not isinstance(unit_key, str)
            or not isinstance(hashes, list)
            or not hashes
            or not all(isinstance(value, str) for value in hashes)
        ):
            raise ValueError("TABLE_ROUTER_RUNTIME_TARGET_INVALID")
        policy[unit_key] = frozenset(hashes)
    return policy


def run(args: argparse.Namespace) -> None:
    arena = args.arena.resolve(strict=True)
    targets_path = args.targets.resolve(strict=True)
    dispositions_path = args.dispositions.resolve(strict=True)

    # Everything below this line is fixed before scorer imports hidden truth.
    localized_refusals = seal_runtime_policy(targets_path, dispositions_path)
    bind_path = ORACLE / "ARENA_BIND.json"
    bind = load_json(bind_path)
    models = sorted(
        model
        for model, entry in bind["models"].items()
        if not entry["founder_excluded"] and entry["frozen_outputs"]["available"]
    )
    units, texts = F.load_or_build_units(arena, "parsebench", models, args.replay_cache)

    import scorer as S  # type: ignore[import-not-found]

    surface = S.load_surfaces(arena, bind)["parsebench:table"]
    table_keys = set(surface.all_units())
    selected_units = [unit for unit in units if unit.unit_key in table_keys]
    if len(selected_units) != EXPECTED_PAGES or not set(localized_refusals) <= table_keys:
        raise ValueError("TABLE_ROUTER_PAGE_DENOMINATOR_MISMATCH")
    gt = S.ground_truth("parsebench:table")
    opportunity_freeze = S.build_opportunity_freeze(["parsebench:table"])
    opportunities = opportunity_freeze["surfaces"]["parsebench:table"]["per_unit"]

    baseline_events = candidate_events = detected_events = 0
    baseline_units = candidate_units = 0
    main_losses: list[float] = []
    hard_fail = 0
    bootstrap_rows: list[tuple[int, int, int]] = []
    for unit in selected_units:
        key = unit.unit_key
        primary = texts.get((PRIMARY, key), "")
        gt_text = gt.get(key, "")
        baseline_missing = missing_events(S, gt_text, primary) if gt_text else {}
        remaining = baseline_missing.copy()
        for exact_hash in localized_refusals.get(key, frozenset()):
            detected_events += remaining.pop(exact_hash, 0)
        base_count = sum(baseline_missing.values())
        candidate_count = sum(remaining.values())
        opportunity_count = sum((opportunities.get(key) or {}).values())
        baseline_events += base_count
        candidate_events += candidate_count
        baseline_units += int(base_count > 0)
        candidate_units += int(candidate_count > 0)
        bootstrap_rows.append((base_count, candidate_count, opportunity_count))
        loss = S.unit_loss(surface, PRIMARY, key)
        main_losses.append(loss)
        hard_fail += int(loss > S.HARD_FAIL_TAU)

    total_opportunities = sum(row[2] for row in bootstrap_rows)
    primary_cost = float(bind["cost_and_latency"]["per_model"][PRIMARY]["cost_per_1000_pages_usd"])
    specialist_cost = float(
        bind["cost_and_latency"]["per_model"][SPECIALIST]["cost_per_1000_pages_usd"]
    )
    mean_loss = statistics.fmean(main_losses)
    result: dict[str, Any] = {
        "schema": "tavonel.router.parsebench_table_local_refusal.v1",
        "status": "SPENT_DEVELOPMENT_DIAGNOSTIC",
        "pages": len(selected_units),
        "localized_unresolved_regions": len(localized_refusals),
        "specialist_invocation_fraction": len(localized_refusals) / len(selected_units),
        "baseline": {
            "main_representation_mean_loss": mean_loss,
            "main_representation_irr": 1.0 - mean_loss,
            "hard_fail_pages": hard_fail,
            "sclr_silent_units": baseline_units,
            "sclr_silent_events": baseline_events,
            "sclr_unit_rate": baseline_units / len(selected_units),
            "sclr_opportunity_rate": baseline_events / total_opportunities,
            "historical_raw_provider_usd_per_1000_pages": primary_cost,
        },
        "candidate": {
            "main_representation_mean_loss": mean_loss,
            "main_representation_irr": 1.0 - mean_loss,
            "hard_fail_pages_on_main_representation": hard_fail,
            "sclr_silent_units": candidate_units,
            "sclr_silent_events": candidate_events,
            "sclr_unit_rate": candidate_units / len(selected_units),
            "sclr_opportunity_rate": candidate_events / total_opportunities,
            "critical_events_detected_by_local_refusal": detected_events,
            "localized_unresolved_page_fraction": len(localized_refusals)
            / len(selected_units),
            "historical_raw_provider_usd_per_1000_pages": primary_cost
            + specialist_cost * len(localized_refusals) / len(selected_units),
            "region_runtime_p95": None,
            "region_runtime_p95_reason": "stored specialist evidence is full-page",
        },
        "paired_bootstrap": paired_bootstrap(
            bootstrap_rows, seed=BOOTSTRAP_SEED, replicates=BOOTSTRAP_REPLICATES
        ),
        "critical_opportunities": total_opportunities,
        "input_bindings": {
            "arena_bind_sha256": sha256_file(bind_path),
            "targets_sha256": digest(targets_path),
            "runtime_dispositions_sha256": digest(dispositions_path),
        },
        "hidden_table_truth_visible_to_runtime": False,
        "quality_claim": False,
        "confirmatory_eligible": False,
        "production_promotion": False,
        "fresh_holdout_opened": False,
        "new_gpu_cost_usd": 0,
        "limitations": [
            "targets and policy were developed on this spent corpus",
            "localized refusal is a detection result, not recovered table content",
            "the broad table score applies to the unchanged MinerU representation",
            "crop latency and cost are unmeasured",
        ],
    }
    output = args.output.resolve()
    if output.exists():
        raise ValueError("TABLE_ROUTER_REPLAY_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    result_path = output / "RESULT.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "result_sha256": digest(result_path),
        "policy_freeze_sha256": digest(HERE / "PARSEBENCH_TABLE_ROUTER_REPLAY_FREEZE.json"),
        "text_disclosed": False,
    }
    (output / "RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--dispositions", type=Path, required=True)
    parser.add_argument("--replay-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
