#!/usr/bin/env python3
"""Real GPU successor V2 worker with injectable offline boundaries.

Production reads a content-addressed input through a presigned GET, talks only
to a loopback OpenAI-compatible vLLM server, uploads the raw/scored artifact,
and finally publishes an Ed25519-authenticated terminal envelope.  Tests inject
the inference and transport boundaries and perform no network calls.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

import gpu_successor_v2_inference as inferential
import gpu_successor_v2_scorer as scorer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RAW_OUTPUT_SCHEMA = "tavonel.v2.gpu_successor_raw_outputs.v1"
TERMINAL_ENVELOPE_SCHEMA = "tavonel.v2.gpu_successor_terminal_envelope.v1"
ARMS = ("CURRENT_TYPED", "STALE_TYPED", "CURRENT_TEXT_ONLY")


class WorkerError(RuntimeError):
    """A scientific or authenticated worker transition failed closed."""


class Inference(Protocol):
    def __call__(self, request: dict[str, Any]) -> str: ...


class WorkerTransport(Protocol):
    def fetch_input(self) -> bytes: ...
    def upload_output(self, filename: str, body: bytes) -> str: ...
    def publish_status(self, body: bytes) -> None: ...


def sha_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _require_https_capability(url: str, label: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise WorkerError(f"{label} must be a credential-free https capability URL")
    return url


def verify_runtime_bundle(bundle: dict[str, Any], *, worker_path: Path, scorer_path: Path) -> None:
    """Re-hash the baked files and both manifest digests before inference."""
    for path, field in (
        (worker_path, "entrypoint_sha256"),
        (scorer_path, "scorer_sha256"),
    ):
        if not path.is_file() or sha_bytes(path.read_bytes()) != bundle.get(field):
            raise WorkerError(f"runtime artifact drifted: {field}")
    without_facts = {key: value for key, value in bundle.items() if key != "facts_digest"}
    if sha_bytes(canonical_bytes(without_facts)) != bundle.get("facts_digest"):
        raise WorkerError("worker bundle facts_digest drifted")
    bundle_payload = {
        key: value for key, value in bundle.items() if key not in {"bundle_sha256", "facts_digest"}
    }
    if sha_bytes(canonical_bytes(bundle_payload)) != bundle.get("bundle_sha256"):
        raise WorkerError("worker bundle content digest drifted")


def verify_image_artifact_manifest(
    *, root: Path, manifest_path: Path, schema: str, expected_files_digest: str
) -> None:
    """Re-hash every image-local model/tokenizer file against its semantic manifest."""
    if not root.is_dir() or not manifest_path.is_file():
        raise WorkerError("image-local artifact root or manifest is absent")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkerError("image-local artifact manifest is unreadable") from error
    if manifest.get("schema") != schema or manifest.get("files_digest") != expected_files_digest:
        raise WorkerError("image-local artifact semantic schema or digest drifted")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise WorkerError("image-local artifact manifest has no files")
    expected_paths: set[str] = set()
    for row in files:
        relative = row.get("path") if isinstance(row, dict) else None
        if not isinstance(relative, str) or not relative or ".." in Path(relative).parts:
            raise WorkerError("image-local artifact manifest has an unsafe path")
        path = root / relative
        if (
            not path.is_file()
            or path.is_symlink()
            or sha_bytes(path.read_bytes()) != row.get("sha256")
        ):
            raise WorkerError(f"image-local artifact file drifted: {relative}")
        expected_paths.add(Path(relative).as_posix())
    observed = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != manifest_path.resolve()
    }
    if observed != expected_paths:
        raise WorkerError("image-local artifact manifest is not a complete file enumeration")


def _require_matching_signing_key(private_key: Ed25519PrivateKey, bundle: dict[str, Any]) -> None:
    public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    try:
        expected = base64.b64decode(bundle["terminal_public_key_b64"], validate=True)
    except (KeyError, ValueError, TypeError) as error:
        raise WorkerError("worker bundle terminal public key is invalid") from error
    if public != expected:
        raise WorkerError("ephemeral signing key does not match the frozen public key")


class LocalVllmClient:
    """Minimal OpenAI-compatible client restricted to a loopback endpoint."""

    def __init__(self, *, base_url: str, model: str, timeout_seconds: float = 600.0) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise WorkerError("vLLM endpoint must be an http loopback address")
        if not model or any(character.isspace() for character in model):
            raise WorkerError("an exact local vLLM model identifier is required")
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.model = model
        self.timeout_seconds = timeout_seconds

    def __call__(self, request: dict[str, Any]) -> str:
        payload = canonical_bytes(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": request["system_prompt"]},
                    {"role": "user", "content": request["user_prompt"]},
                ],
                "temperature": request["decoding"]["temperature"],
                "max_tokens": request["max_new_tokens"],
            }
        )
        call = urllib.request.Request(  # noqa: S310 - loopback URL validated in __init__
            self.url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - loopback URL validated in __init__
                call, timeout=self.timeout_seconds
            ) as response:
                body = json.loads(response.read())
            text = body["choices"][0]["message"]["content"]
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            raise WorkerError("local vLLM response was unavailable or malformed") from error
        if not isinstance(text, str):
            raise WorkerError("local vLLM returned a non-text answer")
        return text


class PresignedHttpTransport:
    """Credential-free object transport; all capabilities arrive as URLs."""

    def __init__(
        self,
        *,
        input_get_url: str,
        status_put_url: str,
        status_headers: dict[str, str],
        output_post_url: str,
        output_post_fields: dict[str, str],
        output_object_prefix: str,
    ) -> None:
        self.input_get_url = _require_https_capability(input_get_url, "input GET")
        self.status_put_url = _require_https_capability(status_put_url, "status PUT")
        self.status_headers = status_headers
        self.output_post_url = _require_https_capability(output_post_url, "output POST")
        self.output_post_fields = output_post_fields
        self.output_object_prefix = output_object_prefix.rstrip("/") + "/"

    def fetch_input(self) -> bytes:
        try:
            with urllib.request.urlopen(  # noqa: S310 - validated https capability URL
                self.input_get_url, timeout=120
            ) as response:
                return response.read()
        except OSError as error:
            raise WorkerError("presigned input GET failed") from error

    def upload_output(self, filename: str, body: bytes) -> str:
        boundary = "tavonel-" + hashlib.sha256(body).hexdigest()[:24]
        parts: list[bytes] = []
        fields = {**self.output_post_fields, "Content-Type": "application/json"}
        for key in sorted(fields):
            parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                    str(fields[key]).encode(),
                    b"\r\n",
                ]
            )
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
                b"Content-Type: application/json\r\n\r\n",
                body,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(  # noqa: S310 - validated https capability URL
            self.output_post_url,
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - validated https capability URL
                request, timeout=300
            ) as response:
                if response.status not in {200, 201, 204}:
                    raise WorkerError("presigned output POST was not acknowledged")
        except OSError as error:
            raise WorkerError("presigned output POST failed") from error
        return self.output_object_prefix + filename

    def publish_status(self, body: bytes) -> None:
        request = urllib.request.Request(  # noqa: S310 - validated https capability URL
            self.status_put_url, data=body, headers=self.status_headers, method="PUT"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - validated https capability URL
                request, timeout=120
            ) as response:
                if response.status not in {200, 201, 204}:
                    raise WorkerError("terminal status PUT was not acknowledged")
        except OSError as error:
            raise WorkerError("terminal status PUT failed") from error


def _validate_input(body: dict[str, Any]) -> list[dict[str, Any]]:
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise WorkerError("materialized input has no items")
    if body.get("item_count") != len(items):
        raise WorkerError("materialized input item_count drifted")
    seen: set[str] = set()
    lineages: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("fact_id"), str):
            raise WorkerError("materialized input carries an invalid item")
        if item["fact_id"] in seen:
            raise WorkerError("materialized input contains duplicate fact ids")
        seen.add(item["fact_id"])
        lineage_id = item.get("lineage_id")
        if not isinstance(lineage_id, str) or not lineage_id or lineage_id in lineages:
            raise WorkerError("materialized input requires one unique question per lineage")
        lineages.add(lineage_id)
        if not isinstance(item.get("arms"), dict) or set(item["arms"]) != set(ARMS):
            raise WorkerError("materialized item does not contain exactly both arms")
        scorer.expected_value(item)
    if len(items) != inferential.TARGET_LINEAGES:
        raise WorkerError("materialized input must contain exactly 450 lineages")
    return sorted(items, key=lambda value: value["fact_id"])


def _request_for_inference(arm_body: dict[str, Any]) -> dict[str, Any]:
    required = ("system_prompt", "user_prompt", "decoding", "max_new_tokens")
    if any(key not in arm_body for key in required):
        raise WorkerError("arm request is incomplete")
    if arm_body["decoding"] != {"temperature": 0.0, "strategy": "greedy", "thinking": "off"}:
        raise WorkerError("arm decoding is not the frozen deterministic configuration")
    return {key: arm_body[key] for key in required}


def run_worker(
    *,
    transport: WorkerTransport,
    inference: Inference,
    private_key: Ed25519PrivateKey,
    bundle: dict[str, Any],
    expected_input_sha256: str,
    determinism_repeats: int,
) -> dict[str, Any]:
    if determinism_repeats < 1:
        raise WorkerError("determinism_repeats must be positive")
    _require_matching_signing_key(private_key, bundle)
    input_bytes = transport.fetch_input()
    input_sha = sha_bytes(input_bytes)
    if input_sha != expected_input_sha256:
        raise WorkerError("presigned input failed its content digest")
    try:
        materialized = json.loads(input_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkerError("materialized input is not JSON") from error
    items = _validate_input(materialized)

    output_items: list[dict[str, Any]] = []
    for item in items:
        output_arms: dict[str, Any] = {}
        response_texts: dict[str, list[str]] = {}
        for arm in ARMS:
            request = _request_for_inference(item["arms"][arm])
            repetitions = []
            for index in range(determinism_repeats):
                response_text = inference(request)
                if not isinstance(response_text, str):
                    raise WorkerError("inference boundary returned non-text output")
                repetitions.append(
                    {
                        "repetition": index,
                        "response_text": response_text,
                        "response_sha256": sha_bytes(response_text.encode("utf-8")),
                        "class": scorer.classify_answer(response_text, scorer.expected_value(item)),
                    }
                )
            response_texts[arm] = [entry["response_text"] for entry in repetitions]
            output_arms[arm] = {"repetitions": repetitions}
        output_items.append(
            {
                "fact_id": item["fact_id"],
                "lineage_id": item.get("lineage_id"),
                "kind": item.get("kind"),
                "arms": output_arms,
                "scoring": scorer.score_item(item, response_texts),
            }
        )

    artifact = {
        "schema": RAW_OUTPUT_SCHEMA,
        "status": "completed",
        "input_set_digest": materialized.get("set_digest"),
        "input_sha256": input_sha,
        "item_count": len(output_items),
        "determinism_repeats": determinism_repeats,
        "items": output_items,
        "inference": inferential.analyze(output_items),
    }
    output_bytes = canonical_bytes(artifact)
    output_sha = sha_bytes(output_bytes)
    filename = output_sha[7:] + ".json"
    output_key = transport.upload_output(filename, output_bytes)
    if output_sha[7:] not in output_key:
        raise WorkerError("transport returned a non-content-addressed output key")

    attestation_keys = (
        "bundle_sha256",
        "entrypoint_sha256",
        "scorer_sha256",
        "model_revision_sha256",
        "tokenizer_sha256",
        "vllm_version",
    )
    if any(key not in bundle for key in attestation_keys):
        raise WorkerError("worker bundle lacks runtime attestation fields")
    envelope = {
        "schema": TERMINAL_ENVELOPE_SCHEMA,
        "status": "completed",
        "input_sha256": input_sha,
        "output_key": output_key,
        "output_sha256": output_sha,
        "runtime_attestation": {key: bundle[key] for key in attestation_keys},
    }
    signature = private_key.sign(canonical_bytes(envelope))
    envelope["signature_b64"] = base64.b64encode(signature).decode("ascii")
    transport.publish_status(canonical_bytes(envelope))
    return {"artifact": artifact, "terminal_envelope": envelope}


def _private_key_from_environment() -> Ed25519PrivateKey:
    encoded = os.environ.get("TAVONEL_TERMINAL_PRIVATE_KEY_B64", "")
    try:
        raw = base64.b64decode(encoded, validate=True)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (ValueError, TypeError) as error:
        raise WorkerError("ephemeral terminal signing key is absent or invalid") from error


def _start_local_vllm(bundle: dict[str, Any]) -> subprocess.Popen[bytes]:
    """Start the pinned, image-local vLLM server without a shell or network model fetch."""
    model_path = Path(os.environ.get("TAVONEL_MODEL_PATH", ""))
    if not model_path.is_dir():
        raise WorkerError("pinned model directory is absent from the runtime image")
    try:
        installed = metadata.version("vllm")
    except metadata.PackageNotFoundError as error:
        raise WorkerError("vLLM is absent from the runtime image") from error
    if installed != bundle.get("vllm_version"):
        raise WorkerError("runtime vLLM version drifted")
    command = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(model_path),
        "--tokenizer",
        str(model_path),
        "--served-model-name",
        str(bundle["model_repository"]),
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--disable-log-requests",
        "--generation-config",
        "vllm",
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)  # noqa: S603
    health = "http://127.0.0.1:8000/health"
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise WorkerError("local vLLM exited before readiness")
        try:
            with urllib.request.urlopen(health, timeout=2) as response:
                if response.status == 200:
                    return process
        except OSError:
            time.sleep(1)
    process.terminate()
    raise WorkerError("local vLLM did not become ready within 900 seconds")


def main() -> int:
    bundle_path = Path(os.environ.get("TAVONEL_WORKER_BUNDLE_PATH", ""))
    if not bundle_path.is_file():
        raise WorkerError("frozen worker bundle is absent from the runtime image")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if bundle.get("facts_digest") != os.environ.get("TAVONEL_WORKER_BUNDLE_FACTS_SHA256"):
        raise WorkerError("runtime worker bundle facts digest drifted")
    verify_runtime_bundle(
        bundle,
        worker_path=Path(str(bundle.get("entrypoint_path", ""))),
        scorer_path=Path(str(bundle.get("scorer_path", ""))),
    )
    model_root = Path(os.environ.get("TAVONEL_MODEL_PATH", ""))
    tokenizer_root = Path(os.environ.get("TAVONEL_TOKENIZER_PATH", ""))
    verify_image_artifact_manifest(
        root=model_root,
        manifest_path=Path(os.environ.get("TAVONEL_MODEL_MANIFEST_PATH", "")),
        schema="tavonel.v2.model_artifact_manifest.v1",
        expected_files_digest=bundle["model_revision_sha256"],
    )
    verify_image_artifact_manifest(
        root=tokenizer_root,
        manifest_path=Path(os.environ.get("TAVONEL_TOKENIZER_MANIFEST_PATH", "")),
        schema="tavonel.v2.tokenizer_artifact_manifest.v1",
        expected_files_digest=bundle["tokenizer_sha256"],
    )
    transport = PresignedHttpTransport(
        input_get_url=os.environ["TAVONEL_INPUT_GET_URL"],
        status_put_url=os.environ["TAVONEL_STATUS_PUT_URL"],
        status_headers=json.loads(os.environ["TAVONEL_STATUS_PUT_HEADERS_JSON"]),
        output_post_url=os.environ["TAVONEL_OUTPUT_POST_URL"],
        output_post_fields=json.loads(os.environ["TAVONEL_OUTPUT_POST_FIELDS_JSON"]),
        output_object_prefix=os.environ["TAVONEL_OUTPUT_OBJECT_PREFIX"],
    )
    server = _start_local_vllm(bundle)
    try:
        inference = LocalVllmClient(
            base_url=os.environ.get("TAVONEL_VLLM_BASE_URL", "http://127.0.0.1:8000"),
            model=str(bundle["model_repository"]),
        )
        run_worker(
            transport=transport,
            inference=inference,
            private_key=_private_key_from_environment(),
            bundle=bundle,
            expected_input_sha256=os.environ["TAVONEL_INPUT_SHA256"],
            determinism_repeats=int(bundle["determinism_repeats"]),
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARMS",
    "LocalVllmClient",
    "PresignedHttpTransport",
    "WorkerError",
    "_start_local_vllm",
    "canonical_bytes",
    "run_worker",
    "sha_bytes",
    "verify_image_artifact_manifest",
    "verify_runtime_bundle",
]
