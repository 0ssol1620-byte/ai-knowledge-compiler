#!/usr/bin/env bash
# CANARY-ONLY bootstrap for MonkeyOCRv2-B-Parsing (ARENA_CONTRACT.md section 11.3).
#
# From the bare vllm/vllm-openai:v0.11.2 image: the B2 bundle template has already
# extracted the bundle to /opt/arena, symlinked
# /opt/arena/runtime -> /opt/arena/runtimes/monkeyocrv2_b and exported
# PYTHONPATH=/opt/arena + ARENA_RUNTIME_DIR before calling this script, so this
# script never downloads a bundle and never requires ARENA_BUNDLE_URL. It clones the
# official runtime at its exact commit, installs the same pins the baked Dockerfile
# installs, fetches the pinned weights, and writes /opt/arena/bootstrap-receipt.txt.
# A Full Run from this path needs a founder waiver.
set -euo pipefail

RUNTIME_DIR="${ARENA_RUNTIME_DIR:-/opt/arena/runtime}"
WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/workspace/arena/weights/monkeyocrv2_b}"
MONKEY_DIR="${ARENA_MONKEYOCRV2_DIR:-/opt/monkeyocrv2}"
MONKEYOCRV2_REVISION="${ARENA_MONKEYOCRV2_REVISION:-d46699fb6a4c71d61588e4a71fce03bff4f1ba33}"
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

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git ca-certificates
rm -rf /var/lib/apt/lists/*

git clone --filter=blob:none https://github.com/Yuliang-Liu/MonkeyOCRv2.git "${MONKEY_DIR}"
git -C "${MONKEY_DIR}" checkout --detach "${MONKEYOCRV2_REVISION}"
git -C "${MONKEY_DIR}" rev-parse HEAD > "${MONKEY_DIR}/.arena_revision"
test "$(cat "${MONKEY_DIR}/.arena_revision")" = "${MONKEYOCRV2_REVISION}"

# --- D58 upstream patch -----------------------------------------------------
# parsing/serve.py at d46699fb compares `installed == (0, 11)` where `installed`
# is `vllm_version_tuple()` — a full (major, minor, patch) tuple parsed from
# `importlib.metadata.version("vllm")`. A 3-tuple never equals a 2-tuple in
# Python, so the vendor's own documented legacy install ("pip install
# vllm==0.11.2", README "Document Parsing quick start", non-DFlash path) can
# never take the `== (0, 11)` branch and always falls through to
# `raise SystemExit(f"Unsupported vLLM version: {installed}. ...")`.
# See ARENA_CONTRACT.md section 11.7 D58 for the read URLs and evidence.
# Widen the vendor's own comparison to major.minor instead of skipping the
# check: still refuses vllm 0.10.x/0.12.x etc, only accepts 0.11.x as the
# vendor intended.
sed -i \
    's/^if installed == (0, 11):$/if installed[:2] == (0, 11):  # ARENA D58 patch: vllm_version_tuple() returns a full (major, minor, patch) tuple; upstream compared it to a 2-tuple, so no released 0.11.x ever matched/' \
    "${MONKEY_DIR}/parsing/serve.py"
grep -q '^if installed\[:2\] == (0, 11):' "${MONKEY_DIR}/parsing/serve.py"

# Same pin as runtimes/monkeyocrv2_b/Dockerfile; gradio is intentionally omitted.
python3 -m pip install --no-cache-dir "pypdfium2==5.10.1"

export PYTHONPATH="${PYTHONPATH:-/opt/arena}:${MONKEY_DIR}/parsing"
export ARENA_WEIGHTS_DIR="${WEIGHTS_DIR}"
export ARENA_MONKEYOCRV2_DIR="${MONKEY_DIR}"

python3 "${RUNTIME_DIR}/fetch_weights.py" --weights-dir "${WEIGHTS_DIR}" --manifest

# --- architecture preflight ------------------------------------------------
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly.
#
# This runtime is the sharpest case of that: vllm v0.11.2's registry.py does NOT
# carry MonkeyOCRv2ForCausalLM. The architecture only exists after the vendor's
# parsing/modeling/modeling_monkeyocrv2_vllm_011.py runs
# `ModelRegistry.register_model("MonkeyOCRv2ForCausalLM", MonkeyOCRv2ForCausalLM)`,
# which serve.py imports behind `if installed == (0, 11)`. So the preflight
# imports the same module the server does and then asks the registry, rather than
# trusting either half on its own.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_DIR}" python3 - <<'PY'
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

PINNED_VLLM_PREFIX = "0.11."
EXPECTED_MODEL_TYPE = "monkeyocrv2"
EXPECTED_ARCH = "MonkeyOCRv2ForCausalLM"
VENDOR_MODULE = "modeling.modeling_monkeyocrv2_vllm_011"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


import vllm

if not vllm.__version__.startswith(PINNED_VLLM_PREFIX):
    fail(
        f"vllm is {vllm.__version__}; the vendor's serve.py only registers "
        f"{EXPECTED_ARCH} on vllm 0.11.x"
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
        f"model_type {model_type!r} is not a transformers-native type and the checkpoint "
        "carries no auto_map, so nothing can build its config"
    )

import importlib

try:
    importlib.import_module(VENDOR_MODULE)
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"cannot import {VENDOR_MODULE}: {type(exc).__name__}: {exc}")

from vllm.model_executor.models.registry import ModelRegistry

supported = set(ModelRegistry.get_supported_archs())
missing = [arch for arch in architectures if arch not in supported]
if missing:
    fail(
        f"vLLM {vllm.__version__} still does not register {missing} after importing "
        f"{VENDOR_MODULE}; the server would die on start"
    )

summary = (
    f"model_type={model_type} architectures={','.join(architectures)} "
    f"registered_by={VENDOR_MODULE} transformers={version('transformers')} "
    f"vllm={vllm.__version__}"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"

{
    echo "campaign=${ARENA_CAMPAIGN_ID:-unset}"
    echo "model_key=monkeyocrv2_b"
    echo "base_image=vllm/vllm-openai:v0.11.2"
    echo "architecture_preflight=${ARCH_PREFLIGHT}"
    echo "runtime_repository=https://github.com/Yuliang-Liu/MonkeyOCRv2"
    echo "runtime_revision=${MONKEYOCRV2_REVISION}"
    echo "dflash_enabled=false"
    echo "bootstrapped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "python=$(python3 --version 2>&1)"
    echo "os=$(. /etc/os-release && echo "${PRETTY_NAME}")"
    echo "nvidia_driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
    echo "pip_freeze_sha256=$(python3 -m pip freeze | sha256sum | cut -d' ' -f1)"
    python3 - <<'PY'
import importlib
from importlib.metadata import PackageNotFoundError, version
for name in ("vllm", "torch", "transformers", "pypdfium2", "huggingface_hub", "PIL"):
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - receipt records the failure verbatim
        print(f"{name}=IMPORT_FAILED:{type(exc).__name__}")
        continue
    try:
        print(f"{name}={version(name)}")
    except PackageNotFoundError:
        print(f"{name}={getattr(module, '__version__', 'unknown')}")
core_runner = importlib.import_module("core_runner")
print("core_runner_prompts=" + ",".join(sorted(core_runner.ALL_PROMPT)))
PY
} > "${RECEIPT}"
python3 -m pip freeze > /opt/arena/bootstrap-pip-freeze.txt

echo "[arena] bootstrap receipt written to ${RECEIPT}" >&2
exec "${RUNTIME_DIR}/entrypoint.sh"
