#!/usr/bin/env bash
# CANARY-ONLY bootstrap for GLM-OCR (ARENA_CONTRACT.md section 11.3).
#
# From the bare vllm/vllm-openai:v0.19.0-ubuntu2404 image: the B2 bundle template
# has already extracted the bundle to /opt/arena, symlinked
# /opt/arena/runtime -> /opt/arena/runtimes/glm_ocr and exported
# PYTHONPATH=/opt/arena + ARENA_RUNTIME_DIR before calling this script, so this
# script never downloads a bundle and never requires ARENA_BUNDLE_URL. It installs
# the same pins the baked Dockerfile installs, fetches BOTH pinned models
# (GLM-OCR MIT, PP-DocLayoutV3 Apache-2.0), and writes the bootstrap receipt.
# A Full Run from this path needs a founder waiver.
set -euo pipefail

RUNTIME_DIR="${ARENA_RUNTIME_DIR:-/opt/arena/runtime}"
WEIGHTS_DIR="${ARENA_WEIGHTS_DIR:-/workspace/arena/weights/glm_ocr}"
LAYOUT_DIR="${ARENA_LAYOUT_DIR:-/workspace/arena/weights/pp_doclayoutv3_safetensors}"
RECEIPT=/opt/arena/bootstrap-receipt.txt

mkdir -p /opt/arena /workspace/arena/results

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

export ARENA_WEIGHTS_DIR="${WEIGHTS_DIR}"
export ARENA_LAYOUT_DIR="${LAYOUT_DIR}"

# Same pins as runtimes/glm_ocr/Dockerfile. --no-deps on glmocr so pip cannot pull a
# different torch/transformers in underneath vLLM.
# wordfreq is NOT in glmocr's pyproject -- not in the base dependencies and not in
# the `selfhosted` extra -- but glmocr/postprocess/result_formatter.py imports
# `from wordfreq import zipf_frequency` at module level, and
# glmocr/pipeline/pipeline.py imports that module through
# `from glmocr.postprocess import ResultFormatter` with no try/except. So
# `pip install glmocr[selfhosted]` yields a package whose self-hosted pipeline
# cannot be imported; the SDK's own dependency list is wrong. Installed WITH deps
# because msgpack, langcodes, ftfy and locate are not in the vLLM image (regex is).
python3 -m pip install --no-cache-dir --no-deps "glmocr==0.1.5"
python3 -m pip install --no-cache-dir \
    "pymupdf==1.28.2" \
    "portalocker==4.3.0" \
    "python-dotenv==1.2.3" \
    "pypdfium2==5.13.0" \
    "opencv-python-headless==5.0.0.93" \
    "sentencepiece==0.2.2" \
    "accelerate==1.14.0" \
    "wordfreq==3.1.1"

# --- GLM-OCR architecture pin ---------------------------------------------
# On 2026-09-03 this bootstrap completed and then `vllm serve` died in 10 s on a
# pydantic ModelConfig ValidationError: the checkpoint's model_type `glm_ocr` was
# unknown to the transformers the v0.19.0 image ships. vLLM 0.19.0 does implement
# the architecture -- model_executor/models/registry.py maps
# GlmOcrForConditionalGeneration and GlmOcrMTPModel, and its own glm_ocr.py
# imports transformers.models.glm_ocr -- so its declared `transformers >= 4.56.0,
# < 5` bound is stale against its own code. The SDK README's "Using vLLM" section
# resolves it the same way, on this exact image tag: pip install
# "transformers>=5.3.0". A floor is not a pin (masterplan 15.1), so a pin is what
# ships, and it is deliberately not the newest 5.x:
#   transformers 5.4.0   tokenizers >=0.22.0,<=0.23.0   safetensors >=0.4.3
#   transformers 5.16.1  tokenizers >=0.23.1,<0.24      safetensors >=0.8.0
# The pod carries safetensors 0.7.0, so the newest release would drag safetensors
# and tokenizers along underneath vLLM as well. tokenizers 0.22.0 caps
# huggingface_hub at < 1.0, so the tokenizers pin is 0.22.2 -- the newest stable
# inside transformers' <=0.23.0 window, and still inside vLLM 0.19.0's own
# `tokenizers >= 0.21.1`. hf-xet is pinned because huggingface_hub 1.5.0 raises
# its floor from 1.1.3 to 1.2.0 and the image's version is not in any evidence
# this lane holds.
#
# THE PIN IS 5.4.0, NOT THE 5.3.0 THE VENDOR NAMES. The SDK's own floor is not
# enough for the SDK's own code: glmocr/layout/layout_detector.py does
# `from transformers import PPDocLayoutV3ForObjectDetection, PPDocLayoutV3ImageProcessor`,
# and at v5.3.0 that second name does not exist -- the module ships
# image_processing_pp_doclayout_v3_fast.py whose __all__ is
# ["PPDocLayoutV3ImageProcessorFast"], and image_processing_auto.py maps
# ("pp_doclayout_v3", (None, "PPDocLayoutV3ImageProcessorFast")). v5.4.0 is the
# first release where the file is image_processing_pp_doclayout_v3.py and __all__
# carries the un-suffixed name the SDK imports. 5.4.0 also still maps model_type
# glm_ocr (src/transformers/models/glm_ocr/ is present) and keeps
# tokenizers <=0.23.0 / safetensors >=0.4.3, so the three companion pins below are
# unchanged; the one bound it does move is huggingface_hub, from >= 1.3.0 to
# >= 1.5.0, which the existing 1.5.0 pin already sits on.
# --no-deps: every remaining dependency of these four is pinned here or already
# satisfied by the image, and pip must not resolve torch or vLLM again.
TRANSFORMERS_PIN=5.4.0
python3 -m pip install --no-cache-dir --no-deps \
    "transformers==${TRANSFORMERS_PIN}" \
    "tokenizers==0.22.2" \
    "huggingface_hub==1.5.0" \
    "hf-xet==1.3.2"

# --- import preflight ------------------------------------------------------
# Runs on the installs alone, before 2.8 GB of weights are pulled and before any
# server starts. On 2026-09-03 pod jdwdnvg8a2rzx6 every install above succeeded,
# the architecture preflight PASSed, vLLM initialised its engine -- and the worker
# then died in `_prepare`. An import error inside the SDK is invisible to a
# preflight that only asks transformers and vLLM about the checkpoint, so this one
# imports what the adapter will import and nothing else. It instantiates nothing:
# no GlmOcr, no detector, no CUDA context.
set +e
IMPORT_PREFLIGHT="$(python3 - "${RUNTIME_DIR}/adapter.py" <<'PY'
import importlib
import importlib.util
import sys
from pathlib import Path

# Leaf modules on purpose. `glmocr/layout/__init__.py` catches ImportError from
# layout_detector, sets PPDocLayoutDetector = None and defers the failure to
# Pipeline() -- i.e. to the worker, on a billed GPU. Importing the leaf lets the
# real error out here instead.
MODULES = (
    "glmocr",
    "glmocr.config",
    "glmocr.utils.logging",
    "glmocr.utils.lock_utils",
    "glmocr.utils.image_utils",
    "glmocr.utils.visualization_utils",
    "glmocr.utils.markdown_utils",
    "glmocr.utils.layout_postprocess_utils",
    "glmocr.utils.result_postprocess_utils",
    "glmocr.parser_result",
    "glmocr.postprocess",
    "glmocr.postprocess.result_formatter",
    "glmocr.ocr_client",
    "glmocr.dataloader",
    "glmocr.dataloader.page_loader",
    "glmocr.layout.base",
    "glmocr.layout.layout_detector",
    "glmocr.pipeline",
    "glmocr.pipeline.pipeline",
    "glmocr.api",
)


def die(module, exc):
    print(
        f"[arena] FATAL import preflight: {module}: {type(exc).__name__}: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(64)


for name in MODULES:
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - any import failure is the same verdict
        die(name, exc)

# glmocr/__init__.py resolves its exports through a lazy __getattr__, so importing
# the package proves nothing about the entry point the adapter actually calls.
try:
    from glmocr import GlmOcr  # noqa: F401
except Exception as exc:  # noqa: BLE001
    die("glmocr.GlmOcr", exc)

# The adapter, under the module name and by the path arena.worker.loader uses.
adapter_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("arena_runtime_adapter", adapter_path)
if spec is None or spec.loader is None:
    die("arena_runtime_adapter", ImportError(f"no import spec for {adapter_path}"))
adapter_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter_module
try:
    spec.loader.exec_module(adapter_module)
except Exception as exc:  # noqa: BLE001
    die("arena_runtime_adapter", exc)
if not hasattr(adapter_module, "GlmOcrAdapter"):
    die("arena_runtime_adapter", ImportError("adapter.py does not define GlmOcrAdapter"))

print(len(MODULES) + 2)
PY
)"
IMPORT_STATUS=$?
set -e
if [ "${IMPORT_STATUS}" -ne 0 ]; then
    echo "[arena] FATAL import preflight failed (exit ${IMPORT_STATUS})" >&2
    exit 64
fi
echo "[arena] import preflight PASS ${IMPORT_PREFLIGHT} modules" >&2

python3 "${RUNTIME_DIR}/fetch_weights.py" --weights-dir "${WEIGHTS_DIR}" --manifest
python3 "${RUNTIME_DIR}/fetch_layout_model.py" --layout-dir "${LAYOUT_DIR}"

# --- architecture preflight ------------------------------------------------
# Fail closed HERE, before entrypoint.sh starts a server, so an unloadable stack
# costs one bootstrap instead of a restart loop on a billed GPU. Checks the three
# things that were silently assumed on 2026-09-03: the pin actually landed,
# transformers knows model_type glm_ocr, and vLLM implements the architecture the
# checkpoint declares.
set +e
PREFLIGHT="$(python3 - "${WEIGHTS_DIR}" "${TRANSFORMERS_PIN}" <<'PY'
import json
import sys
from pathlib import Path

weights_dir = Path(sys.argv[1])
pin = sys.argv[2]


def die(reason):
    # The reason goes to the pod log, where the driver reads it; 64 is the same
    # refusal code the D33 revision guard above uses.
    print(f"[arena] FATAL architecture preflight: {reason}", file=sys.stderr)
    raise SystemExit(64)


try:
    import transformers
except Exception as exc:  # noqa: BLE001 - any import failure is the same verdict
    die(f"transformers does not import: {type(exc).__name__}: {exc}")

if transformers.__version__ != pin:
    die(f"transformers is {transformers.__version__}, this runtime pins {pin}")

from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES

if "glm_ocr" not in CONFIG_MAPPING_NAMES:
    die(f"transformers {pin} does not map model_type 'glm_ocr'")

config_path = weights_dir / "config.json"
try:
    declared = json.loads(config_path.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    die(f"cannot read {config_path}: {type(exc).__name__}: {exc}")

model_type = declared.get("model_type")
if model_type != "glm_ocr":
    die(f"{config_path} declares model_type {model_type!r}, expected 'glm_ocr'")

architectures = declared.get("architectures") or []
if not architectures:
    die(f"{config_path} declares no architectures")

try:
    import vllm
    from vllm.model_executor.models.registry import ModelRegistry
except Exception as exc:  # noqa: BLE001
    die(f"vllm does not import: {type(exc).__name__}: {exc}")

supported = set(ModelRegistry.get_supported_archs())
missing = [arch for arch in architectures if arch not in supported]
if missing:
    die(f"vllm {vllm.__version__} does not implement {missing}")

print(
    f"transformers={transformers.__version__} "
    f"vllm={vllm.__version__} arch={architectures[0]}"
)
PY
)"
PREFLIGHT_STATUS=$?
set -e
if [ "${PREFLIGHT_STATUS}" -ne 0 ]; then
    echo "[arena] FATAL architecture preflight failed (exit ${PREFLIGHT_STATUS})" >&2
    exit 64
fi
echo "[arena] architecture preflight PASS ${PREFLIGHT}" >&2

{
    echo "campaign=${ARENA_CAMPAIGN_ID:-unset}"
    echo "model_key=glm_ocr"
    echo "base_image=vllm/vllm-openai:v0.19.0-ubuntu2404"
    echo "sdk_repository=https://github.com/zai-org/GLM-OCR"
    echo "sdk_revision=98ef9846c7045774ff5391a50139e5cbe2850b54"
    echo "layout_model=PaddlePaddle/PP-DocLayoutV3_safetensors@97d101e6db2642e162a1d05392d1b0231c91033e"
    echo "maas_enabled=false"
    echo "transformers_pin=${TRANSFORMERS_PIN}"
    echo "import_preflight=PASS ${IMPORT_PREFLIGHT} modules"
    echo "architecture_preflight=PASS ${PREFLIGHT}"
    echo "bootstrapped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "python=$(python3 --version 2>&1)"
    echo "os=$(. /etc/os-release && echo "${PRETTY_NAME}")"
    echo "nvidia_driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
    echo "pip_freeze_sha256=$(python3 -m pip freeze | sha256sum | cut -d' ' -f1)"
    python3 - <<'PY'
import importlib
from importlib.metadata import PackageNotFoundError, version
for name in (
    "vllm",
    "torch",
    "torchvision",
    "transformers",
    "glmocr",
    "wordfreq",
    "huggingface_hub",
    "PIL",
    "cv2",
):
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - receipt records the failure verbatim
        print(f"{name}=IMPORT_FAILED:{type(exc).__name__}")
        continue
    try:
        print(f"{name}={version(name)}")
    except PackageNotFoundError:
        print(f"{name}={getattr(module, '__version__', 'unknown')}")
PY
} > "${RECEIPT}"
python3 -m pip freeze > /opt/arena/bootstrap-pip-freeze.txt

echo "[arena] bootstrap receipt written to ${RECEIPT}" >&2
exec "${RUNTIME_DIR}/entrypoint.sh"
