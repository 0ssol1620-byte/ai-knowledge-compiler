#!/usr/bin/env python3
"""Derive source-bound target crops from the frozen SEC row-crop manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from PIL import Image

BENCHMARK_ID = "TAVONEL-SEC-TARGET-CELL-DEVELOPMENT-20260910-V1"
EXPECTED_REGIONS = 24
MIN_OUTPUT_WIDTH = 512
MIN_OUTPUT_HEIGHT = 256
MAX_SCALE = 4.0


class TargetCropError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TargetCropError(f"{path}:{number} must contain an object")
        rows.append(value)
    return rows


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for row in rows
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def pixel_bbox(row: dict[str, Any]) -> tuple[int, int, int, int]:
    values = row.get("target_bbox1000")
    if not isinstance(values, list) or len(values) != 4:
        raise TargetCropError(f"invalid target bbox for {row.get('region_id')}")
    width = int(row["input_width_px"])
    height = int(row["input_height_px"])
    x0 = math.floor(float(values[0]) / 1000 * width)
    y0 = math.floor(float(values[1]) / 1000 * height)
    x1 = math.ceil(float(values[2]) / 1000 * width)
    y1 = math.ceil(float(values[3]) / 1000 * height)
    if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
        raise TargetCropError(f"out-of-range target bbox for {row.get('region_id')}")
    return x0, y0, x1, y1


def padded_bbox(
    target: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = target
    target_height = y1 - y0
    horizontal = max(48, target_height * 4)
    vertical = max(24, target_height * 2)
    return (
        max(0, x0 - horizontal),
        max(0, y0 - vertical),
        min(width, x1 + horizontal),
        min(height, y1 + vertical),
    )


def normalized_bbox1000(
    target: tuple[int, int, int, int], crop: tuple[int, int, int, int]
) -> list[int]:
    x0, y0, x1, y1 = target
    cx0, cy0, cx1, cy1 = crop
    width = cx1 - cx0
    height = cy1 - cy0
    return [
        max(0, min(1000, math.floor((x0 - cx0) / width * 1000))),
        max(0, min(1000, math.floor((y0 - cy0) / height * 1000))),
        max(0, min(1000, math.ceil((x1 - cx0) / width * 1000))),
        max(0, min(1000, math.ceil((y1 - cy0) / height * 1000))),
    ]


def process(input_root: Path, output_root: Path, expected_manifest_sha256: str) -> dict[str, Any]:
    manifest_path = input_root / "RUNTIME_MANIFEST.jsonl"
    if sha256_file(manifest_path) != expected_manifest_sha256:
        raise TargetCropError("source runtime manifest hash drift")
    rows = read_jsonl(manifest_path)
    if len(rows) != EXPECTED_REGIONS:
        raise TargetCropError(f"source denominator is {len(rows)}, expected {EXPECTED_REGIONS}")
    if output_root.exists():
        raise TargetCropError(f"output root already exists: {output_root}")
    crop_root = output_root / "crops"
    crop_root.mkdir(parents=True)
    output_rows: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item["region_id"])):
        source_path = input_root / str(row["input_relative_path"])
        if sha256_file(source_path) != row["input_png_sha256"]:
            raise TargetCropError(f"source PNG hash drift for {row['region_id']}")
        with Image.open(source_path) as source:
            source.load()
            width, height = source.size
            if width != int(row["input_width_px"]) or height != int(row["input_height_px"]):
                raise TargetCropError(f"source PNG dimensions drift for {row['region_id']}")
            target = pixel_bbox(row)
            crop = padded_bbox(target, width, height)
            image = source.crop(crop).convert("RGB")
            scale = min(
                MAX_SCALE,
                max(1.0, MIN_OUTPUT_WIDTH / image.width, MIN_OUTPUT_HEIGHT / image.height),
            )
            output_size = (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
            if output_size != image.size:
                image = image.resize(output_size, Image.Resampling.LANCZOS)
            relative = Path("crops") / f"{row['region_id']}.png"
            output_path = output_root / relative
            image.save(output_path, format="PNG", optimize=True)
        target_in_crop = normalized_bbox1000(target, crop)
        output_rows.append(
            {
                "region_id": row["region_id"],
                "ticker": row["ticker"],
                "cik": row["cik"],
                "accession": row["accession"],
                "filing_url": row["filing_url"],
                "filing_html_sha256": row["filing_html_sha256"],
                "fragment_sha256": row["fragment_sha256"],
                "source_row_png_sha256": row["input_png_sha256"],
                "source_target_bbox1000": row["target_bbox1000"],
                "source_crop_pixel_bbox": list(crop),
                "input_relative_path": relative.as_posix(),
                "input_png_sha256": sha256_file(output_path),
                "input_width_px": output_size[0],
                "input_height_px": output_size[1],
                "target_bbox1000": target_in_crop,
            }
        )
    output_manifest = output_root / "RUNTIME_MANIFEST.jsonl"
    write_jsonl(output_manifest, output_rows)
    result = {
        "schema": "tavonel.sec_target_cell_crop_result.v1",
        "benchmark_id": BENCHMARK_ID,
        "source_runtime_manifest_sha256": expected_manifest_sha256,
        "runtime_manifest_sha256": sha256_file(output_manifest),
        "regions": len(output_rows),
        "target_policy": {
            "horizontal_padding": "max(48px, 4 * target height)",
            "vertical_padding": "max(24px, 2 * target height)",
            "minimum_output": [MIN_OUTPUT_WIDTH, MIN_OUTPUT_HEIGHT],
            "maximum_scale": MAX_SCALE,
            "resampling": "Pillow LANCZOS",
        },
        "input_manifest_contains_truth": False,
        "source_truth_opened": True,
        "development_only": True,
        "production_promotion": False,
    }
    atomic_json(output_root / "CROP_RESULT.json", result)
    return result


def self_test() -> None:
    row = {
        "region_id": "r",
        "input_width_px": 2_000,
        "input_height_px": 200,
        "target_bbox1000": [400, 250, 500, 750],
    }
    target = pixel_bbox(row)
    if target != (800, 50, 1000, 150):
        raise TargetCropError(f"pixel bbox self-test failed: {target}")
    crop = padded_bbox(target, 2_000, 200)
    if not (crop[0] <= target[0] < target[2] <= crop[2]):
        raise TargetCropError("padded bbox self-test failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    result = process(
        args.input_root.resolve(),
        args.output_root.resolve(),
        args.expected_manifest_sha256,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
