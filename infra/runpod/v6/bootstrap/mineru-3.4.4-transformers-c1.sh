#!/usr/bin/env bash
set -euo pipefail

SYSTEM_PYTHON="${SYSTEM_PYTHON:-${PYTHON_BIN:-/usr/bin/python3.11}}"
PERSIST_ROOT="${PERSIST_ROOT:-/workspace/folynta}"
VENV_ROOT="${VENV_ROOT:-$PERSIST_ROOT/mineru-3.4.4-venv}"
CACHE_ROOT="${CACHE_ROOT:-$PERSIST_ROOT/cache}"
SOURCE_ROOT="${SOURCE_ROOT:-$PERSIST_ROOT/MinerU}"
MODEL_ROOT="${MODEL_ROOT:-/workspace/folynta/models/MinerU2.5-Pro-2605-1.2B}"
# The historical default above pointed MODEL_ROOT at the container disk. Model
# bytes are part of the resume cache, so override it onto the persistent volume.
MODEL_ROOT="${PERSIST_MODEL_ROOT:-$PERSIST_ROOT/models/MinerU2.5-Pro-2605-1.2B}"
RECEIPT_ROOT="${RECEIPT_ROOT:-$PERSIST_ROOT/receipts}"
MINERU_REVISION="79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
MODEL_REVISION="bff20d4ae2bf202df9f45284b4d43681555a97ed"

mkdir -p "$PERSIST_ROOT" "$(dirname "$SOURCE_ROOT")" "$MODEL_ROOT" \
  "$CACHE_ROOT/pip" "$CACHE_ROOT/huggingface" "$RECEIPT_ROOT"
export PIP_CACHE_DIR="$CACHE_ROOT/pip"
export HF_HOME="$CACHE_ROOT/huggingface"
export HUGGINGFACE_HUB_CACHE="$CACHE_ROOT/huggingface/hub"

# /workspace survives a normal RunPod stop/start while the container disk does
# not. Keep the expensive Python runtime with the model/cache so a stopped job
# can resume instead of cold-downloading the whole environment again.
if ! test -x "$VENV_ROOT/bin/python"; then
  rm -rf "$VENV_ROOT"
  "$SYSTEM_PYTHON" -m venv "$VENV_ROOT"
fi
PYTHON_BIN="$VENV_ROOT/bin/python"

"$PYTHON_BIN" -m pip install \
  --index-url https://download.pytorch.org/whl/cu128 \
  'torch==2.8.0' 'torchvision==0.23.0'

if ! test -d "$SOURCE_ROOT/.git" || \
  test "$(git -C "$SOURCE_ROOT" rev-parse HEAD 2>/dev/null || true)" != "$MINERU_REVISION"; then
  rm -rf "$SOURCE_ROOT"
  git clone --filter=blob:none --no-checkout https://github.com/opendatalab/MinerU.git "$SOURCE_ROOT"
  git -C "$SOURCE_ROOT" checkout --detach "$MINERU_REVISION"
fi
test "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" = "$MINERU_REVISION"

"$PYTHON_BIN" -m pip install \
  'accelerate==1.14.0' \
  'transformers==4.57.3' \
  'mineru-vl-utils==1.0.5' \
  "${SOURCE_ROOT}[core]"

MODEL_ROOT="$MODEL_ROOT" MODEL_REVISION="$MODEL_REVISION" "$PYTHON_BIN" - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="opendatalab/MinerU2.5-Pro-2605-1.2B",
    revision=os.environ["MODEL_REVISION"],
    local_dir=os.environ["MODEL_ROOT"],
)
PY

cat > /root/mineru.json <<EOF
{
  "models-dir": {"vlm": "$MODEL_ROOT"},
  "model-source": "local",
  "config_version": "1.3.2"
}
EOF

"$PYTHON_BIN" -m pip freeze --all | LC_ALL=C sort > "$RECEIPT_ROOT/pip-freeze.txt"
"$PYTHON_BIN" - <<'PY' > "$RECEIPT_ROOT/runtime-identity.json"
import importlib.metadata
import json
import platform
import subprocess
import sys

gpu = subprocess.run(
    [
        "nvidia-smi",
        "--query-gpu=name,uuid,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
value = {
    "schema": "folynta.mineru-runtime-identity.v1",
    "python": sys.version,
    "platform": platform.platform(),
    "gpu": gpu,
    "packages": {
        name: importlib.metadata.version(name)
        for name in ("mineru", "torch", "torchvision", "transformers", "accelerate", "mineru-vl-utils")
    },
    "mineru_revision": "79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7",
    "model_revision": "bff20d4ae2bf202df9f45284b4d43681555a97ed",
    "max_concurrent_requests": 1,
    "persistent_runtime_root": "/workspace/folynta/mineru-3.4.4-venv",
    "persistent_model_root": "/workspace/folynta/models/MinerU2.5-Pro-2605-1.2B",
}
print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
PY

sha256sum "$RECEIPT_ROOT/pip-freeze.txt" "$RECEIPT_ROOT/runtime-identity.json" \
  > "$RECEIPT_ROOT/runtime-files.sha256"
touch "$RECEIPT_ROOT/BOOTSTRAP_COMPLETE"
