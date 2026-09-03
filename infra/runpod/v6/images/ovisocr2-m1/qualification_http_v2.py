#!/usr/bin/env python3
"""Qualification-only HTTP evidence producer baked into the Ovis runtime.

This program is intentionally not a benchmark runner.  It verifies the exact
baked model/runtime identity on one GPU, performs one frozen synthetic OCR
smoke, writes ``folynta.runtime-verification-evidence.v1``, and then serves the
content-free evidence over HTTP until the qualification Pod is stopped.
"""

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

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/opt/folynta/qualification")
MODEL_ROOT = Path(os.environ.get("FOLYNTA_MODEL_ROOT", "/opt/folynta/models/OvisOCR2"))
BAKED_RECEIPT = Path("/opt/folynta/baked-runtime-receipt.txt")
MODEL_REVISION = os.environ.get("MODEL_REVISION", "")
MODEL_SHA256 = "9270560288656ece9d594ef4324dc45b50537739434c192a699c9bbc22346e1a"
TOKENS = ("TAVONEL", "2026-08-16", "42.50", "USD", "MUST")
IMAGE_DIGEST_RE = re.compile(r"^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
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
            "schema": "tavonel.qualification-status.v1",
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
    server = ThreadingHTTPServer(("0.0.0.0", 8001), _handler())
    server.serve_forever()


def synthetic_png() -> bytes:
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
    for line in (
        "TAVONEL",
        "DATE 2026-08-16",
        "AMOUNT 42.50 USD",
        "POLICY MUST",
    ):
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
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def wait_health(process: subprocess.Popen[str], deadline_seconds: int = 420) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM qualification server exited early with {process.returncode}")
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
    raise TimeoutError("vLLM qualification server did not become healthy")


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
    image_digest = os.environ.get("FOLYNTA_IMAGE_DIGEST", "")
    if not IMAGE_DIGEST_RE.fullmatch(image_digest):
        raise RuntimeError("FOLYNTA_IMAGE_DIGEST is missing or not immutable GHCR")
    if os.environ.get("FOLYNTA_QUALIFICATION_ONLY") != "1":
        raise RuntimeError("qualification-only guard is not armed")
    if not BAKED_RECEIPT.is_file() or not MODEL_ROOT.joinpath("model.safetensors").is_file():
        raise RuntimeError("baked runtime/model files are missing")
    if not re.fullmatch(r"[0-9a-f]{40,64}", MODEL_REVISION):
        raise RuntimeError("MODEL_REVISION is invalid")

    actual_versions = {name: version(name) for name in EXPECTED_VERSIONS}
    if actual_versions != EXPECTED_VERSIONS:
        raise RuntimeError(f"runtime dependency mismatch: {actual_versions!r}")
    baked_text = BAKED_RECEIPT.read_text(encoding="utf-8")
    if f"model_revision={MODEL_REVISION}" not in baked_text:
        raise RuntimeError("baked runtime receipt model revision mismatch")
    if f"model_safetensors_sha256={MODEL_SHA256}" not in baked_text:
        raise RuntimeError("baked runtime receipt model hash mismatch")

    phase("model_artifact")
    observed_model = sha256_file(MODEL_ROOT / "model.safetensors")
    expected_model = "sha256:" + MODEL_SHA256
    if observed_model != expected_model:
        raise RuntimeError("baked model artifact hash mismatch")
    baked_runtime_hash = sha256_file(BAKED_RECEIPT)
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
            "http://127.0.0.1:8000/v1/chat/completions", payload=body, timeout=180
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
            "schema": "folynta.runtime-verification-evidence.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "image_digest": image_digest,
            "gpu_type": gpu_name,
            "cuda_version": cuda_version,
            "framework_version": "vllm-" + actual_versions["vllm"],
            "model_revision": MODEL_REVISION,
            "model_artifact_sha256": observed_model,
            "baked_runtime_file_sha256": baked_runtime_hash,
            "smoke_input_sha256": sha256_bytes(image_bytes),
            "smoke_prediction_sha256": prediction_hash,
            "smoke_expected_sha256": expected_hash,
            "identity_verified": True,
            "model_artifact_verified": True,
            "smoke_passed": True,
        }
        write_json("runtime-verification.json", evidence)
        write_json(
            "qualification-detail.json",
            {
                "schema": "tavonel.runtime-qualification-detail.v1",
                "started_at": started.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "public_benchmark_inference_allowed": False,
                "gpu_type": gpu_name,
                "cuda_version": cuda_version,
                "driver_version": driver_version,
                "dependency_versions": actual_versions,
                "model_artifact_sha256": observed_model,
                "baked_runtime_file_sha256": baked_runtime_hash,
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
    threading.Thread(target=serve, name="qualification-evidence-http", daemon=True).start()
    try:
        qualify()
    except Exception as exc:
        write_json(
            "qualification-error.json",
            {
                "schema": "tavonel.runtime-qualification-error.v1",
                "at": datetime.now(UTC).isoformat(),
                "error_type": type(exc).__name__,
                "message": str(exc)[:2000],
                "public_benchmark_inference_allowed": False,
            },
        )
        phase("error", passed=False, error_type=type(exc).__name__)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
