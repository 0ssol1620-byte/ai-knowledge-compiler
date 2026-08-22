#!/usr/bin/env python3
"""Create a secret-free review ZIP for the public recovery campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections.abc import Iterable
from pathlib import Path

from evaluate_service_recovery_equivalence import SERVICE_SOURCE_PATHS

GENERATED_NAMES = (
    "FOLYNTA_PUBLIC_BENCHMARK_RECOVERY_FINAL_REPORT_2026-08-04.md",
    "FOLYNTA_PATENT_TECHNICAL_EVIDENCE_INDEX_2026-08-04.md",
    "folynta-patent-technical-evidence-index-2026-08-04.json",
    "folynta-mineru344-public-core-4shard-plan-2026-08-04.json",
    "folynta-mineru344-public-core-official-failures-r1-2026-08-04.json",
    "folynta-mineru-operational-retry-expansion-evidence-2026-08-04.json",
    "folynta-operational-fault-injection-evaluation-2026-08-04.json",
    "folynta-service-recovery-equivalence-evaluation-2026-08-05.json",
    "folynta-runpod-all-pod-inventory-live-r1-2026-08-04.json",
    "paddle-bootstrap-r9-model-artifact-primary-manifest.json",
    # The recorded scope decision bounds what the report may claim, and the
    # orchestration incident log carries the provisioning failures and their
    # cost. A reviewer needs both to read the coverage statement correctly.
    "folynta-recovery-execution-decision-2026-08-07.json",
    "folynta-post-baseline-pool-orchestration-incidents-2026-08-07.json",
    "folynta-mineru344-public-failure-summary-r1-2026-08-04.json",
    # Targeted quality recovery: which documents were selected, on what rule,
    # and the hand check that the rule targets real extraction defects rather
    # than evaluator artefacts.
    "folynta-highest-impact-failure-selection-2026-08-08.json",
    "folynta-targeting-verification-2026-08-08.json",
    "folynta-recovery-execution-decision-targeted-2026-08-08.json",
)

GENERATED_PREFIXES = (
    "folynta-alternate-recovery-controller-2026-08-04",
    "folynta-deepseek-recovery-bootstrap-2026-08-04",
    "folynta-mineru-quality-candidate-controller-2026-08-04",
    "folynta-mineru-quality-retry-controller-2026-08-04",
    "folynta-mineru344-public-core-official-evaluations",
    "folynta-official-evaluation-controller-2026-08-04",
    "folynta-operational-detection-evaluation-2026-08-04",
    "folynta-operational-prefetch-incident-evidence-2026-08-04",
    "folynta-operational-recovery-round2-2026-08-05",
    "folynta-operational-retry-prefetch-",
    "folynta-patent-paper-artifacts-2026-08-05",
    "folynta-obsolete-pod-cleanup-2026-08-05",
    "folynta-phase-cost-cleanup-2026-08-05",
    # Worker provisioning receipts, the pool capacity incident, and the audit
    # pipeline journal that together show how the three audit Pods were reached.
    "folynta-post-baseline-mineru-pool-2026-08-05",
    "folynta-post-selection-recovery-audit-2026-08-05",
    "folynta-runpod-credit-monitor-2026-08-05",
    "folynta-service-recovery-runtime-2026-08-06",
    "folynta-paddle-recovery-bootstrap-2026-08-04",
    "folynta-post-mineru-selection-controller-2026-08-04",
    "folynta-public-benchmark-recovery-final",
    "folynta-runpod-campaign-cleanup-2026-08-04",
    "folynta-runpod-campaign-pod-registry",
    "folynta-runpod-billing-snapshot",
    "folynta-runpod-cost-snapshot-final-2026-08-04",
    "folynta-stratified-audit-controller-2026-08-04",
    "folynta-stratified-audit-evaluation-controller-2026-08-04",
    "folynta-stratified-audit-official-evaluations-r1-2026-08-04",
    "runpod-operational-retry-controller-2026-08-04",
    "runpod-operational-retry-monitor-2026-08-04",
    "runpod-public-core-live-monitor-2026-08-04",
    "runpod-live-worker1-parse-2026-08-04",
)

SOURCE_NAMES = (
    "apply_operational_retries.py",
    "apply_accepted_alternate_candidates.py",
    "apply_accepted_quality_candidates.py",
    "apply_alternate_candidates.py",
    "apply_mineru_quality_candidates.py",
    "artifact_manifest.py",
    "build_public_benchmark_final_report.py",
    "build_patent_evidence_index.py",
    "build_patent_paper_artifacts.py",
    "classify_operational_worker_health.py",
    "collect_operational_retry_worker.py",
    "collect_dedicated_recovery.py",
    "deepseek_ocr2_stage2.py",
    "collect_mineru_quality_retry_worker.py",
    "compare_official_failure_records.py",
    "compare_official_evaluation_metrics.py",
    "evaluate_operational_detection.py",
    "evaluate_operational_fault_injection.py",
    "evaluate_parsebench_official.py",
    # The remaining official evaluator drivers and the record builder behind
    # every cited metric. Without them a reviewer cannot re-run the evaluation
    # the report describes.
    "evaluate_omnidoc_repeats.py",
    "evaluate_olmocr_official.py",
    "build_public_failure_records.py",
    "summarize_failure_records.py",
    "select_highest_impact_failures.py",
    "capture_omnidoc_frozen_artifacts.py",
    "evaluate_service_recovery_equivalence.py",
    "launch_dedicated_recovery.py",
    "launch_mineru_quality_retry_workers.py",
    "launch_operational_retry_workers.py",
    "package_operational_retry_inputs.py",
    "package_public_benchmark_review.py",
    "package_selective_recovery_inputs.py",
    "parsebench_evaluator_watchdog.py",
    "paddle_result_to_mineru_model.py",
    "paddleocr_vl_stage2.py",
    "prepare_stratified_audit_official.py",
    "plan_operational_retries.py",
    "remote_bootstrap_deepseek_recovery.sh",
    "remote_bootstrap_paddle_recovery.sh",
    "remote_run_dedicated_recovery.sh",
    "remote_run_mineru_quality_retry.sh",
    "remote_run_operational_retry.sh",
    "remote_run_stratified_audit.sh",
    "remote_guard_stalled_public_core.sh",
    "remote_recover_stalled_public_core.sh",
    "remote_stall_watchdog.sh",
    "run_stratified_audit_campaign.py",
    "stage_selective_recovery.py",
    "summarize_stratified_audit_official.py",
    "test_apply_alternate_candidates.py",
    "test_apply_mineru_quality_candidates.py",
    "test_apply_operational_retries.py",
    "test_collect_dedicated_recovery.py",
    "test_build_patent_evidence_index.py",
    "test_build_patent_paper_artifacts.py",
    "test_build_public_benchmark_final_report.py",
    "test_evaluate_operational_detection.py",
    "test_evaluate_operational_fault_injection.py",
    "test_evaluate_service_recovery_equivalence.py",
    "test_compare_official_evaluation_metrics.py",
    "test_launch_operational_retry_workers.py",
    "test_launch_mineru_quality_retry_workers.py",
    "test_operational_recovery_round2_static.py",
    "test_package_operational_retry_inputs.py",
    "test_package_selective_recovery_inputs.py",
    "test_package_public_benchmark_review.py",
    "test_parsebench_evaluator_watchdog.py",
    "test_paddle_result_to_mineru_model.py",
    "test_plan_operational_retries.py",
    "test_public_core_worker_static.py",
    "test_remote_expansion_worker_static.py",
    "test_remote_stall_watchdog_static.py",
    "test_run_stratified_audit_campaign.py",
    "test_stage_selective_recovery.py",
    "start_folynta_operational_retry_prefetch.ps1",
    "collect_folynta_operational_prefetch_incidents.ps1",
    "continue_folynta_official_evaluations.ps1",
    "continue_folynta_operational_retries.ps1",
    "monitor_folynta_live_campaign.py",
    "monitor_folynta_runpod_credit.py",
    "continue_folynta_post_baseline_mineru_pool.ps1",
    "continue_folynta_post_selection_recovery_and_audit.ps1",
    "continue_folynta_alternate_recovery.ps1",
    "continue_folynta_detection_evaluation.ps1",
    "provision_folynta_mineru_recovery_worker.ps1",
    "snapshot_folynta_runpod_billing.ps1",
    "cleanup_folynta_runpod_resources.ps1",
    "continue_folynta_phase_cost_cleanup.ps1",
)

SOURCE_PATHS = (
    "infra/runpod/v6/bootstrap/run-mineru-3.4.4-public-core-worker.sh",
    # The adapter that maps official evaluator decisions onto the recovery
    # taxonomy, and so decides which failures are recoverable at all.
    "benchmark/v6/public_failure_adapter.py",
    "tools/release/deliver_folynta_portable_report.mjs",
    # The repository-local renderer that actually produced the technical report
    # when the external portable-report plugin is not installed.
    "tools/release/render_folynta_portable_report.mjs",
    # SOURCE_NAMES routes every non-.ps1 entry to benchmark/runpod_eval, so a
    # Python tool that lives under tools/release has to be named by full path.
    "tools/release/record_folynta_execution_decision.py",
    *SERVICE_SOURCE_PATHS,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from (candidate for candidate in path.rglob("*") if candidate.is_file())


def package_review(*, repository: Path, output_zip: Path) -> dict[str, object]:
    if output_zip.exists():
        raise FileExistsError(f"review ZIP already exists: {output_zip}")
    generated = repository / "benchmark/reports/generated"
    selected: set[Path] = set()
    for name in GENERATED_NAMES:
        selected.update(_files(generated / name))
    for candidate in generated.iterdir():
        if any(candidate.name.startswith(prefix) for prefix in GENERATED_PREFIXES):
            selected.update(_files(candidate))
    runpod_eval = repository / "benchmark/runpod_eval"
    release = repository / "tools/release"
    for name in SOURCE_NAMES:
        source_root = release if name.endswith(".ps1") else runpod_eval
        selected.update(_files(source_root / name))
    for relative in SOURCE_PATHS:
        selected.update(_files(repository / relative))
    selected.update(_files(repository / "benchmark/v6/candidate-registry.yaml"))
    for candidate in release.iterdir():
        if candidate.is_file() and (
            "folynta" in candidate.name.lower()
            or candidate.name
            in {"runpod_pod_watchdog.ps1", "snapshot_folynta_runpod_cost.ps1"}
        ):
            selected.add(candidate)

    normalized: list[Path] = []
    for path in sorted(selected):
        resolved = path.resolve()
        relative = resolved.relative_to(repository.resolve())
        if "private" in {part.lower() for part in relative.parts}:
            raise ValueError(f"private evidence was selected for ZIP: {relative}")
        if resolved == output_zip.resolve():
            continue
        normalized.append(resolved)
    if not normalized:
        raise ValueError("review ZIP selection is empty")

    manifest_records = [
        {
            "path": path.relative_to(repository).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in normalized
    ]
    manifest = {
        "schema": "folynta.public-benchmark-review-package.v1",
        "secret_free_policy": "benchmark/datasets/private is excluded",
        "file_count": len(manifest_records),
        "files": manifest_records,
    }
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in normalized:
            archive.write(path, path.relative_to(repository).as_posix())
        archive.writestr(
            "REVIEW_PACKAGE_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    receipt = {
        **manifest,
        "zip_path": str(output_zip),
        "zip_size_bytes": output_zip.stat().st_size,
        "zip_sha256": _sha256(output_zip),
    }
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.repository_root.resolve()
    receipt_path = args.receipt.resolve()
    if receipt_path.exists():
        raise FileExistsError(f"package receipt already exists: {receipt_path}")
    receipt = package_review(
        repository=repository,
        output_zip=args.output_zip.resolve(),
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "file_count": receipt["file_count"],
                "zip_sha256": receipt["zip_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["package_review"]
