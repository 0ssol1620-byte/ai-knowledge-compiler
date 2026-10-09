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

Optional local durability qualification:

- `TAVONEL_CORE_JOURNAL_PATH` selects a SQLite file on a persistent local disk.
  The containing directory must already exist and be writable. Omission retains
  process-local replay. The HTTP request/response contract is unchanged.
- The journal durably binds tenant/workspace/idempotency key, immutable work and
  compiler release; each completed document fragment commits before reduction.
  Resume uses the original accepted attempt's provenance. New authenticated
  retries receive the same candidate with an attempt-bound receipt. A changed
  work/release key returns 409; a corrupt/unavailable journal returns 503.
- This is a single-host synthetic qualification backend. SQLite serializes writers
  with a 30-second lock timeout, including fragment extraction and reduction.
  Use a local filesystem with reliable SQLite locks and durability. Network shares,
  distributed workers and multi-region orchestration have not been qualified.
- The journal contains request text, parent snapshots and candidates in plaintext.
  Store it in a private directory and apply the existing storage/retention policy.
  Encryption, retention/compaction, restore and tenant deletion remain deployment
  qualification work. An ephemeral container or serverless filesystem does not
  provide restart durability; do not enable this as a production persistence claim.
- This setting does not promote worlds or change the customer-data gate.

Build from the repository root so both `akc_cir` and `akc_product_core` are in
the Docker context:

```powershell
gcloud builds submit --project tavonel-saas-foundation `
  --config infra/product-core/cloudbuild.yaml `
  --substitutions _IMAGE=asia-northeast3-docker.pkg.dev/tavonel-saas-foundation/tavonel-product-core/product-core:qualification .
```
