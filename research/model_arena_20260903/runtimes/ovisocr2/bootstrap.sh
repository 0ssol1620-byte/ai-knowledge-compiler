#!/usr/bin/env bash
# OvisOCR2 canary bootstrap (ARENA_CONTRACT.md section 11.3 item 4).
#
# Canary only. Masterplan section 15.1 forbids installing a runtime during a Full
# Run, and the controller records runtime_image_digest as
# "bootstrap:<runtime_bundle_sha256>" so a bootstrap result can never be mistaken
# for a baked one.
#
# By the time this script runs, the bundle is already extracted at /opt/arena
# and the B2 template has exec'd this script with PYTHONPATH=/opt/arena and
# ARENA_RUNTIME_DIR=/opt/arena/runtime already exported -- it never downloads
# the bundle itself and never requires ARENA_BUNDLE_URL.
#
# Starts from the official base image
#   docker.io/vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05
# which already ships vllm 0.22.1+cu129 and huggingface-hub 1.17.0, so this
# script installs no Python packages at all -- it verifies them. That is the
# strongest form of "pin the same versions" available here.

set -euo pipefail

MODEL_KEY=ovisocr2
MODEL_REPO=ATH-MaaS/OvisOCR2
MODEL_REVISION=1fc9221b7823a371d6e97f92d527cc847e24e107
BASE_IMAGE="docker.io/vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05"
LARGEST_WEIGHT_FILE=model.safetensors
LARGEST_WEIGHT_SHA256=9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009

ARENA_ROOT=/opt/arena
WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/workspace/arena/weights/${MODEL_KEY}}"
# The worker adapter resolves weights from ARENA_WEIGHTS_DIR (default
# /workspace/arena/weights/<model_key>); export it so bootstrap and worker agree.
export ARENA_WEIGHTS_DIR="${WEIGHTS_DIR}"
RECEIPT=${ARENA_ROOT}/bootstrap-receipt.txt
PIP_FREEZE_FILE=${ARENA_ROOT}/bootstrap-pip-freeze.txt

: "${ARENA_MODEL_REVISION:?ARENA_MODEL_REVISION is required}"

if [[ "${ARENA_MODEL_REVISION}" != "${MODEL_REVISION}" ]]; then
  echo "bootstrap refuses: pod asks for ${ARENA_MODEL_REVISION}, this script pins ${MODEL_REVISION}" >&2
  exit 64
fi

export PIP_NO_CACHE_DIR=1
export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_ENABLE_HF_TRANSFER=0
export VLLM_WORKER_MULTIPROC_METHOD=spawn

mkdir -p "${WEIGHTS_DIR}"

# 1. Runtime versions: verified, not installed. Same assertion as the Dockerfile.
python3 -c "from importlib.metadata import version as v; expected={'vllm':'0.22.1+cu129','huggingface-hub':'1.17.0','pillow':'12.2.0','transformers':'5.10.2'}; actual={n:v(n) for n in expected}; raise SystemExit(None if actual==expected else f'bootstrap dependency mismatch: {actual!r}')"

# 2. Pinned weights (revision + sha256 check), public repo, no token. Same
#    integrity checks the baked image applies at build time.
hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" --local-dir "${WEIGHTS_DIR}"
printf '%s  %s\n' "${LARGEST_WEIGHT_SHA256}" "${WEIGHTS_DIR}/${LARGEST_WEIGHT_FILE}" \
  | sha256sum --check --strict

PYTHONPATH=${ARENA_ROOT} python3 "${ARENA_ROOT}/runtime/adapter.py" \
  --write-weights-receipt "${WEIGHTS_DIR}" \
  --repo "${MODEL_REPO}" \
  --revision "${MODEL_REVISION}"
find "${WEIGHTS_DIR}" -type f -exec chmod 0444 {} +

# 2b. Architecture preflight.
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. OvisOCR2 is
# served by the vLLM offline `LLM` engine loaded in-process in the worker, so there
# is no server to hold open - but the engine still has to recognise the checkpoint,
# and that is what is asserted here.
#
# Floors (evidence in runtime.json.framework_floor_audit): the model card requires
# vllm==0.22.1; the checkpoint declares model_type "qwen3_5", architectures
# ["Qwen3_5ForConditionalGeneration"] and no auto_map, so nothing loads it from
# remote code - either Transformers knows qwen3_5 (the 5.2 line onwards) or vLLM's
# own bundled config does. vllm v0.22.1 registers Qwen3_5ForConditionalGeneration
# and bounds transformers ">= 4.56.0, != 5.0.* .. != 5.5.0", which the image's
# 5.10.2 satisfies.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_DIR}" python3 - <<'PY'
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

PINNED_VLLM_PREFIX = "0.22.1"
EXPECTED_MODEL_TYPE = "qwen3_5"
EXPECTED_ARCH = "Qwen3_5ForConditionalGeneration"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


import vllm

if not vllm.__version__.startswith(PINNED_VLLM_PREFIX):
    fail(f"vllm is {vllm.__version__}, the model card pins {PINNED_VLLM_PREFIX}")

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

from vllm.model_executor.models.registry import ModelRegistry

supported = set(ModelRegistry.get_supported_archs())
missing = [arch for arch in architectures if arch not in supported]
if missing:
    fail(f"vLLM {vllm.__version__} does not register {missing}; it cannot serve this checkpoint")

# Something must be able to build the config: either Transformers knows the
# model_type natively, or vLLM carries its own class for it. Neither is the exact
# shape of the GLM-OCR incident.
from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES

resolver = "transformers" if model_type in CONFIG_MAPPING_NAMES else None
if resolver is None:
    try:
        from vllm.transformers_utils.config import _CONFIG_REGISTRY

        if model_type in _CONFIG_REGISTRY:
            resolver = "vllm.transformers_utils.config"
    except Exception as exc:  # noqa: BLE001 - an unreadable registry is not a pass
        fail(
            f"transformers {version('transformers')} does not know model_type "
            f"{model_type!r} and vLLM's own config registry is unreadable: {exc}"
        )
if resolver is None:
    fail(
        f"neither transformers {version('transformers')} nor vLLM {vllm.__version__} "
        f"knows model_type {model_type!r}, and the checkpoint has no auto_map"
    )

summary = (
    f"model_type={model_type} architectures={','.join(architectures)} "
    f"config_resolver={resolver} vllm={vllm.__version__} "
    f"transformers={version('transformers')}"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"

# 3. Bootstrap receipt (campaign, model_key, base image, versions, pip freeze
#    sha256) and the full pip-freeze sidecar. No URL, no token, no environment
#    dump.
python3 -m pip freeze | LC_ALL=C sort > "${PIP_FREEZE_FILE}"
PIP_FREEZE_SHA256=$(sha256sum "${PIP_FREEZE_FILE}" | cut -d' ' -f1)

{
  echo "campaign=${ARENA_CAMPAIGN_ID:-unset}"
  echo "model_key=${MODEL_KEY}"
  echo "model_repo=${MODEL_REPO}"
  echo "model_revision=${MODEL_REVISION}"
  echo "base_image=${BASE_IMAGE}"
  echo "runtime_mode=bootstrap"
  echo "bootstrap_script_sha256=$(sha256sum "${BASH_SOURCE[0]}" | cut -d' ' -f1)"
  echo "architecture_preflight=${ARCH_PREFLIGHT}"
  echo "vllm_worker_multiproc_method=${VLLM_WORKER_MULTIPROC_METHOD}"
  echo "pip_freeze_sha256=${PIP_FREEZE_SHA256}"
  cat "${WEIGHTS_DIR}/arena-weights-receipt.json"
  echo
  python3 --version
  python3 -c "import torch; print('torch=' + torch.__version__); print('torch_cuda=' + str(torch.version.cuda))"
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader,nounits
} > "${RECEIPT}"
chmod 0444 "${RECEIPT}" "${PIP_FREEZE_FILE}"

echo "bootstrap complete: ${RECEIPT}" >&2
exec bash "${ARENA_ROOT}/runtime/entrypoint.sh"
