#!/usr/bin/env python3
"""Validate and merge sharded MinerU public-core results.

The merger is intentionally evaluator-agnostic at ingestion time: it first
proves exact case coverage and byte bindings, then emits immutable prediction
exports for each official benchmark. Ground truth is never accepted as an
input to this module.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_CANDIDATE_ID = "mineru-3.4.4-vlm"
EXPECTED_ARTIFACT_SHA256 = (
    "1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84"
)
SUITES = ("parsebench", "omnidocbench", "olmocr-bench")

_LABEL_MAP = {
    "text": "Text",
    "title": "Title",
    "doc_title": "Title",
    "paragraph_title": "Section-header",
    "table": "Table",
    "table_caption": "Caption",
    "table_footnote": "Footnote",
    "figure": "Picture",
    "image": "Picture",
    "image_block": "Picture",
    "image_caption": "Caption",
    "image_footnote": "Footnote",
    "figure_caption": "Caption",
    "formula": "Formula",
    "equation": "Formula",
    "equation_block": "Formula",
    "formula_number": "Formula",
    "display_formula": "Formula",
    "inline_formula": "Formula",
    "header": "Page-header",
    "page_header": "Page-header",
    "footer": "Page-footer",
    "page_footer": "Page-footer",
    "page_number": "Page-footer",
    "footnote": "Footnote",
    "page_footnote": "Footnote",
    "list": "List-item",
    "list_item": "List-item",
    "code": "Code",
    "code_caption": "Caption",
    "algorithm": "Code",
    "aside_text": "Text",
    "ref_text": "Text",
    "phonetic": "Text",
    "chart": "Picture",
    "unknown": "Picture",
}


def _io_path(path: Path) -> Path:
    """Use Windows extended-length paths for long benchmark filenames."""
    if os.name != "nt" or not path.is_absolute():
        return path
    value = str(path)
    if value.startswith("\\\\?\\"):
        return path
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value.lstrip("\\"))
    return Path("\\\\?\\" + value)


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _io_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_json(path: Path) -> Any:
    return json.loads(_io_path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> str:
    destination = _io_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json(payload))
    return sha256_file(destination)


def _copy_bound(source: Path, destination: Path, expected_sha256: str) -> str:
    if sha256_file(source) != expected_sha256:
        raise ValueError(f"artifact hash mismatch: {source}")
    io_destination = _io_path(destination)
    io_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), io_destination)
    copied_sha256 = sha256_file(io_destination)
    if copied_sha256 != expected_sha256:
        raise ValueError(f"copied artifact hash mismatch: {destination}")
    return copied_sha256


def _png_dimensions(path: Path) -> tuple[int, int]:
    with _io_path(path).open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"expected a PNG input: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width < 1 or height < 1:
        raise ValueError(f"invalid PNG dimensions: {path}")
    return width, height


def _close_unclosed_tables(markdown: str) -> str:
    opens = len(re.findall(r"<table(?:\s[^>]*)?>", markdown, re.IGNORECASE))
    closes = len(re.findall(r"</table\s*>", markdown, re.IGNORECASE))
    if opens > closes:
        if not markdown.rstrip().endswith(">"):
            markdown += "</td></tr>"
        markdown += "</table>" * (opens - closes)
    return markdown


def _promote_first_table_rows(markdown: str) -> str:
    def promote_table(table_match: re.Match[str]) -> str:
        table = table_match.group(0)
        if re.search(r"<thead(?:\s|>)", table, re.IGNORECASE):
            return table
        row = re.search(r"<tr(?:\s[^>]*)?>(.*?)</tr\s*>", table, re.I | re.S)
        if row is None:
            return table
        header = re.sub(r"<td(?=\s|>)", "<th", row.group(1), flags=re.I)
        header = re.sub(r"</td\s*>", "</th>", header, flags=re.I)
        return table.replace(row.group(0), f"<thead><tr>{header}</tr></thead>", 1)

    return re.sub(
        r"<table(?:\s[^>]*)?>.*?</table\s*>",
        promote_table,
        markdown,
        flags=re.I | re.S,
    )


def _quote_html_attributes(markdown: str) -> str:
    def quote_tag(tag_match: re.Match[str]) -> str:
        tag = tag_match.group(0)
        return re.sub(
            r"(\w+)=([^\s\"'<>=]+)",
            lambda match: f'{match.group(1)}="{html.escape(match.group(2), quote=True)}"',
            tag,
        )

    return re.sub(r"<[^>]+>", quote_tag, markdown)


def normalize_parsebench_markdown(markdown: str) -> str:
    """Apply the deterministic normalization used by ParseBench's MinerU lane."""

    return _quote_html_attributes(_promote_first_table_rows(_close_unclosed_tables(markdown)))


def _coerce_blocks(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("MinerU model payload must contain exactly one page")
    blocks = payload[0]
    if not isinstance(blocks, list):
        raise ValueError("MinerU model page must be a list of blocks")
    return [block for block in blocks if isinstance(block, dict)]


def _layout_item(block: dict[str, Any], width: int, height: int) -> dict[str, Any] | None:
    bbox = block.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    x1, y1, x2, y2 = (
        max(0.0, min(1.0, x1)),
        max(0.0, min(1.0, y1)),
        max(0.0, min(1.0, x2)),
        max(0.0, min(1.0, y2)),
    )
    if x2 <= x1 or y2 <= y1:
        return None
    raw_type = str(block.get("type") or "text").lower()
    label = _LABEL_MAP.get(raw_type, "Text")
    segment = {
        # ParseBench's legacy bridge consumes pixel COCO coordinates here.
        "x": x1 * width,
        "y": y1 * height,
        "w": (x2 - x1) * width,
        "h": (y2 - y1) * height,
        "confidence": 1.0,
        "label": label,
    }
    if raw_type == "table":
        item_type = "table"
    elif raw_type in {"figure", "image", "image_block", "chart"}:
        item_type = "image"
    else:
        item_type = "text"
    content = str(block.get("content") or "")
    return {
        "type": item_type,
        "md": content,
        "value": content,
        "bbox": segment,
        "layout_segments": [segment],
    }


def build_parsebench_result(
    *,
    case: dict[str, Any],
    markdown: str,
    model_payload: Any,
    input_path: Path,
    worker_index: int,
    run_summary_sha256: str,
) -> dict[str, Any]:
    width, height = _png_dimensions(input_path)
    normalized_markdown = normalize_parsebench_markdown(markdown)
    blocks = _coerce_blocks(model_payload)
    items = [
        item
        for item in (_layout_item(block, width, height) for block in blocks)
        if item is not None
    ]
    source_relative_path = str(case["source_relative_path"])
    category = Path(source_relative_path).parent.name
    inference_group = "text" if category == "text" else category
    example_id = f"{inference_group}/{Path(source_relative_path).stem}"
    timestamp = datetime.now(UTC).isoformat()
    # Keep this frozen lane unregistered in ParseBench. The upstream adapter
    # resolver currently selects its generic fallback for registered providers
    # that do not have an explicit layout adapter, bypassing the compatible
    # typed-layout matcher. An immutable, unregistered lane name therefore
    # preserves the actual MinerU layout blocks instead of silently dropping
    # all layout predictions.
    pipeline_name = "mineru-3.4.4-vlm-c1-frozen"
    raw_output = {
        "markdown": normalized_markdown,
        "blocks": blocks,
        "image_width": width,
        "image_height": height,
        "worker_index": worker_index,
        "run_summary_sha256": run_summary_sha256,
        "normalization": "parsebench-mineru2605pro-compatible-v1",
    }
    if category == "layout":
        predictions = []
        for order_index, block in enumerate(blocks):
            item = _layout_item(block, width, height)
            if item is None:
                continue
            segment = item["bbox"]
            content_value = str(block.get("content") or "")
            if item["type"] == "table":
                content = {"type": "table", "html": content_value}
            elif content_value:
                content = {"type": "text", "text": content_value}
            else:
                content = None
            predictions.append(
                {
                    "bbox": [
                        segment["x"],
                        segment["y"],
                        segment["x"] + segment["w"],
                        segment["y"] + segment["h"],
                    ],
                    "score": 1.0,
                    "label": segment["label"],
                    "page": 1,
                    "content": content,
                    "provider_metadata": {
                        "order_index": order_index,
                        "source_type": str(block.get("type") or "unknown"),
                    },
                }
            )
        return {
            "request": {
                "example_id": example_id,
                "source_file_path": source_relative_path,
                "product_type": "layout_detection",
                "schema_override": None,
                "config_override": None,
            },
            "pipeline_name": pipeline_name,
            "product_type": "layout_detection",
            "raw_output": raw_output,
            "output": {
                "task_type": "layout_detection",
                "example_id": example_id,
                "pipeline_name": pipeline_name,
                "model": "unstructured_layout",
                "image_width": width,
                "image_height": height,
                "predictions": predictions,
                "markdown": normalized_markdown,
            },
            "started_at": timestamp,
            "completed_at": timestamp,
            "latency_in_ms": 0,
        }

    return {
        "request": {
            "example_id": example_id,
            "source_file_path": source_relative_path,
            "product_type": "parse",
            "schema_override": None,
            "config_override": None,
        },
        "pipeline_name": pipeline_name,
        "product_type": "parse",
        "raw_output": raw_output,
        "output": {
            "task_type": "parse",
            "example_id": example_id,
            "pipeline_name": pipeline_name,
            "pages": [{"page_index": 0, "markdown": normalized_markdown}],
            "layout_pages": [
                {
                    "page_number": 1,
                    "width": float(width),
                    "height": float(height),
                    "md": normalized_markdown,
                    "text": "",
                    "items": items,
                }
            ],
            "markdown": normalized_markdown,
            "job_id": None,
        },
        "started_at": timestamp,
        "completed_at": timestamp,
        "latency_in_ms": 0,
    }


@dataclass(frozen=True, slots=True)
class WorkerSource:
    worker_index: int
    result_root: Path


def _suite_plan(plan: dict[str, Any], suite: str) -> dict[str, Any]:
    matches = [entry for entry in plan.get("suites", []) if entry.get("benchmark_id") == suite]
    if len(matches) != 1:
        raise ValueError(f"shard plan must contain one suite entry for {suite}")
    return matches[0]


def _shard_cases(plan: dict[str, Any], suite: str, worker_index: int) -> dict[str, dict[str, Any]]:
    suite_entry = _suite_plan(plan, suite)
    matches = [
        shard
        for shard in suite_entry.get("shards", [])
        if int(shard.get("worker_index", -1)) == worker_index
    ]
    if len(matches) != 1:
        raise ValueError(f"missing unique shard for {suite}/worker-{worker_index}")
    cases = matches[0].get("inputs", [])
    result = {str(case["case_id"]): case for case in cases}
    if len(result) != len(cases):
        raise ValueError(f"duplicate case ids in {suite}/worker-{worker_index} shard")
    return result


def _full_manifest(
    staged_root: Path,
    suite: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest_path = staged_root / suite / "inference-input-manifest.json"
    manifest = _load_json(manifest_path)
    inputs = manifest.get("inputs", [])
    case_map = {str(case["case_id"]): case for case in inputs}
    if len(case_map) != len(inputs) or len(case_map) != int(manifest.get("input_count", -1)):
        raise ValueError(f"invalid parent input manifest for {suite}")
    return manifest, case_map


def _find_model_payload(repeat_root: Path, case_id: str) -> Path:
    exact = repeat_root / case_id / "vlm" / f"{case_id}_model.json"
    if exact.is_file():
        return exact
    matches = sorted((repeat_root / case_id).rglob(f"{case_id}_model.json"))
    if len(matches) != 1:
        raise ValueError(f"missing unique MinerU model payload for {case_id}")
    return matches[0]


def _official_destination(output_root: Path, suite: str, case: dict[str, Any]) -> Path:
    source = Path(str(case["source_relative_path"]))
    if suite == "omnidocbench":
        return output_root / "official" / suite / "markdown-repeat-1" / f"{source.stem}.md"
    if suite == "olmocr-bench":
        relative = source.relative_to("bench_data/pdfs")
        return (
            output_root
            / "official"
            / suite
            / "mineru344"
            / relative.parent
            / f"{relative.stem}_pg1_repeat1.md"
        )
    raise ValueError(f"no Markdown official destination for {suite}")


def merge_public_core_results(
    *,
    worker_sources: Iterable[WorkerSource],
    staged_root: Path,
    shard_plan: Path,
    output_root: Path,
) -> dict[str, Any]:
    workers = sorted(worker_sources, key=lambda source: source.worker_index)
    if [source.worker_index for source in workers] != [0, 1, 2, 3]:
        raise ValueError("exactly worker indices 0, 1, 2, and 3 are required")
    if output_root.exists():
        raise FileExistsError(f"output root already exists: {output_root}")
    output_root.mkdir(parents=True)
    plan = _load_json(shard_plan)
    if int(plan.get("worker_count", -1)) != 4 or int(plan.get("total_input_count", -1)) != 5132:
        raise ValueError("shard plan is not the frozen 4-worker/5,132-case campaign")

    suites_payload: list[dict[str, Any]] = []
    total_completed = 0
    total_failed = 0
    for suite in SUITES:
        parent_manifest, full_cases = _full_manifest(staged_root, suite)
        merged_ids: set[str] = set()
        records: list[dict[str, Any]] = []
        for worker in workers:
            expected_cases = _shard_cases(plan, suite, worker.worker_index)
            suite_root = worker.result_root / suite
            summary_path = suite_root / "run-summary.json"
            summary = _load_json(summary_path)
            summary_sha256 = sha256_file(summary_path)
            if summary.get("candidate_id") != EXPECTED_CANDIDATE_ID:
                raise ValueError(f"candidate identity mismatch: {summary_path}")
            if summary.get("artifact_manifest_sha256") != EXPECTED_ARTIFACT_SHA256:
                raise ValueError(f"model artifact mismatch: {summary_path}")
            if summary.get("evidence_class") != "public-core-shard":
                raise ValueError(f"evidence class mismatch: {summary_path}")
            if summary.get("ground_truth_mounted") is not False:
                raise ValueError(f"ground truth isolation failed: {summary_path}")
            runs = summary.get("runs", [])
            if len(runs) != 1 or int(runs[0].get("repeat_index", -1)) != 1:
                raise ValueError(f"full baseline must contain exactly repeat 1: {summary_path}")
            observed = runs[0].get("cases", [])
            observed_map = {str(case["case_id"]): case for case in observed}
            if len(observed_map) != len(observed) or set(observed_map) != set(
                expected_cases
            ):
                raise ValueError(
                    f"worker case coverage mismatch: {suite}/worker-{worker.worker_index}"
                )
            if int(summary.get("input_count", -1)) != len(expected_cases):
                raise ValueError(f"worker input count mismatch: {summary_path}")

            for case_id in sorted(expected_cases):
                if case_id in merged_ids:
                    raise ValueError(f"duplicate merged case: {case_id}")
                merged_ids.add(case_id)
                shard_case = expected_cases[case_id]
                parent_case = full_cases.get(case_id)
                if parent_case is None:
                    raise ValueError(f"shard case is absent from parent manifest: {case_id}")
                if shard_case.get("input_sha256") != parent_case.get("input_sha256"):
                    raise ValueError(f"shard/parent input hash mismatch: {case_id}")
                observed_case = observed_map[case_id]
                if observed_case.get("source_sha256") != parent_case.get("input_sha256"):
                    raise ValueError(f"runtime/source input hash mismatch: {case_id}")
                status = str(observed_case.get("status"))
                if status not in {"completed", "failed"}:
                    raise ValueError(f"unsupported runtime status for {case_id}: {status}")
                source_markdown = suite_root / "markdown-repeat-1" / f"{case_id}.md"
                expected_markdown_sha256 = str(observed_case.get("markdown_sha256"))
                if (
                    not source_markdown.is_file()
                    or sha256_file(source_markdown) != expected_markdown_sha256
                ):
                    raise ValueError(f"runtime Markdown binding mismatch: {case_id}")
                if (
                    status == "completed"
                    and source_markdown.stat().st_size < 1
                    and observed_case.get("semantic_empty_page") is not True
                ):
                    raise ValueError(f"completed case has empty Markdown: {case_id}")
                merged_markdown = (
                    output_root / "merged" / suite / "markdown-repeat-1" / f"{case_id}.md"
                )
                _copy_bound(source_markdown, merged_markdown, expected_markdown_sha256)
                model_sha256: str | None = None
                model_path: Path | None = None
                if status == "completed":
                    model_source = _find_model_payload(suite_root / "repeat-1", case_id)
                    model_sha256 = sha256_file(model_source)
                    model_path = output_root / "merged" / suite / "model-json" / model_source.name
                    _copy_bound(model_source, model_path, model_sha256)
                    if suite in {"omnidocbench", "olmocr-bench"}:
                        official_path = _official_destination(output_root, suite, parent_case)
                        _copy_bound(source_markdown, official_path, expected_markdown_sha256)
                    elif suite == "parsebench":
                        result = build_parsebench_result(
                            case=parent_case,
                            markdown=source_markdown.read_text(encoding="utf-8"),
                            model_payload=_load_json(model_source),
                            input_path=(
                                staged_root
                                / suite
                                / str(parent_case["input_relative_path"])
                            ),
                            worker_index=worker.worker_index,
                            run_summary_sha256=summary_sha256,
                        )
                        source_path = Path(str(parent_case["source_relative_path"]))
                        category = source_path.parent.name
                        result_path = (
                            output_root
                            / "official"
                            / suite
                            / category
                            / f"{source_path.stem}.result.json"
                        )
                        _write_json(result_path, result)
                record = {
                    "case_id": case_id,
                    "source_relative_path": parent_case["source_relative_path"],
                    "input_sha256": parent_case["input_sha256"],
                    "markdown_sha256": expected_markdown_sha256,
                    "model_sha256": model_sha256,
                    "status": status,
                    "primary_worker_index": worker.worker_index,
                    "retry_worker_index": int(shard_case["retry_worker_index"]),
                    "run_summary_sha256": summary_sha256,
                }
                records.append(record)
                total_completed += int(status == "completed")
                total_failed += int(status == "failed")
        if merged_ids != set(full_cases):
            missing = sorted(set(full_cases) - merged_ids)
            extra = sorted(merged_ids - set(full_cases))
            raise ValueError(
                f"full suite coverage mismatch for {suite}; "
                f"missing={missing[:5]}, extra={extra[:5]}"
            )
        suite_index_path = output_root / "indexes" / f"{suite}-cases.json"
        suite_index = {
            "schema": "folynta.public-core-merged-cases.v1",
            "benchmark_id": suite,
            "dataset_revision": parent_manifest["dataset_revision"],
            "input_count": len(records),
            "complete_case_coverage": True,
            "records": sorted(records, key=lambda record: str(record["case_id"])),
        }
        suite_index_sha256 = _write_json(suite_index_path, suite_index)
        suites_payload.append(
            {
                "benchmark_id": suite,
                "input_count": len(records),
                "completed": sum(record["status"] == "completed" for record in records),
                "failed": sum(record["status"] == "failed" for record in records),
                "case_index_sha256": suite_index_sha256,
            }
        )

    receipt = {
        "schema": "folynta.public-core-merge-receipt.v1",
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "artifact_manifest_sha256": f"sha256:{EXPECTED_ARTIFACT_SHA256}",
        "shard_plan_sha256": sha256_file(shard_plan),
        "worker_count": 4,
        "input_count": total_completed + total_failed,
        "completed": total_completed,
        "failed": total_failed,
        "complete_case_coverage": total_completed + total_failed == 5132,
        "ground_truth_mounted_on_workers": False,
        "suites": suites_payload,
    }
    receipt_sha256 = _write_json(output_root / "merge-receipt.json", receipt)
    return {**receipt, "receipt_sha256": receipt_sha256}


def _worker_source(value: str) -> WorkerSource:
    try:
        index_text, path_text = value.split("=", 1)
        index = int(index_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("worker must be INDEX=RESULT_ROOT") from exc
    return WorkerSource(index, Path(path_text))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="append", type=_worker_source, required=True)
    parser.add_argument("--staged-root", type=Path, required=True)
    parser.add_argument("--shard-plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = merge_public_core_results(
        worker_sources=args.worker,
        staged_root=args.staged_root.resolve(),
        shard_plan=args.shard_plan.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "WorkerSource",
    "build_parsebench_result",
    "merge_public_core_results",
    "normalize_parsebench_markdown",
]
