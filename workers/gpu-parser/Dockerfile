# syntax=docker/dockerfile:1.7
ARG MODEL_REVISION=1111111111111111111111111111111111111111

FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS local
ARG MODEL_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/app/.venv/bin:$PATH \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 \
    UV_PYTHON_DOWNLOADS=never \
    MODEL_REVISION=${MODEL_REVISION} \
    AKC_ADAPTER_MODE=mock \
    ALLOW_INLINE_INPUT=true
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python -m pip install "uv==0.12.0" \
    && uv sync --locked --no-dev \
    && uv pip check --python /app/.venv/bin/python
COPY workers/gpu-common/runtime.py ./runtime.py
COPY workers/gpu-parser/paddleocr_adapter.py ./paddleocr_adapter.py
COPY workers/gpu-parser/handler.py ./handler.py
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc
USER 10001
ENTRYPOINT ["python", "handler.py"]

FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802 AS production
ARG MODEL_REVISION
ARG PADDLEOCR_VERSION=3.7.0
ARG PADDLEPADDLE_VERSION=3.2.1
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/app/.venv/bin:$PATH \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 \
    UV_PYTHON_DOWNLOADS=never \
    MODEL_REVISION=${MODEL_REVISION} \
    AKC_ADAPTER_MODE=production \
    MODEL_ADAPTER_MODULE=paddleocr_adapter
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python3 -m pip install --break-system-packages "uv==0.12.0" \
    && uv sync --locked --no-dev \
    && uv pip install --python /app/.venv/bin/python \
      --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
      "paddlepaddle-gpu==${PADDLEPADDLE_VERSION}" \
    && uv pip install --python /app/.venv/bin/python \
      "paddleocr[doc-parser]==${PADDLEOCR_VERSION}" \
    && uv pip check --python /app/.venv/bin/python
COPY workers/gpu-common/runtime.py ./runtime.py
COPY workers/gpu-parser/paddleocr_adapter.py ./paddleocr_adapter.py
COPY workers/gpu-parser/handler.py ./handler.py
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc \
    && chown -R 10001:10001 /app
USER 10001
ENTRYPOINT ["python", "handler.py"]
