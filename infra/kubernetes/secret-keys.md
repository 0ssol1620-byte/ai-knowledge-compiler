# External Secret key contracts

The external secret controller must materialize the namespaced Secrets used by
enabled workloads. They
must never be generated from a committed plaintext file.

## `akc-runtime-secrets`

Required API keys:

| Key                                        | Requirement                                                                  |
| ------------------------------------------ | ---------------------------------------------------------------------------- |
| `AKC_DATABASE_URL`                         | `postgresql+asyncpg://` URL from the managed database secret                 |
| `AKC_JWT_SECRET`                           | at least 32 random bytes, rotated through the session runbook                |
| `AKC_MFA_ENCRYPTION_KEY`                   | dedicated Fernet key for tenant-scoped TOTP seeds                            |
| `AKC_MFA_RECOVERY_HMAC_SECRET`             | dedicated 32-byte minimum key for pending-token and recovery-code digests    |
| `AKC_REDIS_URL`                            | `rediss://` URL for the authoritative atomic abuse-control backend           |
| `AKC_ABUSE_IDENTITY_HMAC_SECRET`           | dedicated 32-byte minimum secret; must differ from JWT and verification keys |
| `AKC_VERIFICATION_HMAC_SECRET`             | dedicated 32-byte minimum pepper for one-time token digests                  |
| `AKC_VERIFICATION_DELIVERY_ENCRYPTION_KEY` | Fernet key for the transactional verification outbox                         |
| `AKC_IDEMPOTENCY_RESPONSE_ENCRYPTION_KEY`  | independent Fernet key for exact mutation-response replay                    |
| `AKC_URL_ENCRYPTION_KEY`                   | Fernet key for full URL task payloads when URL ingestion is enabled          |
| `AKC_URL_QUERY_HMAC_SECRET`                | independent 32-byte minimum key for query correlation digests                |
| `AKC_PAYMENT_MERCHANT_ID`                  | non-secret merchant identifier, injected with the enabled payment overlay    |
| `AKC_PAYMENT_WEBHOOK_SECRET`               | dedicated 32-byte minimum secret for signed provider events                  |
| `AKC_WEBHOOK_ENCRYPTION_KEY`               | Fernet key used only to encrypt endpoint signing secrets                     |

When an overlay enables public registration it must also set
`AKC_EMAIL_VERIFICATION_PROVIDER=resend` and
`AKC_CAPTCHA_PROVIDER=turnstile`, then inject `AKC_RESEND_API_KEY`,
`AKC_RESEND_SENDER`, and `AKC_CAPTCHA_SECRET_KEY` from the external secret
controller. The committed base keeps registration and delivery disabled; it
must never contain provider credentials or the test-support key.

The committed base also keeps `AKC_PAYMENTS_ENABLED=false` and
`AKC_PAYMENT_PROVIDER=disabled`. An enabled payment overlay must inject both
payment keys above. `AKC_PAYMENT_PROVIDER=fake` is rejected in production.

The committed base keeps `AKC_OIDC_ENABLED=false`. An enabled OIDC overlay must
set the exact HTTPS issuer and callback, client ID, asymmetric algorithm and
endpoint-host allowlists, and inject `AKC_OIDC_CLIENT_SECRET`,
`AKC_OIDC_TRANSACTION_ENCRYPTION_KEY`, and `AKC_OIDC_STATE_HMAC_SECRET`.
Provider tenant, redirect, claims, and key rotation remain an external release
gate; local mock-JWKS tests are not production IdP evidence.

## `akc-scheduler-secrets`

Required scheduler keys:

| Key                          | Requirement                                                                 |
| ---------------------------- | --------------------------------------------------------------------------- |
| `AKC_DATABASE_URL`           | Dedicated `akc_scheduler_runtime` PostgreSQL login URL; never the API login |
| `AKC_WEBHOOK_ENCRYPTION_KEY` | Same active Fernet key version used by the API, delivered independently     |

The scheduler login must be `NOINHERIT`, be granted the `akc_scheduler`
`NOLOGIN BYPASSRLS` role, and have no direct application-table grants. The API
login must not be a member of `akc_scheduler`. Follow
`docs/runbooks/scheduler-database-role.md` for provisioning, verification, and
rotation.

## `akc-dispatch-secrets`

Required dispatch-worker keys:

| Key                      | Requirement                                                                                     |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| `AKC_DATABASE_URL`       | Dedicated `akc_dispatch_runtime` PostgreSQL login URL; never the API or webhook-scheduler login |
| Object-store credentials | Prefer an ambient workload identity scoped to required source and derived object prefixes       |

The dispatch login must be `NOINHERIT`, be granted only the
`akc_dispatch_worker` `NOLOGIN BYPASSRLS` role, and have no direct
application-table grants. It must not be a member of `akc_scheduler`, and the
webhook scheduler login must not be a member of `akc_dispatch_worker`.
When `AKC_KNOWLEDGE_PROVIDER=qwen_durable`, dispatch must use S3-compatible
storage and be able to write the exact knowledge input object and read the
exact input/output objects during terminal admission. Do not inject a
tenant-wide static key when workload identity can express the same narrower
access.

## `akc-deletion-secrets`

Required deletion-worker keys:

| Key                      | Requirement                                                               |
| ------------------------ | ------------------------------------------------------------------------- |
| `AKC_DATABASE_URL`       | Dedicated `akc_deletion_runtime` PostgreSQL login URL                     |
| Object-store credentials | Delete-only scoped credentials supplied by the external secret controller |

## `akc-gpu-worker-secrets`

Required GPU provider control-worker keys:

| Key                          | Requirement                                                                                                             |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `AKC_DATABASE_URL`           | Dedicated `akc_gpu_runtime` PostgreSQL login URL; never an API, scheduler, dispatch, deletion, or migration-owner login |
| `AKC_RUNPOD_API_KEY`         | Dedicated provider key with only the approved serverless endpoint scope                                                 |
| `AKC_GPU_WORKER_HMAC_SECRET` | Independent random secret of at least 32 bytes, shared only with the attested GPU endpoint runtime                      |

The login must be `NOINHERIT` and may assume only the
`akc_gpu_worker NOLOGIN BYPASSRLS` role created by migration
`0011_durable_gpu_provider_jobs`. Bind `akc-gpu-worker` to an object-store
identity that can read only the admitted source/derived prefixes and write only
the invocation output prefix. The control worker converts that identity into
short-lived, exact-object GET/PUT grants; the remote endpoint receives neither
ambient storage credentials nor tenant-wide access.

The separately managed Runpod knowledge endpoint must receive
`CALLBACK_HMAC_SECRET`, any loopback-only `QWEN_INFERENCE_API_KEY`, and the
reviewed model-attestation file through its provider secret manager. Exact
model revision, runtime image digest, adapter version, prompt revision, and
knowledge schema digest are non-secret attestations and must match the API,
dispatch, worker image, and provider request byte-for-byte. Never place source
text or a serialized knowledge input in endpoint environment variables.

## `akc-analysis-secrets`

Required native-analysis worker keys:

| Key                        | Requirement                                                                                            |
| -------------------------- | ------------------------------------------------------------------------------------------------------ |
| `AKC_DATABASE_URL`         | Dedicated `akc_analysis_runtime` PostgreSQL login URL; never an API, scheduler, or migration-owner URL |
| `AKC_S3_ACCESS_KEY_ID`     | Source-read and derived-write/delete scoped identity                                                   |
| `AKC_S3_SECRET_ACCESS_KEY` | Matching secret, rotated independently from API credentials                                            |

The analysis login must be `NOINHERIT`, be granted only the
`akc_analysis_worker` `NOLOGIN BYPASSRLS` role, and have no direct table grants.
The worker Secret must not contain `AKC_JWT_SECRET`, webhook/provider secrets,
or tenant content. The parser child receives a sanitized environment and no
credentials.

## `akc-url-fetcher-secrets`

Required URL-ingestion worker keys:

| Key                         | Requirement                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------------------- |
| `AKC_DATABASE_URL`          | Dedicated `akc_url_fetcher_runtime` PostgreSQL login URL; never an API or migration-owner URL     |
| `AKC_URL_ENCRYPTION_KEY`    | Active Fernet key version shared only with the API URL enqueue path                               |
| `AKC_URL_QUERY_HMAC_SECRET` | Independent random secret of at least 32 bytes; never reused as the encryption or application key |
| Object-store credentials    | Quarantine write/read/delete and immutable source promotion only, supplied by workload identity   |

The login must be `NOINHERIT` and may assume only the `akc_url_fetcher`
`NOLOGIN BYPASSRLS` role. The worker Secret must not contain JWT, webhook,
payment, provider, or migration-owner credentials.

## `akc-migration-secrets`

Required migration keys:

| Key                | Requirement                                                                      |
| ------------------ | -------------------------------------------------------------------------------- |
| `AKC_DATABASE_URL` | Short-lived migration-owner PostgreSQL URL, injected only into the migration Job |

## `akc-payment-reconciliation-secrets`

Optional while payments remain disabled:

| Key           | Requirement                                                                                 |
| ------------- | ------------------------------------------------------------------------------------------- |
| `AKC_API_KEY` | tenant-bound key owned by a billing service account; only `api:read` and `api:write` scopes |

The committed reconciliation CronJob is suspended. Before enabling it, replace
the image digest and HTTPS URL, create one CronJob and secret per tenant, and
confirm the service account has the `billing` membership role. Never reuse an
owner's interactive key.

The API object storage uses the standard ambient credential chain with
`AKC_S3_USE_AMBIENT_CREDENTIALS=true`; bind the API ServiceAccount to a
least-privilege workload identity. Do not materialize
`AKC_S3_ACCESS_KEY_ID`/`AKC_S3_SECRET_ACCESS_KEY` in production. If static keys
are ever used in an isolated nonproduction environment, both fields are
required and must come from that environment's secret manager.

Do not place Runpod API keys or GPU HMAC secrets in the API, webhook scheduler,
dispatch, deletion, analysis, or URL-fetcher Secrets; they belong only in
`akc-gpu-worker-secrets`. Never place customer content, presigned URLs, model
weights, or payment API keys in a Kubernetes Secret. The payment webhook secret
above is the only payment secret accepted by the API control plane; remote
provider workers receive only short-lived exact-object grants and their
endpoint-scoped verification secret.
