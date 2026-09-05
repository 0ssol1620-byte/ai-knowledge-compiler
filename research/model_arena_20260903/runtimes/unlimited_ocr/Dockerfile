# syntax=docker/dockerfile:1.7
#
# Unlimited-OCR arena runtime. Build context is the namespace root
# (research/model_arena_20260903/), so `docker build -f runtimes/unlimited_ocr/Dockerfile .`
# from there.
#
# Stage 1 downloads the pinned checkpoint with huggingface_hub. It is separate
# because huggingface_hub 1.x and transformers 4.57.1 (which requires
# huggingface_hub < 1.0) cannot share an environment.
#
# Every pip pin below is stated by the model card. This is the one runtime in
# lane C2 where upstream pins the whole list, so no version here is a lane
# choice: torch 2.10.0, torchvision 0.25.0, transformers 4.57.1, Pillow 12.1.1,
# matplotlib 3.10.8, einops 0.8.2, addict 2.4.0, easydict 1.13, pymupdf 1.27.2.2,
# psutil 7.2.2, tested on Python 3.12.3 + CUDA 12.9.

ARG WEIGHTS_BASE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
ARG RUNTIME_BASE=nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802

ARG MODEL_REPO=baidu/Unlimited-OCR
ARG MODEL_REVISION=07dea832e22aefee32ad281d4b80551282e1c168
ARG LARGEST_WEIGHT_FILE=model-00001-of-000001.safetensors
ARG LARGEST_WEIGHT_SHA256=2bc48a7a110061ea58fff65d3169367eebe3aee371ca6968dc2219c1b2855fc6

# ---------------------------------------------------------------- weights ----
FROM ${WEIGHTS_BASE} AS weights
ARG MODEL_REPO
ARG MODEL_REVISION
ARG LARGEST_WEIGHT_FILE
ARG LARGEST_WEIGHT_SHA256
ENV PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_ENABLE_HF_TRANSFER=0

RUN python -m pip install --no-cache-dir "huggingface_hub[cli]==1.17.0"

# The whole revision is fetched, including assets/long-horizon-ocr.gif (82 MB)
# and the vendored SGLang wheel. Neither is used at run time; they are kept so
# the weights manifest covers the revision exactly as published.
RUN hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" --local-dir /weights \
    && printf '%s  %s\n' "${LARGEST_WEIGHT_SHA256}" "/weights/${LARGEST_WEIGHT_FILE}" \
       | sha256sum --check --strict

COPY arena/ /opt/arena/arena/
COPY runtimes/unlimited_ocr/ /opt/arena/runtime/

# Writes arena-weights-receipt.json + arena-weights-manifest.json with the same
# code the adapter verifies against at load time, so the two can never drift.
RUN PYTHONPATH=/opt/arena python /opt/arena/runtime/adapter.py \
      --write-weights-receipt /weights \
      --repo "${MODEL_REPO}" \
      --revision "${MODEL_REVISION}" \
    && find /weights -type f -exec chmod 0444 {} +

# ---------------------------------------------------------------- runtime ----
FROM ${RUNTIME_BASE} AS runtime
ARG MODEL_REPO
ARG MODEL_REVISION
ARG RUNTIME_BASE
ARG WEIGHTS_BASE

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/opt/arena/venv/bin:$PATH \
    PYTHONPATH=/opt/arena \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    ARENA_MODEL_KEY=unlimited_ocr \
    ARENA_MODEL_REPO=${MODEL_REPO} \
    ARENA_MODEL_REVISION=${MODEL_REVISION} \
    ARENA_RUNTIME_MODE=baked \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/unlimited_ocr \
    ARENA_RUNTIME_DIR=/opt/arena/runtime

# Ubuntu 24.04 ships Python 3.12 (the card was tested on 3.12.3) and marks the
# system interpreter externally managed, so the runtime lives in its own venv
# rather than being forced in with --break-system-packages.
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
         python3 python3-venv python3-pip ca-certificates libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/arena/venv

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu129 \
      torch==2.10.0 \
      torchvision==0.25.0

RUN pip install --no-cache-dir \
      transformers==4.57.1 \
      Pillow==12.1.1 \
      matplotlib==3.10.8 \
      einops==0.8.2 \
      addict==2.4.0 \
      easydict==1.13 \
      pymupdf==1.27.2.2 \
      psutil==7.2.2

COPY --from=weights /weights /opt/arena/weights/unlimited_ocr
COPY arena/ /opt/arena/arena/
COPY runtimes/unlimited_ocr/ /opt/arena/runtime/
# 11.5 D17/D33: baked images carry the prompt registry so the worker can
# resolve ARENA_PROMPT_FILE without a bootstrap download.
COPY prompt_registry/ /opt/arena/prompt_registry/
RUN chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

RUN python -c "from importlib.metadata import version as v; expected={'torch':'2.10.0','torchvision':'0.25.0','transformers':'4.57.1','pillow':'12.1.1','matplotlib':'3.10.8','einops':'0.8.2','addict':'2.4.0','easydict':'1.13','pymupdf':'1.27.2.2','psutil':'7.2.2'}; actual={n:v(n).split('+')[0] for n in expected}; raise SystemExit(None if actual==expected else f'runtime dependency mismatch: {actual!r}')"
RUN python -c "import torch, sys; c=torch.version.cuda; sys.exit(0) if c and c.startswith('12.9') else sys.exit(f'torch reports cuda {c}, expected 12.9')"

# Section 38 provenance, frozen into the image.
RUN { \
      echo "model_key=unlimited_ocr"; \
      echo "model_repo=${MODEL_REPO}"; \
      echo "model_revision=${MODEL_REVISION}"; \
      echo "base_image=${RUNTIME_BASE}"; \
      echo "weights_base_image=${WEIGHTS_BASE}"; \
      cat /opt/arena/weights/unlimited_ocr/arena-weights-receipt.json; \
      echo; \
      python --version; \
      python -c "import torch; print('torch=' + torch.__version__); print('torch_cuda=' + str(torch.version.cuda))"; \
      pip freeze | LC_ALL=C sort; \
      (dpkg -l | LC_ALL=C sort) || true; \
    } > /opt/arena/baked-runtime-receipt.txt \
    && chmod 0444 /opt/arena/baked-runtime-receipt.txt

EXPOSE 8000
ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]
