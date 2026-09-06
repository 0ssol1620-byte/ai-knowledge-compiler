#!/usr/bin/env bash
# Unlimited-OCR canary bootstrap (ARENA_CONTRACT.md section 11.3 item 4).
#
# Canary only. Masterplan section 15.1 forbids installing a runtime during a Full
# Run, and the controller records runtime_image_digest as
# "bootstrap:<runtime_bundle_sha256>" so a bootstrap result can never be mistaken
# for a baked one.
#
# By the time this script runs, the bundle is already extracted at /opt/arena
# and the B2 template has exec'd this script with PYTHONPATH=/opt/arena and
# ARENA_RUNTIME_DIR=/opt/arena/runtime already exported -- it never downloads
# the bundle itself and never requires ARENA_BUNDLE_URL. It only installs the
# exact torch/cuda-compatible pins the Dockerfile installs and fetches
# weights, into a venv, because Ubuntu 24.04 marks the system interpreter
# externally managed.
#
# Starts from the official base image
#   nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802

set -euo pipefail

MODEL_KEY=unlimited_ocr
MODEL_REPO=baidu/Unlimited-OCR
MODEL_REVISION=07dea832e22aefee32ad281d4b80551282e1c168
BASE_IMAGE="nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802"
LARGEST_WEIGHT_FILE=model-00001-of-000001.safetensors
LARGEST_WEIGHT_SHA256=2bc48a7a110061ea58fff65d3169367eebe3aee371ca6968dc2219c1b2855fc6

ARENA_ROOT=/opt/arena
VENV=${ARENA_ROOT}/venv
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

export DEBIAN_FRONTEND=noninteractive
export PIP_NO_CACHE_DIR=1
export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_ENABLE_HF_TRANSFER=0

mkdir -p "${WEIGHTS_DIR}"

apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates curl libglib2.0-0 libgl1
rm -rf /var/lib/apt/lists/*
python3 -m venv "${VENV}"
export PATH="${VENV}/bin:${PATH}"

# 1. Runtime versions, identical to the baked image and to the model card.
pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu129 \
  torch==2.10.0 torchvision==0.25.0
pip install --no-cache-dir \
  transformers==4.57.1 \
  Pillow==12.1.1 \
  matplotlib==3.10.8 \
  einops==0.8.2 \
  addict==2.4.0 \
  easydict==1.13 \
  pymupdf==1.27.2.2 \
  psutil==7.2.2

python -c "from importlib.metadata import version as v; expected={'torch':'2.10.0','torchvision':'0.25.0','transformers':'4.57.1','pillow':'12.1.1','matplotlib':'3.10.8','einops':'0.8.2','addict':'2.4.0','easydict':'1.13','pymupdf':'1.27.2.2','psutil':'7.2.2'}; actual={n:v(n).split('+')[0] for n in expected}; raise SystemExit(None if actual==expected else f'bootstrap dependency mismatch: {actual!r}')"

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
# preflight half only.
#
# Floors (evidence in runtime.json.framework_floor_audit): the model card requires
# torch==2.10.0, torchvision==0.25.0, transformers==4.57.1 - the exact pins above.
# The checkpoint declares model_type "unlimited-ocr", architectures
# ["UnlimitedOCRForCausalLM"] and an auto_map, and its transformers_version field
# says 4.46.3, older than the version the model card tells you to install; the
# card's pin wins, and the check below is what proves the remote code still
# resolves under it instead of assuming either number.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_DIR}" python - <<'PY'
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

PINNED = {"transformers": "4.57.1"}
EXPECTED_MODEL_TYPE = "unlimited-ocr"
EXPECTED_ARCH = "UnlimitedOCRForCausalLM"


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
  echo "image_mode=gundam"
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
