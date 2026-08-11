# Worker Privilege Boundary — What Shipped, and Why BYPASSRLS Is Still On

*Measured 2026-08-11 against a throwaway PostgreSQL 17.2 cluster with all 34
migrations applied. Receipt: `docs/audit/receipts/privilege-receipt.json`
(sha256 `eeb750adf9398593258808f1bf25127c87775c3da0a8c4491ad32a9bfe0d8250`).*

The plan was: inject tenant context into every worker transaction, then remove
`BYPASSRLS` from the seven worker roles and let the existing `RESTRICTIVE`
policies do the scoping. Step one shipped. **Step two cannot be executed as
specified, and the reason is a property of the schema, not of the workers.**

---

## 1. The blocker

`0015_project_access` gave every project-scoped table a `RESTRICTIVE` policy
that consults `memberships` and `project_memberships`:

```
RESTRICTIVE SELECT USING (
  tenant_id = current_setting('app.tenant_id')::uuid
  AND ( EXISTS (SELECT 1 FROM memberships …)
     OR EXISTS (SELECT 1 FROM project_memberships … ) )
)
```

**63 of 112 tables carry such a policy. 30 of those are granted to worker roles.
No worker role holds any grant on `memberships` or `project_memberships`.**

PostgreSQL evaluates a policy's subqueries as the querying role. So with
`BYPASSRLS` removed, the worker does not get zero rows — it gets an error:

```
akc_url_fetcher (NOBYPASSRLS), SELECT id FROM url_fetch_tasks:
  [1] no context at all           InsufficientPrivilegeError: permission denied for table memberships
  [2] app.tenant_id = A           InsufficientPrivilegeError: permission denied for table memberships
  [3] app.tenant_id + app.user_id InsufficientPrivilegeError: permission denied for table memberships
```

Granting the worker read on the two membership tables removes the error and
replaces it with the failure mode the staged ordering existed to prevent:

```
after GRANT SELECT ON memberships, project_memberships TO akc_url_fetcher:
  no context                    0 rows
  app.tenant_id = A only        0 rows   <-- the worker cannot see its own job
  app.tenant_id + owner user_id 1 row
```

The only context that returns the row impersonates a specific human who is an
owner/admin of that tenant. That is a **worse** posture than `BYPASSRLS`: it
lends the worker a person's authority, it breaks when that person's membership
is revoked, and it makes pipeline correctness depend on membership rows.

## 2. The second blocker: a queue poll has no tenant

Independent of the policies, every worker's claim step is cross-tenant by
construction — a queue has no tenant until a row is read:

| site | shape |
|---|---|
| `scheduler.py:848` `publish_outbox_batch` | one batch, `{event.tenant_id for event in events}` — many tenants |
| `scheduler.py:647` dispatch claim | ranks candidates across tenants, admits one |
| `deletions.py:328` retention sweep | sweeps expired documents across all tenants |
| `url_fetcher/worker.py:296` | `SELECT … ORDER BY available_at` over all tenants |
| `gpu_jobs.py:876` | `SELECT … FOR UPDATE SKIP LOCKED` over all tenants |

A single `app.tenant_id` cannot cover these. Any real design needs a *narrow*
cross-tenant read capability for the claim, distinct from the tenant-scoped
capability for the work.

## 3. What this means for the plan

The premise that "Stage B is nearly free" held for the representative tables
that were sampled — `outbox_events` and `deletion_requests` do carry only the
simple tenant policy. It does not hold for the project-scoped tables, which are
the majority of what workers touch.

**A candidate design, not implemented, because it changes the multi-tenant
security model and that is a founder decision:** make the user-level half of the
project policies conditional on a user context being present —

```
tenant_id = current_tenant()
AND ( current_setting('app.user_id', true) IS NULL OR '' = current_setting(…)
      OR <existing membership check> )
```

Tenant scoping still binds unconditionally; the human-authorization gate applies
only to sessions that claim a human. That would touch 63 tables' policies and
weakens the policy for any path that sets tenant without user, so it needs a
survey of API call sites before anyone writes it.

---

## What did ship

**Tenant context injection (plan step 1).** `enter_tenant_context()` in
`packages/security/src/akc_security/tenant_context.py` sets `app.tenant_id` with
`set_config(..., is_local => true)` so it dies with the transaction and cannot
leak across a pooled connection. It fails closed on a missing tenant and on a
tenant that disagrees with the claimed job row. Applied at the post-claim
boundary in the url fetcher, deletion consumer, dispatch loop, GPU control
plane, cpu-document worker and the v6 checkpoint store. Inert while `BYPASSRLS`
holds — which is the point of doing it first.

**One-table repair (step 3).** `0033_backfill_checkpoint_tenant_rls` gives
`collection_metadata_backfill_checkpoints` `ENABLE`/`FORCE ROW LEVEL SECURITY`
and four `RESTRICTIVE` tenant policies, matching the surrounding idiom. Receipt
findings went 8 → 7; the remaining 7 are the `BYPASSRLS` roles.

**Catalog-driven gate (steps 4-6).** `infra/postgres/schema_security_gate.py`
replaces two hardcoded table lists with a live catalog read, so a table that
gains `tenant_id` without RLS fails CI on arrival. The probe role now holds the
union of the real worker grants — 63 tables and 201 column grants — instead of
the previous `GRANT … ON ALL TABLES`, which was broader than any role that runs.

## Negative-test results

Tests 1-7 pass against a role reproducing the real worker grant surface with no
`BYPASSRLS` and no ownership. They cannot be run *as* the worker roles while
those roles hold `BYPASSRLS`, because such a role sees every tenant by
definition.

| # | test | result |
|---|---|---|
| 1 | tenant A → B SELECT | blocked |
| 2 | tenant A → B INSERT / UPDATE / DELETE | INSERT rejected; UPDATE/DELETE affected 0 rows |
| 3 | guessed UUID / direct PK | 0 rows |
| 4 | missing tenant context | 0 rows |
| 5 | spoofed tenant context | 0 rows |
| 6 | job tenant ≠ DB context | unreachable |
| 7 | append-only UPDATE/DELETE | denied for all 5 ledgers |
| 8 | worker roles `rolbypassrls = false` | **not met — 7/7 still hold it** |
| 9 | runtime role is not table owner | holds for all 7 |

## Remaining exceptions

- **Seven roles hold `BYPASSRLS`** — `akc_analysis_worker`,
  `akc_deletion_worker`, `akc_dispatch_worker`, `akc_gpu_worker`,
  `akc_payment_worker`, `akc_scheduler`, `akc_url_fetcher`. Blocked as above.
  The gate fails if an eighth appears.
- **`trial_sessions`** carries `project_id` but holds only a tenant-isolation
  policy. Pre-existing; recorded as a named exception in
  `verify_postgres_gate.py` rather than silently skipped.
- **`akc_payment_worker`** has no worker service in the tree, so there was no
  claim site to instrument.
- **Cross-tenant batch transactions** (§2) carry no injected context, because
  no single tenant is correct for them.
- **`app.workspace_id`** was in the plan; no table in the catalog has a
  `workspace_id` column, so nothing was set.

## Rollback

`alembic downgrade 0032_accepted_block_invalidations` drops the four policies
and the FORCE/ENABLE flags, restoring the pre-0033 state. Verified as a
round trip: `t|t|4` → `f|f|0` → `t|t|4`. The context injection is additive and
inert under `BYPASSRLS`; reverting the commit restores prior behaviour with no
schema change.
