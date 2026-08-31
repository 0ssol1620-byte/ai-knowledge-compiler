#!/usr/bin/env bash
set -euo pipefail

# Install-free runtime verification for the mineru-3.4.4-vlm-c1 baked image.
# Everything this script checks was already installed/downloaded at build
# time; this script only recomputes hashes and reads baked-in receipts. It
# must never run a package-manager or model-download command of any kind --
# infra/runpod/v6/pod_client.py rejects any dockerEntrypoint/dockerStartCmd
# containing the disallowed runtime-install command markers it defines
# (_RUNTIME_INSTALL_MARKERS, pod_client.py lines ~31-40), and this script is a
# candidate for exactly that execution path.

SCRIPT_PATH=$(readlink -f "${BASH_SOURCE[0]}")
SOURCE_ROOT=${FOLYNTA_SOURCE_ROOT:-/opt/folynta/MinerU}
MODEL_ROOT=${FOLYNTA_MODEL_ROOT:-/opt/folynta/models/MinerU2.5-Pro-2605-1.2B}
ARTIFACT_MANIFEST_TOOL=/opt/folynta/artifact_manifest.py
BAKED_RECEIPT=/opt/folynta/baked-runtime-receipt.txt
BAKED_RECEIPT_SHA256_FILE=/opt/folynta/baked-runtime-receipt.sha256
OUT_DIR=${FOLYNTA_VERIFY_OUT_DIR:-/workspace/folynta-mineru}

: "${SOURCE_REVISION:?SOURCE_REVISION must be baked into the image}"
: "${MODEL_REVISION:?MODEL_REVISION must be baked into the image}"
: "${ARTIFACT_MANIFEST_SHA256:?ARTIFACT_MANIFEST_SHA256 must be baked into the image}"

case "${FOLYNTA_IMAGE_DIGEST:-}" in
  *@sha256:????????????????????????????????????????????????????????????????) ;;
  *) echo "FOLYNTA_IMAGE_DIGEST must be immutable" >&2; exit 64 ;;
esac

mkdir -p "$OUT_DIR"

# --- 1. source-tree identity: SOURCE_REVISION only, never MODEL_REVISION. ---
test -d "$SOURCE_ROOT/.git"
actual_source_revision=$(git -C "$SOURCE_ROOT" rev-parse HEAD)
if [[ "$actual_source_revision" != "$SOURCE_REVISION" ]]; then
  echo "source revision mismatch: $actual_source_revision != $SOURCE_REVISION" >&2
  exit 65
fi

# --- 2. model artifact manifest: MODEL_REVISION only, never SOURCE_REVISION. ---
python3 "$ARTIFACT_MANIFEST_TOOL" \
  --root "$MODEL_ROOT" \
  --output "$OUT_DIR/model-artifact-manifest.json" \
  --identity "opendatalab/MinerU2.5-Pro-2605-1.2B@$MODEL_REVISION" \
  > "$OUT_DIR/model-artifact-manifest-receipt.json"
python3 - "$OUT_DIR/model-artifact-manifest-receipt.json" "$ARTIFACT_MANIFEST_SHA256" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    receipt = json.load(handle)
expected = sys.argv[2]
if receipt["sha256"] != expected:
    raise SystemExit(f"artifact manifest sha256 mismatch: {receipt['sha256']} != {expected}")
PY

# --- 3. installed package versions (no reinstall, read-only check). ---
python3 - <<'PY'
from importlib.metadata import version

pinned = {
    "torch": "2.8.0",
    "torchvision": "0.23.0",
    "accelerate": "1.14.0",
    "transformers": "4.57.3",
    "mineru-vl-utils": "1.0.5",
}
actual_pinned = {name: version(name) for name in pinned}
if actual_pinned != pinned:
    raise SystemExit(f"runtime version mismatch: {actual_pinned!r}")
# mineru is installed from the pinned SOURCE_REVISION checkout, not a released
# version number, so it is reported below but not asserted against a fixed
# string.
version("mineru")
PY

# --- 4. baked-runtime-file hash: compared ONLY against the build-time
#     constant baked into this image. FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256 (if
#     a provider sets it) names the canonical hash of the whole
#     qualification-receipt OBJECT -- see infra/runpod/v6/pod_client.py
#     PodCreateSpec.provider_payload and
#     infra/runpod/v6/runtime_qualification.py
#     BakedRuntimeQualification.receipt_sha256 = canonical_sha256(value) over
#     the full mapping -- never a single file's hash.
#     benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh (lines ~37-41) checks a
#     file hash against that env var; that is the confirmed defect this script
#     does not repeat. The env var is read below only to log it.
test -f "$BAKED_RECEIPT"
test -f "$BAKED_RECEIPT_SHA256_FILE"
baked_receipt_actual_sha256=$(sha256sum "$BAKED_RECEIPT" | cut -d' ' -f1)
baked_receipt_expected_sha256=$(cat "$BAKED_RECEIPT_SHA256_FILE")
if [[ "$baked_receipt_actual_sha256" != "$baked_receipt_expected_sha256" ]]; then
  echo "baked runtime receipt file hash mismatch: $baked_receipt_actual_sha256 != $baked_receipt_expected_sha256" >&2
  exit 66
fi

# --- 5. GPU/CUDA identity: reported for the receipt, not gated on. ---
gpu_identity=$(nvidia-smi --query-gpu=name,uuid,driver_version,memory.total --format=csv,noheader,nounits)

{
  echo "verification_script_sha256=$(sha256sum "$SCRIPT_PATH" | cut -d' ' -f1)"
  echo "image_digest=$FOLYNTA_IMAGE_DIGEST"
  echo "source_revision=$SOURCE_REVISION"
  echo "model_revision=$MODEL_REVISION"
  echo "artifact_manifest_sha256=$ARTIFACT_MANIFEST_SHA256"
  echo "baked_runtime_receipt_file_sha256=$baked_receipt_actual_sha256"
  echo "provider_qualification_receipt_object_sha256_logged_only=${FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256:-<unset>}"
  python3 --version
  python3 -m pip freeze | LC_ALL=C sort
  echo "gpu=$gpu_identity"
} > "$OUT_DIR/verify-runtime-receipt.txt"
