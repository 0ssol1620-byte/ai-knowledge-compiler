# Backup, restore, and deletion drill

This runbook defines the evidence required to claim recoverability. Terraform,
versioned buckets, or a successful backup job alone are not restore evidence.
No RPO/RTO is considered achieved until a timed isolated restore passes the
application checks below.

## Preconditions and ownership

- Platform/SRE owns the drill; Security observes tenant-isolation and audit
  checks; Privacy observes deletion/retention checks.
- Use an isolated nonproduction account and synthetic tenant. Never restore
  production customer data into a developer-accessible environment.
- Record the application commit, signed image digests, migration revision,
  model/configuration revisions, database backup identifier, object manifest
  version, region, drill owner, and UTC start time.
- Confirm the destination has default-deny networking, workload identity,
  external secrets, encrypted volumes, no outbound provider access, and
  production-equivalent RLS.
- Set a plan-specific approved target before starting. `target_rpo_minutes` and
  `target_rto_minutes` may not be left blank and are not inferred from vendor
  marketing.

## Backup controls

PostgreSQL requires encrypted automated backups plus point-in-time recovery,
cross-account access controls, retention alarms, and periodic backup
enumeration. Object storage requires KMS encryption, versioning, lifecycle
policy, public-access blocks, incomplete multipart cleanup, and an inventory
that binds database object references to object version IDs. Audit evidence
uses governance Object Lock; legal hold remains a separate approved workflow.

Backups and object versions inherit the source data classification. Access,
restore, export, and deletion actions are audited without logging content,
credentials, or presigned URLs.

## Quarterly restore drill

1. Freeze the drill scope and calculate the intended recovery point in UTC.
2. Restore PostgreSQL to a new isolated instance at that point in time.
3. Restore or reference versioned object manifests at the corresponding
   versions. Do not silently use current objects with an older database.
4. Apply only forward-compatible migrations required by the selected
   application revision; record every migration and duration.
5. Start the API with external processing disabled and durable workers paused.
6. Verify database readiness, schema revision, tenant memberships/RLS,
   source/result hashes, job event sequence continuity, credit ledger balance,
   export reproducibility, retention schedules, and deletion receipts.
7. Run cross-tenant negative tests and prove one tenant cannot list, download,
   stream, export, or delete another tenant's artifacts.
8. Resume a bounded synthetic job and verify no duplicate event, work item, or
   credit consumption occurs.
9. Measure:
   - `recovery_point_utc` and data age at incident time;
   - `database_restore_seconds`;
   - `object_reconcile_seconds`;
   - `migration_seconds`;
   - `application_ready_seconds`;
   - total achieved RPO and RTO.
10. Destroy the isolated environment through the reviewed account workflow and
    retain only sanitized evidence and deletion confirmation.

The drill fails closed if any object hash is missing/mismatched, RLS is absent,
the ledger does not reconcile, events have gaps/duplicates, deletion state is
reversed, the measured target is missed, or required evidence is incomplete.

## Mass-deletion drill

1. Require a dry-run inventory, step-up authentication, dual approval, and an
   explicit synthetic tenant/project scope. Reject prefixes, globs, empty IDs,
   and production accounts.
2. Delete source, derived, export, index, cache, and eligible training-pool
   records through idempotent jobs.
3. Preserve only the minimum lawful content-free audit event and deletion
   receipt.
4. Verify object absence, database tombstones/absence, cache/index
   invalidation, future training exclusion, presigned URL expiry, and the
   backup-expiry schedule.
5. Re-run the request and prove it does not widen scope or fail unsafely.
6. Attempt recovery from ordinary product paths and prove deleted material is
   unavailable. Document the date on which retained backups age out.

Object Lock or regulatory retention may delay physical deletion. The product
must disclose that boundary and track the expiry; it must not report immediate
physical erasure when only logical deletion occurred.

## Evidence record

Store a content-free JSON/Markdown bundle with:

- drill ID, approvers, environment/account, timestamps, and incident scenario;
- immutable application/config/model/migration revisions;
- backup and object-manifest identifiers or hashes;
- target and measured RPO/RTO;
- checks and exact pass/fail counts;
- alert screenshots/IDs and sanitized logs;
- failures, corrective owners/dates, and rerun reference;
- environment destruction and synthetic-data deletion receipt.

The artifact must say `production_recovery_proven: false` for local or
scaffold-only runs. A failed drill is valuable evidence but never a passed
release gate.
