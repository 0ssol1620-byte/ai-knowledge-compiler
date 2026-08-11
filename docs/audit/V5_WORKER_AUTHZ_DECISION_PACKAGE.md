# Worker Authorization — Decision Package

*Written 2026-08-11 at the design checkpoint the founder called; updated the same
day when the founder approved it and settled F-1 and F-2. `0034` and `0035` have
landed and both are inert — **no worker role's `BYPASSRLS` has been removed, and
two hard gates now stand between this state and the first removal.** This document
settles the design as nine decisions, says who decided each, and carries the
migration and shadow-validation plan.*

**Supersedes the judgement in `V5_WORKER_AUTHZ_ARMING.md`.** That document listed
six prerequisites and routed most of them upward. Five of the six were technical
decisions I should have made and did not. They are made here, with reasons.

**Technology intake:** this design adds no dependency. It is PostgreSQL row-level
security, SQL functions and role attributes. `docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml`
records Cedar / OpenFGA / OPA as P3 gated on measured need — **no policy engine is
adopted or proposed here**, and the register's own Security-track entry confirms no
RED or YELLOW family touches this work.

---

## 0. Decision rights, and the test used to assign them

A decision goes to the founder only when it **accepts risk, spends money, cannot be
undone, or carries legal or contractual meaning.** Everything else is engineering
and is decided below with its reasoning, which is the thing that can be argued with
later.

| # | Decision | Decided by | Status |
|---|---|---|---|
| 1 | Human Authorization Plane | implementer | **done** — landed in 0034 |
| 2 | Service / Worker Authorization Plane | implementer | **done** — landed in 0034 |
| 3 | Control-plane queue claim mechanism | founder | **decided F-1** — Option B, built in `0035`, seven proofs green |
| 4 | Tenant Data Plane access conditions | implementer | **decided** — landed, with a stated limit |
| 5 | Atomic claim ownership | implementer | **done** — the broker stamps and returns in one statement |
| 6 | Context injection points, order, fail-closed set | implementer | **decided** — modules built, claim-site wiring not (§13.7) |
| 7 | Scheduler's residual 7-table cross-tenant surface | founder (already given) | **closed** — approved, conditions met |
| 8 | Compromised-worker threat model | implementer states it; founder approves the public claim | **decided F-2** — approved wording in §8, verbatim |
| 9 | API role creation timing | implementer | **done** — created inert in 0034 |

**Two founder items, both now settled.** Item 3 was a genuine risk-acceptance
choice between two mechanisms; the founder chose the narrower one (F-1). Item 8 was
a disclosure decision — `CLAUDE.md` puts "what a public claim says, and whether
evidence supports it" outside an agent's authority — and the approved wording is in
§8 verbatim (F-2). **Nothing open needs a person.** What blocks arming now is two
engineering gates, in §10.

**Reclassified out of the founder queue**, with the reason each is engineering:

| Was | Now | Why |
|---|---|---|
| A-1 claim-site wiring | implementer | reversible code change, covered by tests — still outstanding, §13.7 |
| A-2 control-plane declarations | implementer | same |
| A-3 `akc_api_runtime` credential | **operator action**, not a decision | the decision (role exists, inert, assumed by `SET ROLE`) is made; issuing a secret is provisioning |
| A-4 column-level grant narrowing | implementer | reversible, no risk accepted — see §7 |
| A-5 event payload contract | implementer | a test, not a policy |

---

## 1. Human Authorization Plane — **done**

**Decision.** Two objects. `akc_api_runtime` authenticates; `akc_api_plane`
authorizes. Both `NOINHERIT`, both `NOBYPASSRLS`, the plane owns nothing and is a
member of nothing. The API connects as the login principal and reaches the plane
with `SET ROLE`, so `current_user` becomes the plane. **All 247
membership-referencing policies target `akc_api_plane` directly. No group is ever
targeted.**

**Basis.** Direct targeting is not a style preference. `pg_policy.polroles` does not
reach a `NOINHERIT` member of a group (`V5_WORKER_AUTHZ_SPIKE.md` D), and every
runtime login role in this repository is `NOINHERIT`. A group-targeted policy would
have compiled, deployed, and matched nobody.

The plane needs a permissive policy wherever none applies — `RESTRICTIVE` subtracts
and never grants (spike C). 36 tables in the plane's surface carried only
restrictive policies and received a tenant-scoped permissive policy. The plane is
granted only the operations its policies admit: `collection_integrity_decisions`
gets `SELECT, INSERT` and no `UPDATE`/`DELETE`, because those decisions are
immutable evidence and the alternative was inventing a policy to justify a grant.

**Migration plan.** None remaining. Landed in `0034`; `downgrade` returns all 247
policies to `PUBLIC`, drops the backfill and both roles, verified as a round trip.

**Shadow validation.** Done — 14 cases. The load-bearing ones:
`human:no-user-no-rows` (a tenant without a user sees nothing, so the plane is
membership-gated and not merely tenant-gated), `human:revoke-is-immediate`
(deleting the membership row drops access in the same breath, no reindex — the
`CLAUDE.md` runtime invariant), and three `human:no-escalation-to-*` cases.

---

## 2. Service / Worker Authorization Plane — **done**

**Decision.** Worker roles are targeted directly and individually. There is no
worker group, no shared plane role, and no policy that branches on role inside its
expression. Each worker's permissive access is tenant-scoped; its restrictive
constraints are per (table × role).

**Basis.** Same spike-D constraint. Beyond that, one policy with role branches would
make every role's blast radius the union of all of them — the property the plane
separation exists to remove. Spike B confirms the mechanism (a policy that does not
apply costs nothing, not even an ACL check on what it references) but is not a
licence to merge policies.

The permissive-coverage check written into `0034` found two roles-tables where a
worker held a grant that no permissive policy would admit — `akc_dispatch_worker`
on `collections` and `collection_events`. **Those were latent before this work.**
`BYPASSRLS` was hiding them, and arming day would have shown the collection
pipeline reading zero rows with no error.

**Migration plan.** None remaining.

**Shadow validation.** Done. The gate now asserts the invariant permanently: any
granted operation with no permissive policy behind it fails CI with the triple
named.

---

## 3. Control-plane queue claim — **decided (F-1), built**

### The problem, measured

A queue has no tenant until a row is read. `0034` gave `akc_scheduler` a bounded
cross-tenant capability on its seven tables. **It gave the other six worker roles
nothing**, and that is not an oversight to patch quietly — it is the boundary
working. Measured:

```
armed akc_url_fetcher, SELECT FROM url_fetch_tasks:
  no declaration                       0 rows
  app.control_plane = 'claim'          0 rows
  app.control_plane = 'job_discovery'  0 rows
```

The only permissive policy on `url_fetch_tasks` requires a tenant. Same for
`gpu_provider_invocations`, `analysis_tasks`, and for `akc_dispatch_worker` /
`akc_deletion_worker` reading `outbox_events`. **Arming those roles without solving
this stops the pipeline.**

### Why this is the founder's and not mine

The founder's condition on cross-tenant access was explicit: purposes limited to
*control-plane metadata* — job discovery, scheduling, claim, lease — and proof that
no tenant data-plane content is in scope. `url_fetch_tasks` carries
`canonical_url` and `encrypted_url`; `analysis_tasks` and
`gpu_provider_invocations` carry job parameters and result manifests. **These are
data-plane tables.** Admitting them wholesale is outside the standard already
approved, and `infra/postgres/control_plane_registry.py` — which I wrote — names
admitting a table a founder decision. Self-approving past my own gate would make
the gate decorative.

### The two mechanisms

**Option A — purpose-gated permissive SELECT on each queue table.**
The `0034` shape, extended: `CREATE POLICY … AS PERMISSIVE FOR SELECT TO
akc_url_fetcher USING (<purpose declared> AND <no tenant bound>)`. Cheap, uses only
vocabulary already proven, one migration.
*What it accepts:* during discovery the worker sees **whole rows for every tenant**
— URLs, parameters, manifests. A compromised worker that declares `claim` reads the
entire queue across all tenants without claiming anything.

**Option B — a claim broker function (recommended).**
A `SECURITY DEFINER` SQL function per queue that performs the claim atomically and
returns **only identifiers**: `(claim_id, tenant_id, project_id, lease_token,
lease_expires_at)`. The worker holds `EXECUTE` and no cross-tenant `SELECT` at all.
It then calls `enter_claim_context()` with what it got and re-reads the row under
ordinary tenant + claim scope.
*What it accepts:* a `SECURITY DEFINER` surface, which is a privilege-escalation
shape by construction. Mitigated by `SET search_path = pg_catalog, public`, a fixed
`LANGUAGE sql` body with no dynamic SQL, no arguments that reach a table name, and
ownership by a non-login role. **There is precedent in this repository**:
`akc_is_current_project_creator` (0015) is `SECURITY DEFINER`, owned by
`akc_dispatch_worker`, with `EXECUTE` to `PUBLIC`.
*What it buys:* cross-tenant exposure shrinks from whole data-plane rows to five
identifiers, which is control-plane metadata by the founder's own definition — so
Option B arguably lands **inside** the standard already approved rather than
extending it. It also makes the claim atomic and ownership provable in one step
(§5).

### Decision — F-1, founder, 2026-08-11: **Option B**

The exposure difference is the whole argument: Option A lets a compromised worker
read every tenant's queue contents by declaring a purpose it was going to declare
anyway; Option B lets it learn that a job exists and obtain a lease for one.

`V5_WORKER_AUTHZ_SPIKE.md` recorded that a definer-function layer was "not forced"
as a general architecture. That finding stands — this is not a general layer, it is
one function per queue doing one thing.

**Built in `0035_claim_broker`, and no longer a design.** Two brokers exist —
`akc_claim_url_fetch_task` and `akc_claim_gpu_invocation` — owned by
`akc_claim_broker`, a `NOLOGIN NOINHERIT NOBYPASSRLS` role that reaches the queues
through purpose-gated permissive policies of its own. The workers hold `EXECUTE`
and no cross-tenant read at all.

`analysis_tasks` and `deletion_requests` deliberately have no broker: nothing
polls them cross-tenant. `akc_dispatch_worker` and `akc_deletion_worker` remain
unbrokered because they poll `outbox_events`, which carries no lease to bind and
whose control-plane policies name `akc_scheduler` alone — admitting two more roles
there is a separate decision. All four facts are recorded in
`control_plane_registry.py` and asserted against the catalog by CI, so the
uncovered paths cannot be forgotten on arming day.

### Migration plan — landed

| Revision | Contents | Downgrade |
|---|---|---|
| `0035_claim_broker` | `akc_claim_broker` role; purpose-gated permissive policies for it on the two queues and on `audit_events`; one `SECURITY DEFINER` claim function and one depth probe per queue, `EXECUTE` revoked from `PUBLIC` and granted to that queue's worker role only | drops the four functions, the five policies and the role; round-tripped |

Additive and inert: nothing calls the functions while the workers' existing claim
paths run.

### What the design gives up, stated

The lease is now the only thing excluding a second claimer. The ORM predicate it
replaces treats a `queued` row as claimable *regardless of its lease*, which is
safe there because the caller immediately takes an advisory lock and holds the
row's transaction open. The broker stamps and returns in one statement and has
neither, so that disjunct is dropped and the broker's predicate is **stricter**
than the one it replaces. **This was found by the concurrency proof, not by
reading**: with the disjunct present, four concurrent callers were granted 16
claims over 12 rows.

### Shadow validation — all green

| Case | Result |
|---|---|
| `broker:claims-one-row-atomically` | 4 concurrent callers x 4 attempts granted **10 claims over 10 distinct rows**, 0 left claimable — no row handed to two callers, none lost |
| `broker:returned-token-is-the-row-token` | every returned token is the token now on its row; the claim and its receipt cannot diverge |
| `broker:returns-identifiers-only` | the result is exactly the five columns |
| `broker:no-cross-tenant-select-remains-{undeclared,declared}` | holding `EXECUTE`, a direct `SELECT` still reads nothing — the worker gained a claim path, not a read path |
| `broker:stamps-a-lease-the-caller-can-bind` | binding the returned identifiers makes exactly the claimed row visible |
| `broker:a-forged-token-still-binds-nothing` | the claim id alone does not satisfy the binding |
| `broker:refuses-an-undeclared-purpose-{undeclared,unapproved}`, `broker:refuses-when-a-tenant-is-bound` | three refusals |
| `broker:cannot-{replace,own,drop,unpin,become}` | the caller cannot redefine, take, drop, unpin or become the thing that grants it access |
| `broker:cannot-execute-another-queues-broker` | holding one queue's broker grants nothing on another's |
| `broker:execute-is-not-public` | a role outside the grant is refused — PostgreSQL grants `EXECUTE` to `PUBLIC` by default and this proves the revoke held |
| `broker:search-path-is-pinned` | `pg_proc.proconfig` reads `search_path=pg_catalog, public` |
| `broker:definer-owner-is-not-privileged` | the owner holds neither `BYPASSRLS` nor `LOGIN` |
| `broker:lease-is-clamped` | a 100,000,000-second request came back as 1:00:00 |
| `broker:every-grant-is-audited` | 10 audit rows for 10 grants, naming the session principal |
| `broker:depth-probe-{sees-what-the-worker-cannot,is-purpose-gated-too}` | depth 3 against a worker read of 0, and 0 once a tenant is bound |

**Three of these passed vacuously on the first run** — the clamp and both depth
cases ran against a queue the concurrency proof had just drained, so they measured
nothing and said so. They now seed their own rows.

---

## 4. Tenant Data Plane — **decided (implementer)**

**Decision.** A worker reaches tenant data under two conditions, both required:

1. `app.tenant_id` matches the row's tenant — the existing `*_tenant_isolation`
   permissive policies, untouched by `0034`;
2. on the four lease-bearing tables, the `_claim_binding` restrictive policy also
   holds: the row is the claimed row, the lease token matches, the lease has not
   expired, and the project agrees.

**The limit, stated rather than glossed: claim binding covers the four lease tables
and nothing else.** An armed worker holding a valid claim for one job in tenant A
can read *all* of tenant A's `documents`, `pages` and `blocks` — not only the ones
belonging to its job.

**Why I am not extending it.** Job-scoping every data-plane table means a
correlated subquery from each table back to its job on paths that run per page.
The risk it removes is a worker legitimately inside tenant A seeing more of tenant
A; the boundary that matters — tenant A to tenant B — is already held by the
tenant-isolation policies. That is a bad trade of hot-path cost against a small
reduction, and it is a technical judgement, not a risk to hand upward. It is
recorded in §8 as a non-claim so nobody infers job-level isolation from the phrase
"claim binding".

**Migration plan.** None. Landed in `0034`.

**Shadow validation.** Done — 16 worker-plane cases, including forged tenant,
forged project, forged claim, reused lease, expired lease, missing lease, missing
claim, and three other-queue denials. One case should be **added** when §3 is
built, to keep the limit honest rather than merely written down:

| Case | Proves |
|---|---|
| `claim:tenant-scope-is-the-worker-boundary` | a worker bound to job X in tenant A **can** read tenant A's other documents — asserted as the documented limit, so a future change that tightens or loosens it is visible |

---

## 5. Atomic claim ownership — **decided (implementer)**

**Decision.** **The lease token is the ownership proof.** It is an unguessable
UUID, written by the claim, and carried in a transaction-local GUC. Possession of
the token plus row identity plus a live expiry is what the `_claim_binding` policy
checks, and that is the complete database-side control.

Atomicity comes from the claim broker of §3: `UPDATE … SET lease_token =
gen_random_uuid(), lease_expires_at = now() + <lease>` over a `SELECT … FOR UPDATE
SKIP LOCKED` subquery, in one statement, returning the identifiers. One statement,
one row, no window between selecting and stamping.

**No `claimed_by` column will be added.** `url_fetch_tasks` has none today
(confirmed against the catalog this session; the other three lease tables must be
confirmed at implementation time). Adding one across four tables would duplicate
what the token already proves, and would introduce a second ownership record that
can disagree with the first.

**The consequence, stated precisely.** `WorkerClaim.claimed_by` and
`WorkerClaimOwnerMismatch` in `akc_security.tenant_context` are an
**application-level** assertion — the caller supplies the identity it believes it
has, and the module refuses a mismatch. **There is no database column behind it.**
At the database, "another worker's live lease" and "a reused lease" are the same
failure and both are blocked by the token comparison. The application check is
defence in depth against a caller confusing its own state, not against a hostile
one. Anyone reading `claimed_by` as a database-enforced control is reading it
wrong.

**Migration plan.** Folded into `0035_claim_broker` (§3). No schema change.

**Shadow validation.** `broker:claims-one-row-atomically` and
`broker:stamps-a-lease-the-caller-can-bind` above. Already proven for the checking
half: `claim:reused-lease`, `claim:expired-lease`, `claim:missing-lease` all yield
zero rows, and the application-level refusals have 27 unit tests in
`packages/security/tests/test_claim_context.py`.

---

## 6. Context injection — points, order, fail-closed set — **decided (implementer)**

**Decision — the order is fixed and it is the only correct one.**

*A claim transaction:*

1. `enter_control_plane_context(purpose="claim")` — **before** the poll.
2. Claim (the broker of §3) → identifiers.
3. `enter_claim_context(claim=…, worker_id=…, now=…)` — sets `app.tenant_id`,
   `app.project_id`, `app.claim_id`, `app.lease_token`, and **clears
   `app.control_plane`**.
4. All further reads and writes.

*A cross-tenant batch (retention sweep, outbox fan-out, delivery claim):* step 1
only, with its own purpose. Never `enter_claim_context` — no single tenant is
correct for it.

**The ordering constraint that is easy to get wrong.** The `_claim_binding` policy
compares the row's `lease_token` to `app.lease_token`, and the claiming transaction
*writes* a new token. The worker must therefore declare **the lease it is taking**,
before the write — not the lease it found. With the broker of §3 this is automatic,
because the broker returns the token it just stamped. Without the broker it is a
trap, which is a further argument for Option B.

**Fail-closed set — implemented and tested.** `enter_claim_context` writes nothing
unless all of: `worker_id` non-empty; `claim_id`, `tenant_id`, `lease_token` present
and well formed; `claimed_by` non-empty and equal to `worker_id`; `lease_expires_at`
timezone-aware and strictly greater than `now` (**the boundary is closed** — a lease
expiring exactly now is not held); every supplied `expected_*` equal to the claim,
where an assertion naming a project the claim does not have is a mismatch and not a
pass. A partial binding is never left behind: a tenant set with no claim reads as
ordinary tenant-scoped access, which is worse than refusing.

`enter_control_plane_context` refuses a purpose outside the closed set of five, and
refuses when a tenant is already bound — a transaction doing one tenant's work
cannot reopen the cross-tenant view.

**Injection sites, final list.** Four claim sites — `services/url-fetcher/.../worker.py`
`_claim`, `services/scheduler/.../gpu_jobs.py` `_claim`,
`services/api/.../deletions.py` `_claim_deletion_request`, the analysis task claim.
Five scan sites — `scheduler.py` `publish_outbox_batch`, `_dispatch_on_connection`,
`_deliver_locked`, `cleanup_retained_rows`; `deletions.py`
`_run_retention_sweep_unlocked`.

**Migration plan.** None — this is application code, delivered as two pull requests
(scan declarations first, they are independent of §3; claim bindings second, they
depend on `0035`). Reversible by revert.

**Shadow validation.** The GUC contract is already proven at the policy level.
What the wiring needs is a **test that fails when a site is added without a
binding**, in the shape of the existing
`test_every_sessionmaker_site_in_the_deletion_module_binds_a_tenant`: enumerate the
claim and scan sites by AST and assert each is preceded by the corresponding call.
That test is the deliverable, not a shadow case.

---

## 7. The scheduler's residual 7-table surface — **closed**

**Decision (founder, already given; conditions met).** `akc_scheduler` keeps
cross-tenant access to exactly seven tables — `outbox_events`,
`webhook_deliveries`, `webhook_endpoints`, `job_events`, `idempotency_records`,
`email_verification_tokens`, `email_verification_deliveries` — gated on a declared
purpose from a closed set of five and on no tenant being bound.

**Why it is acceptable, and where it is not clean.** The seven were re-derived from
the live ACL, not taken from the design. Every column of all seven was read: no
document body, no compiled knowledge, no evidence payload. Three column families
are customer-controlled or secret and are named rather than glossed —
`webhook_endpoints.encrypted_secret`/`.url`, `idempotency_records.response_body`
(never written on the current path; `idempotency.py:266-267` stores only
ciphertext), and the `email_verification_*` encrypted payload, pseudonym and token
digest. Full reasoning in `V5_CONTROL_PLANE_BOUNDARY.md` §3.

**A-4, decided: narrow the grants to columns, and do it before the scheduler is
disarmed.** This was previously routed to the founder and should not have been. It
accepts no risk — it removes some — costs nothing, and is reversible with a
`GRANT`. It is blocked only on changing what the scheduler selects, because the
retention and fan-out paths select whole ORM entities.

**A-5, decided: build the payload contract.** `outbox_events.payload` and
`job_events.payload` are unconstrained `json`. All 53 construction sites were
enumerated: 49 build dict literals whose 48 distinct keys are identifiers, hashes,
counts, statuses and codes, with no `text`/`content`/`body`/`title` key; 4 are
non-literal and three of those bind a local identifier dict a few lines above. That
is a **code reading, not a guarantee** — nothing structurally prevents a future site
from writing document content into an event. A schema check at emit time turns it
into one. This is a test, not a policy, and it is mine to decide.

### Migration plan

| Revision | Contents | Downgrade |
|---|---|---|
| *(PR, no migration)* | scheduler selects narrowed to the columns it uses; payload emit contract | revert |
| `0036_control_plane_column_grants` | `REVOKE SELECT ON <table>` then `GRANT SELECT (cols)` for the seven; excludes the three sensitive families where the scheduler does not need them | re-`GRANT SELECT` at table level |

### Shadow-validation plan

| Case | Proves |
|---|---|
| `control:column-narrowed-select-denied` | `SELECT encrypted_secret FROM webhook_endpoints` raises for `akc_scheduler` while the fan-out query still succeeds |
| `control:retention-still-sweeps` | each of the four retention sweeps returns the same row count before and after narrowing |
| plus the 8 control-plane cases already passing | unchanged behaviour on the purpose gate |

---

## 8. Compromised-worker threat model — **statement is mine; the public claim is the founder's**

### What is blocked — all measured, all currently passing

| | |
|---|---|
| Reach a tenant it never claimed (forged tenant, project or claim id) | blocked |
| Reuse another job's live lease | blocked |
| Act on an expired lease | blocked |
| Act with no claim bound | blocked |
| Read another worker's queue | blocked — no grant |
| Read tenant data as the scheduler | blocked — no grant |
| Escalate laterally to another worker role | blocked — one login principal per worker role |
| Reopen the cross-tenant view after binding a tenant | blocked — policy and module both |
| Drop or retarget the policy binding it | blocked — not the owner |
| Human plane: see anything without a membership row | blocked |

### What is **not** blocked — say this exactly

1. **A compromised worker can claim a new job, and that job may belong to another
   tenant.** One worker class serves every tenant. No row policy changes that, and
   the claim broker of §3 does not either — a legitimate claim is what it is for.
2. **Over time, a compromised worker that keeps claiming accumulates access to many
   tenants, one job at a time.** The rate is bounded by the queue, not by
   authorization.
3. **Within a tenant it holds a claim for, a worker sees that tenant's whole data
   plane** — not only its job's rows. §4 records why, and that it is deliberate.
4. **Nothing here is an exfiltration control.** These are read-authorization
   boundaries. A worker legitimately processing a document can copy it.

### F-2 — approved public wording, founder, 2026-08-11

**This is the approved claim, verbatim. It is the whole of what may be said.**

> Workers do not receive blanket cross-tenant data access. A worker must obtain a
> valid job claim before entering a tenant data plane, and forged tenant, project,
> claim, or lease context is rejected. Worker pools may legitimately process jobs
> from multiple tenants over time.

**Forbidden, in any document, comment, commit message or external copy:**

- "A fully compromised worker cannot reach another tenant." — false; see items 1
  and 2 above.
- "job-isolated" — the data-plane boundary is tenant isolation, not job-row
  isolation. §4 records why.
- "only the rows belonging to its job" — same reason. True of the four
  lease-bearing tables, false of `documents`, `pages` and `blocks`.

The three forbidden phrases are not stylistic preferences. Each of them asserts a
property this system does not have, and each is a plausible thing to write after
reading the words "claim binding" without reading §4.

### Migration and shadow-validation plan

No migration. The threat model is maintained **as executable cases**, not prose: the
"not blocked" list gets its own harness section asserting the behaviour is present,
so that if a future change accidentally blocks item 3, the document is corrected
rather than silently becoming pessimistic.

| Case | Proves |
|---|---|
| `residual:worker-may-claim-a-second-tenant` | after releasing tenant A's claim, the same role successfully claims tenant B's job — the documented residual, asserted rather than assumed |
| `residual:tenant-scope-not-job-scope` | duplicate of §4's case; kept in the threat-model section so the limit is discoverable from either direction |

---

## 9. API role creation timing — **done**

**Decision.** The role pair was created in `0034`, **inert**: `NOLOGIN`, no
password, no application wired to it. Creation was deliberately not deferred to the
API work, because the human plane is what 247 policies now target — a plane that
does not exist would have made those policies match nobody, which is precisely the
spike-D failure in a different disguise.

**Gated on, to become live:**

1. `GRANT LOGIN` with a real credential — **an operator action, not a decision.** A
   migration must not mint credentials, which is why it was created without one.
2. The API connecting as `akc_api_runtime` and issuing `SET ROLE akc_api_plane`
   after connect and before any query, with `app.user_id` and `app.tenant_id` set
   per request as they already are.
3. Nothing else. It does not wait on arming, on §3, or on the founder.

**Why `NOINHERIT` matters here and is not a detail.** If the login principal
inherited the plane, it would hold the plane's rights without asking, and the two
objects would be one object with two names. `SET ROLE` is the separation.

**Migration plan.** None. The gate asserts the shape permanently: both roles exist,
neither is `SUPERUSER`/`BYPASSRLS`/`CREATEROLE`/`CREATEDB`, neither inherits, the
login principal can assume the plane, and the plane is a member of nothing.

**Shadow validation.** Done — `human:role-separation` proves
`session_user = akc_api_runtime`, `current_user = akc_api_plane`. The harness sets a
throwaway password for one run and removes it, which is how the chain is proven
without leaving a credential behind.

---

## 10. Consolidated migration sequence

Nothing below is started. Each disarm step is one `ALTER ROLE`, so each rollback is
one `ALTER ROLE`.

| Order | Revision / PR | Contents | Gated on | Status |
|---|---|---|---|---|
| 1 | `0035_claim_broker` | two `SECURITY DEFINER` claim functions and two depth probes, `EXECUTE` per role, broker role and its policies | founder F-1 | **done** |
| 2 | PR | `claim_via_broker` + `ClaimStarvationDetector` in `akc_security` | 0035 | **done** |
| 3 | PR | `enter_control_plane_context` at the five scan sites; AST test | — | not started |
| 4 | PR | url fetcher and GPU claim sites call the broker; AST test | 0035 | **not started — see §13.7** |
| 5 | PR | zero-row starvation metric wired into each poll loop | 2, 4 | not started |
| 6 | PR | scheduler selects narrowed; payload emit contract | — | not started |
| 7 | `0036_control_plane_column_grants` | scheduler grants narrowed to columns | 6 | not started |
| — | **GATE 1** | zero-row starvation detection live in staging: backlog, claimable depth, successful claims and consecutive zero polls all observable, and an alert that fires on starvation and never on an idle queue | 2, 5 | **blocking** |
| — | **GATE 2** | CI green on `pgvector/pgvector:pg17` with the **unmodified** migration tree: `alembic upgrade head` → privilege receipt → comparison → shadow validation | wired in `ci.yml` | **blocking** |
| 8 | `0037_disarm_payment_worker` | `NOBYPASSRLS` — no service exists; the free rehearsal | Gates 1, 2 | not started |
| 9 | `0038_disarm_scheduler` | `NOBYPASSRLS` | 3, 7 | not started |
| 10 | `0039_disarm_url_fetcher` | `NOBYPASSRLS` | 4, 5 | not started |
| 11 | `0040_disarm_gpu_worker` | `NOBYPASSRLS` | 4, 5 | not started |
| 12 | `0041_disarm_analysis_worker` | `NOBYPASSRLS` | 4, 5 | not started |
| 13 | `0042_disarm_dispatch_worker` | `NOBYPASSRLS` | 4, 5, and a decision on `outbox_events` | not started |
| 14 | `0043_disarm_deletion_worker` | `NOBYPASSRLS` | same, plus irreversible purges — last | not started |

**Both gates are hard preconditions on step 8, not advisory.**

**Gate 1 — zero-row starvation detection.** An armed worker that cannot see its
queue raises nothing; it reads zero rows, which is what an idle queue also reads.
The detector compares *claimable depth* — from the broker's `…_depth` probe, which
is subject to the same purpose gate and returns a count and no rows — against this
worker's *consecutive empty polls*, and classifies: `HEALTHY` (claimed something),
`IDLE` (no backlog, never alerts), `CONTENDED` (backlog, lost a race, below
threshold), `STARVED` (backlog and a run of empty polls — the only state that
pages). `broker:depth-probe-sees-what-the-worker-cannot` proves the signature
exists at the database: depth 3 while the worker's own read sees 0. The logic and
its negative test are built; **wiring it into the poll loops is step 5 and is not
done**, so Gate 1 is not green.

**Gate 2 — unmodified pgvector reproduction.** Every measurement in this package
was taken on a throwaway cluster where `0024` had to be rewritten *outside the
repository* to substitute `vector(1024)` with `real[]`, because pgvector is not
installed on the machine. The substitution cannot affect ownership, policies, ACLs
or role attributes — but "cannot affect" is an argument, not a measurement. The CI
`postgres-gate` job runs the unmodified tree against `pgvector/pgvector:pg17` and
now carries the shadow validation as its last step; it is labelled as Gate 2 in
`ci.yml` so the reason survives the next person to edit it.

**Canary between each disarm.** Flip in staging, run that role's real workload, hold
one full retention cycle. Watch two signatures, which are different faults:
`permission denied for table X` is a schema problem the `0034` retarget was meant to
have eliminated; **zero rows where rows were expected** is the dangerous one,
because nothing raises. A claim loop finding no work is indistinguishable from an
idle queue, so **the zero-rows metric must exist before step 6**.

**Definition of done.** `worker roles are NOBYPASSRLS` leaves the gate's
`PENDING_INVARIANTS` list and becomes an assertion; `_report_bypassrls` becomes
`_verify_bypassrls_absent`. Until then CI prints `7/7 (not yet removed)` on every
run, which is the right amount of noise for an unfinished control.

---

## 11. Consolidated shadow-validation plan

The harness (`infra/postgres/shadow_validate_dual_plane.py`) runs three passes and
must keep doing so: **inert** as the real roles with `BYPASSRLS` as shipped;
**armed** with the attribute removed *in a throwaway cluster only*, restored at the
end and asserted restored; **human plane**, which needs no shadow.

| Section | Now | After §7 |
|---|---:|---:|
| inert | 4 | 4 |
| control plane | 8 | 10 |
| worker plane / claim | 16 | 16 |
| **claim broker (F-1)** | **23** | 23 |
| human plane | 14 | 14 |
| residual (threat model) | 0 | 2 |
| **total** | **65** | **69** |

**A rule this harness earned the hard way.** `claim:no-lateral-set-role` failed on
its first run because the harness logged in once and granted itself both worker
roles; `SET ROLE` is checked against the *session* user's memberships, so the
shortcut proved the opposite of what it claimed. Every future case involving role
identity uses the real one-login-per-worker principals.

---

## 12. Founder decisions — both settled

**F-1, 2026-08-11 — the queue claim mechanism: Option B.** The claim broker.
Workers receive no cross-tenant queue `SELECT`. The return surface is fixed at
five identifiers and enforced in three places: the migration emits it, the schema
security gate reads it back from `pg_proc` and fails if it grew, and
`claim_via_broker` refuses a result set that is not exactly those five columns at
run time. Built in `0035`, twenty-three shadow cases green.

**F-2, 2026-08-11 — the public isolation claim.** The approved wording is in §8,
verbatim, together with the three forbidden phrases. Nothing in this repository
may say more than the approved paragraph.

### Open founder items

**None.** The remaining work is engineering and operations.

**Not founder decisions, for the record:** claim-site wiring, control-plane
declarations, column-grant narrowing, the payload contract, the `claimed_by`
decision, the injection order, the starvation threshold, and the disarm ordering.
Those are engineering, they are decided above, and the reasoning is written down
so it can be argued with.

**An operator action, not a decision:** issuing the `akc_api_runtime` credential.

**A decision that will arrive later:** admitting `akc_dispatch_worker` and
`akc_deletion_worker` to the `outbox_events` control-plane boundary, which steps
13 and 14 need and which nothing else does. It is the same shape as F-1 and
carries the same conditions. It is recorded in `control_plane_registry.py` under
`UNBROKERED_CROSS_TENANT_CLAIMS` so it cannot be skipped by whoever reaches those
steps first.

---

## 13. What remains uncertain

Stated as uncertainty rather than smoothed into the plan.

1. **~~The claim broker is a design, not a measurement.~~** Settled. Built in
   `0035` and proven by twenty-three cases, including the concurrency one — which
   **failed on its first run and found a real defect**: the predicate inherited
   from the ORM kept a `queued` row claimable after its lease was stamped, so four
   concurrent callers were granted 16 claims over 12 rows. The broker's predicate
   is now stricter than the one it replaces, and §3 says why.
2. **~~Three of the four lease tables have not had their columns confirmed.~~**
   Settled 2026-08-12. All four were checked, and **none** of `analysis_tasks`,
   `deletion_requests`, `gpu_provider_invocations` or `url_fetch_tasks` carries
   `claimed_by`, `worker_id`, `claimed_at`, `owner_id` or `locked_by`. **The lease
   token is the sole ownership record on every lease-bearing table**, so §5's
   conclusion now rests on measurement rather than on one sample. Lower stakes
   again for the two brokered queues: the broker hands the lease to exactly one
   caller, so ownership there is not a comparison at all.
3. **~~The starvation detector is built but not wired.~~** Wired 2026-08-12
   into `GpuInvocationWorker.run_one` → `_observe_poll` → `claim_backlog` →
   `ClaimStarvationDetector` → `record_claim_poll`, publishing five series plus
   `akc_claim_poll_starved`. `0036_claim_backlog_probe` added the second count the
   discrimination needs. **Gate 1 is now split** — see §10: **1A (detector
   correctness and discrimination) is GREEN**; **1B (real workload observation)
   is PENDING** and is required before production activation, not before staging.
4. **~~Nothing has run against pgvector.~~** **Gate 2 is GREEN**, CI run
   `31517256771`, job `postgres-rls-and-role-boundaries`, on
   `pgvector/pgvector:pg17@sha256:d2ef61f4…`: the unmodified migration tree
   applied to head, the receipt was generated, the committed receipt matched the
   catalog CI built independently, and the shadow suite passed. `0035` and `0036`
   apply unmodified on real pgvector. The paragraph that stood here is kept below
   because the reasoning it records is still the reason the gate existed.

   *Superseded:* **Nothing has run against pgvector.** Every measurement here comes from a
   throwaway cluster where `0024` was rewritten outside the repository to substitute
   `vector(1024)` with `real[]` and omit the `hnsw` index, per the precedent in
   `V5_PRIVILEGE_RECEIPT_FINDINGS.md`. The substitution cannot affect ownership,
   policies, ACLs or role attributes — but that is an argument, not a measurement.
   **Gate 2 is therefore not green.** The CI job is wired and labelled; this
   session could not run it.
5. **The payload finding is a code reading with a known blind spot.** Four
   construction sites are non-literal and two of those are pass-throughs whose
   content is decided by callers. "No site writes document content into an event"
   is true today and is not enforced.
6. **Arming has never been rehearsed end to end.** The shadow harness removes
   `BYPASSRLS` from two roles for the length of one run in a disposable cluster. It
   has never been removed from a role serving real traffic, and the canary procedure
   in §10 is written, not exercised.
7. **The claim sites do not call the broker.** The one deliverable of this pass
   that was not completed, and the reason is specific rather than time. The broker
   returns five identifiers; the url fetcher's `_claim` works from a fully
   populated ORM row and, in the same transaction, checks the document and project
   for `deletion_requested_at`, takes an advisory lock, increments `attempt_count`,
   moves the task to `running` and the document to `URL_FETCHING`, and can exit
   through a cancellation path that dead-letters without claiming. Rewiring means
   re-deriving all of that on the far side of the broker call — a restructure of a
   path with cancellation semantics, in the same family of code where an earlier
   commit in this repository claimed coverage it did not have. It is arming work,
   not inert work, and it is step 4 of §10.

---

## Provenance

Every number in this document was measured on a throwaway PostgreSQL 17.2 cluster
(port 55441, own data directory, destroyed after; the machine's
`postgresql-x64-17` service and its `akc` database untouched).

- Receipt at `0035`: `docs/audit/receipts/privilege-receipt-0035.json`,
  `receipt_sha256`
  `92feefed7344e203e7bc11272d3f1303c7fb04de54e0ffebbb0bc109507d0de6`. This is the
  baseline CI compares against.
- Receipt at `0034`: `docs/audit/receipts/privilege-receipt-0034.json`,
  `receipt_sha256`
  `c1cfc06dc7c05b9d37ca0311c4d071a5dc8b98a593c99bbbe55eae4b58927545`. Kept as the
  measurement it was.
- The 0033 receipt `docs/audit/receipts/privilege-receipt.json`
  (`eeb750ad…`) is unchanged and remains what other documents cite.
- Detail: `V5_CONTROL_PLANE_BOUNDARY.md` (boundary, column examination, threat
  model), `V5_WORKER_AUTHZ_SPIKE.md` (the three PostgreSQL facts the design rests
  on), `V5_WORKER_PRIVILEGE_BOUNDARY.md` (why arming was blocked before `0034`).
