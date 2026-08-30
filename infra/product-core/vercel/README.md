# Product-Core v2 Vercel deployment

This adapter is the authenticated fallback deployment for environments where
Cloud Run control-plane access is unavailable. It preserves the same FastAPI,
HMAC, release-digest, candidate-only, and customer-data fail-closed contracts
as `infra/product-core/Dockerfile`.

Stage a deployment directory outside the Git worktree with the deterministic
release builder:

```powershell
uv run python infra/product-core/vercel/stage_release.py `
  --output $env:TEMP/tavonel-product-core-v2-release
```

The builder copies this directory's four runtime files and these package roots
into `vendor/`, then writes `release-manifest.json` with the exact source digest:

- `packages/cir-python/src/akc_cir`
- `packages/domain-packs/src/akc_domain_packs`
- `packages/product-core/src/akc_product_core`

Required production environment variables:

- `TAVONEL_PRODUCT_CORE_HMAC`: at least 32 random bytes.
- `TAVONEL_CORE_RELEASE_DIGEST`: `sha256:` plus the deterministic staged
  source digest.

Do not set `TAVONEL_CORE_ALLOW_CUSTOMER_DATA` for Foundation qualification.
The service exposes `GET /health` and HMAC-authenticated `POST /v2/compile`.
