# Arming the worker authorization boundary — steps 6 to 9

> **Superseded by `V5_WORKER_AUTHZ_DECISION_PACKAGE.md`.** That document is the
> settled plan. Five of the six prerequisites listed here were routed to the
> founder and should not have been — they are engineering decisions, and they are
> made there with reasons. Only the queue-claim mechanism (A-6 below) survives as
> a founder decision. Kept for the reasoning behind the disarm ordering, which the
> package carries forward unchanged.

**Nothing in this document has been executed.** It is the written-down sequence
for removing `BYPASSRLS`, prepared while the schema work of steps 1–5 was fresh,
so that the arming session starts from a plan rather than from archaeology.

Steps 1–5 landed in `0034_dual_plane_authorization` and are inert: all seven
worker roles still hold `BYPASSRLS`, and
`infra/postgres/shadow_validate_dual_plane.py` asserts that they do.

---

## The order, and why it is this order

Arming is per role, and the roles are not equally ready. Two independent things
have to be true for a role before its attribute comes off:

1. **The schema admits it.** Every table it holds a grant on must have a
   permissive policy that applies to it, and no policy applicable to it may
   reference a table it cannot read. `0034` did this for all seven, and the
   schema security gate now fails if it stops being true.
2. **The code binds what the policies read.** Every claim site must call
   `enter_claim_context()` before touching a lease-bearing table, and every
   cross-tenant scan must call `enter_control_plane_context()`. **This is not
   done.** It is the whole of step 6.

Condition 1 without condition 2 produces a worker that sees zero rows. That is
fail-closed, which is correct, and it is also an outage.

---

## A — prerequisites, none of them executed

| # | Item | Where |
|---|---|---|
| **A-1** | Every claim site calls `enter_claim_context()` with the lease token it is about to write | `services/url-fetcher/.../worker.py:_claim`, `services/scheduler/.../gpu_jobs.py:_claim`, `services/api/.../deletions.py:_claim_deletion_request`, the analysis task claim |
| **A-2** | Every cross-tenant scan calls `enter_control_plane_context()` with its purpose | `scheduler.py` `publish_outbox_batch`, `_dispatch_on_connection`, `_deliver_locked`, `cleanup_retained_rows`; `deletions.py` `_run_retention_sweep_unlocked` |
| **A-3** | `akc_api_runtime` is granted `LOGIN` with a real credential, and the API is wired to `SET ROLE akc_api_plane` after connecting | deployment + `services/api` |
| **A-4** | Control-plane grants narrowed from whole tables to the columns the scheduler selects | requires changing the ORM selects first — see `V5_CONTROL_PLANE_BOUNDARY.md` §3.2 |
| **A-5** | A payload contract for `outbox_events.payload` / `job_events.payload`, so "no document content in events" becomes structural rather than a code reading | §3.3 of the same document |
| **A-6** | **A founder decision on whether the other six worker roles get a bounded cross-tenant capability, and on which tables** | `control_plane_registry.py`, `V5_CONTROL_PLANE_BOUNDARY.md` §5a |

**A-6 blocks step 8 outright, and it is not an agent's call.** Measured: an armed
`akc_url_fetcher` reads zero rows from `url_fetch_tasks` whether it declares a
purpose or not, because the only permissive policy there requires a tenant and a
queue poll has none. The same applies to `gpu_provider_invocations`,
`analysis_tasks`, and to `akc_dispatch_worker` / `akc_deletion_worker` polling
`outbox_events`. The scheduler works because the founder approved *its*
boundary; extending that to six more roles is a new approval, with the same
conditions attached — the tables re-derived, the absence of tenant data-plane
content proven per column, the purposes limited, and CI failing on an eighth
table.

**A-1 has a shape that is easy to get wrong.** The claim-binding policy compares
the row's `lease_token` against `app.lease_token`, and the transaction that
*takes* a lease writes a new token. So the worker must declare the lease it is
about to take **before** the `UPDATE`, not after. The binding is "the lease I am
claiming", not "the lease I found".

**A-3 is a founder/operator action, not an agent action.** The migration creates
`akc_api_runtime` `NOLOGIN` with no password on purpose.

---

## B — the disarm order

Least blast radius first, and one role per change so a rollback is one
`ALTER ROLE`.

| Step | Role | Why here |
|---|---|---|
| **6** | `akc_payment_worker` | no worker service exists in the tree, so nothing can break; it is the free rehearsal of the migration shape |
| **7** | `akc_scheduler` | the control-plane boundary is built and shadow-proven for exactly this role; depends on A-2 |
| **8** | `akc_url_fetcher`, then `akc_gpu_worker`, then `akc_analysis_worker` | one at a time, each depends on its own A-1 site |
| **9** | `akc_dispatch_worker`, then `akc_deletion_worker` | last, because the dispatch worker touches 33 tables and the deletion worker performs the irreversible purges |

Each step is its own migration, `0035` onward, and each is:

```python
op.execute("ALTER ROLE akc_payment_worker NOBYPASSRLS")   # upgrade
op.execute("ALTER ROLE akc_payment_worker BYPASSRLS")     # downgrade
```

That is the entire DDL. Everything else was done in `0034`.

---

## C — canary, per role

A migration that flips an attribute is not a canary. The canary is the
observation window between the flip and the next one:

1. Flip in staging. Run the role's own workload — not a synthetic query.
2. Watch for the two failure signatures, which are different problems:
   - `InsufficientPrivilegeError: permission denied for table X` — a policy
     applicable to the role references a table it cannot read. Schema problem;
     `0034`'s retarget was supposed to have removed this class.
   - **zero rows where rows were expected** — a permissive policy is missing, or
     the code did not bind the context the policy reads. Application problem,
     and the dangerous one, because nothing raises.
3. The second signature needs a metric before step 6 begins. A claim loop that
   finds no work looks exactly like an idle queue.
4. Hold for one full retention cycle before the next role. The retention sweeps
   run daily, and they are the paths least likely to be exercised by a smoke
   test.

---

## D — rollback

`ALTER ROLE <role> BYPASSRLS` restores the previous behaviour immediately and
completely; no data moves and no schema changes. That is the reason for the
role-at-a-time shape.

Rolling back `0034` itself is a different and larger act — it returns 247
policies to `PUBLIC`, drops the two plane roles and their grants, and removes
the permissive backfill that `akc_dispatch_worker` now depends on for
`collections` and `collection_events`. It round-trips
(`alembic downgrade 0033_backfill_checkpoint_tenant_rls`, verified), but it
should be a response to a defect in `0034`, not to a problem arming surfaced.

---

## E — what tells you it worked

The gate's `PENDING_INVARIANTS` list is the scoreboard. When
`worker roles are NOBYPASSRLS` moves out of that list and into an assertion,
arming is done, and `_report_bypassrls` becomes `_verify_bypassrls_absent`.

Until then it prints `7/7 (not yet removed)` on every CI run, which is the
correct amount of noise for an unfinished security control.
