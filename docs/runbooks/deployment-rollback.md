# Deployment, canary, and rollback

## Before deployment

1. Select an immutable commit and signed API/web/scheduler image digests.
2. Verify CI, security, infrastructure, model-registry, license, and release
   evidence all reference that commit. Resolve every high/critical finding.
3. Render the Kubernetes environment overlay and reject `.invalid`,
   `replace-with-*`, mutable images, plaintext Secrets, wildcard CORS, and
   broad egress.
4. Confirm workload identity, database PITR, object versioning, alerts,
   dashboards, runbooks, on-call ownership, and rollback artifacts.
5. Run the revision-named migration Job. Database changes must be
   backward-compatible with both current and previous application revisions.

## Canary

- Deploy one canary replica with external providers and experimental routes
  still disabled.
- Run synthetic login/upload/analyze/compile/SSE/export/delete.
- Compare request error/latency, job completion, queue age, source coverage,
  credit settlement, costs, audit writes, and deletion receipts.
- Increase traffic through reviewed steps, for example
  1% -> 5% -> 20% -> 50% -> 100%, only after each observation window passes.
  Model rollout is independent from application rollout and uses its own
  revision/cost/quality gates.

Stop automatically on cross-tenant indicators, audit-write failure, duplicate
credit, schema-invalid export, revision mismatch, broad deletion failure, or a
burn-rate threshold. Do not wait for a percentage window on a hard fail.

## Rollback

1. Set the narrowest affected feature/provider traffic to zero.
2. Roll back to the last signed application/configuration/model tuple; do not
   use an unrecorded floating tag.
3. Do not reverse a database migration unless its reviewed down migration is
   proven safe. Prefer forward repair after expand/migrate/contract changes.
4. Drain or replay only idempotent work. Reconcile event sequence, outbox/DLQ,
   source/result hashes, exports, credits, and deletion jobs.
5. Repeat the synthetic canary and keep the incident open until telemetry is
   stable.

Record the trigger, timestamps, revisions, commands/workflow runs, observed
impact, reconciliation results, and follow-up. A rollback plan in Git is not
evidence that rollback has been demonstrated.
