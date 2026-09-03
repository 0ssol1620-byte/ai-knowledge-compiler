#!/usr/bin/env python3
"""Create an evaluator-only OmniDocBench ground-truth subset.

The inference manifest contains filenames/source paths and hashes only. This
tool joins those identifiers to the official annotation locally, refuses
missing or duplicate rows, and emits both the evaluator input and a hash
receipt. The result must never be copied into an inference bundle.

The real OmniDocBench annotation is large enough that loading the complete JSON
array can exhaust a controller process. The CLI therefore parses the top-level
array incrementally, spills only requested rows to short-lived local files, and
streams the final ordered subset to disk. The pure ``build_subset`` helper is
kept for small unit-test fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_CHUNK_BYTES = 1024 * 1024


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _requested_filenames(manifest: dict[str, Any]) -> list[str]:
    if manifest.get("ground_truth_mounted") is not False:
        raise ValueError("inference manifest must explicitly record absent ground truth")

    schema = manifest.get("schema")
    requested: list[str] = []
    if schema in {
        "folynta.public-core-inference-inputs.v1",
        "folynta.public-core-inference-shard.v1",
        "folynta.public-core-stratified-audit.v1",
    }:
        inputs = manifest.get("inputs")
        if not isinstance(inputs, list) or int(manifest.get("input_count", -1)) != len(inputs):
            raise ValueError("public-core inference manifest input count is invalid")
        for item in inputs:
            if not isinstance(item, dict) or not isinstance(item.get("source_relative_path"), str):
                raise ValueError("every public-core inference input requires source_relative_path")
            relative = Path(item["source_relative_path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("public-core source path must be a safe relative path")
            requested.append(relative.name)
    else:
        cases = manifest.get("cases")
        if not isinstance(cases, list) or int(manifest.get("case_count", -1)) != len(cases):
            raise ValueError("inference manifest case count is invalid")
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("filename"), str):
                raise ValueError("every inference case requires a filename")
            filename = Path(case["filename"]).name
            if filename != case["filename"]:
                raise ValueError("inference filenames must be basenames")
            requested.append(filename)

    if not requested:
        raise ValueError("inference manifest contains no requested pages")
    if len(set(requested)) != len(requested):
        raise ValueError("duplicate inference filenames are forbidden")
    return requested


def _annotation_filename(row: dict[str, Any]) -> str:
    page_info = row.get("page_info")
    image_path = page_info.get("image_path") if isinstance(page_info, dict) else None
    if not isinstance(image_path, str):
        raise ValueError("annotation row is missing page_info.image_path")
    return Path(image_path).name


def build_subset(annotation: object, manifest: object) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(annotation, list) or not all(isinstance(row, dict) for row in annotation):
        raise ValueError("OmniDocBench annotation must be a list of objects")
    if not isinstance(manifest, dict):
        raise ValueError("inference manifest must be an object")
    requested = _requested_filenames(manifest)

    indexed: dict[str, dict[str, Any]] = {}
    for row in annotation:
        filename = _annotation_filename(row)
        if filename in indexed:
            raise ValueError(f"duplicate annotation image_path: {filename}")
        indexed[filename] = row

    missing = [filename for filename in requested if filename not in indexed]
    if missing:
        raise ValueError(f"annotation is missing inference cases: {missing[:8]}")
    return [indexed[filename] for filename in requested], requested


def iter_json_array_objects(path: Path) -> Iterator[dict[str, Any]]:
    """Incrementally decode one top-level JSON array without loading it whole."""

    decoder = json.JSONDecoder()
    buffer = ""
    position = 0
    started = False
    finished = False
    eof = False

    with path.open("r", encoding="utf-8") as handle:
        while not finished:
            if not eof and (position >= len(buffer) or len(buffer) - position < _CHUNK_BYTES // 4):
                if position:
                    buffer = buffer[position:]
                    position = 0
                chunk = handle.read(_CHUNK_BYTES)
                if chunk:
                    buffer += chunk
                else:
                    eof = True

            while position < len(buffer) and buffer[position].isspace():
                position += 1

            if not started:
                if position >= len(buffer):
                    if eof:
                        raise ValueError("annotation JSON is empty")
                    continue
                if buffer[position] != "[":
                    raise ValueError("annotation JSON must be a top-level array")
                position += 1
                started = True
                continue

            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position < len(buffer) and buffer[position] == "]":
                position += 1
                finished = True
                break
            if position < len(buffer) and buffer[position] == ",":
                position += 1
                continue
            if position >= len(buffer):
                if eof:
                    raise ValueError("annotation JSON ended before closing array")
                continue

            try:
                value, end = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError:
                if eof:
                    raise ValueError("annotation JSON contains an invalid/truncated row") from None
                if position:
                    buffer = buffer[position:]
                    position = 0
                chunk = handle.read(_CHUNK_BYTES)
                if chunk:
                    buffer += chunk
                    continue
                eof = True
                continue
            if not isinstance(value, dict):
                raise ValueError("annotation array entries must be objects")
            position = end
            yield value

        while position < len(buffer) and buffer[position].isspace():
            position += 1
        if position != len(buffer):
            raise ValueError("annotation JSON has trailing content after the array")
        if not eof and handle.read(1):
            raise ValueError("annotation JSON has trailing content after the array")


def stream_subset_to_file(
    *, annotation_path: Path, manifest: dict[str, Any], output_path: Path
) -> tuple[list[str], str]:
    """Write requested annotation rows in manifest order with bounded memory."""

    requested = _requested_filenames(manifest)
    requested_set = set(requested)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    spill_dir = output_path.parent / f".{output_path.name}.spill-{os.getpid()}"
    if spill_dir.exists() or output_path.exists():
        raise ValueError("ground-truth output/spill path already exists")
    spill_dir.mkdir()
    matched: dict[str, Path] = {}
    seen: set[str] = set()
    try:
        for row in iter_json_array_objects(annotation_path):
            filename = _annotation_filename(row)
            if filename in seen:
                raise ValueError(f"duplicate annotation image_path: {filename}")
            seen.add(filename)
            if filename not in requested_set:
                continue
            spill_name = hashlib.sha256(filename.encode("utf-8")).hexdigest() + ".json"
            spill_path = spill_dir / spill_name
            spill_path.write_text(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
            matched[filename] = spill_path

        missing = [filename for filename in requested if filename not in matched]
        if missing:
            raise ValueError(f"annotation is missing inference cases: {missing[:8]}")

        output_hash = hashlib.sha256()
        with output_path.open("wb") as output:
            def emit(data: bytes) -> None:
                output.write(data)
                output_hash.update(data)

            emit(b"[")
            for index, filename in enumerate(requested):
                if index:
                    emit(b",")
                emit(matched[filename].read_bytes())
            emit(b"]\n")
        return requested, "sha256:" + output_hash.hexdigest()
    finally:
        shutil.rmtree(spill_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--inference-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.receipt_out.exists():
        raise SystemExit("output paths must not already exist")

    manifest_bytes = args.inference_manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    filenames, subset_sha256 = stream_subset_to_file(
        annotation_path=args.annotation,
        manifest=manifest,
        output_path=args.output,
    )
    receipt = {
        "schema_version": "1.2.0",
        "role": "evaluator_only_ground_truth",
        "streaming_annotation_parse": True,
        "ground_truth_mounted_on_inference_worker": False,
        "case_count": len(filenames),
        "filenames": filenames,
        "source_annotation_sha256": sha256_file(args.annotation),
        "inference_manifest_sha256": sha256_bytes(manifest_bytes),
        "subset_sha256": subset_sha256,
    }
    args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_out.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "case_count": len(filenames),
                "subset_sha256": subset_sha256,
                "receipt_out": str(args.receipt_out),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
