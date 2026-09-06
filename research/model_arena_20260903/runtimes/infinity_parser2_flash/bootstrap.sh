#!/usr/bin/env bash
# CANARY-ONLY bootstrap for Infinity-Parser2-Flash (ARENA_CONTRACT.md section 11.3).
#
# Runs from the official base image vllm/vllm-openai:v0.19.0-ubuntu2404 without the
# arena layer baked in. The B2 bundle template has already extracted the bundle to
# /opt/arena, symlinked /opt/arena/runtime -> /opt/arena/runtimes/infinity_parser2_flash
# and exported PYTHONPATH=/opt/arena + ARENA_RUNTIME_DIR before calling this script,
# so this script never downloads a bundle and never requires ARENA_BUNDLE_URL. It
# installs exactly the pinned versions the Dockerfile installs, resolves the pinned
# checkpoint, and records every version it saw into /opt/arena/bootstrap-receipt.txt.
#
# BOOTSTRAP IS OPEN for this runtime (founder decision 2026-09-03, superseding
# ARENA_CONTRACT D36's earlier baked-only reversal; see runtime.json.notes and
# runtime.json.runtime_mode_allowed, which this script reads rather than trusting a
# literal copied here). weights_strategy is volume_cache: the ~4.4 GB checkpoint is
# meant to land on a persistent RunPod network volume once, not be re-fetched on
# every pod boot.
set -euo pipefail

RUNTIME_DIR="${ARENA_RUNTIME_DIR:-/opt/arena/runtime}"
WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/workspace/arena/weights/infinity_parser2_flash}"
RECEIPT=/opt/arena/bootstrap-receipt.txt

mkdir -p /opt/arena /workspace/arena/results

# --- D36 runtime-mode guard ------------------------------------------------
# Fail closed on the file that owns the decision, not on a literal copied here.
MODE_ALLOWED="$(python3 -c 'import json,sys;print(",".join(json.load(open(sys.argv[1], encoding="utf-8"))["runtime_mode_allowed"]))' "${RUNTIME_DIR}/runtime.json")"
case ",${MODE_ALLOWED}," in
    *,bootstrap,*) ;;
    *)
        echo "[arena] bootstrap refuses: runtime.json allows only [${MODE_ALLOWED}]"             "for infinity_parser2_flash; the ~4.4 GB checkpoint belongs in the baked" \
            "image or a volume cache, not a metered pod's ephemeral boot" >&2
        exit 64
        ;;
esac

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

# entrypoint.sh's WEIGHTS_DIR defaults to the BAKED path (/opt/arena/weights/...).
# On 2026-09-04 pod gx5b5cakrhp359 this line was missing, so bootstrap.sh resolved
# the ~4.4 GB checkpoint into /workspace and entrypoint.sh -- never told where
# bootstrap put it -- resolved the SAME checkpoint again into /opt: two ~1.5-2 min
# downloads of the same ~4.4 GB on a $6.98/h pod. Exporting here is the fix;
# entrypoint.sh's fetch_weights.py call then hits the cache-hit path.
export ARENA_WEIGHTS_DIR="${WEIGHTS_DIR}"

# --- Framework pin (D55, 2026-09-04) ---------------------------------------
# Same family runtimes/glm_ocr already proved live on this exact base image: the
# SDK/model-card floor is a floor, not a pin (masterplan 15.1 forbids `pip install
# -U`), so it is turned into an exact version here. See the architecture preflight
# below for why transformers, not just vLLM, has to be this new. --no-deps: every
# remaining dependency of these four is pinned here or already satisfied by the
# image, and pip must not resolve torch or vLLM again.
TRANSFORMERS_PIN=5.4.0
python3 -m pip install --no-cache-dir --no-deps \
    "transformers==${TRANSFORMERS_PIN}" \
    "tokenizers==0.22.2" \
    "huggingface_hub==1.5.0" \
    "hf-xet==1.3.2"

# --- architecture preflight ------------------------------------------------
# 2026-09-03: the GLM-OCR canary reached the model-server start and died because
# the base image's Transformers did not know the checkpoint's model_type; RunPod
# restart-looped the container and the pod burned GPU time invisibly. The
# 2026-09-03 version of this preflight checked only the vLLM half (below) and
# concluded no transformers pin was needed, because vllm==0.17.1 ships its OWN
# Qwen3_5MoeConfig/Qwen3_5MoeTextConfig and can resolve the ARCHITECTURE without
# transformers knowing about it at all. That was correct and incomplete: real
# canary pod gx5b5cakrhp359 (2026-09-04, 2xH100) shows vLLM resolving the
# architecture fine and then dying on `ValueError: Tokenizer class TokenizersBackend
# does not exist or is not currently imported` (transformers/models/auto/
# tokenization_auto.py via vllm/tokenizers/hf.py). TOKENIZER loading always goes
# through the image's real transformers -- the bundled vLLM config shim never
# touches it -- and the checkpoint's tokenizer_config.json declares
# tokenizer_class=TokenizersBackend, a class transformers only gained in its v5.x
# line (src/transformers/tokenization_utils_tokenizers.py); vllm==0.17.1's image
# bounds transformers '>= 4.56.0, < 5' (requirements/common.txt), so it never had
# that class regardless of which 4.x release was installed.
#
# This runs BEFORE the ~4.4 GB weight download (fetching only config.json and
# tokenizer_config.json -- a few KB -- via hf_hub_download) so a framework that
# cannot serve this checkpoint fails in seconds, not after minutes of paid
# download on a 2-GPU pod.
ARCH_PREFLIGHT="$(ARENA_PREFLIGHT_RUNTIME_JSON="${RUNTIME_DIR}/runtime.json" python3 - <<'PY'
import json
import os
import sys

PINNED_VLLM_PREFIX = "0.19.0"
PINNED_TRANSFORMERS = "5.4.0"
EXPECTED_MODEL_TYPE = "qwen3_5"
EXPECTED_TEXT_MODEL_TYPE = "qwen3_5_text"
EXPECTED_ARCH = "Qwen3_5ForConditionalGeneration"
EXPECTED_TOKENIZER_CLASS = "TokenizersBackend"


def fail(reason: str) -> None:
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


spec = json.load(open(os.environ["ARENA_PREFLIGHT_RUNTIME_JSON"], encoding="utf-8"))
repo = spec["weights"]["repo"]
revision = spec["weights"]["revision"]

# --- transformers half: can it even import the tokenizer class this checkpoint
# names? (the 2026-09-04 gap the 2026-09-03 preflight did not check) -----------
import transformers

if transformers.__version__ != PINNED_TRANSFORMERS:
    fail(f"transformers is {transformers.__version__}, this runtime pins {PINNED_TRANSFORMERS}")

from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES

if EXPECTED_MODEL_TYPE not in CONFIG_MAPPING_NAMES:
    fail(f"transformers {transformers.__version__} does not map model_type {EXPECTED_MODEL_TYPE!r}")

try:
    from transformers.tokenization_utils_tokenizers import TokenizersBackend
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(
        f"transformers {transformers.__version__} has no importable "
        f"{EXPECTED_TOKENIZER_CLASS}: {type(exc).__name__}: {exc} -- this is exactly the "
        "2026-09-04 gx5b5cakrhp359 failure (ValueError: Tokenizer class "
        f"{EXPECTED_TOKENIZER_CLASS} does not exist or is not currently imported)"
    )
if TokenizersBackend is None:
    fail(f"transformers {transformers.__version__} imports {EXPECTED_TOKENIZER_CLASS} as None")

# Fetch only the two small metadata files -- not the ~4.4 GB checkpoint -- to
# check what THIS revision actually declares, rather than trusting the constants
# above to still be true.
from huggingface_hub import hf_hub_download

try:
    config_path = hf_hub_download(repo_id=repo, revision=revision, filename="config.json")
    tokenizer_config_path = hf_hub_download(
        repo_id=repo, revision=revision, filename="tokenizer_config.json"
    )
except Exception as exc:  # noqa: BLE001 - the reason is the point of the check
    fail(f"cannot fetch config metadata for {repo}@{revision}: {type(exc).__name__}: {exc}")

config = json.load(open(config_path, encoding="utf-8"))
tokenizer_config = json.load(open(tokenizer_config_path, encoding="utf-8"))

model_type = config.get("model_type")
architectures = tuple(config.get("architectures") or ())
text_model_type = (config.get("text_config") or {}).get("model_type")
tokenizer_class = tokenizer_config.get("tokenizer_class")
if model_type != EXPECTED_MODEL_TYPE or EXPECTED_ARCH not in architectures:
    fail(
        f"checkpoint declares model_type={model_type!r} architectures={architectures!r}, "
        f"runtime.json was written for {EXPECTED_MODEL_TYPE!r}/{EXPECTED_ARCH!r}"
    )
if tokenizer_class != EXPECTED_TOKENIZER_CLASS:
    fail(
        f"checkpoint's tokenizer_config.json declares tokenizer_class={tokenizer_class!r}, "
        f"this preflight was written for {EXPECTED_TOKENIZER_CLASS!r}"
    )

# --- vLLM half: unchanged from the 2026-09-03 preflight, still valid at 0.19.0 -
import vllm

if not vllm.__version__.startswith(PINNED_VLLM_PREFIX):
    fail(
        f"vllm is {vllm.__version__}; this runtime pins vllm=={PINNED_VLLM_PREFIX} and "
        "earlier lines (0.16.0, 0.16.1rc1, 0.17.0rc0) reject this checkpoint's "
        "transformers-5 config layout (vllm issue #36236)"
    )

from vllm.model_executor.models.registry import ModelRegistry

supported = set(ModelRegistry.get_supported_archs())
missing = [arch for arch in architectures if arch not in supported]
if missing:
    fail(f"vLLM {vllm.__version__} does not register {missing}; it cannot serve this checkpoint")

# The nested text config is the half issue #36236 was about: a checkpoint saved by
# transformers 5.x names it qwen3_5_moe_text, and a vLLM that only knows
# Qwen3_5MoeConfig raises "Invalid type of HuggingFace config" at load.
# Dense Qwen3.5 may live as qwen3_5 or share support via model registry only.
known_text_types = set()
try:
    from vllm.transformers_utils.configs import qwen3_5 as _vllm_q35
    known_text_types |= {
        getattr(candidate, "model_type", None)
        for candidate in vars(_vllm_q35).values()
        if isinstance(candidate, type)
    }
except Exception:
    pass
try:
    from vllm.transformers_utils.configs import qwen3_5_moe as _vllm_q35_moe
    known_text_types |= {
        getattr(candidate, "model_type", None)
        for candidate in vars(_vllm_q35_moe).values()
        if isinstance(candidate, type)
    }
except Exception:
    pass
if text_model_type is not None and known_text_types and text_model_type not in known_text_types:
    # Soft: registry arch check below is authoritative; config module names vary by vLLM.
    print(
        f"[arena] warn: text_config.model_type={text_model_type!r} not in bundled config "
        f"model_types={sorted(t for t in known_text_types if t)!r}; continuing on registry arch check",
        file=sys.stderr,
    )
if text_model_type is not None and text_model_type != EXPECTED_TEXT_MODEL_TYPE:
    fail(
        f"checkpoint's text_config.model_type is {text_model_type!r}, "
        f"runtime.json was written for {EXPECTED_TEXT_MODEL_TYPE!r}"
    )

summary = (
    f"model_type={model_type} text_config.model_type={text_model_type} "
    f"architectures={','.join(architectures)} tokenizer_class={tokenizer_class} "
    f"transformers={transformers.__version__} vllm={vllm.__version__} "
    "resolver=vllm.transformers_utils.configs.qwen3_5+transformers.tokenization_utils_tokenizers"
)
print(f"[arena] architecture preflight PASS {summary}", file=sys.stderr)
print(f"PASS {summary}")
PY
)"

# --- weight resolution -------------------------------------------------------
# Only reached once the framework has proven it can load this checkpoint.
echo "[arena] resolving weights into ${WEIGHTS_DIR}" >&2
python3 "${RUNTIME_DIR}/fetch_weights.py" --weights-dir "${WEIGHTS_DIR}"

# Record exactly what is present so the canary receipt can be compared against the
# baked image's provenance (masterplan 38).
{
    echo "campaign=${ARENA_CAMPAIGN_ID:-unset}"
    echo "model_key=infinity_parser2_flash"
    echo "base_image=vllm/vllm-openai:v0.19.0-ubuntu2404"
    echo "transformers_pin=${TRANSFORMERS_PIN}"
    echo "architecture_preflight=${ARCH_PREFLIGHT}"
    echo "bootstrapped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "python=$(python3 --version 2>&1)"
    echo "os=$(. /etc/os-release && echo "${PRETTY_NAME}")"
    echo "nvidia_driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
    echo "pip_freeze_sha256=$(python3 -m pip freeze | sha256sum | cut -d' ' -f1)"
    python3 - <<'PY'
import importlib
for name in ("vllm", "torch", "transformers", "tokenizers", "huggingface_hub", "fastapi", "PIL"):
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - receipt records the failure verbatim
        print(f"{name}=IMPORT_FAILED:{type(exc).__name__}")
    else:
        print(f"{name}={getattr(module, '__version__', 'unknown')}")
PY
} > "${RECEIPT}"
python3 -m pip freeze > /opt/arena/bootstrap-pip-freeze.txt

echo "[arena] bootstrap receipt written to ${RECEIPT}" >&2
exec "${RUNTIME_DIR}/entrypoint.sh"
