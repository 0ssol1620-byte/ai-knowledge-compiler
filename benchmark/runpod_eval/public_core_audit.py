"""Build deterministic, ground-truth-free stratified audit input manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from public_core_sources import canonical_json, content_sha256, write_manifest


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _load_full_manifest(path: Path, benchmark_id: str) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "folynta.public-core-inference-inputs.v1":
        raise ValueError("audit parent must be a public-core inference manifest")
    if manifest.get("benchmark_id") != benchmark_id:
        raise ValueError("audit benchmark does not match its parent manifest")
    if manifest.get("ground_truth_mounted") is not False:
        raise ValueError("audit parent manifest must be ground-truth-free")
    if manifest.get("content_sha256") != content_sha256(manifest):
        raise ValueError("audit parent manifest content hash is invalid")
    inputs = manifest.get("inputs")
    if (
        not isinstance(inputs, list)
        or manifest.get("source_count") != len(inputs)
        or manifest.get("input_count") != len(inputs)
        or manifest.get("complete_source_coverage") is not True
        or manifest.get("complete_input_coverage") is not True
    ):
        raise ValueError("audit parent manifest is incomplete")
    return cast(dict[str, Any], manifest)


def _omnidoc_strata(dataset_root: Path) -> dict[str, str]:
    rows = json.loads((dataset_root / "OmniDocBench.json").read_text(encoding="utf-8"))
    strata: dict[str, str] = {}
    for row in rows:
        page_info = row["page_info"]
        relative = f"images/{page_info['image_path']}"
        attributes = page_info.get("page_attribute", {})
        stratum = canonical_json(
            {
                "data_source": attributes.get("data_source"),
                "language": attributes.get("language"),
                "layout": attributes.get("layout"),
                "has_special_issue": bool(attributes.get("special_issue", [])),
            }
        )
        if relative in strata and strata[relative] != stratum:
            raise ValueError(f"OmniDoc source has conflicting strata: {relative}")
        strata[relative] = stratum
    return strata


def _path_stratum(benchmark_id: str, relative: str) -> str:
    parts = Path(relative).as_posix().split("/")
    if benchmark_id == "parsebench" and len(parts) >= 2 and parts[0] == "docs":
        return parts[1]
    if (
        benchmark_id == "olmocr-bench"
        and len(parts) >= 4
        and parts[:2] == ["bench_data", "pdfs"]
    ):
        return parts[2]
    raise ValueError(f"cannot derive public audit stratum: {benchmark_id}/{relative}")


def build_stratified_audit_manifest(
    *,
    full_input_manifest: Path,
    benchmark_id: str,
    dataset_root: Path,
    target_count: int,
    seed: str,
) -> dict[str, Any]:
    if benchmark_id not in {"omnidocbench", "parsebench", "olmocr-bench"}:
        raise ValueError(f"unsupported public benchmark: {benchmark_id}")
    if not seed or len(seed) > 128:
        raise ValueError("audit seed is required and must be at most 128 characters")
    parent = _load_full_manifest(full_input_manifest, benchmark_id)
    inputs = parent["inputs"]
    if not 0 < target_count < len(inputs):
        raise ValueError("audit target count must be positive and smaller than the full corpus")
    omni_strata = _omnidoc_strata(dataset_root) if benchmark_id == "omnidocbench" else {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in inputs:
        relative = str(item["source_relative_path"])
        raw_stratum = (
            omni_strata.get(relative)
            if benchmark_id == "omnidocbench"
            else _path_stratum(benchmark_id, relative)
        )
        if raw_stratum is None:
            raise ValueError(f"public source has no audit stratum: {relative}")
        stratum_id = "stratum-" + _hash_text(f"{benchmark_id}\n{raw_stratum}")[:16]
        groups[stratum_id].append(item)
    if target_count < len(groups):
        raise ValueError("audit target count must cover every observed stratum")
    ranked = {
        stratum: sorted(
            items,
            key=lambda item: (
                _hash_text(f"{seed}\n{item['case_id']}"),
                str(item["case_id"]),
            ),
        )
        for stratum, items in groups.items()
    }
    positions = {stratum: 0 for stratum in groups}
    selected: list[dict[str, Any]] = []
    while len(selected) < target_count:
        progressed = False
        for stratum in sorted(ranked):
            index = positions[stratum]
            if index >= len(ranked[stratum]):
                continue
            selected.append(ranked[stratum][index])
            positions[stratum] += 1
            progressed = True
            if len(selected) == target_count:
                break
        if not progressed:
            raise ValueError("audit selection exhausted before reaching its target")
    selected = sorted(selected, key=lambda item: str(item["case_id"]))
    selected_ids = {str(item["case_id"]) for item in selected}
    summary = [
        {
            "stratum_id": stratum,
            "source_count": len(items),
            "selected_count": sum(str(item["case_id"]) in selected_ids for item in items),
        }
        for stratum, items in sorted(groups.items())
    ]
    selection_digest = hashlib.sha256(
        canonical_json([item["case_id"] for item in selected]).encode()
    ).hexdigest()
    manifest: dict[str, Any] = {
        "schema": "folynta.public-core-stratified-audit.v1",
        "benchmark_id": benchmark_id,
        "dataset_revision": parent["dataset_revision"],
        "parent_input_manifest_sha256": parent["content_sha256"],
        "ground_truth_mounted": False,
        "source_count": len(inputs),
        "input_count": len(selected),
        "complete_source_coverage": False,
        "complete_input_coverage": True,
        "stratified": True,
        "audit_seed": seed,
        "stratum_count": len(groups),
        "stratum_summary": summary,
        "selection_sha256": f"sha256:{selection_digest}",
        "inputs": selected,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-input-manifest", type=Path, required=True)
    parser.add_argument(
        "--benchmark-id",
        choices=("omnidocbench", "parsebench", "olmocr-bench"),
        required=True,
    )
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--target-count", type=int, default=128)
    parser.add_argument("--seed", default="folynta-public-core-audit-v1")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_stratified_audit_manifest(
        full_input_manifest=args.full_input_manifest,
        benchmark_id=args.benchmark_id,
        dataset_root=args.dataset_root,
        target_count=args.target_count,
        seed=args.seed,
    )
    write_manifest(args.output, manifest)
    print(
        canonical_json(
            {
                "benchmark_id": manifest["benchmark_id"],
                "input_count": manifest["input_count"],
                "stratum_count": manifest["stratum_count"],
                "selection_sha256": manifest["selection_sha256"],
                "content_sha256": manifest["content_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_stratified_audit_manifest"]
