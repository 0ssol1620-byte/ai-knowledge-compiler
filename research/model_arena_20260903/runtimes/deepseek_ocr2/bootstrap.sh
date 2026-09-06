#!/usr/bin/env bash
# DeepSeek-OCR-2 canary bootstrap (ARENA_CONTRACT.md section 11.3 item 4).
#
# This path exists so a canary can run before the baked image is built. It is
# never used for a Full Run: masterplan section 15.1 forbids installing a runtime
# during the run, and the controller records runtime_image_digest as
# "bootstrap:<runtime_bundle_sha256>" so bootstrap results can never be mistaken
# for baked ones.
#
# By the time this script runs, the bundle is already extracted at /opt/arena
# and the B2 template has exec'd this script with PYTHONPATH=/opt/arena and
# ARENA_RUNTIME_DIR=/opt/arena/runtime already exported -- it never downloads
# the bundle itself and never requires ARENA_BUNDLE_URL. It only installs the
# same pinned versions the baked Dockerfile installs and fetches weights.
#
# Starts from the official base image
#   pytorch/pytorch:2.6.0-cuda11.8-cudnn9-devel@sha256:01fe58a7663aff1dc7407043abbc524a9a9d149933cf4f9e4edb59bf1285079e

set -euo pipefail

MODEL_KEY=deepseek_ocr2
MODEL_REPO=deepseek-ai/DeepSeek-OCR-2
MODEL_REVISION=aaa02f3811945a91062062994c5c4a3f4c0af2b0
BASE_IMAGE="pytorch/pytorch:2.6.0-cuda11.8-cudnn9-devel@sha256:01fe58a7663aff1dc7407043abbc524a9a9d149933cf4f9e4edb59bf1285079e"
LARGEST_WEIGHT_FILE=model-00001-of-000001.safetensors
LARGEST_WEIGHT_SHA256=d8ff67a424ba6f4dd077885eb9d6a05d2537e76fe5491f0e2a9b712f8c8870fa

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
export MAX_JOBS=4

mkdir -p "${WEIGHTS_DIR}"

# 1. Runtime versions, identical to the baked image.
python -c "import torch, sys; v=torch.__version__.split('+')[0]; c=torch.version.cuda; sys.exit(0) if (v=='2.6.0' and c=='11.8') else sys.exit(f'base image ships torch {torch.__version__} cuda {c}, expected 2.6.0/11.8')"

pip install --no-cache-dir \
  transformers==4.46.3 \
  tokenizers==0.20.3 \
  einops==0.8.1 \
  addict==2.4.0 \
  easydict==1.13 \
  Pillow==11.1.0 \
  numpy==1.26.4 \
  packaging==24.2 \
  ninja==1.11.1.3
# flash-attn: install from a prebuilt wheel pinned by URL + sha256, never
# built from source. Bootstrap pod d8s9nypr5wrcz9 (2026-09-03 RunPod canary,
# receipt receipts/canary-driver-deepseek_ocr2.json) failed the old
# `--no-build-isolation flash-attn==2.7.3` line with
# `FileNotFoundError: [Errno 2] No such file or directory: 'git'`; even with
# git present that line compiles flash-attn from source on the pod
# (MAX_JOBS=4), tens of minutes of paid GPU time per canary and per Full Run
# pod. The official flash-attention v2.7.3 release
# (https://github.com/Dao-AILab/flash-attention/releases/tag/v2.7.3) ships a
# prebuilt wheel matching this image's exact stack: cu11, torch2.6, cp311,
# and cxx11abiFALSE -- the pip cu118 build of torch 2.6.0 (linux_x86_64,
# manylinux2014-tagged, per download.pytorch.org/whl/cu118) predates
# PyTorch's manylinux_2_28/new-ABI switch (torch 2.7+), so
# torch._C._GLIBCXX_USE_CXX11_ABI is False on this base image and the FALSE
# wheel is the correct match.
FLASH_ATTN_WHEEL=flash_attn-2.7.3+cu11torch2.6cxx11abiFALSE-cp311-cp311-linux_x86_64.whl
FLASH_ATTN_WHEEL_URL="https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.3/${FLASH_ATTN_WHEEL}"
FLASH_ATTN_WHEEL_SHA256=727fad58861999fcf23b400b9ae47ad8cb5ee9b0a88550b1d4ae0b629212c646
FLASH_ATTN_WHEEL_PATH="${ARENA_ROOT}/${FLASH_ATTN_WHEEL}"
python -c "import urllib.request; urllib.request.urlretrieve('${FLASH_ATTN_WHEEL_URL}', '${FLASH_ATTN_WHEEL_PATH}')"
if ! printf '%s  %s\n' "${FLASH_ATTN_WHEEL_SHA256}" "${FLASH_ATTN_WHEEL_PATH}" | sha256sum --check --strict; then
  echo "[arena] FATAL flash-attn wheel sha256 mismatch: ${FLASH_ATTN_WHEEL_URL}" >&2
  exit 64
fi
pip install --no-cache-dir "${FLASH_ATTN_WHEEL_PATH}"
rm -f "${FLASH_ATTN_WHEEL_PATH}"

python -c "from importlib.metadata import version as v; expected={'transformers':'4.46.3','tokenizers':'0.20.3','einops':'0.8.1','addict':'2.4.0','easydict':'1.13','pillow':'11.1.0','numpy':'1.26.4','flash-attn':'2.7.3'}; actual={n:v(n) for n in expected}; raise SystemExit(None if actual==expected else f'bootstrap dependency mismatch: {actual!r}')"

# 2. Pinned weights (revision + sha256 check), public repo, no token. Same
#    integrity checks the baked image applies at build time.
pip install --no-cache-dir --target /opt/arena/hfcli "huggingface_hub[cli]==1.17.0"
PYTHONPATH=/opt/arena/hfcli python -m huggingface_hub.cli.hf download \
  "${MODEL_REPO}" --revision "${MODEL_REVISION}" --local-dir "${WEIGHTS_DIR}"
printf '%s  %s\n' "${LARGEST_WEIGHT_SHA256}" "${WEIGHTS_DIR}/${LARGEST_WEIGHT_FILE}" \
  | sha256sum --check --strict

PYTHONPATH=${ARENA_ROOT} python "${ARENA_ROOT}/runtime/adapter.py" \
  --write-weights-receipt "${WEIGHTS_DIR}" \
  --repo "${MODEL_REPO}" \
  --revision "${MODEL_REVISION}"
find "${WEIGHTS_DIR}" -type f -exec chmod 0444 {} +

# 2b. Architecture preflight.
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. This runtime
# runs the model in-process in the worker (no separate server), so it gets the
# preflight half only - but the same failure would otherwise surface on the first
# page of a metered canary instead of here.
#
# Floors (evidence in runtime.json.framework_floor_audit): the model card requires
# torch==2.6.0, transformers==4.46.3, tokenizers==0.20.3, flash-attn==2.7.3; the
# checkpoint declares model_type "deepseek_vl_v2", architectures
# ["DeepseekOCR2ForCausalLM"], transformers_version 4.46.3, and an auto_map, so it
# is loaded through remote code rather than a transformers-native mapping.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_DIR}" python - <<'PY'
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

PINNED = {"transformers": "4.46.3", "tokenizers": "0.20.3"}
EXPECTED_MODEL_TYPE = "deepseek_vl_v2"
EXPECTED_ARCH = "DeepseekOCR2ForCausalLM"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


for name, pin in PINNED.items():
    installed = version(name)
    if installed != pin:
        fail(f"{name} is {installed}, this runtime pins {pin}")

weights = Path(os.environ["ARENA_PREFLIGHT_WEIGHTS_DIR"])
try:
    config = json.loads((weights / "config.json").read_text(encoding="utf-8"))
except OSError as exc:
    fail(f"cannot read {weights / 'config.json'}: {exc}")
model_type = config.get("model_type")
architectures = tuple(config.get("architectures") or ())
auto_map = config.get("auto_map") or {}
if model_type != EXPECTED_MODEL_TYPE or EXPECTED_ARCH not in architectures:
    fail(
        f"checkpoint declares model_type={model_type!r} architectures={architectures!r}, "
        f"runtime.json was written for {EXPECTED_MODEL_TYPE!r}/{EXPECTED_ARCH!r}"
    )

from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES

if model_type not in CONFIG_MAPPING_NAMES and "AutoConfig" not in auto_map:
    fail(
        f"transformers {version('transformers')} does not know model_type {model_type!r} "
        "and the checkpoint carries no auto_map.AutoConfig to load it from remote code"
    )
from transformers import AutoConfig

try:
    resolved = AutoConfig.from_pretrained(str(weights), trust_remote_code=True)
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"transformers cannot build a config for {model_type!r}: {type(exc).__name__}: {exc}")

summary = (
    f"model_type={model_type} architectures={','.join(architectures)} "
    f"config_class={type(resolved).__name__} loader=remote_code "
    f"transformers={version('transformers')}"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"

# 3. Bootstrap receipt (campaign, model_key, base image, versions, pip freeze
#    sha256) and the full pip-freeze sidecar. No URL, no token, no environment
#    dump.
pip freeze | LC_ALL=C sort > "${PIP_FREEZE_FILE}"
PIP_FREEZE_SHA256=$(sha256sum "${PIP_FREEZE_FILE}" | cut -d' ' -f1)

{
  echo "campaign=${ARENA_CAMPAIGN_ID:-unset}"
  echo "model_key=${MODEL_KEY}"
  echo "model_repo=${MODEL_REPO}"
  echo "model_revision=${MODEL_REVISION}"
  echo "base_image=${BASE_IMAGE}"
  echo "runtime_mode=bootstrap"
  echo "architecture_preflight=${ARCH_PREFLIGHT}"
  echo "bootstrap_script_sha256=$(sha256sum "${BASH_SOURCE[0]}" | cut -d' ' -f1)"
  echo "pip_freeze_sha256=${PIP_FREEZE_SHA256}"
  cat "${WEIGHTS_DIR}/arena-weights-receipt.json"
  echo
  python --version
  python -c "import torch; print('torch=' + torch.__version__); print('torch_cuda=' + str(torch.version.cuda))"
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader,nounits
} > "${RECEIPT}"
chmod 0444 "${RECEIPT}" "${PIP_FREEZE_FILE}"

echo "bootstrap complete: ${RECEIPT}" >&2
exec bash "${ARENA_ROOT}/runtime/entrypoint.sh"
