# Runpod Deployment Contract

Endpoints are disabled until the corresponding model release has an exact
revision, license snapshot, signed image digest, self-test, security scan,
reproducible benchmark, and fallback recipe.

Deployment secrets are created in the provider control plane or approved secret
manager and are never committed. Required runtime configuration:

- exact `MODEL_REVISION`;
- `MODEL_ADAPTER_MODULE`;
- scoped input/output host allowlists;
- current `GPU_USD_PER_SECOND` estimate;
- feature gate for experimental workers;
- `REQUIRE_CALLBACK_AUTH=true`;
- a minimum 32-byte `CALLBACK_HMAC_SECRET` from the provider secret manager;
- `CALLBACK_TOKEN_AUDIENCE=akc-gpu-worker`;
- `ALLOW_INLINE_INPUT=false`;
- no tenant-wide storage credentials.

Every callback token is short-lived and scoped to its audience, job, and
tenant. Production mode refuses to start when callback authentication is
disabled or the secret is missing/short. Rotate the callback secret through an
overlap window managed by the control plane; never put it in endpoint YAML,
image layers, logs, callback payloads, or CI artifacts.

`ALLOW_INLINE_INPUT` is local-self-test only. Production input/output URLs must
use HTTPS, pass the explicit host allowlists, resolve to public addresses at
validation and connection time, and carry the narrowest short-lived object
grant. Callback URLs follow the same SSRF policy.

Smoke a single synthetic page, verify revision/checksum/cost cap/callback
authentication, and canary 1% -> 5% -> 20%. Provider retry is disabled because
the control plane owns retry and idempotency. Large results go to scoped object
storage and the provider response contains only a small manifest.
