# syntax=docker/dockerfile:1.7
FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_NO_PROGRESS=1

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
COPY services ./services
COPY workers ./workers
RUN python -m pip install "uv==0.12.0" \
    && python -m uv sync --locked --no-dev --no-editable \
    && python -m uv pip check --python /build/.venv/bin/python

FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH

RUN groupadd --gid 10001 akc \
    && useradd --uid 10001 --gid akc --create-home --shell /usr/sbin/nologin akc \
    && install -d -o akc -g akc /app

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv

USER 10001:10001
STOPSIGNAL SIGTERM
CMD ["python", "-m", "akc_scheduler"]
