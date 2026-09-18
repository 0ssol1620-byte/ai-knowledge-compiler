"""Materialize and freeze the exact model and request inputs for execution.

Model artifacts are deliberately stored outside Git.  The generated manifests
contain only paths, sizes and digests and are safe to review and commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .execution_input_admission import _request_id
from .preflight_mixed_holdout import digest, load_json, load_jsonl

MODEL_KEYS = ("mineru_vlm", "ovisocr2", "paddleocr_vl_1_6")
CAMPAIGN_ID = "TAVONEL-ROUTER-MIXED-SOURCE-HOLDOUT-20260910-V1"
CHUNK_BYTES = 8 * 1024 * 1024


class PreparationError(ValueError):
    """A frozen execution input could not be materialized exactly."""


@dataclass(frozen=True, slots=True)
class DownloadJob:
    repository: str
    revision: str
    remote_relative: str
    target: Path
    expected_sha: str
    expected_size: int


def _streaming_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _atomic_copy(source: Path, target: Path, expected: str) -> None:
    if target.is_file() and _streaming_digest(target) == expected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with source.open("rb") as reader, temporary.open("xb") as writer:
        shutil.copyfileobj(reader, writer, CHUNK_BYTES)
        writer.flush()
        os.fsync(writer.fileno())
    if _streaming_digest(temporary) != expected:
        temporary.unlink(missing_ok=True)
        raise PreparationError(f"COPY_DIGEST_MISMATCH:{target.as_posix()}")
    os.replace(temporary, target)


def _atomic_bytes(payload: bytes, target: Path, expected: str) -> None:
    if digest(payload) != expected:
        raise PreparationError(f"GENERATED_DIGEST_MISMATCH:{target.as_posix()}")
    if target.is_file() and _streaming_digest(target) == expected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _download_one(
    *,
    repository: str,
    revision: str,
    remote_relative: str,
    target: Path,
    expected_sha: str,
    expected_size: int,
) -> None:
    if target.is_file():
        if target.stat().st_size == expected_size and _streaming_digest(target) == expected_sha:
            return
        raise PreparationError(f"EXISTING_ARTIFACT_MISMATCH:{target.as_posix()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    offset = temporary.stat().st_size if temporary.is_file() else 0
    if offset > expected_size:
        temporary.unlink()
        offset = 0
    url = (
        "https://huggingface.co/"
        + quote(repository, safe="/")
        + "/resolve/"
        + quote(revision, safe="")
        + "/"
        + quote(remote_relative, safe="/")
        + "?download=true"
    )
    headers = {"User-Agent": "TAVONEL-Router-Holdout/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=180) as response:  # noqa: S310 - fixed official host
        status = int(response.status)
        if status == 200 and offset:
            temporary.unlink()
            offset = 0
        elif status not in ({200} if not offset else {206}):
            raise PreparationError(f"MODEL_DOWNLOAD_HTTP_{status}:{remote_relative}")
        mode = "ab" if offset else "xb"
        with temporary.open(mode) as handle:
            while chunk := response.read(CHUNK_BYTES):
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    if temporary.stat().st_size != expected_size:
        raise PreparationError(f"MODEL_DOWNLOAD_SIZE_MISMATCH:{remote_relative}")
    if _streaming_digest(temporary) != expected_sha:
        raise PreparationError(f"MODEL_DOWNLOAD_DIGEST_MISMATCH:{remote_relative}")
    os.replace(temporary, target)


def materialize_models(
    *,
    arena_root: Path,
    model_root: Path,
    snapshot_binding: Mapping[str, Any],
    download_workers: int,
) -> list[dict[str, object]]:
    snapshots = snapshot_binding.get("models")
    if not isinstance(snapshots, Mapping) or set(snapshots) != set(MODEL_KEYS):
        raise PreparationError("MODEL_SNAPSHOT_PORTFOLIO_INVALID")
    model_rows: list[dict[str, object]] = []
    download_jobs: list[DownloadJob] = []
    for model_key in MODEL_KEYS:
        snapshot = snapshots[model_key]
        if not isinstance(snapshot, Mapping):
            raise PreparationError(f"{model_key}:MODEL_SNAPSHOT_INVALID")
        revision = snapshot.get("revision")
        repository = snapshot.get("repository")
        files = snapshot.get("files")
        if (
            not isinstance(revision, str)
            or not isinstance(repository, str)
            or not isinstance(files, list)
        ):
            raise PreparationError(f"{model_key}:MODEL_SNAPSHOT_INVALID")
        runtime_source = arena_root / "runtimes" / model_key / "runtime.json"
        bundle_source = arena_root / "bundles" / model_key / "arena-bundle.tar.gz"
        runtime = load_json(runtime_source)
        inference_bytes = json.dumps(
            runtime.get("inference_config"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        runtime_relative = f"{model_key}/runtime.json"
        bundle_relative = f"{model_key}/arena-bundle.tar.gz"
        inference_relative = f"{model_key}/inference_config.json"
        identity = {
            "model_revision": revision,
            "runtime_sha256": _streaming_digest(runtime_source),
            "bundle_sha256": _streaming_digest(bundle_source),
            "inference_config_sha256": digest(inference_bytes),
        }
        _atomic_copy(runtime_source, model_root / runtime_relative, identity["runtime_sha256"])
        _atomic_copy(bundle_source, model_root / bundle_relative, identity["bundle_sha256"])
        _atomic_bytes(
            inference_bytes,
            model_root / inference_relative,
            identity["inference_config_sha256"],
        )
        for file_row in files:
            if not isinstance(file_row, Mapping):
                raise PreparationError(f"{model_key}:SNAPSHOT_FILE_INVALID")
            relative = file_row.get("relative_path")
            size = file_row.get("size_bytes")
            sha = file_row.get("sha256")
            if (
                not isinstance(relative, str)
                or not relative.startswith(f"{model_key}/weights/")
                or not isinstance(size, int)
                or not isinstance(sha, str)
            ):
                raise PreparationError(f"{model_key}:SNAPSHOT_FILE_INVALID")
            remote_relative = relative.removeprefix(f"{model_key}/weights/")
            target = model_root / relative
            if remote_relative == "arena-weights-revision.txt":
                _atomic_bytes(revision.encode("utf-8"), target, sha)
            else:
                download_jobs.append(
                    DownloadJob(
                        repository=repository,
                        revision=revision,
                        remote_relative=remote_relative,
                        target=target,
                        expected_sha=sha,
                        expected_size=size,
                    )
                )
        model_rows.append(
            {
                "model_key": model_key,
                "model_revision": revision,
                "runtime_sha256": identity["runtime_sha256"],
                "runtime_relative_path": runtime_relative,
                "bundle_sha256": identity["bundle_sha256"],
                "bundle_relative_path": bundle_relative,
                "inference_config_sha256": identity["inference_config_sha256"],
                "inference_config_relative_path": inference_relative,
                "weight_files": files,
            }
        )
    with ThreadPoolExecutor(max_workers=download_workers) as pool:
        futures = [
            pool.submit(
                _download_one,
                repository=job.repository,
                revision=job.revision,
                remote_relative=job.remote_relative,
                target=job.target,
                expected_sha=job.expected_sha,
                expected_size=job.expected_size,
            )
            for job in download_jobs
        ]
        for future in as_completed(futures):
            future.result()
    return model_rows


def build_requests(
    *,
    source_rows: Sequence[Mapping[str, Any]],
    render_rows: Sequence[Mapping[str, Any]],
    model_rows: Sequence[Mapping[str, Any]],
    router_policy_sha256: str,
    model_root: Path,
) -> list[dict[str, object]]:
    source_by_id = {str(row["unit_id"]): row for row in source_rows}
    requests: list[dict[str, object]] = []
    for render in sorted(render_rows, key=lambda row: str(row["unit_id"])):
        unit_id = str(render["unit_id"])
        source = source_by_id[unit_id]
        for model in sorted(model_rows, key=lambda row: str(row["model_key"])):
            model_key = str(model["model_key"])
            runtime = load_json(model_root / str(model["runtime_relative_path"]))
            render_sha = str(render["render_sha256"])
            requests.append(
                {
                    "request_id": _request_id(unit_id, model_key, render_sha),
                    "unit_id": unit_id,
                    "model_key": model_key,
                    "source_sha256": source["source_sha256"],
                    "target_locator": source["target_locator"],
                    "render_sha256": render_sha,
                    "router_policy_sha256": router_policy_sha256,
                    "runtime_sha256": model["runtime_sha256"],
                    "bundle_sha256": model["bundle_sha256"],
                    "inference_config_sha256": model["inference_config_sha256"],
                    "base_image": runtime["base_image"],
                }
            )
    return requests


def _write_json(path: Path, value: object) -> None:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(payload) if not path.exists() else None
    if path.read_bytes() != payload:
        raise PreparationError(f"FROZEN_OUTPUT_ALREADY_DIFFERS:{path.name}")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
        for row in rows
    ).encode("utf-8")
    path.write_bytes(payload) if not path.exists() else None
    if path.read_bytes() != payload:
        raise PreparationError(f"FROZEN_OUTPUT_ALREADY_DIFFERS:{path.name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--arena-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--download-workers", type=int, default=3)
    args = parser.parse_args(argv)
    package = args.package_root
    model_rows = materialize_models(
        arena_root=args.arena_root,
        model_root=args.model_root,
        snapshot_binding=load_json(package / "MODEL_SNAPSHOT_BINDING.json"),
        download_workers=args.download_workers,
    )
    binding = load_json(package / "RUNTIME_BINDING.json")
    requests = build_requests(
        source_rows=load_jsonl(package / "SELECTED_SOURCE_MANIFEST.jsonl"),
        render_rows=load_jsonl(package / "RENDER_MANIFEST.jsonl"),
        model_rows=model_rows,
        router_policy_sha256=str(binding["router_policy_sha256"]),
        model_root=args.model_root,
    )
    budget = load_json(package / "MIXED_SOURCE_HOLDOUT_PROTOCOL.json")["execution_budget"]
    limits = {
        "schema": "tavonel.router_execution_limits.v1",
        "state": "FROZEN_BEFORE_EXECUTION",
        "campaign_id": CAMPAIGN_ID,
        "maximum_new_gpu_spend_usd": budget["maximum_new_gpu_spend_usd"],
        "maximum_model_unit_calls": len(requests),
        "maximum_parallel_pods": budget["maximum_parallel_pods"],
    }
    _write_jsonl(package / "MODEL_ARTIFACT_MANIFEST.jsonl", model_rows)
    _write_jsonl(package / "REQUEST_MANIFEST.jsonl", requests)
    _write_json(package / "EXECUTION_LIMITS.json", limits)
    print(json.dumps({"models": len(model_rows), "requests": len(requests)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
