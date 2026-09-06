#!/usr/bin/env python3
"""Dry-run-first, SFIR4-only launcher for GPU successor V2."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import sha_file
from gpu_successor_v2_four_link_acceptance import verify as verify_four_link
from gpu_successor_v2_runtime import (
    STUDY_ID,
    V2Controller,
    V2Limits,
    V2RuntimeError,
    load_v2_bundle,
)
from gpu_successor_v2_safety import projected_launch_gate

from benchmark.v6.ledger import EvidenceLedger
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget


def _json_exact(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    if not path.is_file() or sha_file(path) != expected_sha256:
        raise V2RuntimeError(f"exact {label} path/hash drifted")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V2RuntimeError(f"{label} is unreadable") from error
    if not isinstance(body, dict):
        raise V2RuntimeError(f"{label} must be a JSON mapping")
    return body


def _verify_live_rate_receipt(path: Path, body: dict[str, Any]) -> dict[str, Any]:
    if body.get("schema") != "tavonel.runpod.provider_rate_receipt.v1":
        raise V2RuntimeError("RunPod rate receipt semantic schema drifted")
    source_url = body.get("source_url")
    if not isinstance(source_url, str) or not source_url.startswith("https://api.runpod.io/"):
        raise V2RuntimeError("rate receipt is not bound to the RunPod provider API")
    try:
        observed = datetime.fromisoformat(str(body["observed_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as error:
        raise V2RuntimeError("rate receipt observed_at is invalid") from error
    age = (datetime.now(UTC) - observed.astimezone(UTC)).total_seconds()
    if age < 0 or age > 900:
        raise V2RuntimeError("RunPod rate receipt is not fresh within 15 minutes")
    raw_path = Path(str(body.get("provider_response_path", "")))
    if not raw_path.is_absolute():
        raw_path = path.parent / raw_path
    raw = _json_exact(
        raw_path.resolve(), body.get("provider_response_sha256"), "raw RunPod rate response"
    )
    if (
        raw.get("gpu_type") != body.get("gpu_type")
        or body.get("gpu_type") != "NVIDIA H200"
        or raw.get("gpu_count") != 1
        or raw.get("hourly_rate_usd") != body.get("hourly_rate_usd")
        or not isinstance(body.get("hourly_rate_usd"), (int, float))
        or body["hourly_rate_usd"] <= 0
    ):
        raise V2RuntimeError("rate receipt does not reproduce the exact provider response")
    return body


def prepare_spec(
    *,
    sfir4_acceptance_path: Path,
    sfir4_acceptance_sha256: str,
    four_link_path: Path,
    four_link_sha256: str,
    materialized_path: Path,
    materialized_sha256: str,
    protocol_freeze_path: Path,
    protocol_freeze_sha256: str,
    worker_bundle_path: Path,
    worker_bundle_sha256: str,
    rate_receipt_path: Path,
    rate_receipt_sha256: str,
    runtime_image_digest: str,
    model_pin_sha256: str,
    projected_gpu_seconds: float = 20_700,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sfir4 = _json_exact(sfir4_acceptance_path, sfir4_acceptance_sha256, "SFIR4 acceptance")
    if (
        sfir4.get("schema") != "tavonel.sfir4.acceptance_authority.v1"
        or sfir4.get("state") != "ACCEPTED"
        or sfir4.get("verdict") != "PASS"
    ):
        raise V2RuntimeError("fresh SFIR4 ACCEPTED/PASS authority is required")
    four = _json_exact(four_link_path, four_link_sha256, "V2 four-link acceptance")
    held = verify_four_link(four)
    if held.get("state") != "ACCEPTED" or held.get("floor") != 450:
        raise V2RuntimeError("V2 four-link floor 450 is not accepted")
    if (four.get("source_sfir4_acceptance") or {}).get("sha256") != sfir4_acceptance_sha256:
        raise V2RuntimeError("SFIR4 acceptance and four-link authority are not cross-bound")
    materialized = _json_exact(materialized_path, materialized_sha256, "V2 materialized input")
    if (
        materialized.get("schema") != "tavonel.v2.gpu_successor_materialized_inputs.v2"
        or materialized.get("study_id") != STUDY_ID
        or materialized.get("item_count") != 450
    ):
        raise V2RuntimeError("V2 materialized input is not exactly 450 lineages")
    lineages = [row.get("lineage_id") for row in materialized.get("items", [])]
    if len(lineages) != len(set(lineages)) or any(not value for value in lineages):
        raise V2RuntimeError("materialized input is not one question per unique lineage")
    if materialized.get("manifest", {}).get("sha256") != four.get("manifest_sha256"):
        raise V2RuntimeError("four-link and materialized input bind different manifests")
    if (
        materialized.get("manifest", {}).get("sfir4_acceptance", {}).get("sha256")
        != sfir4_acceptance_sha256
    ):
        raise V2RuntimeError("materialized input binds a different SFIR4 acceptance")
    if (
        materialized.get("context_artifact", {}).get("sfir4_acceptance_sha256")
        != sfir4_acceptance_sha256
    ):
        raise V2RuntimeError("context artifact binds a different SFIR4 acceptance")
    freeze = _json_exact(protocol_freeze_path, protocol_freeze_sha256, "V2 protocol freeze")
    if (
        freeze.get("schema") != "tavonel.v2.gpu_successor_v2.protocol_freeze.v1"
        or freeze.get("study_id") != STUDY_ID
        or freeze.get("freeze_complete") is not True
    ):
        raise V2RuntimeError("complete V2 protocol freeze is required")
    if (
        freeze.get("worker_bundle", {}).get("sha256") != worker_bundle_sha256
        or freeze.get("model_pin", {}).get("sha256") != model_pin_sha256
    ):
        raise V2RuntimeError("protocol freeze does not bind exact worker/model pins")
    authorities = freeze.get("execution_authorities") or {}
    if (
        authorities.get("sfir4_acceptance_sha256") != sfir4_acceptance_sha256
        or authorities.get("four_link_acceptance_sha256") != four_link_sha256
        or authorities.get("materialized_input_sha256") != materialized_sha256
    ):
        raise V2RuntimeError("protocol freeze does not bind exact execution authorities")
    if freeze.get("runtime_image_digest") != runtime_image_digest:
        raise V2RuntimeError("protocol freeze binds a different OCI runtime image")
    bundle = load_v2_bundle(worker_bundle_path, worker_bundle_sha256)
    rate = _json_exact(rate_receipt_path, rate_receipt_sha256, "live RunPod rate receipt")
    _verify_live_rate_receipt(rate_receipt_path, rate)
    projection = projected_launch_gate(
        projected_gpu_seconds=projected_gpu_seconds,
        live_hourly_rate_usd=rate.get("hourly_rate_usd"),
        rate_source=f"{rate_receipt_path.resolve()}#{rate_receipt_sha256}",
    )
    if not isinstance(runtime_image_digest, str) or "@sha256:" not in runtime_image_digest:
        raise V2RuntimeError("runtime image is not pinned by OCI digest")
    spec = {
        "study_id": STUDY_ID,
        "runtime_image_digest": runtime_image_digest,
        "model_pin_sha256": model_pin_sha256,
        "materialized_input_sha256": materialized_sha256,
        "execution_authority": {
            "sfir4_acceptance_path": str(sfir4_acceptance_path.resolve()),
            "sfir4_acceptance_sha256": sfir4_acceptance_sha256,
            "four_link_acceptance_path": str(four_link_path.resolve()),
            "four_link_acceptance_sha256": four_link_sha256,
            "protocol_freeze_path": str(protocol_freeze_path.resolve()),
            "protocol_freeze_sha256": protocol_freeze_sha256,
        },
        "projection": projection,
    }
    return spec, bundle


def execute_prepared(
    *,
    spec: dict[str, Any],
    bundle: dict[str, Any],
    materialized_path: Path,
    output_path: Path,
    ledger_path: Path,
    provider: Any,
    objects: Any,
) -> dict[str, Any]:
    ledger = EvidenceLedger(ledger_path, cohort_id="gpu-successor-v2", run_tag="v6-sfir4-v2")
    budget = AuthorizedSpendBudget(campaign_id="gpu-successor-v2", hard_cap_usd="40")
    return V2Controller(
        provider=provider,
        objects=objects,
        ledger=ledger,
        budget=budget,
        limits=V2Limits(maximum_seconds=20_700, maximum_cost_usd=Decimal("38")),
    ).execute(spec=spec, input_path=materialized_path, bundle=bundle, output_path=output_path)


def environment_backend(args: argparse.Namespace) -> tuple[Any, Any]:
    """Construct real RunPod and R2 adapters only after every launch gate passes."""
    import base64
    import os

    import boto3
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from gpu_successor_r2 import S3CompatibleObjectTransport
    from gpu_successor_v2_runpod_backend import build_environment_transport

    access = os.environ.get("AKC_S3_ACCESS_KEY_ID")
    secret = os.environ.get("AKC_S3_SECRET_ACCESS_KEY")
    if not access or not secret:
        raise V2RuntimeError("scoped AKC S3/R2 credentials are absent")
    signing = os.environ.get("TAVONEL_TERMINAL_PRIVATE_KEY_B64", "")
    try:
        private = Ed25519PrivateKey.from_private_bytes(base64.b64decode(signing, validate=True))
        derived_public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        bundle_public = base64.b64decode(
            json.loads(args.worker_bundle.read_text(encoding="utf-8"))["terminal_public_key_b64"],
            validate=True,
        )
    except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise V2RuntimeError("ephemeral V2 signing material is invalid") from error
    if derived_public != bundle_public:
        raise V2RuntimeError("ephemeral V2 signing key does not match the frozen bundle")
    client = boto3.client(
        "s3",
        endpoint_url=args.r2_endpoint_url,
        region_name=args.r2_region,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
    )
    provider = build_environment_transport(
        runtime_protocol_path=args.runtime_protocol,
        worker_bundle_path_in_image=args.worker_bundle_path_in_image,
        model_path_in_image=args.model_path_in_image,
        model_manifest_path_in_image=args.model_manifest_path_in_image,
        tokenizer_path_in_image=args.tokenizer_path_in_image,
        tokenizer_manifest_path_in_image=args.tokenizer_manifest_path_in_image,
    )
    objects = S3CompatibleObjectTransport(
        client=client, bucket=args.r2_bucket, prefix=args.r2_prefix
    )
    return provider, objects


def main(
    argv: list[str] | None = None,
    backend_factory: Callable[[argparse.Namespace], tuple[Any, Any]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in (
        "sfir4-acceptance",
        "four-link",
        "materialized",
        "protocol-freeze",
        "worker-bundle",
        "rate-receipt",
    ):
        parser.add_argument("--" + flag, required=True, type=Path)
        parser.add_argument("--" + flag + "-sha256", required=True)
    parser.add_argument("--runtime-image-digest", required=True)
    parser.add_argument("--model-pin-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--runtime-protocol", type=Path, required=True)
    parser.add_argument("--worker-bundle-path-in-image", required=True)
    parser.add_argument("--model-path-in-image", required=True)
    parser.add_argument("--model-manifest-path-in-image", required=True)
    parser.add_argument("--tokenizer-path-in-image", required=True)
    parser.add_argument("--tokenizer-manifest-path-in-image", required=True)
    parser.add_argument("--r2-endpoint-url", required=True)
    parser.add_argument("--r2-bucket", required=True)
    parser.add_argument("--r2-region", default="auto")
    parser.add_argument("--r2-prefix", default="")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        spec, bundle = prepare_spec(
            sfir4_acceptance_path=args.sfir4_acceptance,
            sfir4_acceptance_sha256=args.sfir4_acceptance_sha256,
            four_link_path=args.four_link,
            four_link_sha256=args.four_link_sha256,
            materialized_path=args.materialized,
            materialized_sha256=args.materialized_sha256,
            protocol_freeze_path=args.protocol_freeze,
            protocol_freeze_sha256=args.protocol_freeze_sha256,
            worker_bundle_path=args.worker_bundle,
            worker_bundle_sha256=args.worker_bundle_sha256,
            rate_receipt_path=args.rate_receipt,
            rate_receipt_sha256=args.rate_receipt_sha256,
            runtime_image_digest=args.runtime_image_digest,
            model_pin_sha256=args.model_pin_sha256,
        )
        if not args.execute:
            print(json.dumps({"state": "READY_NO_PROVIDER_CALL", "spec": spec}, indent=2))
            return 0
        provider, objects = (backend_factory or environment_backend)(args)
        try:
            result = execute_prepared(
                spec=spec,
                bundle=bundle,
                materialized_path=args.materialized,
                output_path=args.output,
                ledger_path=args.ledger,
                provider=provider,
                objects=objects,
            )
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        print(json.dumps(result, indent=2))
        return 0
    except V2RuntimeError as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["environment_backend", "execute_prepared", "main", "prepare_spec"]
