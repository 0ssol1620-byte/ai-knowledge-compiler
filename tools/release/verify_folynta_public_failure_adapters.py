"""Bind official public evaluator type inventories to the 18-code adapters."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.v6.contracts import canonical_sha256
from benchmark.v6.public_failure_adapter import PUBLIC_FAILURE_RULES


def _jsonl_type_counts(paths: tuple[Path, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in paths:
        if not path.is_file():
            raise ValueError(f"official evaluator index is missing: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            evaluator_type = row.get("type")
            if not isinstance(evaluator_type, str) or not evaluator_type:
                raise ValueError(f"official evaluator type is missing: {path}")
            counts[evaluator_type] += 1
    return counts


def _omnidoc_metric_types(config_path: Path) -> set[str]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    metrics = config.get("end2end_eval", {}).get("metrics") if isinstance(config, dict) else None
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("OmniDocBench evaluator metric inventory is missing")
    return {str(name) for name in metrics}


def _mapping_payload(benchmark_id: str) -> list[dict[str, str | bool]]:
    return [
        {
            "evaluator_type": evaluator_type,
            "failure_code": rule.failure_code,
            "minimum_scope": rule.minimum_scope,
            "request_recovery": rule.failure_code not in {"T03", "H01", "H02"},
        }
        for evaluator_type, rule in sorted(PUBLIC_FAILURE_RULES[benchmark_id].items())
    ]


def verify_public_failure_adapters(
    *,
    acquisition_receipt: Path,
    omnidoc_config: Path,
    parsebench_root: Path,
    olmocr_root: Path,
) -> dict[str, Any]:
    acquisition = json.loads(acquisition_receipt.read_text(encoding="utf-8"))
    if acquisition.get("gate") != "PASS":
        raise ValueError("public-core acquisition gate is not PASS")
    revisions = {
        str(item["benchmark_id"]): str(item["dataset_revision"])
        for item in acquisition["datasets"]
        if item.get("passed") is True
    }
    parse_files = tuple(
        parsebench_root / filename
        for filename in (
            "chart.jsonl",
            "layout.jsonl",
            "table.jsonl",
            "text_content.jsonl",
            "text_formatting.jsonl",
        )
    )
    parse_counts = _jsonl_type_counts(parse_files)
    olm_files = tuple(sorted((olmocr_root / "bench_data").glob("*.jsonl")))
    if not olm_files:
        raise ValueError("olmOCR-Bench evaluator indexes are missing")
    olm_counts = _jsonl_type_counts(olm_files)
    omni_types = _omnidoc_metric_types(omnidoc_config)

    observed = {
        "omnidocbench": omni_types | {"missing_page"},
        "parsebench": set(parse_counts),
        "olmocr-bench": set(olm_counts),
    }
    for benchmark_id, observed_types in observed.items():
        registered_types = set(PUBLIC_FAILURE_RULES[benchmark_id])
        if registered_types != observed_types:
            missing = sorted(observed_types - registered_types)
            stale = sorted(registered_types - observed_types)
            raise ValueError(
                f"{benchmark_id} adapter inventory mismatch; missing={missing}, stale={stale}"
            )
        if benchmark_id not in revisions:
            raise ValueError(f"{benchmark_id} has no passed acquisition revision")

    datasets = [
        {
            "benchmark_id": "omnidocbench",
            "dataset_revision": revisions["omnidocbench"],
            "evaluator_type_count": len(observed["omnidocbench"]),
            "evaluator_assertion_count": None,
            "mapping": _mapping_payload("omnidocbench"),
            "passed": True,
        },
        {
            "benchmark_id": "parsebench",
            "dataset_revision": revisions["parsebench"],
            "evaluator_type_count": len(parse_counts),
            "evaluator_assertion_count": sum(parse_counts.values()),
            "mapping": _mapping_payload("parsebench"),
            "passed": True,
        },
        {
            "benchmark_id": "olmocr-bench",
            "dataset_revision": revisions["olmocr-bench"],
            "evaluator_type_count": len(olm_counts),
            "evaluator_assertion_count": sum(olm_counts.values()),
            "mapping": _mapping_payload("olmocr-bench"),
            "passed": True,
        },
    ]
    receipt: dict[str, Any] = {
        "schema": "folynta.public-failure-adapter-verification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "acquisition_receipt_sha256": acquisition["receipt_sha256"],
        "unknown_type_policy": "fail-closed",
        "ground_truth_mount_policy": "evaluator-only",
        "datasets": datasets,
        "gate": "PASS",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-receipt", type=Path, required=True)
    parser.add_argument("--omnidoc-config", type=Path, required=True)
    parser.add_argument("--parsebench-root", type=Path, required=True)
    parser.add_argument("--olmocr-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = verify_public_failure_adapters(
        acquisition_receipt=args.acquisition_receipt,
        omnidoc_config=args.omnidoc_config,
        parsebench_root=args.parsebench_root,
        olmocr_root=args.olmocr_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["verify_public_failure_adapters"]
