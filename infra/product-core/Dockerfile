FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/packages/cir-python/src:/app/packages/domain-packs/src:/app/packages/product-core/src \
    PORT=8080

RUN groupadd --system --gid 10001 tavonel \
    && useradd --system --uid 10001 --gid tavonel --home /nonexistent --shell /usr/sbin/nologin tavonel \
    && pip install --no-cache-dir \
        fastapi==0.140.13 \
        pydantic==2.13.4 \
        pyyaml==6.0.3 \
        uvicorn==0.35.0

WORKDIR /app
COPY --chown=10001:10001 packages/cir-python/src/akc_cir packages/cir-python/src/akc_cir
COPY --chown=10001:10001 packages/domain-packs/src/akc_domain_packs packages/domain-packs/src/akc_domain_packs
COPY --chown=10001:10001 packages/product-core/src/akc_product_core packages/product-core/src/akc_product_core

USER 10001:10001
EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn akc_product_core.__main__:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
