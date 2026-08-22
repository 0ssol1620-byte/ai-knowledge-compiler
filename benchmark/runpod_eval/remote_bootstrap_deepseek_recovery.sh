#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: remote_bootstrap_deepseek_recovery.sh RECEIPT_ROOT ARTIFACT_MANIFEST_RUNNER" >&2
  exit 2
fi

receipt_root="$1"
artifact_manifest_runner="$2"
venv="/workspace/folynta/venvs/deepseek-ocr2-r1"
cache="/workspace/folynta/cache/deepseek-ocr2-r1"
model_root="$cache/model"
state="$receipt_root/bootstrap-state.jsonl"
model_revision="aaa02f3811945a91062062994c5c4a3f4c0af2b0"
# The prior full manifest included Hugging Face client metadata whose bytes vary
# by client version. This hash covers the same 16 immutable model files while
# excluding only .cache download metadata.
artifact_sha256="77137d41428555c636b04ec5a1617e72c7e3e98afd81502b5c8659f6430421bc"
runtime_source_revision="2f3699ebbb96fa8af32212e8c170f2cc28730fad"

test -f "$artifact_manifest_runner"
test ! -e "$receipt_root"
mkdir -p "$receipt_root" "$(dirname "$venv")" "$cache"
printf '{"event":"bootstrap_started","unix":%s}\n' "$(date -u +%s)" >>"$state"
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total \
  --format=csv,noheader,nounits >"$receipt_root/gpu-identity.txt"

if [[ ! -x "$venv/bin/python" ]]; then
  /usr/bin/python3.11 -m pip install --upgrade 'uv==0.8.13'
  uv python install 3.12.9
  uv venv --python 3.12.9 --seed "$venv"
  "$venv/bin/python" -m pip install --upgrade 'pip==25.1.1' 'wheel==0.45.1' \
    'packaging==24.2' 'ninja==1.11.1.4'
  "$venv/bin/python" -m pip install \
    'torch==2.6.0' 'torchvision==0.21.0' 'torchaudio==2.6.0' \
    --index-url https://download.pytorch.org/whl/cu124
  "$venv/bin/python" -m pip install \
    'transformers==4.46.3' \
    'tokenizers==0.20.3' \
    'PyMuPDF==1.26.3' \
    'img2pdf==0.6.1' \
    'einops==0.8.1' \
    'easydict==1.13' \
    'addict==2.4.0' \
    'Pillow==11.3.0' \
    'numpy==2.1.3'
  MAX_JOBS=8 "$venv/bin/python" -m pip install \
    'flash-attn==2.7.3' --no-build-isolation
else
  printf '{"event":"existing_venv_reused","unix":%s}\n' \
    "$(date -u +%s)" >>"$state"
fi

export HF_HOME="$cache/huggingface"
"$venv/bin/python" - <<PY
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="deepseek-ai/DeepSeek-OCR-2",
    revision="$model_revision",
    local_dir="$model_root",
)
PY
"$venv/bin/python" "$artifact_manifest_runner" \
  --root "$model_root" \
  --output "$receipt_root/model-artifact-manifest.json" \
  --identity "deepseek-ai/DeepSeek-OCR-2@$model_revision" \
  --exclude-prefix .cache \
  >"$receipt_root/model-artifact-manifest.stdout.json"
observed_artifact="$(sha256sum "$receipt_root/model-artifact-manifest.json" | cut -d' ' -f1)"
if [[ "$observed_artifact" != "$artifact_sha256" ]]; then
  echo "DeepSeek-OCR-2 artifact manifest hash mismatch: $observed_artifact" >&2
  exit 35
fi

"$venv/bin/python" - <<PY >"$receipt_root/runtime-identity.json"
import importlib.metadata
import json
import platform
import torch

payload = {
    "schema": "folynta.deepseek-ocr2-runtime.v1",
    "model_revision": "$model_revision",
    "artifact_manifest_sha256": "sha256:$artifact_sha256",
    "runtime_source_revision": "$runtime_source_revision",
    "python": platform.python_version(),
    "torch": torch.__version__,
    "transformers": importlib.metadata.version("transformers"),
    "tokenizers": importlib.metadata.version("tokenizers"),
    "flash_attn": importlib.metadata.version("flash-attn"),
    "cuda_available": torch.cuda.is_available(),
    "cuda_device": torch.cuda.get_device_name(0),
    "model_path": "$model_root",
    "ground_truth_mounted": False,
}
if payload["python"] != "3.12.9":
    raise SystemExit("DeepSeek Python identity mismatch")
if payload["torch"] != "2.6.0+cu124":
    raise SystemExit("DeepSeek Torch identity mismatch")
if payload["transformers"] != "4.46.3" or payload["flash_attn"] != "2.7.3":
    raise SystemExit("DeepSeek package identity mismatch")
if not payload["cuda_available"]:
    raise SystemExit("DeepSeek CUDA control failed")
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
PY
printf '{"event":"runtime_ready","unix":%s}\n' "$(date -u +%s)" >>"$state"
printf '%s\n' "$venv/bin/python"
