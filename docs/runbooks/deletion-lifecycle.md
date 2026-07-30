# Durable deletion lifecycle

## Contract

`DELETE /v1/documents/{id}` and `DELETE /v1/projects/{id}` return `202
Accepted` with a deletion request ID and `status_url`. Supply
`Idempotency-Key` on every call. Reusing a key for the same target returns the
same deletion request; reusing it for another target returns `409`.

The acceptance transaction immediately tombstones the target. All normal read,
write, analysis, compile, export, download, dashboard, and event-stream paths
then treat it as absent. In that same transaction, queued/running compile and
analysis work is cancelled and any outstanding credit reservation is released
through a unique ledger operation key. The transaction also writes an
immutable database and object manifest plus `deletion.purge.requested.v1`. It
does not claim that physical erasure has completed.

Poll `GET /v1/deletions/{request_id}`:

- `requested`, `purging`, and `retry`: erasure is incomplete and `receipt` is
  null.
- `dead_letter`: the retry budget was exhausted; access remains tombstoned and
  no receipt exists.
- `purged`: every manifest object is absent, domain rows are gone, and the
  content-free immutable receipt is present.

Never infer success from a missing target alone. Only `state=purged` with a
receipt is terminal proof.

## Scheduled retention

The dedicated deletion worker performs a bounded oldest-first sweep using each
tenant's `data_retention_days`. Expired active documents are locked with
`FOR UPDATE SKIP LOCKED` on PostgreSQL and admitted through the same unique,
idempotent `DeletionRequest` and outbox path as manual deletion. The default
sweep interval is one hour
(`AKC_DELETION_RETENTION_SWEEP_INTERVAL_SECONDS=3600`).

Changing a retention value affects later sweeps. It does not bypass the
tombstone, manifest, retry, receipt, or audit state machine.

The application sweep is authoritative for tenant-controlled source, derived,
and export data. Terraform fixes their bucket lifecycle safety net at 3650
days, the largest value accepted by `tenants.data_retention_days`; it cannot
preempt an active tenant policy. Quarantine and working storage remain
separate short-lived classes. JobEvent hot data is removed in bounded,
oldest-first scheduler batches after `AKC_EVENT_RETENTION_DAYS` (default 7)
using the scheduler's exact `SELECT, DELETE` grant.

## Worker trust boundary

Production runs a separate process:

```text
python -m akc_scheduler --mode deletion
```

Before consuming work it validates:

- PostgreSQL and the exact `akc_deletion_worker` effective role;
- a non-login, non-owner, non-superuser BYPASSRLS role with bounded grants;
- forced RLS on deletion evidence tables;
- no user, API-key, webhook, membership, idempotency, or feature-flag access;
- S3-compatible storage and either ambient workload identity or a complete
  static credential pair.

`AKC_S3_DELETION_MODE=versioned` is the AWS/Terraform contract. For each exact
key the worker paginates `ListObjectVersions`, removes every version and delete
marker in batches, rejects provider-reported partial errors, and lists again
before recording success. A delete marker alone is never treated as erasure.
Providers without versioning must be configured explicitly as
`unversioned-explicit`; that is an operator attestation that the bucket cannot
retain historical versions. The adapter deletes the key and proves exact-key
absence with a paginated listing. Unsupported listing or unverifiable absence
fails closed, so no receipt is issued.

The Terraform output `deletion_worker_object_purge_policy_arn` grants only
bucket/version inventory, object/version deletion, and multipart abort for
quarantine, source, working, derived, and export buckets. It grants no object
read and excludes Object-Locked audit evidence.

The Kubernetes base deploys two replicas under `akc-deletion-worker`, a
dedicated service account, restricted security context, PDB, probes, metrics
service, and monitoring-only ingress. Environment overlays must provide a
signed immutable image digest, the deletion runtime database login, storage
buckets, and network egress to only PostgreSQL and the configured object
store.

## Attempt behavior

The consumer claims outbox rows with `FOR UPDATE SKIP LOCKED`, moves their
availability forward as a lease, and takes a per-request PostgreSQL advisory
lock. Object I/O occurs without holding a database row lock. Each object has
independent durable progress:

- a missing object or missing multipart upload is successful and idempotent;
- successful objects are not retried after a partial failure;
- failures record only bounded error codes and object-key hashes;
- exponential backoff is capped and jittered;
- an expired request lease closes the interrupted attempt as
  `deletion_lease_expired` before takeover;
- the receipt and database purge occur only when every object is terminally
  absent.

Queued/running compile and analysis work is fenced. Compile releases its write
transaction before provider latency and rechecks the target under lock after
the provider returns. Deletion cancels eligible work and releases only the
outstanding credit reservation through a unique ledger operation key.

## Operations

Validate configuration and privileges without consuming:

```text
python -m akc_scheduler --check --mode deletion
```

Run one bounded retention and outbox pass:

```text
python -m akc_scheduler --once --mode deletion
```

Monitor:

- `akc_deletion_oldest_pending_seconds`;
- `akc_deletion_attempts_total{result}`;
- `akc_deletion_object_results_total{result}`;
- deletion outbox depth and dead letters;
- a growing difference between `object_count` and `deleted_count`.

Alert when pending age exceeds the retention SLO, any request reaches
`dead_letter`, the capability check fails, or the object store becomes
unreachable.

For a dead letter, preserve the request, manifest, attempts, outbox row, and
receipt absence. Diagnose credentials, bucket policy, provider retention lock,
or database privileges. Recovery must be an approved, audited replay of the
same deletion request ID; do not create an ad hoc manifest, delete evidence
rows, or manufacture a receipt. Escalate legal-hold or provider Object Lock
cases because logical tombstoning is not physical erasure.

## Verification

Release evidence must include:

- API idempotency, immediate no-access, and cross-tenant status isolation;
- partial object failure followed by retry and terminal receipt;
- versioned S3 pagination removes all versions and delete markers, while an
  HTTP-success partial delete response leaves the request retryable with no
  receipt;
- crash after remote delete followed by lease takeover and idempotent rerun;
- retry exhaustion with no receipt;
- concurrent worker single-claim behavior;
- legacy deletion-event compatibility;
- project and empty-project cascade;
- retention sweep duplicate safety;
- in-flight compile versus deletion with no result resurrection, no credit
  consume, and exactly one reservation release;
- bounded JobEvent hot-retention cleanup preserves recent events;
- Alembic upgrade through `0007`, downgrade through `0003`, and re-upgrade;
- deployment/security validators and PostgreSQL role capability checks.
