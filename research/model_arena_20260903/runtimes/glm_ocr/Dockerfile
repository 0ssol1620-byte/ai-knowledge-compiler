# syntax=docker/dockerfile:1.7
# GLM-OCR arena runtime.
#
# Build context is the namespace root: research/model_arena_20260903/
#   docker build -f runtimes/glm_ocr/Dockerfile -t <tag> .
#
# The official docs express their versions as floors, not pins:
#   model card:  pip install -U vllm --extra-index-url https://wheels.vllm.ai/nightly
#   SDK README:  pip install -U "vllm>=0.17.0"  OR
#                docker pull vllm/vllm-openai:v0.19.0-ubuntu2404
# A nightly wheel is unpinnable and `pip install -U` is forbidden (masterplan 15.1),
# so the SDK's own recommended image tag is used, taken by digest. torch,
# torchvision and vLLM are pinned BY THAT DIGEST and are not reinstalled.
#
# transformers is the exception, and it is not optional: the transformers this
# image ships does not know model_type `glm_ocr`, so `vllm serve` died in 10 s on
# a pydantic ModelConfig ValidationError on 2026-09-03. The SDK README's "Using
# vLLM" section installs one on top of this exact tag -- `pip install
# "transformers>=5.3.0"` -- and a floor is turned into the pin below. The pin is
# 5.4.0 rather than the 5.3.0 the vendor names, because glmocr's own layout stage
# imports `PPDocLayoutV3ImageProcessor`, a name transformers only exports from
# 5.4.0 (at 5.3.0 the class is `PPDocLayoutV3ImageProcessorFast`). See
# bootstrap.sh for that evidence and for why not the newest 5.x. This file and
# bootstrap.sh install the same four pins.
#
# Sources:
#   https://github.com/zai-org/GLM-OCR/blob/v0.1.5/README.md
#   https://github.com/zai-org/GLM-OCR/blob/v0.1.5/pyproject.toml
#   https://huggingface.co/zai-org/GLM-OCR
#   https://hub.docker.com/r/vllm/vllm-openai/tags  (digest resolved 2026-09-03)
#   https://raw.githubusercontent.com/vllm-project/vllm/v0.19.0/requirements/common.txt
#   https://raw.githubusercontent.com/vllm-project/vllm/v0.19.0/vllm/model_executor/models/registry.py
FROM vllm/vllm-openai:v0.19.0-ubuntu2404@sha256:69234fc31ff1d5e1687b2f06bba39e0f8c58dd4755f0508dbe0595cd3692b851

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/arena \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/glm_ocr \
    ARENA_LAYOUT_DIR=/opt/arena/weights/pp_doclayoutv3_safetensors \
    ARENA_VLLM_PORT=8080 \
    HF_HUB_ENABLE_HF_TRANSFER=0

# Record the versions the base image already provides, then refuse to continue if
# they do not meet the SDK's documented floors. Failing here is the point: a silent
# torch upgrade under vLLM is exactly the dependency accident masterplan 15.1
# exists to prevent. transformers is NOT asserted here -- the image's copy is the
# one that could not read the checkpoint, and it is replaced by the pin below.
RUN python3 - <<'PY'
from importlib.metadata import version
import vllm
torch_version = version("torch")
def at_least(actual: str, floor: str) -> bool:
    to_tuple = lambda v: tuple(int(p) for p in v.split("+")[0].split(".")[:3] if p.isdigit())
    return to_tuple(actual) >= to_tuple(floor)
assert at_least(torch_version, "2.10.0"), f"torch {torch_version} < 2.10.0"
assert at_least(vllm.__version__, "0.17.0"), f"vllm {vllm.__version__} < 0.17.0"
print("base image:", {"vllm": vllm.__version__, "torch": torch_version,
                      "transformers": version("transformers")})
PY

# The GLM-OCR architecture pin. Identical to bootstrap.sh; --no-deps because every
# remaining dependency of these four is pinned here or already satisfied by the
# image, and pip must not resolve torch or vLLM again.
RUN python3 -m pip install --no-cache-dir --no-deps \
        "transformers==5.4.0" \
        "tokenizers==0.22.2" \
        "huggingface_hub==1.5.0" \
        "hf-xet==1.3.2"

# glmocr and the parts of its [selfhosted] extra the base image does not already
# carry. --no-deps on glmocr keeps pip from resolving torch/transformers again;
# every runtime dependency it declares is either listed here or already present,
# and the assertion block below proves it.
#
# Versions are the latest satisfying the SDK's own floors on 2026-09-03 (PyPI JSON
# API), because the SDK publishes floors rather than pins:
#   glmocr 0.1.5 == the tagged release; pyproject floors are >= for the rest.
#
# wordfreq is the exception that is in no floor at all: glmocr's pyproject never
# declares it, yet glmocr/postprocess/result_formatter.py imports it at module
# level and glmocr/pipeline/pipeline.py imports that module unguarded. Without it
# the self-hosted pipeline cannot be constructed. Installed WITH deps -- msgpack,
# langcodes, ftfy and locate are not in this image.
RUN python3 -m pip install --no-cache-dir --no-deps "glmocr==0.1.5" \
 && python3 -m pip install --no-cache-dir \
        "pymupdf==1.28.2" \
        "portalocker==4.3.0" \
        "python-dotenv==1.2.3" \
        "pypdfium2==5.13.0" \
        "opencv-python-headless==5.0.0.93" \
        "sentencepiece==0.2.2" \
        "accelerate==1.14.0" \
        "wordfreq==3.1.1"

WORKDIR /opt/arena

COPY arena/ /opt/arena/arena/
# D17: the prompt registry travels with the image; the worker resolves
# /opt/arena/prompt_registry/<prompt_id>.txt and fails closed when it is missing.
COPY prompt_registry/ /opt/arena/prompt_registry/
COPY runtimes/glm_ocr/ /opt/arena/runtime/

# Both models, both pinned, both hashed. The pipeline is two checkpoints under two
# different licences (MIT + Apache-2.0) and neither is allowed to float.
RUN python3 /opt/arena/runtime/fetch_weights.py \
        --weights-dir /opt/arena/weights/glm_ocr \
        --manifest \
 && python3 /opt/arena/runtime/fetch_layout_model.py \
        --layout-dir /opt/arena/weights/pp_doclayoutv3_safetensors

# Prove the SDK imports, that nothing above broke the base image's stack, and that
# this image can actually read the checkpoint it just baked in. The last part is
# the 2026-09-03 failure: bootstrap.sh runs the same checks on the bootstrap path,
# and here they fail the build instead of a billed pod. The module list is
# bootstrap.sh's import preflight -- leaf modules, because glmocr/layout/__init__
# swallows an ImportError from layout_detector and defers it to Pipeline().
RUN python3 - /opt/arena/runtime/adapter.py <<'PY'
import importlib
import importlib.util
import json
import sys
from importlib.metadata import version
from pathlib import Path
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
for name in MODULES:
    try:
        importlib.import_module(name)
    except Exception as exc:
        raise SystemExit(f"[arena] FATAL import preflight: {name}: {type(exc).__name__}: {exc}")
from glmocr import GlmOcr  # noqa: F401
spec = importlib.util.spec_from_file_location("arena_runtime_adapter", Path(sys.argv[1]))
assert spec is not None and spec.loader is not None
adapter_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter_module
spec.loader.exec_module(adapter_module)
assert hasattr(adapter_module, "GlmOcrAdapter"), "adapter.py does not define GlmOcrAdapter"
print(f"[arena] import preflight PASS {len(MODULES) + 2} modules")
import glmocr, transformers, vllm
from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES
from vllm.model_executor.models.registry import ModelRegistry
assert version("glmocr") == "0.1.5", version("glmocr")
assert vllm.__version__.startswith("0.19."), vllm.__version__
assert transformers.__version__ == "5.4.0", transformers.__version__
assert "glm_ocr" in CONFIG_MAPPING_NAMES, "transformers does not map model_type glm_ocr"
declared = json.load(open("/opt/arena/weights/glm_ocr/config.json", encoding="utf-8"))
assert declared["model_type"] == "glm_ocr", declared["model_type"]
supported = set(ModelRegistry.get_supported_archs())
missing = [a for a in declared["architectures"] if a not in supported]
assert not missing, f"vllm {vllm.__version__} does not implement {missing}"
print("[arena] architecture preflight PASS "
      f"transformers={transformers.__version__} vllm={vllm.__version__} "
      f"arch={declared['architectures'][0]}")
PY

RUN python3 -c "import arena.constants as c; assert 'glm_ocr' in c.MODEL_KEYS" \
 && chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

# ---------------------------------------------------------------- non-root ----
# Trivy DS-0002. Everything above ran as root and stays root-owned, so weights,
# receipts and code are read-only to the runtime: a boot can verify them but never
# rewrite them. No chown of /opt/arena -- that would copy the weight layer and hand
# the receipts to the process they constrain. Only the three directories below are
# writable. /workspace/arena is used when nothing is mounted over it; a root-owned
# RunPod volume masks it, and arena.worker.config.resolve_state_dir then falls back
# to ARENA_STATE_FALLBACK_DIR and says so on the pod log and in /v1/ready.
# uid/gid 10001 is the one services/api uses.
RUN groupadd --system --gid 10001 arena \
 && useradd --system --uid 10001 --gid arena --home-dir /home/arena --create-home \
      --shell /usr/sbin/nologin arena \
 && install -d -o arena -g arena -m 0750 /var/lib/arena /var/lib/arena/state /workspace/arena
ENV HOME=/home/arena \
    ARENA_FATAL_FILE=/var/lib/arena/FATAL \
    ARENA_MODEL_SERVER_LOG=/var/lib/arena/model-server.log \
    ARENA_STATE_FALLBACK_DIR=/var/lib/arena/state
USER 10001:10001

EXPOSE 8000
ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]
