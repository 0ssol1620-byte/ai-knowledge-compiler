# syntax=docker/dockerfile:1.7
FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72 AS builder

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
RUN python -m pip install "uv==0.13.4" \
    && python -m uv sync --locked --no-dev --no-editable \
    && python -m uv pip check --python /build/.venv/bin/python

FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72 AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    AWS_EC2_METADATA_DISABLED=true

RUN groupadd --gid 10001 akc \
    && useradd --uid 10001 --gid akc --create-home --shell /usr/sbin/nologin akc \
    && install -d -o akc -g akc /app \
    && apt-get update \
    && apt-get install --yes --no-install-recommends apt bubblewrap libpcre2-8-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --root-user-action ignore pip

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv

USER 10001:10001
EXPOSE 9102
STOPSIGNAL SIGTERM
CMD ["python", "-m", "akc_worker_document"]
