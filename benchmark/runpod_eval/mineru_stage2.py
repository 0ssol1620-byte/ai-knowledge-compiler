"""Run a ground-truth-isolated MinerU Stage-2 parser cohort on a GPU Pod.

The script invokes the pinned vendor CLI once per repeat, preserves the complete
vendor output, and emits a flat Markdown directory for OmniDocBench evaluation.
It records failures instead of converting them into empty successful pages.
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


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    parser.add_argument("--mineru-cli", type=Path, required=True)
    parser.add_argument("--repository-revision", required=True)
    parser.add_argument("--artifact-manifest-sha256", required=True)
    parser.add_argument("--backend", default="pipeline")
    parser.add_argument("--method", default="ocr")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--repeats", type=int, default=3, choices=(1, 3))
    parser.add_argument("--limit", type=int, default=18)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    return parser.parse_args()


def find_markdown(root: Path, stem: str) -> Path | None:
    exact = sorted(path for path in root.rglob("*.md") if path.stem == stem)
    if exact:
        return exact[0]
    candidates = sorted(path for path in root.rglob("*.md") if stem in path.stem)
    return candidates[0] if candidates else None


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
    staged_input = args.output_dir / "frozen-input"
    staged_input.mkdir()
    for image in images:
        shutil.copy2(image, staged_input / image.name)

    runs: list[dict[str, Any]] = []
    started_at = time.time()
    for repeat_index in range(1, args.repeats + 1):
        repeat_root = args.output_dir / f"repeat-{repeat_index}"
        markdown_root = args.output_dir / f"markdown-repeat-{repeat_index}"
        markdown_root.mkdir()
        command = [
            str(args.mineru_cli),
            "--path",
            str(staged_input),
            "--output",
            str(repeat_root),
            "--backend",
            args.backend,
            "--method",
            args.method,
        ]
        if args.backend.startswith("hybrid"):
            command.extend(["--effort", args.effort])
        repeat_started = time.perf_counter()
        timed_out = False
        return_code: int | None = None
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout_seconds,
                check=False,
            )
            return_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        latency_seconds = time.perf_counter() - repeat_started
        (args.output_dir / f"repeat-{repeat_index}.stdout.log").write_text(
            stdout, encoding="utf-8"
        )
        (args.output_dir / f"repeat-{repeat_index}.stderr.log").write_text(
            stderr, encoding="utf-8"
        )

        cases: list[dict[str, Any]] = []
        for image in images:
            markdown = find_markdown(repeat_root, image.stem)
            status = (
                "completed"
                if markdown is not None and markdown.stat().st_size > 0
                else "failed"
            )
            target = markdown_root / f"{image.stem}.md"
            if markdown is not None:
                shutil.copy2(markdown, target)
            else:
                target.write_text("", encoding="utf-8")
            cases.append(
                {
                    "case_id": image.stem,
                    "source_sha256": f"sha256:{sha256_file(image)}",
                    "status": status,
                    "markdown_sha256": f"sha256:{sha256_file(target)}",
                    "markdown_characters": len(target.read_text(encoding="utf-8")),
                }
            )
        runs.append(
            {
                "repeat_index": repeat_index,
                "return_code": return_code,
                "timed_out": timed_out,
                "latency_seconds": latency_seconds,
                "completed": sum(case["status"] == "completed" for case in cases),
                "failed": sum(case["status"] == "failed" for case in cases),
                "cases": cases,
            }
        )
        print(canonical_json({"event": "repeat_completed", **runs[-1]}), flush=True)

    if args.backend == "pipeline":
        candidate_id = "mineru-3.4.4-pipeline"
    elif args.backend == "vlm-engine":
        candidate_id = "mineru-3.4.4-vlm"
    else:
        candidate_id = f"mineru-3.4.4-hybrid-{args.effort}"
    summary = {
        "schema_version": "1.0.0",
        "candidate_id": candidate_id,
        "repository_revision": args.repository_revision,
        "artifact_manifest_sha256": args.artifact_manifest_sha256,
        "backend": args.backend,
        "method": args.method,
        "effort": args.effort,
        "ground_truth_mounted": False,
        "input_count": len(images),
        "repeat_count": args.repeats,
        "started_at_unix": started_at,
        "completed_at_unix": time.time(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "mineru": importlib.metadata.version("mineru"),
            "torch": importlib.metadata.version("torch"),
            "gpu": gpu_identity(),
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
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
