#!/usr/bin/env python3
"""Build a patent-review-oriented technical evidence index for the campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluate_service_recovery_equivalence import SERVICE_SOURCE_PATHS

ALGORITHM_SOURCES = (
    "benchmark/runpod_eval/classify_operational_worker_health.py",
    "benchmark/runpod_eval/evaluate_operational_fault_injection.py",
    "benchmark/runpod_eval/evaluate_operational_detection.py",
    "benchmark/runpod_eval/evaluate_parsebench_official.py",
    "benchmark/runpod_eval/parsebench_evaluator_watchdog.py",
    "benchmark/runpod_eval/plan_operational_retries.py",
    "benchmark/runpod_eval/package_operational_retry_inputs.py",
    "benchmark/runpod_eval/launch_operational_retry_workers.py",
    "benchmark/runpod_eval/collect_operational_retry_worker.py",
    "benchmark/runpod_eval/remote_run_operational_retry.sh",
    "benchmark/runpod_eval/remote_stall_watchdog.sh",
    "benchmark/runpod_eval/remote_guard_stalled_public_core.sh",
    "benchmark/runpod_eval/remote_recover_stalled_public_core.sh",
    "infra/runpod/v6/bootstrap/run-mineru-3.4.4-public-core-worker.sh",
    "benchmark/runpod_eval/apply_operational_retries.py",
    "benchmark/runpod_eval/stage_selective_recovery.py",
    "benchmark/runpod_eval/package_selective_recovery_inputs.py",
    "benchmark/runpod_eval/launch_mineru_quality_retry_workers.py",
    "benchmark/runpod_eval/collect_mineru_quality_retry_worker.py",
    "benchmark/runpod_eval/remote_run_mineru_quality_retry.sh",
    "benchmark/runpod_eval/apply_mineru_quality_candidates.py",
    "benchmark/runpod_eval/compare_official_failure_records.py",
    "benchmark/runpod_eval/compare_official_evaluation_metrics.py",
    "benchmark/runpod_eval/apply_accepted_quality_candidates.py",
    "benchmark/runpod_eval/apply_alternate_candidates.py",
    "benchmark/runpod_eval/apply_accepted_alternate_candidates.py",
    "benchmark/runpod_eval/paddleocr_vl_stage2.py",
    "benchmark/runpod_eval/deepseek_ocr2_stage2.py",
    "benchmark/runpod_eval/launch_dedicated_recovery.py",
    "benchmark/runpod_eval/collect_dedicated_recovery.py",
    "benchmark/runpod_eval/remote_run_dedicated_recovery.sh",
    "benchmark/runpod_eval/run_stratified_audit_campaign.py",
    "benchmark/runpod_eval/summarize_stratified_audit_official.py",
    "benchmark/runpod_eval/evaluate_service_recovery_equivalence.py",
    "benchmark/runpod_eval/test_evaluate_service_recovery_equivalence.py",
    "tools/release/start_folynta_operational_retry_prefetch.ps1",
    "tools/release/collect_folynta_operational_prefetch_incidents.ps1",
    "tools/release/continue_folynta_operational_retries.ps1",
    "tools/release/continue_folynta_official_evaluations.ps1",
    "tools/release/monitor_folynta_live_campaign.py",
    "tools/release/monitor_folynta_runpod_credit.py",
    "tools/release/continue_folynta_post_baseline_mineru_pool.ps1",
    "tools/release/continue_folynta_post_selection_recovery_and_audit.ps1",
    "tools/release/snapshot_folynta_runpod_billing.ps1",
    "tools/release/cleanup_folynta_runpod_resources.ps1",
    "tools/release/continue_folynta_phase_cost_cleanup.ps1",
    # The official evaluator drivers and the recovery-taxonomy adapter produce
    # every metric this index cites, so they are fingerprinted alongside the
    # orchestration they are called from.
    "benchmark/runpod_eval/evaluate_omnidoc_repeats.py",
    "benchmark/runpod_eval/evaluate_olmocr_official.py",
    "benchmark/runpod_eval/build_public_failure_records.py",
    "benchmark/runpod_eval/summarize_failure_records.py",
    "benchmark/runpod_eval/select_highest_impact_failures.py",
    "benchmark/runpod_eval/capture_omnidoc_frozen_artifacts.py",
    "benchmark/v6/public_failure_adapter.py",
    "tools/release/continue_folynta_alternate_recovery.ps1",
    "tools/release/continue_folynta_detection_evaluation.ps1",
    "tools/release/provision_folynta_mineru_recovery_worker.ps1",
    "tools/release/record_folynta_execution_decision.py",
    "tools/release/render_folynta_portable_report.mjs",
    *SERVICE_SOURCE_PATHS,
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _fingerprint(repository: Path, relative: str) -> dict[str, Any]:
    path = repository / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _technical_effects() -> list[dict[str, str]]:
    return [
        {
            "technical_effect": "운영 장애와 문서 단위 실패를 분리 판정",
            "measurement": "실제 장애 상태 정확도, 오탐·미탐, 재시도 결과의 회복률",
            "report_pointer": "operational_fault_detection",
            "primary_evidence_role": "detection_report",
        },
        {
            "technical_effect": "장애 작업자를 배제한 다른 Pod 재처리",
            "measurement": "재시도 건수, 동일 작업자 재시도 0건, 복구 완료율",
            "report_pointer": "operational_retry",
            "primary_evidence_role": "detection_report",
        },
        {
            "technical_effect": "단일 장문 문서 정체의 격리와 연속 처리",
            "measurement": "건별 1,800초 제한, 반환 코드 124, 다음 배치 전환 시간",
            "report_pointer": "recovery_runtime_policy; operational_retry batch records",
            "primary_evidence_role": "timing.milestones.operational_retry_merged",
        },
        {
            "technical_effect": "전체 처리 무출력 감지 후 완료 결과 보존 재개",
            "measurement": "15분 정체 임계값, 보존 문서 수, 문서 단위 재시도",
            "report_pointer": "recovery_runtime_policy.live_primary_stall_recovery",
            "primary_evidence_role": "primary_progress_timeline",
        },
        {
            "technical_effect": "완료 이전 단계의 실행 병목 복구",
            "measurement": "실행 처리 건수, 다른 Pod 경로와 실행 장애 교정 이력",
            "report_pointer": "operational_retry.prefetch",
            "primary_evidence_role": "operational_prefetch_incidents",
        },
        {
            "technical_effect": "선택적 이종 모델 복구로 공식 정확도 개선",
            "measurement": "기준 대비 최종 무실패 비율과 공식 지표 변화",
            "report_pointer": "case_zero_official_failure_accuracy; official_metrics.delta",
            "primary_evidence_role": "final_failure_records",
        },
        {
            "technical_effect": "성능 퇴행 후보의 fail-closed 거부",
            "measurement": "모델별 채택 건수와 회귀로 되돌린 건수",
            "report_pointer": "selection",
            "primary_evidence_role": "alternate_terminal",
        },
        {
            "technical_effect": "집계 공식 지표 퇴행 시 단계 전체 롤백",
            "measurement": "실패 수 변화와 olmOCR 전체 점수 변화",
            "report_pointer": "selection.aggregate_metric_safety",
            "primary_evidence_role": "mineru_quality_retry_aggregate_comparison",
        },
        {
            "technical_effect": "계층화 표본에서 복구 재현성 검증",
            "measurement": "3회 출력·지표·실패 판정·지연시간 분산",
            "report_pointer": "three_repeat_variance_audit",
            "primary_evidence_role": "audit_summary",
        },
        {
            "technical_effect": "승인된 컴퓨팅 비용 상한 준수",
            "measurement": "RunPod 청구 API 기록과 승인 상한 비교",
            "report_pointer": "cost",
            "primary_evidence_role": "cost_snapshot",
        },
        {
            "technical_effect": "단계 완료 증빙과 연동된 GPU 자원 자동 정지",
            "measurement": "선택 복구 및 3회 감사 완료 시점부터 최종 삭제까지 절감된 유휴 GPU 시간",
            "report_pointer": "cost; phase_cost_cleanup",
            "primary_evidence_role": "phase_cost_cleanup_receipt",
        },
        {
            "technical_effect": "장애 증빙 보존 후 교체된 GPU 자원의 조기 제거",
            "measurement": "로컬 장애 증빙 해시와 연결된 교체 Pod 삭제 및 공급자 404 확인",
            "report_pointer": "evidence.obsolete_pod_cleanup_receipt",
            "primary_evidence_role": "obsolete_pod_cleanup_receipt",
        },
        {
            "technical_effect": "증빙 수집 후 모든 캠페인 클라우드 자원 삭제",
            "measurement": "Pod별 404 확인과 잔존 FOLYNTA Pod 0건",
            "report_pointer": "evidence.runpod_cleanup_receipt",
            "primary_evidence_role": "runpod_cleanup_receipt",
        },
        {
            "technical_effect": "벤치마크 복구 정책과 서비스 제어면의 구현 동등성",
            "measurement": (
                "서비스 장애 주입 상태 정확도, 격리 정확도, 영향 shard 재생 범위, "
                "통합 테스트 수"
            ),
            "report_pointer": "service_recovery_equivalence",
            "primary_evidence_role": "service_recovery_equivalence",
        },
        {
            "technical_effect": "동일 모델 재시도에서 이종 모델 승격으로 이어지는 다단 복구의 수렴",
            "measurement": (
                "라운드별 복구율과 잔여 건수, 2라운드 이상을 요구한 건수, "
                "이종 모델이 최종 해결한 건수"
            ),
            "report_pointer": "campaign_completion_ledger.recovery_outcome",
            "primary_evidence_role": "campaign_completion_ledger",
        },
        {
            "technical_effect": "복구 대상 선정의 누락 없음",
            "measurement": (
                "재시도 계획에 포함되지 않은 채 미해결로 남은 건수, "
                "시도 후 미복구 건수와 개별 추적 정보"
            ),
            "report_pointer": "campaign_completion_ledger.recovery_outcome",
            "primary_evidence_role": "campaign_completion_ledger",
        },
        {
            "technical_effect": "복구 레인이 공식 정확도에 기여한 크기의 단일 변수 측정",
            "measurement": (
                "모델·평가기 리비전·코퍼스·설정을 고정하고 복구 산출물만 제거했을 때의 "
                "공식 점수 차이와 신뢰구간 중첩 여부"
            ),
            "report_pointer": "recovery_accuracy_counterfactual",
            "primary_evidence_role": "recovery_accuracy_counterfactual",
        },
        {
            "technical_effect": "동일 입력에 대한 지식 아키텍처 계획의 재현성",
            "measurement": "청사진별 반복 실행 시 계획 해시 동일성과 청사진 간 계획 상이성",
            "report_pointer": "knowledge_compilation_properties.architecture_determinism",
            "primary_evidence_role": "knowledge_compilation_properties",
        },
        {
            "technical_effect": "미해결 링크를 포함한 산출물의 생성 차단",
            "measurement": (
                "컴파일 거부 건수와 사유 분류, 산출된 vault 내 미해결 링크 수"
            ),
            "report_pointer": "knowledge_compilation_properties.vault_compilation",
            "primary_evidence_role": "knowledge_compilation_properties",
        },
        {
            "technical_effect": "기존 사용자 자료에 병합할 때의 무손실 보장",
            "measurement": (
                "정책별 충돌 탐지 건수, 충돌 없이 사라지거나 덮어써진 기존 파일 수, "
                "이름 변경 정책의 출력 파일 수 항등식"
            ),
            "report_pointer": "knowledge_compilation_properties.merge_safety",
            "primary_evidence_role": "knowledge_compilation_properties",
        },
    ]


def _alternatives_evaluated() -> list[dict[str, Any]]:
    """Approaches that were built and measured, and did not work.

    A specification that records only what succeeded overstates how obvious the
    working mechanism was. These were implemented, run on the same corpus, and
    rejected on their own measurements.
    """
    return [
        {
            "approach": "정답지 없이 예측물만으로 재처리 대상 문서를 선별",
            "implementation": "benchmark/runpod_eval/evaluate_blind_quality_detection.py",
            "signals": (
                "빈 출력, 반복 퇴화, 표 구조 붕괴, 벤치마크 내 길이 이탈, 문자 구성 이상"
            ),
            "outcome": "기각",
            "why": (
                "선별 결과가 무작위 선택보다 낮은 실패 질량을 회수했고, 예측 길이만으로 "
                "정렬하는 무탐지 기준선이 모든 예산 구간에서 더 높았다. 실패 질량이 "
                "문서 규모와 교락되어 있어, 결함을 고르는 일이 규모를 배제하는 방향으로 "
                "작동한다."
            ),
            "report_pointer": "blind_quality_detection.outcome",
            "primary_evidence_role": "blind_quality_detection",
        },
    ]


def _benchmark_scope() -> dict[str, dict[str, Any]]:
    return {
        "parsebench": {
            "input_count": 2078,
            "focus": "문서 파싱 충실도, 표·읽기 순서·시간 근거 및 데이터 파이프라인 실용성",
            "official_source": "https://github.com/run-llama/ParseBench",
        },
        "omnidocbench": {
            "input_count": 1651,
            "focus": "문서·레이아웃·언어 유형별 텍스트·수식·표·읽기 순서 인식",
            "official_source": "https://github.com/opendatalab/OmniDocBench",
        },
        "olmocr-bench": {
            "input_count": 1403,
            "focus": "텍스트 존재·부재, 읽기 순서, 상호 관계와 형식 충실도",
            "official_source": "https://github.com/allenai/olmocr",
        },
    }


def _write_markdown(
    *,
    report: dict[str, Any],
    index: dict[str, Any],
    final_report_path: Path,
    output_markdown: Path,
) -> None:
    lines = [
        "# FOLYNTA 특허 검토용 기술 증빙 인덱스",
        "",
        (
            "이 문서는 변리사 검토를 위한 기술 증빙 색인입니다. 발명자, 신규성, "
            "진보성, 출원일 또는 우선권에 관한 법률 의견은 아닙니다."
        ),
        "",
        "## 실험 범위와 재현 조건",
        "",
        f"- 전체 공개 벤치마크: {int(report['scope']['full_corpus_input_count']):,}건, 전수 1회",
        "- 반복 감사: 벤치마크별 128건을 3회 처리, 총 1,152회 추론",
        f"- 기준 모델: {report['models']['baseline']}",
        f"- 복구 모델: {', '.join(report['models']['alternate_recovery'])}",
        f"- 선택 원칙: {report['selection']['policy']}",
        (
            "- 서비스 복구 통합 테스트: "
            f"{index['service_recovery_equivalence']['service_test_count']}개 통과"
        ),
        "",
        "## 벤치마크별 기술 검증 범위",
        "",
        "| 벤치마크 | 전수 입력 | 검증 초점 | 공식 출처 |",
        "|---|---:|---|---|",
    ]
    for benchmark_id, scope in index["benchmark_scope"].items():
        lines.append(
            f"| {benchmark_id} | {int(scope['input_count']):,} | {scope['focus']} | "
            f"{scope['official_source']} |"
        )
    lines += [
        "",
        "## 청구항 검토에 활용 가능한 기술 효과와 직접 증거",
        "",
        "| 기술 효과 | 측정 방법 | 최종 보고서 위치 | 주 증거 |",
        "|---|---|---|---|",
    ]
    for row in index["technical_effect_matrix"]:
        lines.append(
            f"| {row['technical_effect']} | {row['measurement']} | "
            f"`{row['report_pointer']}` | `{row['primary_evidence_role']}` |"
        )
    lines += [
        "",
        "## 증거 동일성",
        "",
        f"- 최종 보고서 파일 해시: `{_sha256(final_report_path)}`",
        f"- 최종 보고서 내장 영수증: `{report['receipt_sha256']}`",
        f"- 서비스 동등성 영수증: `{index['service_recovery_equivalence']['receipt_sha256']}`",
        f"- 이 인덱스 영수증: `{index['receipt_sha256']}`",
        "",
        (
            "핵심 알고리즘, 테스트 경로, 서비스 구현과 결과를 SHA-256으로 고정합니다. "
            "전수 평가, 장애 판정, 복구 선택, 반복 감사, 비용 및 자원 삭제 증거는 "
            "최종 ZIP의 매니페스트와 연결됩니다."
        ),
        "",
        "## 해석 한계와 출원 전 보완",
        "",
    ]
    lines.extend(f"- {item}" for item in index["interpretation_boundaries"])
    lines.append("")
    lines.extend(f"- {item}" for item in index["applicant_completion_items"])
    lines.append("")
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def build_index(
    *,
    repository: Path,
    final_report_path: Path,
    service_evidence_path: Path,
    output_json: Path,
    output_markdown: Path,
) -> dict[str, Any]:
    for output in (output_json, output_markdown):
        if output.exists():
            raise FileExistsError(f"patent evidence index already exists: {output}")
    report = _load(final_report_path)
    if report.get("status") != "complete_and_officially_verified":
        raise ValueError("final report is not complete and officially verified")
    if int(report["scope"]["full_corpus_input_count"]) != 5132:
        raise ValueError("full public benchmark corpus coverage is invalid")
    service = _load(service_evidence_path)
    if (
        service.get("schema") != "folynta.service-recovery-equivalence-evaluation.v1"
        or service.get("status") != "complete_service_recovery_equivalence_verified"
        or service.get("gate_passed") is not True
        or int(service.get("service_test_count", 0)) < 60
        or float(service.get("anomaly_detection", {}).get("f1", -1)) != 1.0
        or float(service.get("quarantine_detection", {}).get("f1", -1)) != 1.0
    ):
        raise ValueError("service recovery equivalence evidence is incomplete")

    evidence_files: list[dict[str, str]] = [
        {
            "role": "service_recovery_equivalence",
            "path": service_evidence_path.relative_to(repository).as_posix(),
            "sha256": _sha256(service_evidence_path),
        }
    ]
    for key, value in report["evidence"].items():
        if key.endswith("_sha256"):
            continue
        paired_hash = report["evidence"].get(f"{key}_sha256")
        if paired_hash:
            evidence_files.append(
                {"role": key, "path": str(value), "sha256": str(paired_hash)}
            )
    index: dict[str, Any] = {
        "schema": "folynta.patent-technical-evidence-index.v1",
        "purpose": (
            "변리사 기술 검토용 증빙 패키지이며 발명자, 신규성, 진보성, "
            "특허 가능성 또는 우선권에 관한 법률 판단은 아님"
        ),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "final_report": {
            "path": final_report_path.relative_to(repository).as_posix(),
            "file_sha256": _sha256(final_report_path),
            "embedded_receipt_sha256": report["receipt_sha256"],
        },
        "service_recovery_equivalence": service,
        "experiment_scope": report["scope"],
        "benchmark_scope": _benchmark_scope(),
        "model_identities": report["models"],
        "compute_configuration": report["compute_configuration"],
        "selection_policy": report["selection"]["policy"],
        "technical_effect_matrix": _technical_effects(),
        "alternatives_evaluated_and_rejected": _alternatives_evaluated(),
        "accuracy_effect": {
            "case_level": report["case_zero_official_failure_accuracy"],
            "official_metric_delta": report["official_metrics"]["delta"],
        },
        "fault_detection_effect": report["operational_fault_detection"],
        "recovery_runtime_policy": report["recovery_runtime_policy"],
        "evidence_quality_notes": report.get("evidence_quality_notes", {}),
        "repeatability_effect": report["three_repeat_variance_audit"],
        "timing_evidence": report["timing"],
        "cost_evidence": report["cost"],
        "algorithm_source_fingerprints": [
            _fingerprint(repository, relative) for relative in ALGORITHM_SOURCES
        ],
        "evidence_file_chain": evidence_files,
        "interpretation_boundaries": [
            "결과는 고정된 공개 벤치마크, 리뷰 규칙과 기록된 실행 환경에 한정됩니다.",
            "SHA-256은 파일 동일성을 증명하지만 독립적인 공인 시점 인증은 아닙니다.",
            "비용은 RunPod 공급자 기록을 기준으로 산출하며 최종 회계 기록은 계정 청구서입니다.",
            (
                "서비스 장애 주입은 구현 동등성을 검증하며 모든 운영 장애의 "
                "발생 빈도를 일반화하지 않습니다."
            ),
            "이 패키지는 신규성, 진보성, 발명자 또는 우선권을 법적으로 판단하지 않습니다.",
        ],
        "applicant_completion_items": [
            "발명자 이름과 기여 진술은 비밀정보가 포함되지 않는 별도 문서에 기록합니다.",
            "날짜가 있는 외부 공개·설계 기록과 저장소 커밋 기록을 첨부합니다.",
            "변리사가 기술 효과 매트릭스를 허용 가능한 청구항 문구에 대응시킵니다.",
            "선행기술 조사표와 청구항 대비표는 법률 검토 문서로 별도 작성합니다.",
            "최종 ZIP과 SHA-256을 문서 관리 시스템에 보존합니다.",
        ],
    }
    encoded = json.dumps(
        index, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    index["receipt_sha256"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_markdown(
        report=report,
        index=index,
        final_report_path=final_report_path,
        output_markdown=output_markdown,
    )
    return index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--final-report", type=Path, required=True)
    parser.add_argument("--service-evidence", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = build_index(
        repository=args.repository_root.resolve(),
        final_report_path=args.final_report.resolve(),
        service_evidence_path=args.service_evidence.resolve(),
        output_json=args.output_json.resolve(),
        output_markdown=args.output_markdown.resolve(),
    )
    print(
        json.dumps(
            {"status": "complete", "receipt_sha256": index["receipt_sha256"]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ALGORITHM_SOURCES", "build_index"]
