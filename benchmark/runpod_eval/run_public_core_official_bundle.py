#!/usr/bin/env python3
"""Run the three frozen public-core evaluators under one repeatable contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build_public_failure_records import EvaluationSource, build_failure_records


@dataclass(frozen=True, slots=True)
class EvaluationCommand:
    benchmark_id: str
    python: Path
    arguments: tuple[str, ...]
    output_root: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_official_commands(
    *,
    repository_root: Path,
    merged_root: Path,
    output_root: Path,
    parsebench_max_workers: int = 8,
    omnidoc_workers: int = 4,
) -> tuple[EvaluationCommand, ...]:
    """Build the three evaluator invocations.

    The two worker counts are a machine knob, not part of the contract. Eight
    ParseBench workers each load scipy, and on a 32 GB workstation that already
    held a benchmark corpus the Windows page file could not commit them: every
    one of the 568 chart evaluations failed with "DLL load failed ... the paging
    file is too small", which the evaluator reports as "worker error" against an
    unknown example. Lowering the count changes how long the run takes and
    nothing about what it measures.
    """
    runpod_eval = repository_root / "benchmark" / "runpod_eval"
    acquired = repository_root / "benchmark" / "datasets" / "acquired" / "public-core"
    checkouts = (
        repository_root / "benchmark" / "datasets" / "private" / "evaluator-checkouts"
    )
    manifests = repository_root / "benchmark" / "reports" / "generated" / "public-core-manifests"
    return (
        EvaluationCommand(
            benchmark_id="parsebench",
            python=repository_root
            / "benchmark"
            / "cache"
            / "parsebench"
            / ".venv"
            / "Scripts"
            / "python.exe",
            arguments=(
                str(runpod_eval / "evaluate_parsebench_official.py"),
                "--evaluator-dir",
                str(checkouts / "parsebench"),
                "--predictions-root",
                str(merged_root / "official" / "parsebench"),
                "--dataset-root",
                str(acquired / "parsebench"),
                "--source-manifest",
                str(manifests / "parsebench-source-manifest.json"),
                "--output-root",
                str(output_root / "parsebench"),
                "--max-workers",
                str(parsebench_max_workers),
            ),
            output_root=output_root / "parsebench",
        ),
        EvaluationCommand(
            benchmark_id="omnidocbench",
            python=repository_root
            / "benchmark"
            / "cache"
            / "omnidoc"
            / ".venv"
            / "Scripts"
            / "python.exe",
            arguments=(
                str(runpod_eval / "evaluate_omnidoc_repeats.py"),
                "--evaluator-dir",
                str(checkouts / "omnidocbench"),
                "--ground-truth",
                str(acquired / "omnidocbench" / "OmniDocBench.json"),
                "--predictions-root",
                str(merged_root / "official" / "omnidocbench"),
                "--output-dir",
                str(output_root / "omnidocbench"),
                "--source-manifest",
                str(manifests / "omnidocbench-source-manifest.json"),
                "--repeats",
                "1",
                "--workers",
                str(omnidoc_workers),
            ),
            output_root=output_root / "omnidocbench",
        ),
        EvaluationCommand(
            benchmark_id="olmocr-bench",
            python=repository_root
            / "benchmark"
            / "datasets"
            / "private"
            / "evaluator-venvs"
            / "olmocr"
            / "Scripts"
            / "python.exe",
            arguments=(
                str(runpod_eval / "evaluate_olmocr_official.py"),
                "--evaluator-dir",
                str(checkouts / "olmocr-bench"),
                "--dataset-root",
                str(acquired / "olmocr-bench"),
                "--candidate-dir",
                str(merged_root / "official" / "olmocr-bench" / "mineru344"),
                "--source-manifest",
                str(manifests / "olmocr-bench-source-manifest.json"),
                "--output-root",
                str(output_root / "olmocr-bench"),
                "--bootstrap-samples",
                "2000",
            ),
            output_root=output_root / "olmocr-bench",
        ),
    )


def run_official_bundle(
    *,
    repository_root: Path,
    merged_root: Path,
    output_root: Path,
    failure_records: Path,
    parsebench_max_workers: int = 8,
    omnidoc_workers: int = 4,
) -> dict[str, Any]:
    merge_receipt_path = merged_root / "merge-receipt.json"
    merge_receipt = json.loads(merge_receipt_path.read_text(encoding="utf-8"))
    if (
        int(merge_receipt.get("completed", -1)) != 5132
        or int(merge_receipt.get("failed", -1)) != 0
        or merge_receipt.get("complete_case_coverage") is not True
    ):
        raise ValueError("official bundle requires 5,132 completed predictions")
    output_root.mkdir(parents=True, exist_ok=True)
    logs = output_root / "orchestrator-logs"
    logs.mkdir(exist_ok=True)
    commands = build_official_commands(
        repository_root=repository_root,
        merged_root=merged_root,
        output_root=output_root,
        parsebench_max_workers=parsebench_max_workers,
        omnidoc_workers=omnidoc_workers,
    )
    evaluations: list[dict[str, Any]] = []
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    for command in commands:
        summary_path = command.output_root / "evaluation-summary.json"
        if not summary_path.is_file():
            result = subprocess.run(
                [str(command.python), *command.arguments],
                cwd=repository_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            (logs / f"{command.benchmark_id}.stdout.log").write_text(
                result.stdout, encoding="utf-8"
            )
            (logs / f"{command.benchmark_id}.stderr.log").write_text(
                result.stderr, encoding="utf-8"
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"official evaluator failed: {command.benchmark_id}/{result.returncode}"
                )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        evaluations.append(
            {
                "benchmark_id": command.benchmark_id,
                "evaluator_revision": str(summary["evaluator_revision"]),
                "evaluation_summary_sha256": _sha256(summary_path),
            }
        )

    if not failure_records.is_file():
        build_failure_records(
            merged_root=merged_root,
            evaluations=tuple(
                EvaluationSource(command.benchmark_id, command.output_root)
                for command in commands
            ),
            output_path=failure_records,
        )
    failures = json.loads(failure_records.read_text(encoding="utf-8"))
    receipt = {
        "schema": "folynta.public-core-official-evaluation-bundle.v1",
        "merge_receipt_sha256": _sha256(merge_receipt_path),
        "input_count": 5132,
        "evaluations": evaluations,
        "official_failure_record_count": int(failures["record_count"]),
        "recoverable_case_count": int(failures["recoverable_case_count"]),
        "failure_records_sha256": _sha256(failure_records),
    }
    receipt_path = output_root / "official-evaluation-bundle-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return {**receipt, "receipt_sha256": _sha256(receipt_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--merged-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--failure-records", type=Path, required=True)
    parser.add_argument("--parsebench-max-workers", type=int, default=8)
    parser.add_argument("--omnidoc-workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_official_bundle(
        repository_root=args.repository_root.resolve(),
        merged_root=args.merged_root.resolve(),
        output_root=args.output_root.resolve(),
        failure_records=args.failure_records.resolve(),
        parsebench_max_workers=args.parsebench_max_workers,
        omnidoc_workers=args.omnidoc_workers,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EvaluationCommand", "build_official_commands", "run_official_bundle"]
