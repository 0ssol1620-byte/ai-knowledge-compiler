"""One valid example per schema name, shared by the core tests.

These are fixtures, not evidence. Every digest is an obviously synthetic
constant so nothing here can be mistaken for a real campaign artifact, and no
value in this file resembles a credential.
"""

from __future__ import annotations

from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.core.receipts import CANARY_CRITERIA

TS: Final = "2026-09-03T12:00:00.000Z"
TS_LATER: Final = "2026-09-03T12:05:00.000Z"
SHA_A: Final = "sha256:" + "a1" * 32
SHA_B: Final = "sha256:" + "b2" * 32
SHA_C: Final = "sha256:" + "c3" * 32
SHA_D: Final = "sha256:" + "d4" * 32
JOB_ID: Final = "e5" * 32
BASE_JOB_ID: Final = "f6" * 32
RECOVERY_ID: Final = "07" * 32
IMAGE_DIGEST: Final = "ghcr.io/tavonel/arena-paddleocr@sha256:" + "1b" * 32
CASE_KEY: Final = "omnidocbench-58851882e7b39101a6f5756c"
SAMPLE_ID: Final = "omnidoc:images/PPT_1001115_eng_page_003"


def _page_receipt() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.page-receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "inference_job_id": JOB_ID,
        "benchmark": "omnidoc",
        "sample_id": SAMPLE_ID,
        "case_key": CASE_KEY,
        "source_sha256": SHA_A,
        "model_key": "paddleocr_vl_1_6",
        "model_revision": "1234567890abcdef1234567890abcdef12345678",
        "runtime_image_digest": IMAGE_DIGEST,
        "runtime_mode": "baked",
        "job_kind": "inference",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "gpu_id": "0",
        "pod_id": "pod-abc123",
        "worker_id": "paddleocr_vl_1_6-w0-pod-abc123",
        "shard_id": "paddleocr_vl_1_6-omnidoc-0000",
        "prompt_id": "paddleocr_vl_official_v1",
        "prompt_sha256": SHA_B,
        "inference_config_sha256": SHA_C,
        "image_width": 1654,
        "image_height": 2339,
        "queued_at": TS,
        "worker_ready_at": TS,
        "started_at": TS,
        "first_token_at": None,
        "finished_at": TS_LATER,
        "queue_ms": 120,
        "load_ms": 0,
        "preprocess_ms": 40,
        "inference_ms": 3410,
        "postprocess_ms": 25,
        "total_ms": 3595,
        "peak_vram_mb": 18240,
        "baseline_vram_mb": 15870,
        "vram_total_mb": 24564,
        "vram_measurement_source": "nvidia-smi",
        "input_bytes": 512000,
        "output_bytes": 8192,
        "output_chars": 8100,
        "input_tokens": None,
        "output_tokens": None,
        "attempt": 1,
        "retry_count": 0,
        "retry_reason": None,
        "status": "SUCCESS",
        "error_class": None,
        "semantic_error_class": None,
        "error_message": None,
        "wasted_gpu_seconds": 0.0,
        "recovery_job_id": None,
        "raw_output_path": f"runs/paddleocr_vl_1_6/raw/{CASE_KEY}.raw.txt",
        "raw_output_sha256": SHA_D,
        "canonical_output_path": f"runs/paddleocr_vl_1_6/canonical/{CASE_KEY}.md",
        "canonical_output_sha256": SHA_A,
    }


def _event() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.event.v1",
        "campaign_id": CAMPAIGN_ID,
        "ts": TS,
        "entity_kind": "model",
        "entity_id": "paddleocr_vl_1_6",
        "from_state": "CANARY",
        "to_state": "QUALIFIED",
        "reason": "canary PASS on 15 pages",
        "detail": {"canary_receipt": SHA_A},
    }


def _pod_ledger() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.pod-ledger.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": "paddleocr_vl_1_6",
        "runtime_mode": "baked",
        "pod_id": "pod-abc123",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "data_center_id": "EU-RO-1",
        "listed_rate_usd_per_hour": 0.34,
        "gpu_count": 1,
        "price_snapshot_sha256": SHA_B,
        "provisioned_at": TS,
        "model_ready_at": TS_LATER,
        "last_job_finished_at": None,
        "terminated_at": None,
        "billed_seconds": 3600.0,
        "model_loading_seconds": 210.0,
        "useful_inference_seconds": 3200.0,
        "retry_seconds": 40.0,
        "idle_seconds": 150.0,
        "estimated_provider_cost_usd": 0.34,
        "useful_cost_usd": 0.302,
        "wasted_cost_usd": 0.038,
    }


def _error_record() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.error-record.v1",
        "campaign_id": CAMPAIGN_ID,
        "error_class": "TENSOR_SHAPE",
        "first_seen": TS,
        "last_seen": TS_LATER,
        "count": 3,
        "affected_model": "mineru_vlm",
        "affected_image_digest": IMAGE_DIGEST,
        "affected_gpu_type": "NVIDIA A40",
        "retryability": False,
        "root_cause": None,
        "resolution": None,
        "wasted_gpu_seconds": 91.5,
    }


def _route_decision() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.route-decision.v1",
        "campaign_id": CAMPAIGN_ID,
        "variant": "C",
        "case_key": CASE_KEY,
        "sample_id": SAMPLE_ID,
        "primary": "paddleocr_vl_1_6",
        "signals": {"table_density": 0.42, "truncation_suspected": False},
        "signals_sha256": SHA_A,
        "decision": "ESCALATE",
        "target": "mineru_vlm",
        "decision_sha256": SHA_B,
        "decided_before_gt": True,
        "policy_id": "adaptive_v1",
        "policy_sha256": SHA_C,
    }


def _recovery_job() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.recovery-job.v1",
        "recovery_job_id": RECOVERY_ID,
        "base_inference_job_id": BASE_JOB_ID,
        "case_key": CASE_KEY,
        "sample_id": SAMPLE_ID,
        "model_key": "paddleocr_vl_1_6",
        "recovery_type": "overlap_tiling",
        "recovery_config": {"tile_overlap_px": 128, "tiles": 4},
        "recovery_config_sha256": SHA_D,
        "round": 1,
        "trigger_signals": ["truncation_suspected"],
        "planned_before_gt": True,
    }


def _run_summary() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.run-summary.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": "paddleocr_vl_1_6",
        "model_revision": "1234567890abcdef1234567890abcdef12345678",
        "runtime_image_digest": IMAGE_DIGEST,
        "runtime_mode": "baked",
        "started_at": TS,
        "finished_at": TS_LATER,
        "sample_count": 5132,
        "success_count": 5120,
        "failed_count": 12,
        "quarantined_count": 0,
        "paused_count": 0,
        "per_benchmark_counts": {"parsebench": 2078, "omnidoc": 1651, "olmocr": 1403},
        "error_class_counts": {"OUTPUT_EMPTY": 12},
        "total_gpu_seconds": 18090.0,
        "wasted_gpu_seconds": 42.0,
        "receipt_manifest_sha256": SHA_A,
        "notes": [],
    }


def _frozen() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.frozen.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": "paddleocr_vl_1_6",
        "frozen_at": TS,
        "manifest_sha256": SHA_A,
        "sample_count": 5132,
        "success_count": 5120,
        "failed_count": 12,
        "model_revision": "1234567890abcdef1234567890abcdef12345678",
        "runtime_image_digest": IMAGE_DIGEST,
    }


def _canary_receipt() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.canary-receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": "paddleocr_vl_1_6",
        "model_revision": "1234567890abcdef1234567890abcdef12345678",
        "runtime_image_digest": IMAGE_DIGEST,
        "runtime_mode": "baked",
        "base_image": "ghcr.io/tavonel/arena-paddleocr:1.6",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "gpu_compute_capability": "8.9",
        "pod_id": "pod-abc123",
        "authorization_receipt_path": "receipts/authorizations/phase1_canary-20260903T074000Z.json",
        "authorization_receipt_sha256": "4d" * 32,
        "pod_ledger_path": "cost/pod_ledger.jsonl",
        "started_at": TS,
        "finished_at": TS_LATER,
        "page_count": 15,
        "success_count": 15,
        "failed_count": 0,
        "stage_latency_ms": {
            "inference": {"p50_ms": 3400.0, "p90_ms": 4100.0, "p95_ms": 4400.0},
            "total": {"p50_ms": 3525.0, "p90_ms": 4210.0, "p95_ms": 4520.0},
        },
        "peak_vram_mb": 18240,
        "gpu_total_vram_mb": 24564,
        "vram_headroom_mb": 6324,
        "warm_sec_per_page": 3.525,
        "total_samples": 5132,
        "replica_count": 4,
        "overhead_factor": 1.15,
        "selected_gpu_hourly_rate_usd": 0.34,
        "price_snapshot_sha256": SHA_B,
        "gpu_hours_projected": 5.026,
        "raw_gpu_cost_projected_usd": 1.709,
        "wall_time_hours_projected": 1.445,
        "status": "PASS",
        "criteria": [
            {"criterion": name, "passed": True, "detail": "observed on 15 canary pages"}
            for name in CANARY_CRITERIA
        ],
        "fail_reasons": [],
    }


def _provision_gate() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.provision_gate.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": "paddleocr_vl_1_6",
        "phase": "phase1_canary",
        "evaluated_at": TS,
        "authorization": {
            "allowed": True,
            "phase": "phase1_canary",
            "required_usd": 2.0022,
            "authorization_receipt_sha256": "4d" * 32,
        },
        "provisioning": {
            "mode": "dry_run",
            "pod_id": None,
            "pod_name": "arena-paddleocr-vl-w0-20260903v1",
            "runtime_mode": "bootstrap",
        },
        "gpu_pool": {"ok": True, "gpu_pool_priority": ["NVIDIA GeForce RTX 4090"]},
        "license": {"allowed": True, "license_status": "approved"},
    }


def _bundle_publish() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.bundle-publish.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_key": "paddleocr_vl_1_6",
        "bundle_sha256": "9e" * 32,
        "bundle_size_bytes": 184320,
        "bundle_file_count": 27,
        "bundle_manifest_sha256": SHA_C,
        "r2_bucket": "tavonel-arena-20260903",
        "r2_key": f"bundles/{CAMPAIGN_ID}/paddleocr_vl_1_6/arena-bundle.tar.gz",
        "uploaded_at": TS,
    }


def _model_registry_record() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.model-registry-record.v1",
        "model_key": "paddleocr_vl_1_6",
        "display_name": "PaddleOCR-VL 1.6",
        "repo": "PaddlePaddle/PaddleOCR-VL-1.6",
        "revision": "1234567890abcdef1234567890abcdef12345678",
        "license": "Apache-2.0",
        "runtime_type": "vllm",
        "runtime_version": "0.8.5",
        "container_image": "ghcr.io/tavonel/arena-paddleocr:20260903",
        "container_digest": IMAGE_DIGEST,
        "cuda": "12.4",
        "torch": "2.6.0",
        "gpu_min_vram_gb": 24.0,
        "gpu_count_min": 1,
        "prompt_id": "paddleocr_vl_official_v1",
        "prompt_sha256": "sha256:" + "b" * 64,
        "prompt_kind": "none",
        "runtime_repository": "https://github.com/PaddlePaddle/PaddleOCR",
        "runtime_revision": "v3.2.0",
        "preprocess_config_id": "paddleocr_vl_official_preprocess_v1",
        "max_concurrency_per_worker": 2,
        "recommended_gpu_pool": ["NVIDIA GeForce RTX 4090", "NVIDIA A40"],
        "canary_status": "PENDING",
        "full_run_eligible": False,
        "official_source_urls": ["https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6"],
        "resolved_at": TS,
        "resolution_method": "huggingface api model info at pinned revision",
        "license_evidence_url": "https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/blob/main/LICENSE",
        "license_notes": (
            "Apache-2.0 is copyright permission from this contributor only. "
            "It settles nothing about a third party's patents."
        ),
        "weights_strategy": "baked",
        "runtime_mode_allowed": ["baked", "bootstrap"],
        "official_prompt_id": "paddleocr_vl_official_v1",
        "official_inference_config": {"max_new_tokens": 4096, "dpi": 200},
        "official_inference_config_sha256": SHA_C,
        "gpu_pool_priority": ["NVIDIA GeForce RTX 4090", "NVIDIA A40"],
        "concurrency_policy": {"per_worker": 2, "scale": "replicas_and_concurrency"},
        "shard_size_hint": 200,
    }


def _evaluator_registry_record() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.evaluator-registry-record.v1",
        "benchmark": "omnidoc",
        "repository": "https://github.com/opendatalab/OmniDocBench",
        "historical_pin": "193627ae9e97d89188468ed1ee3b7a856ff76044",
        "upstream_head_at_start": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "main_pin": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "main_pin_rationale": "upstream HEAD at campaign start, frozen for the main lane",
        "historical_lane_required": True,
        "entrypoint": "pdf_validation.py",
        "dataset_repository": "opendatalab/OmniDocBench",
        "dataset_revision": "aa1ee96d0000000000000000000000000000000000",
        "dataset_manifest_sha256": SHA_A,
        "gt_paths": ["benchmark/datasets/acquired/public-core/omnidocbench"],
        "license": "Apache-2.0",
        "frozen": False,
    }


def _authorization_receipt() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.authorization-receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "phase": "phase1_canary",
        "authorized_by": "founder",
        "authorized_at": "2026-09-03T00:00:00Z",
        "expires_at": "2026-09-10T00:00:00Z",
        "max_usd": 120.0,
        "model_keys": ["paddleocr_vl_1_6"],
        "statement": "Founder authorized the phase 1 canary for PaddleOCR-VL on 2026-09-03.",
        "notes": None,
    }


def _runtime() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.runtime.v1",
        "model_key": "paddleocr_vl_1_6",
        "display_name": "PaddleOCR-VL 1.6",
        "model_repo": "PaddlePaddle/PaddleOCR-VL-1.6",
        "model_revision": "1234567890abcdef1234567890abcdef12345678",
        "official_runtime": "vllm",
        "runtime_version": "0.8.5",
        "runtime_repository": "PaddlePaddle/PaddleOCR",
        "runtime_revision": "b03f46425e8ff4442b268ce449e3eef758146cd4",
        "base_image": "vllm/vllm-openai@sha256:" + "2c" * 32,
        "gpu_min_vram_gb": 24.0,
        "gpu_count_min": 1,
        "gpu_pool_priority": ["NVIDIA GeForce RTX 4090", "NVIDIA A40"],
        "max_concurrency_per_worker": 2,
        "shard_size_hint": 200,
        "per_page_timeout_seconds": 180,
        "prompt_id": "paddleocr_vl_official_v1",
        "prompt_kind": "none",
        "min_cuda_version": "12.8",
        "inference_config": {"max_new_tokens": 4096, "dpi": 200},
        "weights_strategy": "baked",
        "runtime_mode_allowed": ["baked", "bootstrap"],
        "official_source_urls": ["https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6"],
        "license": {
            "id": "Apache-2.0",
            "url": "https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/blob/main/LICENSE",
            "status": "verified",
            # Founder licence decisions 2026-09-03 added these optional fields to
            # LicenseRef (arena/core/receipts.py) for licences with more structure
            # than id/url/status (e.g. MinerU's Apache-2.0-plus-terms). This example
            # leaves them unset; the round-trip test needs them present as null.
            "name": None,
            "spdx_base": None,
            "additional_terms": None,
            "text_sha256": None,
            "source_url": None,
            "notes": None,
        },
        "notes": "Official vLLM serving path; canary must confirm the loaded revision.",
        "weights": {
            "repo": "PaddlePaddle/PaddleOCR-VL-1.6",
            "revision": "1234567890abcdef1234567890abcdef12345678",
            "largest_file": "model.safetensors",
            "largest_file_sha256": SHA_D,
        },
    }


def _worker_run_request() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.worker-run-request.v1",
        "campaign_id": CAMPAIGN_ID,
        "inference_job_id": JOB_ID,
        "sample_id": SAMPLE_ID,
        "case_key": CASE_KEY,
        "benchmark": "omnidoc",
        "source_sha256": SHA_A,
        "image_b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgAB",
        "width": 1654,
        "height": 2339,
        "prompt_id": "paddleocr_vl_official_v1",
        "prompt_sha256": SHA_B,
        "inference_config_sha256": SHA_C,
        "job_kind": "inference",
        "metadata": {"page_index": 3, "media_type": "image"},
        "timeout_seconds": 180,
    }


def _worker_run_response() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.worker-run-response.v1",
        "inference_job_id": JOB_ID,
        "status": "SUCCESS",
        "error_class": None,
        "semantic_error_class": None,
        "error_message": None,
        "worker_id": "paddleocr_vl_1_6-w0-pod-abc123",
        "model_key": "paddleocr_vl_1_6",
        "model_revision": "1234567890abcdef1234567890abcdef12345678",
        "runtime_mode": "baked",
        "runtime_image_digest": IMAGE_DIGEST,
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "pod_id": "pod-abc123",
        "started_at": TS,
        "first_token_at": None,
        "finished_at": TS_LATER,
        "timings_ms": {
            "load_ms": 0,
            "preprocess_ms": 40,
            "inference_ms": 3410,
            "postprocess_ms": 25,
            "total_ms": 3475,
        },
        "peak_vram_mb": 18240,
        "baseline_vram_mb": 15870,
        "vram_total_mb": 24564,
        "vram_measurement_source": "nvidia-smi",
        "input_bytes": 512000,
        "output_bytes": 8192,
        "output_chars": 8100,
        "input_tokens": None,
        "output_tokens": None,
        "raw_output": {
            "raw_text": "# Heading\n\nBody text.\n",
            "output_format": "markdown",
            "native_json": None,
            "usage": {},
            "warnings": [],
        },
        "canonical": {
            "markdown": "# Heading\n\nBody text.\n",
            "elements": None,
            "lossy": False,
            "conversion_notes": [],
        },
        "raw_output_sha256": SHA_D,
        "canonical_output_sha256": SHA_A,
    }


def _ready_response() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.ready-response.v1",
        "stage": "READY",
        "worker_id": "paddleocr_vl_1_6-w0-pod-abc123",
        "model_key": "paddleocr_vl_1_6",
        "model_revision": "1234567890abcdef1234567890abcdef12345678",
        "runtime_mode": "baked",
        "runtime_image_digest": IMAGE_DIGEST,
        "load_receipt": {"load_ms": 41000, "cache_hit": True},
        "warmup_receipt": {"warmup_ms": 3900, "schema_valid": True},
        "started_at": TS,
        "ready_at": TS_LATER,
        "last_error": None,
    }


def _heartbeat() -> dict[str, Any]:
    return {
        "schema": "tavonel.arena.heartbeat.v1",
        "worker_id": "paddleocr_vl_1_6-w0-pod-abc123",
        "state": "BUSY",
        "stage": "BUSY",
        "job_id": JOB_ID,
        "ts": TS,
        "last_progress_at": TS,
        "gpu_util": 87.5,
        "vram_used": 18240,
        "gpu_metrics_unavailable_reason": None,
        "output_progress": 4096,
        "jobs_done": 120,
        "jobs_failed": 1,
        "pid": 42,
    }


_BUILDERS: Final = {
    "page-receipt": _page_receipt,
    "event": _event,
    "pod-ledger": _pod_ledger,
    "error-record": _error_record,
    "route-decision": _route_decision,
    "recovery-job": _recovery_job,
    "run-summary": _run_summary,
    "frozen": _frozen,
    "canary-receipt": _canary_receipt,
    "provision_gate": _provision_gate,
    "bundle-publish": _bundle_publish,
    "model-registry-record": _model_registry_record,
    "evaluator-registry-record": _evaluator_registry_record,
    "authorization-receipt": _authorization_receipt,
    "runtime": _runtime,
    "worker-run-request": _worker_run_request,
    "worker-run-response": _worker_run_response,
    "ready-response": _ready_response,
    "heartbeat": _heartbeat,
}


def example(name: str) -> dict[str, Any]:
    """A fresh, valid record for one schema name."""

    return _BUILDERS[name]()


EXAMPLE_NAMES: Final = tuple(_BUILDERS)
