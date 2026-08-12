"""Run a ground-truth-isolated MinerU Stage-2 parser cohort on a GPU Pod.

The script invokes the pinned vendor CLI once per repeat, preserves the complete
vendor output, and emits a flat Markdown directory for OmniDocBench evaluation.
It records failures instead of converting them into empty successful pages.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from input_contract import adaptive_repeat_indices, select_inference_inputs

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


def _decode_process_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _posix_descendant_pids(root_pid: int) -> tuple[int, ...]:
    """Snapshot descendants before their parent can die and reparent them to PID 1."""
    children: dict[int, list[int]] = {}
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return ()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            fields = stat[stat.rfind(")") + 2 :].split()
            parent_pid = int(fields[1])
            pid = int(entry.name)
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(parent_pid, []).append(pid)
    descendants: list[int] = []
    pending = list(children.get(root_pid, ()))
    while pending:
        pid = pending.pop()
        descendants.append(pid)
        pending.extend(children.get(pid, ()))
    return tuple(descendants)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process_tree(process: subprocess.Popen[str], grace_seconds: float = 5.0) -> None:
    """Terminate the complete inference process tree, not only the MinerU CLI parent."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        descendants = _posix_descendant_pids(process.pid)
        for pid in reversed(descendants):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None and not any(
                _pid_exists(pid) for pid in descendants
            ):
                return
            time.sleep(0.05)
        for pid in reversed(descendants):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    elif os.name == "nt":
        taskkill = shutil.which("taskkill.exe")
        if taskkill is None:
            process.kill()
        else:
            subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                text=True,
            )
    else:
        process.kill()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace_seconds)


def _run_command_with_timeout(
    command: list[str], timeout_seconds: int
) -> tuple[int, str, str, bool]:
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(command, **popen_kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        return (
            124,
            _decode_process_output(stdout) or _decode_process_output(exc.stdout),
            _decode_process_output(stderr) or _decode_process_output(exc.stderr),
            True,
        )


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
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Run bounded source-only sub-batches; zero preserves one CLI call per repeat.",
    )
    parser.add_argument(
        "--resume-interrupted",
        action="store_true",
        help=(
            "Resume a bounded run after infrastructure interruption, reusing only "
            "case outputs that already contain non-empty Markdown."
        ),
    )
    return parser.parse_args()


def find_markdown(root: Path, stem: str) -> Path | None:
    exact = sorted(path for path in root.rglob("*.md") if path.stem == stem)
    if exact:
        return exact[0]
    candidates = sorted(path for path in root.rglob("*.md") if stem in path.stem)
    return candidates[0] if candidates else None


def _chunks(images: tuple[Path, ...], batch_size: int) -> tuple[tuple[Path, ...], ...]:
    if batch_size < 0:
        raise ValueError("--batch-size cannot be negative")
    if batch_size == 0 or batch_size >= len(images):
        return (images,)
    return tuple(
        tuple(images[index : index + batch_size])
        for index in range(0, len(images), batch_size)
    )


def _stage_batch_input(root: Path, images: tuple[Path, ...]) -> Path:
    root.mkdir(parents=True, exist_ok=False)
    for image in images:
        source = image.resolve()
        target = root / image.name
        try:
            target.hardlink_to(source)
        except OSError:
            shutil.copy2(source, target)
    return root


def _validate_frozen_input(root: Path, images: tuple[Path, ...]) -> None:
    expected = {image.name: sha256_file(image) for image in images}
    observed = {
        path.name: sha256_file(path)
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGES
    }
    if observed != expected:
        raise ValueError("interrupted run frozen input does not match selected inputs")


def _case_has_reusable_markdown(repeat_root: Path, image: Path) -> bool:
    markdown = find_markdown(repeat_root / image.stem, image.stem)
    return markdown is not None and markdown.stat().st_size > 0


def _archive_interrupted_path(path: Path, archive_root: Path) -> None:
    if not path.exists():
        return
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / path.name
    suffix = 1
    while target.exists():
        target = archive_root / f"{path.name}.{suffix}"
        suffix += 1
    shutil.move(str(path), target)


def _merge_batch_cases(
    *, batch_output: Path, repeat_root: Path, images: tuple[Path, ...]
) -> None:
    repeat_root.mkdir(parents=True, exist_ok=True)
    for image in images:
        exact = batch_output / image.stem
        candidates = [exact] if exact.is_dir() else sorted(
            path for path in batch_output.rglob(image.stem) if path.is_dir()
        )
        if len(candidates) > 1:
            raise ValueError(f"MinerU batch emitted duplicate case directories: {image.stem}")
        if not candidates:
            continue
        target = repeat_root / image.stem
        if target.exists():
            raise ValueError(f"MinerU batch attempted to overwrite a case: {image.stem}")
        shutil.move(str(candidates[0]), target)


def main() -> int:
    args = parse_args()
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be positive")
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
    try:
        batches = _chunks(images, args.batch_size)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.resume_interrupted:
        if args.batch_size < 1:
            raise SystemExit("--resume-interrupted requires a positive --batch-size")
        if not args.output_dir.is_dir():
            raise SystemExit("interrupted output directory does not exist")
        if (args.output_dir / "run-summary.json").exists():
            raise SystemExit("completed output cannot be resumed")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=False)
    staged_input = args.output_dir / "frozen-input"
    if args.resume_interrupted:
        try:
            _validate_frozen_input(staged_input, images)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
    else:
        staged_input.mkdir()
        for image in images:
            shutil.copy2(image, staged_input / image.name)

    runs: list[dict[str, Any]] = []
    started_at = time.time()
    for repeat_index in repeat_indices:
        repeat_root = args.output_dir / f"repeat-{repeat_index}"
        markdown_root = args.output_dir / f"markdown-repeat-{repeat_index}"
        markdown_root.mkdir(exist_ok=args.resume_interrupted)
        repeat_started = time.perf_counter()
        batch_records: list[dict[str, Any]] = []
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        for batch_index, batch_images in enumerate(batches):
            bounded = len(batches) > 1
            reused = args.resume_interrupted and all(
                _case_has_reusable_markdown(repeat_root, image)
                for image in batch_images
            )
            if reused:
                batch_records.append(
                    {
                        "batch_index": batch_index,
                        "input_count": len(batch_images),
                        "return_code": 0,
                        "timed_out": False,
                        "latency_seconds": 0.0,
                        "case_ids": [image.stem for image in batch_images],
                        "resumed_reused": True,
                    }
                )
                stdout_parts.append(
                    f"[batch-{batch_index:04d}]\nreused-after-infrastructure-interruption"
                )
                stderr_parts.append(f"[batch-{batch_index:04d}]\n")
                continue
            if bounded:
                batch_input = (
                    args.output_dir
                    / f"batch-input-repeat-{repeat_index}"
                    / f"batch-{batch_index:04d}"
                )
                if batch_input.exists():
                    try:
                        _validate_frozen_input(batch_input, batch_images)
                    except ValueError as exc:
                        raise SystemExit(str(exc)) from exc
                else:
                    batch_input = _stage_batch_input(batch_input, batch_images)
                batch_output = (
                    args.output_dir
                    / f"batch-output-repeat-{repeat_index}"
                    / f"batch-{batch_index:04d}"
                )
                if args.resume_interrupted:
                    _archive_interrupted_path(
                        batch_output,
                        args.output_dir
                        / f"interrupted-batch-output-repeat-{repeat_index}",
                    )
                    for image in batch_images:
                        _archive_interrupted_path(
                            repeat_root / image.stem,
                            args.output_dir
                            / f"interrupted-repeat-{repeat_index}",
                        )
            else:
                batch_input = staged_input
                batch_output = repeat_root
            command = [
                str(args.mineru_cli),
                "--path",
                str(batch_input),
                "--output",
                str(batch_output),
                "--backend",
                args.backend,
                "--method",
                args.method,
            ]
            if args.backend.startswith("hybrid"):
                command.extend(["--effort", args.effort])
            batch_started = time.perf_counter()
            (
                batch_return_code,
                batch_stdout,
                batch_stderr,
                batch_timed_out,
            ) = _run_command_with_timeout(command, args.timeout_seconds)
            if bounded and batch_output.exists():
                _merge_batch_cases(
                    batch_output=batch_output,
                    repeat_root=repeat_root,
                    images=batch_images,
                )
            stdout_parts.append(f"[batch-{batch_index:04d}]\n{batch_stdout}")
            stderr_parts.append(f"[batch-{batch_index:04d}]\n{batch_stderr}")
            batch_records.append(
                {
                    "batch_index": batch_index,
                    "input_count": len(batch_images),
                    "return_code": batch_return_code,
                    "timed_out": batch_timed_out,
                    "latency_seconds": time.perf_counter() - batch_started,
                    "case_ids": [image.stem for image in batch_images],
                    "resumed_reused": False,
                }
            )
        timed_out = any(record["timed_out"] for record in batch_records)
        return_code = next(
            (
                int(record["return_code"])
                for record in batch_records
                if record["return_code"] not in {0, None}
            ),
            0,
        )
        stdout = "\n".join(stdout_parts)
        stderr = "\n".join(stderr_parts)
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
                "batch_size": args.batch_size,
                "batch_count": len(batch_records),
                "batches": batch_records,
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
        "evidence_class": args.evidence_class,
        "input_inventory_count": len(all_images),
        "input_count": len(images),
        "complete_input_coverage": selection.complete_input_coverage,
        "input_manifest_sha256": selection.input_manifest_sha256,
        "benchmark_id": selection.benchmark_id,
        "dataset_revision": selection.dataset_revision,
        "repeat_count": len(repeat_indices),
        "repeat_start_index": repeat_indices[0],
        "resumed_interrupted": args.resume_interrupted,
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
