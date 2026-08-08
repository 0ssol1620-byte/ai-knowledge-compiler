from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).with_name("continue_folynta_phase_cost_cleanup.ps1")


def test_phase_cleanup_is_evidence_gated_and_identity_bound() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "alternate_recovery_officially_selected" in text
    assert "input_count_per_repeat -ne 384" in text
    assert "repeat_count -ne 3" in text
    assert "inference_count -ne 1152" in text
    assert "[string]$pod.name -ne $ExpectedName" in text
    assert 'Invoke-RestMethod -Method Post -Uri "$uri/stop"' in text
    assert "desiredStatus -eq 'EXITED'" in text


def test_phase_cleanup_stops_only_post_phase_reusable_pods() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for pod_id in (
        "8q4p95vk8aqrqc",
        "68lo3k8a2lft1i",
        "p2tvagqhw6almp",
        "12lbrsp8nz0oie",
        "nut7g2azdnrtm6",
    ):
        assert text.count(pod_id) == 1
    assert "xk1371aijxy7hm" not in text
    assert "rop1r15ph47bx6" not in text
    assert "b0b5oruh32c7dk" not in text


def test_finalizer_waits_for_phase_cleanup_before_final_deletion() -> None:
    finalizer = Path(__file__).with_name(
        "finalize_folynta_public_benchmark_campaign_v2.ps1"
    ).read_text(encoding="utf-8")
    wait_position = finalizer.index("Wait-ForFile -Path $phaseCostTerminal")
    cleanup_position = finalizer.index("cleanup_folynta_runpod_resources.ps1")
    assert wait_position < cleanup_position
    assert "phase_pods_stopped_after_verified_evidence" in finalizer
    assert "phase_cost_cleanup_receipt = $phaseCostTerminal" in finalizer
    assert "Final campaign report completion gate failed" in finalizer
    assert "Patent evidence completion gate failed" in finalizer
    assert "Review ZIP completion gate failed" in finalizer
    assert "actualZipSha256" in finalizer


def test_final_report_and_review_package_bind_phase_cleanup_evidence() -> None:
    repository = SCRIPT.parents[2]
    report_builder = (
        repository / "benchmark/runpod_eval/build_public_benchmark_final_report.py"
    ).read_text(encoding="utf-8")
    package_builder = (
        repository / "benchmark/runpod_eval/package_public_benchmark_review.py"
    ).read_text(encoding="utf-8")
    patent_builder = (
        repository / "benchmark/runpod_eval/build_patent_evidence_index.py"
    ).read_text(encoding="utf-8")
    assert "phase_cost_cleanup_receipt_sha256" in report_builder
    assert '"folynta-phase-cost-cleanup-2026-08-05"' in package_builder
    assert '"folynta-obsolete-pod-cleanup-2026-08-05"' in package_builder
    assert '"tools/release/continue_folynta_phase_cost_cleanup.ps1"' in patent_builder
    assert "obsolete_pod_cleanup_receipt_sha256" in report_builder


def test_finalizer_requires_service_recovery_equivalence_before_patent_zip() -> None:
    repository = SCRIPT.parents[2]
    finalizer = Path(__file__).with_name(
        "finalize_folynta_public_benchmark_campaign_v2.ps1"
    ).read_text(encoding="utf-8")
    patent_builder = (
        repository / "benchmark/runpod_eval/build_patent_evidence_index.py"
    ).read_text(encoding="utf-8")
    package_builder = (
        repository / "benchmark/runpod_eval/package_public_benchmark_review.py"
    ).read_text(encoding="utf-8")
    # Anchor on the Invoke-FinalNative step names. The earlier anchors named
    # progress events the finaliser never emitted, so the ordering assertion
    # could not run at all.
    service_position = finalizer.index("'Service recovery equivalence evidence'")
    patent_position = finalizer.index("'Patent technical evidence index'")
    zip_position = finalizer.index("'Review evidence package'")
    assert service_position < patent_position < zip_position
    assert "service_test_count -lt 60" in finalizer
    assert "anomaly_detection.f1 -ne 1.0" in finalizer
    assert "quarantine_detection.f1 -ne 1.0" in finalizer
    assert "'--service-evidence', $serviceEvidence" in finalizer
    assert "service_recovery_equivalence" in patent_builder
    assert "SERVICE_SOURCE_PATHS" in patent_builder
    assert "folynta-service-recovery-equivalence-evaluation-2026-08-05.json" in package_builder
