#!/usr/bin/env python3
"""Build a full MinerU-composite candidate view from alternate-model outputs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from apply_operational_retries import (
    ResultSource,
    _load,
    _replace_bound,
    _sha256,
    _write,
)
from paddle_result_to_mineru_model import paddle_response_to_mineru_model
from public_core_merge import EXPECTED_ARTIFACT_SHA256, EXPECTED_CANDIDATE_ID, SUITES
from stage_selective_recovery import RECOVERY_MODELS

ALTERNATE_MODELS = tuple(
    model for model in RECOVERY_MODELS if model != "mineru-3.4.4-vlm-quality-retry"
)
MODEL_IDENTITIES = {
    "paddleocr-vl-1.6": {
        "candidate_id": "paddleocr-vl-1.6",
        "artifact_manifest_sha256": (
            "sha256:40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
        ),
    },
    "deepseek-ocr-2": {
        "candidate_id": "deepseek-ocr-2-3b-transformers",
        "artifact_manifest_sha256": (
            "sha256:77137d41428555c636b04ec5a1617e72c7e3e98afd81502b5c8659f6430421bc"
        ),
    },
}

PADDLE_MARGINAL_LABELS = {
    "number",
    "footnote",
    "header",
    "header_image",
    "footer",
    "footer_image",
}


def _case_lookup(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runs = summary.get("runs", [])
    if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
        raise ValueError("alternate candidate requires exactly repeat 1")
    cases = runs[0].get("cases", [])
    result = {str(item["case_id"]): item for item in cases}
    if len(result) != len(cases):
        raise ValueError("alternate result contains duplicate cases")
    return result


def _write_paddle_model(
    response_path: Path,
    target: Path,
    *,
    permit_empty_markdown_error: bool = False,
    semantic_empty_page: bool = False,
) -> str:
    payload = _load(response_path)
    if permit_empty_markdown_error and payload.get("error") == "empty_markdown":
        payload = dict(payload)
        payload["error"] = None
    model = [[]] if semantic_empty_page else paddle_response_to_mineru_model(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    target.write_text(
        json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return _sha256(target)


def _paddle_text_blocks(payload: dict[str, Any]) -> list[dict[str, str]]:
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError("Paddle empty-Markdown fallback requires exactly one page")
    page = pages[0]
    result = page.get("res", page) if isinstance(page, dict) else None
    parsing = result.get("parsing_res_list") if isinstance(result, dict) else None
    if not isinstance(parsing, list):
        raise ValueError("Paddle empty-Markdown fallback has no parsing_res_list")
    blocks: list[tuple[tuple[int, float, float, int], dict[str, str]]] = []
    for index, raw in enumerate(parsing):
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("block_content") or "").strip()
        if not content:
            continue
        label = str(raw.get("block_label") or "text").strip().lower().replace("-", "_")
        order = raw.get("block_order")
        bbox = raw.get("block_bbox")
        x = float(bbox[0]) if isinstance(bbox, list) and len(bbox) == 4 else 0.0
        y = float(bbox[1]) if isinstance(bbox, list) and len(bbox) == 4 else float(index)
        if isinstance(order, bool) or not isinstance(order, (int, float)):
            key = (1, y, x, index)
        else:
            key = (0, float(order), 0.0, index)
        blocks.append((key, {"label": label, "content": content}))
    return [block for _, block in sorted(blocks, key=lambda item: item[0])]


def _write_recovered_markdown(target: Path, blocks: list[dict[str, str]]) -> str:
    content = "\n\n".join(block["content"] for block in blocks).strip()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{content}\n" if content else "", encoding="utf-8")
    return _sha256(target)


def _write_markdown_model(markdown_path: Path, target: Path) -> str:
    content = markdown_path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError("cannot build a model payload from empty Markdown")
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(
        target,
        [[{"bbox": [0.0, 0.0, 1.0, 1.0], "type": "text", "content": content}]],
    )
    return _sha256(target)


def apply_alternate_candidates(
    *,
    baseline_sources: tuple[ResultSource, ...],
    recovery_root: Path,
    selective_plan: Path,
    recovery_model: str,
    output_root: Path,
    operational_failure_targets: bool = False,
    paddle_layout_fallback_root: Path | None = None,
) -> dict[str, Any]:
    baselines = {item.worker_index: item.result_root for item in baseline_sources}
    if set(baselines) != {0, 1, 2, 3} or len(baselines) != len(baseline_sources):
        raise ValueError("exactly four unique baseline workers are required")
    if recovery_model not in ALTERNATE_MODELS:
        raise ValueError("unsupported alternate recovery model")
    if output_root.exists():
        raise FileExistsError(f"alternate candidate output exists: {output_root}")
    plan = _load(selective_plan)
    if (
        plan.get("schema") != "folynta.public-core-selective-recovery-staging.v1"
        or plan.get("recovery_model") != recovery_model
        or plan.get("different_worker_only") is not True
    ):
        raise ValueError("alternate recovery plan identity is invalid")
    routes = plan.get("routes", [])
    if int(plan.get("input_count", -1)) != len(routes):
        raise ValueError("alternate recovery plan coverage is invalid")

    output_root.mkdir(parents=True)
    original_hashes: dict[tuple[int, str], str] = {}
    for worker in range(4):
        shutil.copytree(
            baselines[worker], output_root / f"worker-{worker:02d}", copy_function=os.link
        )
        for suite in SUITES:
            original_hashes[(worker, suite)] = _sha256(
                baselines[worker] / suite / "run-summary.json"
            )

    identity = MODEL_IDENTITIES[recovery_model]
    recovery_cases: dict[tuple[int, str, str], tuple[dict[str, Any], str]] = {}
    for worker in range(4):
        for suite in SUITES:
            summary_path = (
                recovery_root / f"worker-{worker:02d}" / suite / "run-summary.json"
            )
            if not summary_path.is_file():
                continue
            summary = _load(summary_path)
            if (
                summary.get("candidate_id") != identity["candidate_id"]
                or summary.get("artifact_manifest_sha256")
                != identity["artifact_manifest_sha256"]
                or summary.get("ground_truth_mounted") is not False
                or summary.get("evidence_class") != "public-core-shard"
            ):
                raise ValueError(f"alternate result identity mismatch: {summary_path}")
            summary_sha256 = _sha256(summary_path)
            for case_id, case in _case_lookup(summary).items():
                key = (worker, suite, case_id)
                if key in recovery_cases:
                    raise ValueError(f"duplicate alternate result: {key}")
                recovery_cases[key] = (case, summary_sha256)

    paddle_fallback_cases: dict[tuple[int, str, str], dict[str, Any]] = {}
    if paddle_layout_fallback_root is not None:
        for worker in range(4):
            for suite in SUITES:
                summary_path = (
                    paddle_layout_fallback_root
                    / f"worker-{worker:02d}"
                    / suite
                    / "run-summary.json"
                )
                if not summary_path.is_file():
                    continue
                summary = _load(summary_path)
                if (
                    summary.get("candidate_id")
                    != MODEL_IDENTITIES["paddleocr-vl-1.6"]["candidate_id"]
                    or summary.get("artifact_manifest_sha256")
                    != MODEL_IDENTITIES["paddleocr-vl-1.6"]["artifact_manifest_sha256"]
                    or summary.get("ground_truth_mounted") is not False
                ):
                    raise ValueError(
                        f"Paddle layout fallback identity mismatch: {summary_path}"
                    )
                for case_id, case in _case_lookup(summary).items():
                    paddle_fallback_cases[(worker, suite, case_id)] = case

    applied = 0
    inference_failed = 0
    empty_markdown_failures_resolved = 0
    overlays: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for route in routes:
        suite = str(route["benchmark_id"])
        case_id = str(route["case_id"])
        primary = int(route["primary_worker_index"])
        recovery_worker = int(route["recovery_worker_index"])
        if primary == recovery_worker:
            raise ValueError(f"same-worker alternate recovery is forbidden: {suite}/{case_id}")
        observed = recovery_cases.get((recovery_worker, suite, case_id))
        if observed is None:
            raise ValueError(f"planned alternate result is missing: {suite}/{case_id}")
        recovery_case, recovery_summary_sha256 = observed
        candidate_suite = output_root / f"worker-{primary:02d}" / suite
        summary_path = candidate_suite / "run-summary.json"
        summary = _load(summary_path)
        if (
            summary.get("candidate_id") != EXPECTED_CANDIDATE_ID
            or summary.get("artifact_manifest_sha256") != EXPECTED_ARTIFACT_SHA256
        ):
            raise ValueError(f"baseline MinerU identity mismatch: {summary_path}")
        baseline_case = _case_lookup(summary).get(case_id)
        expected_status = "failed" if operational_failure_targets else "completed"
        if baseline_case is None or baseline_case.get("status") != expected_status:
            raise ValueError(
                "alternate target baseline status is invalid: "
                f"{suite}/{case_id}/{baseline_case and baseline_case.get('status')}"
            )
        status = str(recovery_case.get("status"))
        overlay: dict[str, Any] = {
            "benchmark_id": suite,
            "case_id": case_id,
            "recovery_model": recovery_model,
            "primary_worker_index": primary,
            "logical_recovery_worker_index": recovery_worker,
            "baseline_summary_sha256": original_hashes[(primary, suite)],
            "recovery_summary_sha256": recovery_summary_sha256,
            "recovery_status": status,
            "candidate_applied": False,
        }
        if status == "completed":
            recovery_suite = recovery_root / f"worker-{recovery_worker:02d}" / suite
            markdown_sha256 = str(recovery_case["markdown_sha256"])
            _replace_bound(
                recovery_suite / "markdown-repeat-1" / f"{case_id}.md",
                candidate_suite / "markdown-repeat-1" / f"{case_id}.md",
                markdown_sha256,
            )
            model_sha256: str | None = None
            model_strategy = "not_required"
            if recovery_model == "paddleocr-vl-1.6":
                response = recovery_suite / "repeat-1" / f"{case_id}.json"
                if _sha256(response) != str(recovery_case["artifact_sha256"]):
                    raise ValueError(f"Paddle response binding mismatch: {case_id}")
                model_sha256 = _write_paddle_model(
                    response,
                    candidate_suite
                    / "repeat-1"
                    / case_id
                    / "vlm"
                    / f"{case_id}_model.json",
                )
                model_strategy = "paddle_layout_adapter_v1"
            elif suite == "parsebench":
                if operational_failure_targets:
                    fallback = paddle_fallback_cases.get(
                        (recovery_worker, suite, case_id)
                    )
                    if (
                        fallback is None
                        or fallback.get("status") != "failed"
                        or fallback.get("error") != "empty_markdown"
                    ):
                        raise ValueError(
                            "DeepSeek operational ParseBench recovery requires a "
                            f"bound failed Paddle layout response: {case_id}"
                        )
                    response = (
                        paddle_layout_fallback_root
                        / f"worker-{recovery_worker:02d}"
                        / suite
                        / "repeat-1"
                        / f"{case_id}.json"
                    )
                    if _sha256(response) != str(fallback["artifact_sha256"]):
                        raise ValueError(
                            f"Paddle layout fallback response mismatch: {case_id}"
                        )
                    model_target = (
                        candidate_suite
                        / "repeat-1"
                        / case_id
                        / "vlm"
                        / f"{case_id}_model.json"
                    )
                    if _paddle_text_blocks(_load(response)):
                        model_sha256 = _write_paddle_model(
                            response,
                            model_target,
                            permit_empty_markdown_error=True,
                        )
                        model_strategy = "deepseek_markdown_paddle_layout_adapter_v1"
                    else:
                        model_sha256 = _write_markdown_model(
                            recovery_suite / "markdown-repeat-1" / f"{case_id}.md",
                            model_target,
                        )
                        model_strategy = (
                            "deepseek_full_page_no_paddle_layout_adapter_v1"
                        )
                else:
                    model_strategy = "retain_mineru_layout_replace_markdown"
                    model_path = (
                        candidate_suite
                        / "repeat-1"
                        / case_id
                        / "vlm"
                        / f"{case_id}_model.json"
                    )
                    model_sha256 = _sha256(model_path)
            elif recovery_model == "deepseek-ocr-2" and operational_failure_targets:
                model_sha256 = _write_markdown_model(
                    recovery_suite / "markdown-repeat-1" / f"{case_id}.md",
                    candidate_suite
                    / "repeat-1"
                    / case_id
                    / "vlm"
                    / f"{case_id}_model.json",
                )
                model_strategy = "deepseek_full_page_markdown_adapter_v1"
            baseline_case.update(
                {
                    "status": "completed",
                    "markdown_sha256": markdown_sha256,
                    "markdown_characters": int(recovery_case["markdown_characters"]),
                }
            )
            overlay.update(
                {
                    "candidate_applied": True,
                    "markdown_sha256": markdown_sha256,
                    "model_sha256": model_sha256,
                    "model_strategy": model_strategy,
                }
            )
            applied += 1
        elif (
            status == "failed"
            and operational_failure_targets
            and recovery_model == "deepseek-ocr-2"
            and recovery_case.get("error") == "empty_markdown"
            and paddle_layout_fallback_root is not None
        ):
            fallback = paddle_fallback_cases.get((recovery_worker, suite, case_id))
            if (
                fallback is None
                or fallback.get("status") != "failed"
                or fallback.get("error") != "empty_markdown"
            ):
                raise ValueError(
                    "DeepSeek empty-Markdown resolution requires a bound Paddle "
                    f"empty-Markdown response: {suite}/{case_id}"
                )
            response = (
                paddle_layout_fallback_root
                / f"worker-{recovery_worker:02d}"
                / suite
                / "repeat-1"
                / f"{case_id}.json"
            )
            if _sha256(response) != str(fallback["artifact_sha256"]):
                raise ValueError(f"Paddle empty-Markdown response mismatch: {case_id}")
            paddle_payload = _load(response)
            blocks = _paddle_text_blocks(paddle_payload)
            selected_blocks = (
                [block for block in blocks if block["label"] not in PADDLE_MARGINAL_LABELS]
                if suite == "parsebench"
                else blocks
            )
            semantic_empty_page = not selected_blocks
            markdown_path = candidate_suite / "markdown-repeat-1" / f"{case_id}.md"
            markdown_sha256 = _write_recovered_markdown(markdown_path, selected_blocks)
            model_path = (
                candidate_suite
                / "repeat-1"
                / case_id
                / "vlm"
                / f"{case_id}_model.json"
            )
            if suite == "parsebench":
                model_sha256 = _write_paddle_model(
                    response,
                    model_path,
                    permit_empty_markdown_error=True,
                    semantic_empty_page=semantic_empty_page,
                )
                model_strategy = (
                    "dual_model_semantic_empty_page_adapter_v1"
                    if semantic_empty_page
                    else "paddle_ignored_label_text_and_layout_adapter_v1"
                )
            elif semantic_empty_page:
                model_path.parent.mkdir(parents=True, exist_ok=True)
                _write(model_path, [[]])
                model_sha256 = _sha256(model_path)
                model_strategy = "dual_model_semantic_empty_page_adapter_v1"
            else:
                model_sha256 = _write_markdown_model(markdown_path, model_path)
                model_strategy = "paddle_text_deepseek_empty_adapter_v1"
            baseline_case.update(
                {
                    "status": "completed",
                    "markdown_sha256": markdown_sha256,
                    "markdown_characters": markdown_path.stat().st_size,
                    "semantic_empty_page": semantic_empty_page,
                    "empty_page_evidence": {
                        "deepseek_error": "empty_markdown",
                        "paddle_error": "empty_markdown",
                        "paddle_text_block_count": len(blocks),
                        "selected_text_block_count": len(selected_blocks),
                        "ground_truth_mounted": False,
                    },
                }
            )
            overlay.update(
                {
                    "candidate_applied": True,
                    "empty_markdown_failure_resolved": True,
                    "semantic_empty_page": semantic_empty_page,
                    "markdown_sha256": markdown_sha256,
                    "model_sha256": model_sha256,
                    "model_strategy": model_strategy,
                    "paddle_response_sha256": str(fallback["artifact_sha256"]),
                }
            )
            applied += 1
            empty_markdown_failures_resolved += 1
        elif status == "failed":
            inference_failed += 1
        else:
            raise ValueError(f"unsupported alternate status: {suite}/{case_id}/{status}")
        overlays.setdefault((primary, suite), []).append(overlay)
        summary[f"{recovery_model}_candidate_overlay"] = sorted(
            overlays[(primary, suite)], key=lambda item: str(item["case_id"])
        )
        summary["runs"][0]["completed"] = sum(
            item["status"] == "completed" for item in summary["runs"][0]["cases"]
        )
        summary["runs"][0]["failed"] = sum(
            item["status"] == "failed" for item in summary["runs"][0]["cases"]
        )
        _write(summary_path, summary)

    receipt: dict[str, Any] = {
        "schema": "folynta.alternate-recovery-candidate-overlay.v1",
        "recovery_model": recovery_model,
        "selective_plan_sha256": _sha256(selective_plan),
        "attempted": len(routes),
        "candidate_outputs_applied": applied,
        "inference_failed": inference_failed,
        "empty_markdown_failures_resolved": empty_markdown_failures_resolved,
        "final_acceptance_pending_official_evaluation": True,
        "operational_failure_targets": operational_failure_targets,
        "paddle_layout_fallback_bound": paddle_layout_fallback_root is not None,
        "strict_different_worker_plan": True,
        "composite_summaries": [
            {
                "primary_worker_index": worker,
                "benchmark_id": suite,
                "original_sha256": original_hashes[(worker, suite)],
                "candidate_sha256": _sha256(
                    output_root / f"worker-{worker:02d}" / suite / "run-summary.json"
                ),
            }
            for worker in range(4)
            for suite in SUITES
        ],
    }
    receipt_path = output_root / f"{recovery_model}-candidate-receipt.json"
    receipt["receipt_sha256"] = _write(receipt_path, receipt)
    return receipt


def _source(value: str) -> ResultSource:
    try:
        index, path = value.split("=", 1)
        return ResultSource(int(index), Path(path))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("result source must be INDEX=PATH") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="append", type=_source, required=True)
    parser.add_argument("--recovery-root", type=Path, required=True)
    parser.add_argument("--selective-plan", type=Path, required=True)
    parser.add_argument("--recovery-model", choices=ALTERNATE_MODELS, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--operational-failure-targets", action="store_true")
    parser.add_argument("--paddle-layout-fallback-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = apply_alternate_candidates(
        baseline_sources=tuple(args.baseline),
        recovery_root=args.recovery_root.resolve(),
        selective_plan=args.selective_plan.resolve(),
        recovery_model=args.recovery_model,
        output_root=args.output_root.resolve(),
        operational_failure_targets=args.operational_failure_targets,
        paddle_layout_fallback_root=(
            args.paddle_layout_fallback_root.resolve()
            if args.paddle_layout_fallback_root
            else None
        ),
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ALTERNATE_MODELS", "MODEL_IDENTITIES", "apply_alternate_candidates"]
