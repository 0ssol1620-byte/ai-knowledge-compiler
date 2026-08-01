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
    parser.add_argument("--repeats", type=int, default=3, choices=(1, 3))
    parser.add_argument("--limit", type=int, default=18)
    parser.add_argument("--base-size", type=int, default=1024)
    parser.add_argument("--image-size", type=int, default=768)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"output directory already exists: {args.output_dir}")
    images = [
        path
        for path in sorted(args.input_dir.rglob("*"))
        if path.is_file() and path.suffix.casefold() in SUPPORTED_IMAGES
    ][: args.limit]
    if not images:
        raise SystemExit("no supported images found")
    args.output_dir.mkdir(parents=True)

    import torch
    from transformers import AutoModel, AutoTokenizer

    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        args.model_path,
        _attn_implementation="flash_attention_2",
        trust_remote_code=True,
        use_safetensors=True,
    )
    model = model.eval().cuda().to(torch.bfloat16)
    model_load_seconds = time.perf_counter() - load_started

    started_at = time.time()
    runs: list[dict[str, Any]] = []
    for repeat_index in range(1, args.repeats + 1):
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
            markdown = ""
            try:
                result = model.infer(
                    tokenizer,
                    prompt=VENDOR_PROMPT,
                    image_file=str(image),
                    output_path=str(case_root),
                    base_size=args.base_size,
                    image_size=args.image_size,
                    crop_mode=True,
                    save_results=True,
                )
                markdown = resolve_markdown(result, case_root)
            except Exception as exc:  # preserve failures as evidence
                error = f"{type(exc).__name__}: {exc}"
            target = markdown_root / f"{image.stem}.md"
            target.write_text(markdown + ("\n" if markdown else ""), encoding="utf-8")
            cases.append(
                {
                    "case_id": image.stem,
                    "source_sha256": f"sha256:{sha256_file(image)}",
                    "status": "completed" if markdown else "failed",
                    "error": error,
                    "latency_seconds": time.perf_counter() - case_started,
                    "markdown_sha256": f"sha256:{sha256_file(target)}",
                    "markdown_characters": len(markdown),
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
        "input_count": len(images),
        "repeat_count": args.repeats,
        "model_load_seconds": model_load_seconds,
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
    raise SystemExit(main())
