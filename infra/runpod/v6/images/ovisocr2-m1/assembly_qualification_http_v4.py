#!/usr/bin/env python3
"""Verify a TAVONEL Ovis runtime assembled on an immutable public vLLM base."""

# ruff: noqa: S310, S603, S607, E501

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from typing import Any

ROOT = Path("/opt/tavonel/assembly-qualification")
MODEL_ROOT = Path("/opt/tavonel/models/OvisOCR2")
BASE_IMAGE_RE = re.compile(r"^vllm/vllm-openai@sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
TOKENS = ("TAVONEL", "2026-08-16", "42.50", "USD", "MUST")
EXPECTED_VERSIONS = {
    "vllm": "0.22.1+cu129",
    "huggingface-hub": "1.17.0",
    "pillow": "12.2.0",
    "transformers": "5.10.2",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_json(name: str, value: Any) -> None:
    (ROOT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def phase(name: str, **details: Any) -> None:
    write_json(
        "status.json",
        {
            "schema": "tavonel.assembly-qualification-status.v1",
            "state": name,
            "at": datetime.now(UTC).isoformat(),
            **details,
        },
    )


def _handler() -> type[SimpleHTTPRequestHandler]:
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    return QuietHandler


def serve() -> None:
    os.chdir(ROOT)
    ThreadingHTTPServer(("0.0.0.0", 8001), _handler()).serve_forever()


def decode_receipt(env_name: str) -> dict[str, Any]:
    encoded = os.environ.get(env_name, "")
    if not encoded:
        raise RuntimeError(f"{env_name} is missing")
    try:
        payload = base64.b64decode(encoded, validate=True)
        value = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{env_name} is malformed") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{env_name} is not a JSON object")
    return value


def download_bytes(url: str, *, timeout: int = 120) -> bytes:
    if not url.startswith(("https://security.ubuntu.com/ubuntu/", "https://archive.ubuntu.com/ubuntu/")):
        raise RuntimeError("security package URL escaped the Ubuntu allowlist")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "tavonel-verified-assembly/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def installed_version(package: str) -> str:
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Version}", package],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def install_security_patch(receipt: dict[str, Any]) -> tuple[str, str, str]:
    phase("security_patch")
    if receipt.get("schema") != "tavonel.linux-libc-dev-remediation-source.v1":
        raise RuntimeError("security package receipt schema drifted")
    if receipt.get("inrelease_packages_hash_match") is not True:
        raise RuntimeError("security package receipt is not index-bound")
    package_sha = str(receipt.get("package_sha256", ""))
    version_expected = str(receipt.get("selected_version", ""))
    size_expected = int(receipt.get("package_size", -1))
    filename = str(receipt.get("package_filename", ""))
    suite = str(receipt.get("selected_suite", ""))
    if not SHA_RE.fullmatch(package_sha) or version_expected != "5.15.0-187.197":
        raise RuntimeError("security package identity drifted")
    if size_expected != 1_361_444 or not filename.startswith("pool/"):
        raise RuntimeError("security package source metadata drifted")
    base = (
        "https://security.ubuntu.com/ubuntu"
        if suite == "jammy-security"
        else "https://archive.ubuntu.com/ubuntu"
    )
    if suite not in {"jammy-security", "jammy-updates"}:
        raise RuntimeError("security package suite drifted")
    url = f"{base}/{filename}"
    before = installed_version("linux-libc-dev")
    payload = download_bytes(url)
    if len(payload) != size_expected or sha256_bytes(payload) != package_sha:
        raise RuntimeError("downloaded security package failed size/hash verification")
    deb = ROOT / "linux-libc-dev-fixed.deb"
    deb.write_bytes(payload)
    result = subprocess.run(
        ["dpkg", "-i", str(deb)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError("linux-libc-dev fixed package installation failed")
    after = installed_version("linux-libc-dev")
    if after != version_expected:
        raise RuntimeError("linux-libc-dev installed version does not equal the fixed version")
    return before, after, package_sha


def verify_model_snapshot(receipt: dict[str, Any]) -> tuple[str, str, float]:
    from huggingface_hub import snapshot_download

    phase("model_download")
    if receipt.get("schema") != "tavonel.ovis-model-snapshot.v1":
        raise RuntimeError("model snapshot receipt schema drifted")
    repository = str(receipt.get("repository", ""))
    revision = str(receipt.get("resolved_revision", ""))
    files = receipt.get("files")
    if repository != "ATH-MaaS/OvisOCR2" or not REVISION_RE.fullmatch(revision):
        raise RuntimeError("model repository/revision drifted")
    if not isinstance(files, list) or len(files) != int(receipt.get("file_count", -1)):
        raise RuntimeError("model snapshot receipt file coverage is invalid")
    allow_patterns: list[str] = []
    expected: dict[str, tuple[int, str]] = {}
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError("model snapshot receipt contains an invalid file record")
        relative = str(item.get("path", ""))
        digest = "sha256:" + str(item.get("sha256", "")).removeprefix("sha256:")
        size = int(item.get("bytes", -1))
        if not relative or relative.startswith(("/", "..")) or not SHA_RE.fullmatch(digest):
            raise RuntimeError("model snapshot receipt file identity is invalid")
        allow_patterns.append(relative)
        expected[relative] = (size, digest)
    started = time.perf_counter()
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repository,
        revision=revision,
        local_dir=MODEL_ROOT,
        allow_patterns=allow_patterns,
    )
    elapsed = time.perf_counter() - started
    total = 0
    for relative, (expected_size, expected_sha) in expected.items():
        path = MODEL_ROOT / relative
        if not path.is_file() or path.stat().st_size != expected_size:
            raise RuntimeError(f"model snapshot file size mismatch: {relative}")
        if sha256_file(path) != expected_sha:
            raise RuntimeError(f"model snapshot file hash mismatch: {relative}")
        total += expected_size
    if total != int(receipt.get("total_bytes", -1)):
        raise RuntimeError("model snapshot verified byte coverage drifted")
    model_sha = sha256_file(MODEL_ROOT / "model.safetensors")
    if model_sha != str(receipt.get("model_safetensors_sha256", "")):
        raise RuntimeError("model.safetensors hash disagrees with snapshot receipt")
    return revision, model_sha, elapsed


def synthetic_png() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            font = ImageFont.truetype(candidate, 96)
            break
    else:
        try:
            font = ImageFont.load_default(size=72)
        except TypeError:
            font = ImageFont.load_default()
    y = 70
    for line in ("TAVONEL", "DATE 2026-08-16", "AMOUNT 42.50 USD", "POLICY MUST"):
        draw.text((100, y), line, fill="black", font=font)
        y += 180
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def request_json(url: str, *, payload: dict[str, Any] | None = None, timeout: float = 10) -> Any:
    body = None if payload is None else canonical_bytes(payload)
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST" if body else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def wait_health(process: subprocess.Popen[str], deadline_seconds: int = 420) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM assembly server exited early with {process.returncode}")
        try:
            request = urllib.request.Request(
                "http://127.0.0.1:8000/health",
                headers={"Accept": "*/*"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                if 200 <= response.status < 300:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(3)
    raise TimeoutError("vLLM assembly server did not become healthy")


def gpu_identity() -> tuple[str, str, str]:
    name = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True
    ).strip().splitlines()[0]
    driver = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True
    ).strip().splitlines()[0]
    import torch

    cuda = str(torch.version.cuda or "")
    if not re.fullmatch(r"1[123]\.\d", cuda):
        raise RuntimeError(f"unexpected torch CUDA version: {cuda!r}")
    return name, cuda, driver


def qualify() -> None:
    started = datetime.now(UTC)
    phase("identity")
    assembly_id = os.environ.get("TAVONEL_ASSEMBLY_ID", "")
    base_image = os.environ.get("TAVONEL_BASE_IMAGE_DIGEST", "")
    bootstrap_sha = os.environ.get("TAVONEL_BOOTSTRAP_SHA256", "")
    if not SHA_RE.fullmatch(assembly_id) or not SHA_RE.fullmatch(bootstrap_sha):
        raise RuntimeError("assembly/bootstrap identity is invalid")
    if not BASE_IMAGE_RE.fullmatch(base_image):
        raise RuntimeError("public vLLM base image digest is not immutable")
    if os.environ.get("FOLYNTA_QUALIFICATION_ONLY") != "1":
        raise RuntimeError("qualification-only guard is not armed")
    if sha256_file(Path(__file__)) != bootstrap_sha:
        raise RuntimeError("assembly qualification bootstrap hash mismatch")

    package_receipt = decode_receipt("TAVONEL_SECURITY_RECEIPT_B64")
    model_receipt = decode_receipt("TAVONEL_MODEL_RECEIPT_B64")
    package_receipt_sha = sha256_bytes(canonical_bytes(package_receipt))
    model_receipt_sha = sha256_bytes(canonical_bytes(model_receipt))
    expected_assembly = sha256_bytes(
        canonical_bytes(
            {
                "base_image_digest": base_image,
                "bootstrap_sha256": bootstrap_sha,
                "model_receipt_sha256": model_receipt_sha,
                "security_receipt_sha256": package_receipt_sha,
            }
        )
    )
    if expected_assembly != assembly_id:
        raise RuntimeError("assembly id does not match bound components")

    before, after, package_sha = install_security_patch(package_receipt)
    revision, model_sha, model_seconds = verify_model_snapshot(model_receipt)

    phase("runtime_identity")
    actual_versions = {name: version(name) for name in EXPECTED_VERSIONS}
    if actual_versions != EXPECTED_VERSIONS:
        raise RuntimeError(f"runtime dependency mismatch: {actual_versions!r}")
    gpu_name, cuda_version, driver_version = gpu_identity()

    phase("starting_vllm", gpu_type=gpu_name, cuda_version=cuda_version)
    server_log = (ROOT / "vllm-server.log").open("w", encoding="utf-8", buffering=1)
    process = subprocess.Popen(
        [
            "vllm",
            "serve",
            str(MODEL_ROOT),
            "--served-model-name",
            "ATH-MaaS/OvisOCR2",
            "--trust-remote-code",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--gpu-memory-utilization",
            "0.72",
            "--gdn-prefill-backend",
            "triton",
            "--disable-log-stats",
        ],
        stdout=server_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_health(process)
        phase("smoke")
        image_bytes = synthetic_png()
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        body = {
            "model": "ATH-MaaS/OvisOCR2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract all visible text exactly. Preserve letters, numbers, punctuation, currency codes, dates, and modal words. Output only the transcription.",
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        smoke_started = time.perf_counter()
        response = request_json(
            "http://127.0.0.1:8000/v1/chat/completions",
            payload=body,
            timeout=180,
        )
        smoke_seconds = time.perf_counter() - smoke_started
        text = str(response["choices"][0]["message"]["content"])
        upper = text.upper()
        checks = {token: token in upper for token in TOKENS}
        canonical_prediction = {"critical_tokens_present": checks}
        canonical_expected = {"critical_tokens_present": {token: True for token in TOKENS}}
        prediction_hash = sha256_bytes(canonical_bytes(canonical_prediction))
        expected_hash = sha256_bytes(canonical_bytes(canonical_expected))
        if not all(checks.values()) or prediction_hash != expected_hash:
            raise RuntimeError("frozen critical-token OCR smoke failed")

        evidence = {
            "schema": "tavonel.verified-runtime-assembly-evidence.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "assembly_id": assembly_id,
            "base_image_digest": base_image,
            "bootstrap_sha256": bootstrap_sha,
            "security_receipt_sha256": package_receipt_sha,
            "security_package_sha256": package_sha,
            "security_version_before": before,
            "security_version_after": after,
            "gpu_type": gpu_name,
            "cuda_version": cuda_version,
            "framework_version": "vllm-" + actual_versions["vllm"],
            "model_revision": revision,
            "model_receipt_sha256": model_receipt_sha,
            "model_artifact_sha256": model_sha,
            "smoke_input_sha256": sha256_bytes(image_bytes),
            "smoke_prediction_sha256": prediction_hash,
            "smoke_expected_sha256": expected_hash,
            "identity_verified": True,
            "security_patch_verified": True,
            "model_artifact_verified": True,
            "smoke_passed": True,
        }
        write_json("assembly-verification.json", evidence)
        write_json(
            "qualification-detail.json",
            {
                "schema": "tavonel.verified-runtime-assembly-detail.v1",
                "started_at": started.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "public_benchmark_inference_allowed": False,
                "dependency_versions": actual_versions,
                "gpu_type": gpu_name,
                "cuda_version": cuda_version,
                "driver_version": driver_version,
                "security_version_before": before,
                "security_version_after": after,
                "model_download_seconds": round(model_seconds, 3),
                "smoke_seconds": round(smoke_seconds, 3),
                "smoke_response_sha256": sha256_bytes(text.encode("utf-8")),
                "critical_token_checks": checks,
            },
        )
        phase("done", passed=True)
    finally:
        server_log.flush()


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=serve, name="assembly-evidence-http", daemon=True).start()
    try:
        qualify()
    except Exception as exc:
        write_json(
            "qualification-error.json",
            {
                "schema": "tavonel.verified-runtime-assembly-error.v1",
                "at": datetime.now(UTC).isoformat(),
                "error_type": type(exc).__name__,
                "message": str(exc)[:1000],
            },
        )
        phase("error", error_type=type(exc).__name__)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
