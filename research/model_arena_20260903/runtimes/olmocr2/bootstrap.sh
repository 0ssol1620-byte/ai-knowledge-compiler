#!/usr/bin/env bash
# CANARY-ONLY bootstrap for olmOCR-2-7B-1025-FP8 (ARENA_CONTRACT.md section 11.3).
#
# From the bare vllm/vllm-openai:v0.11.2 image: the B2 bundle template has already
# extracted the bundle to /opt/arena, symlinked
# /opt/arena/runtime -> /opt/arena/runtimes/olmocr2 and exported
# PYTHONPATH=/opt/arena + ARENA_RUNTIME_DIR before calling this script, so this
# script never downloads a bundle and never requires ARENA_BUNDLE_URL. It installs
# exactly the versions the baked Dockerfile installs, downloads the pinned weights
# to /workspace, and records every version it saw into
# /opt/arena/bootstrap-receipt.txt. A Full Run from this path needs a founder
# waiver (runtime_image_digest becomes "bootstrap:<runtime_bundle_sha256>").
set -euo pipefail

RUNTIME_DIR="${ARENA_RUNTIME_DIR:-/opt/arena/runtime}"
WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/workspace/arena/weights/olmocr2}"
RECEIPT=/opt/arena/bootstrap-receipt.txt

mkdir -p /opt/arena /workspace/arena/results

# --- D33 revision guard ----------------------------------------------------
# runtime.json owns the pinned revision (ARENA_CONTRACT D16). A pod that asks for
# a different one is a mis-provisioned pod, not something to reconcile silently.
: "${ARENA_MODEL_REVISION:?ARENA_MODEL_REVISION is required}"
MODEL_REVISION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8"))["weights"]["revision"])' "${RUNTIME_DIR}/runtime.json")"
if [ "${ARENA_MODEL_REVISION}" != "${MODEL_REVISION}" ]; then
    echo "[arena] bootstrap refuses: pod asks for ${ARENA_MODEL_REVISION}," \
        "runtime.json pins ${MODEL_REVISION}" >&2
    exit 64
fi

export ARENA_WEIGHTS_DIR="${WEIGHTS_DIR}"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends poppler-utils
rm -rf /var/lib/apt/lists/*

# Same pins as runtimes/olmocr2/Dockerfile. Sources:
#   https://github.com/allenai/olmocr/blob/v0.4.27/pyproject.toml  ([gpu] extra)
python3 -m pip install --no-cache-dir "olmocr==0.4.27" "transformers==4.57.3"

python3 "${RUNTIME_DIR}/fetch_weights.py" --weights-dir "${WEIGHTS_DIR}" --manifest

# --- architecture preflight ------------------------------------------------
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. Assert the
# pinned versions AND that both frameworks can actually resolve this checkpoint,
# here, before a server is started.
#
# Floors (evidence in runtime.json.framework_floor_audit):
#   checkpoint config.json declares transformers_version 4.53.2, model_type
#   qwen2_5_vl, architectures ["Qwen2_5_VLForConditionalGeneration"];
#   vllm v0.11.2 requirements/common.txt bounds transformers >= 4.56.0, < 5 and
#   its registry.py carries Qwen2_5_VLForConditionalGeneration.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_DIR}" python3 - <<'PY'
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

PINNED = {"transformers": "4.57.3", "olmocr": "0.4.27"}
PINNED_VLLM_PREFIX = "0.11.2"
EXPECTED_MODEL_TYPE = "qwen2_5_vl"
EXPECTED_ARCH = "Qwen2_5_VLForConditionalGeneration"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


for name, pin in PINNED.items():
    installed = version(name)
    if installed != pin:
        fail(f"{name} is {installed}, this runtime pins {pin}")

import vllm

if not vllm.__version__.startswith(PINNED_VLLM_PREFIX):
    fail(f"vllm is {vllm.__version__}, this runtime pins {PINNED_VLLM_PREFIX}")

weights = Path(os.environ["ARENA_PREFLIGHT_WEIGHTS_DIR"])
try:
    config = json.loads((weights / "config.json").read_text(encoding="utf-8"))
except OSError as exc:
    fail(f"cannot read {weights / 'config.json'}: {exc}")
model_type = config.get("model_type")
architectures = tuple(config.get("architectures") or ())
if model_type != EXPECTED_MODEL_TYPE or EXPECTED_ARCH not in architectures:
    fail(
        f"checkpoint declares model_type={model_type!r} architectures={architectures!r}, "
        f"runtime.json was written for {EXPECTED_MODEL_TYPE!r}/{EXPECTED_ARCH!r}"
    )

from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES

if model_type not in CONFIG_MAPPING_NAMES and "auto_map" not in config:
    fail(
        f"transformers {version('transformers')} does not know model_type {model_type!r} "
        "and the checkpoint carries no auto_map to load it from remote code"
    )
from transformers import AutoConfig

try:
    resolved = AutoConfig.from_pretrained(str(weights))
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"transformers cannot build a config for {model_type!r}: {type(exc).__name__}: {exc}")

from vllm.model_executor.models.registry import ModelRegistry

supported = set(ModelRegistry.get_supported_archs())
missing = [arch for arch in architectures if arch not in supported]
if missing:
    fail(f"vLLM {vllm.__version__} does not register {missing}; it cannot serve this checkpoint")

summary = (
    f"model_type={model_type} architectures={','.join(architectures)} "
    f"config_class={type(resolved).__name__} transformers={version('transformers')} "
    f"vllm={vllm.__version__} olmocr={version('olmocr')}"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"

{
    echo "campaign=${ARENA_CAMPAIGN_ID:-unset}"
    echo "model_key=olmocr2"
    echo "base_image=vllm/vllm-openai:v0.11.2"
    echo "architecture_preflight=${ARCH_PREFLIGHT}"
    echo "bootstrapped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "python=$(python3 --version 2>&1)"
    echo "os=$(. /etc/os-release && echo "${PRETTY_NAME}")"
    echo "nvidia_driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
    echo "pip_freeze_sha256=$(python3 -m pip freeze | sha256sum | cut -d' ' -f1)"
    python3 - <<'PY'
import importlib
from importlib.metadata import PackageNotFoundError, version
for name in ("vllm", "torch", "transformers", "olmocr", "huggingface_hub", "PIL"):
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - receipt records the failure verbatim
        print(f"{name}=IMPORT_FAILED:{type(exc).__name__}")
        continue
    try:
        print(f"{name}={version(name)}")
    except PackageNotFoundError:
        print(f"{name}={getattr(module, '__version__', 'unknown')}")
from olmocr.prompts import build_no_anchoring_v4_yaml_prompt
prompt = build_no_anchoring_v4_yaml_prompt()
import hashlib
print("prompt_sha256=sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest())
PY
} > "${RECEIPT}"
python3 -m pip freeze > /opt/arena/bootstrap-pip-freeze.txt

echo "[arena] bootstrap receipt written to ${RECEIPT}" >&2
exec "${RUNTIME_DIR}/entrypoint.sh"
