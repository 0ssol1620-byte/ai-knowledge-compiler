# syntax=docker/dockerfile:1.7
# Arena C0 (WO-D10-0F): the MinerU 3.4.4 pipeline behind the AKC external-runner protocol.
# REBUILT from the 3.4.4 release: the digest the production endpoint runs is not recorded in
# the repository (README.md). Evaluation only; never the production endpoint.
#
# Build context: this directory. Every input is pinned: the base image by digest, the Debian
# packages by a dated snapshot, every Python package by version and sha256 (pip
# --require-hashes), the weights by revision and per-file digest (mineru_akc_weights.py fails
# the build on any difference).
FROM python:3.11-slim-bookworm@sha256:e8c69d86735f6df3efa06b324694fe51f0422785f83a3bd463052636c2421944

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# opencv-python (a MinerU dependency) loads libGL and GLib.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261116T000000Z bookworm main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261116T000000Z bookworm-updates main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261116T000000Z bookworm-security main' \
      > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /opt/akc/requirements.lock
RUN python -m pip install --require-hashes --only-binary=:all: --no-deps \
      -r /opt/akc/requirements.lock \
    && python -m pip check

COPY weights-manifest.json mineru.json mineru_akc_weights.py /opt/akc/
RUN python /opt/akc/mineru_akc_weights.py /opt/akc/weights-manifest.json \
      /opt/akc/models/PDF-Extract-Kit-1.0

COPY mineru_akc_server.py /opt/akc/
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin akc

# Serving is offline: the weights are baked, every hub is told not to fetch.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    MINERU_MODEL_SOURCE=local \
    MINERU_TOOLS_CONFIG_JSON=/opt/akc/mineru.json \
    MINERU_API_MAX_CONCURRENT_REQUESTS=1 \
    MINERU_API_ENABLE_FASTAPI_DOCS=false \
    MINERU_API_OUTPUT_ROOT=/tmp/mineru-api-output \
    MINERU_TASK_RESULT_TIMEOUT_SECONDS=170
USER 10001
EXPOSE 8080
ENTRYPOINT ["python", "/opt/akc/mineru_akc_server.py"]
