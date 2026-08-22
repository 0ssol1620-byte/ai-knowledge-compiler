"""Re-hash all public-core audit selections and quantify adaptive repeat savings."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark.runpod_eval.input_contract import select_inference_inputs
from benchmark.runpod_eval.public_core_sources import content_sha256, write_manifest

BENCHMARK_IDS = ("omnidocbench", "parsebench", "olmocr-bench")


def verify_public_audits(
    *, stage_root: Path, audit_manifest_dir: Path
) -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    seeds: set[str] = set()
    for benchmark_id in BENCHMARK_IDS:
        dataset_stage = stage_root / benchmark_id
        full_manifest_path = dataset_stage / "inference-input-manifest.json"
        audit_path = audit_manifest_dir / f"{benchmark_id}-stratified-audit.json"
        full_manifest = json.loads(full_manifest_path.read_text(encoding="utf-8"))
        audit_manifest = json.loads(audit_path.read_text(encoding="utf-8"))
        expected_count = int(audit_manifest.get("input_count", 0))
        selection = select_inference_inputs(
            input_dir=dataset_stage,
            supported_extensions={".png"},
            limit=0,
            evidence_class="stratified-audit",
            expected_input_count=expected_count,
            input_manifest=audit_path,
            parent_input_manifest=full_manifest_path,
        )
        if selection.benchmark_id != benchmark_id:
            raise ValueError(f"{benchmark_id} audit benchmark identity is invalid")
        if audit_manifest.get("parent_input_manifest_sha256") != full_manifest.get(
            "content_sha256"
        ):
            raise ValueError(f"{benchmark_id} audit is not bound to its full input manifest")
        if selection.dataset_revision != full_manifest.get("dataset_revision"):
            raise ValueError(f"{benchmark_id} audit revision is invalid")
        seed = audit_manifest.get("audit_seed")
        if not isinstance(seed, str) or not seed:
            raise ValueError(f"{benchmark_id} audit seed is invalid")
        seeds.add(seed)
        datasets.append(
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": selection.dataset_revision,
                "source_count": audit_manifest["source_count"],
                "audit_input_count": len(selection.selected),
                "audit_input_bytes": sum(path.stat().st_size for path in selection.selected),
                "stratum_count": audit_manifest["stratum_count"],
                "selection_sha256": audit_manifest["selection_sha256"],
                "audit_manifest_sha256": selection.input_manifest_sha256,
                "parent_input_manifest_sha256": full_manifest["content_sha256"],
                "passed": True,
            }
        )
    if len(seeds) != 1:
        raise ValueError("public benchmark audits must share one deterministic seed")
    full_inputs = sum(int(item["source_count"]) for item in datasets)
    audit_inputs = sum(int(item["audit_input_count"]) for item in datasets)
    blind_three_full = full_inputs * 3
    adaptive_stable = full_inputs + audit_inputs * 3
    saved = blind_three_full - adaptive_stable
    receipt: dict[str, Any] = {
        "schema": "folynta.public-core-stratified-audit-verification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_seed": next(iter(seeds)),
        "audit_repeat_count": 3,
        "same_selection_required_for_all_audits": True,
        "ground_truth_mounted": False,
        "total_source_count": full_inputs,
        "total_audit_input_count": audit_inputs,
        "blind_three_full_page_inferences": blind_three_full,
        "adaptive_stable_page_inferences": adaptive_stable,
        "saved_page_inferences": saved,
        "saved_page_inference_ratio": saved / blind_three_full,
        "datasets": datasets,
        "gate": "PASS",
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--audit-manifest-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = verify_public_audits(
        stage_root=args.stage_root,
        audit_manifest_dir=args.audit_manifest_dir,
    )
    write_manifest(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["verify_public_audits"]
