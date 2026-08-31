#!/usr/bin/env bash
set -euo pipefail

# Read-only runtime verification for the paddleocr-vl-1.6-fastdeploy-c8 image.
# Verification and reporting ONLY: this script never resolves, downloads, or
# mutates a dependency. It only inspects what the build already froze.
#
# Known-defect note (do NOT repeat, see infra/runpod/v6/pod_client.py around
# the FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256 environment key): that value is the
# canonical hash of the whole qualification-receipt OBJECT the control plane
# assembles, not the hash of any single baked file in this image. Comparing it
# against a file hash is the bug bootstrap_ovisocr2_m1.sh carries. This script
# reads and logs FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256 for traceability only --
# it is never validated against a file hash below. The baked-runtime-file
# identity check instead compares against BAKED_RECEIPT_SHA256_FILE, a
# constant written into this image at build time.

MODEL_ROOT="${FOLYNTA_MODEL_ROOT:-/opt/folynta/models/PaddleOCR-VL-1.6}"
ARTIFACT_MANIFEST_RUNNER="/opt/folynta/artifact_manifest.py"
MODEL_REVISION="${MODEL_REVISION:?MODEL_REVISION must be set (baked as an image ENV)}"
ARTIFACT_MANIFEST_SHA256="${ARTIFACT_MANIFEST_SHA256:?ARTIFACT_MANIFEST_SHA256 must be set (baked as an image ENV)}"
ARTIFACT_MANIFEST_IDENTITY="PaddlePaddle/PaddleOCR-VL-1.6@${MODEL_REVISION}"
BAKED_RECEIPT_FILE="/opt/folynta/baked-runtime-receipt.txt"
BAKED_RECEIPT_SHA256_FILE="/opt/folynta/baked-runtime-receipt.sha256"
VENV_PYTHON="/opt/folynta/venv/bin/python"

status=0
report() { printf '%s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; status=1; }

report "== paddleocr-vl-1.6-fastdeploy-c8 verify-runtime =="

# 1. Model files present.
if [[ -d "$MODEL_ROOT" ]] && [[ -n "$(find "$MODEL_ROOT" -type f -print -quit)" ]]; then
  report "model root present: $MODEL_ROOT"
else
  fail "model root missing or empty: $MODEL_ROOT"
fi

# 2. Recompute the artifact manifest and compare to the pinned hash.
if [[ -f "$ARTIFACT_MANIFEST_RUNNER" ]]; then
  manifest_tmp="$(mktemp)"
  if "$VENV_PYTHON" "$ARTIFACT_MANIFEST_RUNNER" \
       --root "$MODEL_ROOT" \
       --output "$manifest_tmp" \
       --identity "$ARTIFACT_MANIFEST_IDENTITY" \
       --exclude-prefix .cache \
       >/dev/null; then
    observed_artifact="$(sha256sum "$manifest_tmp" | cut -d' ' -f1)"
    if [[ "$observed_artifact" == "$ARTIFACT_MANIFEST_SHA256" ]]; then
      report "artifact manifest hash verified: sha256:${observed_artifact}"
    else
      fail "artifact manifest hash mismatch: observed=sha256:${observed_artifact} expected=sha256:${ARTIFACT_MANIFEST_SHA256}"
    fi
  else
    fail "artifact manifest runner exited non-zero"
  fi
  rm -f "$manifest_tmp"
else
  fail "artifact manifest runner missing: $ARTIFACT_MANIFEST_RUNNER"
fi

# 3. Installed package versions match the frozen pins (read-only lookup, no
#    resolution and no network access).
if "$VENV_PYTHON" - <<'PY'
import importlib.metadata
import sys

expected = {
    "paddlepaddle-gpu": "3.2.1",
    "paddleocr": "3.7.0",
    "paddlex": "3.7.2",
    "fastdeploy-gpu": "2.3.0",
    "paddleformers": "1.2.0",
    "protobuf": "6.33.6",
}
mismatches = {}
for name, expected_version in expected.items():
    try:
        observed_version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        observed_version = None
    if observed_version != expected_version:
        mismatches[name] = {"expected": expected_version, "observed": observed_version}

if mismatches:
    print(f"package version mismatch: {mismatches!r}", file=sys.stderr)
    raise SystemExit(1)
print(f"package versions verified: {expected!r}")
PY
then
  :
else
  fail "package version verification failed"
fi

# 4. Baked-runtime-file identity: compare against the build-time-baked
#    constant file only (see the known-defect note above for why this is
#    deliberately NOT FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256).
if [[ -f "$BAKED_RECEIPT_FILE" && -f "$BAKED_RECEIPT_SHA256_FILE" ]]; then
  baked_constant="$(tr -d '[:space:]' < "$BAKED_RECEIPT_SHA256_FILE")"
  observed_receipt="$(sha256sum "$BAKED_RECEIPT_FILE" | cut -d' ' -f1)"
  if [[ "$observed_receipt" == "$baked_constant" ]]; then
    report "baked-runtime-file hash verified: sha256:${observed_receipt}"
  else
    fail "baked-runtime-file hash mismatch: observed=sha256:${observed_receipt} baked_constant=sha256:${baked_constant}"
  fi
else
  fail "baked runtime receipt file or its constant hash file is missing"
fi

# Record-only: the qualification-receipt-object hash the control plane may
# pass in at pod-create time. This is NOT a file hash and is never validated
# against anything in this script -- it is logged for traceability only.
if [[ -n "${FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256:-}" ]]; then
  report "qualification receipt object hash (record only, not validated here): ${FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256}"
fi

# 5. GPU/CUDA identity report.
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,uuid,driver_version,memory.total \
    --format=csv,noheader,nounits
else
  fail "nvidia-smi not found"
fi

exit "$status"
