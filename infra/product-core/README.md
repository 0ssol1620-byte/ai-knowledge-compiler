# Product-Core v2 deployment

This image exposes `GET /health` and HMAC-authenticated `POST /v2/compile`.
It creates candidate worlds only. It never owns or mutates a Product active-world
pointer and defaults to rejecting `approved_customer_data` requests.

Required runtime secrets:

- `TAVONEL_PRODUCT_CORE_HMAC`: at least 32 bytes, injected from Secret Manager.
- `TAVONEL_CORE_RELEASE_DIGEST`: the deployed immutable image digest in
  `sha256:<64 hex>` form.

Optional policy:

- `TAVONEL_CORE_ALLOW_CUSTOMER_DATA=true` is forbidden until the customer-data
  release gate is separately approved. Omit it for Foundation qualification.

Build from the repository root so both `akc_cir` and `akc_product_core` are in
the Docker context:

```powershell
gcloud builds submit --project tavonel-saas-foundation `
  --config infra/product-core/cloudbuild.yaml `
  --substitutions _IMAGE=asia-northeast3-docker.pkg.dev/tavonel-saas-foundation/tavonel-product-core/product-core:qualification .
```
