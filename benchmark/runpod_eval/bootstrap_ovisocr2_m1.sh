#!/usr/bin/env bash
set -euo pipefail

ROOT=/workspace/folynta-m1
VENV=/workspace/ovis-venv
MODEL_ROOT=/workspace/models/OvisOCR2
REVISION=65c619d374b55d4152e85150fc1b003700bc1f0c

cd "$ROOT"
python3 -m pip install --no-cache-dir --break-system-packages 'uv==0.12.1'
uv venv --python 3.11 --seed "$VENV"
UV_TORCH_BACKEND=cu129 uv pip install \
  --python "$VENV/bin/python" \
  --torch-backend=cu129 \
  'vllm==0.22.1' \
  'huggingface-hub==0.36.0' \
  'pillow==12.3.0'

"$VENV/bin/hf" download \
  ATH-MaaS/OvisOCR2 \
  --revision "$REVISION" \
  --local-dir "$MODEL_ROOT"

{
  echo "bootstrap_sha256=$(sha256sum "$ROOT/bootstrap_ovisocr2_m1.sh" | cut -d' ' -f1)"
  echo "base_image=runpod/pytorch@sha256:60baa36d3fb6b98fd4f4ece6b96776c83c01a8b7c540e54460ab4d496816141f"
  echo "model_revision=$REVISION"
  "$VENV/bin/python" --version
  uv --version
  "$VENV/bin/python" -m pip freeze | LC_ALL=C sort
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader,nounits
} > /workspace/folynta-m1/bootstrap-runtime-receipt.txt
