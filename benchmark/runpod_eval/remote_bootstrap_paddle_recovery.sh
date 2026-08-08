#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: remote_bootstrap_paddle_recovery.sh BACKEND_CONFIG RECEIPT_ROOT ARTIFACT_MANIFEST_RUNNER" >&2
  exit 2
fi

backend_config="$1"
receipt_root="$2"
artifact_manifest_runner="$3"
venv="/workspace/folynta/venvs/paddle-fastdeploy-r1"
cache="/workspace/folynta/cache/paddle-fastdeploy-r1"
model_root="$cache/PaddleOCR-VL-1.6"
state="$receipt_root/bootstrap-state.jsonl"
service_log="$receipt_root/fastdeploy-service.log"
model_revision="66317acc4c9fc17bd154591ce650735cd2855f3e"
artifact_sha256="40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
before_patch="b50570cb2c13f29f2a7f8803d6bdb3368111e906152425f9666d0ca4818a396d"
after_patch="3be4e76c7e0fedd11c77eb5a704763a8c46ed0fd2ae1cf851e25aa08b7808fa9"

test -f "$backend_config"
test -f "$artifact_manifest_runner"
test ! -e "$receipt_root"
mkdir -p "$receipt_root" "$(dirname "$venv")" "$cache"
printf '{"event":"bootstrap_started","unix":%s}\n' "$(date -u +%s)" >>"$state"
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total \
  --format=csv,noheader,nounits >"$receipt_root/gpu-identity.txt"

if [[ ! -x "$venv/bin/python" ]]; then
  /usr/bin/python3.11 -m venv "$venv"
  "$venv/bin/python" -m pip install --upgrade 'pip==25.1.1'
  "$venv/bin/python" -m pip install \
    'paddlepaddle-gpu==3.2.1' \
    --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
  "$venv/bin/python" -m pip install 'paddleocr[doc-parser]==3.7.0'
  export PATH="$venv/bin:$PATH"
  "$venv/bin/paddleocr" install_genai_server_deps fastdeploy
else
  printf '{"event":"existing_venv_reused","unix":%s}\n' \
    "$(date -u +%s)" >>"$state"
fi

# PaddlePaddle 3.2.1 still reads FieldDescriptor.label while protobuf 7.x
# removed that compatibility attribute.  The transitive dependency resolved to
# protobuf 7.35.1 on 2026-08-06 and made an otherwise frozen runtime fail before
# loading any model weights, so keep this indirect dependency reproducible too.
"$venv/bin/python" -m pip install 'protobuf==6.33.6'

patch_file="$venv/lib/python3.11/site-packages/fastdeploy/input/text_processor.py"
test -f "$patch_file"
observed_before="$(sha256sum "$patch_file" | cut -d' ' -f1)"
if [[ "$observed_before" == "$before_patch" ]]; then
  sed -i \
    's/from paddleformers\.trl\.llm_utils import/from paddleformers.cli.utils.llm_utils import/' \
    "$patch_file"
elif [[ "$observed_before" != "$after_patch" ]]; then
  echo "unexpected FastDeploy compatibility target hash: $observed_before" >&2
  exit 31
fi
observed_after="$(sha256sum "$patch_file" | cut -d' ' -f1)"
if [[ "$observed_after" != "$after_patch" ]]; then
  echo "FastDeploy compatibility patch hash mismatch" >&2
  exit 32
fi

"$venv/bin/python" - <<'PY' >"$receipt_root/package-versions.json"
import importlib.metadata
import json

expected = {
    "paddlepaddle-gpu": "3.2.1",
    "paddleocr": "3.7.0",
    "paddlex": "3.7.2",
    "fastdeploy-gpu": "2.3.0",
    "paddleformers": "1.2.0",
    "protobuf": "6.33.6",
}
observed = {name: importlib.metadata.version(name) for name in expected}
if observed != expected:
    raise SystemExit(f"frozen Paddle runtime mismatch: {observed!r}")
print(json.dumps(observed, sort_keys=True, separators=(",", ":")))
PY
printf '{"event":"packages_verified","unix":%s}\n' "$(date -u +%s)" >>"$state"

export PADDLE_PDX_MODEL_SOURCE="HF"
export HF_HOME="$cache/huggingface"
export PADDLEX_HOME="$cache/paddlex"
"$venv/bin/python" - <<PY
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="PaddlePaddle/PaddleOCR-VL-1.6",
    revision="$model_revision",
    local_dir="$model_root",
)
PY
nohup "$venv/bin/paddleocr" genai_server \
  --model_name "PaddleOCR-VL-1.6-0.9B" \
  --model_dir "$model_root" \
  --host 127.0.0.1 \
  --port 8118 \
  --backend fastdeploy \
  --backend_config "$backend_config" \
  >"$service_log" 2>&1 < /dev/null &
service_pid=$!
printf '%s\n' "$service_pid" >"$receipt_root/fastdeploy-service.pid"

ready=false
for _attempt in $(seq 1 120); do
  if ! kill -0 "$service_pid" 2>/dev/null; then
    tail -200 "$service_log" >&2 || true
    echo "FastDeploy service exited before readiness" >&2
    exit 33
  fi
  if "$venv/bin/python" - <<'PY'
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8118/v1/models", timeout=5) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
  then
    ready=true
    break
  fi
  sleep 10
done
if [[ "$ready" != true ]]; then
  echo "FastDeploy service did not become ready" >&2
  exit 34
fi

# Bind the immutable Hugging Face revision to primary model bytes only. The
# local_dir `.cache` metadata varies across huggingface_hub releases and is not
# model content, so it is deliberately excluded from the stable identity.
"$venv/bin/python" "$artifact_manifest_runner" \
  --root "$model_root" \
  --output "$receipt_root/model-artifact-manifest.json" \
  --identity "PaddlePaddle/PaddleOCR-VL-1.6@$model_revision" \
  --exclude-prefix .cache \
  >"$receipt_root/model-artifact-manifest.stdout.json"
observed_artifact="$(sha256sum "$receipt_root/model-artifact-manifest.json" | cut -d' ' -f1)"
if [[ "$observed_artifact" != "$artifact_sha256" ]]; then
  echo "PaddleOCR-VL artifact manifest hash mismatch after readiness: $observed_artifact" >&2
  exit 35
fi
printf '{"event":"model_artifact_verified","unix":%s}\n' "$(date -u +%s)" >>"$state"

"$venv/bin/python" - <<PY >"$receipt_root/runtime-identity.json"
import hashlib
import json
import platform
from pathlib import Path

backend = Path(${backend_config@Q})
payload = {
    "schema": "folynta.paddleocr-vl16-fastdeploy-runtime.v1",
    "model_revision": "$model_revision",
    "artifact_manifest_sha256": "sha256:$artifact_sha256",
    "backend_config_sha256": "sha256:" + hashlib.sha256(backend.read_bytes()).hexdigest(),
    "python": platform.python_version(),
    "service_url": "http://127.0.0.1:8118/v1",
    "service_pid": $service_pid,
    "compatibility_patch_before_sha256": "sha256:$before_patch",
    "compatibility_patch_after_sha256": "sha256:$after_patch",
    "ground_truth_mounted": False,
}
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
PY
printf '{"event":"service_ready","service_pid":%s,"unix":%s}\n' \
  "$service_pid" "$(date -u +%s)" >>"$state"
printf '%s\n' "$service_pid"
