#!/usr/bin/env bash
# PaddleOCR-VL 1.6 - CANARY-ONLY bootstrap (ARENA_CONTRACT.md section 11.3 item 4).
#
# Masterplan section 15.1 forbids installing a runtime during a Full Run: this
# path exists so a canary can qualify the model before the image is built, and
# the controller records runtime_image_digest as "bootstrap:<bundle sha256>".
# The full run requires the baked image.
#
# This script NEVER downloads the worker bundle and requires no
# bundle-URL variable of any kind. By the time it runs, the B2 start command has already
# verified and extracted the bundle into /opt/arena, created the symlink
# /opt/arena/runtime -> /opt/arena/runtimes/paddleocr_vl_1_6, and exported
# PYTHONPATH=/opt/arena and ARENA_RUNTIME_DIR=/opt/arena/runtime. All this
# script does is install the same pinned versions the Dockerfile installs,
# fetch the pinned weights, write the receipt, and hand over to entrypoint.sh.
#
# Start from the official base image only, digest-pinned in runtime.json:
#   ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:paddleocr3.6-nvidia-gpu
#     @sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
# That image already carries PaddleOCR-VL-1.6 (paddleocr 3.6.0 / paddlex 3.6.1,
# label 0006f78-ppocr3.6-pdx3.6), so nothing upgrades it here: this script
# installs only what the docs say that image still lacks for the vLLM genai
# server, exactly as the Dockerfile does - see provenance.json,
# paddleocr_version_finding.

set -euo pipefail

MODEL_KEY="paddleocr_vl_1_6"
MODEL_REPO="${ARENA_MODEL_REPO:-PaddlePaddle/PaddleOCR-VL-1.6}"
MODEL_REVISION="${ARENA_MODEL_REVISION:?ARENA_MODEL_REVISION is required}"
WEIGHTS_LARGEST_FILE="${ARENA_WEIGHTS_LARGEST_FILE:-model.safetensors}"
WEIGHTS_LARGEST_SHA256="${ARENA_WEIGHTS_LARGEST_SHA256:-85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db}"
PADDLEOCR_VERSION="3.6.0"
PADDLEX_VERSION="3.6.1"
FLASH_ATTN_WHEEL="https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.3.14/flash_attn-2.8.2+cu128torch2.8-cp310-cp310-linux_x86_64.whl"
BASE_IMAGE="${ARENA_BASE_IMAGE:-ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:paddleocr3.6-nvidia-gpu}"
BASE_IMAGE_DIGEST="${ARENA_BASE_IMAGE_DIGEST:-sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db}"

# D54: the bundle entrypoint (arena/worker/bundle.py START_CMD_TEMPLATE) already
# chose a writable ARENA_ROOT and exported it -- /opt/arena when writable, else
# $HOME/arena, else /tmp/arena -- because this model's official base image runs
# as non-root USER paddleocr (HOME=/home/paddleocr, confirmed from the image's
# OCI config) and cannot write /opt. Fall back to the /opt/arena literal only
# when this script is somehow invoked without that export (a baked image's own
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

# D54: the official image runs as non-root USER paddleocr with no venv on PATH
# (confirmed from the image's OCI config), so a pip install that needs to write
# the system site-packages can fail there. Retry with --user when the plain
# install fails and Python is not already running inside a venv (pip refuses
# --user inside one).
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

# 1. Same pinned stack as the Dockerfile, in the same order. Nothing upgrades
#    the vendor's paddleocr/paddlex pairing; the versions the image carries are
#    asserted, so a moved tag fails here rather than changing the model quietly.
#    No `pip install -U`.
"${PYTHON_BIN}" -c "import importlib.metadata as m, sys; \
found = {n: m.version(n) for n in ('paddleocr', 'paddlex')}; \
want = {'paddleocr': '${PADDLEOCR_VERSION}', 'paddlex': '${PADDLEX_VERSION}'}; \
sys.exit(0 if found == want else f'base image carries {found}, expected {want}')"
record "paddleocr_version=$("${PYTHON_BIN}" -c 'import paddleocr; print(paddleocr.__version__)')"
record "paddlex_version=$("${PYTHON_BIN}" -c 'import importlib.metadata as m; print(m.version("paddlex"))')"
pip_install "${FLASH_ATTN_WHEEL}"
# paddleocr's own installer, not a raw `pip install`: it shells out to pip
# internally for the genai-server backend deps. Not wrapped by pip_install
# above -- a --user retry cannot be forced through this CLI's own argv -- so a
# non-writable system site-packages here is a residual, unverified risk (D54).
paddleocr install_genai_server_deps vllm
pip_install "huggingface_hub[cli]==0.35.3"

# 2. Weights into the persistent volume cache: public repository, pinned
#    revision, no token, sha256 checked. A mismatch stops the pod.
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
record "weights_dir=${WEIGHTS_ROOT}"
record "weights_largest_file=${WEIGHTS_LARGEST_FILE}"
record "weights_largest_file_sha256=sha256:${WEIGHTS_LARGEST_SHA256}"

# 2b. Architecture preflight.
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. Assert the
# toolkit versions AND that both the toolkit and the genai server's vLLM can
# resolve this checkpoint, before serving starts.
#
# Floors (evidence in runtime.json.framework_floor_audit): the model card requires
# paddleocr[doc-parser] >= 3.6.0 and paddlepaddle >= 3.2.1, and the image carries
# paddleocr 3.6.0 / paddlex 3.6.1 (D43); the checkpoint declares model_type
# "paddleocr_vl", architectures ["PaddleOCRVLForConditionalGeneration"] and an
# auto_map. The VLM stage is served by `paddleocr genai_server --backend vllm`,
# so the vLLM installed just above by `paddleocr install_genai_server_deps vllm`
# is the one that must know it. D61 (real canary, pod rcre8rpux1oohv,
# 2026-09-04): that installer is `paddlex --install genai-vllm-server`, whose
# extra pins `vllm == 0.10.2` (PaddleX v3.6.1 setup.py), and PaddleX declares
# PaddleOCR-VL's `min_vllm_version` as 0.11.1 -- below that it ships the model
# out-of-tree and registers it itself through its `vllm.general_plugins` entry
# point (`register_paddlex_genai_models` ->
# paddlex.inference.genai.backends.vllm:register_models), which vLLM runs when
# the server process starts. A cold `ModelRegistry.get_supported_archs()` is
# therefore the wrong question; the preflight runs that same hook first and
# fails only if the architecture is still unknown afterwards.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_ROOT}" "${PYTHON_BIN}" - <<'PY'
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

EXPECTED_MODEL_TYPE = "paddleocr_vl"
EXPECTED_ARCH = "PaddleOCRVLForConditionalGeneration"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


try:
    from paddleocr import PaddleOCRVL  # noqa: F401 - resolving the class is the check
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"paddleocr {version('paddleocr')} cannot resolve PaddleOCRVL: {exc}")

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

try:
    import vllm
    from vllm.model_executor.models.registry import ModelRegistry
except Exception as exc:  # noqa: BLE001 - the genai server backend is vllm
    fail(f"the genai_server backend vllm is not importable: {type(exc).__name__}: {exc}")
supported = set(ModelRegistry.get_supported_archs())
missing = [arch for arch in architectures if arch not in supported]
registration = "vllm built-in registry"
if missing:
    # D61: same hook vLLM runs from paddlex's `vllm.general_plugins` entry point.
    try:
        from paddlex.inference.genai.backends.vllm import register_models

        register_models()
    except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
        fail(
            f"paddlex {version('paddlex')} vllm plugin hook (register_models) failed on "
            f"vLLM {vllm.__version__}: {type(exc).__name__}: {exc}"
        )
    supported = set(ModelRegistry.get_supported_archs())
    missing = [arch for arch in architectures if arch not in supported]
    registration = "paddlex vllm.general_plugins entry point (register_models)"
if missing:
    fail(
        f"the genai_server's vLLM {vllm.__version__} does not register {missing} even "
        "after paddlex's register_models hook; the VLM stage would die on start"
    )

summary = (
    f"model_type={model_type} architectures={','.join(architectures)} "
    f"paddleocr={version('paddleocr')} paddlex={version('paddlex')} "
    f"genai_server_vllm={vllm.__version__} arch_registration={registration!r}"
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
