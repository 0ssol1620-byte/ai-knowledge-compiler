# Kubernetes deployment contract

The base is a hardened, deliberately non-deployable production contract. It
contains eight stateless workloads, Services, PodDisruptionBudgets, HPAs,
restricted pod security, default-deny networking, quota, and same-origin web/API
Ingress routes. It does **not** prove that a production environment exists.

## Mandatory overlay values

An environment overlay must replace every `.invalid` host, image placeholder,
bucket placeholder, TLS secret placeholder, and the
`AKC_DEPLOYMENT_REVISION` placeholder. The revision must be the exact
40-character Git SHA used to build the signed images; the same ConfigMap value
is injected into both API and web health responses. Application and worker images
must use signed immutable digests. `NEXT_PUBLIC_AKC_API_URL` is a Next.js build
input, so the web image must be built for the public same-origin URL; setting it
only on the running container is not sufficient.

Create every workload-specific Secret through an external secret controller.
The analysis worker must not receive API JWT or webhook keys. Never add a
rendered Secret to Git. The exact key contract is in
[`secret-keys.md`](secret-keys.md).

The base intentionally leaves API egress to PostgreSQL and S3 denied. The
overlay must add the narrowest cluster-specific egress rules:

- managed PostgreSQL address and port 5432;
- approved regional S3 endpoint on TLS port 443;
- the approved ClamAV service on port 3310;
- an in-cluster OpenTelemetry collector on 4317, if enabled;
- scheduler egress to PostgreSQL and the exact approved webhook destinations;
- when `AKC_COLLECTION_SEMANTIC_RETRIEVAL_ENABLED=true`, the exact approved
  embedding provider on TLS 443 plus PostgreSQL; inject
  `AKC_COLLECTION_SEMANTIC_RETRIEVAL_EMBEDDING_API_KEY` and
  `AKC_COLLECTION_SEMANTIC_RETRIEVAL_ROW_HMAC_SECRET` only through
  `akc-runtime-secrets`;
- when `AKC_COLLECTION_METADATA_ENCRYPTION_ENABLED=true`, the versioned AES-256
  decrypt keyring and independent path blind-index key only through
  `akc-runtime-secrets`; keep collection writes disabled until the staged
  backfill/collision/decryptability verifier is clean;
- no GPU/provider egress until the corresponding feature, tenant consent,
  model revision, callback authentication, and release evidence are approved.

The current web bundle performs API calls in the browser through the
same-origin Ingress, so the web pod has no API egress permission. Add server-side
web egress only if reviewed server code begins making such calls.

NetworkPolicy cannot portably select an external service by DNS name. Use the
cluster CNI's FQDN policy or reviewed stable CIDRs; do not add `0.0.0.0/0` as a
shortcut. Patch the ingress-controller, DNS, Prometheus, and OpenTelemetry
namespace/pod labels when the cluster differs from the documented base labels.
The collection embedding overlay must bind the FQDN rule to the same hostname
as `AKC_COLLECTION_SEMANTIC_RETRIEVAL_EMBEDDING_ENDPOINT_URL`; a matching port
without matching destination identity is not sufficient. Keep the base feature
disabled until rendered-manifest checks, the PostgreSQL retrieval migration,
provider attestation, and a no-customer-data canary all pass.
Semantic retrieval and the finalizer may never be enabled while collection
metadata encryption is disabled. Encryption-key rotation keeps legacy keys
decrypt-only until a complete re-encryption pass. Blind-index key rotation is a
write-fenced full reindex, not a rolling mixed-key deployment.
Follow the staged
[collection metadata encryption runbook](../../docs/runbooks/collection-metadata-encryption.md)
for revision 0026, tenant-scoped backfill/verification, revision 0027, and rotations.

## Apply sequence

1. Render the overlay and reject unresolved placeholders.
2. Scan Kubernetes policy and images; verify signatures and SBOMs.
3. Run the revision-named migration Job from `jobs/migrate.yaml`.
4. Server-side dry-run, then apply the application overlay.
5. Wait for API, web, scheduler, dispatch, deletion, analysis, GPU-control, and
   URL-fetcher rollouts; verify `/health/live`, `/health/ready`, login,
   authenticated API, upload, durable dispatch, SSE reconnect, export, and
   deletion.
6. Run a synthetic canary and watch error budget, queue age, costs, and audit
   writes before increasing traffic.

The API readiness probe checks its database and, when configured, the
fail-closed malware scanner without sending customer content. The web probe
uses the real `/login` page. `/api/health` is a revision-bearing deployment
evidence surface, not a substitute for API/database readiness. Release
verification must reject a missing revision or a SHA that differs between the
web response, API response, image attestation, and intended release. The API
Ingress disables response buffering and has a long read timeout so SSE is not
broken by the proxy.

## Durable processing boundary

`AKC_LOCAL_BACKGROUND_TASKS=false` is required in production. The base splits
the transactional-outbox webhook scheduler and durable compile dispatcher into
separate least-privilege database roles and two-replica workloads using
PostgreSQL `SKIP LOCKED` claims. Native document parsing is a third durable
lane: the API only enqueues, while a restricted CPU worker runs every parser in
a credential-free bubblewrap network namespace inside a gVisor pod. Its
readiness probe proves both its exact database capability and sandbox launcher.
Their readiness probes run mode-specific,
non-mutating database checks; liveness checks only the process so a database
outage does not cause a restart storm. Each process exposes a monitoring-only
Prometheus port, while the dispatch process executes compile jobs with bounded
leases, attempts, timeouts, and dead-letter semantics.

The in-cluster GPU control worker owns only durable provider state,
exact-object grants, result admission, and resume events. GPU model execution
workers remain isolated provider endpoints. Their production configuration
must require job/tenant/audience-scoped callback tokens and a secret supplied
by the provider secret manager.

## Required cluster services

- metrics-server for `autoscaling/v2` HPAs;
- an Ingress controller and managed certificate integration;
- external secrets/workload identity;
- a CNI that enforces both ingress and egress NetworkPolicy;
- managed PostgreSQL with PITR and encrypted object storage;
- a fail-closed ClamAV service or approved equivalent;
- Prometheus/Alertmanager and an OpenTelemetry collector;
- admission policy that rejects privileged pods, mutable images, and unresolved
  placeholders.
- a `gvisor` RuntimeClass with unprivileged user namespaces enabled for the
  analysis worker's nested bubblewrap self-test.
