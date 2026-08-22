# Privilege Receipt — Findings

*Generated 2026-08-11 from a live PostgreSQL 17.2 catalog at
`0032_accepted_block_invalidations`. Receipt:
`docs/audit/receipts/privilege-receipt.json`. Generator:
`scripts/generate_privilege_receipt.py`.*

> **Superseded in part, kept as the measurement it was.** The numbers below are
> the state at `0032`. `0033_backfill_checkpoint_tenant_rls` closed finding 1,
> so the current receipt reads 106 tables with RLS and 7 findings rather than
> 105 and 8. §4's conclusion that "Stage B is nearly free" was drawn from the
> simple tenant tables and **does not hold** for the project-scoped ones —
> see `docs/audit/V5_WORKER_PRIVILEGE_BOUNDARY.md`.

**The catalog corrects the survey it was meant to confirm, in the direction that
makes the work smaller.** The RLS posture is already close to what Stage A was
going to build. One table is genuinely unprotected. The `GRANT ON ALL TABLES`
pattern is not in the production migrations at all.

---

## Result

| | |
|---|---:|
| Tables | **112** (the static survey said 107) |
| Carrying `tenant_id` | **106** |
| …with RLS enabled | **105** |
| …with FORCE RLS | **105** |
| …with ≥1 policy | **105** |
| Genuinely global (no `tenant_id`) | **6** |
| **Findings** | **8** |

The six without `tenant_id` are exactly the six predicted:
`tenants`, `users`, `model_registry`, `oidc_identities`,
`oidc_login_transactions`, `alembic_version`.

### The eight findings

```
[collection_metadata_backfill_checkpoints]  tenant_id column but RLS not enabled
[-]  role akc_analysis_worker  has BYPASSRLS
[-]  role akc_deletion_worker  has BYPASSRLS
[-]  role akc_dispatch_worker  has BYPASSRLS
[-]  role akc_gpu_worker       has BYPASSRLS
[-]  role akc_payment_worker   has BYPASSRLS
[-]  role akc_scheduler        has BYPASSRLS
[-]  role akc_url_fetcher      has BYPASSRLS
```

Seven are the known BYPASSRLS design that Stage A removes. **One is a table.**

---

## 1. `collection_metadata_backfill_checkpoints` — the only unprotected table

```json
{ "tenant_id": true, "rls_enabled": false, "rls_forced": false,
  "policy_count": 0, "grants": {} }
```

It carries a tenant, has no RLS, no policy — **and no grants to anybody**. Its
ACL is empty, so no runtime role can reach it regardless. It is a
defence-in-depth gap rather than an exposure: the outer control (grants) holds
while the inner one (RLS) is absent.

It is also the exact shape the schema-security gate exists to catch — a table
that acquired `tenant_id` without acquiring the protection that is supposed to
travel with it. Stage A fixes the table; the gate makes the class impossible.

## 2. `GRANT ON ALL TABLES` is not in the production migrations

The instruction was to abolish that pattern. **It is not there to abolish.**
Per-role grant surface, measured from the ACLs, excluding owner rights:

| Role | Tables | Privileges held |
|---|---:|---|
| `akc_dispatch_worker` | 33 | INSERT, SELECT |
| `akc_deletion_worker` | 30 | DELETE, INSERT, SELECT |
| `akc_analysis_worker` | 18 | DELETE, INSERT, SELECT |
| `akc_gpu_worker` | 16 | INSERT, SELECT |
| `akc_payment_worker` | 12 | INSERT, SELECT |
| `akc_scheduler` | 7 | DELETE, INSERT, SELECT |
| `akc_url_fetcher` | 7 | INSERT, SELECT |

Already table-scoped and action-scoped. **No role holds UPDATE. No role holds
TRUNCATE.** No privilege is granted to `PUBLIC` anywhere.

The blanket pattern lives in exactly one place —
`infra/postgres/verify_postgres_gate.py`, which creates its disposable CI role
with `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public`. So
the CI probe role is broader than any production role, which means **tenant
isolation is currently being proven against a role more privileged than the ones
that actually run.** That is the thing to fix, and it makes the test stronger
rather than weaker.

## 3. Append-only ledgers are already correct

All five, checked against the receipt:

```
accepted_blocks        grants: akc_dispatch_worker = INSERT, SELECT
                       policies: accepted_blocks_insert (INSERT)
                                 accepted_blocks_select (SELECT)
```

No UPDATE or DELETE grant, no UPDATE or DELETE policy. The instruction to keep
them INSERT-only is **already satisfied** — Stage A's job is to assert it, not to
impose it.

The first version of this receipt reported these five as findings, because it
counted the *owner's* full rights as grants. Owner rights come with ownership and
cannot be revoked; reporting them would flag the definition of ownership as a
defect on all 112 tables. FORCE RLS is what constrains an owner, and that is
asserted separately. The generator now excludes the owner from the grant checks.

## 4. Stage B is nearly free, because the policies are already written for it

A representative tenant table:

```
RESTRICTIVE  SELECT  TO PUBLIC  USING (tenant_id = current_setting('app.tenant_id')…)
RESTRICTIVE  INSERT  TO PUBLIC  WITH CHECK (…)
RESTRICTIVE  UPDATE  TO PUBLIC  USING (…)
RESTRICTIVE  DELETE  TO PUBLIC  USING (…)
```

Three properties make this the Stage B substrate:

- **`RESTRICTIVE`** — ANDed with everything else. It cannot be widened by adding
  a permissive policy elsewhere.
- **`TO PUBLIC`** — it already applies to *every* role, workers included.
- **`current_setting('app.tenant_id')`** — the GUC mechanism Stage B needs to
  populate already exists and is already what the policies read.

**Workers escape this today only by holding BYPASSRLS.** Remove the attribute and
set `app.tenant_id` in the worker's transaction, and row scoping is correct
immediately — no new policy vocabulary, no per-worker exemption policies, no
`USING (true)`.

This collapses the earlier plan's most invasive element. The rejected design —
a catalog-wide `akc_rls_exempt` group with a permissive exemption on every
FORCE-RLS table — was solving a problem the schema does not have.

---

## What Stage A and Stage B actually are now

**Stage A**

1. Enable RLS + FORCE + tenant policy on `collection_metadata_backfill_checkpoints`.
2. `ALTER ROLE … NOBYPASSRLS` on the seven worker roles.
3. Narrow the CI gate's probe role from `ON ALL TABLES` to the union of the real
   per-role grants, and probe **as the actual runtime roles** rather than as a
   synthetic superset.
4. Assert the append-only invariant rather than impose it: no UPDATE/DELETE
   grant or policy on the five ledgers.
5. Restrict `users` — it is global, which decides *how* it is controlled (role
   grants, not row policies), not *how much*.

Steps 2 and 3 are the behavioural change. Step 1 is a one-table repair. Steps 4
and 5 are assertions over an already-correct state.

**Stage B**

Inject `app.tenant_id` (and `app.workspace_id` where present) into each
tenant-owned worker job's transaction; fail closed when absent or mismatched.
The policies need no rewriting. The test that matters is the negative one: a
worker that sets another tenant's UUID must still see nothing, which the
`RESTRICTIVE` policies already guarantee once BYPASSRLS is gone.

**Ordering.** Stage A step 2 removes the workers' escape hatch, so the tenant
context of Stage B must be in place first or workers go to zero rows. The safe
sequence is: inject context (B, inert while BYPASSRLS holds) → remove BYPASSRLS
(A) → verify. The two stages interleave rather than stack, and the plan must say
so.

---

## Method

A throwaway PostgreSQL 17.2 cluster was initialised on port 55432 with its own
data directory, all 33 migrations applied, the catalog read, and the cluster
destroyed. The machine's own `postgresql-x64-17` service and its `akc` database
were not touched — its credentials in `.env` do not authenticate against it, and
migrating a database this work does not own is not a survey.

**One documented deviation.** pgvector is not installed on this machine, so
`0024_production_hybrid_retrieval` could not run as written. A *copy* of the
migration tree outside the repository substituted `vector(1024)` with `real[]`
and omitted the `hnsw` index. The repository was not modified.

The substitution cannot affect this receipt: it changes a column's type and drops
one index, while the receipt measures ownership, RLS flags, policies and ACLs.
`knowledge_retrieval_records` appears with its real policies and grants. Anyone
regenerating this against a pgvector-equipped PostgreSQL should get an identical
privilege picture — and that reproduction is worth doing in CI, which already has
the right image.

## Reproducing

```bash
python scripts/generate_privilege_receipt.py \
  --url "$AKC_CI_ADMIN_DATABASE_URL" \
  --out docs/audit/receipts/privilege-receipt.json
```

Add `--check` to fail on drift. That is what turns the receipt into the
schema-security gate: a new table with `tenant_id` and no RLS changes the
receipt, and a changed receipt fails CI.
