#!/usr/bin/env python3
"""Run the frozen SEC source-fact crops on isolated, pinned Arena workers.

The command is validation-only unless ``--execute`` is supplied. It never reads
the sealed fact values. Provider outputs and receipts live under an ignored
scratch directory until a separate freeze step hashes them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_BENCHMARK_ID = "TAVONEL-SEC-SOURCE-FACT-HOLDOUT-20260910-V1"
LEGACY_TRANSPORT_BENCHMARK = "olmocr"
PRIMARY_MODELS = ("mineru_vlm", "paddleocr_vl_1_6")
ADJUDICATOR_MODELS = ("ovisocr2",)
ALL_MODELS = PRIMARY_MODELS + ADJUDICATOR_MODELS
CAMPAIGN_ID = "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1"
MAX_SPEND_USD = 5.0
MAX_CALLS = 72
POLL_SECONDS = 20.0
BOOT_DEADLINE_SECONDS = 2_700.0


class HoldoutRunError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_bytes(payload.encode("utf-8"))


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def append_jsonl(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HoldoutRunError(f"{path} must contain a JSON object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise HoldoutRunError(f"{path}:{number} must contain a JSON object")
        rows.append(value)
    return rows


def bare_sha(value: str) -> str:
    return value.removeprefix("sha256:")


def install_arena(arena_root: Path) -> None:
    if not (arena_root / "arena" / "provider" / "runpod_v1.py").is_file():
        raise HoldoutRunError(f"Arena provider code is absent under {arena_root}")
    sys.path.insert(0, str(arena_root))


def load_and_validate_inputs(
    *, input_root: Path, binding_path: Path, authorization_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    binding = read_json(binding_path)
    authorization = read_json(authorization_path)
    if binding.get("benchmark_id") != authorization.get("benchmark_id"):
        raise HoldoutRunError("binding/authorization benchmark_id mismatch")
    if authorization.get("production_promotion") is not False:
        raise HoldoutRunError("authorization must keep production_promotion false")
    authorized_spend = float(authorization.get("maximum_new_gpu_spend_usd", 0))
    authorized_calls = int(authorization.get("maximum_model_region_calls", 0))
    if not 0 < authorized_spend <= MAX_SPEND_USD:
        raise HoldoutRunError("authorization spend ceiling exceeds the harness hard cap")
    if not 0 < authorized_calls <= MAX_CALLS:
        raise HoldoutRunError("authorization call ceiling exceeds the harness hard cap")
    if float(binding.get("maximum_new_gpu_spend_usd", 0)) > authorized_spend:
        raise HoldoutRunError("binding spend ceiling exceeds authorization")
    if int(binding.get("maximum_model_region_calls", 0)) > authorized_calls:
        raise HoldoutRunError("binding call ceiling exceeds authorization")
    source_truth_opened = bool(binding.get("source_truth_opened", False))
    if bool(authorization.get("source_truth_opened", False)) != source_truth_opened:
        raise HoldoutRunError("binding/authorization truth-state mismatch")
    expiry = datetime.fromisoformat(str(authorization["expires_at"]).replace("Z", "+00:00"))
    if datetime.now(tz=UTC) >= expiry:
        raise HoldoutRunError("RunPod authorization expired")

    manifest_path = input_root / "RUNTIME_MANIFEST.jsonl"
    if sha256_file(manifest_path) != binding["capture_runtime_manifest_sha256"]:
        raise HoldoutRunError("capture runtime manifest hash drift")
    rows = read_jsonl(manifest_path)
    if len(rows) != int(binding["selected_regions"]):
        raise HoldoutRunError("capture denominator drift")
    expected = {str(row[0]): str(row[1]) for row in binding["input_pngs"]}
    actual = {str(row["region_id"]): str(row["input_png_sha256"]) for row in rows}
    if actual != expected:
        raise HoldoutRunError("input PNG manifest differs from the pre-execution binding")
    forbidden = {"value", "normalized_visible_value", "fact_value", "ground_truth", "truth"}
    for row in rows:
        if forbidden.intersection(row):
            raise HoldoutRunError(f"runtime manifest exposes truth for {row.get('region_id')}")
        path = input_root / str(row["input_relative_path"])
        if sha256_file(path) != row["input_png_sha256"]:
            raise HoldoutRunError(f"input PNG hash drift for {row['region_id']}")
    return binding, rows, authorization


def validate_model_binding(arena_root: Path, binding: dict[str, Any], model: str) -> dict[str, Any]:
    model_binding = dict(binding["models"][model])
    runtime_path = arena_root / "runtimes" / model / "runtime.json"
    if sha256_file(runtime_path) != model_binding["runtime_json_sha256"]:
        raise HoldoutRunError(f"{model}: runtime.json hash drift")
    runtime = read_json(runtime_path)
    if runtime.get("model_revision") != model_binding["model_revision"]:
        raise HoldoutRunError(f"{model}: model revision drift")
    if runtime.get("prompt_id") != model_binding["prompt_id"]:
        raise HoldoutRunError(f"{model}: prompt id drift")
    if (
        canonical_sha256(runtime.get("inference_config"))
        != model_binding["inference_config_sha256"]
    ):
        raise HoldoutRunError(f"{model}: inference config hash drift")
    bundle_path = arena_root / "bundles" / model / "arena-bundle.tar.gz"
    if sha256_file(bundle_path) != model_binding["bundle_sha256"]:
        raise HoldoutRunError(f"{model}: local bundle hash drift")
    return runtime


def verify_remote_bundles(
    arena_root: Path, binding: dict[str, Any], models: tuple[str, ...], receipt_dir: Path
) -> None:
    from arena.provider.r2 import BUCKET_NAME, R2Client
    from arena.provider.secrets import r2_credentials

    client = R2Client(r2_credentials(block="account"), bucket=BUCKET_NAME, execute=True)
    access = client.preflight_access()
    if access.detail.get("bucket_state") != "exists":
        raise HoldoutRunError(f"R2 preflight failed: {access.detail.get('bucket_state')}")
    append_jsonl(receipt_dir / "r2.jsonl", access.to_dict())
    for model in models:
        item = binding["models"][model]
        observed = client.object_sha256(str(item["r2_key"]))
        if observed != item["bundle_sha256"]:
            raise HoldoutRunError(f"{model}: R2 bundle hash {observed} does not match binding")
    written = read_jsonl(receipt_dir / "r2.jsonl") if (receipt_dir / "r2.jsonl").is_file() else []
    known = {row.get("request_sha256") for row in written}
    for receipt in client.receipts:
        value = receipt.to_dict()
        if value.get("request_sha256") not in known:
            append_jsonl(receipt_dir / "r2.jsonl", value)


def select_models(choice: str) -> tuple[str, ...]:
    if choice == "primary":
        return PRIMARY_MODELS
    if choice == "adjudicator":
        return ADJUDICATOR_MODELS
    if choice == "all":
        return ALL_MODELS
    raise HoldoutRunError(f"unknown model set {choice}")


def adjudication_rows(
    here: Path, rows: list[dict[str, Any]], benchmark_id: str
) -> list[dict[str, Any]]:
    decision = read_json(here / "SEC_SOURCE_FACT_PRIMARY_DECISION_BINDING.json")
    if decision.get("benchmark_id") != benchmark_id:
        raise HoldoutRunError("primary decision binding benchmark mismatch")
    if decision.get("sealed_truth_opened") is not False:
        raise HoldoutRunError("primary decision binding crossed the truth boundary")
    region_ids = [str(value) for value in decision.get("adjudication_region_ids", [])]
    if canonical_sha256(region_ids) != decision.get("adjudication_region_ids_sha256"):
        raise HoldoutRunError("adjudication region-id hash drift")
    by_id = {str(row["region_id"]): row for row in rows}
    if len(region_ids) != int(decision.get("adjudication_count", -1)):
        raise HoldoutRunError("adjudication denominator drift")
    missing = [region_id for region_id in region_ids if region_id not in by_id]
    if missing:
        raise HoldoutRunError(f"adjudication ids missing from input manifest: {missing}")
    return [by_id[region_id] for region_id in region_ids]


def run_model(
    *,
    arena_root: Path,
    input_root: Path,
    output_root: Path,
    binding: dict[str, Any],
    rows: list[dict[str, Any]],
    model: str,
    benchmark_id: str,
    source_truth_opened: bool,
    hourly_rate: float,
    deadline_monotonic: float,
) -> dict[str, Any]:
    from arena.controller.provision import allowed_cuda_versions
    from arena.provider.r2 import BUCKET_NAME, R2Client
    from arena.provider.runpod_pods import ProviderReceipt
    from arena.provider.runpod_v1 import PodV1, RunPodV1Client
    from arena.provider.secrets import r2_credentials, runpod_api_key, worker_bearer
    from arena.provider.worker_client import (
        RunRequest,
        WorkerClient,
        WorkerError,
        worker_base_url,
    )

    runtime = read_json(arena_root / "runtimes" / model / "runtime.json")
    model_binding = binding["models"][model]
    model_dir = output_root / model
    receipt_dir = model_dir / "provider-receipts"
    raw_dir = model_dir / "raw"
    canonical_dir = model_dir / "canonical"
    for directory in (receipt_dir, raw_dir, canonical_dir):
        directory.mkdir(parents=True, exist_ok=True)
    if (model_dir / "COMPLETE.json").exists():
        raise HoldoutRunError(f"{model}: output already complete; refusing to overwrite")

    token = worker_bearer(secrets.token_urlsafe(48))
    r2 = R2Client(r2_credentials(block="account"), bucket=BUCKET_NAME, execute=True)
    signed_url = r2.presign_get(str(model_binding["r2_key"]), expires_seconds=2 * 3600)
    bundle_secret = worker_bearer(signed_url)
    bundle_sha = bare_sha(str(model_binding["bundle_sha256"]))
    name_suffix = hashlib.sha256(benchmark_id.encode("utf-8")).hexdigest()[:8]
    pod_name = f"arena-{model.replace('_', '-')}-sec-{name_suffix}"
    from arena.provider.runpod_pods import PodSpec

    spec = PodSpec(
        name=pod_name,
        image_name=str(runtime["base_image"]),
        gpu_type_ids=tuple(str(value) for value in runtime["gpu_pool_priority"]),
        model_key=model,
        model_revision=str(runtime["model_revision"]),
        runtime_mode="bootstrap",
        image_digest=f"bootstrap:sha256:{bundle_sha}",
        cloud_type="SECURE",
        gpu_count=int(runtime.get("gpu_count_min", 1)),
        container_disk_gb=80,
        allowed_cuda_versions=allowed_cuda_versions(str(runtime["min_cuda_version"])),
        max_lifetime_hours=1,
        campaign_id=CAMPAIGN_ID,
        prompt_id=str(runtime["prompt_id"]),
        worker_token=token,
        bundle_url=bundle_secret,
        bundle_sha256=bundle_sha,
        extra_env={"TAVONEL_EXECUTION_LABEL": benchmark_id.lower()},
    )
    client = RunPodV1Client(
        key=runpod_api_key(), execute=True, campaign_id=CAMPAIGN_ID, receipts_dir=receipt_dir
    )
    pod_id: str | None = None
    started = time.monotonic()
    started_at = utc_now()
    results: list[dict[str, Any]] = []
    teardown_errors: list[str] = []
    pod_summary: dict[str, Any] = {}
    provider_hourly_rate = hourly_rate
    try:
        listed = client.list_pods()
        if isinstance(listed, ProviderReceipt):
            raise HoldoutRunError(f"{model}: live pod list returned a dry receipt")
        if any(pod.name == pod_name and pod.is_live for pod in listed):
            raise HoldoutRunError(f"{model}: a live pod already uses the holdout name")
        created = client.create_pod(spec)
        if isinstance(created, ProviderReceipt):
            raise HoldoutRunError(f"{model}: live create unexpectedly returned a dry receipt")
        if not isinstance(created, PodV1):
            raise HoldoutRunError(f"{model}: provider returned an unknown pod record")
        pod_id = created.pod_id
        pod_summary = created.to_summary()
        if created.cost_usd_per_hour > 0:
            provider_hourly_rate = created.cost_usd_per_hour
        print(f"[{model}] pod {pod_id} created on {created.gpu_type_id or 'pending'}", flush=True)

        worker = WorkerClient(
            worker_base_url(pod_id),
            bearer=token,
            timeouts={"ready": 12.0, "provenance": 30.0, "run": 930.0, "drain": 30.0},
        )
        ready: dict[str, Any] | None = None
        next_notice = 0.0
        while time.monotonic() < min(deadline_monotonic, started + BOOT_DEADLINE_SECONDS):
            pod = client.get_pod(pod_id, persist_receipt=False)
            if pod is None:
                raise HoldoutRunError(f"{model}: pod disappeared before readiness")
            if isinstance(pod, PodV1) and pod.desired_status in {"EXITED", "TERMINATED"}:
                raise HoldoutRunError(f"{model}: pod entered {pod.desired_status} before readiness")
            try:
                candidate = dict(worker.ready())
                if candidate.get("stage") == "READY":
                    ready = candidate
                    break
            except WorkerError:
                pass
            elapsed = time.monotonic() - started
            if elapsed >= next_notice:
                print(f"[{model}] loading ({elapsed:.0f}s)", flush=True)
                next_notice = elapsed + 60.0
            time.sleep(POLL_SECONDS)
        if ready is None:
            raise HoldoutRunError(f"{model}: readiness deadline exceeded")
        print(f"[{model}] READY after {time.monotonic() - started:.1f}s", flush=True)
        provenance = dict(worker.provenance())
        atomic_json(model_dir / "PROVENANCE.json", provenance)

        for index, row in enumerate(rows, 1):
            if time.monotonic() >= deadline_monotonic:
                raise HoldoutRunError("overall holdout deadline exceeded")
            region_id = str(row["region_id"])
            image_path = input_root / str(row["input_relative_path"])
            image_bytes = image_path.read_bytes()
            job_material = "\0".join(
                (benchmark_id, model, region_id, str(row["input_png_sha256"]), bundle_sha)
            )
            request = RunRequest(
                campaign_id=CAMPAIGN_ID,
                inference_job_id=hashlib.sha256(job_material.encode("utf-8")).hexdigest(),
                sample_id=f"olmocr:sec-source-fact/{region_id}#p0",
                case_key=region_id,
                benchmark=LEGACY_TRANSPORT_BENCHMARK,
                source_sha256=str(row["input_png_sha256"]),
                image_bytes=image_bytes,
                width=int(row["input_width_px"]),
                height=int(row["input_height_px"]),
                prompt_id=str(model_binding["prompt_id"]),
                prompt_sha256=str(model_binding["prompt_sha256"]),
                inference_config_sha256=str(model_binding["inference_config_sha256"]),
                job_kind="recovery",
                timeout_seconds=min(600, int(runtime["per_page_timeout_seconds"])),
                metadata={
                    "benchmark_id": benchmark_id,
                    "authority": "SEC EDGAR primary Inline XBRL filing HTML",
                    "ticker": str(row["ticker"]),
                    "cik": str(row["cik"]),
                    "accession": str(row["accession"]),
                    "filing_html_sha256": str(row["filing_html_sha256"]),
                    "fragment_sha256": str(row["fragment_sha256"]),
                    "target_bbox1000": list(row["target_bbox1000"]),
                    "truth_withheld_from_model": True,
                    "source_truth_opened_by_operator": source_truth_opened,
                },
            )
            response = worker.run(request)
            if (
                response.model_key != model
                or response.model_revision != model_binding["model_revision"]
            ):
                raise HoldoutRunError(f"{model}: worker identity mismatch on {region_id}")
            expected_runtime = f"bootstrap:sha256:{bundle_sha}"
            if response.runtime_image_digest != expected_runtime:
                raise HoldoutRunError(f"{model}: runtime digest mismatch on {region_id}")
            raw_path = raw_dir / f"{region_id}.txt"
            canonical_path = canonical_dir / f"{region_id}.md"
            raw_path.write_text(response.raw_text, encoding="utf-8", newline="\n")
            canonical_path.write_text(response.canonical_markdown, encoding="utf-8", newline="\n")
            receipt = {
                "schema": "tavonel.sec_source_fact_model_output.v1",
                "benchmark_id": benchmark_id,
                "transport_benchmark_enum": LEGACY_TRANSPORT_BENCHMARK,
                "region_id": region_id,
                "ticker": row["ticker"],
                "model_key": model,
                "model_revision": response.model_revision,
                "runtime_image_digest": response.runtime_image_digest,
                "status": response.status,
                "error_class": response.error_class,
                "semantic_error_class": response.semantic_error_class,
                "raw_path": raw_path.relative_to(output_root).as_posix(),
                "raw_sha256": sha256_file(raw_path),
                "canonical_path": canonical_path.relative_to(output_root).as_posix(),
                "canonical_sha256": sha256_file(canonical_path),
                "timings_ms": dict(response.timings_ms),
                "peak_vram_mb": response.peak_vram_mb,
                "output_chars": response.output_chars,
                "warnings": list(response.warnings),
                "truth_opened": source_truth_opened,
            }
            append_jsonl(model_dir / "outputs.jsonl", receipt)
            results.append(receipt)
            print(
                f"[{model}] {index:02d}/{len(rows)} {region_id} {response.status} "
                f"{int(response.timings_ms.get('total_ms', 0))}ms",
                flush=True,
            )
        try:
            worker.drain()
        except WorkerError as exc:
            teardown_errors.append(f"drain: {type(exc).__name__}")
    finally:
        if pod_id is not None:
            try:
                pod = client.get_pod(pod_id, persist_receipt=True)
                if isinstance(pod, PodV1):
                    pod_summary = pod.to_summary()
            except Exception as exc:  # teardown keeps going
                teardown_errors.append(f"final_get: {type(exc).__name__}")
            try:
                client.stop_pod(pod_id)
            except Exception as exc:
                teardown_errors.append(f"stop: {type(exc).__name__}")
            try:
                client.delete_pod(pod_id)
            except Exception as exc:
                teardown_errors.append(f"delete: {type(exc).__name__}")
            gone = False
            last_probe_error: str | None = None
            for _ in range(12):
                try:
                    if client.get_pod(pod_id, persist_receipt=False) is None:
                        gone = True
                        break
                except Exception as exc:
                    last_probe_error = type(exc).__name__
                time.sleep(5.0)
            if not gone:
                teardown_errors.append("pod_not_confirmed_gone")
                if last_probe_error is not None:
                    teardown_errors.append(f"pod_delete_probe: {last_probe_error}")
        client.close()

    elapsed = time.monotonic() - started
    complete = {
        "schema": "tavonel.sec_source_fact_model_run.v1",
        "benchmark_id": benchmark_id,
        "model_key": model,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": round(elapsed, 3),
        "conservative_hourly_rate_usd": hourly_rate,
        "provider_hourly_rate_usd": provider_hourly_rate,
        "estimated_actual_gpu_cost_usd": round(
            provider_hourly_rate * elapsed / 3600.0, 6
        ),
        "reserved_one_hour_ceiling_usd": hourly_rate,
        "pod": pod_summary,
        "pod_id": pod_id,
        "output_count": len(results),
        "success_count": sum(row["status"] == "SUCCESS" for row in results),
        "teardown_errors": teardown_errors,
        "pod_deleted": "pod_not_confirmed_gone" not in teardown_errors,
        "truth_opened": source_truth_opened,
    }
    atomic_json(model_dir / "COMPLETE.json", complete)
    if len(results) != len(rows) or teardown_errors:
        raise HoldoutRunError(f"{model}: run or teardown incomplete: {complete}")
    return complete


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arena-root",
        type=Path,
        default=Path("D:/CodexProjects/ai-knowledge-compiler/research/model_arena_20260903"),
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path(".chatgpt2codex/sec-source-fact-crops-20260910-v2"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".chatgpt2codex/sec-source-fact-runpod-20260910-v1"),
    )
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--model-set", choices=("primary", "adjudicator", "all"), default="primary")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    arena_root = args.arena_root.resolve()
    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    binding_path = (
        args.binding.resolve()
        if args.binding is not None
        else here / "SEC_SOURCE_FACT_RUNPOD_BINDING.json"
    )
    authorization_path = (
        args.authorization.resolve()
        if args.authorization is not None
        else here / "SEC_SOURCE_FACT_RUNPOD_AUTHORIZATION.json"
    )
    binding, rows, authorization = load_and_validate_inputs(
        input_root=input_root,
        binding_path=binding_path,
        authorization_path=authorization_path,
    )
    benchmark_id = str(binding.get("benchmark_id", DEFAULT_BENCHMARK_ID))
    source_truth_opened = bool(binding.get("source_truth_opened", False))
    models = select_models(args.model_set)
    authorized_models = {str(value) for value in authorization.get("model_keys", [])}
    if not set(models).issubset(authorized_models):
        raise HoldoutRunError("selected model set exceeds authorization")
    if args.model_set == "adjudicator":
        rows = adjudication_rows(here, rows, benchmark_id)
    selected_calls = len(rows) * len(models)
    if selected_calls > int(authorization["maximum_model_region_calls"]):
        raise HoldoutRunError("selected model set exceeds the frozen call ceiling")
    install_arena(arena_root)
    for model in models:
        validate_model_binding(arena_root, binding, model)

    summary = {
        "benchmark_id": benchmark_id,
        "mode": "execute" if args.execute else "validation_only",
        "models": list(models),
        "regions": len(rows),
        "model_region_calls": len(rows) * len(models),
        "binding_sha256": sha256_file(binding_path),
        "authorization_sha256": sha256_file(authorization_path),
        "runtime_manifest_sha256": sha256_file(input_root / "RUNTIME_MANIFEST.jsonl"),
        "source_truth_opened": source_truth_opened,
    }
    if not args.execute:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if output_root.exists() and any(output_root.iterdir()):
        raise HoldoutRunError(f"output root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    atomic_json(output_root / "EXECUTION_START.json", {**summary, "started_at": utc_now()})
    receipt_dir = output_root / "provider-receipts"
    verify_remote_bundles(arena_root, binding, models, receipt_dir)

    from arena.provider.runpod_pods import PriceSnapshot, ProviderReceipt, RunPodPodsClient
    from arena.provider.secrets import runpod_api_key

    price_client = RunPodPodsClient(
        key=runpod_api_key(), execute=True, receipts_dir=receipt_dir, campaign_id=CAMPAIGN_ID
    )
    try:
        # The live v2 catalog currently rejects its former ``cloud`` query
        # parameter with HTTP 400. Fetch the complete read-only catalog and
        # select the SECURE rate from each immutable row below.
        snapshot = price_client.catalog_gpus()
        if isinstance(snapshot, ProviderReceipt) or not isinstance(snapshot, PriceSnapshot):
            raise HoldoutRunError("live catalog request did not return a price snapshot")
    finally:
        price_client.close()
    rates: dict[str, float] = {}
    reserved = 0.0
    for model in models:
        runtime = read_json(arena_root / "runtimes" / model / "runtime.json")
        priced: list[float] = []
        for gpu in runtime["gpu_pool_priority"]:
            rate = snapshot.row(str(gpu)).rate_for("SECURE")
            if rate is not None:
                priced.append(float(rate))
        if not priced:
            raise HoldoutRunError(f"{model}: no SECURE price in live catalog")
        rates[model] = max(priced)
        reserved += rates[model]
    if reserved > float(authorization["maximum_new_gpu_spend_usd"]):
        raise HoldoutRunError(f"one-hour pod ceilings ${reserved:.4f} exceed authorization")
    print(f"validated {len(rows)} frozen crops; one-hour GPU ceiling ${reserved:.4f}", flush=True)

    deadline = time.monotonic() + int(binding["overall_deadline_seconds"])
    completed: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(models), thread_name_prefix="sec-holdout") as pool:
        futures = {
            pool.submit(
                run_model,
                arena_root=arena_root,
                input_root=input_root,
                output_root=output_root,
                binding=binding,
                rows=rows,
                model=model,
                benchmark_id=benchmark_id,
                source_truth_opened=source_truth_opened,
                hourly_rate=rates[model],
                deadline_monotonic=deadline,
            ): model
            for model in models
        }
        for future in as_completed(futures):
            model = futures[future]
            try:
                completed.append(future.result())
            except Exception as exc:
                errors.append(f"{model}: {type(exc).__name__}: {exc}")
                print(errors[-1], file=sys.stderr, flush=True)

    result = {
        **summary,
        "finished_at": utc_now(),
        "reserved_one_hour_ceiling_usd": round(reserved, 6),
        "estimated_actual_gpu_cost_usd": round(
            sum(float(row["estimated_actual_gpu_cost_usd"]) for row in completed), 6
        ),
        "completed_models": sorted(row["model_key"] for row in completed),
        "errors": errors,
        "source_truth_opened": source_truth_opened,
    }
    atomic_json(output_root / "EXECUTION_RESULT.json", result)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
