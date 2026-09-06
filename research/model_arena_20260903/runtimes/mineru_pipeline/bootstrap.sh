#!/usr/bin/env bash
# MinerU pipeline backend - CANARY-ONLY bootstrap (ARENA_CONTRACT.md section 11.3 item 4).
#
# Masterplan section 15.1 forbids installing a runtime during a Full Run; this
# path exists only so a canary can qualify the model before the image is built.
#
# This script NEVER downloads the worker bundle and requires no
# bundle-URL variable of any kind. The B2 start command has already verified and extracted the
# bundle into /opt/arena, created the symlink /opt/arena/runtime ->
# /opt/arena/runtimes/mineru_pipeline, and exported PYTHONPATH=/opt/arena and
# ARENA_RUNTIME_DIR=/opt/arena/runtime.
#
# Start from the official base image only, digest-pinned in runtime.json:
#   vllm/vllm-openai:v0.21.0
#     @sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9
# which is the base MinerU's own docker/global/Dockerfile uses.

set -euo pipefail

MODEL_KEY="mineru_pipeline"
MINERU_REVISION="${ARENA_RUNTIME_SOURCE_REVISION:-fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883}"
MODEL_REPO="${ARENA_MODEL_REPO:-opendatalab/PDF-Extract-Kit-1.0}"
MODEL_REVISION="${ARENA_MODEL_REVISION:?ARENA_MODEL_REVISION is required}"
WEIGHTS_LARGEST_FILE="${ARENA_WEIGHTS_LARGEST_FILE:-models/MFR/unimernet_hf_small_2503/model.safetensors}"
WEIGHTS_LARGEST_SHA256="${ARENA_WEIGHTS_LARGEST_SHA256:-9244e2565585c0f89bc3a6eeeea080ef3c588375fc0d536074fe88e80b917cda}"
BASE_IMAGE="${ARENA_BASE_IMAGE:-vllm/vllm-openai:v0.21.0}"
BASE_IMAGE_DIGEST="${ARENA_BASE_IMAGE_DIGEST:-sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9}"

ARENA_ROOT="/opt/arena"
RUNTIME_DIR="${ARENA_RUNTIME_DIR:-${ARENA_ROOT}/runtime}"
WEIGHTS_ROOT="/workspace/arena/weights/${MODEL_KEY}"
RECEIPT="${ARENA_ROOT}/bootstrap-receipt.txt"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -f "${RUNTIME_DIR}/entrypoint.sh" ]; then
  echo "bootstrap: ${RUNTIME_DIR}/entrypoint.sh is missing; the bundle was not laid out as section 11.3 requires" >&2
  exit 1
fi

mkdir -p "${WEIGHTS_ROOT}" /workspace/arena/results

: > "${RECEIPT}"
record() { printf '%s\n' "$*" >> "${RECEIPT}"; }

record "campaign_id=${ARENA_CAMPAIGN_ID:-unset}"
record "model_key=${MODEL_KEY}"
record "base_image=${BASE_IMAGE}"
record "base_image_digest=${BASE_IMAGE_DIGEST}"
record "mineru_git_revision=${MINERU_REVISION}"
record "model_repo=${MODEL_REPO}"
record "model_revision=${MODEL_REVISION}"
record "bootstrapped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 1. Fonts and libgl, exactly as MinerU's own image installs them.
apt-get update
# git: the vllm/vllm-openai image ships none, and pip needs it to fetch the
# pinned MinerU revision below (real canary 2026-09-03: "Cannot find command git").
apt-get install -y --no-install-recommends fonts-noto-core fonts-noto-cjk fontconfig libgl1 git
fc-cache -fv
rm -rf /var/lib/apt/lists/*

# 2. Same pins as the Dockerfile, in the same order. Never `pip install -U`.
"${PYTHON_BIN}" -m pip install --no-cache-dir --break-system-packages \
  "mineru[core] @ git+https://github.com/opendatalab/MinerU.git@${MINERU_REVISION}"
"${PYTHON_BIN}" -m pip install --no-cache-dir --break-system-packages \
  "transformers==4.57.3" "accelerate==1.14.0" "mineru-vl-utils==1.0.5" \
  "huggingface_hub[cli]==0.35.3"

# 3. Weights into the persistent volume cache: public repository, pinned
#    revision, no token, sha256 checked.
if [ -f "${WEIGHTS_ROOT}/arena-weights-revision.txt" ] \
   && [ "$(cat "${WEIGHTS_ROOT}/arena-weights-revision.txt")" = "${MODEL_REVISION}" ]; then
  record "weights_cache_hit=true"
  export ARENA_WEIGHTS_CACHE_HIT=true
else
  record "weights_cache_hit=false"
  # D59: `hf download`'s --include is argparse nargs="*", not action="append" -
  # huggingface_hub 0.35.3's commands/download.py declares
  #   download_parser.add_argument("--include", nargs="*", type=str, ...)
  # so seven repeated `--include PATTERN` flags do not accumulate: each flag
  # replaces the previous value and only the LAST pattern survives. The real
  # canary's `hf download` therefore fetched only
  # models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx, returned exit 0
  # (a "successful" download of that one file), and never touched
  # models/MFR/unimernet_hf_small_2503/model.safetensors - so the checksum
  # below failed with "could not be read" rather than a hash mismatch.
  # snapshot_download's allow_patterns takes the whole list in one call, so all
  # seven patterns are honoured together.
  WEIGHTS_FETCH_SUMMARY="$(ARENA_WEIGHTS_ROOT="${WEIGHTS_ROOT}" ARENA_MODEL_REPO="${MODEL_REPO}" \
    ARENA_MODEL_REVISION="${MODEL_REVISION}" HF_HUB_DISABLE_IMPLICIT_TOKEN=1 "${PYTHON_BIN}" - <<'PY'
import os
import sys

from huggingface_hub import snapshot_download

ALLOW_PATTERNS = [
    "models/Layout/PP-DocLayoutV2/*",
    "models/MFR/unimernet_hf_small_2503/*",
    "models/MFR/pp_formulanet_plus_m/*",
    "models/OCR/paddleocr_torch/*",
    "models/TabRec/SlanetPlus/slanet-plus.onnx",
    "models/TabRec/UnetStructure/unet.onnx",
    "models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx",
]


def fail(reason: str) -> None:
    print(f"[arena] FATAL weights: {reason}", file=sys.stderr)
    raise SystemExit(64)


local_dir = os.environ["ARENA_WEIGHTS_ROOT"]
try:
    snapshot_download(
        repo_id=os.environ["ARENA_MODEL_REPO"],
        revision=os.environ["ARENA_MODEL_REVISION"],
        local_dir=local_dir,
        allow_patterns=ALLOW_PATTERNS,
    )
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"snapshot_download failed: {type(exc).__name__}: {exc}")

fetched = [
    os.path.join(root, name)
    for root, _dirs, files in os.walk(local_dir)
    for name in files
    if name != "arena-weights-revision.txt"
]
if not fetched:
    fail(f"snapshot_download completed but no files matched {ALLOW_PATTERNS} under {local_dir}")

largest = max(fetched, key=os.path.getsize)
summary = f"files={len(fetched)} largest={os.path.relpath(largest, local_dir)} largest_bytes={os.path.getsize(largest)}"
print(f"[arena] weights fetch PASS {summary}", file=sys.stderr)
print(summary)
PY
  )"
  record "weights_fetch_summary=${WEIGHTS_FETCH_SUMMARY}"
fi
echo "${WEIGHTS_LARGEST_SHA256}  ${WEIGHTS_ROOT}/${WEIGHTS_LARGEST_FILE}" | sha256sum -c - || {
  echo "[arena] FATAL weights: checksum verification failed for ${WEIGHTS_ROOT}/${WEIGHTS_LARGEST_FILE}" >&2
  exit 64
}
# The revision marker is written only after the checksum above passes, never
# before - D59: on the real canary's restart, the marker (written unconditionally
# right after `hf download` returned 0) made the second attempt take the
# cache-hit branch and skip downloading entirely, so the missing file was never
# retried.
printf '%s' "${MODEL_REVISION}" > "${WEIGHTS_ROOT}/arena-weights-revision.txt"
record "weights_dir=${WEIGHTS_ROOT}"
record "weights_largest_file=${WEIGHTS_LARGEST_FILE}"
record "weights_largest_file_sha256=sha256:${WEIGHTS_LARGEST_SHA256}"

printf '{"models-dir": {"pipeline": "%s"}, "model-source": "local", "config_version": "1.3.2"}\n' \
  "${WEIGHTS_ROOT}" > "${ARENA_ROOT}/mineru.json"

# 3b. Architecture preflight.
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. This runtime
# starts no model server, so it gets the preflight half only - but the same class
# of failure (a toolkit that cannot resolve what it was asked to load) still costs
# a whole canary if it is discovered on the first page instead of here.
#
# There is no single VLM checkpoint to name: opendatalab/PDF-Extract-Kit-1.0 at the
# pinned revision has no top-level config.json - its root holds only models/,
# README.md and .gitattributes, and each stage carries its own config under
# models/. So the equivalent check is the toolkit's own: MinerU 3.4.5 pins
# transformers >= 4.57.3, < 5.0.0 (pyproject [pipeline] extra), the pinned
# transformers must be installed, do_parse must import, and every model directory
# the pipeline backend loads must be on disk.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_ROOT}" "${PYTHON_BIN}" - <<'PY'
import os
import sys
from importlib.metadata import version
from pathlib import Path

PINNED = {"transformers": "4.57.3", "accelerate": "1.14.0", "mineru-vl-utils": "1.0.5"}
PIPELINE_MODEL_DIRS = (
    "models/Layout/PP-DocLayoutV2",
    "models/MFR/unimernet_hf_small_2503",
    "models/MFR/pp_formulanet_plus_m",
    "models/OCR/paddleocr_torch",
)


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


for name, pin in PINNED.items():
    installed = version(name)
    if installed != pin:
        fail(f"{name} is {installed}, this runtime pins {pin}")

try:
    from mineru.cli.common import do_parse  # noqa: F401 - resolving it is the check
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"cannot import mineru.cli.common.do_parse: {type(exc).__name__}: {exc}")

weights = Path(os.environ["ARENA_PREFLIGHT_WEIGHTS_DIR"])
absent = [name for name in PIPELINE_MODEL_DIRS if not (weights / name).is_dir()]
if absent:
    fail(f"the pipeline backend's model directories are missing under {weights}: {absent}")

summary = (
    f"backend=pipeline checkpoint_config=none-at-repo-root "
    f"model_dirs={len(PIPELINE_MODEL_DIRS)} mineru={version('mineru')} "
    f"transformers={version('transformers')}"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"
record "architecture_preflight=${ARCH_PREFLIGHT}"

# 4. Every version this bootstrap installed (masterplan section 38).
"${PYTHON_BIN}" -m pip freeze --all | LC_ALL=C sort > "${ARENA_ROOT}/bootstrap-pip-freeze.txt"
record "pip_freeze_sha256=sha256:$(sha256sum "${ARENA_ROOT}/bootstrap-pip-freeze.txt" | cut -d' ' -f1)"
record "mineru_declared_version=$("${PYTHON_BIN}" -c 'import importlib.metadata as m; print(m.version("mineru"))')"
record "python=$("${PYTHON_BIN}" -c 'import sys; print(sys.version.replace(chr(10), " "))')"
if command -v nvidia-smi >/dev/null 2>&1; then
  record "gpu=$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits | head -n 1)"
else
  record "gpu=unavailable"
fi

# 5. Hand off. entrypoint.sh is the single start path for both modes.
export MINERU_MODEL_SOURCE=local
export MINERU_TOOLS_CONFIG_JSON="${ARENA_ROOT}/mineru.json"
export OMP_NUM_THREADS=1
export ARENA_WEIGHTS_DIR="${WEIGHTS_ROOT}"
export ARENA_RUNTIME_DIR="${RUNTIME_DIR}"
export PYTHONPATH="${PYTHONPATH:-${ARENA_ROOT}}"
export PYTHON_BIN
exec "${RUNTIME_DIR}/entrypoint.sh"
