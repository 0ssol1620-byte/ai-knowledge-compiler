"""Build ground-truth-free public benchmark source and inference manifests.

The official benchmark indexes are read only on the evaluator side to discover
the source file and page for each case.  Expected text, rules, labels, and other
ground-truth fields are never copied into either emitted manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
EXPECTED_SOURCE_COUNTS = {
    "omnidocbench": 1651,
    "parsebench": 2078,
    "olmocr-bench": 1403,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def content_sha256(payload: dict[str, Any]) -> str:
    content = {
        key: value
        for key, value in payload.items()
        if key not in {"content_sha256", "receipt_sha256"}
    }
    return f"sha256:{hashlib.sha256(canonical_json(content).encode()).hexdigest()}"


@dataclass(frozen=True, slots=True)
class PublicSource:
    case_id: str
    source_relative_path: str
    source_sha256: str
    media_type: str
    page_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "source_relative_path": self.source_relative_path,
            "source_sha256": self.source_sha256,
            "media_type": self.media_type,
            "page_index": self.page_index,
        }


def _safe_source(dataset_root: Path, relative_path: str) -> Path:
    normalized = relative_path.replace("\\", "/")
    if Path(normalized).is_absolute():
        raise ValueError(f"absolute source path is forbidden: {relative_path}")
    root = dataset_root.resolve()
    source = (root / normalized).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source escapes dataset root: {relative_path}") from exc
    io_source = (
        Path(f"\\\\?\\{source}")
        if os.name == "nt" and not str(source).startswith("\\\\?\\")
        else source
    )
    if not io_source.is_file():
        raise ValueError(f"source is missing: {relative_path}")
    return io_source


def _page_index(value: Any, *, zero_based: bool = False) -> int:
    if value is None:
        return 0
    page = int(value)
    if page < 0 or (not zero_based and page == 0):
        raise ValueError(f"invalid page value: {value}")
    return page if zero_based else page - 1


def _stable_case_id(benchmark_id: str, relative_path: str, page_index: int) -> str:
    identity = f"{benchmark_id}\n{relative_path}\n{page_index}".encode()
    return f"{benchmark_id}-{hashlib.sha256(identity).hexdigest()[:24]}"


def _deduplicate(rows: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    by_path: dict[str, int] = {}
    for relative_path, page_index in rows:
        prior = by_path.setdefault(relative_path, page_index)
        if prior != page_index:
            raise ValueError(f"source has conflicting page references: {relative_path}")
    return sorted(by_path.items())


def _source_refs(dataset_root: Path, benchmark_id: str) -> list[tuple[str, int]]:
    if benchmark_id == "omnidocbench":
        index = json.loads((dataset_root / "OmniDocBench.json").read_text(encoding="utf-8"))
        return _deduplicate(
            (
                f"images/{row['page_info']['image_path']}",
                _page_index(row["page_info"].get("page_no"), zero_based=True),
            )
            for row in index
        )
    if benchmark_id == "parsebench":
        parse_index_files = (
            "chart.jsonl",
            "layout.jsonl",
            "table.jsonl",
            "text_content.jsonl",
            "text_formatting.jsonl",
        )
        return _jsonl_source_refs(dataset_root, parse_index_files, pdf_prefix="")
    if benchmark_id == "olmocr-bench":
        index_root = dataset_root / "bench_data"
        olm_index_files = tuple(path.name for path in sorted(index_root.glob("*.jsonl")))
        if not olm_index_files:
            raise ValueError("olmOCR-Bench contains no official JSONL indexes")
        return _jsonl_source_refs(
            index_root, olm_index_files, pdf_prefix="bench_data/pdfs/"
        )
    raise ValueError(f"unsupported public benchmark: {benchmark_id}")


def _jsonl_source_refs(
    index_root: Path,
    index_files: Iterable[str],
    *,
    pdf_prefix: str,
) -> list[tuple[str, int]]:
    refs: list[tuple[str, int]] = []
    for filename in index_files:
        index_path = index_root / filename
        if not index_path.is_file():
            raise ValueError(f"official index is missing: {index_path}")
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            refs.append((f"{pdf_prefix}{row['pdf']}", _page_index(row.get("page"))))
    return _deduplicate(refs)


def build_source_manifest(
    *, dataset_root: Path, benchmark_id: str, dataset_revision: str
) -> dict[str, Any]:
    root = dataset_root.resolve()
    sources: list[PublicSource] = []
    for relative_path, page_index in _source_refs(root, benchmark_id):
        source = _safe_source(root, relative_path)
        suffix = source.suffix.casefold()
        media_type = "image" if suffix in IMAGE_EXTENSIONS else "pdf" if suffix == ".pdf" else ""
        if not media_type:
            raise ValueError(f"unsupported public source type: {relative_path}")
        sources.append(
            PublicSource(
                case_id=_stable_case_id(benchmark_id, relative_path, page_index),
                source_relative_path=relative_path.replace("\\", "/"),
                source_sha256=sha256_file(source),
                media_type=media_type,
                page_index=page_index,
            )
        )
    expected = EXPECTED_SOURCE_COUNTS[benchmark_id]
    if len(sources) != expected:
        raise ValueError(
            f"{benchmark_id} source count {len(sources)} does not match frozen count {expected}"
        )
    payload: dict[str, Any] = {
        "schema": "folynta.public-core-source-manifest.v1",
        "benchmark_id": benchmark_id,
        "dataset_revision": dataset_revision,
        "ground_truth_mounted": False,
        "index_use": "source-enumeration-only",
        "excluded_index_fields": "all fields except source path and page",
        "source_count": len(sources),
        "complete_source_coverage": True,
        "sources": [source.as_dict() for source in sources],
    }
    payload["content_sha256"] = content_sha256(payload)
    return payload


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _render_pdf(source: Path, target: Path, *, page_index: int, dpi: int) -> None:
    try:
        import pypdfium2
    except ImportError as exc:
        raise RuntimeError("pypdfium2 is required to stage PDF benchmark sources") from exc
    document = pypdfium2.PdfDocument(str(source))
    try:
        if page_index >= len(document):
            raise ValueError(f"PDF page {page_index} is unavailable: {source}")
        page = document[page_index]
        try:
            bitmap = page.render(scale=dpi / 72.0)
            try:
                image = bitmap.to_pil()
                image.save(target, format="PNG", compress_level=9)
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _stage_image(source: Path, target: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to stage image benchmark sources") from exc
    with Image.open(source) as image:
        image.convert("RGB").save(target, format="PNG", compress_level=9)


def stage_inference_inputs(
    *,
    dataset_root: Path,
    source_manifest: dict[str, Any],
    stage_dir: Path,
    dpi: int,
) -> dict[str, Any]:
    if dpi <= 0:
        raise ValueError("DPI must be positive")
    stage_dir.mkdir(parents=True, exist_ok=False)
    input_dir = stage_dir / "inputs"
    input_dir.mkdir()
    staged: list[dict[str, Any]] = []
    try:
        for item in source_manifest["sources"]:
            source = _safe_source(dataset_root, item["source_relative_path"])
            target = input_dir / f"{item['case_id']}.png"
            if item["media_type"] == "image":
                _stage_image(source, target)
            else:
                _render_pdf(source, target, page_index=item["page_index"], dpi=dpi)
            staged.append(
                {
                    **item,
                    "input_relative_path": target.relative_to(stage_dir).as_posix(),
                    "input_sha256": sha256_file(target),
                }
            )
    except Exception:
        shutil.rmtree(stage_dir)
        raise
    payload: dict[str, Any] = {
        "schema": "folynta.public-core-inference-inputs.v1",
        "benchmark_id": source_manifest["benchmark_id"],
        "dataset_revision": source_manifest["dataset_revision"],
        "source_manifest_sha256": source_manifest["content_sha256"],
        "ground_truth_mounted": False,
        "renderer": {
            "pdf_backend": "pypdfium2",
            "dpi": dpi,
            "output_format": "png",
        },
        "source_count": len(staged),
        "input_count": len(staged),
        "complete_source_coverage": True,
        "complete_input_coverage": True,
        "inputs": staged,
    }
    payload["content_sha256"] = content_sha256(payload)
    write_manifest(stage_dir / "inference-input-manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-id", choices=tuple(EXPECTED_SOURCE_COUNTS), required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument("--source-manifest-output", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=144)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_source_manifest(
        dataset_root=args.dataset_root,
        benchmark_id=args.benchmark_id,
        dataset_revision=args.dataset_revision,
    )
    write_manifest(args.source_manifest_output, manifest)
    output: dict[str, Any] = {
        "benchmark_id": args.benchmark_id,
        "source_count": manifest["source_count"],
        "source_manifest": str(args.source_manifest_output),
        "source_manifest_sha256": manifest["content_sha256"],
    }
    if args.stage_dir is not None:
        staged = stage_inference_inputs(
            dataset_root=args.dataset_root,
            source_manifest=manifest,
            stage_dir=args.stage_dir,
            dpi=args.dpi,
        )
        output.update(
            {
                "input_count": staged["input_count"],
                "input_manifest": str(args.stage_dir / "inference-input-manifest.json"),
                "input_manifest_sha256": staged["content_sha256"],
            }
        )
    print(canonical_json(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_SOURCE_COUNTS",
    "build_source_manifest",
    "content_sha256",
    "sha256_file",
    "stage_inference_inputs",
    "write_manifest",
]
