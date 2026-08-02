"""Summarize the FOLYNTA non-visual algorithm contract suite from JUnit XML."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import defusedxml.ElementTree as ET


@dataclass(frozen=True)
class AlgorithmArea:
    key: str
    title: str
    modules: tuple[str, ...]
    contract: str


AREAS = (
    AlgorithmArea(
        key="classification_routing",
        title="페이지 분류·비용 예측·적응형 라우팅",
        modules=("akc_router", "akc_parallel_runtime.routing", "akc_router.estimation"),
        contract="객관 특징 분류, 준비된 경로만 선택, 비공개 데이터 외부 전송 금지",
    ),
    AlgorithmArea(
        key="credit_cost_accounting",
        title="크레딧·비용·결제 원장",
        modules=("akc_parallel_runtime.credits", "akc_api.credit_policy", "akc_api.payments"),
        contract="검증 승인된 논리 작업만 1회 과금하고 retry·hedge·실패는 중복 과금하지 않음",
    ),
    AlgorithmArea(
        key="quality_verification",
        title="품질·수치·표·근거 검증",
        modules=(
            "akc_quality",
            "akc_parallel_runtime.validation",
            "akc_parallel_runtime.arbitration",
        ),
        contract="critical finding과 authority mismatch가 점수·다수결을 우회하지 못함",
    ),
    AlgorithmArea(
        key="fault_detection_health",
        title="침묵 실패·이상 결과·worker health 탐지",
        modules=(
            "akc_parallel_runtime.failures",
            "akc_parallel_runtime.health",
            "semantic_monitor",
        ),
        contract="HTTP 200이어도 의미 오류를 실패로 처리하고 오염 worker를 격리함",
    ),
    AlgorithmArea(
        key="retry_recovery",
        title="최소 범위 재시도·선택 복구·무효화",
        modules=(
            "akc_parallel_runtime.recovery",
            "collection_region_runtime",
            "collection_integrity",
        ),
        contract="cell→row→table→region→page 순서의 최소 범위 복구와 완전한 lineage 보존",
    ),
    AlgorithmArea(
        key="knowledge_architecture",
        title="문서→지식 아키텍처·검색·패키지",
        modules=("knowledge_pipeline", "collection_semantic_runtime", "akc_exporters"),
        contract=(
            "노트·엔티티·관계·아키텍처·패키지가 원문 근거와 동일한 canonical identity를 유지함"
        ),
    ),
    AlgorithmArea(
        key="state_identity_security",
        title="상태기계·동시성·결정 추적·보안 경계",
        modules=("attempts", "identity", "finalization", "storage security"),
        contract=(
            "idempotency, append-only history, first-verified, tenant/object scope가 깨지지 않음"
        ),
    ),
)


def _area(classname: str, name: str) -> str:
    value = f"{classname}.{name}".casefold()
    if any(term in value for term in ("credit", "payment", "refund", "bill", "cost")):
        return "credit_cost_accounting"
    if any(
        term in value
        for term in (
            "knowledge_pipeline",
            "collection_semantic_runtime",
            "retrieval",
            "architecture",
            "canonical_note",
        )
    ):
        return "knowledge_architecture"
    if any(
        term in value
        for term in (
            "recovery_and_continuity",
            "collection_region_runtime",
            "collection_integrity_decisions",
            "retry",
            "dead_letter",
            "redrive",
            "correct_source",
        )
    ):
        return "retry_recovery"
    if any(
        term in value
        for term in (
            "topology_and_failures",
            "attempts_and_health",
            "semantic_monitor",
            "worker_health",
            "silent_failure",
            "quarantine",
        )
    ):
        return "fault_detection_health"
    if any(
        term in value
        for term in (
            "test_quality",
            "packages.quality",
            "validation_and_arbitration",
            "numeric_geometry",
            "authority",
            "evidence",
        )
    ):
        return "quality_verification"
    if any(
        term in value
        for term in (
            "router",
            "routing",
            "collection_estimation",
            "sharding",
            "sampling",
            "provider",
            "public_proof",
        )
    ):
        return "classification_routing"
    return "state_identity_security"


def _status(case: ET.Element) -> str:
    for value in ("failure", "error", "skipped"):
        if case.find(value) is not None:
            return value
    return "passed"


def _junit_summary(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    root = ET.fromstring(payload)
    testcases = list(root.iter("testcase"))
    totals = Counter(_status(case) for case in testcases)
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "tests": len(testcases),
        "passed": totals["passed"],
        "failed": totals["failure"],
        "errors": totals["error"],
        "skipped": totals["skipped"],
        "duration_seconds": round(
            sum(float(case.attrib.get("time", "0") or 0) for case in testcases),
            6,
        ),
        "gate": (
            "PASS"
            if testcases and totals["failure"] == totals["error"] == totals["skipped"] == 0
            else "FAIL"
        ),
    }


def summarize(
    path: Path,
    coverage_path: Path | None = None,
    golden_path: Path | None = None,
    regression_path: Path | None = None,
) -> dict[str, object]:
    payload = path.read_bytes()
    root = ET.fromstring(payload)
    testcases = list(root.iter("testcase"))
    area_rows: dict[str, list[ET.Element]] = {area.key: [] for area in AREAS}
    for case in testcases:
        area_rows[_area(case.attrib.get("classname", ""), case.attrib.get("name", ""))].append(case)

    areas = []
    for area in AREAS:
        rows = area_rows[area.key]
        statuses = Counter(_status(case) for case in rows)
        duration = sum(float(case.attrib.get("time", "0") or 0) for case in rows)
        areas.append(
            {
                "key": area.key,
                "title": area.title,
                "contract": area.contract,
                "modules": list(area.modules),
                "tests": len(rows),
                "passed": statuses["passed"],
                "failed": statuses["failure"],
                "errors": statuses["error"],
                "skipped": statuses["skipped"],
                "duration_seconds": round(duration, 6),
                "gate": (
                    "PASS"
                    if rows and statuses["failure"] == statuses["error"] == statuses["skipped"] == 0
                    else "FAIL"
                ),
            }
        )
    totals = Counter(_status(case) for case in testcases)
    deterministic_gate = (
        "PASS"
        if testcases and totals["failure"] == totals["error"] == totals["skipped"] == 0
        else "FAIL"
    )
    coverage: dict[str, object] | None = None
    if coverage_path is not None:
        coverage_payload = coverage_path.read_bytes()
        coverage_source = json.loads(coverage_payload)
        coverage_totals = coverage_source["totals"]
        coverage = {
            "path": coverage_path.as_posix(),
            "sha256": hashlib.sha256(coverage_payload).hexdigest(),
            "percent_covered": coverage_totals["percent_covered"],
            "statements": coverage_totals["num_statements"],
            "covered_lines": coverage_totals["covered_lines"],
            "branches": coverage_totals["num_branches"],
            "covered_branches": coverage_totals["covered_branches"],
            "gate_percent": 80.0,
            "gate": "PASS" if coverage_totals["percent_covered"] >= 80 else "FAIL",
        }
    golden: dict[str, object] | None = None
    if golden_path is not None:
        golden_payload = golden_path.read_bytes()
        golden_source = json.loads(golden_payload)
        golden = {
            "path": golden_path.as_posix(),
            "sha256": hashlib.sha256(golden_payload).hexdigest(),
            "gate": golden_source["gate"],
            "corpus_type": golden_source["corpus_type"],
            "metrics": golden_source["metrics"],
            "claim_boundary": golden_source["claim_boundary"],
        }
    regression = _junit_summary(regression_path) if regression_path is not None else None
    return {
        "schema": "folynta.algorithm-evaluation-summary.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "junit_path": path.as_posix(),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "totals": {
            "tests": len(testcases),
            "passed": totals["passed"],
            "failed": totals["failure"],
            "errors": totals["error"],
            "skipped": totals["skipped"],
        },
        "areas": areas,
        "coverage": coverage,
        "golden_evaluation": golden,
        "full_backend_regression": regression,
        "gates": {
            "deterministic_contract_suite": deterministic_gate,
            "public_empirical_corpus": "PARTIAL",
            "private_holdout": "EXTERNAL_BLOCKED",
            "production_calibration": "PARTIAL",
        },
        "claim_boundary": {
            "proven": (
                "고정 입력에 대한 결정 규칙, 상태 보존성, 과금 불변식, 오류 주입 대응, "
                "지식 패키지 근거 계약"
            ),
            "not_proven": (
                "현실 분포 전체의 분류 정확도, private holdout 품질, production invoice와 "
                "provider telemetry의 장기 calibration"
            ),
        },
    }


def markdown(summary: dict[str, object]) -> str:
    totals = summary["totals"]
    assert isinstance(totals, dict)
    lines = [
        "# FOLYNTA 비디자인 알고리즘 검증 리포트",
        "",
        f"- 전체: {totals['tests']}개",
        f"- 통과: {totals['passed']}개",
        f"- 실패/오류/건너뜀: {totals['failed']}/{totals['errors']}/{totals['skipped']}",
        f"- 결정적 계약 Gate: `{summary['gates']['deterministic_contract_suite']}`",  # type: ignore[index]
    ]
    coverage = summary.get("coverage")
    if isinstance(coverage, dict):
        lines.extend(
            [
                (
                    f"- 코드 커버리지: {coverage['percent_covered']:.2f}% "
                    f"(Gate {coverage['gate_percent']:.0f}%, `{coverage['gate']}`)"
                ),
                (
                    f"- line/branch: {coverage['covered_lines']}/{coverage['statements']}, "
                    f"{coverage['covered_branches']}/{coverage['branches']}"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## 영역별 결과",
            "",
            "| 영역 | 테스트 | 통과 | 실패 | Gate | 핵심 계약 |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for area in summary["areas"]:  # type: ignore[union-attr]
        lines.append(
            f"| {area['title']} | {area['tests']} | {area['passed']} | "
            f"{area['failed'] + area['errors']} | {area['gate']} | {area['contract']} |"
        )
    golden = summary.get("golden_evaluation")
    if isinstance(golden, dict):
        metrics = golden["metrics"]
        lines.extend(
            [
                "",
                "## 고정 오류 주입 코퍼스 정량 결과",
                "",
                "| 알고리즘 | 코퍼스 | 지표 | 결과 |",
                "|---|---:|---|---:|",
                (
                    "| 페이지 분류 | "
                    f"{metrics['page_classification']['fixtures']} | accuracy | "
                    f"{metrics['page_classification']['accuracy']:.3f} |"
                ),
                (
                    "| 품질 이상 탐지 | "
                    f"{metrics['quality_anomaly_detection']['fixtures']} | precision/recall/F1 | "
                    f"{metrics['quality_anomaly_detection']['precision']:.3f} / "
                    f"{metrics['quality_anomaly_detection']['recall']:.3f} / "
                    f"{metrics['quality_anomaly_detection']['f1']:.3f} |"
                ),
                (
                    "| 실패 원인 분류 | "
                    f"{metrics['failure_diagnosis']['fixtures']} | accuracy | "
                    f"{metrics['failure_diagnosis']['accuracy']:.3f} |"
                ),
                (
                    "| 복구 specialist 선택 | "
                    f"{metrics['recovery_selection']['fixtures']} | accuracy | "
                    f"{metrics['recovery_selection']['selection_accuracy']:.3f} |"
                ),
                (
                    "| 라우팅·escalation | "
                    f"{metrics['routing_and_escalation']['fixtures']} | decision accuracy | "
                    f"{metrics['routing_and_escalation']['decision_accuracy']:.3f} |"
                ),
                (
                    "| 중복 시도 과금 | "
                    f"{metrics['credit_accounting']['duplicate_attempts']} | charged credits | "
                    f"{metrics['credit_accounting']['duplicate_charge_credits']} |"
                ),
                "",
                f"- Golden Gate: `{golden['gate']}`",
                f"- 경계: {golden['claim_boundary']}",
            ]
        )
    regression = summary.get("full_backend_regression")
    if isinstance(regression, dict):
        lines.extend(
            [
                "",
                "## 전체 백엔드 회귀",
                "",
                "| 테스트 | 통과 | 실패 | 오류 | 스킵 | Gate |",
                "|---:|---:|---:|---:|---:|---|",
                (
                    f"| {regression['tests']} | {regression['passed']} | "
                    f"{regression['failed']} | {regression['errors']} | "
                    f"{regression['skipped']} | {regression['gate']} |"
                ),
                "",
                (
                    "- 범위: API·상태기계·보안·스케줄러·삭제·과금·검색·"
                    "지식 패키지·모델 평가 도구 회귀"
                ),
                "- 이 Gate는 현재 코드베이스 회귀 무결성을 증명하며 실운영 SLO를 대신하지 않는다.",
            ]
        )
    lines.extend(
        [
            "",
            "## 판정 경계",
            "",
            f"- 증명됨: {summary['claim_boundary']['proven']}",  # type: ignore[index]
            f"- 아직 증명되지 않음: {summary['claim_boundary']['not_proven']}",  # type: ignore[index]
            "- 따라서 이 리포트는 서비스 알고리즘의 결정적 기능·안전 계약 통과 증거이며, "
            "현실 분포 전체 정확도나 private holdout 합격을 대신하지 않는다.",
            "",
            "## 추가 Gate",
            "",
            "| Gate | 상태 |",
            "|---|---|",
            f"| Public empirical corpus | {summary['gates']['public_empirical_corpus']} |",  # type: ignore[index]
            f"| Private holdout | {summary['gates']['private_holdout']} |",  # type: ignore[index]
            f"| Production calibration | {summary['gates']['production_calibration']} |",  # type: ignore[index]
            "",
        ]
    )
    return "\n".join(lines)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--golden", type=Path)
    parser.add_argument("--regression", type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    return parser.parse_args()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def main() -> None:
    args = _arguments()
    summary = summarize(args.junit, args.coverage, args.golden, args.regression)
    _write(args.json_output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _write(args.markdown_output, markdown(summary))
    print(json.dumps(summary["totals"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
