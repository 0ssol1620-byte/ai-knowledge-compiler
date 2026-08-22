"""Run DeepSeek-OCR-2 with the vendor Transformers inference contract.

Ground truth is never mounted on the inference worker. Results and failures are
preserved per page and arranged as repeat-specific Markdown directories for the
pinned OmniDocBench evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from input_contract import adaptive_repeat_indices, select_inference_inputs
from isolated_case_process import run_isolated_process

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
VENDOR_PROMPT = "<image>\n<|grounding|>Convert the document to markdown. "


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_markdown(result: object, output_dir: Path) -> str:
    """Prefer the returned Markdown, then the vendor's persisted result."""

    if isinstance(result, str) and result.strip():
        return result.strip()
    candidates = sorted(
        [
            *output_dir.rglob("*.md"),
            *output_dir.rglob("*.mmd"),
            *output_dir.rglob("*.txt"),
        ],
        key=lambda path: (path.suffix != ".mmd", path.name),
    )
    for candidate in candidates:
        text = candidate.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return text
    return ""


def gpu_identity() -> dict[str, str]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise RuntimeError("nvidia-smi is required for frozen GPU identity")
    result = subprocess.run(
        [
            executable,
            "--query-gpu=name,uuid,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    name, uuid, driver, memory_mib = [part.strip() for part in result.stdout.strip().split(",")]
    return {
        "name": name,
        "uuid": uuid,
        "driver_version": driver,
        "memory_mib": memory_mib,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--artifact-manifest-sha256", required=True)
    parser.add_argument("--repeats", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--repeat-start-index", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument("--limit", type=int, default=18)
    parser.add_argument(
        "--evidence-class",
        choices=("smoke", "public-core", "public-core-shard", "stratified-audit"),
        default="smoke",
    )
    parser.add_argument("--expected-input-count", type=int)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--parent-input-manifest", type=Path)
    parser.add_argument("--base-size", type=int, default=1024)
    parser.add_argument("--image-size", type=int, default=768)
    parser.add_argument("--case-timeout-seconds", type=int, default=900)
    return parser.parse_args()


def _single_case(spec_path: Path) -> int:
    """Load the frozen model and run one case in a killable child process."""

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    image = Path(str(spec["image"])).resolve()
    output_root = Path(str(spec["output_root"])).resolve()
    markdown_path = Path(str(spec["markdown_path"])).resolve()
    response_path = Path(str(spec["response_path"])).resolve()
    model_path = str(spec["model_path"])
    if not image.is_file() or not model_path:
        raise ValueError("isolated DeepSeek-OCR-2 case spec is invalid")

    import torch
    from transformers import AutoModel, AutoTokenizer

    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        model_path,
        _attn_implementation="flash_attention_2",
        trust_remote_code=True,
        use_safetensors=True,
    )
    model = model.eval().cuda().to(torch.bfloat16)
    model_load_seconds = time.perf_counter() - load_started
    error: str | None = None
    markdown = ""
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        result = model.infer(
            tokenizer,
            prompt=VENDOR_PROMPT,
            image_file=str(image),
            output_path=str(output_root),
            base_size=int(spec["base_size"]),
            image_size=int(spec["image_size"]),
            crop_mode=True,
            save_results=True,
        )
        markdown = resolve_markdown(result, output_root)
        if not markdown:
            error = "empty_markdown"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown + ("\n" if markdown else ""), encoding="utf-8")
    response_path.write_text(
        canonical_json(
            {
                "error": error,
                "model_load_seconds": model_load_seconds,
                "markdown_characters": len(markdown),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def main() -> int:
    args = parse_args()
    if args.case_timeout_seconds < 60:
        raise SystemExit("--case-timeout-seconds must be at least 60")
    if args.output_dir.exists():
        raise SystemExit(f"output directory already exists: {args.output_dir}")
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
    args.output_dir.mkdir(parents=True)

    started_at = time.time()
    runs: list[dict[str, Any]] = []
    model_load_seconds = 0.0
    for repeat_index in repeat_indices:
        repeat_root = args.output_dir / f"repeat-{repeat_index}"
        markdown_root = args.output_dir / f"markdown-repeat-{repeat_index}"
        repeat_root.mkdir()
        markdown_root.mkdir()
        repeat_started = time.perf_counter()
        cases: list[dict[str, Any]] = []
        for image in images:
            case_root = repeat_root / image.stem
            case_root.mkdir()
            case_started = time.perf_counter()
            error: str | None = None
            markdown_path = markdown_root / f"{image.stem}.md"
            response_path = case_root / "isolated-case-response.json"
            spec_path = case_root / "isolated-case-spec.json"
            spec_path.write_text(
                canonical_json(
                    {
                        "image": str(image.resolve()),
                        "output_root": str((case_root / "vendor-output").resolve()),
                        "markdown_path": str(markdown_path.resolve()),
                        "response_path": str(response_path.resolve()),
                        "model_path": args.model_path,
                        "base_size": args.base_size,
                        "image_size": args.image_size,
                    }
                )
                + "\n",
                encoding="utf-8",
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
            if response_path.is_file():
                response = json.loads(response_path.read_text(encoding="utf-8"))
                child_error = response.get("error")
                if error is None and child_error:
                    error = str(child_error)
                model_load_seconds += float(response.get("model_load_seconds", 0.0))
            else:
                error = error or "isolated_child_missing_response"
            if not markdown_path.is_file():
                markdown_path.write_text("", encoding="utf-8")
            markdown = markdown_path.read_text(encoding="utf-8").rstrip()
            cases.append(
                {
                    "case_id": image.stem,
                    "source_sha256": f"sha256:{sha256_file(image)}",
                    "status": "completed" if markdown and error is None else "failed",
                    "error": error,
                    "latency_seconds": time.perf_counter() - case_started,
                    "markdown_sha256": f"sha256:{sha256_file(markdown_path)}",
                    "markdown_characters": len(markdown),
                    "isolation": "one-process-per-case",
                    "case_timeout_seconds": args.case_timeout_seconds,
                }
            )
        run = {
            "repeat_index": repeat_index,
            "latency_seconds": time.perf_counter() - repeat_started,
            "completed": sum(case["status"] == "completed" for case in cases),
            "failed": sum(case["status"] == "failed" for case in cases),
            "cases": cases,
        }
        runs.append(run)
        print(canonical_json({"event": "repeat_completed", **run}), flush=True)

    summary = {
        "schema_version": "1.0.0",
        "candidate_id": "deepseek-ocr-2-3b-transformers",
        "model_path": args.model_path,
        "model_revision": args.model_revision,
        "artifact_manifest_sha256": args.artifact_manifest_sha256,
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
        "model_load_seconds": model_load_seconds,
        "case_process_isolation": True,
        "case_timeout_seconds": args.case_timeout_seconds,
        "started_at_unix": started_at,
        "completed_at_unix": time.time(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "torch": importlib.metadata.version("torch"),
            "transformers": importlib.metadata.version("transformers"),
            "tokenizers": importlib.metadata.version("tokenizers"),
            "flash_attn": importlib.metadata.version("flash-attn"),
            "gpu": gpu_identity(),
        },
        "inference_contract": {
            "prompt_sha256": hashlib.sha256(VENDOR_PROMPT.encode("utf-8")).hexdigest(),
            "base_size": args.base_size,
            "image_size": args.image_size,
            "crop_mode": True,
            "dtype": "bfloat16",
            "attention": "flash_attention_2",
        },
        "runs": runs,
    }
    summary_path = args.output_dir / "run-summary.json"
    summary_path.write_text(canonical_json(summary) + "\n", encoding="utf-8")
    print(
        canonical_json(
            {
                "summary": str(summary_path),
                "sha256": f"sha256:{sha256_file(summary_path)}",
                "completed": sum(run["completed"] for run in runs),
                "failed": sum(run["failed"] for run in runs),
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--single-case-spec":
        raise SystemExit(_single_case(Path(sys.argv[2])))
    raise SystemExit(main())
