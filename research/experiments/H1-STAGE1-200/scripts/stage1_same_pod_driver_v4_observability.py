#!/usr/bin/env python3
"""Reverify the v29 assembly, then run the sealed hard-200 cohort on the same Pod.

The driver never receives benchmark ground truth.  It first executes the exact
hash-bound v29 qualification producer.  Only a done/PASS qualification may
open the Stage-1 lane.  The GT-free source bundle is then downloaded from a
time-limited presigned URL, hash-verified, contract-checked, and evaluated on
the same GPU/runtime.  Only outputs and receipts are exposed by the evidence
server.
"""

from __future__ import annotations

import base64
import contextlib
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path("/opt/tavonel/stage1")
ASSEMBLY_ROOT = Path("/opt/tavonel/assembly-qualification")
MODEL_ROOT = Path("/opt/tavonel/models/OvisOCR2")
INPUT_ROOT = ROOT / "input"
RUNNER_ROOT = ROOT / "runner"
OUTPUT_ROOT = ROOT / "output"
BUNDLE = ROOT / "stage1-source-only.tar"
RESULT_ARCHIVE = ROOT / "stage1-results.tar.gz"
SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
MAX_BUNDLE_BYTES = 2 * 1024 * 1024 * 1024
EXPECTED_INPUT_COUNT = 200
EXPECTED_MEMBER_COUNT = 202
DENIED_QUALIFIER_ENV_EXACT = frozenset(
    {
        "TAVONEL_STAGE1_CONTROL_TOKEN",
        "TAVONEL_STAGE1_BUNDLE_URL",
        "TAVONEL_STAGE1_BUNDLE_SHA256",
        "TAVONEL_STAGE1_BUNDLE_BYTES",
    }
)
DENIED_QUALIFIER_ENV_PREFIXES = (
    "TAVONEL_STAGE1_DRIVER_",
    "TAVONEL_STAGE1_RUNNER_",
    "TAVONEL_INPUT_CONTRACT_",
)

_qualifier_process: subprocess.Popen[bytes] | None = None
_qualifier_stdout: Any = None
_qualifier_stderr: Any = None


def now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_json(name: str, value: Any) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def phase(name: str, **details: Any) -> None:
    write_json(
        "stage1-status.json",
        {
            "schema": "tavonel.stage1-same-pod-status.v1",
            "state": name,
            "at": now(),
            **details,
        },
    )


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"required environment value is missing: {name}")
    return value


def is_denied_qualifier_env(name: str) -> bool:
    if name in DENIED_QUALIFIER_ENV_EXACT or name.endswith("_GZ_B64"):
        return True
    return name.startswith(DENIED_QUALIFIER_ENV_PREFIXES)


def build_qualifier_child_env(parent: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if parent is None else parent
    return {key: value for key, value in source.items() if not is_denied_qualifier_env(key)}


def harvest_qualifier_evidence(process: subprocess.Popen[bytes] | None) -> dict[str, Any]:
    if _qualifier_stdout is not None:
        with contextlib.suppress(Exception):
            _qualifier_stdout.flush()
    if _qualifier_stderr is not None:
        with contextlib.suppress(Exception):
            _qualifier_stderr.flush()

    child_returncode = process.poll() if process is not None else None
    evidence: dict[str, Any] = {
        "child_pid": process.pid if process is not None else None,
        "child_returncode": child_returncode,
        "child_alive": process is not None and child_returncode is None,
        "vllm_server_log_present": False,
        "vllm_server_log_sha256": None,
        "vllm_server_log_bytes": 0,
        "vllm_server_log_tail": "",
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    source_log = ASSEMBLY_ROOT / "vllm-server.log"
    dest_log = ROOT / "vllm-server.log"
    if source_log.is_file():
        shutil.copy2(source_log, dest_log)
        raw = dest_log.read_bytes()
        evidence["vllm_server_log_present"] = True
        evidence["vllm_server_log_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        evidence["vllm_server_log_bytes"] = len(raw)
        evidence["vllm_server_log_tail"] = (
            raw[-16000:].replace(b"\x00", b"").decode("utf-8", errors="replace")
        )
    write_json(
        "vllm-server-log-tail.json",
        {
            "vllm_server_log_sha256": evidence["vllm_server_log_sha256"],
            "vllm_server_log_tail": evidence["vllm_server_log_tail"],
        },
    )
    write_json(
        "qualifier-child.json",
        {
            "child_pid": evidence["child_pid"],
            "child_returncode": evidence["child_returncode"],
            "child_alive": evidence["child_alive"],
        },
    )
    status_path = ASSEMBLY_ROOT / "status.json"
    if status_path.is_file():
        write_json(
            "qualifier-status-mirror.json",
            json.loads(status_path.read_text(encoding="utf-8")),
        )
    return evidence


def materialize_gzip_b64(env_name: str, sha_env_name: str, target: Path) -> str:
    encoded = required_env(env_name)
    expected = required_env(sha_env_name)
    if not SHA_RE.fullmatch(expected):
        raise RuntimeError(f"invalid expected digest for {target.name}")
    try:
        payload = gzip.decompress(base64.b64decode(encoded, validate=True))
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"compressed payload is invalid: {target.name}") from exc
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise RuntimeError(f"compressed payload hash mismatch: {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return actual


def wait_qualification(process: subprocess.Popen[bytes]) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + 20 * 60
    while time.monotonic() < deadline:
        error_path = ASSEMBLY_ROOT / "qualification-error.json"
        status_path = ASSEMBLY_ROOT / "status.json"
        if error_path.is_file():
            payload = json.loads(error_path.read_text(encoding="utf-8"))
            write_json("qualifier-error-mirror.json", payload)
            harvest_qualifier_evidence(process)
            error_type = str(payload.get("error_type", "unknown"))
            message = str(payload.get("message", ""))[:500]
            raise RuntimeError(
                f"same-Pod assembly qualification failed: {error_type}: {message}"
            )
        if status_path.is_file():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            write_json("qualifier-status-mirror.json", status)
            if status.get("state") == "done" and status.get("passed") is True:
                verification = json.loads(
                    (ASSEMBLY_ROOT / "assembly-verification.json").read_text(encoding="utf-8")
                )
                detail = json.loads(
                    (ASSEMBLY_ROOT / "qualification-detail.json").read_text(encoding="utf-8")
                )
                return verification, detail
            if status.get("state") == "error":
                harvest_qualifier_evidence(process)
                raise RuntimeError("same-Pod assembly qualification entered error state")
        if process.poll() is not None:
            harvest_qualifier_evidence(process)
            raise RuntimeError(
                f"assembly qualifier exited before PASS with code {process.returncode}"
            )
        time.sleep(2)
    harvest_qualifier_evidence(process)
    raise TimeoutError("same-Pod assembly qualification exceeded 20 minutes")


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    time.sleep(5)


def auth_handler() -> type[SimpleHTTPRequestHandler]:
    token = required_env("TAVONEL_STAGE1_CONTROL_TOKEN")

    class Handler(SimpleHTTPRequestHandler):
        def _authorized(self) -> bool:
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def do_GET(self) -> None:
            if not self._authorized():
                self.send_response(401)
                self.end_headers()
                return
            super().do_GET()

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def start_http_server(port: int, name: str) -> ThreadingHTTPServer:
    os.chdir(ROOT)
    deadline = time.monotonic() + 30
    while True:
        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), auth_handler())
            threading.Thread(
                target=server.serve_forever,
                name=name,
                daemon=True,
            ).start()
            return server
        except OSError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Stage-1 HTTP server could not bind port {port}") from exc
            time.sleep(1)


def start_evidence_server() -> ThreadingHTTPServer:
    return start_http_server(8001, "stage1-evidence-http")


def curl_download_presigned(url: str, destination: Path) -> None:
    if not url.startswith("https://"):
        raise RuntimeError("Stage-1 bundle URL must use HTTPS")
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError("curl is unavailable on Stage-1 Pod")
    partial = destination.with_suffix(destination.suffix + ".partial")
    config = (
        "\n".join(
            (
                "silent",
                "show-error",
                "location",
                "retry = 5",
                "retry-delay = 2",
                "max-time = 1800",
                f'url = "{url.replace(chr(34), r"\\\"")}"',
                f'output = "{partial.as_posix()}"',
            )
        )
        + "\n"
    )
    completed = subprocess.run(  # noqa: S603
        [curl, "--config", "-"],
        input=config.encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=31 * 60,
    )
    if completed.returncode != 0 or not partial.is_file():
        raise RuntimeError("presigned Stage-1 bundle download failed")
    partial.replace(destination)


def content_sha256(value: dict[str, Any]) -> str:
    content = {key: item for key, item in value.items() if key != "content_sha256"}
    return canonical_sha256(content)


def validate_member(member: tarfile.TarInfo) -> str:
    name = member.name.replace("\\", "/")
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError("Stage-1 archive contains an unsafe path")
    if member.issym() or member.islnk() or member.isdev():
        raise RuntimeError("Stage-1 archive contains a link/device member")
    lowered = name.lower()
    if "ground_truth" in lowered or "ground-truth" in lowered:
        raise RuntimeError("Stage-1 archive contains a GT-like path")
    return name


def validate_and_extract_bundle() -> tuple[dict[str, Any], dict[str, Any]]:
    expected_sha = required_env("TAVONEL_STAGE1_BUNDLE_SHA256")
    expected_bytes = int(required_env("TAVONEL_STAGE1_BUNDLE_BYTES"))
    if not SHA_RE.fullmatch(expected_sha):
        raise RuntimeError("Stage-1 bundle SHA is malformed")
    if not 1 <= expected_bytes <= MAX_BUNDLE_BYTES:
        raise RuntimeError("Stage-1 bundle size is outside the bounded range")
    if BUNDLE.stat().st_size != expected_bytes or sha256_file(BUNDLE) != expected_sha:
        raise RuntimeError("Stage-1 bundle size/hash verification failed")
    INPUT_ROOT.mkdir(parents=True, exist_ok=False)
    with tarfile.open(BUNDLE, "r") as archive:
        members = archive.getmembers()
        names = [validate_member(member) for member in members]
        if len(names) != EXPECTED_MEMBER_COUNT or len(set(names)) != len(names):
            raise RuntimeError("Stage-1 archive member cardinality is invalid")
        if names[0:2] != [
            "inference-input-manifest.json",
            "parent-inference-input-manifest.json",
        ]:
            raise RuntimeError("Stage-1 archive manifest ordering/identity drifted")
        if sum(1 for name in names if name.startswith("inputs/")) != EXPECTED_INPUT_COUNT:
            raise RuntimeError("Stage-1 archive does not contain exactly 200 source inputs")
        archive.extractall(INPUT_ROOT, filter="data")
    shard = json.loads((INPUT_ROOT / "inference-input-manifest.json").read_text(encoding="utf-8"))
    parent = json.loads(
        (INPUT_ROOT / "parent-inference-input-manifest.json").read_text(encoding="utf-8")
    )
    if shard.get("schema") != "folynta.public-core-inference-shard.v1":
        raise RuntimeError("Stage-1 shard schema drifted")
    if parent.get("schema") != "folynta.public-core-inference-inputs.v1":
        raise RuntimeError("Stage-1 parent schema drifted")
    if (
        shard.get("input_count") != EXPECTED_INPUT_COUNT
        or len(shard.get("inputs") or []) != EXPECTED_INPUT_COUNT
    ):
        raise RuntimeError("Stage-1 shard input count drifted")
    if (
        shard.get("ground_truth_mounted") is not False
        or parent.get("ground_truth_mounted") is not False
    ):
        raise RuntimeError("Stage-1 manifests are not GT-free")
    if shard.get("content_sha256") != content_sha256(shard):
        raise RuntimeError("Stage-1 shard content hash is invalid")
    if parent.get("content_sha256") != content_sha256(parent):
        raise RuntimeError("Stage-1 parent content hash is invalid")
    if shard.get("parent_input_manifest_sha256") != parent.get("content_sha256"):
        raise RuntimeError("Stage-1 shard/parent content binding is invalid")
    parent_by_case = {str(item.get("case_id")): item for item in parent.get("inputs", [])}
    seen_paths: set[str] = set()
    for item in shard["inputs"]:
        case_id = str(item.get("case_id", ""))
        if not case_id or parent_by_case.get(case_id) != item:
            raise RuntimeError("Stage-1 shard input differs from parent entry")
        relative = str(item.get("input_relative_path", ""))
        if not relative.startswith("inputs/") or relative in seen_paths:
            raise RuntimeError("Stage-1 input path is invalid or duplicated")
        seen_paths.add(relative)
        path = INPUT_ROOT / relative
        if not path.is_file() or sha256_file(path) != str(item.get("input_sha256", "")):
            raise RuntimeError("Stage-1 source input hash verification failed")
    return shard, parent


def run_stage1() -> tuple[dict[str, Any], int]:
    runner = RUNNER_ROOT / "ovisocr2_stage1_hard200.py"
    contract = RUNNER_ROOT / "input_contract.py"
    materialize_gzip_b64("TAVONEL_STAGE1_RUNNER_GZ_B64", "TAVONEL_STAGE1_RUNNER_SHA256", runner)
    materialize_gzip_b64("TAVONEL_INPUT_CONTRACT_GZ_B64", "TAVONEL_INPUT_CONTRACT_SHA256", contract)
    revision = required_env("TAVONEL_MODEL_REVISION")
    artifact_sha = required_env("TAVONEL_ARTIFACT_MANIFEST_SHA256")
    if not REVISION_RE.fullmatch(revision) or not SHA_RE.fullmatch(artifact_sha):
        raise RuntimeError("Stage-1 candidate identity is malformed")
    command = [
        sys.executable,
        str(runner),
        "--input-dir",
        str(INPUT_ROOT),
        "--output-dir",
        str(OUTPUT_ROOT),
        "--model-path",
        str(MODEL_ROOT),
        "--model-revision",
        revision,
        "--artifact-manifest-sha256",
        artifact_sha,
        "--repeats",
        "1",
        "--repeat-start-index",
        "1",
        "--limit",
        "0",
        "--evidence-class",
        "public-core-shard",
        "--expected-input-count",
        str(EXPECTED_INPUT_COUNT),
        "--input-manifest",
        str(INPUT_ROOT / "inference-input-manifest.json"),
        "--parent-input-manifest",
        str(INPUT_ROOT / "parent-inference-input-manifest.json"),
        "--batch-size",
        "2",
        "--gpu-memory-utilization",
        "0.80",
    ]
    stdout_path = ROOT / "stage1.stdout.log"
    stderr_path = ROOT / "stage1.stderr.log"
    started = time.perf_counter()
    with (
        stdout_path.open("w", encoding="utf-8", buffering=1) as out,
        stderr_path.open("w", encoding="utf-8", buffering=1) as err,
    ):
        completed = subprocess.run(  # noqa: S603
            command,
            stdout=out,
            stderr=err,
            check=False,
            timeout=90 * 60,
        )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(f"Stage-1 inference failed with exit code {completed.returncode}")
    summary_path = OUTPUT_ROOT / "run-summary.json"
    if not summary_path.is_file():
        raise RuntimeError("Stage-1 run-summary.json is missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        summary.get("ground_truth_mounted") is not False
        or int(summary.get("input_count", -1)) != EXPECTED_INPUT_COUNT
    ):
        raise RuntimeError("Stage-1 run summary violated GT/input-count contract")
    return summary, round(elapsed, 3)


def build_result_archive() -> tuple[str, int]:
    with tarfile.open(RESULT_ARCHIVE, "w:gz", compresslevel=6) as archive:
        archive.add(OUTPUT_ROOT, arcname="output", recursive=True)
        for name in (
            "stage1.stdout.log",
            "stage1.stderr.log",
            "stage1-receipt.json",
            "assembly-verification.json",
            "qualification-detail.json",
        ):
            path = ROOT / name
            if path.is_file():
                archive.add(path, arcname=name)
    with tarfile.open(RESULT_ARCHIVE, "r:gz") as archive:
        for member in archive.getmembers():
            name = validate_member(member)
            if name.startswith("input/") or "/inputs/" in f"/{name.lower()}/":
                raise RuntimeError("Stage-1 result archive contains source input material")
    return sha256_file(RESULT_ARCHIVE), RESULT_ARCHIVE.stat().st_size


def main() -> int:
    global _qualifier_process, _qualifier_stdout, _qualifier_stderr
    ROOT.mkdir(parents=True, exist_ok=True)
    start_http_server(8002, "stage1-bootstrap-heartbeat")
    phase("bootstrap_heartbeat")
    qualifier = ROOT / "assembly_qualification_http_v4.py"
    qualifier_sha = materialize_gzip_b64(
        "TAVONEL_QUALIFIER_GZ_B64",
        "TAVONEL_QUALIFIER_SHA256",
        qualifier,
    )
    phase("qualification", qualifier_sha256=qualifier_sha)
    qualifier_stdout_path = ROOT / "qualifier.stdout.log"
    qualifier_stderr_path = ROOT / "qualifier.stderr.log"
    with (
        qualifier_stdout_path.open("w", encoding="utf-8", errors="replace") as qualifier_stdout,
        qualifier_stderr_path.open("w", encoding="utf-8", errors="replace") as qualifier_stderr,
    ):
        _qualifier_stdout = qualifier_stdout
        _qualifier_stderr = qualifier_stderr
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, str(qualifier)],
            stdout=qualifier_stdout,
            stderr=qualifier_stderr,
            start_new_session=True,
            env=build_qualifier_child_env(),
        )
        _qualifier_process = process
        phase("qualification_child_started", child_pid=process.pid)
        verification, detail = wait_qualification(process)
        terminate_process_group(process)
        qualifier_stdout.flush()
        qualifier_stderr.flush()
    (ROOT / "assembly-verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (ROOT / "qualification-detail.json").write_text(
        json.dumps(detail, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(
        verification.get(key) is True
        for key in (
            "identity_verified",
            "security_patch_verified",
            "model_artifact_verified",
            "smoke_passed",
        )
    ):
        raise RuntimeError("same-Pod qualification evidence is not PASS")
    if detail.get("public_benchmark_inference_allowed") is not False:
        raise RuntimeError("qualification phase unexpectedly allowed public benchmark")

    start_evidence_server()
    phase("bundle_download")
    curl_download_presigned(required_env("TAVONEL_STAGE1_BUNDLE_URL"), BUNDLE)
    phase("bundle_verify")
    shard, parent = validate_and_extract_bundle()
    phase(
        "bundle_verified",
        input_count=EXPECTED_INPUT_COUNT,
        shard_content_sha256=shard["content_sha256"],
        parent_content_sha256=parent["content_sha256"],
    )
    BUNDLE.unlink(missing_ok=True)
    phase("inference", input_count=EXPECTED_INPUT_COUNT)
    summary, inference_seconds = run_stage1()
    runs = summary.get("runs") or []
    completed_count = sum(int(item.get("completed", 0)) for item in runs if isinstance(item, dict))
    failed_count = sum(int(item.get("failed", 0)) for item in runs if isinstance(item, dict))
    receipt = {
        "schema": "tavonel.stage1-hard200-same-pod.v1",
        "completed_at": now(),
        "input_count": EXPECTED_INPUT_COUNT,
        "completed": completed_count,
        "failed": failed_count,
        "ground_truth_mounted": False,
        "ground_truth_in_bundle": False,
        "assembly_id": verification["assembly_id"],
        "gpu_type": verification["gpu_type"],
        "cuda_version": verification["cuda_version"],
        "framework_version": verification["framework_version"],
        "model_revision": verification["model_revision"],
        "model_artifact_sha256": verification["model_artifact_sha256"],
        "security_version_after": verification["security_version_after"],
        "shard_content_sha256": shard["content_sha256"],
        "parent_content_sha256": parent["content_sha256"],
        "run_summary_sha256": sha256_file(OUTPUT_ROOT / "run-summary.json"),
        "inference_seconds": inference_seconds,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    write_json("stage1-receipt.json", receipt)
    result_sha, result_bytes = build_result_archive()
    phase(
        "done",
        passed=True,
        completed=completed_count,
        failed=failed_count,
        result_sha256=result_sha,
        result_bytes=result_bytes,
    )
    while True:
        time.sleep(60)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        evidence = harvest_qualifier_evidence(_qualifier_process)
        write_json(
            "stage1-error.json",
            {
                "schema": "tavonel.stage1-same-pod-error.v2",
                "at": now(),
                "error_type": type(exc).__name__,
                "message": str(exc)[:1000],
                "child_pid": evidence["child_pid"],
                "child_returncode": evidence["child_returncode"],
                "child_alive": evidence["child_alive"],
                "vllm_server_log_present": evidence["vllm_server_log_present"],
                "vllm_server_log_sha256": evidence["vllm_server_log_sha256"],
                "vllm_server_log_bytes": evidence["vllm_server_log_bytes"],
                "vllm_server_log_tail": evidence["vllm_server_log_tail"],
            },
        )
        phase("error", error_type=type(exc).__name__)
        while True:
            time.sleep(60)
