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
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def yaml_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def render_config(
    *,
    ground_truth: Path,
    prediction: Path,
    workers: int,
    quick_match_timeout_seconds: int = 60,
    page_match_timeout_seconds: int = 90,
) -> str:
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
    quick_match_truncated_timeout_sec: {quick_match_timeout_seconds}
    match_timeout_sec: {page_match_timeout_seconds}
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
"""


def count_frozen_markdown_pages(prediction: Path) -> int:
    """Count the frozen Markdown pages under ``prediction``.

    Windows rejects non-extended paths longer than MAX_PATH (260). OmniDocBench
    ships CJK source names that push some prediction paths past that limit, and
    ``Path.is_file`` swallows the resulting WinError 3 and reports ``False``,
    which silently undercounts real pages. ``os.scandir`` answers from the
    directory entry itself, so it stays exact regardless of path length.
    """
    total = 0
    with os.scandir(prediction) as entries:
        for entry in entries:
            if not entry.name.lower().endswith(".md"):
                continue
            try:
                is_file = entry.is_file()
            except OSError:
                is_file = entry.is_file(follow_symlinks=False)
            if is_file:
                total += 1
    return total


def require_exact_page_count(metric_result: object, prediction: Path) -> int:
    if not isinstance(metric_result, dict):
        raise ValueError("official evaluator result must be an object")
    debug = metric_result.get("match_debug")
    if not isinstance(debug, dict):
        raise ValueError("official evaluator result is missing match_debug")
    measured = int(debug.get("page_count", 0))
    expected = count_frozen_markdown_pages(prediction)
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


def _case_lookup(source_manifest: Path) -> dict[str, str]:
    payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    if payload.get("schema") == "folynta.public-core-source-manifest.v1":
        items = payload.get("sources", [])
        expected_count = int(payload.get("source_count", -1))
    else:
        items = payload.get("inputs", [])
        expected_count = int(payload.get("input_count", -1))
    result: dict[str, str] = {}
    for item in items:
        stem = Path(str(item["source_relative_path"])).stem
        if stem in result:
            raise ValueError(f"duplicate OmniDocBench source stem: {stem}")
        result[stem] = str(item["case_id"])
    if len(result) != expected_count:
        raise ValueError("OmniDocBench source manifest coverage is invalid")
    return result


def strip_element_suffix(location: str) -> str:
    """Return the page name behind an official OmniDocBench detail key.

    Per-page artifacts key on the bare image name. ``table_per_table_TEDS.json``
    appends a per-table ``_[index]`` suffix. Four OmniDocBench sources are named
    ``book_en_[搬书匠#20][HTML5 Canvas].2011.英文版_page_208.png`` and friends, so
    splitting on the first ``_[`` truncates a real page down to ``book_en``.
    Only a trailing element suffix is removed; image names always end in a file
    extension, never in ``]``.
    """
    if location.endswith("]") and "_[" in location:
        return location.rsplit("_[", 1)[0]
    return location


def _safe_location(value: str) -> str:
    """Render an ASCII identifier that stays unique per official location.

    The recovery taxonomy accepts ``[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}`` only.
    ``str.isalnum`` is Unicode-aware, so it used to pass CJK page names straight
    through into an identifier the adapter then rejected. Folding those to ``-``
    is lossy and can merge two distinct pages, so whenever the fold or the
    length cap drops information the original value is bound back through a
    SHA-256 prefix.
    """
    rendered = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "._:/-")
        else "-"
        for character in value
    )
    if rendered == value and len(value) <= 512:
        return rendered.strip("-") or "unknown"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    stem = rendered[:495].strip("-")
    return f"{stem}-{digest}" if stem else f"location-{digest}"


def extract_official_failures(
    *, official_artifact_dir: Path,
    source_manifest: Path,
    output_path: Path,
) -> dict[str, Any]:
    lookup = _case_lookup(source_manifest)
    specifications = (
        ("text_block_per_page_edit.json", "text_block", "edit_distance", False),
        ("display_formula_per_page_edit.json", "display_formula", "edit_distance", False),
        ("table_per_page_edit.json", "table", "edit_distance", False),
        ("reading_order_per_page_edit.json", "reading_order", "edit_distance", False),
        ("table_per_table_TEDS.json", "table", "teds", True),
    )
    failures: list[dict[str, Any]] = []
    observed_stems: set[str] = set()
    for filename, evaluator_type, metric, higher_is_better in specifications:
        path = official_artifact_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"missing official OmniDocBench detail artifact: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"official OmniDocBench detail artifact is not an object: {path}")
        for raw_location, raw_value in sorted(payload.items()):
            source_name = strip_element_suffix(str(raw_location))
            stem = Path(source_name).stem
            case_id = lookup.get(stem)
            if case_id is None:
                raise ValueError(
                    "official OmniDocBench detail references an unknown page: "
                    f"{source_name}"
                )
            observed_stems.add(stem)
            if metric == "teds":
                if not isinstance(raw_value, dict) or "TEDS" not in raw_value:
                    raise ValueError(f"official table TEDS payload is invalid: {raw_location}")
                official_value = float(raw_value["TEDS"])
                score = official_value
                failed = official_value < 1.0 - 1e-12
            else:
                official_value = float(raw_value)
                score = 1.0 - official_value
                failed = official_value > 1e-12
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"official OmniDocBench score is outside [0,1]: {raw_location}")
            if failed:
                failures.append(
                    {
                        "case_id": case_id,
                        "evaluator_type": evaluator_type,
                        "location_id": _safe_location(f"{metric}:{raw_location}"),
                        "source_name": source_name,
                        "metric": metric,
                        "official_value": official_value,
                        "score": score,
                        "higher_is_better": higher_is_better,
                    }
                )
    evidence = {
        "schema": "folynta.omnidocbench-official-failures.v1",
        "source_manifest_sha256": sha256_file(source_manifest),
        "source_count": len(lookup),
        "pages_with_scored_elements": len(observed_stems),
        "failure_count": len(failures),
        "failures": sorted(
            failures,
            key=lambda item: (
                str(item["case_id"]),
                str(item["evaluator_type"]),
                str(item["location_id"]),
            ),
        ),
    }
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return evidence


def run_evaluation(
    *,
    evaluator_dir: Path,
    ground_truth: Path,
    predictions_root: Path,
    output_dir: Path,
    source_manifest: Path,
    repeats: int,
    workers: int,
    quick_match_timeout_seconds: int,
    page_match_timeout_seconds: int,
) -> dict[str, object]:
    if quick_match_timeout_seconds < 1:
        raise ValueError("quick-match timeout must be positive")
    if page_match_timeout_seconds <= quick_match_timeout_seconds:
        raise ValueError("page-match timeout must exceed quick-match timeout")
    output_dir.mkdir(parents=True, exist_ok=True)
    revision = evaluator_revision(evaluator_dir)
    records: list[dict[str, object]] = []
    for repeat_index in range(1, repeats + 1):
        prediction = predictions_root / f"markdown-repeat-{repeat_index}"
        if not prediction.is_dir():
            raise FileNotFoundError(f"missing prediction directory: {prediction}")
        repeat_dir = output_dir / f"repeat-{repeat_index}"
        repeat_dir.mkdir(parents=True, exist_ok=True)
        destination = repeat_dir / "metric-result.json"
        artifact_dir = repeat_dir / "official-artifacts"
        required_artifacts = (
            "metric_result.json",
            "text_block_per_page_edit.json",
            "display_formula_per_page_edit.json",
            "table_per_page_edit.json",
            "reading_order_per_page_edit.json",
            "table_per_table_TEDS.json",
        )
        if destination.is_file() and all(
            (artifact_dir / name).is_file() for name in required_artifacts
        ):
            parsed = json.loads(destination.read_text(encoding="utf-8"))
            page_count = require_exact_page_count(parsed, prediction)
            official_artifacts = {
                path.name: sha256_file(path)
                for path in sorted(artifact_dir.iterdir())
                if path.is_file()
            }
            failure_path = repeat_dir / "official-element-failures.json"
            failure_evidence = extract_official_failures(
                official_artifact_dir=artifact_dir,
                source_manifest=source_manifest,
                output_path=failure_path,
            )
            records.append(
                {
                    "repeat_index": repeat_index,
                    "elapsed_seconds": 0.0,
                    "resumed_from_frozen_official_artifacts": True,
                    "metric_result_sha256": sha256_file(destination),
                    "page_count": page_count,
                    "official_artifacts": official_artifacts,
                    "official_failure_count": failure_evidence["failure_count"],
                    "official_failure_evidence_sha256": sha256_file(failure_path),
                    "official_match_debug": parsed.get("match_debug", {}),
                }
            )
            continue
        config_path = repeat_dir / "omnidoc-partial.yaml"
        config_path.write_text(
            render_config(
                ground_truth=ground_truth,
                prediction=prediction,
                workers=workers,
                quick_match_timeout_seconds=quick_match_timeout_seconds,
                page_match_timeout_seconds=page_match_timeout_seconds,
            ),
            encoding="utf-8",
        )
        started = time.time()
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        stdout_path = repeat_dir / "stdout.log"
        stderr_path = repeat_dir / "stderr.log"
        with (
            stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_handle,
            stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_handle,
        ):
            process = subprocess.run(
                [sys.executable, "pdf_validation.py", "--config", str(config_path)],
                cwd=evaluator_dir,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
            )
        if process.returncode != 0:
            raise RuntimeError(f"OmniDocBench repeat {repeat_index} failed: {process.returncode}")

        prefix = f"{prediction.name}_quick_match"
        source_result = evaluator_dir / "result" / f"{prefix}_metric_result.json"
        if not source_result.is_file():
            raise FileNotFoundError(f"missing official metric result: {source_result}")
        shutil.copy2(source_result, destination)
        parsed = json.loads(destination.read_text(encoding="utf-8"))
        page_count = require_exact_page_count(parsed, prediction)
        official_artifacts: dict[str, str] = {}
        for source_artifact in sorted((evaluator_dir / "result").glob(f"{prefix}_*")):
            if not source_artifact.is_file():
                continue
            artifact_name = source_artifact.name.removeprefix(f"{prefix}_")
            artifact_destination = repeat_dir / "official-artifacts" / artifact_name
            artifact_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_artifact, artifact_destination)
            official_artifacts[artifact_name] = sha256_file(artifact_destination)
        if "metric_result.json" not in official_artifacts:
            raise FileNotFoundError("official artifact capture omitted metric_result.json")
        failure_path = repeat_dir / "official-element-failures.json"
        failure_evidence = extract_official_failures(
            official_artifact_dir=repeat_dir / "official-artifacts",
            source_manifest=source_manifest,
            output_path=failure_path,
        )
        records.append(
            {
                "repeat_index": repeat_index,
                "elapsed_seconds": time.time() - started,
                "resumed_from_frozen_official_artifacts": False,
                "metric_result_sha256": sha256_file(destination),
                "page_count": page_count,
                "official_artifacts": official_artifacts,
                "official_failure_count": failure_evidence["failure_count"],
                "official_failure_evidence_sha256": sha256_file(failure_path),
                "official_match_debug": parsed.get("match_debug", {}),
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
        "source_manifest_sha256": sha256_file(source_manifest),
        "stall_recovery_policy": {
            "normal_match_method": "quick_match",
            "quick_match_timeout_seconds": quick_match_timeout_seconds,
            "page_match_timeout_seconds": page_match_timeout_seconds,
            "timeout_fallback": "chunked_hungarian",
            "score_inflation_allowed": False,
        },
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
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--quick-match-timeout-seconds", type=int, default=60)
    parser.add_argument("--page-match-timeout-seconds", type=int, default=90)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_evaluation(
        evaluator_dir=args.evaluator_dir.resolve(),
        ground_truth=args.ground_truth.resolve(),
        predictions_root=args.predictions_root.resolve(),
        output_dir=args.output_dir.resolve(),
        source_manifest=args.source_manifest.resolve(),
        repeats=args.repeats,
        workers=args.workers,
        quick_match_timeout_seconds=args.quick_match_timeout_seconds,
        page_match_timeout_seconds=args.page_match_timeout_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
