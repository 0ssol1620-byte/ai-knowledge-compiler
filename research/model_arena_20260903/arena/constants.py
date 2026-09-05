"""Frozen campaign constants shared by every lane.

Change nothing here without a receipt. These values are part of every
inference_job_id and every canary selection, so editing them mid-campaign
invalidates work that has already been paid for.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Final

CAMPAIGN_ID: Final = "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1"
CAMPAIGN_DATE: Final = "2026-09-03"
NAMESPACE_ROOT: Final = Path(__file__).resolve().parents[1]
REPO_ROOT: Final = NAMESPACE_ROOT.parents[1]

# Benchmark keys use the masterplan section 9.2 sample_id prefixes. The staged
# public-core tree from the 2026-08 FOLYNTA campaign uses different ids; this
# mapping is the single place where the translation happens.
BENCHMARK_KEYS: Final = ("parsebench", "omnidoc", "olmocr")
STAGED_BENCHMARK_ID: Final = MappingProxyType(
    {"parsebench": "parsebench", "omnidoc": "omnidocbench", "olmocr": "olmocr-bench"}
)
EXPECTED_SAMPLE_COUNTS: Final = MappingProxyType(
    {"parsebench": 2078, "omnidoc": 1651, "olmocr": 1403}
)
TOTAL_SAMPLES: Final = 5132

# Source-only inference bundle (PNG page renders + non-GT manifest). Ground
# truth lives under benchmark/datasets/acquired/public-core and benchmark/cache
# and must never be referenced from the inference plane.
STAGED_PUBLIC_CORE_ROOT: Final = REPO_ROOT / "benchmark" / "datasets" / "staged-public-core"
ACQUIRED_PUBLIC_CORE_ROOT: Final = (
    REPO_ROOT / "benchmark" / "datasets" / "acquired" / "public-core"
)
EVALUATOR_CACHE_ROOT: Final = REPO_ROOT / "benchmark" / "cache"
BENCHMARK_REGISTRY_LOCK: Final = REPO_ROOT / "benchmark" / "benchmark-registry.lock.yaml"

# Historical evaluator pins from the 5,132-document FOLYNTA campaign
# (docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md). Kept as the historical lane.
HISTORICAL_EVALUATOR_PINS: Final = MappingProxyType(
    {
        "parsebench": "1d460294b3b9c57fb3fa944dc17a9c044c24d1e5",
        "omnidoc": "193627ae9e97d89188468ed1ee3b7a856ff76044",
        "olmocr": "cfa88c1eb1c2ec4495c84d6820ffe85d33b7408c",
    }
)

MODEL_KEYS: Final = (
    "paddleocr_vl_1_6",
    "mineru_pipeline",
    "mineru_vlm",
    "deepseek_ocr2",
    "ovisocr2",
    "unlimited_ocr",
    "infinity_parser2_pro",
    "infinity_parser2_flash",
    "monkeyocrv2_b",
    "olmocr2",
    "hpd_parsing",
    "glm_ocr",
    "opus5_subscription",
)
GPU_MODEL_KEYS: Final = tuple(k for k in MODEL_KEYS if k != "opus5_subscription")
OPUS_DISPLAY_NAME: Final = "Claude Opus 5 - Claude Code subscription surface"

# Canary (section 17): deterministic, GT-blind selection. The salt is fixed for
# the campaign so every lane selects the same pages.
CANARY_SALT: Final = "TAVONEL-ARENA-CANARY-20260903"
CANARY_PAGES_PER_BENCHMARK: Final = 5  # 15 pages per model, inside the 10-20 band
OPUS_CANARY_PAGES: Final = 50  # section 21.7 health check before scaling workers

# Budget (section 19). The hard cap is a runaway guard, not a funding limit.
BUDGET_TARGET_USD: Final = 250.0
BUDGET_SOFT_CAP_USD: Final = 500.0
BUDGET_HARD_CAP_USD: Final = 500.0

# Worker HTTP contract (ARENA_CONTRACT.md section 4).
WORKER_PORT: Final = 8000
WORKER_API_PREFIX: Final = "/v1"
HEARTBEAT_INTERVAL_SECONDS: Final = 30

# Error taxonomy (section 16). Order matters only for display.
ERROR_CLASSES: Final = (
    "INFRA_CAPACITY",
    "INFRA_NETWORK",
    "IMAGE_PULL",
    "MODEL_DOWNLOAD",
    "DEPENDENCY",
    "MODEL_LOAD",
    "CUDA_INIT",
    "CUDA_OOM",
    "GPU_KERNEL",
    "TENSOR_SHAPE",
    "INPUT_DECODE",
    "PREPROCESS",
    "INFERENCE_TIMEOUT",
    "INFERENCE_STALL",
    "OUTPUT_EMPTY",
    "OUTPUT_TRUNCATED",
    "OUTPUT_MALFORMED",
    "OUTPUT_REPETITION",
    "POSTPROCESS",
    "UPLOAD",
    "CHECKSUM",
    "RATE_LIMIT",
    "AUTH",
    "SUBSCRIPTION_LIMIT",
    "EVALUATOR",
    "UNKNOWN",
)

CONTROLLER_STATES: Final = (
    "DISCOVERED",
    "REGISTERED",
    "RUNTIME_BUILDING",
    "CANARY",
    "QUALIFIED",
    "QUEUED",
    "RUNNING",
    "OUTPUT_FROZEN",
    "SCORED",
    "REPORTED",
    "CANARY_FAILED",
    "RUNTIME_QUARANTINED",
    "BUDGET_PAUSED",
    "SUBSCRIPTION_PAUSED",
    "SOURCE_QUARANTINED",
    "EVALUATOR_BLOCKED",
)

WORKER_STATES: Final = (
    "PROVISIONING",
    "IMAGE_READY",
    "MODEL_LOADING",
    "WARMING",
    "READY",
    "BUSY",
    "DRAINING",
    "TERMINATED",
    "STALLED",
    "OOM",
    "CRASHED",
    "QUARANTINED",
)
