# syntax=docker/dockerfile:1.7
# Build is a hosted step. Weights are supplied read-only at /weights together
# with /weights/manifest.json; nothing is downloaded here. Outbound is limited to
# the RunPod job control plane; model and adapter paths are offline
# (HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE).
FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802
ARG MODEL_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH \
    UV_LINK_MODE=copy UV_NO_CACHE=1 UV_NO_PROGRESS=1 UV_PYTHON_DOWNLOADS=never \
    MODEL_REVISION=${MODEL_REVISION} WEIGHTS_DIR=/weights \
    WEIGHT_MANIFEST=/weights/manifest.json HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python3 -m pip install --break-system-packages "uv==0.13.4" \
    && uv sync --locked --no-dev \
    && uv pip check --python /app/.venv/bin/python
COPY workers/gpu-verifier/handler.py ./handler.py
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc \
    && chown -R 10001:10001 /app
USER 10001
ENTRYPOINT ["python", "handler.py"]
