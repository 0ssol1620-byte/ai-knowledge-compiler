#!/usr/bin/env python3
"""Run the sealed hard-200 cohort on a fresh, reverified v29 RTX4090 Pod.

A temporary Cloudflare R2 object carries only the GT-free source bundle.  The
fresh Pod replays the exact v29 assembly qualification before Stage-1 starts.
No benchmark ground truth or static cloud credentials are sent to the GPU.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = ROOT / ".chatgpt2codex"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRATCH))

from runpod_curl_transport_v2 import RunPodCurlTransport  # noqa: E402
from runpod_registry_auth_v27 import read_labeled_secret  # noqa: E402

from tools.release.relay_runpod_archive_via_r2 import (  # noqa: E402
    parse_env,
    parse_r2_credentials,
)

READY = SCRATCH / "formal-runtime-v29" / "ovisocr2-v29-assembly-ready.json"
FORMAL_QUAL_DIR = ROOT / "research" / "experiments" / "ASSURANCE-A-01" / "receipts"
FORMAL_QUAL_MATCHES = sorted(FORMAL_QUAL_DIR.glob("*v29*runtime-qualification.json"))
FORMAL_QUAL = (
    FORMAL_QUAL_MATCHES[0]
    if len(FORMAL_QUAL_MATCHES) == 1
    else FORMAL_QUAL_DIR / "__invalid-v29-runtime-qualification-selection__"
)
QUALIFIER = (
    ROOT
    / "infra"
    / "runpod"
    / "v6"
    / "images"
    / "ovisocr2-m1"
    / "assembly_qualification_http_v4.py"
)
DRIVER = (
    ROOT
    / "research"
    / "experiments"
    / "H1-STAGE1-200"
    / "scripts"
    / "stage1_same_pod_driver_v2_heartbeat.py"
)
RUNNER = (
    ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts" / "ovisocr2_stage1_hard200.py"
)
INPUT_CONTRACT = ROOT / "benchmark" / "runpod_eval" / "input_contract.py"
MODEL_RECEIPT = SCRATCH / "ovis-model-v26" / "snapshot-receipt.json"
SECURITY_RECEIPT = SCRATCH / "security-remediation-v28" / "linux-libc-dev-source-receipt.json"
BUNDLE = SCRATCH / "formal-runtime-v28" / "stage1-hard-200-source-only-v2.tar"
BUNDLE_RECEIPT = SCRATCH / "formal-runtime-v28" / "stage1-hard-200-source-only-v2.receipt.json"
OUT_ROOT = SCRATCH / "formal-runtime-v29" / "stage1"
PODS_URL = "https://rest.runpod.io/v1/pods"
GRAPHQL_URL = "https://api.runpod.io/graphql"
GPU = "NVIDIA GeForce RTX 4090"
MAX_HOURLY = Decimal("0.80")
MAX_TOTAL_SECONDS = 105 * 60
SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path.name}")
    return value


def gzip_b64(path: Path) -> tuple[str, str]:
    payload = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    encoded = base64.b64encode(gzip.compress(payload, compresslevel=9, mtime=0)).decode("ascii")
    return encoded, digest


def canonical_b64(value: dict[str, Any]) -> tuple[str, str]:
    payload = canonical_bytes(value)
    return base64.b64encode(payload).decode("ascii"), "sha256:" + hashlib.sha256(
        payload
    ).hexdigest()


def require_preconditions() -> dict[str, Any]:
    if len(FORMAL_QUAL_MATCHES) != 1:
        raise RuntimeError("expected exactly one v29 runtime-qualification receipt")
    for path in (
        READY,
        FORMAL_QUAL,
        QUALIFIER,
        DRIVER,
        RUNNER,
        INPUT_CONTRACT,
        MODEL_RECEIPT,
        SECURITY_RECEIPT,
        BUNDLE,
        BUNDLE_RECEIPT,
    ):
        if not path.is_file():
            raise RuntimeError(f"Stage-1 prerequisite is missing: {path.name}")
    ready = read_object(READY)
    formal = read_object(FORMAL_QUAL)
    model = read_object(MODEL_RECEIPT)
    security = read_object(SECURITY_RECEIPT)
    bundle = read_object(BUNDLE_RECEIPT)
    if ready.get("schema") != "tavonel.verified-runtime-assembly-ready.v1":
        raise RuntimeError("v29 READY schema drifted")
    if ready.get("qualification_state") != "READY":
        raise RuntimeError("v29 runtime is not READY")
    if ready.get("fresh_pod_must_reverify_assembly_before_public_benchmark") is not True:
        raise RuntimeError("v29 READY does not require fresh-Pod requalification")
    if ready.get("manual_ready_override_allowed") is not False:
        raise RuntimeError("v29 READY unexpectedly permits manual override")
    if int(ready.get("persistent_volume_gb", -1)) != 0:
        raise RuntimeError("v29 READY persistent-volume contract drifted")
    if int(ready.get("critical_vulnerability_count", -1)) != 0:
        raise RuntimeError("v29 READY does not bind CRITICAL=0")
    if formal.get("passed") is not True or formal.get("provider_cleanup_verified") is not True:
        raise RuntimeError("formal v29 qualification/cleanup is not PASS")
    if formal.get("assembly_id") != ready.get("assembly_id"):
        raise RuntimeError("v29 formal/READY assembly id mismatch")
    if formal.get("model_artifact_sha256") != ready.get("model_artifact_sha256"):
        raise RuntimeError("v29 formal/READY model identity mismatch")
    if model.get("repository") != "ATH-MaaS/OvisOCR2" or int(model.get("file_count", -1)) != 14:
        raise RuntimeError("Ovis model receipt drifted")
    if security.get("inrelease_packages_hash_match") is not True:
        raise RuntimeError("security receipt is not Ubuntu-index-bound")
    if bundle.get("input_count") != 200:
        raise RuntimeError("hard-200 bundle input count drifted")
    if (
        bundle.get("ground_truth_mounted") is not False
        or bundle.get("ground_truth_in_bundle") is not False
    ):
        raise RuntimeError("hard-200 bundle is not GT-free")
    if (
        bundle.get("all_input_hashes_verified") is not True
        or bundle.get("shard_parent_binding_verified") is not True
    ):
        raise RuntimeError("hard-200 bundle integrity receipt is not PASS")
    if bundle.get("tar_sha256") != sha256_file(BUNDLE):
        raise RuntimeError("hard-200 bundle hash drifted")
    stage1 = ready.get("stage1")
    if not isinstance(stage1, dict) or stage1.get("bundle_sha256") != bundle.get("tar_sha256"):
        raise RuntimeError("READY does not bind the sealed hard-200 bundle")
    return {
        "ready": ready,
        "formal": formal,
        "model": model,
        "security": security,
        "bundle": bundle,
    }


def parse_working_bucket(env_file: Path, client: Any) -> str:
    if env_file.is_file():
        values = parse_env(env_file)
        bucket = values.get("AKC_S3_BUCKET_WORKING", "").strip()
        if bucket and not bucket.startswith("replace-with-"):
            return bucket
    response = client.list_buckets()
    names = [str(item.get("Name", "")) for item in response.get("Buckets", []) if item.get("Name")]
    preferred = [
        name
        for name in names
        if any(token in name.lower() for token in ("working", "tavonel", "folynta", "akc"))
    ]
    if len(preferred) == 1:
        return preferred[0]
    if len(names) == 1:
        return names[0]
    raise RuntimeError("R2 working bucket cannot be resolved unambiguously")


def make_r2_client(credential_file: Path, env_file: Path) -> tuple[Any, str]:
    access_key, secret_key, endpoint = parse_r2_credentials(credential_file)
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    return client, parse_working_bucket(env_file, client)


def r2_upload_bundle(client: Any, bucket: str, key: str, expected_sha: str) -> str:
    client.upload_file(
        str(BUNDLE),
        bucket,
        key,
        ExtraArgs={"Metadata": {"sha256": expected_sha.removeprefix("sha256:")}},
        Config=TransferConfig(
            multipart_threshold=64 * 1024 * 1024,
            multipart_chunksize=64 * 1024 * 1024,
            max_concurrency=8,
            use_threads=True,
        ),
    )
    head = client.head_object(Bucket=bucket, Key=key)
    if int(head["ContentLength"]) != BUNDLE.stat().st_size:
        raise RuntimeError("temporary R2 Stage-1 object size drifted")
    if head.get("Metadata", {}).get("sha256") != expected_sha.removeprefix("sha256:"):
        raise RuntimeError("temporary R2 Stage-1 object hash metadata drifted")
    return str(
        client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )
    )


def r2_delete_verify(client: Any, bucket: str, key: str) -> bool:
    client.delete_object(Bucket=bucket, Key=key)
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return True
        raise
    return False


def read_runpod_key(credential_file: Path) -> tuple[str, str, RunPodCurlTransport]:
    candidates: list[tuple[int, str, str, RunPodCurlTransport]] = []
    for label in ("Runpod_B", "Runpod_A"):
        key = read_labeled_secret(credential_file, label)
        transport = RunPodCurlTransport(api_key=key)
        running = sum(
            1 for pod in transport.list_pods() if str(pod.get("desiredStatus", "")) == "RUNNING"
        )
        candidates.append((running, label, key, transport))
    eligible = [item for item in candidates if item[0] == 0]
    if not eligible:
        raise RuntimeError("no RunPod credential has zero running Pods")
    _, label, key, transport = sorted(eligible, key=lambda item: item[1] != "Runpod_A")[0]
    return label, key, transport


def spend_state(transport: RunPodCurlTransport) -> tuple[Decimal, Decimal]:
    query = "query Stage1Spend { myself { clientBalance currentSpendPerHr } }"
    payload = transport.graphql(query=query)
    myself = payload.get("myself") if isinstance(payload, dict) else None
    if not isinstance(myself, dict):
        raise RuntimeError("RunPod spend query returned invalid data")
    return Decimal(str(myself["clientBalance"])), Decimal(str(myself["currentSpendPerHr"]))


def create_once_or_reconcile(
    transport: RunPodCurlTransport,
    *,
    payload: dict[str, Any],
    name: str,
) -> tuple[dict[str, Any], bool]:
    if transport.reconcile_unique_pod(name) is not None:
        raise RuntimeError("Stage-1 Pod name already exists before create")
    try:
        return transport.create_pod(payload), False
    except RuntimeError as exc:
        if "transport failure" not in str(exc):
            raise
        reconciled = transport.reconcile_unique_pod(name)
        if reconciled is None:
            raise RuntimeError(
                "Stage-1 Pod create was transport-ambiguous and no Pod was reconciled; no retry"
            ) from exc
        return reconciled, True


def curl_get(
    url: str,
    *,
    token: str | None = None,
    output: Path | None = None,
    timeout: int = 30,
) -> tuple[int, bytes]:
    if not url.startswith("https://") or ".proxy.runpod.net/" not in url:
        raise RuntimeError("RunPod proxy URL escaped allowlist")
    curl = shutil.which("curl")
    if curl is None:
        raise RuntimeError("curl is unavailable")
    lines = [
        "silent",
        "show-error",
        "location",
        f"max-time = {timeout}",
        f'url = "{url}"',
        'header = "Accept: application/json"',
    ]
    if token:
        lines.append(f'header = "Authorization: Bearer {token}"')
    if output is not None:
        lines.append(f'output = "{output.resolve()}"')
    config = "\n".join(lines) + "\n"
    completed = subprocess.run(  # noqa: S603
        [str(Path(curl).resolve()), "--config", "-", "--write-out", "\n%{http_code}"],
        input=config.encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=timeout + 10,
    )
    if completed.returncode != 0:
        return 0, b""
    if output is not None:
        status_text = completed.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1:]
        status = int(status_text[0]) if status_text and status_text[0].isdigit() else -1
        return status, b""
    text = completed.stdout.decode("utf-8", errors="replace")
    body, _, status_text = text.rpartition("\n")
    status = int(status_text) if status_text.isdigit() else -1
    return status, body.encode("utf-8")


def proxy_json(pod_id: str, name: str, token: str | None = None) -> dict[str, Any] | None:
    status, body = curl_get(
        f"https://{pod_id}-8001.proxy.runpod.net/{name}",
        token=token,
        timeout=20,
    )
    if status != 200 or not body:
        return None
    value = json.loads(body.decode("utf-8"))
    return dict(value) if isinstance(value, dict) else None


def validate_result_archive(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise RuntimeError("Stage-1 result archive is empty")
        for member in members:
            name = member.name.replace("\\", "/")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or member.issym() or member.islnk():
                raise RuntimeError("Stage-1 result archive contains an unsafe member")
            lowered = name.lower()
            if (
                "ground_truth" in lowered
                or "ground-truth" in lowered
                or "/inputs/" in f"/{lowered}/"
            ):
                raise RuntimeError("Stage-1 result archive contains forbidden source/GT material")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    bound = require_preconditions()
    bundle_sha = str(bound["bundle"]["tar_sha256"])
    control_token = secrets.token_urlsafe(32)
    control_token_sha = "sha256:" + hashlib.sha256(control_token.encode("utf-8")).hexdigest()
    run_id = uuid.uuid4().hex[:12]
    run_dir = OUT_ROOT / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    r2_key = f"tavonel/stage1/hard200/{uuid.uuid4().hex}.tar"
    r2_client, bucket = make_r2_client(args.credential_file.resolve(), args.env_file.resolve())
    r2_uploaded = False
    r2_deleted = False
    pod_id: str | None = None
    transport: RunPodCurlTransport | None = None
    main_error: Exception | None = None
    cleanup: dict[str, Any] = {
        "pod_delete_attempted": False,
        "pod_absence_verified": False,
        "r2_delete_attempted": False,
        "r2_absence_verified": False,
    }
    try:
        presigned = r2_upload_bundle(r2_client, bucket, r2_key, bundle_sha)
        r2_uploaded = True
        label, _, transport = read_runpod_key(args.credential_file.resolve())
        balance, spend = spend_state(transport)
        if balance < Decimal("3.00") or spend > Decimal("0.10"):
            raise RuntimeError("RunPod balance/spend preflight is outside Stage-1 authorization")

        qualifier_b64, qualifier_sha = gzip_b64(QUALIFIER)
        driver_b64, driver_sha = gzip_b64(DRIVER)
        runner_b64, runner_sha = gzip_b64(RUNNER)
        contract_b64, contract_sha = gzip_b64(INPUT_CONTRACT)
        security_b64, security_receipt_sha = canonical_b64(bound["security"])
        model_b64, model_receipt_sha = canonical_b64(bound["model"])
        ready = bound["ready"]
        if qualifier_sha != ready.get("bootstrap_sha256"):
            raise RuntimeError("fresh-Pod qualifier hash does not equal v29 READY bootstrap")
        assembly_id = str(ready["assembly_id"])
        bootstrap_command = (
            "mkdir -p /opt/tavonel/stage1 && "
            "printf '%s' \"$TAVONEL_STAGE1_DRIVER_GZ_B64\" | base64 -d | gzip -d > "
            "/opt/tavonel/stage1/stage1_same_pod_driver_v2_heartbeat.py && "
            "exec python3 /opt/tavonel/stage1/stage1_same_pod_driver_v2_heartbeat.py"
        )
        name = f"tavonel-stage1-v29-{run_id}"
        payload = {
            "name": name,
            "imageName": str(ready["base_image_digest"]),
            "cloudType": "SECURE",
            "computeType": "GPU",
            "gpuTypeIds": [GPU],
            "gpuTypePriority": "availability",
            "gpuCount": 1,
            "containerDiskInGb": int(ready["container_disk_gb"]),
            "volumeInGb": 0,
            "ports": ["8001/http", "8002/http"],
            "interruptible": False,
            "allowedCudaVersions": ["12.8", "12.9"],
            "dockerEntrypoint": ["/bin/bash", "-lc", bootstrap_command],
            "env": {
                "FOLYNTA_QUALIFICATION_ONLY": "1",
                "HF_HOME": "/opt/tavonel/hf-cache",
                "TAVONEL_ASSEMBLY_ID": assembly_id,
                "TAVONEL_BASE_IMAGE_DIGEST": str(ready["base_image_digest"]),
                "TAVONEL_BOOTSTRAP_SHA256": qualifier_sha,
                "TAVONEL_SECURITY_RECEIPT_B64": security_b64,
                "TAVONEL_MODEL_RECEIPT_B64": model_b64,
                "TAVONEL_STAGE1_DRIVER_GZ_B64": driver_b64,
                "TAVONEL_QUALIFIER_GZ_B64": qualifier_b64,
                "TAVONEL_QUALIFIER_SHA256": qualifier_sha,
                "TAVONEL_STAGE1_RUNNER_GZ_B64": runner_b64,
                "TAVONEL_STAGE1_RUNNER_SHA256": runner_sha,
                "TAVONEL_INPUT_CONTRACT_GZ_B64": contract_b64,
                "TAVONEL_INPUT_CONTRACT_SHA256": contract_sha,
                "TAVONEL_STAGE1_BUNDLE_URL": presigned,
                "TAVONEL_STAGE1_BUNDLE_SHA256": bundle_sha,
                "TAVONEL_STAGE1_BUNDLE_BYTES": str(BUNDLE.stat().st_size),
                "TAVONEL_STAGE1_CONTROL_TOKEN": control_token,
                "TAVONEL_MODEL_REVISION": str(bound["model"]["resolved_revision"]),
                "TAVONEL_ARTIFACT_MANIFEST_SHA256": str(bound["model"]["model_safetensors_sha256"]),
            },
        }
        pod, reconciled = create_once_or_reconcile(transport, payload=payload, name=name)
        pod_id = str(pod.get("id", ""))
        if not pod_id:
            raise RuntimeError("Stage-1 Pod id is unavailable")
        rate = Decimal(str(pod.get("costPerHr", pod.get("adjustedCostPerHr", "0"))))
        if rate <= 0 or rate > MAX_HOURLY:
            raise RuntimeError("Stage-1 Pod hourly rate exceeds authorization")
        create_receipt = {
            "schema": "tavonel.stage1-v29-create.v1",
            "created_at": now(),
            "credential_label": label,
            "pod_id": pod_id,
            "pod_name": name,
            "gpu_type": GPU,
            "hourly_rate_usd": str(rate),
            "hourly_ceiling_usd": str(MAX_HOURLY),
            "persistent_volume_gb": 0,
            "container_disk_gb": int(ready["container_disk_gb"]),
            "assembly_id": assembly_id,
            "qualifier_sha256": qualifier_sha,
            "stage1_driver_sha256": driver_sha,
            "stage1_runner_sha256": runner_sha,
            "input_contract_sha256": contract_sha,
            "security_receipt_sha256": security_receipt_sha,
            "model_receipt_sha256": model_receipt_sha,
            "bundle_sha256": bundle_sha,
            "bundle_bytes": BUNDLE.stat().st_size,
            "control_token_sha256": control_token_sha,
            "ground_truth_mounted": False,
            "ground_truth_in_bundle": False,
            "r2_object_key_sha256": "sha256:" + hashlib.sha256(r2_key.encode("utf-8")).hexdigest(),
            "pod_create_reconciled_after_ambiguity": reconciled,
            "secrets_persisted": False,
        }
        (run_dir / "create-receipt.json").write_text(
            json.dumps(create_receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        deadline = time.monotonic() + MAX_TOTAL_SECONDS
        last_state = ""
        done_payload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if transport.verify_deleted(pod_id):
                raise RuntimeError("Stage-1 Pod disappeared before completion")
            qual_error = proxy_json(pod_id, "qualification-error.json")
            if qual_error is not None:
                raise RuntimeError(
                    "fresh-Pod v29 qualification failed: "
                    + str(qual_error.get("error_type", "unknown"))
                )
            stage_error = proxy_json(pod_id, "stage1-error.json", control_token)
            if stage_error is not None:
                raise RuntimeError(
                    "Stage-1 same-Pod driver failed: "
                    + str(stage_error.get("error_type", "unknown"))
                )
            status = proxy_json(pod_id, "stage1-status.json", control_token)
            if status is not None:
                state = str(status.get("state", ""))
                if state and state != last_state:
                    last_state = state
                    (run_dir / "last-stage1-status.json").write_text(
                        json.dumps(status, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                if (
                    state in {"bundle_verified", "inference", "done"}
                    and r2_uploaded
                    and not r2_deleted
                ):
                    cleanup["r2_delete_attempted"] = True
                    r2_deleted = r2_delete_verify(r2_client, bucket, r2_key)
                    cleanup["r2_absence_verified"] = r2_deleted
                    if not r2_deleted:
                        raise RuntimeError("temporary Stage-1 R2 object deletion was not verified")
                if state == "done" and status.get("passed") is True:
                    done_payload = status
                    break
            time.sleep(10)
        if done_payload is None:
            raise TimeoutError("Stage-1 same-Pod campaign exceeded the 105-minute bound")

        result_sha = str(done_payload.get("result_sha256", ""))
        result_bytes = int(done_payload.get("result_bytes", -1))
        if not SHA_RE.fullmatch(result_sha) or result_bytes <= 0:
            raise RuntimeError("Stage-1 done status lacks valid result identity")
        result_archive = run_dir / "stage1-results.tar.gz"
        http_status, _ = curl_get(
            f"https://{pod_id}-8001.proxy.runpod.net/stage1-results.tar.gz",
            token=control_token,
            output=result_archive,
            timeout=10 * 60,
        )
        if http_status != 200 or not result_archive.is_file():
            raise RuntimeError("Stage-1 result archive download failed")
        if (
            result_archive.stat().st_size != result_bytes
            or sha256_file(result_archive) != result_sha
        ):
            raise RuntimeError("Stage-1 result archive size/hash mismatch")
        validate_result_archive(result_archive)
        for filename in (
            "stage1-receipt.json",
            "assembly-verification.json",
            "qualification-detail.json",
        ):
            status_code, body = curl_get(
                f"https://{pod_id}-8001.proxy.runpod.net/{filename}",
                token=control_token,
                timeout=30,
            )
            if status_code != 200 or not body:
                raise RuntimeError(f"Stage-1 evidence fetch failed: {filename}")
            (run_dir / filename).write_bytes(body)
        stage_receipt = read_object(run_dir / "stage1-receipt.json")
        if (
            stage_receipt.get("ground_truth_mounted") is not False
            or stage_receipt.get("ground_truth_in_bundle") is not False
        ):
            raise RuntimeError("Stage-1 receipt violated GT isolation")
        if int(stage_receipt.get("input_count", -1)) != 200:
            raise RuntimeError("Stage-1 receipt input count drifted")
        if stage_receipt.get("assembly_id") != assembly_id:
            raise RuntimeError("same-Pod Stage-1 assembly id drifted")
        extract = run_dir / "results"
        extract.mkdir()
        with tarfile.open(result_archive, "r:gz") as archive:
            archive.extractall(extract, filter="data")
        summary_path = extract / "output" / "run-summary.json"
        if not summary_path.is_file():
            raise RuntimeError("Stage-1 downloaded result lacks run-summary.json")
        summary = read_object(summary_path)
        if (
            summary.get("ground_truth_mounted") is not False
            or int(summary.get("input_count", -1)) != 200
        ):
            raise RuntimeError("downloaded Stage-1 summary violated GT/input-count contract")
        local_receipt = {
            "schema": "tavonel.stage1-v29-local-retrieval.v1",
            "completed_at": now(),
            "run_id": run_id,
            "assembly_id": assembly_id,
            "gpu_type": GPU,
            "input_count": 200,
            "ground_truth_mounted": False,
            "ground_truth_in_bundle": False,
            "result_archive_sha256": result_sha,
            "result_archive_bytes": result_bytes,
            "stage1_receipt_sha256": sha256_file(run_dir / "stage1-receipt.json"),
            "run_summary_sha256": sha256_file(summary_path),
            "r2_object_deleted_before_result_retrieval": r2_deleted,
        }
        local_receipt["receipt_sha256"] = canonical_sha256(local_receipt)
        (run_dir / "retrieval-receipt.json").write_text(
            json.dumps(local_receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {"status": "PASS", "run_dir": run_dir.relative_to(ROOT).as_posix()}, sort_keys=True
            )
        )
        return 0
    except Exception as exc:
        main_error = exc
        raise
    finally:
        errors: list[str] = []
        if pod_id is not None and transport is not None:
            cleanup["pod_delete_attempted"] = True
            try:
                transport.delete_pod(pod_id)
                for _ in range(30):
                    if transport.verify_deleted(pod_id):
                        cleanup["pod_absence_verified"] = True
                        break
                    time.sleep(3)
            except Exception as exc:
                errors.append("pod:" + type(exc).__name__)
        if r2_uploaded and not r2_deleted:
            cleanup["r2_delete_attempted"] = True
            try:
                r2_deleted = r2_delete_verify(r2_client, bucket, r2_key)
                cleanup["r2_absence_verified"] = r2_deleted
            except Exception as exc:
                errors.append("r2:" + type(exc).__name__)
        cleanup.update(
            {
                "completed_at": now(),
                "main_error_type": type(main_error).__name__ if main_error else None,
                "cleanup_errors": errors,
            }
        )
        (run_dir / "cleanup-receipt.json").write_text(
            json.dumps(cleanup, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if pod_id is not None and not cleanup["pod_absence_verified"]:
            raise RuntimeError("Stage-1 Pod cleanup was not verified")
        if r2_uploaded and not cleanup["r2_absence_verified"]:
            raise RuntimeError("Stage-1 R2 cleanup was not verified")


if __name__ == "__main__":
    raise SystemExit(main())
