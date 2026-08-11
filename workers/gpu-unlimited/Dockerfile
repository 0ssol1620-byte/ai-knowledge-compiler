# syntax=docker/dockerfile:1.7
ARG MODEL_REVISION=1111111111111111111111111111111111111111

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS local
ARG MODEL_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PATH=/app/.venv/bin:$PATH UV_LINK_MODE=copy UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 UV_PYTHON_DOWNLOADS=never \
    MODEL_REVISION=${MODEL_REVISION} AKC_ADAPTER_MODE=mock ALLOW_INLINE_INPUT=true \
    EXPERIMENT_ENABLED=false
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python -m pip install "uv==0.12.0" \
    && uv sync --locked --no-dev \
    && uv pip check --python /app/.venv/bin/python
COPY workers/gpu-common/runtime.py ./runtime.py
COPY workers/gpu-unlimited/handler.py ./handler.py
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc
USER 10001
ENTRYPOINT ["python", "handler.py"]

FROM nvidia/cuda:13.3.1-cudnn-runtime-ubuntu24.04@sha256:2c9730db1d78ce3a7503a2f4ff2d64add3e7d1a47d57da504376192dda335242 AS production
ARG MODEL_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PATH=/app/.venv/bin:$PATH UV_LINK_MODE=copy UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 UV_PYTHON_DOWNLOADS=never \
    MODEL_REVISION=${MODEL_REVISION} AKC_ADAPTER_MODE=production EXPERIMENT_ENABLED=false
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python3 -m pip install --break-system-packages "uv==0.12.0" \
    && uv sync --locked --no-dev \
    && uv pip check --python /app/.venv/bin/python
COPY workers/gpu-common/runtime.py ./runtime.py
COPY workers/gpu-unlimited/handler.py ./handler.py
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc \
    && chown -R 10001:10001 /app
USER 10001
ENTRYPOINT ["python", "handler.py"]
