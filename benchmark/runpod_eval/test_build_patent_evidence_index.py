from __future__ import annotations

import json
from pathlib import Path

from benchmark.runpod_eval.build_patent_evidence_index import (
    ALGORITHM_SOURCES,
    build_index,
)
from benchmark.runpod_eval.package_public_benchmark_review import (
    SOURCE_NAMES,
    SOURCE_PATHS,
)


def test_review_package_includes_every_fingerprinted_algorithm_source() -> None:
    packaged_paths = set(SOURCE_PATHS)
    packaged_names = set(SOURCE_NAMES)
    assert all(
        relative in packaged_paths or Path(relative).name in packaged_names
        for relative in ALGORITHM_SOURCES
    )


def test_build_index_binds_report_service_sources_and_effects(tmp_path: Path) -> None:
    for relative in ALGORITHM_SOURCES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"source:{relative}\n", encoding="utf-8")

    report_path = tmp_path / "benchmark/reports/generated/final.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "complete_and_officially_verified",
        "receipt_sha256": "sha256:report-receipt",
        "scope": {
            "full_corpus_input_count": 5132,
            "full_corpus_repeat_count": 1,
            "stratified_audit_input_count_per_suite": 128,
            "stratified_audit_repeat_count": 3,
            "stratified_audit_inference_count": 1152,
        },
        "models": {
            "baseline": "MinerU 3.4.4 VLM(c1)",
            "alternate_recovery": ["PaddleOCR-VL-1.6", "DeepSeek-OCR-2"],
        },
        "compute_configuration": {
            "gpu": {"name": "NVIDIA GeForce RTX 4090", "memory_mib": "24564"}
        },
        "selection": {"policy": "accept improvements and revert regressions"},
        "case_zero_official_failure_accuracy": {"parsebench": {"gain": 0.1}},
        "official_metrics": {"delta": {"official_failure_records_removed": 10}},
        "operational_fault_detection": {"case_failure_detection": {"f1": 1.0}},
        "recovery_runtime_policy": {"per_case_timeout_seconds": 1800},
        "three_repeat_variance_audit": {"repeat_count": 3},
        "timing": {"elapsed_hours_to_report": 12.5},
        "cost": {"within_approved_cap": True},
        "evidence": {
            "detection_report": "benchmark/reports/generated/detection.json",
            "detection_report_sha256": "sha256:detection",
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    service_path = tmp_path / "benchmark/reports/generated/service.json"
    service = {
        "schema": "folynta.service-recovery-equivalence-evaluation.v1",
        "status": "complete_service_recovery_equivalence_verified",
        "gate_passed": True,
        "service_test_count": 60,
        "anomaly_detection": {"f1": 1.0},
        "quarantine_detection": {"f1": 1.0},
        "receipt_sha256": "sha256:service-receipt",
    }
    service_path.write_text(json.dumps(service), encoding="utf-8")
    output_json = tmp_path / "index.json"
    output_markdown = tmp_path / "index.md"

    index = build_index(
        repository=tmp_path,
        final_report_path=report_path,
        service_evidence_path=service_path,
        output_json=output_json,
        output_markdown=output_markdown,
    )

    assert index["schema"] == "folynta.patent-technical-evidence-index.v1"
    assert len(index["algorithm_source_fingerprints"]) == len(ALGORITHM_SOURCES)
    assert index["evidence_file_chain"][0]["role"] == "service_recovery_equivalence"
    assert index["timing_evidence"]["elapsed_hours_to_report"] == 12.5
    assert index["recovery_runtime_policy"]["per_case_timeout_seconds"] == 1800
    effects = {row["technical_effect"] for row in index["technical_effect_matrix"]}
    assert "단일 장문 문서 정체의 격리와 연속 처리" in effects
    assert "전체 처리 무출력 감지 후 완료 결과 보존 재개" in effects
    assert "벤치마크 복구 정책과 서비스 제어면의 구현 동등성" in effects
    assert index["receipt_sha256"].startswith("sha256:")
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "FOLYNTA 특허 검토용 기술 증빙 인덱스" in markdown
    assert "증거 동일성" in markdown
    assert "서비스 복구 통합 테스트: 60개 통과" in markdown
