#!/usr/bin/env bash
# MinerU VLM - CANARY-ONLY bootstrap (ARENA_CONTRACT.md section 11.3 item 4).
#
# Masterplan section 15.1 forbids installing a runtime during a Full Run; this
# path exists only so a canary can qualify the model before the image is built.
#
# This script NEVER downloads the worker bundle and requires no
# bundle-URL variable of any kind. The B2 start command has already verified and extracted the
# bundle into /opt/arena, created the symlink /opt/arena/runtime ->
# /opt/arena/runtimes/mineru_vlm, and exported PYTHONPATH=/opt/arena and
# ARENA_RUNTIME_DIR=/opt/arena/runtime.
#
# Start from the official base image only, digest-pinned in runtime.json:
#   vllm/vllm-openai:v0.21.0
#     @sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9
#
# MASTERPLAN SECTION 14: concurrency 1 per worker, replicas only. Nothing here
# raises it, and adapter.py refuses any other value at load time.

set -euo pipefail

MODEL_KEY="mineru_vlm"
MINERU_REVISION="${ARENA_RUNTIME_SOURCE_REVISION:-fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883}"
MODEL_REPO="${ARENA_MODEL_REPO:-opendatalab/MinerU2.5-Pro-2605-1.2B}"
MODEL_REVISION="${ARENA_MODEL_REVISION:?ARENA_MODEL_REVISION is required}"
WEIGHTS_LARGEST_FILE="${ARENA_WEIGHTS_LARGEST_FILE:-model.safetensors}"
WEIGHTS_LARGEST_SHA256="${ARENA_WEIGHTS_LARGEST_SHA256:-abf8681ca63b8dec7b67de257af47b821f179442f72998d0696ae2ed9232a5f0}"
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
record "concurrency_per_worker=1"
record "concurrency_scale=replicas_only"
record "bootstrapped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 1. Fonts and libgl, exactly as MinerU's own image installs them.
apt-get update
# git: the vllm/vllm-openai image ships none, and pip needs it to fetch the
# pinned MinerU revision below (real canary 2026-09-03: "Cannot find command git").
apt-get install -y --no-install-recommends fonts-noto-core fonts-noto-cjk fontconfig libgl1 git
fc-cache -fv
rm -rf /var/lib/apt/lists/*

# 2. The vendor's own stack, nothing more. Until D68 this step re-pinned
#    transformers==4.57.3, accelerate==1.14.0, mineru-vl-utils==1.0.5 and
#    huggingface_hub[cli]==0.35.3 on top of mineru[core] (pins carried over
#    from a 2026-08 local smoke test of the transformers engine). The real
#    canary on pod 8sb0n4zqo8tapn printed the diff those pins made against
#    what mineru[core] itself resolves on the vllm/vllm-openai:v0.21.0 image:
#    transformers 4.57.6 -> 4.57.3, mineru_vl_utils 1.2.1 -> 1.0.5,
#    huggingface_hub 0.36.2 -> 0.35.3, accelerate 1.13.0 -> 1.14.0 -- and the
#    VLM answered every layout prompt with ']]<|><|><|><|>' on that pinned
#    stack (pods r0yal3hocpipsm, 733khrz3mcscrw, 8sb0n4zqo8tapn). The vendor
#    Dockerfile for this exact MinerU tag is `FROM vllm/vllm-openai:v0.21.0`
#    + `pip install -U 'mineru[core]>=3.4.0'` and nothing else, so that is
#    what runs here now; the resolved versions are recorded below. Still
#    never `pip install -U` of anything the pinned MinerU revision does not
#    ask for itself.
"${PYTHON_BIN}" -m pip install --no-cache-dir --break-system-packages \
  "mineru[core] @ git+https://github.com/opendatalab/MinerU.git@${MINERU_REVISION}"
# D64 diagnostics: what the vendor's own resolution of mineru[core] produced on
# this image, before the pins below touch it. The vendor Dockerfile stops here;
# every line the pins change is a departure from the vendor stack, and the
# post-run container log (D62) keeps the diff.
"${PYTHON_BIN}" -m pip freeze --all 2>/dev/null | LC_ALL=C sort > "${ARENA_ROOT}/freeze-vendor-resolution.txt"
# D68: no re-pinning. What the vendor resolution gave us, by name, so the
# receipt and the container log say exactly which stack answered.
VENDOR_VERSIONS="$("${PYTHON_BIN}" -c "import importlib.metadata as m; print(' '.join(f'{n}=={m.version(n)}' for n in ('mineru', 'mineru-vl-utils', 'vllm', 'transformers', 'tokenizers', 'torch', 'huggingface_hub', 'accelerate')))")"
echo "[arena] vendor resolution: ${VENDOR_VERSIONS}"
record "vendor_resolution=${VENDOR_VERSIONS}"
record "pins_changed_vs_vendor_resolution=nothing (D68: pins removed)"

# 3. Weights into the persistent volume cache: public repository, pinned
#    revision, no token, sha256 checked.
if [ -f "${WEIGHTS_ROOT}/arena-weights-revision.txt" ] \
   && [ "$(cat "${WEIGHTS_ROOT}/arena-weights-revision.txt")" = "${MODEL_REVISION}" ]; then
  record "weights_cache_hit=true"
  export ARENA_WEIGHTS_CACHE_HIT=true
else
  record "weights_cache_hit=false"
  HF_HUB_DISABLE_IMPLICIT_TOKEN=1 hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" \
    --local-dir "${WEIGHTS_ROOT}"
fi
echo "${WEIGHTS_LARGEST_SHA256}  ${WEIGHTS_ROOT}/${WEIGHTS_LARGEST_FILE}" | sha256sum -c - || {
  echo "[arena] FATAL weights: checksum verification failed for ${WEIGHTS_ROOT}/${WEIGHTS_LARGEST_FILE}" >&2
  exit 64
}
# D59: same ordering fix as mineru_pipeline's bootstrap, applied here even
# though this runtime's `hf download` (no --include, so the argparse
# nargs="*" --include bug does not apply) fetched the right file on the real
# canary. The revision marker must only be written after the checksum above
# passes - writing it right after `hf download` returns would let a future
# restart skip a retry on a partial or corrupted download.
printf '%s' "${MODEL_REVISION}" > "${WEIGHTS_ROOT}/arena-weights-revision.txt"
record "weights_dir=${WEIGHTS_ROOT}"
record "weights_largest_file=${WEIGHTS_LARGEST_FILE}"
record "weights_largest_file_sha256=sha256:${WEIGHTS_LARGEST_SHA256}"

printf '{"models-dir": {"vlm": "%s"}, "model-source": "local", "config_version": "1.3.2"}\n' \
  "${WEIGHTS_ROOT}" > "${ARENA_ROOT}/mineru.json"

# 3b. Architecture preflight.
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. This runtime
# starts no model server (D59: MinerU's vlm-engine resolves to vllm-engine on
# this image, but ModelSingleton.get_model in mineru/backend/vlm/vlm_analyze.py
# holds it as an in-process vllm.LLM object, not an HTTP server - "http-client"
# is the separate backend name for that - so ARENA_CONTRACT 11.6 still applies),
# so it gets the preflight half only.
#
# Floors (evidence in runtime.json.framework_floor_audit): the checkpoint declares
# model_type "qwen2_vl", architectures ["Qwen2VLForConditionalGeneration"] and
# transformers_version 4.57.2; MinerU 3.4.5's pyproject [vlm] extra pins
# transformers >= 4.57.3, < 5.0.0, which the vendor resolution satisfies (vllm-engine
# still imports transformers to build the checkpoint's AutoConfig, which is what
# the preflight below exercises).
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_WEIGHTS_DIR="${WEIGHTS_ROOT}" "${PYTHON_BIN}" - <<'PY'
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

# D68: the arena no longer re-pins on top of mineru[core]; what must hold is
# MinerU's own floor for this git revision (pyproject [vlm]/[core]:
# transformers >= 4.57.3, < 5.0.0; mineru-vl-utils >= 1.0.5, < 2). The exact
# versions the vendor resolution produced are recorded, not asserted.
FLOORS = {
    "transformers": ((4, 57, 3), (5, 0, 0)),
    "mineru-vl-utils": ((1, 0, 5), (2, 0, 0)),
}


def _parse(v: str) -> tuple:
    parts = []
    for piece in v.split("+")[0].split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts[:3]) + (0,) * (3 - len(parts[:3]))
EXPECTED_MODEL_TYPE = "qwen2_vl"
EXPECTED_ARCH = "Qwen2VLForConditionalGeneration"
# D59: this image is vllm/vllm-openai (the same base MinerU's own
# docker/global/Dockerfile FROMs), get_vlm_engine(inference_engine="auto")
# always resolves to vllm-engine here because vllm is importable on Linux
# (mineru/utils/engine_utils.py:_select_linux_engine), and the model card's
# own official_inference_config already names backend "vllm-engine". The
# pinned "transformers" here was wrong for this image, not a MinerU bug.
EXPECTED_ENGINE = "vllm-engine"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


for name, (floor, ceiling) in FLOORS.items():
    installed = version(name)
    if not (floor <= _parse(installed) < ceiling):
        fail(
            f"{name} is {installed}, outside MinerU's own range "
            f"[{'.'.join(map(str, floor))}, {'.'.join(map(str, ceiling))})"
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

from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES

if model_type not in CONFIG_MAPPING_NAMES and "auto_map" not in config:
    fail(
        f"transformers {version('transformers')} does not know model_type {model_type!r} "
        "and the checkpoint carries no auto_map to load it from remote code"
    )
from transformers import AutoConfig

try:
    resolved = AutoConfig.from_pretrained(str(weights))
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"transformers cannot build a config for {model_type!r}: {type(exc).__name__}: {exc}")

from mineru.utils.engine_utils import get_vlm_engine

engine = get_vlm_engine(inference_engine="auto", is_async=False)
if str(engine) != EXPECTED_ENGINE:
    fail(
        f"MinerU's vlm-engine resolved to {engine!r}, but runtime.json's "
        f"inference_config.expected_vlm_engine is {EXPECTED_ENGINE!r}"
    )

summary = (
    f"model_type={model_type} architectures={','.join(architectures)} "
    f"config_class={type(resolved).__name__} vlm_engine={engine} "
    f"mineru={version('mineru')} transformers={version('transformers')}"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"
record "architecture_preflight=${ARCH_PREFLIGHT}"

# 4. Every version this bootstrap installed (masterplan section 38), plus the
#    engine `vlm-engine` resolves to - the adapter fails closed if it is not the
#    pinned one, so recording it here makes the canary receipt self-explaining.
"${PYTHON_BIN}" -m pip freeze --all | LC_ALL=C sort > "${ARENA_ROOT}/bootstrap-pip-freeze.txt"
record "pip_freeze_sha256=sha256:$(sha256sum "${ARENA_ROOT}/bootstrap-pip-freeze.txt" | cut -d' ' -f1)"
record "mineru_declared_version=$("${PYTHON_BIN}" -c 'import importlib.metadata as m; print(m.version("mineru"))')"
record "resolved_vlm_engine=$("${PYTHON_BIN}" -c 'from mineru.utils.engine_utils import get_vlm_engine; print(get_vlm_engine(inference_engine="auto", is_async=False))')"
record "python=$("${PYTHON_BIN}" -c 'import sys; print(sys.version.replace(chr(10), " "))')"
if command -v nvidia-smi >/dev/null 2>&1; then
  record "gpu=$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits | head -n 1)"
else
  record "gpu=unavailable"
fi

# 4b. D64 self-test: the vendor's own CLI on the worker's synthetic warm-up
#     page, same env, same weights, same engine. Pods r0yal3hocpipsm and
#     733khrz3mcscrw answered every page - including that warm-up - with the
#     layout string "]]<|><|><|><|>" through the adapter's in-process do_parse.
#     If `mineru` itself produces the same garbage here, the fault is in the
#     stack (image, weights, GPU) and not in the adapter; if it parses, the
#     adapter's path is the difference. Never fatal: this is evidence, and the
#     canary verdict still comes from the real pages.
export MINERU_MODEL_SOURCE=local
export MINERU_TOOLS_CONFIG_JSON="${ARENA_ROOT}/mineru.json"
SELFTEST_DIR="${ARENA_ROOT}/selftest"
mkdir -p "${SELFTEST_DIR}"
set +e
PYTHONPATH="${ARENA_ROOT}" "${PYTHON_BIN}" -c "from pathlib import Path; from arena.worker.synthetic import synthetic_page_png; synthetic_page_png(Path('${SELFTEST_DIR}/warmup.png'))"
# D71 follow-up: pod t0e8yz3oobso7i answered every real page with the layout
# string ']]<|><|><|><|>' on the vendor's own stack, and the only line that
# could say whether the vendor CLI does the same without the arena adapter
# was this self-test's -- which kept 4 lines and lost the answer. The whole
# CLI log goes to a file; the raw layout answer (mineru_vl_utils logs it at
# DEBUG, hence LOGURU_LEVEL), its format warning, and every weight-loading
# warning are printed under [arena] so the driver's READY-time capture (D71)
# carries them into the receipt.
SELFTEST_LOG="${SELFTEST_DIR}/cli.log"
LOGURU_LEVEL=DEBUG "${PYTHON_BIN}" -c "import sys; from mineru.cli.client import main; sys.argv = ['mineru', '-p', '${SELFTEST_DIR}/warmup.png', '-o', '${SELFTEST_DIR}/out', '-b', 'vlm-engine']; main()" > "${SELFTEST_LOG}" 2>&1
SELFTEST_STATUS=$?
tail -n 4 "${SELFTEST_LOG}"
SELFTEST_RAW="$(grep -A1 'Layout raw output' "${SELFTEST_LOG}" | grep -v 'Layout raw output' | head -n 1 | head -c 300)"
SELFTEST_FORMAT="$(grep -c 'does not match expected format' "${SELFTEST_LOG}" || true)"
echo "[arena] selftest layout raw answer: ${SELFTEST_RAW:-<none logged>} (format warnings: ${SELFTEST_FORMAT})"
record "selftest_layout_raw=${SELFTEST_RAW:-none}"
record "selftest_format_warnings=${SELFTEST_FORMAT}"
grep -iE 'warn|unexpected|missing|ignored|not loaded|mismatch|deprecat' "${SELFTEST_LOG}" | grep -viE 'does not match expected format|urllib3|pydantic' | head -n 25 | sed 's/^/[arena] selftest load: /' | cut -c1-400
SELFTEST_MD="$(find "${SELFTEST_DIR}/out" -name '*.md' 2>/dev/null | head -n 1)"
if [ -n "${SELFTEST_MD}" ]; then
  echo "[arena] selftest: mineru CLI exit=${SELFTEST_STATUS} markdown_bytes=$(wc -c < "${SELFTEST_MD}") head=$(head -c 200 "${SELFTEST_MD}" | tr '\n' ' ')"
  record "selftest=exit ${SELFTEST_STATUS}, markdown_bytes $(wc -c < "${SELFTEST_MD}")"
else
  echo "[arena] selftest: mineru CLI exit=${SELFTEST_STATUS} wrote no markdown"
  record "selftest=exit ${SELFTEST_STATUS}, no markdown"
fi
# 4c. D73 probes: the adapter's exact do_parse call, in a fresh process, under
#     each of the ways the worker process differs from the CLI (its kwargs,
#     its env, a non-main thread), plus the CLI defaults through the same
#     in-process path. One line each, and a summary line last so the D71
#     READY-time capture cannot lose them behind the worker's own engine
#     start-up. Evidence only; the canary verdict still comes from the pages.
PROBE_SUMMARY=""
PROBE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/selftest_probe.py"
for PROBE in engine-ids aio-cli-args aio-adapter-args; do
  PROBE_OUT="${SELFTEST_DIR}/probe-${PROBE}"
  mkdir -p "${PROBE_OUT}"
  PROBE_LINE="$(PYTHONPATH="${ARENA_ROOT}" "${PYTHON_BIN}" "${PROBE_SCRIPT}" "${PROBE}" "${SELFTEST_DIR}/warmup.png" "${PROBE_OUT}" 2>"${PROBE_OUT}/stderr.log" | grep '^\[arena\] probe' | tail -n 1)"
  if [ -z "${PROBE_LINE}" ]; then
    PROBE_LINE="[arena] probe ${PROBE}: no summary line (exit $?); stderr tail: $(tail -n 3 "${PROBE_OUT}/stderr.log" | tr '\n' ' ' | cut -c1-300)"
  fi
  echo "${PROBE_LINE}"
  record "probe_${PROBE}=${PROBE_LINE#\[arena\] probe ${PROBE}: }"
  PROBE_SUMMARY="${PROBE_SUMMARY}${PROBE}=[${PROBE_LINE#\[arena\] probe ${PROBE}: }] "
done
echo "[arena] probe summary: ${PROBE_SUMMARY}"
set -e

# 5. Hand off. entrypoint.sh is the single start path for both modes.
export MINERU_TOOLS_CONFIG_JSON="${ARENA_ROOT}/mineru.json"
export MINERU_API_MAX_CONCURRENT_REQUESTS=1
export OMP_NUM_THREADS=1
export ARENA_WEIGHTS_DIR="${WEIGHTS_ROOT}"
export ARENA_RUNTIME_DIR="${RUNTIME_DIR}"
export PYTHONPATH="${PYTHONPATH:-${ARENA_ROOT}}"
export PYTHON_BIN
exec "${RUNTIME_DIR}/entrypoint.sh"
