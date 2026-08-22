#!/usr/bin/env python3
"""Build the final evidence-bound report for the public recovery campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUITE_ORDER = ("parsebench", "omnidocbench", "olmocr-bench")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _relative(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp is not timezone-aware: {value}")
    return parsed.astimezone(UTC)


def _milestone(path: Path, repository: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = _load(path)
    observed = payload.get("completed_at_utc") or payload.get("created_at_utc")
    if not observed:
        return None
    return {
        "path": _relative(path, repository),
        "sha256": _sha256(path),
        "status": payload.get("status") or payload.get("schema"),
        "completed_at_utc": _timestamp(str(observed)).isoformat(),
    }


def _longest_observed_no_progress(path: Path) -> dict[str, Any]:
    last_counts: dict[int, int] = {}
    last_change: dict[int, datetime] = {}
    longest_seconds = 0.0
    longest_worker: int | None = None
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid progress JSONL at line {line_number}") from exc
        observed_at = _timestamp(str(payload["observed_at_utc"]))
        for worker in payload.get("workers", []):
            if "error" in worker:
                continue
            index = int(worker["worker_index"])
            count = sum(
                int(worker.get(field, 0))
                for field in (
                    "parsebench_directories",
                    "omnidocbench_directories",
                    "olmocr_bench_directories",
                )
            )
            if index not in last_counts:
                last_counts[index] = count
                last_change[index] = observed_at
            elif count != last_counts[index]:
                gap = (observed_at - last_change[index]).total_seconds()
                if gap > longest_seconds:
                    longest_seconds = gap
                    longest_worker = index
                last_counts[index] = count
                last_change[index] = observed_at
    return {
        "worker_index": longest_worker,
        "seconds": longest_seconds,
        "minutes": longest_seconds / 60,
    }


def _recovery_runtime_policy(
    *, repository: Path, primary_progress: Path
) -> dict[str, Any]:
    sources = {
        "operational_runner": (
            repository / "benchmark/runpod_eval/remote_run_operational_retry.sh"
        ),
        "quality_runner": (
            repository / "benchmark/runpod_eval/remote_run_mineru_quality_retry.sh"
        ),
        "operational_launcher": (
            repository / "benchmark/runpod_eval/launch_operational_retry_workers.py"
        ),
        "quality_launcher": (
            repository / "benchmark/runpod_eval/launch_mineru_quality_retry_workers.py"
        ),
        "full_worker": (
            repository
            / "infra/runpod/v6/bootstrap/run-mineru-3.4.4-public-core-worker.sh"
        ),
        "full_stall_guard": (
            repository / "benchmark/runpod_eval/remote_guard_stalled_public_core.sh"
        ),
        "full_stall_recovery": (
            repository / "benchmark/runpod_eval/remote_recover_stalled_public_core.sh"
        ),
    }
    # Each retry lane pins its own case timeout, and the operational lane was
    # lowered to 900 s once the live run measured a 144 s p99 and a 808 s longest
    # success. Read the pinned value instead of asserting one shared constant, so
    # the report states what each lane actually enforced.
    retry_timeouts: dict[str, int] = {}
    for name in ("operational_runner", "quality_runner"):
        text = sources[name].read_text(encoding="utf-8")
        timeout = re.search(r"--timeout-seconds (\d+)", text)
        if "--batch-size 1" not in text or timeout is None:
            raise ValueError(f"retry isolation policy is not pinned in {name}")
        retry_timeouts[name] = int(timeout.group(1))
    for name in ("operational_launcher", "quality_launcher"):
        if "2100 60 {result_root}" not in sources[name].read_text(encoding="utf-8"):
            raise ValueError(f"retry watchdog policy is not pinned in {name}")
    full_worker = sources["full_worker"].read_text(encoding="utf-8")
    if not all(
        marker in full_worker
        for marker in (
            'CASE_TIMEOUT_SECONDS="${CASE_TIMEOUT_SECONDS:-900}"',
            'BATCH_SIZE="${BATCH_SIZE:-1}"',
            "--resume-interrupted",
        )
    ):
        raise ValueError("full-corpus case-bounded resume policy is not pinned")
    full_guard = sources["full_stall_guard"].read_text(encoding="utf-8")
    full_recovery = sources["full_stall_recovery"].read_text(encoding="utf-8")
    if (
        'STALL_THRESHOLD_SECONDS="${STALL_THRESHOLD_SECONDS:-900}"'
        not in full_guard
        or "CASE_TIMEOUT_SECONDS=900" not in full_guard
        or "live_stall_detected_case_bounded_recovery" not in full_recovery
        or "live_stall_recovery_relaunched" not in full_recovery
    ):
        raise ValueError("full-corpus live stall recovery policy is not pinned")
    observed_gap = _longest_observed_no_progress(primary_progress)
    return {
        "batch_size_cases": 1,
        "per_case_timeout_seconds": retry_timeouts["operational_runner"],
        "per_case_timeout_seconds_by_lane": {
            "operational_retry": retry_timeouts["operational_runner"],
            "mineru_quality_retry": retry_timeouts["quality_runner"],
        },
        "stall_watchdog_seconds": 2100,
        "selection_basis": (
            "Live primary processing produced an inter-observation gap longer than "
            "the rejected 600-second retry timeout, so each case is isolated behind "
            "its own bounded timeout. The operational retry lane was tightened to "
            "900 seconds after the live run measured a 144-second p99 and a "
            "808-second longest success, which preserves every observed success "
            "while halving the wait on a true hang. The MinerU quality retry lane "
            "keeps the original 30-minute bound."
        ),
        "longest_observed_primary_no_new_directory": observed_gap,
        "primary_progress_path": _relative(primary_progress, repository),
        "primary_progress_sha256": _sha256(primary_progress),
        "live_primary_stall_recovery": {
            "stall_threshold_seconds": 900,
            "batch_size_cases_after_recovery": 1,
            "per_case_timeout_seconds_after_recovery": 900,
            "resume_completed_outputs": True,
            "scope": "parsebench, omnidocbench, and olmocr-bench",
        },
        "source_sha256": {name: _sha256(path) for name, path in sources.items()},
    }


def _aggregate_stage(
    *, repository: Path, comparison: str | None, rollback: bool
) -> dict[str, Any]:
    if not comparison:
        if rollback:
            raise ValueError("aggregate rollback has no comparison evidence")
        return {"status": "not_run", "rollback": False}
    path = Path(comparison).resolve()
    payload = _load(path)
    if payload.get("schema") != "folynta.aggregate-official-metric-comparison.v1":
        raise ValueError("aggregate official comparison identity is invalid")
    no_regression = payload.get("no_regression") is True
    if no_regression == rollback:
        raise ValueError("aggregate comparison and rollback decision disagree")
    return {
        "status": (
            "accepted_non_regressing"
            if no_regression
            else "rolled_back_aggregate_regression"
        ),
        "rollback": rollback,
        "no_regression": no_regression,
        "delta": payload["delta"],
        "path": _relative(path, repository),
        "sha256": _sha256(path),
    }


def _final_evaluation_root(repository: Path, failure_path: Path) -> Path:
    name = failure_path.name
    if name in {
        "folynta-mineru344-public-core-official-failures-r1-2026-08-04.json",
        "folynta-mineru344-public-failure-records-r1-2026-08-04.json",
    }:
        return (
            repository
            / "benchmark/reports/generated"
            / "folynta-mineru344-public-core-official-evaluations-r1-2026-08-04"
        )
    alternate = (
        repository
        / "benchmark/reports/generated"
        / "folynta-alternate-recovery-controller-2026-08-04"
    )
    if name == "deepseek-accepted-failures.json":
        return alternate / "deepseek-accepted-evaluation"
    if name == "paddle-accepted-failures.json":
        return alternate / "paddle-accepted-evaluation"
    if "post-mineru" in name:
        return (
            repository
            / "benchmark/reports/generated"
            / "folynta-mineru344-public-core-official-evaluations-post-mineru-r1-2026-08-04"
        )
    if "quality-candidate" in name:
        return (
            repository
            / "benchmark/reports/generated"
            / "folynta-mineru344-public-core-official-evaluations-quality-candidate-r1-2026-08-04"
        )
    raise ValueError(f"cannot bind final failure records to evaluation root: {failure_path}")


def _failure_cases(payload: dict[str, Any]) -> dict[str, set[str]]:
    result = {suite: set() for suite in SUITE_ORDER}
    for record in payload.get("records", []):
        suite = str(record["benchmark_id"])
        if suite not in result:
            raise ValueError(f"unexpected failure benchmark: {suite}")
        result[suite].add(str(record["case_id"]))
    return result


def _summary(root: Path, suite: str) -> dict[str, Any]:
    return _load(root / suite / "evaluation-summary.json")


def _official_metrics(root: Path) -> dict[str, Any]:
    parse = _summary(root, "parsebench")
    omni = _summary(root, "omnidocbench")
    olm = _summary(root, "olmocr-bench")
    omni_records = omni.get("records", [])
    if len(omni_records) != 1 or int(omni_records[0]["repeat_index"]) != 1:
        raise ValueError("full-corpus OmniDocBench evaluation must contain repeat 1 only")
    return {
        "parsebench_rule_failure_count": int(parse["rule_failure_count"]),
        "parsebench_groups": parse.get("groups", []),
        "omnidocbench_element_failure_count": int(
            omni_records[0]["official_failure_count"]
        ),
        "omnidocbench_metric_summary": omni_records[0].get("metric_summary", {}),
        "olmocr_overall_score": float(olm["overall_score"]),
        "olmocr_confidence_interval_95": olm.get("confidence_interval_95", []),
        "olmocr_rule_failure_count": int(olm["rule_failure_count"]),
        "evaluator_revisions": {
            "parsebench": str(parse["evaluator_revision"]),
            "omnidocbench": str(omni["evaluator_revision"]),
            "olmocr-bench": str(olm["evaluator_revision"]),
        },
    }


def _rate(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def _write_korean_final_markdown(
    *, report: dict[str, Any], output_markdown: Path
) -> None:
    scope = report["scope"]
    selection = report["selection"]
    cost = report["cost"]
    timing = report["timing"]
    lines = [
        "# FOLYNTA 전체 공개 벤치마크 장애 복구 최종 보고서",
        "",
        "## 결론",
        "",
        (
            f"공개 벤치마크 {int(scope['full_corpus_input_count']):,}건을 "
            "MinerU 3.4.4 VLM(c1)으로 전수 처리한 뒤, 운영 장애 재시도와 "
            "공식 평가 기반 선택 복구를 적용했습니다. 공식 지표가 개선된 문서만 "
            "채택하고 동일하거나 악화된 후보는 원본으로 되돌렸습니다."
        ),
        "",
        "## 벤치마크별 정확도 변화",
        "",
        (
            "| 벤치마크 | 입력 | 기준 무실패 문서 | 최종 무실패 문서 | "
            "절대 비율 상승 | 추가 통과 문서 |"
        ),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for suite in SUITE_ORDER:
        row = report["case_zero_official_failure_accuracy"][suite]
        lines.append(
            f"| {suite} | {int(row['input_count']):,} | "
            f"{int(row['baseline_cases_with_zero_official_failures']):,} | "
            f"{int(row['final_cases_with_zero_official_failures']):,} | "
            f"{float(row['absolute_rate_gain']):.6f} | "
            f"{int(row['additional_cases_cleared']):,} |"
        )
    lines += [
        "",
        "## 복구 모델 선택 및 롤백",
        "",
        f"- 선택 원칙: {selection['policy']}",
        (
            f"- PaddleOCR-VL: 경로 {int(selection['paddle_routed_case_count']):,}건, "
            f"채택 {int(selection['paddle_accepted_case_count']):,}건, "
            f"회귀 롤백 {int(selection['paddle_reverted_regression_case_count']):,}건"
        ),
        (
            f"- DeepSeek-OCR-2: 경로 {int(selection['deepseek_routed_case_count']):,}건, "
            f"채택 {int(selection['deepseek_accepted_case_count']):,}건, "
            f"회귀 롤백 {int(selection['deepseek_reverted_regression_case_count']):,}건"
        ),
        "",
        "## 공식 지표 변화",
        "",
        "```json",
        json.dumps(report["official_metrics"]["delta"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 장애 판별과 다른 Pod 재시도",
        "",
        "```json",
        json.dumps(report["operational_fault_detection"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 장애 복구 실행 정책",
        "",
        "```json",
        json.dumps(report["recovery_runtime_policy"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 3회 층화 표본 반복 검증",
        "",
        "```json",
        json.dumps(report["three_repeat_variance_audit"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 시간과 비용",
        "",
        f"- 전체 경과 시간: {float(timing['elapsed_hours_to_report']):.3f}시간",
        f"- RunPod 공급자 청구 합계: USD {float(cost['total_runtime_rate_estimate_usd']):.6f}",
        f"- 승인 비용 상한: USD {float(cost['approved_cap_usd']):.2f}",
        f"- 상한 준수: {bool(cost['within_approved_cap'])}",
        "",
        "## 증빙 파일과 SHA-256 연결",
        "",
    ]
    for role, value in report["evidence"].items():
        if role.endswith("_sha256"):
            continue
        digest = report["evidence"].get(f"{role}_sha256")
        if digest:
            lines.append(f"- `{role}`: `{value}` / `{digest}`")
    lines += [
        "",
        f"최종 보고서 내장 영수증: `{report['receipt_sha256']}`",
        "",
    ]
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def _validate_expansion_evidence(payload: dict[str, Any]) -> int:
    if payload.get("status") != "ready_identity_bound_and_smoke_passed":
        raise ValueError("MinerU retry expansion evidence is not ready")
    worker_count = int(payload.get("expansion_worker_count", -1))
    workers = payload.get("workers", [])
    if worker_count != 3 or len(workers) != worker_count:
        raise ValueError("MinerU retry expansion evidence does not bind three workers")
    if {int(worker["worker_index"]) for worker in workers} != {4, 5, 6}:
        raise ValueError("MinerU retry expansion worker indices are invalid")
    expected_manifest = str(payload["model_artifact_manifest_sha256"])
    for worker in workers:
        if str(worker["model_artifact_manifest_sha256"]) != expected_manifest:
            raise ValueError("MinerU retry expansion model identity mismatch")
        if int(worker.get("nonempty_smoke_markdown_count", 0)) < 1:
            raise ValueError("MinerU retry expansion smoke inference did not pass")
    return worker_count


def build_report(
    *,
    repository: Path,
    alternate_terminal_path: Path,
    audit_terminal_path: Path,
    detection_path: Path,
    cost_path: Path,
    output_json: Path,
    output_markdown: Path,
) -> dict[str, Any]:
    for output in (output_json, output_markdown):
        if output.exists():
            raise FileExistsError(f"final report already exists: {output}")

    alternate = _load(alternate_terminal_path)
    audit_terminal = _load(audit_terminal_path)
    detection = _load(detection_path)
    cost = _load(cost_path)
    if alternate.get("status") != "alternate_recovery_officially_selected":
        raise ValueError("alternate recovery is not officially selected")
    if audit_terminal.get("status") != "official_three_repeat_audit_complete":
        raise ValueError("three-repeat audit is not complete")
    if int(alternate.get("input_count", -1)) != 5132:
        raise ValueError("alternate recovery corpus coverage is invalid")
    if not bool(cost.get("within_approved_cap")):
        raise ValueError("RunPod cost cap was exceeded")
    controlled_faults = detection.get("controlled_fault_injection")
    retry_confirmation = detection.get("live_different_pod_retry_confirmation")
    if not isinstance(controlled_faults, dict) or not isinstance(
        retry_confirmation, dict
    ):
        raise ValueError("operational detection lacks independent fault evidence")
    if (
        float(controlled_faults.get("state_exact_accuracy", -1)) != 1.0
        or int(retry_confirmation.get("detected_case_count", -1))
        != int(retry_confirmation.get("different_pod_retry_completed", -1))
        + int(retry_confirmation.get("different_pod_retry_failed", -1))
    ):
        raise ValueError("operational detection evidence coverage is invalid")

    official_terminal_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-official-evaluation-controller-2026-08-04/terminal-receipt.json"
    )
    official_terminal = _load(official_terminal_path)
    baseline_failure_path = Path(str(official_terminal["failure_records"])).resolve()
    if not baseline_failure_path.is_relative_to(repository.resolve()):
        raise ValueError("baseline failure evidence escapes the repository")
    final_failure_path = Path(str(alternate["final_failure_records"])).resolve()
    baseline_failures = _load(baseline_failure_path)
    final_failures = _load(final_failure_path)
    if int(final_failures.get("record_count", -1)) != int(
        alternate["final_official_failure_record_count"]
    ):
        raise ValueError("final official failure count is not bound to terminal receipt")

    shard_plan_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-mineru344-public-core-4shard-plan-2026-08-04.json"
    )
    shard_plan = _load(shard_plan_path)
    suite_counts = {
        str(suite["benchmark_id"]): int(suite["input_count"])
        for suite in shard_plan["suites"]
    }
    if set(suite_counts) != set(SUITE_ORDER) or sum(suite_counts.values()) != 5132:
        raise ValueError("public suite coverage is invalid")

    baseline_cases = _failure_cases(baseline_failures)
    final_cases = _failure_cases(final_failures)
    case_accuracy: dict[str, Any] = {}
    for suite in SUITE_ORDER:
        total = suite_counts[suite]
        baseline_failed = len(baseline_cases[suite])
        final_failed = len(final_cases[suite])
        baseline_rate = _rate(total - baseline_failed, total)
        final_rate = _rate(total - final_failed, total)
        case_accuracy[suite] = {
            "input_count": total,
            "baseline_cases_with_zero_official_failures": total - baseline_failed,
            "final_cases_with_zero_official_failures": total - final_failed,
            "baseline_zero_official_failure_rate": baseline_rate,
            "final_zero_official_failure_rate": final_rate,
            "absolute_rate_gain": final_rate - baseline_rate,
            "additional_cases_cleared": baseline_failed - final_failed,
        }

    baseline_evaluation_root = (
        repository
        / "benchmark/reports/generated"
        / "folynta-mineru344-public-core-official-evaluations-r1-2026-08-04"
    )
    final_evaluation_root = _final_evaluation_root(repository, final_failure_path)
    terminal_final_evaluation = Path(str(alternate["final_evaluation_root"])).resolve()
    if terminal_final_evaluation != final_evaluation_root.resolve():
        raise ValueError("alternate terminal and final evaluation root disagree")
    baseline_metrics = _official_metrics(baseline_evaluation_root)
    final_metrics = _official_metrics(final_evaluation_root)
    metric_delta = {
        "parsebench_rule_failures_removed": (
            baseline_metrics["parsebench_rule_failure_count"]
            - final_metrics["parsebench_rule_failure_count"]
        ),
        "omnidocbench_element_failures_removed": (
            baseline_metrics["omnidocbench_element_failure_count"]
            - final_metrics["omnidocbench_element_failure_count"]
        ),
        "olmocr_overall_score_gain": (
            final_metrics["olmocr_overall_score"]
            - baseline_metrics["olmocr_overall_score"]
        ),
        "olmocr_rule_failures_removed": (
            baseline_metrics["olmocr_rule_failure_count"]
            - final_metrics["olmocr_rule_failure_count"]
        ),
        "official_failure_records_removed": (
            int(baseline_failures["record_count"])
            - int(final_failures["record_count"])
        ),
    }
    if (
        any(
            int(metric_delta[key]) < 0
            for key in (
                "parsebench_rule_failures_removed",
                "omnidocbench_element_failures_removed",
                "olmocr_rule_failures_removed",
                "official_failure_records_removed",
            )
        )
        or float(metric_delta["olmocr_overall_score_gain"]) < -1e-12
        or any(int(item["additional_cases_cleared"]) < 0 for item in case_accuracy.values())
    ):
        raise ValueError("final official evaluation regresses from the MinerU baseline")

    audit_summary_path = Path(str(audit_terminal["summary"])).resolve()
    audit_summary = _load(audit_summary_path)
    operational_plan_path = (
        repository
        / "benchmark/datasets/private/runpod-2026-08-04"
        / "operational-retry-staging/retry-plan-receipt.json"
    )
    worker_health_path = (
        repository
        / "benchmark/reports/generated"
        / "runpod-operational-retry-controller-2026-08-04"
        / "operational-worker-health.json"
    )
    operational_plan = _load(operational_plan_path)
    worker_health = _load(worker_health_path)
    prefetch_terminal_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-operational-retry-prefetch-controller-2026-08-04"
        / "terminal-receipt.json"
    )
    prefetch_launch_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-operational-retry-prefetch-launch-2026-08-04.json"
    )
    prefetch_incident_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-operational-prefetch-incident-evidence-2026-08-04"
        / "incident-receipt.json"
    )
    prefetch_terminal = _load(prefetch_terminal_path)
    prefetch_launch = _load(prefetch_launch_path)
    prefetch_incidents = _load(prefetch_incident_path)
    if (
        prefetch_terminal.get("schema")
        != "folynta.operational-retry-prefetch-terminal.v1"
        or prefetch_terminal.get("status")
        != "launched_before_full_baseline_completion"
        or int(prefetch_terminal.get("input_count", -1)) != 1788
        or list(prefetch_terminal.get("primary_worker_scope", [])) != [1, 2]
        or prefetch_launch.get("schema") != "folynta.operational-retry-launch.v1"
        or int(prefetch_launch.get("input_count", -1)) != 1788
        or int(prefetch_launch.get("worker_count", -1)) != 3
    ):
        raise ValueError("operational retry prefetch evidence is invalid")
    incident_observations = prefetch_incidents.get(
        "corrected_worker_observations", []
    )
    if (
        prefetch_incidents.get("schema")
        != "folynta.operational-prefetch-incident-evidence.v1"
        or prefetch_incidents.get("secret_free") is not True
        or len(prefetch_incidents.get("incidents", [])) != 3
        or len(incident_observations) != 3
        or sum(
            int(item.get("corrected_run_model_artifact_count", 0))
            for item in incident_observations
        )
        < 1
        or any(
            int(item.get("corrected_runner_process_count", 0)) < 1
            for item in incident_observations
        )
        or str(prefetch_incidents["corrected_launch_receipt"]["sha256"])
        != _sha256(prefetch_launch_path)
    ):
        raise ValueError("operational prefetch incident evidence is invalid")
    post_terminal_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-post-mineru-selection-controller-2026-08-04/terminal-receipt.json"
    )
    post_terminal = _load(post_terminal_path)
    aggregate_metric_safety = {
        "mineru_quality_retry": _aggregate_stage(
            repository=repository,
            comparison=str(post_terminal["aggregate_metric_comparison"]),
            rollback=bool(post_terminal["aggregate_metric_rollback"]),
        ),
        "paddleocr_vl": _aggregate_stage(
            repository=repository,
            comparison=alternate.get("paddle_aggregate_metric_comparison"),
            rollback=bool(alternate.get("paddle_aggregate_metric_rollback")),
        ),
        "deepseek_ocr2": _aggregate_stage(
            repository=repository,
            comparison=alternate.get("deepseek_aggregate_metric_comparison"),
            rollback=bool(alternate.get("deepseek_aggregate_metric_rollback")),
        ),
    }
    aggregate_evidence: dict[str, str] = {}
    for stage_name, stage in aggregate_metric_safety.items():
        if "path" in stage:
            aggregate_evidence[f"{stage_name}_aggregate_comparison"] = str(
                stage["path"]
            )
            aggregate_evidence[f"{stage_name}_aggregate_comparison_sha256"] = str(
                stage["sha256"]
            )
    paddle_terminal = (
        repository
        / "benchmark/reports/generated"
        / "folynta-paddle-recovery-bootstrap-2026-08-04/terminal-receipt.json"
    )
    deepseek_terminal = (
        repository
        / "benchmark/reports/generated"
        / "folynta-deepseek-recovery-bootstrap-2026-08-04/terminal-receipt.json"
    )
    hardware_receipt = (
        repository
        / "benchmark/reports/generated"
        / "runpod-live-worker1-parse-2026-08-04/run-summary.json"
    )
    auxiliary_straggler_marker = (
        repository
        / "benchmark/reports/generated"
        / "runpod-live-worker1-parse-2026-08-04/straggler-case-id.txt"
    )
    hardware_environment = _load(hardware_receipt)["environment"]
    observed_hourly_rates = sorted(
        {float(pod["hourly_rate_usd"]) for pod in cost.get("pods", [])}
    )
    campaign_inventory = _load(
        repository
        / "benchmark/reports/generated"
        / "folynta-runpod-all-pod-inventory-live-r1-2026-08-04.json"
    )
    cleanup_receipt_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-runpod-campaign-cleanup-2026-08-04/pod-deletion-receipt.json"
    )
    registry_evidence_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-runpod-campaign-pod-registry-final-2026-08-05.json"
    )
    phase_cost_cleanup_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-phase-cost-cleanup-2026-08-05/terminal-receipt.json"
    )
    obsolete_pod_cleanup_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-obsolete-pod-cleanup-2026-08-05/pod-deletion-receipt.json"
    )
    cleanup_receipt = _load(cleanup_receipt_path)
    registry_evidence = _load(registry_evidence_path)
    phase_cost_cleanup = _load(phase_cost_cleanup_path)
    obsolete_pod_cleanup = _load(obsolete_pod_cleanup_path)
    if (
        cleanup_receipt.get("all_provider_absent") is not True
        or int(cleanup_receipt.get("provider_prefix_remaining_count", -1)) != 0
        or registry_evidence.get("schema")
        != "folynta.runpod-campaign-pod-registry.v1"
        or int(cleanup_receipt.get("registry_pod_count", -1))
        != int(registry_evidence.get("pod_count", -2))
        or phase_cost_cleanup.get("status")
        != "phase_pods_stopped_after_verified_evidence"
        or int(phase_cost_cleanup.get("stopped_pod_count", -1)) != 5
        or obsolete_pod_cleanup.get("status")
        != "obsolete_replaced_pods_deleted_and_absent_verified"
        or int(obsolete_pod_cleanup.get("pod_count", -1)) != 2
        or not all(
            pod.get("provider_absent_verified") is True
            for pod in obsolete_pod_cleanup.get("pods", [])
        )
    ):
        raise ValueError(
            "RunPod phase stop, cleanup, or campaign registry evidence is invalid"
        )
    expansion_evidence_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-mineru-operational-retry-expansion-evidence-2026-08-04.json"
    )
    expansion_evidence = _load(expansion_evidence_path)
    verified_expansion_worker_count = _validate_expansion_evidence(
        expansion_evidence
    )
    controlled_fault_evidence_path = (
        repository
        / "benchmark/reports/generated"
        / "folynta-operational-fault-injection-evaluation-2026-08-04.json"
    )
    if _sha256(controlled_fault_evidence_path) != str(
        controlled_faults["evidence_sha256"]
    ):
        raise ValueError("controlled fault evidence hash is not bound to detection")
    operational_retry_plan = _load(
        repository
        / "benchmark/datasets/private/runpod-2026-08-04"
        / "operational-retry-staging/retry-plan-receipt.json"
    )
    expansion_pod_count = sum(
        str(pod.get("role", "")).startswith("mineru-operational-retry-worker-")
        for pod in campaign_inventory["pods"]
    )
    if expansion_pod_count != verified_expansion_worker_count:
        raise ValueError("campaign inventory and retry expansion evidence disagree")
    report_created_at = datetime.now(UTC)
    campaign_started_at = min(
        _timestamp(str(pod["last_started_at_utc"])) for pod in cost["pods"]
    )
    milestone_paths = {
        "primary_baseline_collected": (
            repository
            / "benchmark/reports/generated/runpod-public-core-live-monitor-2026-08-04"
            / "terminal-receipt.json"
        ),
        "operational_retry_merged": (
            repository
            / "benchmark/reports/generated/runpod-operational-retry-monitor-2026-08-04"
            / "terminal-receipt.json"
        ),
        "operational_retry_prefetch_launched": prefetch_terminal_path,
        "baseline_official_evaluation": (
            repository
            / "benchmark/reports/generated/folynta-official-evaluation-controller-2026-08-04"
            / "terminal-receipt.json"
        ),
        "mineru_quality_retry": (
            repository
            / "benchmark/reports/generated/folynta-mineru-quality-retry-monitor-2026-08-04"
            / "terminal-receipt.json"
        ),
        "mineru_quality_selection": (
            repository
            / "benchmark/reports/generated/folynta-mineru-quality-candidate-controller-2026-08-04"
            / "terminal-receipt.json"
        ),
        "alternate_recovery_selection": alternate_terminal_path,
        "three_repeat_audit": audit_terminal_path,
        "operational_detection_evaluation": detection_path,
    }
    milestones = {
        name: milestone
        for name, path in milestone_paths.items()
        if (milestone := _milestone(path, repository)) is not None
    }
    primary_progress_path = (
        repository
        / "benchmark/reports/generated/runpod-public-core-live-monitor-2026-08-04"
        / "progress.jsonl"
    )
    recovery_runtime_policy = _recovery_runtime_policy(
        repository=repository, primary_progress=primary_progress_path
    )

    report: dict[str, Any] = {
        "schema": "folynta.public-benchmark-recovery-final-report.v1",
        "status": "complete_and_officially_verified",
        "created_at_utc": report_created_at.isoformat(),
        "scope": {
            "full_corpus_input_count": 5132,
            "full_corpus_repeat_count": 1,
            "stratified_audit_input_count_per_suite": 128,
            "stratified_audit_repeat_count": 3,
            "stratified_audit_inference_count": 1152,
            "suite_input_counts": suite_counts,
        },
        "models": {
            "baseline": "MinerU 3.4.4 VLM(c1)",
            "operational_retry": "MinerU 3.4.4 VLM(c1) on a different eligible Pod",
            "quality_retry": "MinerU 3.4.4 VLM quality retry",
            "alternate_recovery": ["PaddleOCR-VL-1.6", "DeepSeek-OCR-2"],
            "artifact_identity_policy": (
                "immutable model revision plus primary model bytes; mutable "
                "Hugging Face .cache metadata excluded"
            ),
            "paddle_runtime": _load(paddle_terminal)["runtime_identity"],
            "deepseek_runtime": _load(deepseek_terminal)["runtime_identity"],
        },
        "compute_configuration": {
            "gpu": hardware_environment["gpu"],
            "pod_topology": {
                "mineru_shard_pods": 4,
                "mineru_operational_retry_expansion_pods": expansion_pod_count,
                "mineru_operational_retry_eligible_pods": len(
                    operational_retry_plan["eligible_retry_workers"]
                ),
                "expanded_mineru_stages": [
                    "different-pod operational retry",
                    "MinerU official-quality retry",
                    "three-repeat stratified audit",
                ],
                "quarantined_primary_shard_pods": len(
                    operational_retry_plan["quarantined_worker_indices"]
                ),
                "selective_recovery_pods": 2,
                "total_campaign_pods": int(
                    cost.get("registry_pod_count", campaign_inventory["pod_count"])
                ),
                "parallelism_unit": "independent document",
                "shared_gpu_memory_required": False,
            },
            "observed_hourly_rates_usd": observed_hourly_rates,
            "selection_rationale": (
                "All pinned runtimes fit and execute on one 24 GB RTX 4090 while "
                "document-level sharding provides horizontal throughput. The frozen "
                "four-Pod primary design was preserved while three byte-identical "
                "retry-only Pods were added to reduce recovery wall time; larger-memory "
                "data-center GPUs are not required by this campaign"
            ),
            "suitability_boundary": (
                "Re-evaluate RTX 5090 or 48-80 GB data-center GPUs when a pinned model "
                "exceeds 24 GB, batching becomes the primary bottleneck, or minimum wall "
                "time outweighs cost and homogeneous-hardware evidence"
            ),
        },
        "selection": {
            "policy": (
                "accept only cases with fewer official failures, no new failure codes, "
                "and no escalation; revert unchanged or regressed candidates"
            ),
            "paddle_routed_case_count": int(alternate["paddle_routed_case_count"]),
            "paddle_accepted_case_count": int(alternate["paddle_accepted_case_count"]),
            "paddle_reverted_regression_case_count": int(
                alternate["paddle_reverted_regression_case_count"]
            ),
            "deepseek_routed_case_count": int(alternate["deepseek_routed_case_count"]),
            "deepseek_accepted_case_count": int(alternate["deepseek_accepted_case_count"]),
            "deepseek_reverted_regression_case_count": int(
                alternate["deepseek_reverted_regression_case_count"]
            ),
            "aggregate_metric_safety": aggregate_metric_safety,
        },
        "case_zero_official_failure_accuracy": case_accuracy,
        "official_metrics": {
            "baseline": baseline_metrics,
            "final": final_metrics,
            "delta": metric_delta,
        },
        "operational_fault_detection": detection,
        "evidence_quality_notes": {
            "auxiliary_straggler_marker_line_ending": {
                "finding": (
                    "The worker-1 ParseBench auxiliary straggler case-id marker ends "
                    "with a literal 'n' instead of a newline."
                ),
                "impact": "none_on_quarantine_or_retry_routing",
                "reason": (
                    "Worker quarantine is derived from repeated suite_stall_detected "
                    "records in stall-watchdog.jsonl; the auxiliary marker is not a "
                    "classification or routing input."
                ),
                "raw_evidence_preserved": True,
            },
            "live_prefetch_launch_incidents": {
                "incident_count": len(prefetch_incidents["incidents"]),
                "codes": [
                    str(item["code"]) for item in prefetch_incidents["incidents"]
                ],
                "corrected_runner_count": sum(
                    int(item["corrected_runner_process_count"])
                    for item in incident_observations
                ),
                "corrected_model_artifacts_at_evidence_capture": sum(
                    int(item["corrected_run_model_artifact_count"])
                    for item in incident_observations
                ),
                "raw_evidence_preserved": True,
            },
        },
        "operational_retry": {
            "retry_case_count": int(operational_plan["failed_input_count"]),
            "same_worker_retry_count": sum(
                int(item["primary_worker_index"]) == int(item["retry_worker_index"])
                for item in operational_plan.get("failures", [])
            ),
            "worker_health": worker_health,
            "prefetch": {
                "primary_worker_scope": list(
                    prefetch_terminal["primary_worker_scope"]
                ),
                "retry_worker_indices": list(
                    prefetch_terminal["retry_worker_indices"]
                ),
                "input_count": int(prefetch_terminal["input_count"]),
                "launched_before_full_baseline_completion": True,
            },
        },
        "recovery_runtime_policy": recovery_runtime_policy,
        "three_repeat_variance_audit": audit_summary,
        "timing": {
            "measurement_boundary": (
                "earliest campaign billing boundary through provider-verified resource "
                "cleanup and final report creation"
            ),
            "campaign_started_at_utc": campaign_started_at.isoformat(),
            "report_created_at_utc": report_created_at.isoformat(),
            "elapsed_seconds_to_report": (
                report_created_at - campaign_started_at
            ).total_seconds(),
            "elapsed_hours_to_report": (
                report_created_at - campaign_started_at
            ).total_seconds()
            / 3600,
            "milestones": milestones,
        },
        "cost": cost,
        "evidence": {
            "baseline_failure_records": _relative(baseline_failure_path, repository),
            "baseline_failure_records_sha256": _sha256(baseline_failure_path),
            "final_failure_records": _relative(final_failure_path, repository),
            "final_failure_records_sha256": _sha256(final_failure_path),
            "baseline_evaluation_root": _relative(baseline_evaluation_root, repository),
            "final_evaluation_root": _relative(final_evaluation_root, repository),
            "alternate_terminal": _relative(alternate_terminal_path, repository),
            "alternate_terminal_sha256": _sha256(alternate_terminal_path),
            "audit_summary": _relative(audit_summary_path, repository),
            "audit_summary_sha256": _sha256(audit_summary_path),
            "detection_report": _relative(detection_path, repository),
            "detection_report_sha256": _sha256(detection_path),
            "controlled_fault_injection": _relative(
                controlled_fault_evidence_path, repository
            ),
            "controlled_fault_injection_sha256": _sha256(
                controlled_fault_evidence_path
            ),
            "operational_retry_prefetch_terminal": _relative(
                prefetch_terminal_path, repository
            ),
            "operational_retry_prefetch_terminal_sha256": _sha256(
                prefetch_terminal_path
            ),
            "operational_retry_prefetch_launch": _relative(
                prefetch_launch_path, repository
            ),
            "operational_retry_prefetch_launch_sha256": _sha256(
                prefetch_launch_path
            ),
            "operational_prefetch_incidents": _relative(
                prefetch_incident_path, repository
            ),
            "operational_prefetch_incidents_sha256": _sha256(
                prefetch_incident_path
            ),
            "primary_progress_timeline": _relative(
                primary_progress_path, repository
            ),
            "primary_progress_timeline_sha256": _sha256(primary_progress_path),
            "cost_snapshot": _relative(cost_path, repository),
            "cost_snapshot_sha256": _sha256(cost_path),
            "runpod_cleanup_receipt": _relative(cleanup_receipt_path, repository),
            "runpod_cleanup_receipt_sha256": _sha256(cleanup_receipt_path),
            "runpod_campaign_registry": _relative(registry_evidence_path, repository),
            "runpod_campaign_registry_sha256": _sha256(registry_evidence_path),
            "phase_cost_cleanup_receipt": _relative(
                phase_cost_cleanup_path, repository
            ),
            "phase_cost_cleanup_receipt_sha256": _sha256(
                phase_cost_cleanup_path
            ),
            "obsolete_pod_cleanup_receipt": _relative(
                obsolete_pod_cleanup_path, repository
            ),
            "obsolete_pod_cleanup_receipt_sha256": _sha256(
                obsolete_pod_cleanup_path
            ),
            "hardware_execution_receipt": _relative(hardware_receipt, repository),
            "hardware_execution_receipt_sha256": _sha256(hardware_receipt),
            "mineru_retry_expansion_evidence": _relative(
                expansion_evidence_path, repository
            ),
            "mineru_retry_expansion_evidence_sha256": _sha256(
                expansion_evidence_path
            ),
            "auxiliary_straggler_marker": _relative(
                auxiliary_straggler_marker, repository
            ),
            "auxiliary_straggler_marker_sha256": _sha256(auxiliary_straggler_marker),
            **aggregate_evidence,
        },
    }
    encoded = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    report["receipt_sha256"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _write_korean_final_markdown(report=report, output_markdown=output_markdown)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--alternate-terminal", type=Path, required=True)
    parser.add_argument("--audit-terminal", type=Path, required=True)
    parser.add_argument("--detection-report", type=Path, required=True)
    parser.add_argument("--cost-snapshot", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        repository=args.repository_root.resolve(),
        alternate_terminal_path=args.alternate_terminal.resolve(),
        audit_terminal_path=args.audit_terminal.resolve(),
        detection_path=args.detection_report.resolve(),
        cost_path=args.cost_snapshot.resolve(),
        output_json=args.output_json.resolve(),
        output_markdown=args.output_markdown.resolve(),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "receipt_sha256": report["receipt_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_report"]
