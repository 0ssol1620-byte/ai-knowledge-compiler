#!/usr/bin/env python3
"""Run hard-200 with one R2 upload and bounded RunPod startup-host retries.

The verified v7 implementation supplies every immutable artifact, R2, GT-isolation,
control-plane, result-validation, and cleanup primitive.  This wrapper changes only
startup orchestration: it uploads the GT-free bundle once, rotates across the two
founder-authorized RunPod credentials when a Pod never reaches a runtime, and
continues qualification/inference only on the first runtime-positive Pod.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import secrets
import sys
import tarfile
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SCRATCH = ROOT / ".chatgpt2codex"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRATCH))

from runpod_curl_transport_v2 import RunPodCurlTransport  # noqa: E402
from runpod_registry_auth_v27 import read_labeled_secret  # noqa: E402

BASE_PATH = Path(__file__).with_name("run_stage1_v29_r2_v7_r2_verified.py")
_spec = importlib.util.spec_from_file_location("stage1_v7", BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Stage-1 v7 module cannot be loaded")
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)

STARTUP_TIMEOUT_SECONDS = 10 * 60
MAX_STARTUP_ATTEMPTS = 4
POLL_SECONDS = 10
RUNTIME_QUERY = """
query Stage1Runtime($podId: String!) {
  pod(input: { podId: $podId }) {
    id
    name
    desiredStatus
    runtime {
      uptimeInSeconds
      ports { privatePort publicPort type }
    }
  }
}
"""


def now() -> str:
    return base.now()


def candidate_transports(credential_file: Path) -> list[tuple[str, RunPodCurlTransport]]:
    candidates: list[tuple[str, RunPodCurlTransport]] = []
    for label in ("Runpod_B", "Runpod_A"):
        key = read_labeled_secret(credential_file, label)
        transport = RunPodCurlTransport(api_key=key)
        running = [
            pod for pod in transport.list_pods() if str(pod.get("desiredStatus", "")) == "RUNNING"
        ]
        if running:
            continue
        balance, spend = base.spend_state(transport)
        if balance < Decimal("3.00") or spend > Decimal("0.10"):
            continue
        candidates.append((label, transport))
    if not candidates:
        raise RuntimeError("no authorized RunPod credential passed Stage-1 preflight")
    return candidates


def runtime_snapshot(transport: RunPodCurlTransport, pod_id: str) -> dict[str, Any]:
    data = transport.graphql(query=RUNTIME_QUERY, variables={"podId": pod_id})
    pod = data.get("pod") if isinstance(data, dict) else None
    if not isinstance(pod, dict):
        return {"runtime_present": False, "desired_status": None}
    runtime = pod.get("runtime")
    result: dict[str, Any] = {
        "runtime_present": isinstance(runtime, dict),
        "desired_status": pod.get("desiredStatus"),
    }
    if isinstance(runtime, dict):
        result["uptime_seconds"] = int(runtime.get("uptimeInSeconds") or 0)
        result["ports"] = [
            {
                "privatePort": item.get("privatePort"),
                "publicPortPresent": item.get("publicPort") is not None,
                "type": item.get("type"),
            }
            for item in (runtime.get("ports") or [])
            if isinstance(item, dict)
        ]
    return result


def delete_and_verify(transport: RunPodCurlTransport, pod_id: str) -> bool:
    transport.delete_pod(pod_id)
    for _ in range(30):
        if transport.verify_deleted(pod_id):
            return True
        time.sleep(2)
    return False


def fresh_presigned(client: Any, bucket: str, key: str) -> str:
    return str(
        client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=2 * 60 * 60,
        )
    )


def build_payload(
    *,
    ready: dict[str, Any],
    bound: dict[str, Any],
    presigned: str,
    qualifier_b64: str,
    qualifier_sha: str,
    driver_b64: str,
    runner_b64: str,
    runner_sha: str,
    contract_b64: str,
    contract_sha: str,
    security_b64: str,
    model_b64: str,
    control_token: str,
    name: str,
) -> dict[str, Any]:
    bootstrap_command = (
        "mkdir -p /opt/tavonel/stage1 && "
        "printf '%s' \"$TAVONEL_STAGE1_DRIVER_GZ_B64\" | base64 -d | gzip -d > "
        "/[REDACTED].py && "
        "exec python3 /[REDACTED].py"
    )
    return {
        "name": name,
        "imageName": str(ready["base_image_digest"]),
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": [base.GPU],
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
            "TAVONEL_ASSEMBLY_ID": str(ready["assembly_id"]),
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
            "TAVONEL_STAGE1_BUNDLE_SHA256": str(bound["bundle"]["tar_sha256"]),
            "TAVONEL_STAGE1_BUNDLE_BYTES": str(base.BUNDLE.stat().st_size),
            "TAVONEL_STAGE1_CONTROL_TOKEN": control_token,
            "TAVONEL_MODEL_REVISION": str(bound["model"]["resolved_revision"]),
            "[REDACTED]": str(bound["model"]["model_safetensors_sha256"]),
        },
    }


def monitor_campaign(
    *,
    transport: RunPodCurlTransport,
    pod_id: str,
    control_token: str,
    run_dir: Path,
    r2_client: Any,
    bucket: str,
    r2_key: str,
    r2_state: dict[str, bool],
) -> dict[str, Any]:
    deadline = time.monotonic() + base.MAX_TOTAL_SECONDS
    last_state = ""
    while time.monotonic() < deadline:
        if transport.verify_deleted(pod_id):
            raise RuntimeError("Stage-1 runtime-positive Pod disappeared before completion")
        stage_error = base.proxy_json(pod_id, "stage1-error.json", control_token, port=8002)
        qualifier_error = base.proxy_json(
            pod_id, "qualifier-error-mirror.json", control_token, port=8002
        )
        if qualifier_error is not None:
            (run_dir / "qualifier-error-mirror.json").write_text(
                json.dumps(qualifier_error, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        qualifier_status = base.proxy_json(
            pod_id, "qualifier-status-mirror.json", control_token, port=8002
        )
        if qualifier_status is not None:
            (run_dir / "last-qualifier-status.json").write_text(
                json.dumps(qualifier_status, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if stage_error is not None:
            error_type = str(stage_error.get("error_type", "unknown"))
            message = str(stage_error.get("message", ""))[:500]
            raise RuntimeError(f"Stage-1 same-Pod driver failed: {error_type}: {message}")
        status = base.proxy_json(pod_id, "stage1-status.json", control_token, port=8002)
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
                and r2_state["uploaded"]
                and not r2_state["deleted"]
            ):
                r2_state["deleted"] = base.r2_delete_verify(r2_client, bucket, r2_key)
                if not r2_state["deleted"]:
                    raise RuntimeError("temporary Stage-1 R2 object deletion was not verified")
            if state == "done" and status.get("passed") is True:
                return status
        time.sleep(POLL_SECONDS)
    raise TimeoutError("Stage-1 runtime-positive campaign exceeded the 105-minute bound")


def fetch_and_validate_results(
    *,
    pod_id: str,
    control_token: str,
    run_dir: Path,
    done_payload: dict[str, Any],
    assembly_id: str,
    r2_deleted: bool,
    run_id: str,
) -> None:
    result_sha = str(done_payload.get("result_sha256", ""))
    result_bytes = int(done_payload.get("result_bytes", -1))
    if not base.SHA_RE.fullmatch(result_sha) or result_bytes <= 0:
        raise RuntimeError("Stage-1 done status lacks valid result identity")
    result_archive = run_dir / "stage1-results.tar.gz"
    http_status, _ = base.curl_get(
        f"https://{pod_id}-8002.proxy.runpod.net/stage1-results.tar.gz",
        token=control_token,
        output=result_archive,
        timeout=10 * 60,
    )
    if http_status != 200 or not result_archive.is_file():
        raise RuntimeError("Stage-1 result archive download failed")
    if (
        result_archive.stat().st_size != result_bytes
        or base.sha256_file(result_archive) != result_sha
    ):
        raise RuntimeError("Stage-1 result archive size/hash mismatch")
    base.validate_result_archive(result_archive)
    for filename in (
        "stage1-receipt.json",
        "assembly-verification.json",
        "qualification-detail.json",
    ):
        status_code, body = base.curl_get(
            f"https://{pod_id}-8002.proxy.runpod.net/{filename}",
            token=control_token,
            timeout=30,
        )
        if status_code != 200 or not body:
            raise RuntimeError(f"Stage-1 evidence fetch failed: {filename}")
        (run_dir / filename).write_bytes(body)
    stage_receipt = base.read_object(run_dir / "stage1-receipt.json")
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
    summary = base.read_object(summary_path)
    if (
        summary.get("ground_truth_mounted") is not False
        or int(summary.get("input_count", -1)) != 200
    ):
        raise RuntimeError("downloaded Stage-1 summary violated GT/input-count contract")
    local_receipt = {
        "schema": "tavonel.stage1-v29-host-retry-local-retrieval.v1",
        "completed_at": now(),
        "run_id": run_id,
        "assembly_id": assembly_id,
        "gpu_type": base.GPU,
        "input_count": 200,
        "ground_truth_mounted": False,
        "ground_truth_in_bundle": False,
        "result_archive_sha256": result_sha,
        "result_archive_bytes": result_bytes,
        "stage1_receipt_sha256": base.sha256_file(run_dir / "stage1-receipt.json"),
        "run_summary_sha256": base.sha256_file(summary_path),
        "r2_absence_verified_before_return": r2_deleted,
    }
    local_receipt["receipt_sha256"] = base.canonical_sha256(local_receipt)
    (run_dir / "retrieval-receipt.json").write_text(
        json.dumps(local_receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    bound = base.require_preconditions()
    bundle_sha = str(bound["bundle"]["tar_sha256"])
    run_id = uuid.uuid4().hex[:12]
    run_dir = base.OUT_ROOT / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    r2_key = f"tavonel/stage1/hard200/{uuid.uuid4().hex}.tar"
    r2_client, bucket = base.make_r2_client(args.credential_file.resolve(), args.env_file.resolve())
    r2_state = {"uploaded": False, "deleted": False}
    active_state_path = run_dir / "internal-active-state.json"
    active_pod: tuple[str, RunPodCurlTransport] | None = None
    attempts: list[dict[str, Any]] = []

    def write_active_state(*, pod_id: str | None = None, label: str | None = None) -> None:
        state = {
            "schema": "tavonel.stage1-v29-host-retry-active.v1",
            "updated_at": now(),
            "bucket": bucket,
            "r2_key": r2_key,
            "r2_uploaded": r2_state["uploaded"],
            "r2_deleted": r2_state["deleted"],
            "active_pod_id": pod_id,
            "active_credential_label": label,
        }
        active_state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    main_error: Exception | None = None
    cleanup: dict[str, Any] = {
        "pod_delete_attempted": False,
        "pod_absence_verified": False,
        "r2_delete_attempted": False,
        "r2_absence_verified": False,
    }
    try:
        base.r2_upload_bundle(r2_client, bucket, r2_key, bundle_sha)
        r2_state["uploaded"] = True
        write_active_state()
        candidates = candidate_transports(args.credential_file.resolve())
        qualifier_b64, qualifier_sha = base.gzip_b64(base.QUALIFIER)
        driver_b64, driver_sha = base.gzip_b64(base.DRIVER)
        runner_b64, runner_sha = base.gzip_b64(base.RUNNER)
        contract_b64, contract_sha = base.gzip_b64(base.INPUT_CONTRACT)
        security_b64, security_sha = base.canonical_b64(bound["security"])
        model_b64, model_sha = base.canonical_b64(bound["model"])
        ready = bound["ready"]
        if qualifier_sha != ready.get("bootstrap_sha256"):
            raise RuntimeError("fresh-Pod qualifier hash does not equal v29 READY bootstrap")
        assembly_id = str(ready["assembly_id"])

        successful: tuple[str, RunPodCurlTransport, str, str] | None = None
        for attempt_index in range(MAX_STARTUP_ATTEMPTS):
            label, transport = candidates[attempt_index % len(candidates)]
            if any(str(pod.get("desiredStatus", "")) == "RUNNING" for pod in transport.list_pods()):
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "credential_label": label,
                        "skipped": "running_pod_present",
                    }
                )
                continue
            balance, spend = base.spend_state(transport)
            if balance < Decimal("3.00") or spend > Decimal("0.10"):
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "credential_label": label,
                        "skipped": "balance_or_spend_gate",
                    }
                )
                continue
            control_token = secrets.token_urlsafe(32)
            token_sha = "sha256:" + hashlib.sha256(control_token.encode("utf-8")).hexdigest()
            name = f"tavonel-stage1-v29-{run_id}-h{attempt_index + 1}"
            payload = build_payload(
                ready=ready,
                bound=bound,
                presigned=fresh_presigned(r2_client, bucket, r2_key),
                qualifier_b64=qualifier_b64,
                qualifier_sha=qualifier_sha,
                driver_b64=driver_b64,
                runner_b64=runner_b64,
                runner_sha=runner_sha,
                contract_b64=contract_b64,
                contract_sha=contract_sha,
                security_b64=security_b64,
                model_b64=model_b64,
                control_token=control_token,
                name=name,
            )
            pod, reconciled = base.create_once_or_reconcile(transport, payload=payload, name=name)
            pod_id = str(pod.get("id", ""))
            if not pod_id:
                raise RuntimeError("Stage-1 retry Pod id is unavailable")
            rate = Decimal(str(pod.get("costPerHr", pod.get("adjustedCostPerHr", "0"))))
            if rate <= 0 or rate > base.MAX_HOURLY:
                if not delete_and_verify(transport, pod_id):
                    raise RuntimeError("over-ceiling Stage-1 retry Pod cleanup failed")
                raise RuntimeError("Stage-1 retry Pod hourly rate exceeds authorization")
            active_pod = (pod_id, transport)
            write_active_state(pod_id=pod_id, label=label)
            started = time.monotonic()
            runtime: dict[str, Any] | None = None
            while time.monotonic() - started < STARTUP_TIMEOUT_SECONDS:
                runtime = runtime_snapshot(transport, pod_id)
                if runtime.get("runtime_present") is True:
                    break
                if transport.verify_deleted(pod_id):
                    break
                time.sleep(POLL_SECONDS)
            elapsed = round(time.monotonic() - started, 3)
            runtime_present = bool(runtime and runtime.get("runtime_present") is True)
            attempt_receipt = {
                "attempt": attempt_index + 1,
                "credential_label": label,
                "pod_id": pod_id,
                "pod_name": name,
                "hourly_rate_usd": str(rate),
                "startup_elapsed_seconds": elapsed,
                "runtime_present": runtime_present,
                "runtime": runtime or {},
                "control_token_sha256": token_sha,
                "pod_create_reconciled_after_ambiguity": reconciled,
            }
            attempts.append(attempt_receipt)
            (run_dir / "startup-attempts.json").write_text(
                json.dumps(attempts, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if runtime_present:
                successful = (pod_id, transport, control_token, label)
                break
            if not delete_and_verify(transport, pod_id):
                raise RuntimeError("startup-outlier Stage-1 Pod cleanup failed")
            active_pod = None
            write_active_state()

        if successful is None:
            raise RuntimeError("all bounded Stage-1 startup host attempts failed before runtime")
        pod_id, transport, control_token, label = successful
        active_pod = (pod_id, transport)
        success_attempt = attempts[-1]
        create_receipt = {
            "schema": "tavonel.stage1-v29-host-retry-create.v1",
            "created_at": now(),
            "successful_credential_label": label,
            "pod_id": pod_id,
            "pod_name": success_attempt["pod_name"],
            "gpu_type": base.GPU,
            "hourly_rate_usd": success_attempt["hourly_rate_usd"],
            "hourly_ceiling_usd": str(base.MAX_HOURLY),
            "startup_attempt_count": len(attempts),
            "startup_attempts_sha256": base.canonical_sha256(attempts),
            "persistent_volume_gb": 0,
            "container_disk_gb": int(ready["container_disk_gb"]),
            "assembly_id": assembly_id,
            "qualifier_sha256": qualifier_sha,
            "stage1_driver_sha256": driver_sha,
            "stage1_runner_sha256": runner_sha,
            "input_contract_sha256": contract_sha,
            "security_receipt_sha256": security_sha,
            "model_receipt_sha256": model_sha,
            "bundle_sha256": bundle_sha,
            "bundle_bytes": base.BUNDLE.stat().st_size,
            "ground_truth_mounted": False,
            "ground_truth_in_bundle": False,
            "r2_uploaded_once": True,
            "secrets_persisted": False,
        }
        (run_dir / "create-receipt.json").write_text(
            json.dumps(create_receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        done_payload = monitor_campaign(
            transport=transport,
            pod_id=pod_id,
            control_token=control_token,
            run_dir=run_dir,
            r2_client=r2_client,
            bucket=bucket,
            r2_key=r2_key,
            r2_state=r2_state,
        )
        fetch_and_validate_results(
            pod_id=pod_id,
            control_token=control_token,
            run_dir=run_dir,
            done_payload=done_payload,
            assembly_id=assembly_id,
            r2_deleted=r2_state["deleted"],
            run_id=run_id,
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
        if active_pod is not None:
            pod_id, transport = active_pod
            cleanup["pod_delete_attempted"] = True
            try:
                cleanup["pod_absence_verified"] = delete_and_verify(transport, pod_id)
            except Exception as exc:
                errors.append("pod:" + type(exc).__name__)
        else:
            cleanup["pod_absence_verified"] = True
        if r2_state["uploaded"] and not r2_state["deleted"]:
            cleanup["r2_delete_attempted"] = True
            try:
                r2_state["deleted"] = base.r2_delete_verify(r2_client, bucket, r2_key)
                cleanup["r2_absence_verified"] = r2_state["deleted"]
                write_active_state(
                    pod_id=active_pod[0] if active_pod is not None else None,
                    label=None,
                )
            except Exception as exc:
                errors.append("r2:" + type(exc).__name__)
        elif r2_state["deleted"]:
            cleanup["r2_absence_verified"] = True
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
        if cleanup["pod_absence_verified"] and (
            not r2_state["uploaded"] or cleanup["r2_absence_verified"]
        ):
            active_state_path.unlink(missing_ok=True)
        if not cleanup["pod_absence_verified"]:
            raise RuntimeError("Stage-1 host-retry Pod cleanup was not verified")
        if r2_state["uploaded"] and not cleanup["r2_absence_verified"]:
            raise RuntimeError("Stage-1 host-retry R2 cleanup was not verified")


if __name__ == "__main__":
    raise SystemExit(main())
