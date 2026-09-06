"""Synthetic 3-system x 3-benchmark campaign tree for lane E3 tests.

Nothing here is real campaign data: three model keys picked from
``arena.constants.MODEL_KEYS`` (one of them the subscription lane) stand in
for the full twelve, and every number is small and hand-chosen so a test can
assert on it exactly. The tree mirrors ARENA_CONTRACT's layout closely enough
that :mod:`arena.reports.loaders` cannot tell it from the real thing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arena.reports.paths import SourcePaths
from arena.reports.variant_ids import VARIANT_IDS, variant_dir_name

MODELS: tuple[str, ...] = ("paddleocr_vl_1_6", "mineru_pipeline", "opus5_subscription")
BENCHMARKS: tuple[str, ...] = ("parsebench", "omnidoc", "olmocr")
GPU_MODELS: tuple[str, ...] = ("paddleocr_vl_1_6", "mineru_pipeline")
VARIANT_DIR_NAMES: dict[str, str] = {v: variant_dir_name(v) for v in VARIANT_IDS}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _page_receipt(
    *,
    model_key: str,
    case_key: str,
    sample_id: str,
    benchmark: str,
    status: str = "SUCCESS",
    total_ms: int = 2000,
    attempt: int = 1,
    retry_count: int = 0,
    error_class: str | None = None,
    gpu_type: str | None = "RTX4090",
    pod_id: str | None = "pod-1",
    peak_vram_mb: int | None = 8000,
    job_kind: str = "inference",
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": "tavonel.arena.page-receipt.v1",
        "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
        "inference_job_id": f"{model_key}-{case_key}-job",
        "benchmark": benchmark,
        "sample_id": sample_id,
        "case_key": case_key,
        "source_sha256": "sha256:" + "a" * 64,
        "model_key": model_key,
        "model_revision": "rev-1",
        "runtime_image_digest": "sha256:" + "b" * 64,
        "runtime_mode": "subscription" if model_key == "opus5_subscription" else "baked",
        "job_kind": job_kind,
        "gpu_type": None if model_key == "opus5_subscription" else gpu_type,
        "pod_id": None if model_key == "opus5_subscription" else pod_id,
        "worker_id": f"{model_key}-w0",
        "shard_id": f"{model_key}-{benchmark}-0000",
        "prompt_id": f"{model_key}-prompt-v1",
        "prompt_sha256": "sha256:" + "c" * 64,
        "inference_config_sha256": "sha256:" + "d" * 64,
        "image_width": 1000,
        "image_height": 1400,
        "queued_at": "2026-09-03T00:00:00.000Z",
        "started_at": "2026-09-03T00:00:01.000Z",
        "finished_at": "2026-09-03T00:00:02.000Z",
        "total_ms": total_ms,
        "peak_vram_mb": None if model_key == "opus5_subscription" else peak_vram_mb,
        "input_bytes": 50_000,
        "output_bytes": 2_000,
        "output_chars": 1_900,
        "attempt": attempt,
        "retry_count": retry_count,
        "status": status,
        "error_class": error_class,
        "error_message": None if status == "SUCCESS" else f"{error_class} on {case_key}",
        "wasted_gpu_seconds": 0.0 if status == "SUCCESS" else round(total_ms / 1000.0, 3),
    }
    if status == "SUCCESS":
        receipt["raw_output_sha256"] = "sha256:" + "e" * 64
        receipt["canonical_output_sha256"] = "sha256:" + "f" * 64
    if model_key == "opus5_subscription":
        receipt["api_equivalent_list_price_usd"] = 0.045
        receipt["subscription_included_usage"] = True
        receipt["actual_marginal_api_cost"] = "N/A"
    return receipt


@pytest.fixture
def campaign_root(tmp_path: Path) -> Path:
    """A fully populated synthetic campaign tree; see module docstring."""

    root = tmp_path / "campaign"
    root.mkdir()

    # ---- scores/<model>/<benchmark>/{summary.json, per_case.jsonl} ----
    quality_by_model_benchmark = {
        ("paddleocr_vl_1_6", "parsebench"): 0.80,
        ("paddleocr_vl_1_6", "omnidoc"): 0.75,
        ("paddleocr_vl_1_6", "olmocr"): 0.70,
        ("mineru_pipeline", "parsebench"): 0.85,
        ("mineru_pipeline", "omnidoc"): 0.90,
        ("mineru_pipeline", "olmocr"): 0.60,
        # opus5_subscription/olmocr deliberately has no summary.json, to
        # exercise the missing-input path; parsebench/omnidoc are EVALUATOR_BLOCKED
        # and present respectively.
        ("opus5_subscription", "parsebench"): 0.95,
    }
    for (model_key, benchmark), value in quality_by_model_benchmark.items():
        _write_json(
            root / "scores" / model_key / benchmark / "summary.json",
            {
                "overall": value,
                "text_edit_distance": round(1 - value, 3),
                "provenance": {"evaluator_repository": "fake", "scored_at": "2026-09-03T00:00:00Z"},
            },
        )
        _write_jsonl(
            root / "scores" / model_key / benchmark / "per_case.jsonl",
            [
                {"case_key": f"{benchmark}-case-0", "document_type": "tables", "score": value},
                {
                    "case_key": f"{benchmark}-case-1",
                    "document_type": "old_scans",
                    "score": round(value - 0.1, 3),
                },
            ],
        )
    _write_json(
        root / "scores" / "opus5_subscription" / "omnidoc" / "summary.json",
        {"status": "EVALUATOR_BLOCKED"},
    )

    # ---- runs/<model>/{receipts/*.json, run-summary.json} ----
    for model_key in MODELS:
        cases = [
            (benchmark, f"{benchmark}-case-0", f"{benchmark}:case/0")
            for benchmark in BENCHMARKS
        ] + [(BENCHMARKS[0], f"{BENCHMARKS[0]}-case-1", f"{BENCHMARKS[0]}:case/1")]
        success = 0
        for i, (benchmark, case_key, sample_id) in enumerate(cases):
            status = "FAILED" if (model_key == "mineru_pipeline" and i == 0) else "SUCCESS"
            error_class = "CUDA_OOM" if status == "FAILED" else None
            receipt = _page_receipt(
                model_key=model_key,
                case_key=case_key,
                sample_id=sample_id,
                benchmark=benchmark,
                status=status,
                total_ms=1500 + i * 200,
                error_class=error_class,
                retry_count=1 if i == 1 else 0,
            )
            _write_json(root / "runs" / model_key / "receipts" / f"{case_key}.json", receipt)
            if status == "SUCCESS":
                success += 1
        _write_json(
            root / "runs" / model_key / "run-summary.json",
            {
                "schema": "tavonel.arena.run-summary.v1",
                "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
                "model_key": model_key,
                "model_revision": "rev-1",
                "runtime_image_digest": "sha256:" + "b" * 64,
                "runtime_mode": "subscription" if model_key == "opus5_subscription" else "baked",
                "started_at": "2026-09-03T00:00:00.000Z",
                "finished_at": "2026-09-03T00:10:00.000Z",
                "sample_count": len(cases),
                "success_count": success,
                "failed_count": len(cases) - success,
                "quarantined_count": 0,
                "paused_count": 0,
                "wasted_gpu_seconds": 0.0,
            },
        )

    # ---- cost/pod_ledger.jsonl (GPU models only) ----
    _write_jsonl(
        root / "cost" / "pod_ledger.jsonl",
        [
            {
                "schema": "tavonel.arena.pod-ledger.v1",
                "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
                "model_key": model_key,
                "runtime_mode": "baked",
                "pod_id": "pod-1",
                "gpu_type": "RTX4090",
                "listed_rate_usd_per_hour": 0.5,
                "price_snapshot_sha256": "sha256:" + "0" * 64,
                "provisioned_at": "2026-09-03T00:00:00.000Z",
                "billed_seconds": 100.0,
                "model_loading_seconds": 10.0,
                "useful_inference_seconds": 80.0,
                "retry_seconds": 5.0,
                "idle_seconds": 5.0,
                "estimated_provider_cost_usd": 0.0139,
                "useful_cost_usd": 0.0111,
                "wasted_cost_usd": 0.0028,
            }
            for model_key in GPU_MODELS
        ],
    )

    # ---- failures/errors.jsonl ----
    _write_jsonl(
        root / "failures" / "errors.jsonl",
        [
            {
                "schema": "tavonel.arena.error-record.v1",
                "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
                "error_class": "CUDA_OOM",
                "first_seen": "2026-09-03T00:00:00.000Z",
                "last_seen": "2026-09-03T00:00:05.000Z",
                "count": 1,
                "affected_model": "mineru_pipeline",
                "retryability": True,
                "root_cause": None,
                "resolution": None,
                "wasted_gpu_seconds": 1.5,
            }
        ],
    )

    # ---- model_registry.json / evaluator_registry.json / campaign_manifest.json ----
    _write_json(
        root / "model_registry.json",
        {
            "models": {
                model_key: {
                    "model_key": model_key,
                    "display_name": model_key.replace("_", " ").title(),
                    "revision": "0" * 40 if model_key != "opus5_subscription" else "claude-opus-5",
                }
                for model_key in MODELS
            }
        },
    )
    _write_json(
        root / "evaluator_registry.json",
        {
            "evaluators": {
                benchmark: {
                    "benchmark": benchmark,
                    "main_pin": "1" * 40,
                    "historical_pin": "2" * 40,
                }
                for benchmark in BENCHMARKS
            }
        },
    )
    _write_json(
        root / "campaign_manifest.json",
        {"campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1"},
    )

    # ---- receipts/canary-<model>.json, receipts/opus-*.json ----
    for model_key in GPU_MODELS:
        _write_json(
            root / "receipts" / f"canary-{model_key}.json",
            {
                "schema": "tavonel.arena.canary-receipt.v1",
                "model_key": model_key,
                "status": "PASS",
                "stage_latency_ms": {
                    "cold_start": {"p50_ms": 4000, "p90_ms": 5000, "p95_ms": 5200},
                    "model_loading": {"p50_ms": 3000, "p90_ms": 3200, "p95_ms": 3300},
                    "warm_up": {"p50_ms": 1000, "p90_ms": 1100, "p95_ms": 1200},
                },
            },
        )
    _write_json(
        root / "receipts" / "opus-canary-20260903T000000Z.json",
        {
            "schema": "tavonel.arena.opus-canary-receipt.v1",
            "model_key": "opus5_subscription",
            "counts": {"attempted": 4, "success": 4, "failed": 0},
            "api_equivalent_list_price_usd_total": 0.18,
            "subscription_included_usage": True,
            "actual_marginal_api_cost": "N/A",
            "stopped": False,
            "stop_reason": None,
        },
    )

    # ---- tavonel/route_decisions, adaptive_replay, recovery_jobs, disagreement, cost ----
    for variant in VARIANT_IDS:
        dir_name = VARIANT_DIR_NAMES[variant]
        decisions = []
        for i in range(3):
            case_key = f"parsebench-case-{i}"
            decision = {
                "schema": "tavonel.arena.route-decision.v1",
                "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
                "variant": variant,
                "case_key": case_key,
                "sample_id": f"parsebench:case/{i}",
                "benchmark": "parsebench",
                "primary": "paddleocr_vl_1_6",
                "decision": "ESCALATE" if i == 0 else "ACCEPT",
                "target": "opus5_subscription" if i == 0 else None,
                "final_model": "opus5_subscription" if i == 0 else "paddleocr_vl_1_6",
                "escalation_stage": 1 if i == 0 else 0,
                "number_of_model_calls": 2 if i == 0 else 1,
                "recovery_required": i == 1,
                "recovery_types": ["higher_dpi"] if i == 1 else [],
                "signals": {},
                "signals_sha256": "sha256:" + "1" * 64,
                "decision_sha256": "sha256:" + f"{i}" * 63 + "a",
                "decided_before_gt": True,
                "policy_id": f"tavonel.{variant}.v1",
                "policy_sha256": "sha256:" + "2" * 64,
            }
            decisions.append(decision)
            _write_json(
                root / "tavonel" / "route_decisions" / dir_name / f"{case_key}.json", decision
            )
        _write_json(
            root / "tavonel" / "route_decisions" / dir_name / "FROZEN.json",
            {
                "frozen_at": "2026-09-03T00:00:00.000Z",
                "decision_manifest_sha256": "sha256:" + "3" * 64,
                "count": len(decisions),
                "policy_sha256": "sha256:" + "2" * 64,
            },
        )
        manifest_rows = [
            {
                "case_key": d["case_key"],
                "sample_id": d["sample_id"],
                "benchmark": d["benchmark"],
                "primary_model_key": d["primary"],
                "chosen_model_key": d["final_model"],
                "final_model": d["final_model"],
                "decision": d["decision"],
                "escalation_stage": d["escalation_stage"],
                "number_of_model_calls": d["number_of_model_calls"],
                "recovery_required": d["recovery_required"],
                "recovery_types": d["recovery_types"],
                "unresolved": False,
            }
            for d in decisions
        ]
        _write_jsonl(
            root / "tavonel" / "adaptive_replay" / dir_name / "manifest.jsonl", manifest_rows
        )
        _write_json(
            root / "tavonel" / "adaptive_replay" / dir_name / "replay-summary.json",
            {
                "variant": variant,
                "total_cases": len(manifest_rows),
                "resolved_cases": len(manifest_rows),
                "unresolved_cases": 0,
                "pages_per_model": {"paddleocr_vl_1_6": 2, "opus5_subscription": 1},
            },
        )
        _write_json(
            root / "tavonel" / "cost" / f"{dir_name}.json",
            {
                "schema": "tavonel.arena.counterfactual-cost.v1",
                "variant": variant,
                "totals": {
                    "pages_served": 3,
                    "priced_pages": 3,
                    "unpriced_pages": 0,
                    "total_usd": 0.12,
                    "usd_per_1000_pages": 40.0,
                },
                "all_models_full_run_usd_for_contrast_only": 0.30,
                "recovery": {"planned_jobs": 1, "type_counts": {"higher_dpi": 1}, "usd": None},
            },
        )

    _write_jsonl(
        root / "tavonel" / "recovery_jobs" / "plan.jsonl",
        [
            {
                "schema": "tavonel.arena.recovery-job.v1",
                "recovery_job_id": "r" * 64,
                "base_inference_job_id": "b" * 64,
                "case_key": "parsebench-case-1",
                "sample_id": "parsebench:case/1",
                "model_key": "paddleocr_vl_1_6",
                "recovery_type": "higher_dpi",
                "recovery_config": {"render_scale": 2.0},
                "recovery_config_sha256": "sha256:" + "4" * 64,
                "round": 1,
                "trigger_signals": ["low_text_density"],
                "planned_before_gt": True,
            }
        ],
    )
    _write_jsonl(
        root / "tavonel" / "disagreement" / "pairs.jsonl",
        [
            {
                "schema": "tavonel.arena.disagreement-pair.v1",
                "case_key": "parsebench-case-0",
                "sample_id": "parsebench:case/0",
                "benchmark": "parsebench",
                "model_a": "mineru_pipeline",
                "model_b": "paddleocr_vl_1_6",
                "metrics": {
                    "text_similarity": 0.92,
                    "number_set_disagreement": 0.05,
                    "table_row_count_difference": 0,
                    "heading_count_difference": 0,
                    "formula_count_difference": 0,
                    "reading_order_disagreement": 0.01,
                    "output_length_ratio": 0.98,
                    "one_empty_one_nonempty": False,
                    "one_truncated_one_complete": False,
                },
            }
        ],
    )

    # ---- evidence/cleanup_receipt.json ----
    _write_json(
        root / "evidence" / "cleanup_receipt.json",
        {"schema": "tavonel.arena.cleanup-receipt.v1", "pods_remaining": 0, "verified": True},
    )

    return root


@pytest.fixture
def source_paths(campaign_root: Path) -> SourcePaths:
    return SourcePaths(root=campaign_root)
