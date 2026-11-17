# syntax=docker/dockerfile:1.7
# Arena C0 and C3 (WO-D10-0F, WO-D10-0I): MinerU 3.4.4 behind the AKC external-runner protocol.
#   docker build --target c0 .   the pipeline backend, PDF-Extract-Kit-1.0 baked (C0)
#   docker build --target c3 .   the same image plus MinerU's [vlm] extra; the VLM backend's
#                                weights are downloaded at launch (README.md, C3)
# REBUILT from the 3.4.4 release: the digest the production endpoint runs is not recorded in
# the repository (README.md). Evaluation only; never the production endpoint.
#
# Build context: this directory. Every input is pinned: the base image by digest, the Debian
# packages by version from a dated snapshot, every Python package by version and sha256 (pip
# --require-hashes), the weights by revision and per-file digest (mineru_akc_weights.py fails
# the build or the launch on any difference, and the server checks them again before serving).
FROM python:3.11-slim-bookworm@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944 AS c0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# opencv-python (a MinerU dependency) loads libGL and GLib. The versions are the ones the
# snapshot's bookworm, bookworm-updates and bookworm-security indexes carry (README.md).
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261116T000000Z bookworm main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261116T000000Z bookworm-updates main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261116T000000Z bookworm-security main' \
      > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
      libgl1=1.6.0-1 libglib2.0-0=2.74.6-2+deb12u9 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /opt/akc/requirements.lock
RUN python -m pip install --require-hashes --only-binary=:all: --no-deps \
      -r /opt/akc/requirements.lock \
    && python -m pip check

COPY weights-manifest.json mineru.json mineru-vlm.json mineru_akc_weights.py /opt/akc/
RUN python /opt/akc/mineru_akc_weights.py /opt/akc/weights-manifest.json \
      /opt/akc/models/PDF-Extract-Kit-1.0

COPY mineru_akc_server.py /opt/akc/
COPY recipes/ /opt/akc/recipes/
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc

# Serving is offline: every hub is told not to fetch. Each recipe names its MinerU config.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    MINERU_MODEL_SOURCE=local \
    MINERU_API_MAX_CONCURRENT_REQUESTS=1 \
    MINERU_API_ENABLE_FASTAPI_DOCS=false \
    MINERU_API_OUTPUT_ROOT=/tmp/mineru-api-output \
    MINERU_TASK_RESULT_TIMEOUT_SECONDS=170
USER 10001
EXPOSE 8080
# The A0 launch shape (README.md): weights checked against the manifest, then served.
CMD ["python", "/opt/akc/mineru_akc_server.py", "--recipe", "/opt/akc/recipes/c0-mineru-pipeline.json"]

FROM c0 AS c3
USER root
COPY requirements-c3.lock /opt/akc/requirements-c3.lock
RUN python -m pip install --require-hashes --only-binary=:all: --no-deps \
      -r /opt/akc/requirements-c3.lock \
    && python -m pip check \
    && install -d -o 10001 -g 10001 /opt/akc/models/MinerU2.5-Pro-2605-1.2B
USER 10001
# Download at the revision (the only step with network), check every file, then serve offline.
CMD ["sh", "-c", "HF_HUB_OFFLINE=0 python /opt/akc/mineru_akc_weights.py /opt/akc/recipes/c3-weights-manifest.json /opt/akc/models/MinerU2.5-Pro-2605-1.2B && exec python /opt/akc/mineru_akc_server.py --recipe /opt/akc/recipes/c3-mineru-vlm.json"]
