# Tenant Scope Survey

*Input for the PostgreSQL privilege-separation work, Stage B. Measured
2026-08-11 against `3fc63ab`.*

Stage B injects a `tenant_id` / `workspace_id` context into each tenant-owned
worker job's transaction so RLS constrains the actual row scope. That only works
if every row a worker touches carries a tenant. This file answers whether it
does.

**Answer: yes, with five exceptions, all of them genuinely global.**

---

## 1. Table inventory

| | Count |
|---|---:|
| Tables in `akc_api.models.Base.metadata` | 92 |
| Tables created by migrations but absent from that metadata | 15 |
| **Total** | **107** |

The 15 outside the API's ORM are the v6 parallel-runtime ledgers and the hybrid
retrieval tables:

```
parse_shards            parse_attempts          attempt_validations
worker_health           semantic_health_events  continuity_edges
accepted_blocks         recovery_tasks          arbitration_decisions
url_fetch_tasks
knowledge_retrieval_records          knowledge_retrieval_edges
knowledge_retrieval_corpus_stats     knowledge_retrieval_term_frequencies
knowledge_retrieval_term_stats
```

These are exactly the tables the workers claim jobs from, so a survey that only
read the API's ORM would have missed the ones Stage B most depends on.

## 2. Tenant scope

**87 of the 92 ORM tables carry a direct `tenant_id` column.**

The five that do not:

| Table | Why it is global |
|---|---|
| `tenants` | the tenant registry itself; scoped on `id`, not `tenant_id` |
| `users` | global identity — a user exists before and across tenancy |
| `model_registry` | control plane; self-referencing FK, no tenant dimension |
| `oidc_identities` | FK to `users`; identity, not tenant data |
| `oidc_login_transactions` | FK to `tenants` and `users`; pre-authentication state |

**All nine v6 parallel-runtime tables carry `tenant_id`**, asserted by the
migration itself rather than inferred — `0031_parallel_pod_runtime._REQUIRED_COLUMNS`
declares the column set per table and every one includes it:

```
parse_shards 24 cols · parse_attempts 28 · attempt_validations 14
worker_health 20 · semantic_health_events 12 · continuity_edges 13
accepted_blocks 15 · recovery_tasks 15 · arbitration_decisions 15
```

Five of them are append-only (`attempt_validations`, `semantic_health_events`,
`continuity_edges`, `accepted_blocks`, `arbitration_decisions`), which matters
for Stage A: an append-only table needs an INSERT policy and no UPDATE/DELETE
policy at all, and that asymmetry is a security property rather than an
oversight.

### The three unknowns that blocked planning

All resolve to *has `tenant_id`*:

| Migration group | Question | Answer |
|---|---|---|
| `0031` parallel pod runtime | do the worker ledgers carry tenant? | **yes, all nine** |
| `0006` email/abuse verification | `email_verification_tokens`, `email_verification_deliveries` | **yes, both** |
| `0025` collection processing runtime | `collection_events`, `collection_processing_task_bindings`, `architecture_plans` | **yes, all** |

**Stage B is therefore tractable.** There is no class of worker job whose rows
lack a tenant to scope by. The work is injecting the context and narrowing the
policies — not inventing a tenant dimension that does not exist.

## 3. Gate coverage vs. tenant scope

`infra/postgres/verify_postgres_gate.py` verifies RLS on:

| Set | Count |
|---|---:|
| `TENANT_TABLES` — ENABLE + FORCE + ≥1 policy asserted | 31 |
| `PROJECT_SCOPED_TABLES` — RESTRICTIVE policy per command asserted | 25 |
| **Union** | **56** |

**53 tables carry a `tenant_id` column and appear in neither set.**

```
architecture_plans          asset_registry              authority_facts
authority_mappings          blueprint_modules           collection_events
collection_files            collection_integrity_action_executions
collection_integrity_decisions                          collection_preflights
collection_metadata_backfill_checkpoints
collection_processing_task_bindings                     collection_regions
collection_source_roots     collection_upload_sessions  collections
cost_prediction_models      credit_grants               credit_reversals
deletion_attempts           deletion_objects            deletion_requests
document_clusters           email_verification_deliveries
email_verification_tokens   estimate_runs               estimate_samples
export_packages             file_content_hashes         file_versions
free_daily_usage            free_processed_sources      free_usage_reservations
knowledge_compile_runs      mfa_challenges              mfa_credentials
package_files               package_validations         page_fingerprints
payment_checkouts           payment_disputes            payment_events
payment_reconciliations     payment_refunds             payments
preflight_feature_records   quarantine_items            region_attempts
route_attempts              trial_sessions              upload_file_sessions
upload_parts                verification_records
```

### What this does and does not mean

**It means CI does not check these 53.** It does **not** mean they lack RLS.

Migrations enable RLS through f-string loops over table lists rather than literal
DDL — `0001` alone emits 28 `ENABLE ROW LEVEL SECURITY`, 28 `FORCE`, and 28
`CREATE POLICY` statements — so static analysis of the migration source
undercounts badly. Two attempts at it here produced numbers that were plainly
wrong (a literal-DDL grep reported 2 tables; an offline `alembic upgrade --sql`
run stopped at revision 0002 because a later migration inspects the connection).

**Per-table RLS status is only knowable from the catalog.** The CI job already
has a live PG17 with `alembic upgrade head` applied, so it is a query away:

```sql
SELECT c.relname,
       c.relrowsecurity      AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       count(p.polname)      AS policies
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_policy p ON p.polrelid = c.oid
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity
ORDER BY rls_enabled, c.relname;
```

Running that and reconciling against this file's 87 is the first task of Stage A,
and its output is the **privilege receipt** the founder asked for. Whatever it
returns, the gate should assert it going forward — a table with `tenant_id` and
no policy is either a finding or a documented exception, and today it is neither
because nothing looks.

### Five tables in a gate set with no `tenant_id` column

`project_memberships`, `team_invitations`, `team_invitation_deliveries`,
`url_fetch_tasks`, `tenants`. These are scoped through a different key
(`project_id`, `id`) and are correctly covered — noted so the reconciliation does
not read them as anomalies.

---

## 4. Recommended global-control-table list

v5 requires that only *genuinely* global control tables get a broader policy. On
this survey the list is short and every entry has a reason:

| Table | Justification |
|---|---|
| `tenants` | the registry being scoped; already RLS'd on `id` |
| `users` | global identity, pre- and cross-tenant |
| `oidc_identities` | identity binding, keyed to `users` |
| `oidc_login_transactions` | pre-authentication state, exists before a tenant is known |
| `model_registry` | control plane; no tenant dimension exists to scope by |
| `alembic_version` | migration bookkeeping; not application data |

Six entries out of 107. **Nothing else qualifies**, and in particular no worker
ledger does — `worker_health` looks like infrastructure but carries `tenant_id`
and should be scoped like everything else.

`users` deserves a note. It is global *and* it is the one table where a broad
grant is most consequential, since it holds identity. Being outside tenant RLS
does not mean it should be readable by every runtime role; it means its access
control is per-role grants rather than row policies, and Stage A should narrow
those grants rather than leave the current blanket `GRANT ON ALL TABLES` pattern
in place.

---

## 5. Method and its limits

- Table inventory and column presence: read from `Base.metadata` and from
  `0031._REQUIRED_COLUMNS` by importing the modules. Reliable.
- Gate coverage: parsed from the `TENANT_TABLES` / `PROJECT_SCOPED_TABLES`
  frozensets. Reliable.
- **RLS enablement per table: not established here.** Static analysis was
  attempted, gave contradictory answers, and is recorded as failed rather than
  reported. The catalog query above is the answer.

No database was created or migrated to produce this. A local PostgreSQL 17
service is running on this machine; it was left alone, because applying
migrations to a database this work does not own is not a survey.
