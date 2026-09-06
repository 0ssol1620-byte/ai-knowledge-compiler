"""Prepare a deterministic, ground-truth-free 200-page OmniDocBench Stage-1 slice.

Selection uses source-image properties only.  The official annotation is never
opened by this program and the staged GPU bundle contains only selected images
plus a content-bound public-core-shard manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

_SCHEMA = "folynta.public-core-inference-shard.v1"
_PAGE_SUFFIXES = (
    re.compile(r"(?i)(?:[_-]page[_-]?\d+)$"),
    re.compile(r"(?i)(?:[_-]p(?:age)?\d+)$"),
    re.compile(r"(?i)(?:[_-]pg\d+(?:[_-]pg\d+)*)$"),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_sha256(value: dict[str, Any]) -> str:
    content = {key: item for key, item in value.items() if key != "content_sha256"}
    return "sha256:" + hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _document_id(source_relative_path: str) -> str:
    source = Path(source_relative_path.replace("\\", "/"))
    stem = source.stem
    for pattern in _PAGE_SUFFIXES:
        updated = pattern.sub("", stem)
        if updated != stem:
            stem = updated
            break
    return f"{source.parent.as_posix()}/{stem}".lstrip("./")


def _histogram_quantile(histogram: list[int], fraction: float) -> int:
    total = sum(histogram)
    target = total * fraction
    seen = 0
    for value, count in enumerate(histogram):
        seen += count
        if seen >= target:
            return value
    return 255


@dataclass(frozen=True, slots=True)
class SourceScore:
    case_id: str
    document_id: str
    input_relative_path: str
    width: int
    height: int
    file_bytes: int
    entropy: float
    edge_density: float
    dynamic_range: float
    megapixel_factor: float
    compression_density: float
    score: float

    def as_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "document_id": self.document_id,
            "input_relative_path": self.input_relative_path,
            "width": self.width,
            "height": self.height,
            "file_bytes": self.file_bytes,
            "entropy": round(self.entropy, 8),
            "edge_density": round(self.edge_density, 8),
            "dynamic_range": round(self.dynamic_range, 8),
            "megapixel_factor": round(self.megapixel_factor, 8),
            "compression_density": round(self.compression_density, 8),
            "hardness_score": round(self.score, 8),
        }


def _score_source(*, root: Path, item: dict[str, Any]) -> SourceScore:
    relative = str(item["input_relative_path"])
    source = (root / relative).resolve()
    try:
        source.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("parent manifest input escapes staged input root") from exc
    if not source.is_file():
        raise FileNotFoundError(source)
    expected = str(item["input_sha256"])
    observed = _sha256_file(source)
    if observed != expected:
        raise ValueError(f"input hash mismatch for {item['case_id']}")

    with Image.open(source) as image:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError(f"invalid image dimensions for {item['case_id']}")
        gray = image.convert("L")
        gray.thumbnail((768, 768), Image.Resampling.LANCZOS)
        entropy = min(max(gray.entropy() / 8.0, 0.0), 1.0)
        histogram = gray.histogram()
        p10 = _histogram_quantile(histogram, 0.10)
        p90 = _histogram_quantile(histogram, 0.90)
        dynamic_range = min(max((p90 - p10) / 255.0, 0.0), 1.0)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_hist = edges.histogram()
        edge_pixels = sum(edge_hist[32:])
        edge_density = edge_pixels / max(1, gray.width * gray.height)

    pixels = width * height
    megapixel_factor = min(pixels / 4_000_000.0, 1.0)
    bytes_per_pixel = source.stat().st_size / pixels
    compression_density = min(math.log2(1.0 + bytes_per_pixel) / 2.0, 1.0)
    score = (
        0.34 * entropy
        + 0.36 * min(edge_density * 2.5, 1.0)
        + 0.14 * dynamic_range
        + 0.10 * megapixel_factor
        + 0.06 * compression_density
    )
    return SourceScore(
        case_id=str(item["case_id"]),
        document_id=_document_id(str(item["source_relative_path"])),
        input_relative_path=relative,
        width=width,
        height=height,
        file_bytes=source.stat().st_size,
        entropy=entropy,
        edge_density=edge_density,
        dynamic_range=dynamic_range,
        megapixel_factor=megapixel_factor,
        compression_density=compression_density,
        score=score,
    )


def _select_diverse(
    scored: list[SourceScore], *, count: int, max_pages_per_document: int
) -> list[SourceScore]:
    ranked = sorted(scored, key=lambda row: (-row.score, row.document_id, row.case_id))
    selected: list[SourceScore] = []
    per_document: dict[str, int] = {}
    selected_ids: set[str] = set()
    for row in ranked:
        if per_document.get(row.document_id, 0) >= max_pages_per_document:
            continue
        selected.append(row)
        selected_ids.add(row.case_id)
        per_document[row.document_id] = per_document.get(row.document_id, 0) + 1
        if len(selected) == count:
            return selected
    for row in ranked:
        if row.case_id in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(row.case_id)
        if len(selected) == count:
            return selected
    raise ValueError(f"could select only {len(selected)} of {count} requested pages")


def prepare(
    *,
    parent_stage_dir: Path,
    output_dir: Path,
    count: int,
    max_pages_per_document: int,
) -> dict[str, Any]:
    if output_dir.exists():
        raise ValueError("output directory already exists")
    if not 100 <= count <= 300:
        raise ValueError("Stage-1 slice count must be between 100 and 300")
    if not 1 <= max_pages_per_document <= 10:
        raise ValueError("max-pages-per-document must be between 1 and 10")

    parent_manifest_path = parent_stage_dir / "inference-input-manifest.json"
    parent = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    if parent.get("schema") != "folynta.public-core-inference-inputs.v1":
        raise ValueError("parent manifest schema is unsupported")
    if parent.get("benchmark_id") != "omnidocbench":
        raise ValueError("Stage-1 hard slice requires OmniDocBench")
    if parent.get("ground_truth_mounted") is not False:
        raise ValueError("parent manifest must be ground-truth-free")
    inputs = parent.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != int(parent.get("input_count", -1)):
        raise ValueError("parent input manifest is incomplete")
    parent_content_hash = str(parent.get("content_sha256", ""))
    if parent_content_hash != _content_sha256(parent):
        raise ValueError("parent manifest content hash is invalid")

    scored = [_score_source(root=parent_stage_dir, item=item) for item in inputs]
    selected = _select_diverse(
        scored, count=count, max_pages_per_document=max_pages_per_document
    )
    item_by_case = {str(item["case_id"]): item for item in inputs}
    selected_items = [item_by_case[row.case_id] for row in selected]

    output_inputs = output_dir / "inputs"
    output_inputs.mkdir(parents=True)
    link_method_counts = {"hardlink": 0, "copy": 0}
    for item in selected_items:
        source = parent_stage_dir / str(item["input_relative_path"])
        target = output_inputs / source.name
        try:
            os.link(source, target)
            link_method_counts["hardlink"] += 1
        except OSError:
            shutil.copy2(source, target)
            link_method_counts["copy"] += 1
        if _sha256_file(target) != str(item["input_sha256"]):
            raise ValueError(f"staged input hash mismatch for {item['case_id']}")

    shard: dict[str, Any] = {
        "schema": _SCHEMA,
        "benchmark_id": parent["benchmark_id"],
        "dataset_revision": parent["dataset_revision"],
        "ground_truth_mounted": False,
        "source_count": parent["source_count"],
        "input_count": len(selected_items),
        "complete_source_coverage": False,
        "complete_input_coverage": True,
        "parent_input_manifest_sha256": parent_content_hash,
        "shard_index": 0,
        "shard_count": 1,
        "inputs": selected_items,
    }
    shard["content_sha256"] = _content_sha256(shard)
    manifest_path = output_dir / "inference-input-manifest.json"
    manifest_path.write_text(
        json.dumps(shard, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    selection_receipt: dict[str, Any] = {
        "schema": "tavonel.assurance-stage1-hard-slice.v1",
        "research_only": True,
        "ground_truth_read_by_selector": False,
        "ground_truth_mounted_on_gpu": False,
        "benchmark_id": parent["benchmark_id"],
        "dataset_revision": parent["dataset_revision"],
        "parent_input_manifest_sha256": parent_content_hash,
        "slice_manifest_sha256": shard["content_sha256"],
        "source_inventory_count": len(scored),
        "selected_count": len(selected),
        "max_pages_per_document": max_pages_per_document,
        "unique_document_count": len({row.document_id for row in selected}),
        "selection_algorithm": {
            "name": "source_only_visual_complexity_v1",
            "weights": {
                "entropy": 0.34,
                "edge_density_capped_x2_5": 0.36,
                "dynamic_range": 0.14,
                "megapixel_factor": 0.10,
                "compression_density": 0.06,
            },
            "tie_break": ["document_id", "case_id"],
        },
        "stage_method_counts": link_method_counts,
        "selected": [row.as_record() for row in selected],
    }
    selection_receipt["receipt_sha256"] = _content_sha256(selection_receipt)
    receipt_path = output_dir / "selection-receipt.json"
    receipt_path.write_text(
        json.dumps(selection_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": str(manifest_path),
        "selection_receipt": str(receipt_path),
        "selected_count": len(selected),
        "unique_document_count": selection_receipt["unique_document_count"],
        "manifest_sha256": shard["content_sha256"],
        "receipt_sha256": selection_receipt["receipt_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-stage-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--max-pages-per-document", type=int, default=4)
    args = parser.parse_args()
    result = prepare(
        parent_stage_dir=args.parent_stage_dir,
        output_dir=args.output_dir,
        count=args.count,
        max_pages_per_document=args.max_pages_per_document,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
