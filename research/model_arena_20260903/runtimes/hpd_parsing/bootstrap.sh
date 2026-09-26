#!/usr/bin/env bash
# HPD-Parsing - CANARY-ONLY bootstrap (ARENA_CONTRACT.md section 11.3 item 4).
#
# Masterplan section 15.1 forbids installing a runtime during a Full Run. This
# path exists only so a canary can qualify the model before the image is built;
# the controller then records runtime_image_digest as "bootstrap:<bundle sha>".
#
# This script NEVER downloads the worker bundle and requires no
# bundle-URL variable of any kind. The B2 start command has already verified and extracted the
# bundle into /opt/arena, created the symlink /opt/arena/runtime ->
# /opt/arena/runtimes/hpd_parsing, and exported PYTHONPATH=/opt/arena and
# ARENA_RUNTIME_DIR=/opt/arena/runtime.
#
# Start from the official base image only, digest-pinned in runtime.json:
#   ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/hpd-parsing-vllm:latest-nvidia-gpu-offline
#     @sha256:1493923dd6b7e368c56b5497f2c82ade2599be9c69aa7498a71417b5c6d9948a
# That image declares its own ENTRYPOINT (/bin/bash /home/hpd/entrypoint.sh), so
# bootstrap mode reaches this script through the REST v1 dockerEntrypoint
# override described in ARENA_CONTRACT D2, not through the image default.
#
# The customized vLLM build is NOT rebuilt here. If the official image somehow
# lacks it, the documented prebuilt wheel below is the only other supported path.

set -euo pipefail

MODEL_KEY="hpd_parsing"
MODEL_REPO="${ARENA_MODEL_REPO:-PaddlePaddle/HPD-Parsing}"
MODEL_REVISION="${ARENA_MODEL_REVISION:?ARENA_MODEL_REVISION is required}"
WEIGHTS_LARGEST_FILE="${ARENA_WEIGHTS_LARGEST_FILE:-model.safetensors}"
WEIGHTS_LARGEST_SHA256="${ARENA_WEIGHTS_LARGEST_SHA256:-f82b9c83ca8a85931b51b717143c24858281aa8cd1f016dd5a7a1ec5d40a7d91}"
PMTP_SHA256="${ARENA_PMTP_SHA256:-a84e697098ce5242a5a10cb95ae05a8cc579134ae01d615ed7bd64f97cddec3a}"
HPD_VLLM_WHEEL="https://paddle-model-ecology.bj.bcebos.com/paddlex/PaddleX3.0/deploy/hpd_parsing/vllm-0.17.1+hpdparsing-cp38-abi3-manylinux_2_31_x86_64.whl"
BASE_IMAGE="${ARENA_BASE_IMAGE:-ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/hpd-parsing-vllm:latest-nvidia-gpu-offline}"
BASE_IMAGE_DIGEST="${ARENA_BASE_IMAGE_DIGEST:-sha256:1493923dd6b7e368c56b5497f2c82ade2599be9c69aa7498a71417b5c6d9948a}"

# D54: the bundle entrypoint (arena/worker/bundle.py START_CMD_TEMPLATE) already
# chose a writable ARENA_ROOT and exported it -- /opt/arena when writable, else
# $HOME/arena, else /tmp/arena -- because this model's official base image runs
# as non-root USER hpd (HOME=/home/hpd, confirmed from the image's OCI config)
# and cannot write /opt. Fall back to the /opt/arena literal only when this
# script is somehow invoked without that export (a baked image's own
# ENTRYPOINT, where /opt/arena is always the layout).
ARENA_ROOT="${ARENA_ROOT:-/opt/arena}"
RUNTIME_DIR="${ARENA_RUNTIME_DIR:-${ARENA_ROOT}/runtime}"
RECEIPT="${ARENA_ROOT}/bootstrap-receipt.txt"
PYTHON_BIN="${PYTHON_BIN:-python}"

if [ ! -f "${RUNTIME_DIR}/entrypoint.sh" ]; then
  echo "bootstrap: ${RUNTIME_DIR}/entrypoint.sh is missing; the bundle was not laid out as section 11.3 requires" >&2
  exit 1
fi

# D54: /workspace is the default (matches every other runtime's convention and
# the persistent-volume cache a canary reruns against), but a non-root image may
# not own it either. Fall back under ARENA_ROOT, which is already known-writable.
WEIGHTS_ROOT_DEFAULT="/workspace/arena/weights/${MODEL_KEY}"
RESULTS_DIR_DEFAULT="/workspace/arena/results"
if ! { mkdir -p "${WEIGHTS_ROOT_DEFAULT}" "${RESULTS_DIR_DEFAULT}" 2>/dev/null \
    && [ -w "${WEIGHTS_ROOT_DEFAULT}" ] && [ -w "${RESULTS_DIR_DEFAULT}" ]; }; then
  echo "bootstrap: /workspace/arena is not writable; falling back under ARENA_ROOT" >&2
  WEIGHTS_ROOT_DEFAULT="${ARENA_ROOT}/weights/${MODEL_KEY}"
  RESULTS_DIR_DEFAULT="${ARENA_ROOT}/results"
  mkdir -p "${WEIGHTS_ROOT_DEFAULT}" "${RESULTS_DIR_DEFAULT}"
fi
WEIGHTS_ROOT="${ARENA_WEIGHTS_DIR:-${WEIGHTS_ROOT_DEFAULT}}"
mkdir -p "${WEIGHTS_ROOT}"

: > "${RECEIPT}"
record() { printf '%s\n' "$*" >> "${RECEIPT}"; }

record "campaign_id=${ARENA_CAMPAIGN_ID:-unset}"
record "model_key=${MODEL_KEY}"
record "base_image=${BASE_IMAGE}"
record "base_image_digest=${BASE_IMAGE_DIGEST}"
record "model_repo=${MODEL_REPO}"
record "model_revision=${MODEL_REVISION}"
record "bootstrapped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# D54: the official image runs as non-root USER hpd. Its own venv
# (/home/hpd/venv, on PATH) is writable by hpd, so this normally needs no
# change; the --user retry is a fallback for a pip target outside that venv
# (pip refuses --user inside a venv, so the retry is skipped there).
pip_install() {
  if "${PYTHON_BIN}" -m pip install --no-cache-dir "$@"; then
    return 0
  fi
  if "${PYTHON_BIN}" -c \
      "import sys; sys.exit(0 if sys.prefix == getattr(sys, 'base_prefix', sys.prefix) else 1)"; then
    echo "bootstrap: pip install failed; retrying with --user (not running in a venv)" >&2
    "${PYTHON_BIN}" -m pip install --no-cache-dir --user "$@"
  else
    echo "bootstrap: pip install failed inside a venv; --user is not a valid retry there" >&2
    return 1
  fi
}

# 1. Engine. Present in the official image; installed from the documented
#    prebuilt wheel only when it is not. Never `pip install -U`.
if "${PYTHON_BIN}" -c "import vllm" >/dev/null 2>&1; then
  record "vllm_source=official_image"
else
  record "vllm_source=official_prebuilt_wheel"
  pip_install "${HPD_VLLM_WHEEL}"
fi
record "vllm_version=$("${PYTHON_BIN}" -c 'import vllm; print(vllm.__version__)')"
pip_install "huggingface_hub[cli]==0.35.3"

# 2. Weights into the persistent volume cache: public repository, pinned
#    revision, no token, sha256 checked. Both the main model and the P-MTP
#    speculative model are required.
if [ -f "${WEIGHTS_ROOT}/arena-weights-revision.txt" ] \
   && [ "$(cat "${WEIGHTS_ROOT}/arena-weights-revision.txt")" = "${MODEL_REVISION}" ]; then
  record "weights_cache_hit=true"
  export ARENA_WEIGHTS_CACHE_HIT=true
else
  record "weights_cache_hit=false"
  HF_HUB_DISABLE_IMPLICIT_TOKEN=1 hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" \
    --local-dir "${WEIGHTS_ROOT}"
  printf '%s' "${MODEL_REVISION}" > "${WEIGHTS_ROOT}/arena-weights-revision.txt"
fi
echo "${WEIGHTS_LARGEST_SHA256}  ${WEIGHTS_ROOT}/${WEIGHTS_LARGEST_FILE}" | sha256sum -c -
echo "${PMTP_SHA256}  ${WEIGHTS_ROOT}/P-MTP/model.safetensors" | sha256sum -c -
test -f "${WEIGHTS_ROOT}/config.json"
test -f "${WEIGHTS_ROOT}/P-MTP/config.json"
record "weights_dir=${WEIGHTS_ROOT}"
record "weights_largest_file=${WEIGHTS_LARGEST_FILE}"
record "weights_largest_file_sha256=sha256:${WEIGHTS_LARGEST_SHA256}"
record "pmtp_model_sha256=sha256:${PMTP_SHA256}"

# 2b. Architecture preflight.
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. Assert the
# engine version AND that it can resolve this checkpoint, before serving starts.
#
# Floors (evidence in runtime.json.framework_floor_audit): the model card requires
# the customized build vllm-0.17.1+hpdparsing (prebuilt wheel above); the
# checkpoint declares model_type "internvl_chat", architectures
# ["InternVLChatModel"] and an auto_map, and upstream vllm v0.17.1's registry.py
# carries "InternVLChatModel": ("internvl", "InternVLChatModel").
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_ROOT}" "${PYTHON_BIN}" - <<'PY'
import json
import os
import sys
from pathlib import Path

PINNED_VLLM_PREFIX = "0.17.1"
PINNED_VLLM_LOCAL = "hpdparsing"
EXPECTED_MODEL_TYPE = "internvl_chat"
EXPECTED_ARCH = "InternVLChatModel"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


import vllm

if not vllm.__version__.startswith(PINNED_VLLM_PREFIX):
    fail(f"vllm is {vllm.__version__}, this runtime pins {PINNED_VLLM_PREFIX}")
if PINNED_VLLM_LOCAL not in vllm.__version__:
    fail(
        f"vllm is {vllm.__version__}: the model card requires the customized build "
        f"'{PINNED_VLLM_PREFIX}+{PINNED_VLLM_LOCAL}' (dynamic request forking, P-MTP "
        "speculative decoding), and a stock build would serve a different engine"
    )

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
if "auto_map" not in config:
    fail(
        f"model_type {model_type!r} is loaded through remote code, but the checkpoint "
        "carries no auto_map"
    )

from vllm.model_executor.models.registry import ModelRegistry

supported = set(ModelRegistry.get_supported_archs())
missing = [arch for arch in architectures if arch not in supported]
if missing:
    fail(f"vLLM {vllm.__version__} does not register {missing}; it cannot serve this checkpoint")

summary = (
    f"model_type={model_type} architectures={','.join(architectures)} "
    f"vllm={vllm.__version__}"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"
record "architecture_preflight=${ARCH_PREFLIGHT}"

# 3. Every version this bootstrap installed (masterplan section 38).
"${PYTHON_BIN}" -m pip freeze --all | LC_ALL=C sort > "${ARENA_ROOT}/bootstrap-pip-freeze.txt"
record "pip_freeze_sha256=sha256:$(sha256sum "${ARENA_ROOT}/bootstrap-pip-freeze.txt" | cut -d' ' -f1)"
record "python=$("${PYTHON_BIN}" -c 'import sys; print(sys.version.replace(chr(10), " "))')"
if command -v nvidia-smi >/dev/null 2>&1; then
  record "gpu=$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits | head -n 1)"
else
  record "gpu=unavailable"
fi

# 4. Hand off. entrypoint.sh is the single start path for both modes.
export MAX_PATCHES_WITH_RESIZE=true
export ARENA_WEIGHTS_DIR="${WEIGHTS_ROOT}"
export ARENA_RUNTIME_DIR="${RUNTIME_DIR}"
export PYTHONPATH="${PYTHONPATH:-${ARENA_ROOT}}"
export PYTHON_BIN
# D54: entrypoint.sh's own FATAL_FILE/SERVER_LOG defaults are /opt/arena/*; make
# them track the ARENA_ROOT actually chosen (which may have fallen back off
# /opt/arena) instead of a path this user may not be able to write.
export ARENA_FATAL_FILE="${ARENA_FATAL_FILE:-${ARENA_ROOT}/FATAL}"
export ARENA_MODEL_SERVER_LOG="${ARENA_MODEL_SERVER_LOG:-${ARENA_ROOT}/model-server.log}"
exec "${RUNTIME_DIR}/entrypoint.sh"
