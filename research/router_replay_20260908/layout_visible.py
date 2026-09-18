"""Measure label-free layout features from the exact route-time raster.

The probe reads only the frozen source manifest and its staged input PNGs. It
does not import the scorer or open benchmark rules. The output is a sealed,
page-complete development capture that can be joined to replay features by
exact source and input-image hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import features as F
from PIL import Image
from PIL import __version__ as pillow_version

EXPECTED_UNITS = 1403
SCHEMA = "tavonel.router_replay.layout_capture.v1"
PROBE_ID = "TAVONEL-LAYOUT-PREFLIGHT-2026-09-10-V1"
RASTER_WIDTH = 160
INK_THRESHOLD = 235
GUTTER_MAX_INK_ROW_FRACTION = 0.02
GUTTER_MIN_WIDTH_FRACTION = 0.03
LONG_LINE_MIN_FRACTION = 0.25


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("LAYOUT_CAPTURE_OBJECT_REQUIRED")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8")
    return digest(path)


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    low = int(index)
    high = min(len(ordered) - 1, low + 1)
    fraction = index - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def measure_image(path: Path) -> dict[str, float | int | None]:
    """Return deterministic geometry features; no model or benchmark label."""
    with Image.open(path) as source:
        gray = source.convert("L")
        target_height = max(1, round(gray.height * RASTER_WIDTH / max(1, gray.width)))
        target_height = min(320, target_height)
        raster = gray.resize((RASTER_WIDTH, target_height), Image.Resampling.BILINEAR)
        width, height = raster.size
        pixels = list(cast(Sequence[int], raster.get_flattened_data()))

    ink = [value < INK_THRESHOLD for value in pixels]
    ink_count = sum(ink)
    col_counts = [0] * width
    horizontal_long = 0
    for y in range(height):
        offset = y * width
        longest = run = 0
        for x in range(width):
            if ink[offset + x]:
                col_counts[x] += 1
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        if longest >= width * LONG_LINE_MIN_FRACTION:
            horizontal_long += longest

    vertical_long = 0
    for x in range(width):
        longest = run = 0
        for y in range(height):
            if ink[y * width + x]:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        if longest >= height * LONG_LINE_MIN_FRACTION:
            vertical_long += longest

    left = round(width * 0.10)
    right = round(width * 0.90)
    min_gutter = max(2, round(width * GUTTER_MIN_WIDTH_FRACTION))
    max_gutter_ink = max(1, round(height * GUTTER_MAX_INK_ROW_FRACTION))
    gutters = 0
    run = 0
    for count in col_counts[left:right]:
        if count <= max_gutter_ink:
            run += 1
        else:
            if run >= min_gutter:
                gutters += 1
            run = 0
    if run >= min_gutter:
        gutters += 1

    return {
        "column_count": min(4, 1 + gutters),
        "table_line_density": (
            min(1.0, (horizontal_long + vertical_long) / max(1, 2 * ink_count))
        ),
        "ink_coverage": ink_count / max(1, width * height),
        "raster_width": width,
        "raster_height": height,
    }


@dataclass(frozen=True, slots=True)
class LayoutCapture:
    root: Path
    source_manifest_sha256: str
    freeze_sha256: str
    records_sha256: str
    records: Mapping[str, Mapping[str, Any]]
    coverage: Mapping[str, int]
    wall_ms: Mapping[str, float | int | None]

    @property
    def binding(self) -> dict[str, Any]:
        return {
            "probe_id": PROBE_ID,
            "source_manifest_sha256": self.source_manifest_sha256,
            "freeze_sha256": self.freeze_sha256,
            "records_sha256": self.records_sha256,
            "units": len(self.records),
            "coverage": dict(self.coverage),
            "wall_ms": dict(self.wall_ms),
            "hidden_evaluation_visible_to_runtime": False,
        }


def capture(source_manifest: Path, input_root: Path, out: Path) -> LayoutCapture:
    source_manifest = source_manifest.resolve(strict=True)
    input_root = input_root.resolve(strict=True)
    out = out.resolve()
    if out.exists():
        raise ValueError("LAYOUT_CAPTURE_OUTPUT_MUST_BE_NEW")
    out.mkdir(parents=False, exist_ok=False)
    rows: list[dict[str, Any]] = []
    for line in source_manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("benchmark") == "olmocr":
            rows.append(row)
    if len(rows) != EXPECTED_UNITS:
        raise ValueError("LAYOUT_CAPTURE_DENOMINATOR_MISMATCH")
    selected = [
        {
            "case_key": row["case_key"],
            "input_relative_path": row["input_relative_path"],
            "input_png_sha256": row["input_png_sha256"],
            "original_source_sha256": row["original_source_sha256"],
        }
        for row in rows
    ]
    freeze = {
        "schema": SCHEMA,
        "probe_id": PROBE_ID,
        "development_only": True,
        "hidden_evaluation_visible_to_runtime": False,
        "source_manifest_sha256": digest(source_manifest),
        "selected_units": len(selected),
        "selected_source_rows_sha256": "sha256:"
        + hashlib.sha256(
            json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "code_sha256": digest(Path(__file__).resolve()),
        "runtime": {
            "python": platform.python_version(),
            "pillow": pillow_version,
            "platform": platform.platform(),
            "container_image": None,
            "model": None,
        },
        "parameters": {
            "raster_width": RASTER_WIDTH,
            "ink_threshold": INK_THRESHOLD,
            "gutter_max_ink_row_fraction": GUTTER_MAX_INK_ROW_FRACTION,
            "gutter_min_width_fraction": GUTTER_MIN_WIDTH_FRACTION,
            "long_line_min_fraction": LONG_LINE_MIN_FRACTION,
        },
    }
    _write_json(out / "FREEZE.json", freeze)

    records_path = out / "records.jsonl"
    wall_values: list[float] = []
    measured = 0
    failed = 0
    with records_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            relative = Path(str(row["input_relative_path"]))
            image_path = (input_root / relative).resolve(strict=True)
            if input_root not in image_path.parents:
                raise ValueError("LAYOUT_INPUT_PATH_ESCAPE")
            if digest(image_path) != row["input_png_sha256"]:
                raise ValueError("LAYOUT_INPUT_HASH_MISMATCH")
            began = time.perf_counter()
            values: dict[str, float | int | None]
            try:
                values = measure_image(image_path)
                status = "measured"
                measured += 1
            except Exception:
                values = {
                    "column_count": None,
                    "table_line_density": None,
                    "ink_coverage": None,
                    "raster_width": None,
                    "raster_height": None,
                }
                status = "failed"
                failed += 1
            wall_ms = (time.perf_counter() - began) * 1000.0
            wall_values.append(wall_ms)
            record = {
                "case_key": row["case_key"],
                "input_png_sha256": row["input_png_sha256"],
                "original_source_sha256": row["original_source_sha256"],
                "status": status,
                "authority_checked": False,
                "authority_domain": None,
                "wall_ms": wall_ms,
                **values,
            }
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    result = {
        "schema": SCHEMA,
        "probe_id": PROBE_ID,
        "development_only": True,
        "hidden_evaluation_visible_to_runtime": False,
        "selected_units": len(rows),
        "records": len(rows),
        "measured": measured,
        "failed": failed,
        "records_sha256": digest(records_path),
        "wall_ms": {
            "p50": _percentile(wall_values, 0.50),
            "p95": _percentile(wall_values, 0.95),
            "p99": _percentile(wall_values, 0.99),
            "total": sum(wall_values),
        },
        "gpu_spend_usd": 0,
        "model_calls": 0,
    }
    _write_json(out / "RESULT.json", result)
    return load_capture(out)


def load_capture(root: Path) -> LayoutCapture:
    root = root.resolve(strict=True)
    freeze_path = (root / "FREEZE.json").resolve(strict=True)
    result_path = (root / "RESULT.json").resolve(strict=True)
    records_path = (root / "records.jsonl").resolve(strict=True)
    if any(path.parent != root for path in (freeze_path, result_path, records_path)):
        raise ValueError("LAYOUT_CAPTURE_PATH_ESCAPE")
    freeze = _json(freeze_path)
    result = _json(result_path)
    if (
        freeze.get("schema") != SCHEMA
        or freeze.get("probe_id") != PROBE_ID
        or freeze.get("development_only") is not True
        or freeze.get("hidden_evaluation_visible_to_runtime") is not False
        or freeze.get("selected_units") != EXPECTED_UNITS
        or freeze.get("code_sha256") != digest(Path(__file__).resolve())
        or result.get("selected_units") != EXPECTED_UNITS
        or result.get("records") != EXPECTED_UNITS
        or result.get("gpu_spend_usd") != 0
        or result.get("model_calls") != 0
        or result.get("records_sha256") != digest(records_path)
    ):
        raise ValueError("LAYOUT_CAPTURE_BINDING_INVALID")
    records: dict[str, Mapping[str, Any]] = {}
    measured = failed = 0
    for line in records_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        case_key = row.get("case_key")
        status = row.get("status")
        if (
            not isinstance(case_key, str)
            or case_key in records
            or status not in {"measured", "failed"}
            or row.get("authority_checked") is not False
            or row.get("authority_domain") is not None
            or not isinstance(row.get("wall_ms"), (int, float))
        ):
            raise ValueError("LAYOUT_CAPTURE_RECORD_INVALID")
        if status == "measured":
            if (
                not isinstance(row.get("column_count"), int)
                or not 1 <= row["column_count"] <= 4
                or not isinstance(row.get("table_line_density"), (int, float))
                or not 0 <= row["table_line_density"] <= 1
                or not isinstance(row.get("ink_coverage"), (int, float))
                or not 0 <= row["ink_coverage"] <= 1
            ):
                raise ValueError("LAYOUT_CAPTURE_MEASUREMENT_INVALID")
            measured += 1
        else:
            failed += 1
        records[case_key] = row
    if (
        len(records) != EXPECTED_UNITS
        or measured != result.get("measured")
        or failed != result.get("failed")
    ):
        raise ValueError("LAYOUT_CAPTURE_DENOMINATOR_INCOMPLETE")
    return LayoutCapture(
        root=root,
        source_manifest_sha256=str(freeze["source_manifest_sha256"]),
        freeze_sha256=digest(freeze_path),
        records_sha256=digest(records_path),
        records=records,
        coverage={
            "layout_measured": measured,
            "layout_failed": failed,
            "authority_measured": 0,
        },
        wall_ms=dict(result["wall_ms"]),
    )


def augment_units(
    units: Sequence[F.UnitFeatures], capture_value: LayoutCapture
) -> list[F.UnitFeatures]:
    if len(units) != EXPECTED_UNITS:
        raise ValueError("LAYOUT_REPLAY_UNIT_DENOMINATOR_MISMATCH")
    updated: list[F.UnitFeatures] = []
    consumed: set[str] = set()
    for unit in units:
        row = capture_value.records.get(unit.case_key)
        if row is None:
            raise ValueError("LAYOUT_REPLAY_UNIT_UNBOUND")
        if (
            row.get("input_png_sha256") != unit.input_png_sha256
            or row.get("original_source_sha256") != unit.original_source_sha256
        ):
            raise ValueError("LAYOUT_REPLAY_SOURCE_BINDING_MISMATCH")
        consumed.add(unit.case_key)
        status = str(row["status"])
        updated.append(
            replace(
                unit,
                authority_domain=None,
                authority_available=False,
                authority_checked=False,
                layout_column_count=(
                    int(row["column_count"]) if status == "measured" else None
                ),
                layout_table_line_density=(
                    float(row["table_line_density"]) if status == "measured" else None
                ),
                layout_ink_coverage=(
                    float(row["ink_coverage"]) if status == "measured" else None
                ),
                layout_feature_wall_ms=float(row["wall_ms"]),
                layout_feature_status=status,
            )
        )
    if consumed != set(capture_value.records):
        raise ValueError("LAYOUT_CAPTURE_ROWS_UNUSED")
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = capture(args.source_manifest, args.input_root, args.out)
    print(json.dumps(result.binding, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_UNITS",
    "LayoutCapture",
    "augment_units",
    "capture",
    "load_capture",
    "measure_image",
]
