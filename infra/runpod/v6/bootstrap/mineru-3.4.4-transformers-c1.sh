#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.11}"
SOURCE_ROOT="${SOURCE_ROOT:-/workspace/folynta/MinerU}"
MODEL_ROOT="${MODEL_ROOT:-/workspace/folynta/models/MinerU2.5-Pro-2605-1.2B}"
RECEIPT_ROOT="${RECEIPT_ROOT:-/workspace/folynta/receipts}"
MINERU_REVISION="79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
MODEL_REVISION="bff20d4ae2bf202df9f45284b4d43681555a97ed"

mkdir -p "$(dirname "$SOURCE_ROOT")" "$MODEL_ROOT" "$RECEIPT_ROOT"

"$PYTHON_BIN" -m pip install --no-cache-dir \
  --index-url https://download.pytorch.org/whl/cu128 \
  'torch==2.8.0' 'torchvision==0.23.0'

rm -rf "$SOURCE_ROOT"
git clone --filter=blob:none --no-checkout https://github.com/opendatalab/MinerU.git "$SOURCE_ROOT"
git -C "$SOURCE_ROOT" checkout --detach "$MINERU_REVISION"
test "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" = "$MINERU_REVISION"

"$PYTHON_BIN" -m pip install --no-cache-dir \
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
}
print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
PY

sha256sum "$RECEIPT_ROOT/pip-freeze.txt" "$RECEIPT_ROOT/runtime-identity.json" \
  > "$RECEIPT_ROOT/runtime-files.sha256"
touch "$RECEIPT_ROOT/BOOTSTRAP_COMPLETE"
