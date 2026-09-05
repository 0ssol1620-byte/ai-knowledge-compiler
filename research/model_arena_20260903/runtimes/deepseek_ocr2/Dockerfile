# syntax=docker/dockerfile:1.7
#
# DeepSeek-OCR-2 arena runtime. Build context is the namespace root
# (research/model_arena_20260903/), so `docker build -f runtimes/deepseek_ocr2/Dockerfile .`
# from there.
#
# Stage 1 downloads the pinned checkpoint with huggingface_hub. It is a separate
# stage because huggingface_hub 1.x and transformers 4.46.3 (which requires
# huggingface_hub < 1.0) cannot share an environment, and the runtime stage must
# hold the version the model card names.
#
# Every pip pin is `==`. The provenance of each pin is in README.md: the four
# that upstream states (torch, transformers, tokenizers, flash-attn) and the ones
# upstream leaves open, which this lane chose and the build must confirm.

ARG WEIGHTS_BASE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
ARG RUNTIME_BASE=pytorch/pytorch:2.6.0-cuda11.8-cudnn9-devel@sha256:01fe58a7663aff1dc7407043abbc524a9a9d149933cf4f9e4edb59bf1285079e

ARG MODEL_REPO=deepseek-ai/DeepSeek-OCR-2
ARG MODEL_REVISION=aaa02f3811945a91062062994c5c4a3f4c0af2b0
ARG LARGEST_WEIGHT_FILE=model-00001-of-000001.safetensors
ARG LARGEST_WEIGHT_SHA256=d8ff67a424ba6f4dd077885eb9d6a05d2537e76fe5491f0e2a9b712f8c8870fa

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

RUN hf download "${MODEL_REPO}" --revision "${MODEL_REVISION}" --local-dir /weights \
    && printf '%s  %s\n' "${LARGEST_WEIGHT_SHA256}" "/weights/${LARGEST_WEIGHT_FILE}" \
       | sha256sum --check --strict

COPY arena/ /opt/arena/arena/
COPY runtimes/deepseek_ocr2/ /opt/arena/runtime/

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

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/arena \
    MAX_JOBS=4 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    ARENA_MODEL_KEY=deepseek_ocr2 \
    ARENA_MODEL_REPO=${MODEL_REPO} \
    ARENA_MODEL_REVISION=${MODEL_REVISION} \
    ARENA_RUNTIME_MODE=baked \
    ARENA_WEIGHTS_DIR=/opt/arena/weights/deepseek_ocr2 \
    ARENA_RUNTIME_DIR=/opt/arena/runtime

# The base image is the source of torch. Fail the build rather than silently
# running on a different torch/CUDA pair than the model card was tested on.
RUN python -c "import torch, sys; v=torch.__version__.split('+')[0]; c=torch.version.cuda; sys.exit(0) if (v=='2.6.0' and c=='11.8') else sys.exit(f'base image ships torch {torch.__version__} cuda {c}, expected 2.6.0/11.8')"

RUN pip install --no-cache-dir \
      transformers==4.46.3 \
      tokenizers==0.20.3 \
      einops==0.8.1 \
      addict==2.4.0 \
      easydict==1.13 \
      Pillow==11.1.0 \
      numpy==1.26.4 \
      packaging==24.2 \
      ninja==1.11.1.3

# Official install line from the model card, kept verbatim including
# --no-build-isolation. This compiles; expect a long build on the builder pod.
# D56: bootstrap.sh no longer builds flash-attn from source -- it installs the
# matching prebuilt wheel from the flash-attention v2.7.3 GitHub release,
# pinned by URL + sha256, because that path recompiles per canary/run pod at
# paid GPU-minute cost. This baked-image build compiles once at image-build
# time (not per rented pod) and is out of scope for that fix.
RUN pip install --no-cache-dir --no-build-isolation flash-attn==2.7.3

COPY --from=weights /weights /opt/arena/weights/deepseek_ocr2
COPY arena/ /opt/arena/arena/
COPY runtimes/deepseek_ocr2/ /opt/arena/runtime/
# 11.5 D17/D33: baked images carry the prompt registry so the worker can
# resolve ARENA_PROMPT_FILE without a bootstrap download.
COPY prompt_registry/ /opt/arena/prompt_registry/
RUN chmod +x /opt/arena/runtime/entrypoint.sh /opt/arena/runtime/bootstrap.sh

RUN python -c "from importlib.metadata import version as v; expected={'transformers':'4.46.3','tokenizers':'0.20.3','einops':'0.8.1','addict':'2.4.0','easydict':'1.13','pillow':'11.1.0','numpy':'1.26.4','flash-attn':'2.7.3'}; actual={n:v(n) for n in expected}; raise SystemExit(None if actual==expected else f'runtime dependency mismatch: {actual!r}')"

# Section 38 provenance, frozen into the image.
RUN { \
      echo "model_key=deepseek_ocr2"; \
      echo "model_repo=${MODEL_REPO}"; \
      echo "model_revision=${MODEL_REVISION}"; \
      echo "base_image=${RUNTIME_BASE}"; \
      echo "weights_base_image=${WEIGHTS_BASE}"; \
      cat /opt/arena/weights/deepseek_ocr2/arena-weights-receipt.json; \
      echo; \
      python --version; \
      python -c "import torch; print('torch=' + torch.__version__); print('torch_cuda=' + str(torch.version.cuda))"; \
      nvcc --version || true; \
      pip freeze | LC_ALL=C sort; \
      (dpkg -l | LC_ALL=C sort) || true; \
    } > /opt/arena/baked-runtime-receipt.txt \
    && chmod 0444 /opt/arena/baked-runtime-receipt.txt

EXPOSE 8000
ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]
