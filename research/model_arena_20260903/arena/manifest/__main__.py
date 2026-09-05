"""CLI: ``python -m arena.manifest build [--force]`` / ``python -m arena.manifest audit``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from arena.constants import (
    ACQUIRED_PUBLIC_CORE_ROOT,
    BENCHMARK_KEYS,
    BENCHMARK_REGISTRY_LOCK,
    BUDGET_HARD_CAP_USD,
    BUDGET_SOFT_CAP_USD,
    BUDGET_TARGET_USD,
    CAMPAIGN_ID,
    CANARY_PAGES_PER_BENCHMARK,
    CANARY_SALT,
    EVALUATOR_CACHE_ROOT,
    EXPECTED_SAMPLE_COUNTS,
    HISTORICAL_EVALUATOR_PINS,
    NAMESPACE_ROOT,
    OPUS_CANARY_PAGES,
    STAGED_BENCHMARK_ID,
    STAGED_PUBLIC_CORE_ROOT,
)
from arena.manifest.build import BenchmarkSource, BuildConfig, ManifestBuildError, build_campaign
from arena.manifest.gt_isolation import run_gt_isolation_audit, write_receipt

# Masterplan section 17: 50 opus canary pages split 17/17/16 across
# parsebench/omnidoc/olmocr.
_OPUS_CANARY_COUNTS: dict[str, int] = {"parsebench": 17, "omnidoc": 17, "olmocr": 16}
if sum(_OPUS_CANARY_COUNTS.values()) != OPUS_CANARY_PAGES:
    raise AssertionError("opus canary per-benchmark split no longer sums to OPUS_CANARY_PAGES")


def _load_lock_entry(lock_path: Path, staged_id: str) -> dict[str, Any]:
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    for entry in lock.get("benchmarks", []):
        if entry.get("id") == staged_id:
            dataset = entry["dataset"]
            return {
                "repository": str(dataset["repository"]),
                "revision": str(dataset["revision"]),
                "manifest_sha256": str(dataset["manifest_sha256"]),
            }
    raise ManifestBuildError(f"no benchmark-registry.lock.yaml entry for id={staged_id!r}")


def _default_benchmark_sources() -> tuple[BenchmarkSource, ...]:
    sources: list[BenchmarkSource] = []
    for key in BENCHMARK_KEYS:
        staged_id = STAGED_BENCHMARK_ID[key]
        lock_entry = _load_lock_entry(BENCHMARK_REGISTRY_LOCK, staged_id)
        sources.append(
            BenchmarkSource(
                key=key,
                staged_id=staged_id,
                inputs_root=STAGED_PUBLIC_CORE_ROOT / staged_id,
                expected_count=EXPECTED_SAMPLE_COUNTS[key],
                dataset_repository=lock_entry["repository"],
                dataset_revision=lock_entry["revision"],
                dataset_manifest_sha256=lock_entry["manifest_sha256"],
            )
        )
    return tuple(sources)


def _default_config() -> BuildConfig:
    return BuildConfig(
        campaign_id=CAMPAIGN_ID,
        benchmarks=_default_benchmark_sources(),
        acquired_root=ACQUIRED_PUBLIC_CORE_ROOT,
        evaluator_cache_root=EVALUATOR_CACHE_ROOT,
        output_source_manifest=NAMESPACE_ROOT / "source_manifest.jsonl",
        output_campaign_manifest=NAMESPACE_ROOT / "campaign_manifest.json",
        output_canary_selection=NAMESPACE_ROOT / "canary_selection.json",
        cache_path=NAMESPACE_ROOT / "receipts" / "manifest-hash-cache.json",
        receipts_dir=NAMESPACE_ROOT / "receipts",
        constants_path=NAMESPACE_ROOT / "arena" / "constants.py",
        canary_salt=CANARY_SALT,
        canary_pages_per_benchmark=CANARY_PAGES_PER_BENCHMARK,
        opus_canary_counts=_OPUS_CANARY_COUNTS,
        budget={
            "target_usd": BUDGET_TARGET_USD,
            "soft_cap_usd": BUDGET_SOFT_CAP_USD,
            "hard_cap_usd": BUDGET_HARD_CAP_USD,
        },
        historical_evaluator_pins=dict(HISTORICAL_EVALUATOR_PINS),
    )


def _cmd_build(args: argparse.Namespace) -> int:
    config = _default_config()
    try:
        result = build_campaign(config, force=args.force)
    except ManifestBuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "unchanged": result.unchanged,
                "total_samples": result.total_samples,
                "per_benchmark_counts": result.per_benchmark_counts,
                "source_manifest_path": str(result.source_manifest_path),
                "campaign_manifest_path": str(result.campaign_manifest_path),
                "canary_selection_path": str(result.canary_selection_path),
                "gt_isolation_receipt_path": str(result.gt_isolation_receipt_path),
                "gt_isolation_passed": result.gt_isolation_passed,
                "elapsed_seconds": round(result.elapsed_seconds, 3),
            },
            sort_keys=True,
        )
    )
    return 0 if result.gt_isolation_passed else 1


def _cmd_audit(_args: argparse.Namespace) -> int:
    config = _default_config()
    source_manifest_path = config.output_source_manifest
    if not source_manifest_path.is_file():
        print(
            f"AUDIT FAILED: no source manifest at {source_manifest_path}; run "
            "`python -m arena.manifest build` first",
            file=sys.stderr,
        )
        return 1

    staged_manifests: dict[str, dict[str, Any]] = {}
    inputs_roots: dict[str, Path] = {}
    for source in config.benchmarks:
        inputs_roots[source.key] = source.inputs_root
        staged_path = source.inputs_root / "inference-input-manifest.json"
        if not staged_path.is_file():
            print(f"AUDIT FAILED: staged manifest missing: {staged_path}", file=sys.stderr)
            return 1
        staged_manifests[source.key] = json.loads(staged_path.read_text(encoding="utf-8"))

    receipt = run_gt_isolation_audit(
        campaign_id=config.campaign_id,
        inputs_roots=inputs_roots,
        acquired_root=config.acquired_root,
        evaluator_cache_root=config.evaluator_cache_root,
        source_manifest_path=source_manifest_path,
        staged_manifests=staged_manifests,
    )
    receipt_path = write_receipt(receipt, config.receipts_dir)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if not receipt["passed"]:
        print(f"AUDIT FAILED: see {receipt_path}", file=sys.stderr)
        return 1
    print(f"AUDIT PASSED: {receipt_path}", file=sys.stderr)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m arena.manifest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="build the source/campaign/canary manifests")
    build_parser.add_argument(
        "--force", action="store_true", help="rebuild even if the existing manifests look current"
    )
    build_parser.set_defaults(func=_cmd_build)

    audit_parser = subparsers.add_parser("audit", help="run the GT isolation audit standalone")
    audit_parser.set_defaults(func=_cmd_audit)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
