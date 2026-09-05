"""Build ``source_manifest.jsonl`` / ``campaign_manifest.json`` / ``canary_selection.json``.

``build_campaign`` is the pure, injectable core (used directly by tests
against a synthetic staged tree); ``arena.manifest.__main__`` wires it to the
real campaign paths from ``arena.constants``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arena.manifest.canary import build_canary_selection
from arena.manifest.gt_isolation import run_gt_isolation_audit, write_receipt
from arena.manifest.hashcache import HashCache
from arena.manifest.hashing import canonical_json, sha256_file, sha256_text
from arena.manifest.ids_local import compute_case_key, compute_sample_id
from arena.manifest.preflight import compute_preflight_features
from arena.manifest.schema_fields import SOURCE_ROW_FIELDS, SOURCE_ROW_SCHEMA

_CAMPAIGN_MANIFEST_SCHEMA = "tavonel.arena.campaign-manifest.v1"


class ManifestBuildError(RuntimeError):
    """Fail-closed error: something about a staged source is not trustworthy."""


@dataclass(frozen=True, slots=True)
class BenchmarkSource:
    key: str
    staged_id: str
    inputs_root: Path
    expected_count: int
    dataset_repository: str
    dataset_revision: str
    dataset_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class BuildConfig:
    campaign_id: str
    benchmarks: tuple[BenchmarkSource, ...]
    acquired_root: Path
    evaluator_cache_root: Path
    output_source_manifest: Path
    output_campaign_manifest: Path
    output_canary_selection: Path
    cache_path: Path
    receipts_dir: Path
    constants_path: Path
    canary_salt: str
    canary_pages_per_benchmark: int
    opus_canary_counts: Mapping[str, int]
    budget: Mapping[str, float]
    historical_evaluator_pins: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class BuildResult:
    unchanged: bool
    total_samples: int
    per_benchmark_counts: dict[str, int]
    source_manifest_path: Path
    campaign_manifest_path: Path
    canary_selection_path: Path
    gt_isolation_receipt_path: Path
    gt_isolation_passed: bool
    elapsed_seconds: float


def _load_staged_manifest(source: BenchmarkSource) -> dict[str, Any]:
    path = source.inputs_root / "inference-input-manifest.json"
    if not path.is_file():
        raise ManifestBuildError(f"staged manifest missing for {source.key}: {path}")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    content = {k: v for k, v in manifest.items() if k != "content_sha256"}
    recomputed = sha256_text(canonical_json(content))
    if manifest.get("content_sha256") != recomputed:
        raise ManifestBuildError(
            f"staged manifest content hash mismatch for {source.key} "
            f"(recorded={manifest.get('content_sha256')!r} recomputed={recomputed!r})"
        )
    if manifest.get("ground_truth_mounted") is not False:
        raise ManifestBuildError(f"{source.key} staged manifest is not marked GT-free")
    if manifest.get("benchmark_id") != source.staged_id:
        raise ManifestBuildError(
            f"{source.key} staged manifest benchmark_id={manifest.get('benchmark_id')!r} "
            f"!= expected {source.staged_id!r}"
        )
    if manifest.get("dataset_revision") != source.dataset_revision:
        raise ManifestBuildError(
            f"{source.key} staged dataset_revision={manifest.get('dataset_revision')!r} "
            f"!= locked revision {source.dataset_revision!r}"
        )
    items = manifest.get("inputs")
    if not isinstance(items, list) or len(items) != source.expected_count:
        actual = len(items) if isinstance(items, list) else "n/a"
        raise ManifestBuildError(
            f"{source.key} staged sample count {actual} != expected {source.expected_count}"
        )
    return manifest


def _build_rows_for_benchmark(
    source: BenchmarkSource,
    manifest: dict[str, Any],
    hash_cache: HashCache,
    seen_sample_ids: dict[str, str],
    seen_case_keys: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in manifest["inputs"]:
        case_key = compute_case_key(item["case_id"])
        sample_id = compute_sample_id(
            benchmark=source.key,
            source_relative_path=item["source_relative_path"],
            media_type=item["media_type"],
            page_index=item["page_index"],
        )
        if sample_id in seen_sample_ids:
            raise ManifestBuildError(
                f"duplicate sample_id across manifest: {sample_id} "
                f"(case_keys {seen_sample_ids[sample_id]!r} and {case_key!r})"
            )
        if case_key in seen_case_keys:
            raise ManifestBuildError(f"duplicate case_key across manifest: {case_key}")
        seen_sample_ids[sample_id] = case_key
        seen_case_keys.add(case_key)

        png_path = source.inputs_root / item["input_relative_path"]
        if not png_path.is_file():
            raise ManifestBuildError(f"staged PNG missing: {png_path}")
        png_bytes = png_path.stat().st_size
        if png_bytes == 0:
            raise ManifestBuildError(f"staged PNG is zero bytes: {png_path}")
        png_sha256 = hash_cache.hash_file(png_path, cache_key=str(png_path))
        if png_sha256 != item["input_sha256"]:
            raise ManifestBuildError(f"staged PNG hash drift for {case_key}: {png_path}")

        preflight = compute_preflight_features(png_path)
        input_relative_to_root = f"{source.staged_id}/{item['input_relative_path']}".replace(
            "\\", "/"
        )

        row: dict[str, Any] = {
            "schema": SOURCE_ROW_SCHEMA,
            "campaign_id": None,  # filled in by the caller
            "benchmark": source.key,
            "staged_benchmark_id": source.staged_id,
            "dataset_revision": source.dataset_revision,
            "sample_id": sample_id,
            "case_key": case_key,
            "original_source_relative_path": item["source_relative_path"],
            "original_source_sha256": item["source_sha256"],
            "media_type": item["media_type"],
            "page_index": item["page_index"],
            "input_relative_path": input_relative_to_root,
            "input_png_sha256": png_sha256,
            "width": preflight.width,
            "height": preflight.height,
            "bytes": png_bytes,
            "preflight": preflight.as_features_dict(),
        }
        if set(row) != SOURCE_ROW_FIELDS:
            raise ManifestBuildError(
                "internal error: constructed source row field set drifted from the contract "
                "whitelist"
            )
        rows.append(row)
    return rows


def _existing_build_is_current(config: BuildConfig) -> bool:
    if not (
        config.output_campaign_manifest.is_file()
        and config.output_source_manifest.is_file()
        and config.output_canary_selection.is_file()
    ):
        return False
    try:
        existing: Any = json.loads(config.output_campaign_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(existing, dict) or existing.get("campaign_id") != config.campaign_id:
        return False
    if existing.get("constants_sha256") != sha256_file(config.constants_path):
        return False
    benchmarks = existing.get("benchmarks")
    if not isinstance(benchmarks, dict):
        return False
    for source in config.benchmarks:
        entry = benchmarks.get(source.key)
        if not isinstance(entry, dict):
            return False
        staged_path = source.inputs_root / "inference-input-manifest.json"
        if not staged_path.is_file():
            return False
        try:
            staged = json.loads(staged_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if entry.get("staged_manifest_content_sha256") != staged.get("content_sha256"):
            return False
        if entry.get("dataset_revision") != source.dataset_revision:
            return False
        if entry.get("sample_count") != source.expected_count:
            return False
    return True


def _existing_counts(config: BuildConfig) -> tuple[int, dict[str, int]]:
    existing: dict[str, Any] = json.loads(
        config.output_campaign_manifest.read_text(encoding="utf-8")
    )
    per_benchmark = {
        key: int(entry["sample_count"]) for key, entry in existing["benchmarks"].items()
    }
    return int(existing["total_samples"]), per_benchmark


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build_campaign(config: BuildConfig, *, force: bool = False) -> BuildResult:
    started = time.monotonic()

    if not force and _existing_build_is_current(config):
        total, per_benchmark = _existing_counts(config)
        receipt_path = config.receipts_dir / _latest_gt_isolation_receipt_name(config.receipts_dir)
        existing_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        return BuildResult(
            unchanged=True,
            total_samples=total,
            per_benchmark_counts=per_benchmark,
            source_manifest_path=config.output_source_manifest,
            campaign_manifest_path=config.output_campaign_manifest,
            canary_selection_path=config.output_canary_selection,
            gt_isolation_receipt_path=receipt_path,
            gt_isolation_passed=bool(existing_receipt.get("passed")),
            elapsed_seconds=time.monotonic() - started,
        )

    hash_cache = HashCache(config.cache_path)
    seen_sample_ids: dict[str, str] = {}
    seen_case_keys: set[str] = set()
    all_rows: list[dict[str, Any]] = []
    staged_manifests: dict[str, dict[str, Any]] = {}
    per_benchmark_summary: dict[str, dict[str, Any]] = {}

    for source in sorted(config.benchmarks, key=lambda s: s.key):
        manifest = _load_staged_manifest(source)
        staged_manifests[source.key] = manifest
        rows = _build_rows_for_benchmark(
            source, manifest, hash_cache, seen_sample_ids, seen_case_keys
        )
        for row in rows:
            row["campaign_id"] = config.campaign_id
        all_rows.extend(rows)
        per_benchmark_summary[source.key] = {
            "sample_count": len(rows),
            "staged_manifest_content_sha256": manifest["content_sha256"],
        }

    hash_cache.flush()

    all_rows.sort(key=lambda row: str(row["sample_id"]))
    manifest_lines = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) for row in all_rows
    )
    _atomic_write_text(config.output_source_manifest, manifest_lines + "\n" if all_rows else "")

    benchmarks_field: dict[str, Any] = {}
    for source in config.benchmarks:
        summary = per_benchmark_summary[source.key]
        benchmarks_field[source.key] = {
            "staged_benchmark_id": source.staged_id,
            "dataset_repository": source.dataset_repository,
            "dataset_revision": source.dataset_revision,
            "dataset_manifest_sha256": source.dataset_manifest_sha256,
            "sample_count": summary["sample_count"],
            "inputs_root": str(source.inputs_root.resolve()),
            "staged_manifest_content_sha256": summary["staged_manifest_content_sha256"],
        }
    total_samples = sum(int(v["sample_count"]) for v in benchmarks_field.values())

    inputs_roots = {source.key: source.inputs_root for source in config.benchmarks}
    gt_isolation_receipt = run_gt_isolation_audit(
        campaign_id=config.campaign_id,
        inputs_roots=inputs_roots,
        acquired_root=config.acquired_root,
        evaluator_cache_root=config.evaluator_cache_root,
        source_manifest_path=config.output_source_manifest,
        staged_manifests=staged_manifests,
    )
    gt_isolation_path = write_receipt(gt_isolation_receipt, config.receipts_dir)

    campaign_manifest = {
        "schema": _CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": config.campaign_id,
        "created_at": datetime.now(UTC).isoformat(),
        "benchmarks": benchmarks_field,
        "total_samples": total_samples,
        "source_manifest_sha256": sha256_file(config.output_source_manifest),
        "constants_sha256": sha256_file(config.constants_path),
        "budget": dict(config.budget),
        "historical_evaluator_pins": dict(config.historical_evaluator_pins),
        "canary": {
            "salt": config.canary_salt,
            "pages_per_benchmark": config.canary_pages_per_benchmark,
            "opus_pages": sum(config.opus_canary_counts.values()),
        },
        "gt_isolation_receipt_sha256": sha256_file(gt_isolation_path),
    }
    _atomic_write_text(
        config.output_campaign_manifest,
        json.dumps(campaign_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    canary_selection = build_canary_selection(
        all_rows,
        campaign_id=config.campaign_id,
        salt=config.canary_salt,
        gpu_pages_per_benchmark=config.canary_pages_per_benchmark,
        opus_canary_counts=config.opus_canary_counts,
    )
    _atomic_write_text(
        config.output_canary_selection,
        json.dumps(canary_selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    if not gt_isolation_receipt["passed"]:
        raise ManifestBuildError(
            f"GT isolation audit FAILED: {gt_isolation_receipt['checks']}; "
            f"receipt written to {gt_isolation_path}"
        )

    return BuildResult(
        unchanged=False,
        total_samples=total_samples,
        per_benchmark_counts={k: int(v["sample_count"]) for k, v in benchmarks_field.items()},
        source_manifest_path=config.output_source_manifest,
        campaign_manifest_path=config.output_campaign_manifest,
        canary_selection_path=config.output_canary_selection,
        gt_isolation_receipt_path=gt_isolation_path,
        gt_isolation_passed=True,
        elapsed_seconds=time.monotonic() - started,
    )


def _latest_gt_isolation_receipt_name(receipts_dir: Path) -> str:
    candidates = sorted(receipts_dir.glob("gt-isolation-*.json"))
    if not candidates:
        raise ManifestBuildError(
            f"no gt-isolation receipt found under {receipts_dir}; run build without an existing "
            "campaign_manifest.json, or with --force"
        )
    return candidates[-1].name


def load_source_rows(source_manifest_path: Path) -> Sequence[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with source_manifest_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


__all__ = [
    "BenchmarkSource",
    "BuildConfig",
    "BuildResult",
    "ManifestBuildError",
    "build_campaign",
    "load_source_rows",
]
