# syntax=docker/dockerfile:1.7
# Infinity-Parser2-Flash arena runtime.
#
# Build context is the namespace root: research/model_arena_20260903/
#   docker build -f runtimes/infinity_parser2_flash/Dockerfile -t <tag> .
#
# Base image was originally the official vLLM release the model card names
# (vllm==0.17.1). D55 (2026-09-04): a real canary on that image got past
# architecture resolution and then died importing the checkpoint's tokenizer
# (tokenizer_class=TokenizersBackend, a transformers-v5-only class; vllm==0.17.1
# bounds transformers to "< 5"). Bumped to the same image runtimes/glm_ocr already
# proved live on RunPod on this exact digest, pinned by digest so the build stays
# reproducible:
#   https://huggingface.co/infly/Infinity-Parser2-Flash           (checkpoint card)
#   https://hub.docker.com/r/vllm/vllm-openai/tags               (digest resolved 2026-09-03)
#   https://raw.githubusercontent.com/vllm-project/vllm/v0.19.0/requirements/common.txt
#   https://raw.githubusercontent.com/vllm-project/vllm/v0.19.0/vllm/model_executor/models/registry.py
#
# Nothing is installed with `pip install -U` and no package is left unpinned. The
# only Python packages this runtime adds on top of the base image are the four
# transformers-family pins below: the adapter is stdlib-only, and the
# `infinity_parser2` wrapper is deliberately absent because github.com/infly-ai/
# INF-MLLM ships no LICENSE (see README.md).
FROM vllm/vllm-openai:v0.19.0-ubuntu2404@sha256:69234fc31ff1d5e1687b2f06bba39e0f8c58dd4755f0508dbe0595cd3692b851

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/arena \
    ARENA_MODEL_KEY=infinity_parser2_flash \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/infinity_parser2_flash \
    ARENA_VLLM_PORT=8100 \
    HF_HUB_ENABLE_HF_TRANSFER=0

WORKDIR /opt/arena

# Fail the build, loudly, if the base image does not already carry what the worker
# server and the weight fetcher need. We do not install these: adding an unpinned
# dependency on top of a pinned image is the failure mode masterplan 15.1 forbids.
RUN python3 -c "import fastapi, uvicorn, PIL, huggingface_hub, vllm; \
print('base image provides', vllm.__version__, 'transformers-backed vLLM')"

# --- transformers pin (D55, 2026-09-04) -------------------------------------
# Identical to bootstrap.sh and to runtimes/glm_ocr/Dockerfile's four pins on this
# same base image. --no-deps: every remaining dependency of these four is pinned
# here or already satisfied by the image, and pip must not resolve torch or vLLM
# again. See the architecture preflight below for why this is required, not just
# vLLM's own bundled qwen3_5_moe config module.
RUN python3 -m pip install --no-cache-dir --no-deps \
        "transformers==5.4.0" \
        "tokenizers==0.22.2" \
        "huggingface_hub==1.5.0" \
        "hf-xet==1.3.2"

COPY arena/ /opt/arena/arena/
# D17: the prompt registry travels with the image; the worker resolves
# /opt/arena/prompt_registry/<prompt_id>.txt and fails closed when it is missing.
COPY prompt_registry/ /opt/arena/prompt_registry/
COPY runtimes/infinity_parser2_flash/ /opt/arena/runtime/

RUN python3 -c "import arena.constants as c; assert 'infinity_parser2_flash' in c.MODEL_KEYS"

# weights_strategy is volume_cache with runtime_mode_allowed [baked, bootstrap]
# (founder decision 2026-09-03; see runtime.json.notes). This Dockerfile always
# builds the BAKED variant: 70.21 GB of safetensors is fetched HERE, at build time,
# not inside a metered pod. The image is therefore ~78 GB and the build lane must
# size it as baked. --manifest hashes every shard once now, which is why
# inference_config.hash_weights_on_load can stay false at boot.
RUN python3 /opt/arena/runtime/fetch_weights.py         --weights-dir /opt/arena/weights/infinity_parser2_flash         --manifest

# Prove the framework can actually read the checkpoint just baked in, at build
# time instead of on a billed pod. Same two checks bootstrap.sh's architecture
# preflight runs, against the now-local config.json/tokenizer_config.json.
RUN python3 - <<'PY'
import json
from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES
from transformers.tokenization_utils_tokenizers import TokenizersBackend
from vllm.model_executor.models.registry import ModelRegistry
import transformers
import vllm

assert transformers.__version__ == "5.4.0", transformers.__version__
assert vllm.__version__.startswith("0.19."), vllm.__version__
assert "qwen3_5_moe" in CONFIG_MAPPING_NAMES
assert TokenizersBackend is not None

declared = json.load(open("/opt/arena/weights/infinity_parser2_flash/config.json", encoding="utf-8"))
assert declared["model_type"] == "qwen3_5_moe", declared["model_type"]
tokenizer_declared = json.load(
    open("/opt/arena/weights/infinity_parser2_flash/tokenizer_config.json", encoding="utf-8")
)
assert tokenizer_declared["tokenizer_class"] == "TokenizersBackend", tokenizer_declared["tokenizer_class"]

supported = set(ModelRegistry.get_supported_archs())
missing = [a for a in declared["architectures"] if a not in supported]
assert not missing, f"vllm {vllm.__version__} does not implement {missing}"

print(
    "[arena] architecture preflight PASS "
    f"transformers={transformers.__version__} vllm={vllm.__version__} "
    f"arch={declared['architectures'][0]} tokenizer_class={tokenizer_declared['tokenizer_class']}"
)
PY

RUN mkdir -p /workspace/arena/results

RUN chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

EXPOSE 8000
ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]
