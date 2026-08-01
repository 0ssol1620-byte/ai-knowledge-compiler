"""Run a reproducible PaddleOCR-VL Stage-2 inference smoke on a GPU Pod.

This program deliberately has no access to benchmark ground truth.  It freezes
provider output, timings, package identity, model revision, and GPU identity so
the evaluator can score the artifacts later in a separate environment.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "missing"


def gpu_identity() -> dict[str, str]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,uuid,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    name, uuid, driver, memory_mib = [part.strip() for part in result.stdout.strip().split(",")]
    return {
        "name": name,
        "uuid": uuid,
        "driver_version": driver,
        "memory_mib": memory_mib,
    }


def jsonable_result(result: Any) -> dict[str, Any]:
    value = getattr(result, "json", None)
    value = value() if callable(value) else value
    if not isinstance(value, dict):
        raise TypeError("PaddleOCR result does not expose a JSON object")
    return value


def markdown_payload(value: Any) -> str:
    """Extract Markdown text from a PaddleX Markdown payload."""
    markdown = value
    if isinstance(markdown, dict):
        for key in ("markdown_texts", "markdown_text", "text"):
            candidate = markdown.get(key)
            if isinstance(candidate, str):
                return candidate
    if isinstance(markdown, str):
        return markdown
    return ""


def markdown_result(result: Any, value: dict[str, Any]) -> str:
    """Extract evaluator input without depending on a single PaddleX JSON shape.

    PaddleX exposes Markdown through a separate ``result.markdown`` attribute;
    it is intentionally not duplicated in ``result.json``.  The attribute is
    therefore authoritative, with legacy JSON shapes retained as fallbacks.
    """
    markdown = getattr(result, "markdown", None)
    markdown = markdown() if callable(markdown) else markdown
    extracted = markdown_payload(markdown)
    if extracted:
        return extracted
    payload = value.get("res", value)
    extracted = markdown_payload(payload.get("markdown") if isinstance(payload, dict) else None)
    if extracted:
        return extracted
    for key in ("markdown_texts", "markdown_text", "text"):
        candidate = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(candidate, str):
            return candidate
    return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--artifact-manifest-sha256", required=True)
    parser.add_argument("--vl-backend")
    parser.add_argument("--vl-server-url")
    parser.add_argument("--vl-max-concurrency", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=3, choices=(1, 3))
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    images = [
        path
        for path in sorted(args.input_dir.rglob("*"))
        if path.is_file() and path.suffix.casefold() in SUPPORTED_IMAGES
    ][: args.limit]
    if not images:
        raise SystemExit("no supported images found")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    from paddleocr import PaddleOCRVL

    started_at = time.time()
    init_started = time.perf_counter()
    pipeline_options: dict[str, Any] = {
        "pipeline_version": "v1.6",
        "device": "gpu:0",
    }
    if args.vl_backend:
        if not args.vl_server_url:
            raise SystemExit("--vl-server-url is required with --vl-backend")
        pipeline_options.update(
            vl_rec_backend=args.vl_backend,
            vl_rec_server_url=args.vl_server_url,
            vl_rec_max_concurrency=args.vl_max_concurrency,
        )
    pipeline = PaddleOCRVL(**pipeline_options)
    init_seconds = time.perf_counter() - init_started

    runs: list[dict[str, Any]] = []
    for repeat_index in range(1, args.repeats + 1):
        repeat_root = args.output_dir / f"repeat-{repeat_index}"
        repeat_root.mkdir()
        markdown_root = args.output_dir / f"markdown-repeat-{repeat_index}"
        markdown_root.mkdir()
        cases: list[dict[str, Any]] = []
        for image in images:
            case_started = time.perf_counter()
            error: str | None = None
            pages: list[dict[str, Any]] = []
            page_markdown: list[str] = []
            try:
                print(
                    json.dumps(
                        {
                            "event": "case_started",
                            "repeat": repeat_index,
                            "case_id": image.stem,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                for item in pipeline.predict(str(image)):
                    page = jsonable_result(item)
                    pages.append(page)
                    page_markdown.append(markdown_result(item, page))
            except Exception as exc:  # failure is evidence and must remain in the run
                error = f"{type(exc).__name__}: {exc}"
            latency_seconds = time.perf_counter() - case_started
            record = {
                "case_id": image.stem,
                "source_path": image.relative_to(args.input_dir).as_posix(),
                "source_sha256": f"sha256:{sha256_file(image)}",
                "latency_seconds": latency_seconds,
                "status": "completed" if error is None else "failed",
                "error": error,
                "pages": pages,
                "page_markdown": page_markdown,
            }
            output_path = repeat_root / f"{image.stem}.json"
            output_path.write_text(canonical_json(record) + "\n", encoding="utf-8")
            markdown_text = "\n\n".join(part for part in page_markdown if part)
            (markdown_root / f"{image.stem}.md").write_text(
                markdown_text.rstrip() + ("\n" if markdown_text else ""),
                encoding="utf-8",
            )
            record["artifact_sha256"] = f"sha256:{sha256_file(output_path)}"
            record.pop("pages")
            record.pop("page_markdown")
            cases.append(record)
            print(
                json.dumps(
                    {
                        "event": "case_completed",
                        "repeat": repeat_index,
                        "case_id": image.stem,
                        "status": record["status"],
                        "latency_seconds": latency_seconds,
                        "markdown_characters": len(markdown_text),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        runs.append(
            {
                "repeat_index": repeat_index,
                "completed": sum(case["status"] == "completed" for case in cases),
                "failed": sum(case["status"] == "failed" for case in cases),
                "total_latency_seconds": sum(case["latency_seconds"] for case in cases),
                "cases": cases,
            }
        )

    summary = {
        "schema_version": "1.0.0",
        "candidate_id": "paddleocr-vl-1.6",
        "model_revision": args.model_revision,
        "artifact_manifest_sha256": args.artifact_manifest_sha256,
        "pipeline_version": "v1.6",
        "inference_backend": args.vl_backend or "paddle_dynamic",
        "ground_truth_mounted": False,
        "input_count": len(images),
        "repeat_count": args.repeats,
        "started_at_unix": started_at,
        "completed_at_unix": time.time(),
        "initialization_seconds": init_seconds,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "paddlepaddle_gpu": package_version("paddlepaddle-gpu"),
            "paddleocr": package_version("paddleocr"),
            "gpu": gpu_identity(),
        },
        "runs": runs,
    }
    summary_path = args.output_dir / "run-summary.json"
    summary_path.write_text(canonical_json(summary) + "\n", encoding="utf-8")
    print(json.dumps({
        "summary": str(summary_path),
        "sha256": f"sha256:{sha256_file(summary_path)}",
        "completed": sum(run["completed"] for run in runs),
        "failed": sum(run["failed"] for run in runs),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
