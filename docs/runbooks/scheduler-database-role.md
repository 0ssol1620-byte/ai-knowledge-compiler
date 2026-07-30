# Scheduler database role

The webhook scheduler is a cross-tenant infrastructure worker. PostgreSQL row
level security is forced on its scheduler-owned tables, so it must never reuse
the API login or bypass tenant policies through an application-settable GUC.

Migration `0002_scheduler_hardening` creates the cluster role
`akc_scheduler` with these properties:

- `NOLOGIN NOINHERIT BYPASSRLS` with all superuser/role/database/replication
  capabilities disabled;
- schema usage on `public`;
- read, bounded state-update, and retention-delete privileges on
  `outbox_events`;
- read-only access to `webhook_endpoints`;
- read, insert, bounded state-update, and retention-delete privileges on
  `webhook_deliveries`;
- read and retention-delete privileges on `job_events` and expired
  `idempotency_records`;
- no access to tenant content, users, credentials, audit rows, or other domain
  tables.

`BYPASSRLS` is not inherited through ordinary role membership. Deployment
provisioning must create a separate login, grant it membership, and place only
that login's URL in the scheduler secret:

```sql
CREATE ROLE akc_scheduler_runtime
  LOGIN
  NOINHERIT
  PASSWORD '<generated-by-the-secret-manager>';
GRANT akc_scheduler TO akc_scheduler_runtime;
```

Durable compile dispatch is a separate trust boundary. The migration also
creates `akc_dispatch_worker NOLOGIN NOINHERIT BYPASSRLS` with only the domain
table/column privileges required by `run_compile_job`. Provision a different
login and grant it only that role:

```sql
CREATE ROLE akc_dispatch_runtime
  LOGIN
  NOINHERIT
  PASSWORD '<generated-by-the-secret-manager>';
GRANT akc_dispatch_worker TO akc_dispatch_runtime;
```

Never grant both roles to one login. Production runs `--mode webhook` with
`akc-scheduler-secrets` and `--mode dispatch` in a separate Deployment with
`akc-dispatch-secrets`. The combined default mode is development/test-only and
fails closed when `AKC_ENV=production`.

Do not put the password in a migration, manifest, image, or Git. The scheduler
uses the asyncpg startup setting `role=akc_scheduler`, so the runtime login must
be allowed to `SET ROLE akc_scheduler`. The API login must not be a member.
Kubernetes therefore injects `akc-scheduler-secrets` into the scheduler rather
than the API's `akc-runtime-secrets`. The scheduler secret must contain its
dedicated `AKC_DATABASE_URL` and the same secret-manager-managed
`AKC_WEBHOOK_ENCRYPTION_KEY` version used by the API.
The one-shot migration job uses `akc-migration-secrets`, whose
database principal owns the schema and has `CREATEROLE`; those privileges must
never be present on either long-running runtime login.

Set:

```text
AKC_DATABASE_URL=postgresql+asyncpg://akc_scheduler_runtime:...@host:5432/akc
AKC_SCHEDULER_DATABASE_ROLE=akc_scheduler
```

The dispatch Deployment instead sets:

```text
AKC_DATABASE_URL=postgresql+asyncpg://akc_dispatch_runtime:...@host:5432/akc
AKC_DISPATCH_DATABASE_ROLE=akc_dispatch_worker
```

At startup and in `python -m akc_scheduler --check`, the process verifies all
of the following before polling:

- the effective role is exactly `akc_scheduler`;
- it is `NOLOGIN` and has `BYPASSRLS`;
- the session login is `LOGIN NOINHERIT`, has no dangerous role attributes,
  owns neither the database nor application tables, and has no direct
  application-table ACLs;
- forced RLS remains enabled on all five scheduler tables;
- every required table and column privilege is present.

Any mismatch exits non-zero. SQLite bypasses this check only as the explicit
non-production test adapter; production configuration rejects SQLite and every
non-PostgreSQL backend.

For rotation, create or alter the runtime login in the secret manager's
provisioning workflow, update `AKC_DATABASE_URL`, roll scheduler pods, verify
`--check`, and only then revoke the old login. Do not alter the `akc_scheduler`
group role to `LOGIN`.

Terminal webhook deliveries are retained for
`AKC_WEBHOOK_DELIVERY_RETENTION_DAYS` (30 days by default), and published
webhook outbox rows for `AKC_OUTBOX_RETENTION_DAYS` (7 days by default).
Immutable dispatch dead-letter evidence is retained separately for
`AKC_DISPATCH_DEAD_LETTER_RETENTION_DAYS` (30 days by default).
Expired mutation replay records use their per-row expiry (30 days by default).
Cleanup is bounded by `AKC_SCHEDULER_CLEANUP_BATCH_SIZE`. Dead-letter replay
must happen before retention expiry.

Compile replicas also use PostgreSQL session advisory locks for cluster-wide
tenant fairness. The dispatcher scans at most one due event per tenant,
acquires a domain-separated tenant semaphore for the full compile attempt, and
then acquires the existing per-job lock. A busy tenant event is deferred
without increasing `attempts`, so it cannot enter the DLQ solely because
another job from the tenant is running. See
[`dispatch-fairness.md`](dispatch-fairness.md) for configuration, telemetry,
failure behavior, and CI evidence.

Webhook delivery defaults to 42 attempts with capped exponential backoff. Even
at the minimum configured jitter this preserves more than 24 hours of retry
coverage for a receiver outage before dead-lettering.
