# syntax=docker/dockerfile:1.7
ARG MODEL_REVISION=1111111111111111111111111111111111111111

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS local
ARG MODEL_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PATH=/app/.venv/bin:$PATH UV_LINK_MODE=copy UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 UV_PYTHON_DOWNLOADS=never \
    MODEL_REVISION=${MODEL_REVISION} AKC_ADAPTER_MODE=mock ALLOW_INLINE_INPUT=true \
    KNOWLEDGE_BUNDLE_SCHEMA=/app/knowledge-bundle.schema.json \
    KNOWLEDGE_PIPELINE_SCHEMA=/app/knowledge-pipeline-result.schema.json
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python -m pip install "uv==0.12.0" \
    && python -m uv sync --locked --no-dev \
    && python -m uv pip check --python /app/.venv/bin/python
COPY workers/gpu-common/runtime.py ./runtime.py
COPY workers/gpu-knowledge/qwen_adapter.py ./qwen_adapter.py
COPY workers/gpu-knowledge/handler.py ./handler.py
COPY packages/contracts/schemas/knowledge-bundle.schema.json ./knowledge-bundle.schema.json
COPY packages/contracts/schemas/knowledge-pipeline-result.schema.json ./knowledge-pipeline-result.schema.json
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc
USER 10001
ENTRYPOINT ["python", "handler.py"]

FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802 AS production
ARG MODEL_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PATH=/app/.venv/bin:$PATH UV_LINK_MODE=copy UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 UV_PYTHON_DOWNLOADS=never \
    MODEL_REVISION=${MODEL_REVISION} AKC_ADAPTER_MODE=production \
    MODEL_ADAPTER_MODULE=qwen_adapter \
    KNOWLEDGE_BUNDLE_SCHEMA=/app/knowledge-bundle.schema.json \
    KNOWLEDGE_PIPELINE_SCHEMA=/app/knowledge-pipeline-result.schema.json
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python3 -m pip install --break-system-packages "uv==0.12.0" \
    && python3 -m uv sync --locked --no-dev \
    && python3 -m uv pip check --python /app/.venv/bin/python
COPY workers/gpu-common/runtime.py ./runtime.py
COPY workers/gpu-knowledge/qwen_adapter.py ./qwen_adapter.py
COPY workers/gpu-knowledge/handler.py ./handler.py
COPY packages/contracts/schemas/knowledge-bundle.schema.json ./knowledge-bundle.schema.json
COPY packages/contracts/schemas/knowledge-pipeline-result.schema.json ./knowledge-pipeline-result.schema.json
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc \
    && chown -R 10001:10001 /app
USER 10001
ENTRYPOINT ["python", "handler.py"]
