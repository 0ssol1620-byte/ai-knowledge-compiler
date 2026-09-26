# syntax=docker/dockerfile:1.7
#
# OvisOCR2 arena runtime. Build context is the namespace root
# (research/model_arena_20260903/), so `docker build -f runtimes/ovisocr2/Dockerfile .`
# from there.
#
# The base image is the official vLLM image already verified in this repository
# to ship vllm 0.22.1+cu129 — the exact version the OvisOCR2 model card names —
# together with huggingface-hub 1.17.0, so the checkpoint download needs no
# second stage and no extra pip install. Nothing is upgraded here: the build
# asserts the versions and fails if the base image ever moves.
#
# Digest provenance: infra/runpod/v6/images/ovisocr2-m1/Dockerfile pinned and
# verified this digest during the 2026-08 campaign.

ARG BASE_IMAGE=docker.io/vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05
ARG MODEL_REPO=ATH-MaaS/OvisOCR2
ARG MODEL_REVISION=1fc9221b7823a371d6e97f92d527cc847e24e107
ARG LARGEST_WEIGHT_FILE=model.safetensors
ARG LARGEST_WEIGHT_SHA256=9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009

FROM ${BASE_IMAGE} AS runtime
ARG BASE_IMAGE
ARG MODEL_REPO
ARG MODEL_REVISION
ARG LARGEST_WEIGHT_FILE
ARG LARGEST_WEIGHT_SHA256

USER root
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/arena \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    VLLM_WORKER_MULTIPROC_METHOD=spawn \
    ARENA_MODEL_REPO=${MODEL_REPO} \
    ARENA_MODEL_REVISION=${MODEL_REVISION} \
    ARENA_RUNTIME_MODE=baked \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/ovisocr2 \
    ARENA_RUNTIME_DIR=/opt/arena/runtime

# The model card pins vllm==0.22.1. Fail the build rather than run a different
# engine than the official contract names.
RUN python3 -c "from importlib.metadata import version as v; expected={'vllm':'0.22.1+cu129','huggingface-hub':'1.17.0','pillow':'12.2.0','transformers':'5.10.2'}; actual={n:v(n) for n in expected}; raise SystemExit(None if actual==expected else f'base image dependency mismatch: {actual!r}')"

# HF_HUB_OFFLINE is set for the run, so the download step turns it off for
# itself only. The revision is the only thing fetched; nothing is resolved from
# a moving tag.
RUN HF_HUB_OFFLINE=0 hf download "${MODEL_REPO}" \
      --revision "${MODEL_REVISION}" \
      --local-dir /opt/arena/weights/ovisocr2 \
    && printf '%s  %s\n' "${LARGEST_WEIGHT_SHA256}" \
       "/opt/arena/weights/ovisocr2/${LARGEST_WEIGHT_FILE}" \
       | sha256sum --check --strict

COPY arena/ /opt/arena/arena/
COPY runtimes/ovisocr2/ /opt/arena/runtime/
# 11.5 D17/D33: baked images carry the prompt registry so the worker can
# resolve ARENA_PROMPT_FILE without a bootstrap download.
COPY prompt_registry/ /opt/arena/prompt_registry/
RUN chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

# Writes arena-weights-receipt.json + arena-weights-manifest.json with the same
# code the adapter verifies against at load time, so the two can never drift.
RUN python3 /opt/arena/runtime/adapter.py \
      --write-weights-receipt /opt/arena/weights/ovisocr2 \
      --repo "${MODEL_REPO}" \
      --revision "${MODEL_REVISION}" \
    && find /opt/arena/weights/ovisocr2 -type f -exec chmod 0444 {} +

# Section 38 provenance, frozen into the image.
RUN { \
      echo "model_key=ovisocr2"; \
      echo "model_repo=${MODEL_REPO}"; \
      echo "model_revision=${MODEL_REVISION}"; \
      echo "base_image=${BASE_IMAGE}"; \
      cat /opt/arena/weights/ovisocr2/arena-weights-receipt.json; \
      echo; \
      python3 --version; \
      python3 -c "import torch; print('torch=' + torch.__version__); print('torch_cuda=' + str(torch.version.cuda))"; \
      python3 -m pip freeze | LC_ALL=C sort; \
      (dpkg -l | LC_ALL=C sort) || true; \
    } > /opt/arena/baked-runtime-receipt.txt \
    && chmod 0444 /opt/arena/baked-runtime-receipt.txt

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
