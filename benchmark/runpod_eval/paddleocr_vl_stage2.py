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

from input_contract import adaptive_repeat_indices, select_inference_inputs
from isolated_case_process import run_isolated_process

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
    parser.add_argument("--repeats", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--repeat-start-index", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--evidence-class",
        choices=("smoke", "public-core", "public-core-shard", "stratified-audit"),
        default="smoke",
    )
    parser.add_argument("--expected-input-count", type=int)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--parent-input-manifest", type=Path)
    parser.add_argument("--case-timeout-seconds", type=int, default=600)
    return parser.parse_args()


def _single_case(spec_path: Path) -> int:
    """Run one PaddleOCR-VL case in a killable child process."""

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    image = Path(str(spec["image"])).resolve()
    response_path = Path(str(spec["response_path"])).resolve()
    markdown_path = Path(str(spec["markdown_path"])).resolve()
    pipeline_options = spec["pipeline_options"]
    if not image.is_file() or not isinstance(pipeline_options, dict):
        raise ValueError("isolated PaddleOCR-VL case spec is invalid")

    from paddleocr import PaddleOCRVL

    init_started = time.perf_counter()
    pipeline = PaddleOCRVL(**pipeline_options)
    initialization_seconds = time.perf_counter() - init_started
    error: str | None = None
    pages: list[dict[str, Any]] = []
    page_markdown: list[str] = []
    try:
        for item in pipeline.predict(str(image)):
            page = jsonable_result(item)
            pages.append(page)
            page_markdown.append(markdown_result(item, page))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    markdown_text = "\n\n".join(part for part in page_markdown if part)
    if error is None and not markdown_text.strip():
        error = "empty_markdown"
    response_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(
        canonical_json(
            {
                "error": error,
                "initialization_seconds": initialization_seconds,
                "pages": pages,
                "page_markdown": page_markdown,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        markdown_text.rstrip() + ("\n" if markdown_text else ""),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    args = parse_args()
    if args.case_timeout_seconds < 60:
        raise SystemExit("--case-timeout-seconds must be at least 60")
    try:
        selection = select_inference_inputs(
            input_dir=args.input_dir,
            supported_extensions=SUPPORTED_IMAGES,
            limit=args.limit,
            evidence_class=args.evidence_class,
            expected_input_count=args.expected_input_count,
            input_manifest=args.input_manifest,
            parent_input_manifest=args.parent_input_manifest,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        repeat_indices = adaptive_repeat_indices(
            evidence_class=args.evidence_class,
            repeats=args.repeats,
            repeat_start_index=args.repeat_start_index,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    all_images = selection.inventory
    images = selection.selected
    args.output_dir.mkdir(parents=True, exist_ok=False)

    started_at = time.time()
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
    runs: list[dict[str, Any]] = []
    initialization_seconds_total = 0.0
    for repeat_index in repeat_indices:
        repeat_root = args.output_dir / f"repeat-{repeat_index}"
        repeat_root.mkdir()
        markdown_root = args.output_dir / f"markdown-repeat-{repeat_index}"
        markdown_root.mkdir()
        cases: list[dict[str, Any]] = []
        for image in images:
            case_root = repeat_root / image.stem
            case_root.mkdir()
            case_started = time.perf_counter()
            error: str | None = None
            output_path = repeat_root / f"{image.stem}.json"
            markdown_path = markdown_root / f"{image.stem}.md"
            spec_path = case_root / "isolated-case-spec.json"
            spec_path.write_text(
                canonical_json(
                    {
                        "image": str(image.resolve()),
                        "response_path": str(output_path.resolve()),
                        "markdown_path": str(markdown_path.resolve()),
                        "pipeline_options": pipeline_options,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
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
            completed = run_isolated_process(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--single-case-spec",
                    str(spec_path),
                ],
                timeout_seconds=args.case_timeout_seconds,
            )
            (case_root / "child.stdout.log").write_text(
                completed.stdout, encoding="utf-8"
            )
            (case_root / "child.stderr.log").write_text(
                completed.stderr, encoding="utf-8"
            )
            if completed.timed_out:
                error = f"case_timeout_{args.case_timeout_seconds}s"
            elif completed.return_code != 0:
                error = f"isolated_child_exit_{completed.return_code}"
            if output_path.is_file():
                response = json.loads(output_path.read_text(encoding="utf-8"))
                child_error = response.get("error")
                if error is None and child_error:
                    error = str(child_error)
                initialization_seconds_total += float(
                    response.get("initialization_seconds", 0.0)
                )
            else:
                response = {
                    "error": error or "isolated_child_missing_response",
                    "initialization_seconds": 0.0,
                    "pages": [],
                    "page_markdown": [],
                }
                error = str(response["error"])
                output_path.write_text(
                    canonical_json(response) + "\n", encoding="utf-8"
                )
            if not markdown_path.is_file():
                markdown_path.write_text("", encoding="utf-8")
            latency_seconds = time.perf_counter() - case_started
            markdown_text = markdown_path.read_text(encoding="utf-8")
            if error is None and not markdown_text.strip():
                error = "empty_markdown"
            record = {
                "case_id": image.stem,
                "source_path": image.relative_to(args.input_dir).as_posix(),
                "source_sha256": f"sha256:{sha256_file(image)}",
                "latency_seconds": latency_seconds,
                "status": "completed" if error is None else "failed",
                "error": error,
                "isolation": "one-process-per-case",
                "case_timeout_seconds": args.case_timeout_seconds,
            }
            record["artifact_sha256"] = f"sha256:{sha256_file(output_path)}"
            record["markdown_sha256"] = f"sha256:{sha256_file(markdown_path)}"
            record["markdown_characters"] = len(markdown_text)
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
        "evidence_class": args.evidence_class,
        "input_inventory_count": len(all_images),
        "input_count": len(images),
        "complete_input_coverage": selection.complete_input_coverage,
        "input_manifest_sha256": selection.input_manifest_sha256,
        "benchmark_id": selection.benchmark_id,
        "dataset_revision": selection.dataset_revision,
        "repeat_count": len(repeat_indices),
        "repeat_start_index": repeat_indices[0],
        "started_at_unix": started_at,
        "completed_at_unix": time.time(),
        "initialization_seconds": initialization_seconds_total,
        "case_process_isolation": True,
        "case_timeout_seconds": args.case_timeout_seconds,
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
    if len(sys.argv) == 3 and sys.argv[1] == "--single-case-spec":
        raise SystemExit(_single_case(Path(sys.argv[2])))
    raise SystemExit(main())
