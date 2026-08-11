# Control Plane Authorization Boundary

*Measured 2026-08-11 against a throwaway PostgreSQL 17.2 cluster with all 35
migrations applied. Receipt: `docs/audit/receipts/privilege-receipt-0035.json`
(internal `receipt_sha256`
`92feefed7344e203e7bc11272d3f1303c7fb04de54e0ffebbb0bc109507d0de6`). The 0033
and 0034 receipts are unchanged and remain the measurements other documents
cite.*

This is not a security exception. An exception is a thing you carve out of a
rule and then stop looking at. This is a **boundary**: a named set of tables, a
named set of purposes, a policy that enforces both, and a CI gate that fails
when the catalog stops matching the list.

The thing it replaces is `BYPASSRLS` on `akc_scheduler` — an attribute that
applies to all 112 tables and asks no questions. `BYPASSRLS` is still on. What
0034 builds is the structure that lets it come off.

---

## 1. Why a cross-tenant capability has to exist at all

A queue has no tenant until a row is read. Every worker's claim step is
therefore cross-tenant by construction, and no value of `app.tenant_id` is
correct for it. `V5_WORKER_PRIVILEGE_BOUNDARY.md` §2 lists the five sites. The
question was never whether to have a cross-tenant read; it was whether it would
be a blanket attribute or a bounded capability.

---

## 2. The seven tables, re-derived

The design named seven. **A previous census of this schema was wrong by seven
tables** — 56 against the receipt's 63 — so the number was re-derived from the
live catalog rather than accepted:

```sql
SELECT c.relname, a.privilege_type
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE n.nspname = 'public' AND pg_get_userbyid(a.grantee) = 'akc_scheduler'
```

| Table | Table grants | Column `UPDATE` grants | Cross-tenant call site |
|---|---|---|---|
| `outbox_events` | SELECT, DELETE | `published_at`, `attempts`, `last_error` | `scheduler.py` `outbox_claim_statement`, `dispatch_claim_statement`, `cleanup_retained_rows` |
| `webhook_deliveries` | SELECT, INSERT, DELETE | 8 delivery-state columns | `delivery_claim_statement`, `publish_outbox_batch`, `cleanup_retained_rows` |
| `webhook_endpoints` | SELECT | — | `publish_outbox_batch`: endpoints for the set of tenants in the claimed batch |
| `job_events` | SELECT, DELETE | — | `cleanup_retained_rows` retention sweep |
| `idempotency_records` | SELECT, DELETE | — | `cleanup_retained_rows` retention sweep |
| `email_verification_tokens` | SELECT, DELETE | — | delivery-outbox retention |
| `email_verification_deliveries` | SELECT, DELETE | 8 delivery-state columns | delivery-outbox poll by `available_at` |

**Seven confirmed, and the derivation is repeated at run time.** The migration
asserts the count, and `infra/postgres/schema_security_gate.py` fails CI in both
directions: a table granted but not registered, and a table registered but no
longer granted.

`akc_scheduler` holds no `UPDATE`, `INSERT` or `TRUNCATE` at table level
anywhere, and no grant at all on the other 105 tables. That is not a claim about
policy — it is the ACL, and the shadow run confirms `documents`,
`url_fetch_tasks` and `collections` raise `InsufficientPrivilegeError` for this
role even with a valid control-plane declaration.

---

## 3. Tenant data-plane content: what was looked for, and what was found

The founder's condition was to prove the boundary carries no customer document
body, no compiled knowledge, no evidence payload and no secrets. Every column of
all seven tables was read. **The honest answer is "none of the four, and three
things adjacent to them."**

### 3.1 Absent

- **No document body, page, block, or extracted text.** None of the seven tables
  has a column of that kind. `documents`, `pages`, `blocks`, `source_files`,
  `document_versions` and `page_assets` are all outside the boundary and
  ungranted.
- **No compiled knowledge.** `knowledge_notes`, `entities`, `relations`,
  `knowledge_retrieval_records` — outside, ungranted.
- **No evidence payload.** The five append-only ledgers are outside, ungranted,
  and separately asserted by the gate to hold no `UPDATE`/`DELETE` for anybody.

### 3.2 Present, and named rather than glossed

Three column families inside the boundary are customer-controlled or secret.
They are recorded in `CONTROL_PLANE_SENSITIVE_COLUMNS` so the gate fails if the
schema moves under this document.

| Column | What it is | Why the grant is not narrowed today |
|---|---|---|
| `webhook_endpoints.encrypted_secret`, `.secret_hash`, `.url` | the HMAC signing secret (encrypted) and the customer's callback URL | the scheduler `SELECT`s the endpoint row to fan out; narrowing to a column list requires changing what `publish_outbox_batch` selects |
| `idempotency_records.response_body`, `.response_body_ciphertext` | an API response body | **`response_body` is never written on the current path** — `idempotency.py:266-267` sets it to `None` and stores only the ciphertext. The plaintext column is a residue of the encryption bridge |
| `email_verification_deliveries.encrypted_payload`, `.recipient_pseudonym`, `email_verification_tokens.token_hash` | an encrypted delivery payload, a pseudonymous recipient, and an HMAC digest of a one-time token | the retention sweep and the delivery poll read the row |

**This is a real gap, and it is not closed here.** The founder's condition says
"grant only the tables, columns and operations needed". At table level that
already holds; at column level it does not, because the scheduler's retention
and fan-out paths select whole ORM entities. Narrowing the grants without first
changing those selects would break the scheduler — a behavioural change, and
this migration's whole discipline is to land inert. It is item **A-4** in
`V5_WORKER_AUTHZ_ARMING.md`.

What can be said without qualification: none of these is a *tenant data-plane*
artifact. Two are ciphertext, one is a digest, one is a pseudonym, one is a URL
the customer configured, and one is dead.

### 3.3 The event payloads — a code-reading result, not a structural one

`outbox_events.payload`, `job_events.payload` and `webhook_deliveries.payload`
are unconstrained `json`. Every construction site in `services/` and `workers/`
was enumerated: **49 build a dict literal, 4 do not.** Across the 49 there are
48 distinct keys, and every one is an identifier, a sha256, a count, a status or
an error code —

```
actor_user_id, analysis_task_id, approved_estimate_sha256, batch_id,
billing_disposition, code, collection_id, credits, document_id, export_id,
job_id, manifest_hash, page_count, project_id, reason, stage, status,
target_type, tenant_id, verification_state, …
```

No `text`, `content`, `body`, `title`, `filename` or `snippet`. Of the four
non-literal sites, three bind a local dict of identifiers a few lines above
(`collection_api.py:5740`, `pdf_passwords.py:236`, and the runtime model at
`collection_semantic_runtime.py:1652`); the fourth, `services.py:210`, takes the
payload as a parameter.

**Stated precisely: no site in the tree writes document content into an event
payload, and nothing structurally prevents one from doing so.** A payload schema
contract would turn this from a reading into a guarantee. It does not exist and
is not built here.

---

## 4. How the boundary is enforced

### 4.1 Purpose, declared

A control-plane policy admits the scheduler only when the transaction has said
what it is doing and has no tenant bound:

```sql
NULLIF(current_setting('app.control_plane', true), '')
  = ANY (ARRAY['claim','job_discovery','lease','retention','scheduling'])
AND NULLIF(current_setting('app.tenant_id', true), '') IS NULL
```

Three properties fall out, all measured:

- **Undeclared sees nothing.** `current_setting(..., true)` returns `NULL` when
  unset, `NULL = ANY(...)` is `NULL`, and the policy does not admit. Fail closed
  by construction rather than by an `IF`.
- **An unapproved purpose sees nothing.** Declaring `exfiltrate` returns zero
  rows.
- **Binding a tenant closes the view.** The cross-tenant reach is available only
  while no tenant is bound, so a transaction cannot discover work across tenants
  and then keep that reach while doing one tenant's work.
  `enter_tenant_context()` also clears the declaration outright, so this holds
  even if the policy is later changed.

This is deliberately **not** `USING (true)`. A blanket exemption would make
every restrictive policy beside it decorative, and it is the design
`V5_PRIVILEGE_RECEIPT_FINDINGS.md` §4 already rejected.

### 4.2 Audit

`akc_security.tenant_context.enter_control_plane_context(handle, purpose=...)`
is the only way the GUC gets set. It refuses a purpose outside the closed set,
refuses when a tenant is already bound, and returns a `ControlPlaneContext`
naming the purpose that was applied — so the caller has something to log and a
test has something to assert. The declaration is per transaction and
`SET LOCAL`, so it cannot leak across a pooled connection.

### 4.3 CI

`infra/postgres/schema_security_gate.py` now fails on:

- a control-plane role granted a table outside `control_plane_registry.py`;
- a registered table the catalog no longer grants;
- an approved table with no purpose-gated policy;
- a control-plane policy that admits any role but `akc_scheduler`;
- **any granted operation with no permissive policy behind it** — see §5;
- a lease-bearing table with no restrictive claim binding;
- a sensitive column named in the registry that the catalog no longer has.

`tests/security/test_control_plane_boundary.py` asserts the three copies of the
purpose list — registry, security package, migration — still agree, without
needing a database.

---

## 5. What the coverage check found

A `RESTRICTIVE` policy grants nothing. A role granted `SELECT` on a table whose
every policy is restrictive gets **zero rows and no error**, which is
indistinguishable from an empty table until someone notices the pipeline
stopped.

The check added in 0034 fired on its first run with six pairs. Two of them were
not created by this work:

```
akc_dispatch_worker collections.SELECT
akc_dispatch_worker collection_events.SELECT
akc_dispatch_worker collection_events.INSERT
```

`collections` and `collection_events` carry only restrictive policies. The
dispatch worker holds grants on both. **Under `BYPASSRLS` this is invisible; the
day the attribute came off, the collection pipeline would have silently seen
nothing.** 0034 gives those two tables a tenant-scoped permissive policy for the
roles that hold the grants.

The other three were the human plane holding operations its own policies do not
admit — `collection_integrity_decisions.UPDATE`/`.DELETE` and
`collection_integrity_action_executions.DELETE`. Those decisions are immutable
evidence, so the fix was to **narrow the grant**, not to invent a policy that
would justify it.

---

## 5a. The gap this work opened, and how F-1 closed most of it

> **Updated 2026-08-11.** The founder settled this as **F-1, Option B**: a claim
> broker rather than a cross-tenant `SELECT`. `0035_claim_broker` landed it for
> `url_fetch_tasks` and `gpu_provider_invocations`. The measurement below is
> preserved as what prompted the decision, and it still describes
> `akc_dispatch_worker` and `akc_deletion_worker`, which remain uncovered.

**As measured, before F-1: only `akc_scheduler` had a bounded cross-tenant
capability. The other six worker roles had none — so once armed they could not
poll their queues at all.**

```
armed akc_url_fetcher, SELECT FROM url_fetch_tasks:
  no declaration                      0 rows
  app.control_plane = 'claim'         0 rows
  app.control_plane = 'job_discovery' 0 rows
```

The claim binding permits an unbound transaction, but the only *permissive*
policy on `url_fetch_tasks` is `url_fetch_tasks_tenant_isolation`, which
requires a tenant — and a queue poll has none. The same holds for
`gpu_provider_invocations`, `analysis_tasks`, and for `akc_dispatch_worker` and
`akc_deletion_worker` reading `outbox_events`, whose control-plane policies name
`akc_scheduler` and nobody else.

This was fail-closed, and it was not a defect in `0034`: before `0034` those
roles could not poll either — `BYPASSRLS` was doing it, and removing it was
always going to expose this. Nor was it mine to fix by widening the boundary,
which is the decision `control_plane_registry.py` exists to force.

**What F-1 chose.** Not a cross-tenant `SELECT` on each queue, which would have
let a compromised worker read every tenant's URLs, parameters and manifests by
declaring a purpose it was going to declare anyway. Instead a `SECURITY DEFINER`
broker per queue that claims one row and returns five identifiers — claim id,
tenant, project, lease token, lease expiry — owned by `akc_claim_broker`, a
`NOLOGIN NOBYPASSRLS` role that reaches the queues through purpose-gated
policies of its own. The workers hold `EXECUTE` and still no cross-tenant read:
`broker:no-cross-tenant-select-remains-declared` proves the grant added a claim
path and not a read path.

**What is still open.** `akc_dispatch_worker` and `akc_deletion_worker` poll
`outbox_events`, which carries no lease to bind and whose control-plane policies
name `akc_scheduler` alone. Admitting them is the same shape of decision as F-1
and is recorded in `control_plane_registry.py` under
`UNBROKERED_CROSS_TENANT_CLAIMS`, with the three measured cases still in the
shadow harness so the gap stays measured rather than remembered.

---

## 6. The two planes

`0034` also splits human authorization from worker authorization, because the
control-plane boundary cannot exist without it: `job_events` carries a
membership-referencing policy, and a worker with no grant on `memberships`
cannot evaluate it — it errors rather than returning nothing.

- **`akc_api_plane`** — the human authorization plane. All 247
  membership-referencing policies now target it. `NOINHERIT`, `NOBYPASSRLS`,
  owns nothing, member of nothing.
- **`akc_api_runtime`** — the login principal. `NOINHERIT`, so the plane is
  assumed by `SET ROLE` rather than held. Created `NOLOGIN` with no password: a
  migration does not mint credentials.

Policies target the plane **directly, never a group**, because
`pg_policy.polroles` does not reach a `NOINHERIT` member of a group — measured
in `V5_WORKER_AUTHZ_SPIKE.md` (D). Group targeting would have produced policies
that silently match nobody.

Retargeting is not a loosening of tenant isolation. The `*_tenant_*` policies
are untouched and still apply to every role. What moved is the
human-authorization half, to the only role that can answer it.

---

## 7. Threat model — what this does *not* claim

**A fully compromised worker is not confined to one tenant.** Say so plainly.

The claim binding stops a worker from reaching a tenant it has not claimed *with
the claim it currently holds*. It does not stop the same worker from doing what
it is designed to do next: returning to the queue and claiming a different job,
which may belong to a different tenant. That is the architecture — one worker
class serves every tenant — and no row policy changes it.

What the boundary does buy, precisely:

| | |
|---|---|
| Reach a tenant it never claimed | **blocked** — forged tenant, project or claim id yields nothing |
| Reuse another job's live lease | **blocked** |
| Act on an expired lease | **blocked** |
| Act with no claim bound | **blocked** |
| Read another worker's queue | **blocked** — no grant |
| Read tenant data as the scheduler | **blocked** — no grant |
| Escalate to another role | **blocked** — one login principal per worker role |
| **Claim a new job and reach that tenant** | **not blocked, by design** |
| **Accumulate tenants over time by claiming repeatedly** | **not blocked** |

The second and third are a separate boundary — admission control on who may
claim what — and it is not built. Anyone writing marketing copy from this
document: "a fully compromised worker cannot reach another tenant" is **false**.
"A worker cannot reach a tenant outside the job it holds" is true.

---

## 8. Measured

`infra/postgres/shadow_validate_dual_plane.py`, 65 cases, all passing. The
inert pass runs as the real worker roles with `BYPASSRLS` exactly as it ships.
The armed pass removes the attribute **in the throwaway cluster only**, measures,
and restores it; the run fails if restoration did not happen. The human-plane
pass needs no shadow — `akc_api_plane` has never had `BYPASSRLS`.

```
inert — BYPASSRLS as shipped                                    4 cases
armed — control plane                                           8 cases
armed — worker plane claim binding                             16 cases
claim broker (F-1)                                             23 cases
human plane                                                    14 cases
```

Three of the sixteen record the §5a limitation rather than a protection. They
are in the harness because a gap that is only written down stops being true
without anyone noticing.

Notable results:

- `control:retarget-removed-the-acl-check` — the scheduler's cross-tenant
  `job_events` sweep now runs **without a grant on `memberships`**. That is the
  blocker `V5_WORKER_PRIVILEGE_BOUNDARY.md` §1 recorded, closed.
- `human:revoke-is-immediate` — deleting the membership row takes the person's
  access to zero in the same breath, with no reindex.
- `human:no-user-no-rows` — the plane is membership-gated, not merely
  tenant-gated. Setting a tenant without a user sees nothing.
- `claim:no-lateral-set-role` — the url fetcher cannot become the scheduler.
  **This case failed on the first run**, because the harness had logged in once
  and granted itself both worker roles; `SET ROLE` is checked against the
  *session* user's memberships, so the shortcut proved the opposite of what it
  claimed. Rewritten to use the real one-login-per-worker principals.

## Method

Throwaway PostgreSQL 17.2 cluster, port 55441, own data directory, destroyed
after. The machine's `postgresql-x64-17` service and its `akc` database were not
touched.

pgvector is not installed on this machine, so
`0024_production_hybrid_retrieval` could not run as written. A **copy** of the
migration tree outside the repository substituted `vector(1024)` with `real[]`
and omitted the `hnsw` index, exactly as
`V5_PRIVILEGE_RECEIPT_FINDINGS.md` §Method records. No repository file was
modified to run it. The substitution changes a column type and drops one index;
this document measures ownership, policies, ACLs and role attributes.
