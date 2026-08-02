"""Run a ground-truth-isolated OvisOCR2 cohort on a GPU worker.

The implementation follows the vendor model-card inference contract while
keeping ground truth outside the worker. Every page is preserved as an
individual success or failure and every repeat emits evaluator-ready Markdown.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_TAG_BLOCK = re.compile(r'^\s*<img src="images/bbox_\d+_\d+_\d+_\d+\.jpg"\s*/>\s*$')
VENDOR_PROMPT = (
    "Extract all readable content from the image in natural human reading order and "
    "output the result as a single Markdown document. For charts or images, represent "
    'them using an HTML image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}'
    '.jpg" />, where left, top, right, bottom are bounding box coordinates scaled to '
    "[0, 1000). Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown.\nPreserve the original text "
    "without translation or paraphrasing."
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_truncated_repeats(
    text: str,
    *,
    min_text_len: int = 8_000,
    max_period: int = 200,
    min_period: int = 1,
    min_repeat_chars: int = 100,
    min_repeat_times: int = 5,
) -> str:
    """Apply the deterministic tail de-duplication published by the vendor."""

    length = len(text)
    if length < min_text_len:
        return text
    max_period = min(max_period, length - 1)
    for unit_len in range(min_period, max_period + 1):
        if text[length - 1] != text[length - 1 - unit_len]:
            continue
        match_len = 1
        index = length - 2
        while index >= unit_len and text[index] == text[index - unit_len]:
            match_len += 1
            index -= 1
        total_len = match_len + unit_len
        repeat_times, tail_len = divmod(total_len, unit_len)
        if repeat_times >= min_repeat_times and total_len >= min_repeat_chars:
            return text[: length - total_len + unit_len] + text[length - tail_len :]
    return text


def filter_visual_region_tags(text: str) -> str:
    """Match the model-card default used for evaluation Markdown."""

    return "\n\n".join(
        block for block in text.split("\n\n") if not IMAGE_TAG_BLOCK.match(block)
    ).strip()


def chunked(items: list[Path], size: int) -> Iterable[list[Path]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    for index in range(0, len(items), size):
        yield items[index : index + size]


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
    parser.add_argument("--candidate-id", default="ovisocr2-0.9b-vllm-0.22.1")
    parser.add_argument("--repeats", type=int, default=3, choices=(1, 3))
    parser.add_argument("--limit", type=int, default=18)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.8)
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

    # vLLM's library entrypoint defaults to fork on Linux. CUDA cannot be
    # re-initialized in that child after model inspection, so use the
    # documented compatible method before importing vLLM.
    os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
    # The worker is launched from an explicitly selected virtual-environment
    # interpreter rather than an activated shell.  Preserve that interpreter's
    # executable tools (notably FlashInfer's JIT `ninja`) in spawned workers.
    # Do not resolve the virtual-environment Python symlink: resolving it would
    # point back to `/usr/bin` and drop the venv-installed tool directory.
    interpreter_bin = str(Path(sys.executable).parent)
    os.environ["PATH"] = interpreter_bin + os.pathsep + os.environ.get("PATH", "")

    import torch
    from PIL import Image
    from vllm import LLM, SamplingParams

    load_started = time.perf_counter()
    model = LLM(
        model=args.model_path,
        tensor_parallel_size=1,
        gpu_memory_utilization=args.gpu_memory_utilization,
        gdn_prefill_backend="triton",
        trust_remote_code=True,
    )
    model_load_seconds = time.perf_counter() - load_started
    prompt = model.get_tokenizer().apply_chat_template(
        [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": VENDOR_PROMPT}]}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    sampling = SamplingParams(max_tokens=16_384, temperature=0.0)

    started_at = time.time()
    runs: list[dict[str, Any]] = []
    for repeat_index in range(1, args.repeats + 1):
        markdown_root = args.output_dir / f"markdown-repeat-{repeat_index}"
        markdown_root.mkdir()
        repeat_started = time.perf_counter()
        cases: list[dict[str, Any]] = []
        for batch in chunked(images, args.batch_size):
            opened = [Image.open(path).convert("RGB") for path in batch]
            inputs = [
                {
                    "prompt": prompt,
                    "multi_modal_data": {"image": image},
                    "mm_processor_kwargs": {
                        "images_kwargs": {
                            "min_pixels": 448 * 448,
                            "max_pixels": 2_880 * 2_880,
                        }
                    },
                }
                for image in opened
            ]
            batch_started = time.perf_counter()
            try:
                outputs = model.generate(inputs, sampling)
                if len(outputs) != len(batch):
                    raise RuntimeError(
                        "output cardinality mismatch: "
                        f"expected {len(batch)}, received {len(outputs)}"
                    )
                for path, output in zip(batch, outputs, strict=True):
                    raw_text = output.outputs[0].text.strip()
                    markdown = filter_visual_region_tags(clean_truncated_repeats(raw_text))
                    target = markdown_root / f"{path.stem}.md"
                    target.write_text(markdown + ("\n" if markdown else ""), encoding="utf-8")
                    cases.append(
                        {
                            "case_id": path.stem,
                            "source_sha256": f"sha256:{sha256_file(path)}",
                            "status": "completed" if markdown else "failed",
                            "markdown_sha256": f"sha256:{sha256_file(target)}",
                            "markdown_characters": len(markdown),
                            "batch_latency_seconds": time.perf_counter() - batch_started,
                        }
                    )
            except Exception as exc:  # preserve failure instead of inventing output
                failure = f"{type(exc).__name__}: {exc}"
                for path in batch:
                    target = markdown_root / f"{path.stem}.md"
                    target.write_text("", encoding="utf-8")
                    cases.append(
                        {
                            "case_id": path.stem,
                            "source_sha256": f"sha256:{sha256_file(path)}",
                            "status": "failed",
                            "failure": failure,
                            "markdown_sha256": f"sha256:{sha256_file(target)}",
                            "markdown_characters": 0,
                            "batch_latency_seconds": time.perf_counter() - batch_started,
                        }
                    )
            finally:
                for image in opened:
                    image.close()
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
        "candidate_id": args.candidate_id,
        "model_path": args.model_path,
        "model_revision": args.model_revision,
        "artifact_manifest_sha256": args.artifact_manifest_sha256,
        "ground_truth_mounted": False,
        "input_count": len(images),
        "repeat_count": args.repeats,
        "batch_size": args.batch_size,
        "model_load_seconds": model_load_seconds,
        "started_at_unix": started_at,
        "completed_at_unix": time.time(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "vllm": importlib.metadata.version("vllm"),
            "torch": importlib.metadata.version("torch"),
            "torch_cuda_build": torch.version.cuda,
            "pillow": importlib.metadata.version("pillow"),
            "gpu": gpu_identity(),
        },
        "inference_contract": {
            "prompt_sha256": hashlib.sha256(VENDOR_PROMPT.encode("utf-8")).hexdigest(),
            "temperature": 0.0,
            "max_tokens": 16_384,
            "min_pixels": 448 * 448,
            "max_pixels": 2_880 * 2_880,
            "filter_visual_region_tags": True,
            "gdn_prefill_backend": "triton",
            "worker_multiprocessing_method": os.environ[
                "VLLM_WORKER_MULTIPROC_METHOD"
            ],
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
