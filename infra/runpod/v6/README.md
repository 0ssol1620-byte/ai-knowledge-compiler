# FOLYNTA RunPod orchestration contract

Importing or testing this directory does not inspect credentials, call RunPod,
create paid resources, or change an endpoint. `client.py` is the production REST
adapter, but every operation remains a network-free dry run until `--execute`
is explicitly present. Execute mode reads only `RUNPOD_API_KEY` from the process
environment; the key is withheld from representations, receipts, provider error
bodies, and exception messages.

The model pool registry keeps incompatible model families in separate cache and
image identities. Every pool is disabled until its exact model revision,
artifact manifest, license receipt, runtime image digest, health proof, and
benchmark admission receipt exist. Secret **names** are listed so deployments
can bind provider-managed values; secret values are forbidden here.

The lifecycle is fail-closed:

```text
absent -> provisioning -> warming -> ready -> draining
       -> evidence_pending -> delete_requested -> deleted
```

Startup failure still drains and follows the same evidence/cleanup path.
Deletion cannot be recorded until work is empty, artifacts are uploaded,
evidence is persisted, the grace window elapsed, and the provider confirms the
endpoint is absent. Cleanup failures and inactive run tags are independently
audited as possible orphans.

`SpendGuard` does not impose a budget gate. Planned mandatory work may continue
after a soft expected-cost alert. A hard stop is reserved for duplicate
idempotency, excessive retry loops, duplicate acceptance or user billing, and a
greater-than-three-times anomaly with duplicate/error/idle evidence. Provider
retries stay at zero because the control plane owns retry lineage.

The scheduling contract implements the mandated priority order with tenant
round-robin fairness, predicts finish time for size-aware least-load routing,
filters on capability plus infrastructure and semantic health, guards URL/cache/
evaluator/database backpressure, and computes a capacity-capped dynamic worker
target. A cost soft alert never reduces the target; a proven runaway hard stop
does.

No endpoint was launched while the original local contract was produced. A
later 2026-08-01 live hello-world control smoke exercised create, exact-three
dispatch/status, billing lookup, drain/delete/GET 404, and tagged orphan audit.
It produced terminal cleanup and orphan-zero receipts, but it did not run a
parser/compiler model or establish model cost, speedup, quality, Public Core,
or Champion evidence. Mandatory external execution must still write exact
model/runtime identities, actual model cost, raw results, failure artifacts,
and terminal cleanup evidence into a signed benchmark evidence bundle. The
truth boundary and receipt hashes are recorded in
`docs/release/STRUCTARA_V6_COMPLETION_REPORT_2026-08-01.md`.

## Pinned live REST v2 dialect

The beta API contract was checked against the live public OpenAPI document at
`https://api.runpod.io/v2/openapi.json` on 2026-08-01. The client pins:

- management: `https://api.runpod.io/v2`;
- queue: `https://api.runpod.ai/v2/{endpoint_id}`;
- endpoint type: `QUEUE` (not the stale documentation value `QUEUE_BASED`);
- queue-delay scaling: `{type: QUEUE_DELAY, queueDelay: number}`;
- request-count scaling: `{type: REQUEST_COUNT, requestCount: integer}`;
- worker idle timeout: `workers.idleTimeout` (1-3600 seconds), omitted for
  request-count scaling;
- queue request URLs: `run`, `runSync`, `status`, `stream`, `cancel`, `retry`,
  `purgeQueue`, and `health` on the pinned queue origin.

Unknown fields/statuses, redirects, content types, origins, and legacy response
shapes fail closed. Provider retry count is permanently zero. A queue write is
preceded by a durable intent; an ambiguous outcome blocks resume instead of
silently creating another paid job.

## Safe CLI and immutable receipt paths

The examples below use one exact evidence root. `--receipt-out` creates a new
file with exclusive-create semantics and refuses to overwrite evidence.

```powershell
$EvidenceRoot = 'D:\CodexProjects\ai-knowledge-compiler\benchmark\evidence\v6\cohort-<id>'
New-Item -ItemType Directory -Force -Path $EvidenceRoot

# No key and no network: inspect the exact create request hash first.
.\.venv\Scripts\python.exe -m infra.runpod.v6 `
  --receipt-out "$EvidenceRoot\01-create-dry-run.json" `
  create --spec 'D:\secure\endpoint-spec.json' --idempotency-key 'idem-<64hex>'

# Real inventory/create only after RUNPOD_API_KEY is injected into this process.
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\00-inventory-before.json" inventory
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\02-create-live.json" `
  create --spec 'D:\secure\endpoint-spec.json' --idempotency-key 'idem-<64hex>'

# Exactly-three dispatch is resumable by rerunning the identical command.
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\03-exact-three-dispatch.json" `
  cohort-dispatch --manifest 'D:\secure\cohort-manifest.json'
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\04-status.json" `
  cohort-status --manifest 'D:\secure\cohort-manifest.json'

# Provider spend is a separate receipt, never an implicit user charge.
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\05-provider-cost.json" `
  billing --bucket-size hour --last-n 24 --endpoint-id '<endpoint-id>'

# Destructive cleanup has an exact target confirmation and ends only on GET 404.
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\06-cleanup-provider-absence.json" `
  cohort-cleanup --manifest 'D:\secure\cohort-manifest.json' `
  --confirm-endpoint-id '<endpoint-id>' `
  --evidence-receipt-sha256 'sha256:<64hex>' `
  --artifacts-uploaded --grace-window-elapsed
.\.venv\Scripts\python.exe -m infra.runpod.v6 --execute `
  --receipt-out "$EvidenceRoot\07-orphan-audit.json" `
  audit-orphans --run-tag 'v6-cohort-<id>' `
  --deleted-endpoint-id '<endpoint-id>'
```

The cohort manifest contains `schema_version`, `endpoint_id`, an absolute
`ledger_path`, `expected_cost_usd`, exactly three `RepeatRun.to_dict()` records,
and `inputs_by_run` keyed by those three run IDs. It contains no credential.
The JSONL ledger is the authoritative resume source; status, accepted billing,
provider billing, hard stops, delete intent/acknowledgement, and terminal
provider-absence hashes are chained without overwriting failed attempts.
