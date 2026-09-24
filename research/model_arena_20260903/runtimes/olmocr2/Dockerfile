# syntax=docker/dockerfile:1.7
# olmOCR-2-7B-1025-FP8 arena runtime.
#
# Build context is the namespace root: research/model_arena_20260903/
#   docker build -f runtimes/olmocr2/Dockerfile -t <tag> .
#
# The base image is the one the toolkit's own Dockerfile uses at the pinned tag
# (https://github.com/allenai/olmocr/blob/v0.4.27/Dockerfile -> FROM
# vllm/vllm-openai:v0.11.2), taken by digest so the build is reproducible.
# The toolkit's `gpu` extra pins transformers==4.57.3 and vllm==0.11.2; vllm comes
# from the base image, transformers is pinned explicitly here.
FROM vllm/vllm-openai:v0.11.2@sha256:2c908d5a84ed251b6a17d179f42d06df1aff353007779ac5eecd8a0ea3fe9331

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/arena \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/olmocr2 \
    ARENA_VLLM_PORT=8100 \
    HF_HUB_ENABLE_HF_TRANSFER=0

# poppler-utils ships pdftoppm/pdfinfo. The arena feeds PNGs so nothing renders a
# PDF here, but the toolkit imports its render helpers eagerly and the official
# image installs them; leaving them out would change the package under test.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# Exact versions from https://github.com/allenai/olmocr/blob/v0.4.27/pyproject.toml
# ([project.optional-dependencies].gpu). No `pip install -U` anywhere.
RUN python3 -m pip install --no-cache-dir \
        "olmocr==0.4.27" \
        "transformers==4.57.3"

WORKDIR /opt/arena

COPY arena/ /opt/arena/arena/
# D17: the prompt registry travels with the image; the worker resolves
# /opt/arena/prompt_registry/<prompt_id>.txt and fails closed when it is missing.
COPY prompt_registry/ /opt/arena/prompt_registry/
COPY runtimes/olmocr2/ /opt/arena/runtime/

# weights_strategy is baked: 10.06 GB is small enough to live in the image, which
# removes a boot-time download from every replica (masterplan 15.1/15.2).
RUN python3 /opt/arena/runtime/fetch_weights.py \
        --weights-dir /opt/arena/weights/olmocr2 \
        --manifest

# Fail the build if the prompt this campaign will send is not the prompt the
# installed toolkit builds, or if the pinned versions are not what landed.
RUN python3 - <<'PY'
import json
from importlib.metadata import version
from olmocr.prompts import build_no_anchoring_v4_yaml_prompt
import transformers, vllm
assert version("olmocr") == "0.4.27", version("olmocr")
assert transformers.__version__ == "4.57.3", transformers.__version__
assert vllm.__version__.startswith("0.11.2"), vllm.__version__
prompt = build_no_anchoring_v4_yaml_prompt()
assert prompt.strip(), "olmocr prompt builder returned no text"
print(json.dumps({"olmocr": version("olmocr"), "prompt_chars": len(prompt)}))
PY

RUN python3 -c "import arena.constants as c; assert 'olmocr2' in c.MODEL_KEYS" \
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
