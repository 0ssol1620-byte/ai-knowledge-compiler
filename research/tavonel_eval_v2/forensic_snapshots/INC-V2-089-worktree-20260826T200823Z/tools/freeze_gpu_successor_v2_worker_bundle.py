#!/usr/bin/env python3
"""Build a content-verified GPU successor V2 worker manifest.

This tool records public verification material only.  It refuses secret-like
fields and never accepts, reads, or writes an Ed25519 private key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA = "tavonel.v2.gpu_successor_worker_bundle.v2"
STUDY_ID = "SOURCE_FACT_PROPAGATION_MODEL_V2"
SHA_PREFIX = "sha256:"
SECRET_FIELD_FRAGMENTS = ("private_key", "secret", "password", "credential", "api_key")


class BundleFreezeRefused(RuntimeError):
    """The proposed bundle could not prove immutable, secret-free inputs."""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return SHA_PREFIX + digest.hexdigest()


def canonical_sha(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return SHA_PREFIX + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _require_sha(value: str, label: str) -> str:
    if len(value) != 71 or not value.startswith(SHA_PREFIX):
        raise BundleFreezeRefused(f"{label} is not sha256:<64 hex>")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise BundleFreezeRefused(f"{label} is not sha256:<64 hex>") from error
    return value


def _verified_artifact(path: Path, expected_sha256: str, logical_path: str) -> dict[str, str]:
    if not path.is_file():
        raise BundleFreezeRefused(f"artifact is absent: {logical_path}")
    expected = _require_sha(expected_sha256, logical_path)
    actual = sha_file(path)
    if actual != expected:
        raise BundleFreezeRefused(f"artifact hash drifted: {logical_path}")
    logical = Path(logical_path)
    if logical.is_absolute() or ".." in logical.parts or logical_path.startswith(("/", "\\")):
        raise BundleFreezeRefused(f"artifact logical path is unsafe: {logical_path}")
    return {"path": logical_path.replace("\\", "/"), "sha256": actual}


def _assert_no_secret_fields(value: Any, path: str = "bundle") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            folded = str(key).casefold()
            if any(fragment in folded for fragment in SECRET_FIELD_FRAGMENTS):
                raise BundleFreezeRefused(f"secret-like field refused at {path}.{key}")
            _assert_no_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_fields(child, f"{path}[{index}]")


def build_bundle(
    *,
    worker_path: Path,
    worker_expected_sha256: str,
    worker_logical_path: str,
    scorer_path: Path,
    scorer_expected_sha256: str,
    scorer_logical_path: str,
    terminal_public_key_b64: str,
    model_repository: str,
    model_revision_sha256: str,
    tokenizer_sha256: str,
    vllm_version: str,
    determinism_repeats: int,
) -> dict[str, Any]:
    worker = _verified_artifact(worker_path, worker_expected_sha256, worker_logical_path)
    scorer = _verified_artifact(scorer_path, scorer_expected_sha256, scorer_logical_path)
    try:
        public_bytes = base64.b64decode(terminal_public_key_b64, validate=True)
        Ed25519PublicKey.from_public_bytes(public_bytes)
    except (ValueError, TypeError) as error:
        raise BundleFreezeRefused("terminal public key is not raw Ed25519 base64") from error
    if not model_repository or not vllm_version or determinism_repeats < 1:
        raise BundleFreezeRefused("model, vLLM version, and positive repeats are required")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "study_id": STUDY_ID,
        "bundle_version": 2,
        "entrypoint": ["python", worker["path"]],
        "entrypoint_path": worker["path"],
        "entrypoint_sha256": worker["sha256"],
        "scorer_path": scorer["path"],
        "scorer_sha256": scorer["sha256"],
        "model_repository": model_repository,
        "model_revision_sha256": _require_sha(model_revision_sha256, "model revision"),
        "tokenizer_sha256": _require_sha(tokenizer_sha256, "tokenizer"),
        "vllm_version": vllm_version,
        "determinism_repeats": determinism_repeats,
        "terminal_public_key_b64": terminal_public_key_b64,
        "signing_injection_policy": (
            "Ed25519 signing material is injected ephemerally; it is never serialized in bundle"
        ),
    }
    # Secret scanning is structural to avoid pretending prose scanning is a
    # credential detector.
    _assert_no_secret_fields(payload)
    payload["bundle_sha256"] = canonical_sha(payload)
    payload["facts_digest"] = canonical_sha(payload)
    return payload


def write_exclusive(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
    except FileExistsError as error:
        raise BundleFreezeRefused("bundle output already exists") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True, type=Path)
    parser.add_argument("--worker-sha256", required=True)
    parser.add_argument("--worker-logical-path", required=True)
    parser.add_argument("--scorer", required=True, type=Path)
    parser.add_argument("--scorer-sha256", required=True)
    parser.add_argument("--scorer-logical-path", required=True)
    parser.add_argument("--terminal-public-key-b64", required=True)
    parser.add_argument("--model-repository", required=True)
    parser.add_argument("--model-revision-sha256", required=True)
    parser.add_argument("--tokenizer-sha256", required=True)
    parser.add_argument("--vllm-version", required=True)
    parser.add_argument("--determinism-repeats", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bundle = build_bundle(
        worker_path=args.worker,
        worker_expected_sha256=args.worker_sha256,
        worker_logical_path=args.worker_logical_path,
        scorer_path=args.scorer,
        scorer_expected_sha256=args.scorer_sha256,
        scorer_logical_path=args.scorer_logical_path,
        terminal_public_key_b64=args.terminal_public_key_b64,
        model_repository=args.model_repository,
        model_revision_sha256=args.model_revision_sha256,
        tokenizer_sha256=args.tokenizer_sha256,
        vllm_version=args.vllm_version,
        determinism_repeats=args.determinism_repeats,
    )
    write_exclusive(args.output, bundle)
    print(json.dumps({"output": str(args.output), "sha256": sha_file(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SCHEMA",
    "STUDY_ID",
    "BundleFreezeRefused",
    "build_bundle",
    "canonical_sha",
    "sha_file",
    "write_exclusive",
]
