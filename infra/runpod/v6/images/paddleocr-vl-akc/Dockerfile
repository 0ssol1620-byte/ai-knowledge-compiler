# syntax=docker/dockerfile:1.7
# Arena C1 (WO-D10-0I): PaddleOCR-VL 1.6, the vendor's page pipeline, behind the AKC
# external-runner protocol. The `production` stage of workers/gpu-parser/Dockerfile wrapped as it
# is: the same base digest, apt packages, uv lock, paddlepaddle-gpu and paddleocr versions and
# install commands. In place of the production handler: the one AKC page server
# (mineru-pipeline-akc/mineru_akc_server.py, copied, not duplicated in the tree) running the
# recipe c1-paddleocr-vl.json, whose service (paddleocr_vl_service.py) keeps the vendor's
# PaddleOCRVL object loaded with the production adapter's arguments, as production does.
# Evaluation only; never the production endpoint.
#
# Build context: the repository root.
#   docker build -f infra/runpod/v6/images/paddleocr-vl-akc/Dockerfile .
# NOT hash-locked, exactly as production is not. For this evaluation-only image the pin is the
# built image digest plus the `uv pip freeze` and `uv pip list --format json` output this build
# prints to its log, which the lead saves as a receipt; a hash-locked requirements file comes
# before any production use (README.md of mineru-pipeline-akc, C1). The environment is made by
# uv and has no pip, so the listing uses uv only (WO-D10-0K3). `uv pip list --format json` has
# not run in this image yet, so it is last, behind a line that names it. paddlex is pinned to
# 3.7.2, a release whose PaddleOCR-VL-1.6 pipeline config names the layout model the recipe
# pins (production lets it resolve).
FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04@sha256:d02c4310b6d57ca0b16cd80298bdb33a74187baafe2eccd8a6a16180ddc90802

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/app/.venv/bin:$PATH \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1 \
    UV_PYTHON_DOWNLOADS=never
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./
RUN python3 -m pip install --break-system-packages "uv==0.13.4" \
    && uv sync --locked --no-dev \
    && uv pip install --python /app/.venv/bin/python \
      --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
      "paddlepaddle-gpu==3.2.1" \
    && uv pip install --python /app/.venv/bin/python \
      "paddleocr[doc-parser]==3.7.0" "paddlex==3.7.2" \
    && uv pip check --python /app/.venv/bin/python \
    && uv pip freeze --python /app/.venv/bin/python \
    && echo "AKC listing, the last command of this step: uv pip list --format json (UNVERIFIED offline)" \
    && uv pip list --python /app/.venv/bin/python --format json

# Import gate (WO-D10-0U): the import paddleocr_vl_service.py makes when the service loads
# (`importlib.import_module("paddleocr").PaddleOCRVL`), so a module the install lacks fails the
# build. What PaddleX imports later, while it builds the pipeline and runs a page, is not
# determined without running the image: the lead's first-pod check is in the README of
# mineru-pipeline-akc ("Import gate"). HOME
# points at a directory removed in the same step, so no cache PaddleX writes stays in the image.
RUN HOME=/tmp/akc-import-gate PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
      /app/.venv/bin/python -c "from paddleocr import PaddleOCRVL" \
    && rm -rf /tmp/akc-import-gate

COPY infra/runpod/v6/images/mineru-pipeline-akc/mineru_akc_server.py \
     infra/runpod/v6/images/mineru-pipeline-akc/mineru_akc_weights.py \
     infra/runpod/v6/images/paddleocr-vl-akc/paddleocr_vl_service.py /opt/akc/
COPY infra/runpod/v6/images/mineru-pipeline-akc/recipes/c1-paddleocr-vl.json \
     infra/runpod/v6/images/mineru-pipeline-akc/recipes/c1-weights-manifest.json \
     infra/runpod/v6/images/mineru-pipeline-akc/recipes/c1-layout-weights-manifest.json \
     /opt/akc/recipes/
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc \
    && install -d -o 10001 -g 10001 /opt/akc/models/PaddleOCR-VL-1.6 /opt/akc/models/PP-DocLayoutV3

# Serving is offline: the weights are downloaded at launch, then every hub is told not to fetch.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1
USER 10001
EXPOSE 8080
# Download at the revision (the only step with network), check every file, then serve offline.
# Both models C1 loads, the VLM and the layout model, each checked file by file.
CMD ["sh", "-c", "HF_HUB_OFFLINE=0 python /opt/akc/mineru_akc_weights.py /opt/akc/recipes/c1-weights-manifest.json /opt/akc/models/PaddleOCR-VL-1.6 && HF_HUB_OFFLINE=0 python /opt/akc/mineru_akc_weights.py /opt/akc/recipes/c1-layout-weights-manifest.json /opt/akc/models/PP-DocLayoutV3 && exec python /opt/akc/mineru_akc_server.py --recipe /opt/akc/recipes/c1-paddleocr-vl.json"]
