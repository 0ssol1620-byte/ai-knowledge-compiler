#!/usr/bin/env python3
"""Convert a PaddleOCR-VL page response into the frozen MinerU block shape."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"Paddle {name} must be a positive number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Paddle {name} must be a positive number") from exc
    if result <= 0:
        raise ValueError(f"Paddle {name} must be a positive number")
    return result


def paddle_response_to_mineru_model(payload: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Return one normalized page of ordered blocks for ``public_core_merge``."""

    if payload.get("error") not in (None, ""):
        raise ValueError("cannot adapt a failed PaddleOCR-VL response")
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError("PaddleOCR-VL response must contain exactly one page")
    page = pages[0]
    if not isinstance(page, dict):
        raise ValueError("PaddleOCR-VL page is invalid")
    result = page.get("res", page)
    if not isinstance(result, dict):
        raise ValueError("PaddleOCR-VL page result is invalid")
    width = _positive_number(result.get("width"), "width")
    height = _positive_number(result.get("height"), "height")
    parsing = result.get("parsing_res_list")
    if not isinstance(parsing, list):
        raise ValueError("PaddleOCR-VL parsing_res_list is missing")

    ordered: list[tuple[tuple[int, float, int], dict[str, Any]]] = []
    for index, raw in enumerate(parsing):
        if not isinstance(raw, dict):
            continue
        bbox = raw.get("block_bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            x1, y1, x2, y2 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        x1, x2 = sorted((max(0.0, min(width, x1)), max(0.0, min(width, x2))))
        y1, y2 = sorted((max(0.0, min(height, y1)), max(0.0, min(height, y2))))
        if x2 <= x1 or y2 <= y1:
            continue
        label = str(raw.get("block_label") or "text").strip().lower().replace("-", "_")
        order = raw.get("block_order")
        if isinstance(order, bool) or not isinstance(order, (int, float)):
            sort_key = (1, float(index), index)
        else:
            sort_key = (0, float(order), index)
        ordered.append(
            (
                sort_key,
                {
                    "bbox": [x1 / width, y1 / height, x2 / width, y2 / height],
                    "type": label,
                    "content": str(raw.get("block_content") or ""),
                    "source": "paddleocr-vl-1.6/parsing_res_list",
                },
            )
        )
    blocks = [block for _, block in sorted(ordered, key=lambda item: item[0])]
    if not blocks:
        raise ValueError("PaddleOCR-VL response contains no valid layout blocks")
    return [blocks]


def convert_file(source: Path, output: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PaddleOCR-VL response root must be an object")
    converted = paddle_response_to_mineru_model(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(converted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    convert_file(args.input.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["convert_file", "paddle_response_to_mineru_model"]
