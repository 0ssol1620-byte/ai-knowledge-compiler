# syntax=docker/dockerfile:1.7
# Build is a hosted step. Weights are supplied read-only at /weights together
# with /weights/manifest.json; nothing is downloaded here. Run with --network none.
FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802
ARG MODEL_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MODEL_REVISION=${MODEL_REVISION} WEIGHTS_DIR=/weights \
    WEIGHT_MANIFEST=/weights/manifest.json HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY workers/gpu-verifier/handler.py ./handler.py
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc
USER 10001
ENTRYPOINT ["python3", "handler.py"]
