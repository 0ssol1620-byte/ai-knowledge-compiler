"""Verify exact public-core revisions and materialized Git LFS payloads."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from benchmark.v6.contracts import canonical_sha256


def verify_public_core(repo_root: Path, acquisition_root: Path) -> dict[str, Any]:
    registry = yaml.safe_load(
        (repo_root / "benchmark/v6/dataset-registry.lock.yaml").read_text(encoding="utf-8")
    )
    rows = registry["public_core"]
    reports = []
    all_pass = True
    for row in rows:
        benchmark_id = str(row["id"])
        local_name = {"olmocr-bench": "olmocr-bench"}.get(benchmark_id, benchmark_id)
        local_path = acquisition_root / local_name
        revision = _git(local_path, "rev-parse", "HEAD").strip()
        status = _git(local_path, "status", "--short").strip()
        lfs = json.loads(_git(local_path, "lfs", "ls-files", "--json"))
        manifest = []
        missing = []
        for item in lfs["files"]:
            file_path = local_path / str(item["name"])
            expected_size = int(item["size"])
            actual_size = file_path.stat().st_size if file_path.is_file() else -1
            manifest.append(
                {"path": str(item["name"]), "oid": str(item["oid"]), "size": expected_size}
            )
            if actual_size != expected_size:
                missing.append(str(item["name"]))
        passed = revision == row["dataset_revision"] and not status and not missing
        all_pass = all_pass and passed
        reports.append(
            {
                "benchmark_id": benchmark_id,
                "dataset_revision": revision,
                "expected_dataset_revision": row["dataset_revision"],
                "registry_manifest_sha256": row["dataset_manifest_sha256"],
                "materialized_lfs_manifest_sha256": canonical_sha256(manifest),
                "lfs_file_count": len(manifest),
                "lfs_total_bytes": sum(int(item["size"]) for item in manifest),
                "missing_or_pointer_count": len(missing),
                "worktree_clean": not status,
                "passed": passed,
            }
        )
    receipt = {
        "schema": "folynta.public-core-acquisition.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "ground_truth_mount_policy": "evaluator_only",
        "inference_ground_truth_access": "forbidden",
        "datasets": reports,
        "gate": "PASS" if all_pass else "FAIL",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def _git(path: Path, *args: str) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("git is required to verify public-core acquisition")
    result = subprocess.run(  # noqa: S603 - fixed executable and internal arguments only
        [git_executable, "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--acquisition-root",
        type=Path,
        default=Path("benchmark/datasets/acquired/public-core"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = verify_public_core(
        args.repo_root.resolve(strict=True),
        args.acquisition_root.resolve(strict=True),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if receipt["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
