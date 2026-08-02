#!/usr/bin/env python3
"""Run official OmniDocBench partial metrics over frozen inference repeats.

CDM is intentionally excluded from this portable lane because it requires a
separate TeX/ImageMagick/Ghostscript rendering toolchain. A complete CDM run is
reported through its own environment rather than silently becoming a zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def yaml_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def render_config(*, ground_truth: Path, prediction: Path, workers: int) -> str:
    return f"""end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: {workers}
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: '{yaml_path(ground_truth)}'
    prediction:
      data_path: '{yaml_path(prediction)}'
    match_method: quick_match
    match_workers: {workers}
    quick_match_truncated_timeout_sec: 300
    match_timeout_sec: 420
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
"""


def require_exact_page_count(metric_result: object, prediction: Path) -> int:
    if not isinstance(metric_result, dict):
        raise ValueError("official evaluator result must be an object")
    debug = metric_result.get("match_debug")
    if not isinstance(debug, dict):
        raise ValueError("official evaluator result is missing match_debug")
    measured = int(debug.get("page_count", 0))
    expected = sum(1 for path in prediction.glob("*.md") if path.is_file())
    if expected < 1:
        raise ValueError("prediction directory contains no Markdown pages")
    if measured != expected:
        raise ValueError(
            "official evaluator page count differs from frozen predictions: "
            f"expected {expected}, received {measured}"
        )
    return measured


def evaluator_revision(evaluator_dir: Path) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git is required to freeze the evaluator revision")
    result = subprocess.run(
        [executable, "rev-parse", "HEAD"],
        cwd=evaluator_dir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def run_evaluation(
    *,
    evaluator_dir: Path,
    ground_truth: Path,
    predictions_root: Path,
    output_dir: Path,
    repeats: int,
    workers: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    revision = evaluator_revision(evaluator_dir)
    records: list[dict[str, object]] = []
    for repeat_index in range(1, repeats + 1):
        prediction = predictions_root / f"markdown-repeat-{repeat_index}"
        if not prediction.is_dir():
            raise FileNotFoundError(f"missing prediction directory: {prediction}")
        repeat_dir = output_dir / f"repeat-{repeat_index}"
        repeat_dir.mkdir(parents=True, exist_ok=True)
        config_path = repeat_dir / "omnidoc-partial.yaml"
        config_path.write_text(
            render_config(ground_truth=ground_truth, prediction=prediction, workers=workers),
            encoding="utf-8",
        )
        started = time.time()
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        process = subprocess.run(
            [sys.executable, "pdf_validation.py", "--config", str(config_path)],
            cwd=evaluator_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        (repeat_dir / "stdout.log").write_text(process.stdout, encoding="utf-8")
        (repeat_dir / "stderr.log").write_text(process.stderr, encoding="utf-8")
        if process.returncode != 0:
            raise RuntimeError(f"OmniDocBench repeat {repeat_index} failed: {process.returncode}")

        prefix = f"{prediction.name}_quick_match"
        source_result = evaluator_dir / "result" / f"{prefix}_metric_result.json"
        if not source_result.is_file():
            raise FileNotFoundError(f"missing official metric result: {source_result}")
        destination = repeat_dir / "metric-result.json"
        shutil.copy2(source_result, destination)
        parsed = json.loads(destination.read_text(encoding="utf-8"))
        page_count = require_exact_page_count(parsed, prediction)
        records.append(
            {
                "repeat_index": repeat_index,
                "elapsed_seconds": time.time() - started,
                "metric_result_sha256": sha256_file(destination),
                "page_count": page_count,
            }
        )

    summary = {
        "schema_version": "1.0.0",
        "evaluator": "OmniDocBench",
        "evaluator_revision": revision,
        "metric_scope": [
            "text_edit_distance",
            "formula_edit_distance",
            "table_teds",
            "table_edit_distance",
            "reading_order_edit_distance",
        ],
        "excluded_metric": {
            "name": "CDM",
            "reason": "portable evaluator lane has no validated rendering toolchain",
        },
        "ground_truth_sha256": sha256_file(ground_truth),
        "records": records,
    }
    (output_dir / "evaluation-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator-dir", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--predictions-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_evaluation(
        evaluator_dir=args.evaluator_dir.resolve(),
        ground_truth=args.ground_truth.resolve(),
        predictions_root=args.predictions_root.resolve(),
        output_dir=args.output_dir.resolve(),
        repeats=args.repeats,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
