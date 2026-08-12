#!/usr/bin/env bash
set -euo pipefail

ROOT=/workspace/folynta-m1
SCRIPT_PATH=$(readlink -f "${BASH_SOURCE[0]}")
MODEL_ROOT=${FOLYNTA_MODEL_ROOT:-/opt/folynta/models/OvisOCR2}
REVISION=65c619d374b55d4152e85150fc1b003700bc1f0c
MODEL_SHA256=9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009
BAKED_RECEIPT=/opt/folynta/baked-runtime-receipt.txt

mkdir -p "$ROOT"
cd "$ROOT"

case "${FOLYNTA_IMAGE_DIGEST:-}" in
  *@sha256:????????????????????????????????????????????????????????????????) ;;
  *) echo "FOLYNTA_IMAGE_DIGEST must be immutable" >&2; exit 64 ;;
esac

test -f "$BAKED_RECEIPT"
test -f "$MODEL_ROOT/model.safetensors"
printf '%s  %s\n' "$MODEL_SHA256" "$MODEL_ROOT/model.safetensors" | sha256sum --check --strict

python3 - <<'PY'
from importlib.metadata import version

expected = {
    "vllm": "0.22.1",
    "huggingface-hub": "1.17.0",
    "pillow": "12.2.0",
    "transformers": "5.10.2",
}
actual = {name: version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"baked runtime version mismatch: {actual!r}")
PY

if [[ -n "${FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256:-}" ]]; then
  printf '%s  %s\n' \
    "${FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256#sha256:}" \
    "$BAKED_RECEIPT" | sha256sum --check --strict
fi

{
  echo "verification_script_sha256=$(sha256sum "$SCRIPT_PATH" | cut -d' ' -f1)"
  echo "image_digest=$FOLYNTA_IMAGE_DIGEST"
  echo "baked_runtime_receipt_sha256=$(sha256sum "$BAKED_RECEIPT" | cut -d' ' -f1)"
  echo "model_revision=$REVISION"
  echo "model_safetensors_sha256=$MODEL_SHA256"
  python3 --version
  python3 -m pip freeze | LC_ALL=C sort
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader,nounits
} > /workspace/folynta-m1/bootstrap-runtime-receipt.txt
