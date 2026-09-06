#!/usr/bin/env python3
"""Freeze the complete executable GPU successor V2 bundle, or refuse."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

TOOLS = Path(__file__).resolve().parent
NS = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import freeze_gpu_successor_v2_worker_bundle as worker_freeze  # noqa: E402
from common import canonical_sha, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.gpu_successor_v2.protocol_freeze.v1"
STEM = "gpu-successor-v2-protocol-freeze"
STUDY_ID = "SOURCE_FACT_PROPAGATION_MODEL_V2"
STUDY_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_STUDY_V2.yaml"
RUNTIME_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_RUNTIME_V2.yaml"

COMPONENTS = (
    TOOLS / "build_gpu_successor_v2_cohort.py",
    TOOLS / "gpu_successor_v2_four_link_acceptance.py",
    TOOLS / "gpu_successor_v2_prompt_schema.py",
    TOOLS / "build_gpu_successor_v2_contexts.py",
    TOOLS / "materialize_gpu_successor_v2_inputs.py",
    TOOLS / "gpu_successor_v2_scorer.py",
    TOOLS / "gpu_successor_v2_worker.py",
    TOOLS / "gpu_successor_v2_inference.py",
    TOOLS / "gpu_successor_v2_safety.py",
    TOOLS / "gpu_successor_v2_runtime.py",
    TOOLS / "gpu_successor_v2_runpod_backend.py",
    TOOLS / "launch_gpu_successor_v2.py",
    TOOLS / "freeze_gpu_successor_v2_worker_bundle.py",
    TOOLS / "freeze_gpu_successor_v2_protocols.py",
)


class V2FreezeRefused(RuntimeError):
    """The prospective executable bundle is incomplete or still a draft."""


def _relative(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return str(path.resolve())


def _protocol(path: Path, schema: str, protocol_id: str) -> dict[str, Any]:
    try:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise V2FreezeRefused(f"protocol is unreadable: {_relative(path)}") from error
    if not isinstance(body, dict) or body.get("schema") != schema:
        raise V2FreezeRefused(f"protocol schema drift: {_relative(path)}")
    if body.get("protocol_id") != protocol_id or body.get("study_id") != STUDY_ID:
        raise V2FreezeRefused(f"protocol identity drift: {_relative(path)}")
    if body.get("status") != "FROZEN":
        raise V2FreezeRefused(f"protocol is not authored FROZEN: {_relative(path)}")
    return body


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V2FreezeRefused(f"{label} is unreadable") from error
    if not isinstance(body, dict):
        raise V2FreezeRefused(f"{label} is not a mapping")
    return body


def build_freeze(
    *,
    study_protocol: Path,
    runtime_protocol: Path,
    worker_bundle: Path,
    tokenizer_manifest: Path,
    model_pin: Path,
    sfir4_acceptance: Path,
    four_link_acceptance: Path,
    materialized_input: Path,
    runtime_image_digest: str,
) -> dict[str, Any]:
    _protocol(
        study_protocol,
        "tavonel.v2.protocol.gpu_successor_study.v2",
        "GPU_SUCCESSOR_STUDY_V2",
    )
    _protocol(
        runtime_protocol,
        "tavonel.v2.protocol.gpu_successor_runtime.v2",
        "GPU_SUCCESSOR_RUNTIME_V2",
    )
    bundle = _json(worker_bundle, "worker bundle")
    if bundle.get("schema") != worker_freeze.SCHEMA or bundle.get("study_id") != STUDY_ID:
        raise V2FreezeRefused("worker bundle is not the V2 study bundle")
    worker_path = TOOLS / "gpu_successor_v2_worker.py"
    scorer_path = TOOLS / "gpu_successor_v2_scorer.py"
    if bundle.get("entrypoint_sha256") != sha_file(worker_path):
        raise V2FreezeRefused("worker bundle does not bind the current V2 worker bytes")
    if bundle.get("scorer_sha256") != sha_file(scorer_path):
        raise V2FreezeRefused("worker bundle does not bind the current V2 scorer bytes")
    tokenizer = _json(tokenizer_manifest, "tokenizer manifest")
    if tokenizer.get("schema") != "tavonel.v2.tokenizer_artifact_manifest.v1":
        raise V2FreezeRefused("tokenizer manifest schema drift")
    model = _json(model_pin, "model pin")
    if model.get("schema") != "tavonel.v2.model_artifact_manifest.v1":
        raise V2FreezeRefused("model artifact semantic schema drift")
    if (
        tokenizer.get("repository") != model.get("repository")
        or tokenizer.get("revision") != model.get("revision")
        or bundle.get("tokenizer_sha256") != tokenizer.get("files_digest")
        or bundle.get("model_revision_sha256") != model.get("files_digest")
    ):
        raise V2FreezeRefused("model/tokenizer/bundle semantic pins are not cross-bound")
    if not isinstance(runtime_image_digest, str) or "@sha256:" not in runtime_image_digest:
        raise V2FreezeRefused("OCI runtime image digest is not exact")
    sfir4 = _json(sfir4_acceptance, "SFIR4 acceptance")
    four = _json(four_link_acceptance, "V2 four-link acceptance")
    materialized = _json(materialized_input, "V2 materialized input")
    sfir4_sha, four_sha, materialized_sha = (
        sha_file(sfir4_acceptance),
        sha_file(four_link_acceptance),
        sha_file(materialized_input),
    )
    if sfir4.get("state") != "ACCEPTED" or sfir4.get("verdict") != "PASS":
        raise V2FreezeRefused("actual SFIR4 ACCEPTED/PASS authority is required")
    if (
        four.get("state") != "ACCEPTED"
        or four.get("verdict") != "PASS"
        or (four.get("source_sfir4_acceptance") or {}).get("sha256") != sfir4_sha
        or materialized.get("manifest", {}).get("sha256") != four.get("manifest_sha256")
        or materialized.get("manifest", {}).get("sfir4_acceptance", {}).get("sha256") != sfir4_sha
        or materialized.get("item_count") != 450
    ):
        raise V2FreezeRefused("execution authorities are absent or not exactly cross-bound")
    components = {_relative(path): sha_file(path) for path in COMPONENTS if path.is_file()}
    if len(components) != len(COMPONENTS):
        raise V2FreezeRefused("the V2 executable component set is incomplete")
    body = {
        "schema": SCHEMA,
        "study_id": STUDY_ID,
        "freeze_complete": True,
        "protocols": {
            "study": {"path": _relative(study_protocol), "sha256": sha_file(study_protocol)},
            "runtime": {
                "path": _relative(runtime_protocol),
                "sha256": sha_file(runtime_protocol),
            },
        },
        "worker_bundle": {"path": _relative(worker_bundle), "sha256": sha_file(worker_bundle)},
        "tokenizer_manifest": {
            "path": _relative(tokenizer_manifest),
            "sha256": sha_file(tokenizer_manifest),
        },
        "model_pin": {"path": _relative(model_pin), "sha256": sha_file(model_pin)},
        "runtime_image_digest": runtime_image_digest,
        "execution_authorities": {
            "sfir4_acceptance_sha256": sfir4_sha,
            "four_link_acceptance_sha256": four_sha,
            "materialized_input_sha256": materialized_sha,
        },
        "components": components,
        "provider_calls": 0,
        "gpu_seconds": 0,
        "spend_usd": 0,
    }
    body["bundle_digest"] = canonical_sha(body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=STUDY_PROTOCOL)
    parser.add_argument("--runtime", type=Path, default=RUNTIME_PROTOCOL)
    parser.add_argument("--worker-bundle", type=Path, required=True)
    parser.add_argument("--tokenizer-manifest", type=Path, required=True)
    parser.add_argument("--model-pin", type=Path, required=True)
    parser.add_argument("--sfir4-acceptance", type=Path, required=True)
    parser.add_argument("--four-link-acceptance", type=Path, required=True)
    parser.add_argument("--materialized-input", type=Path, required=True)
    parser.add_argument("--runtime-image-digest", required=True)
    args = parser.parse_args(argv)
    try:
        body = build_freeze(
            study_protocol=args.study,
            runtime_protocol=args.runtime,
            worker_bundle=args.worker_bundle,
            tokenizer_manifest=args.tokenizer_manifest,
            model_pin=args.model_pin,
            sfir4_acceptance=args.sfir4_acceptance,
            four_link_acceptance=args.four_link_acceptance,
            materialized_input=args.materialized_input,
            runtime_image_digest=args.runtime_image_digest,
        )
    except V2FreezeRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2))
        return 4
    written = write_immutable(
        STEM, body, tool=Path(__file__).resolve(), protocol=args.study, pointer=False
    )
    print(json.dumps({"state": "FROZEN", **written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["V2FreezeRefused", "build_freeze"]
