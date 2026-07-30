# Durable GPU provider jobs

The GPU control worker provides a durable, fail-closed boundary for Runpod
serverless execution. It does not make any model or route production-ready by
itself. Route activation still requires the model, license, benchmark, security,
and release evidence described in the model registry and release gates.

## Trust boundary

The API/control plane persists only identifiers, hashes, bounded options, exact
model attestations, and object keys. It never sends original document bytes or
model output inline in a provider request or callback.

For each provider attempt the control worker creates:

- one short-lived presigned GET for the exact admitted source or derived input;
- one short-lived presigned PUT for the exact derived output key;
- a signed control request containing the expected model revision, immutable
  runtime image digest, adapter version, input SHA-256, job/tenant scope, and
  idempotency key.

The default grant lifetime is 20 minutes and is hard-bounded to 10–30 minutes.
It must outlive the provider job timeout. The remote endpoint receives no
tenant-wide object-store credential. Local filesystem storage cannot mint a
provider-safe HTTPS grant and therefore fails closed.

## Durable state machine

```text
queued -> submitting -> submitted -> running -> completed
   |          |             |          |
   +-------> retry <--------+----------+
   |                                  |
   +-> cancel_requested -> cancelling -> cancelled
                                      \-> dead_letter

non-retryable attestation/result failure -> failed
retry budget exhausted                -> dead_letter
```

`gpu_provider_invocations` is the current durable state.
`gpu_provider_attempts` records bounded, append-only attempt evidence.
`gpu_invocation_events` is the content-free ordered transition stream.

### Immutable OOM and invalid-output transitions

Migration `0020_gpu_invocation_transitions` adds a parent/root lineage and an
immutable approval snapshot. A transition never rewrites the failed request,
its options, or its output key:

```text
parent (failed, immutable request/output identity)
  -> child (queued, new idempotency key, new output key)
```

- GPU OOM permits at most two category transitions and also consumes the
  root job's total attempt budget. The first available action halves bounded
  worker-consumed `max_output_tokens`, `batch_size`, and/or `tile_size` without
  going below their safe minima. If nothing can be reduced, escalation is
  allowed only to an exact internal target captured by the router and still
  enabled for that tenant's model-registry cohort.
- Invalid output permits at most one fallback transition. Only the router's
  internal `HPD/Paddle Fast -> Paddle VL` path is accepted here. External OCR
  is not inferred or sent through the Runpod control worker.
- Missing, malformed, disabled, cohort-ineligible, same-target, unsupported,
  category-exhausted, or job-budget-exhausted policy creates no child and
  resumes the owning job for fail-closed operator review.
- The deterministic child idempotency key binds the parent/category/transition
  attempt. Duplicate delivery of the same leased failure therefore cannot
  create another child or another resume.
- Parent and child invocation events, one job progress event, and one audit
  event retain only IDs, strategies, attempts, provider/model revisions,
  request/input hashes, and bounded timing. No source or model output enters
  these events.

The active child ID replaces the matching ID in `job.progress`; page-attempt
identity continues to point to the immutable lineage root. Admission accepts a
child only when that root matches, preserving both resume correctness and the
original routing evidence. Credit reserve/consume/release remains job-scoped;
creating a transition never writes the credit ledger.

A claim transaction only locks and advances database state, then commits.
Runpod submit, poll, cancel, and object-store reads/presigning happen after that
commit. The result is admitted in a new transaction that reacquires the row
lock and verifies the lease/tombstone fence. No network call is performed while
a database write transaction is open.

## Idempotency and result admission

Submission uses one tenant-scoped idempotency key and an immutable canonical
request-manifest SHA-256. Reusing the key with the same manifest returns the
existing invocation; a different manifest is a conflict.

Polling reads the output object and verifies all of the following before
terminal admission:

- actual byte length and SHA-256 match the provider result;
- result schema/job/tenant/provider/idempotency scope matches the invocation;
- exact model revision, runtime image digest, and adapter version match;
- input SHA-256 and exact output object key match;
- provider job and endpoint identities match;
- the parent job/document/project still exist, are active, and are not marked
  for deletion.

The database result manifest contains only bounded metrics, identifiers,
checksums, and hashes of warnings. Raw model output remains in the scoped
derived object.

Poll replay is idempotent. A callback adapter may call
`GpuInvocationWorker.admit_callback` only after authenticating the provider
signature at the HTTP edge. The callback event ID and payload SHA-256 are
persisted; same-ID/different-payload or different terminal evidence is rejected.
There is intentionally no unauthenticated callback route in the control worker.

## Page-scoped visual admission

Visual parser invocations receive one exact derived `inference_raster`, never a
source document or UI preview. The request pins the page asset UUID, zero-based
page index, source SHA-256, RGB colorspace, dimensions, byte length, and an
allowed 200/300 DPI band. The runtime rejects source references to any other
page.

`akc-visual-page-1.0.0` is a strict discriminated result contract. Text, table,
formula, and figure blocks have bounded page/bbox provenance plus mandatory
block and token confidence. Canonical table cells carry their own source refs
and confidence. Numeric/table/formula pages require an independent verifier
with exact numeric agreement and bounded structure/formula agreement. Missing
confidence or verifier evidence is review evidence, never an implicit perfect
score. `provider_raw` must be an empty object, while warnings and quality flags
are bounded identifier codes rather than free-form provider text.

Provider output remains a candidate until the API independently runs
sensitive-data and prompt-injection detection, measured quality evaluation, and
router escalation. Rejected candidate objects are deleted and raw text is not
copied into attempts, reviews, events, or logs. Only an `ACCEPT` decision
promotes blocks atomically; all other decisions leave the existing block set
byte-for-byte unchanged. Accepted structured blocks preserve the complete
model-run attestation used by CIR and export generation.

## Durable knowledge compile handoff

With `AKC_KNOWLEDGE_PROVIDER=qwen_durable`, the compile dispatcher writes a
bounded `knowledge-pipeline-input-1.0.0` object to the tenant's derived prefix
for each durable A-D unit:

1. Stage A maps bounded block previews to semantic sections and classifies the
   document independently of its source file format.
2. Stage B runs once per bounded section shard. Each fragment is at most 32 KiB,
   each unit contains at most 32 fragments and 512 KiB of source text, and no
   unit may exceed 1 MiB canonical JSON.
3. Stage C receives bounded semantic descriptors, evidence snippets and hashes,
   never the whole document. Every candidate must appear exactly once in an
   explained merge group. Unsupported semantic merges fail admission.
4. Stage D receives semantic source/retrieval descriptors plus an exact
   tenant/project ACL attestation. Provider-unverified retrieval is represented
   explicitly with no candidates or links.

Each unit is one immutable GPU invocation. The dispatcher records the current
stage, completed/total units, full compile-input SHA-256, and invocation IDs in
`job.progress`, then returns without replaying route or parse work. A crash or
duplicate dispatch reuses exact stage-unit invocations and cannot submit or
charge the same unit twice. The provider request contains only the input object
hash plus artifact, prompt, schema, model, runtime-image, and adapter
attestations; it contains no blocks or source text.

A terminal GPU transition enqueues one deterministic
`job.dispatch.requested.v1` resume event. Callback and poll replay are
idempotent, while cancellation, deletion tombstones, and terminal parent jobs
fence the resume. The dispatcher then verifies both stored-object hashes,
revalidates the exact stage/unit result against its immutable input, and
reacquires locks on the parent job and every invocation before deterministic
assembly and persistence.

Semantic classification, notes, and relations preserve document version, full
compile-input hash, pipeline schema, model revision, active revision pointer,
and complete invocation provenance. Exact retry reactivates the same immutable
revision. Changed evidence or model creates a new revision and leaves the old
one inactive but preserved. Export fails closed if any Qwen revision is missing
prompt/model/image/adapter/schema or input/output/request/result hashes.

Note stable keys and relation UUIDs are deterministic. Knowledge persistence,
credit consume/release entries, terminal job events, and completion commit in
one database transaction. Replaying a completion therefore neither duplicates
knowledge rows nor consumes credits twice. The deterministic development/test
provider is still document/version scoped but carries no fabricated Qwen
attestation.

## Timeout, retry, cancellation, and deletion

Provider control calls have a separate short timeout. Each submitted provider
job has a durable deadline. Retryable submit/poll failures use bounded
exponential backoff with jitter; exhaustion moves the invocation to
`dead_letter`. A timed-out provider job is cancelled before it can be retried.

Cancellation is also durable and bounded. Job cancellation, document/project
deletion, a terminal parent job, or a missing parent row changes the invocation
to `cancel_requested`. A provider result that races with one of those conditions
is fenced and never admitted.

Deletion includes invocation, attempt, event, and output-object identifiers in
its immutable manifest. Storage purge cannot begin while a provider may still
write. Completed/failed/cancelled invocations are safe; an unconfirmed
dead-letter cancellation is safe only after the persisted object-grant expiry.
Otherwise deletion retries with `gpu_cancellation_pending`.

## Production configuration

Use the isolated `python -m akc_scheduler --mode gpu` deployment. Never combine
the GPU database role or secrets with the API, webhook scheduler, dispatch,
deletion, analysis, URL-fetcher, or migration owner.

Required configuration:

```text
AKC_ENV=production
AKC_GPU_WORKER_ENABLED=true
AKC_GPU_DATABASE_ROLE=akc_gpu_worker
AKC_OBJECT_STORE_DRIVER=s3
AKC_S3_USE_AMBIENT_CREDENTIALS=true
AKC_GPU_ALLOWED_INPUT_HOSTS=<exact-presigned-get-host>
AKC_GPU_ALLOWED_OUTPUT_HOSTS=<exact-presigned-put-host>
AKC_RUNPOD_API_KEY=<endpoint-scoped-secret>
AKC_GPU_WORKER_HMAC_SECRET=<independent-32-byte-minimum-secret>
```

The object-store endpoint in the GPU worker must be public/provider-reachable
HTTPS. A cluster-only S3 Service URL creates unusable presigned grants. The
committed Kubernetes ConfigMap contains explicit replacement placeholders and
must not be deployed unchanged.

Standard Kubernetes `NetworkPolicy` cannot express DNS names. The base permits
public TCP/443 while excluding private and special-use ranges; application code
still restricts presigned URLs to exact configured hosts and the provider
client uses the fixed Runpod API origin. A production cluster with a
FQDN-aware policy engine should additionally allow only the Runpod API and
approved object-store hosts.

Migration `0011_durable_gpu_provider_jobs` creates
`akc_gpu_worker NOLOGIN NOINHERIT BYPASSRLS` with only required
table/column privileges. Migration `0020_gpu_invocation_transitions` adds only
the transition-specific privileges: read the exact model-registry row, insert
append-only job/audit evidence, and update `processing_jobs.progress` plus its
event sequence. It does not grant customer-content, user, billing, deletion, or
general job mutation access. Provision a dedicated login:

```sql
CREATE ROLE akc_gpu_runtime
  LOGIN
  NOINHERIT
  PASSWORD '<generated-by-the-secret-manager>';
GRANT akc_gpu_worker TO akc_gpu_runtime;
```

The external secret controller materializes `akc-gpu-worker-secrets` with that
login URL, the endpoint-scoped Runpod key, and the dedicated HMAC secret. Bind
the ServiceAccount to the least-privilege object-store workload identity.

Before rollout:

```powershell
python -m akc_scheduler --check --mode gpu
kubectl kustomize infra/kubernetes/base
```

The check verifies the exact PostgreSQL effective role, restricted login
attributes, forced RLS, absence of direct runtime-login table grants, required
column privileges, S3-only storage, credential shape, exact host allowlists,
and retry/timeout policy.

## Operations

Monitor state counts, age of the oldest due invocation, attempt error codes,
provider request/cold-start/cost telemetry, cancellation retries, revision
mismatch counters, `akc_unsupported_claim_total`, and deletion requests waiting
on GPU cancellation. Any accepted unsupported claim is a release-blocking
alert; rejected invalid knowledge output increments the `accepted="false"`
series.

For a provider outage, stop new route admission before changing durable rows.
Do not manually fabricate a terminal result. Allow bounded retries to settle,
or request cancellation through the durable API. Resume with a synthetic
canary only after the exact endpoint/image/model attestation and output
checksum pass. See `provider-outage.md`.

For a dead letter, preserve the invocation, attempts, events, request hash, and
result hashes as evidence. Determine whether the provider job may still write.
If cancellation is unconfirmed, wait for the persisted grant expiry before
allowing deletion, rotate the endpoint credential if compromise is suspected,
and replay only by creating a new explicitly authorized invocation. Never edit
a terminal result manifest in place.
