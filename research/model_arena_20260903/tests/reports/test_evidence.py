"""``arena.reports.evidence``: FINAL_EVIDENCE_MANIFEST.json and the DoD checklist."""

from __future__ import annotations

import json
from pathlib import Path

from arena.reports.evidence import DodItem, build_evidence
from arena.reports.loaders import load_campaign_sources
from arena.reports.paths import OutputPaths, SourcePaths
from arena.reports.variant_ids import VARIANT_IDS, variant_dir_name

MODELS = ("paddleocr_vl_1_6", "mineru_pipeline", "opus5_subscription")
BENCHMARKS = ("parsebench", "omnidoc", "olmocr")
VARIANT_DIR_NAMES = {v: variant_dir_name(v) for v in VARIANT_IDS}


def _build(campaign_root: Path) -> tuple[Path, list[DodItem]]:
    source_paths = SourcePaths(root=campaign_root)
    out = OutputPaths.under(campaign_root / "reports")
    sources = load_campaign_sources(
        source_paths, models=MODELS, benchmarks=BENCHMARKS, variant_dir_names=VARIANT_DIR_NAMES
    )
    checklist = build_evidence(
        sources,
        source_paths,
        out,
        models=MODELS,
        benchmarks=BENCHMARKS,
        variant_ids=VARIANT_IDS,
    )
    return out.evidence_dir, checklist


def test_build_evidence_writes_final_manifest_with_hashes(campaign_root: Path) -> None:
    evidence_dir, _ = _build(campaign_root)
    manifest_path = evidence_dir / "FINAL_EVIDENCE_MANIFEST.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifacts"]
    for artifact in manifest["artifacts"]:
        assert artifact["sha256"].startswith("sha256:")
        assert (evidence_dir / artifact["path"]).is_file()


def test_build_evidence_dod_checklist_true_when_data_present(campaign_root: Path) -> None:
    _, checklist = _build(campaign_root)
    by_key = {item.key: item for item in checklist}
    assert by_key["source_hashes"].satisfied is True
    assert by_key["prompts_hashed"].satisfied is True
    assert by_key["pod_costs_recorded"].satisfied is True
    assert by_key["cleanup_verified"].satisfied is True
    assert by_key["routes_frozen"].satisfied is True
    assert by_key["recovery_receipts"].satisfied is True
    assert by_key["official_scoring"].satisfied is True
    # structurally unverifiable from this lane's inputs -> always false, with a reason
    assert by_key["gt_isolation"].satisfied is False
    assert by_key["gt_isolation"].reason


def test_build_evidence_dod_reflects_missing_cost_ledger(campaign_root: Path) -> None:
    (campaign_root / "cost" / "pod_ledger.jsonl").unlink()
    _, checklist = _build(campaign_root)
    by_key = {item.key: item for item in checklist}
    assert by_key["pod_costs_recorded"].satisfied is False
    assert "pod_ledger" in by_key["pod_costs_recorded"].reason


def test_build_evidence_dod_reflects_missing_cleanup_receipt(campaign_root: Path) -> None:
    (campaign_root / "evidence" / "cleanup_receipt.json").unlink()
    _, checklist = _build(campaign_root)
    by_key = {item.key: item for item in checklist}
    assert by_key["cleanup_verified"].satisfied is False


def test_build_evidence_source_hashes_deduped_by_case_key(campaign_root: Path) -> None:
    evidence_dir, _ = _build(campaign_root)
    path = evidence_dir / "source_hashes.jsonl"
    assert path.is_file()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    case_keys = [row["case_key"] for row in rows]
    assert len(case_keys) == len(set(case_keys))
