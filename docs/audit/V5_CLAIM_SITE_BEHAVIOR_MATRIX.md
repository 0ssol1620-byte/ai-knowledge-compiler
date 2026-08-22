# Claim-site behaviour matrix — BEFORE / AFTER

*Started 2026-08-12 as a pre-wiring matrix; reconciled the same day against the
code that now exists. The matrix below is still the specification — what changed
is that the AFTER path it specifies has been written and proved.*

## 0. Current state

| | |
|---|---|
| GPU equivalence (comparative · invariant · shared-body + reachability) | **GREEN** |
| `_claim_via_broker` | **IMPLEMENTED** — `gpu_jobs.py`, reusing `_claim_from_row` |
| Written-AFTER integration proof | **GREEN** — 21 cases, `infra/postgres/verify_claim_via_broker.py` |
| Canary A, broker path with `BYPASSRLS` **ON** | **GREEN** |
| `GpuWorkerPolicy.use_claim_broker` | **default `false`** — the shipped path is still the ORM claim |
| Worker roles disarmed | **none. `BYPASSRLS` is 7/7** |
| Canary B, GPU worker at `NOBYPASSRLS` | **NOT STARTED** — no disarm migration exists |
| Gate 1B, real workload observation | **PENDING** |

`analysis_tasks` remains out of scope for the broker contract: it claims an
`(outbox_event, analysis_task)` pair and locks the *event*, so one `claim_id`
from one table describes half of it (§4, §5.3). It is last in the disarm order
and blocks nothing.

### Superseded — the outcome as it stood before wiring

> **Outcome: wiring is not started.** Two findings gate it, and only one is a
> true stop: §5.1, the clock divergence, which I first wrote up as a founder
> decision and then corrected — it is a test seam, not a production behaviour;
> and §5.3, `analysis_tasks`, a real stop. No site has been wired. The canary is
> chosen and its matrix is complete; the equivalence tests §5.1 describes are not
> written.

Both have since been answered: the equivalence evidence is green in three
categories (§5a) and the GPU canary is wired behind an off-by-default flag.
§5.3 stands unchanged.

---

## 1. The four sites, measured rather than judged

Directive 2 says to measure, not to guess, and specifically not to start with the
url fetcher because I had already analysed it. The measurement is AST-derived
from the claim function itself: lines, exit paths, branch nodes, attribute writes
(state transitions), whether an advisory lock is taken, `commit()` calls, terminal
or dead-letter branches, and how many other entities the claim transaction reads.

```
complexity  site                              lines exits branch writes lock  commits terminal other entities
      19.7  deletion_requests                    47     3      5      7  no          0        0  -
      34.3  gpu_provider_invocations            133     2      8      7  no          1        2  -
      61.5  url_fetch_tasks                     115     5      6     10  yes         5        5  Document, Project
      80.9  analysis_tasks                      159     7      9     15  yes         7        6  Document, Project
```

`complexity = lines/10 + exits + branches + writes + 8·lock + 2·commits + terminal + 3·entities`.
The weights are mine and are arguable; the ordering is not sensitive to them —
`deletion_requests` and `gpu_provider_invocations` take no advisory lock, touch no
other entity, and have no multi-commit choreography, while the other two do all
three.

**The measurement disagreed with my familiarity.** `url_fetch_tasks` — the site I
had already read and would have reached for — is third of four.

### The simplest site is disqualified, and not by complexity

`deletion_requests` scores lowest and **cannot be the canary**, because it is not a
queue poll at all:

```python
async def _claim_request(sessions, *, request_id: uuid.UUID, lease_seconds, now):
    statement = select(DeletionRequest).where(DeletionRequest.id == request_id)
```

It claims **by primary key**. The tenant is already known — an outbox event named
it — so there is no cross-tenant discovery to broker and `0035` correctly gives it
no broker. Wiring it would be wiring nothing.

### Canary: `gpu_provider_invocations`

The simplest site that actually polls cross-tenant. It is the only remaining
choice below the advisory-lock tier, and `akc_claim_gpu_invocation` already exists.

### `claimed_by`, checked on all four (directive 2)

None of the four lease-bearing tables has any ownership column — no `claimed_by`,
`worker_id`, `claimed_at`, `owner_id` or `locked_by`:

```
analysis_tasks             21 cols | ownership cols: NONE
gpu_provider_invocations   50 cols | ownership cols: NONE
deletion_requests          18 cols | ownership cols: NONE
url_fetch_tasks            24 cols | ownership cols: NONE
```

This generalises what was previously verified only for `url_fetch_tasks`. **The
lease token is the sole ownership record on every lease-bearing table**, which is
what the decision package §5 already concluded and now rests on measurement rather
than one sample.

---

## 2. `gpu_provider_invocations` — the canary, in full

### BEFORE (`services/scheduler/src/akc_scheduler/gpu_jobs.py:874`)

| Dimension | Behaviour |
|---|---|
| **Claim eligibility** | `status IN _ACTIVE_STATES` (7 states) AND `available_at <= now` AND (`lease_expires_at IS NULL` OR `<= now`); ordered `available_at, created_at, id`, `LIMIT 1` |
| **Lock semantics** | `with_for_update(skip_locked=True)` on the selected row, held for the whole session transaction |
| **Cancellation behaviour** | `_fence_reason()` may set `cancellation_reason` and force `status='cancel_requested'`; the cancel branch either goes local-terminal (no `provider_job_id`), dead-letters on `cancel_attempt_count >= max`, or moves to `cancelling` and increments `cancel_attempt_count` |
| **Attempt increment** | `attempt_count += 1` **only** on the submit branch; `cancel_attempt_count += 1` on the two cancel branches |
| **Lease stamping** | `lease_token = uuid4()`, `lease_expires_at = now + policy.lease_seconds`, `updated_at = now` — written *after* the fence check, *before* the action branch |
| **Task/document state transition** | `status` → one of `cancel_requested`, `cancelling`, `running`, `submitting`, or a terminal set by `_terminal_local`; `started_at` set on first submit; `last_error_code` cleared on submit. No document row is touched |
| **Dead-letter behaviour** | Two paths, both via `_terminal_local`: cancel unconfirmed (`GPU_PROVIDER_CANCEL_UNCONFIRMED`) and attempts exhausted (`GPU_PROVIDER_ATTEMPTS_EXHAUSTED`) |
| **Transaction boundary** | One session, one `commit()` at the end; on the submit branch it also inserts a `GpuProviderAttempt` and appends a `gpu.invocation.submitting.v1` event inside the same transaction |
| **Return** | `_Claim` with **20 fields**, including `input_object_key`, `input_sha256`, `options`, `model_revision`, `runtime_image_digest`, `adapter_version`, `provider_job_id`, and the decided `action` |

### AFTER — implemented as `GpuInvocationWorker._claim_via_broker`

| Dimension | Behaviour |
|---|---|
| **Broker atomic claim** | `akc_claim_gpu_invocation(lease_seconds)` — one statement: `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING`. Lock semantics preserved: the function runs inside the caller's transaction, so the row lock is held to the same boundary |
| **Five identifiers** | `claim_id, tenant_id, project_id, lease_token, lease_expires_at` |
| **`enter_claim_context`** | binds tenant, project, claim and lease; clears `app.control_plane` |
| **Tenant-scoped reread** | `SELECT … FROM gpu_provider_invocations WHERE id = :claim_id` — now constrained by `gpu_provider_invocations_claim_binding` to exactly that row |
| **Remaining state transitions** | the fence check, the five-way action branch, `attempt_count`/`cancel_attempt_count`, `GpuProviderAttempt` insert, event append and `_terminal_local` all run unchanged on the reread row |

### Equivalence risks specific to this site

1. **Double lease stamp.** BEFORE writes the token at line 904-906. AFTER, the
   broker has already written one. The site must **not** re-stamp: the claim
   binding compares `lease_token = app.lease_token`, so writing a second token
   would make the row invisible to its own transaction mid-flight. The lines that
   stamp the lease are deleted, not moved.
2. **Fence ordering.** BEFORE stamps the lease after `_fence_reason`; AFTER
   stamps before. `_fence_reason` reads job/invocation state and writes only
   `cancellation_reason`/`status`, neither of which the lease predicate consults —
   so the reorder is inert. This is the one reorder in the site and it is
   accounted for.
3. **`updated_at`.** BEFORE sets it in the same assignment block as the lease.
   The broker does not — its `UPDATE` touches only `lease_token` and
   `lease_expires_at` (that is the whole of its column grant). AFTER must set
   `updated_at` on the reread row, or the row's modification time silently stops
   tracking claims.

---

## 3. `url_fetch_tasks` (`services/url-fetcher/.../worker.py:285`)

| Dimension | BEFORE |
|---|---|
| Claim eligibility | `status IN ('queued','retry','running')` AND `available_at <= now` AND (**`status IN ('queued','retry')`** OR lease null/expired) |
| Lock semantics | `FOR UPDATE SKIP LOCKED` **plus** `pg_try_advisory_lock(url_fetch_advisory_lock_key(task.id))`; on failure, pushes `available_at` by 1s and returns |
| Cancellation | if document or project is missing or has `deletion_requested_at`, `_terminal_without_claim(code='URL_FETCH_TARGET_DELETED', cancelled=True)`, commit, release lock, `record_url_fetch_attempt('cancelled')`, return no claim |
| Attempt increment | `attempt_count + 1`, and if `attempt_count >= max_attempts` on entry, dead-letters without claiming |
| Lease stamping | `lease_token`, `lease_expires_at`, **and `available_at = lease_until`** |
| State transition | task → `running`, `started_at` set once, `last_error_code` cleared; **`document.status = 'URL_FETCHING'`** |
| Dead-letter | `_terminal_without_claim(dead_letter=True)` on attempts exhausted |
| Transaction | 5 `commit()` calls across the exit paths; advisory lock released on the non-claiming paths, retained on the claiming one |

**AFTER is the same five-step shape**, plus: the advisory lock must be taken
*after* the broker returns (it needs `claim_id`), and the eligibility disjunct
differs — see §5.2.

---

## 4. `analysis_tasks` (`workers/cpu-document/.../worker.py:1098`) — hardest, last

| Dimension | BEFORE |
|---|---|
| Claim eligibility | a **join** of `OutboxEvent` to `AnalysisTask`, filtered on event type/published/dead-lettered/available, task status and `available_at`, **plus a collection-binding subquery** (no active/paused binding, or an active one), plus lease-free-or-queued |
| Lock semantics | `FOR UPDATE OF OutboxEvent SKIP LOCKED` — **the lock is on the event, not the task** — plus an advisory lock |
| Cancellation | 6 terminal/dead-letter branches |
| Attempt increment | on the task, with the outbox event's `attempts` also incremented |
| Lease stamping | task lease, plus outbox `available_at`/`published_at`/`dead_lettered_at`/`last_error` |
| State transition | 15 attribute writes across `task`, `event` and `document` |
| Transaction | 7 `commit()` calls |

**This site does not fit the broker contract as built.** Its unit of claim is an
`(outbox_event, analysis_task)` pair and its lock is on the event; a broker that
returns a single `claim_id` from `analysis_tasks` describes half of it. `0035`
correctly gives `analysis_tasks` no broker on the grounds that nothing polls it
cross-tenant — that grounds is wrong in detail (this *is* a cross-tenant poll),
but the conclusion holds for a different reason: **the shape does not match.**
Recorded here because the registry's stated reason should be corrected to this
one.

---

## 5. Divergences — and the hard stop

### 5.1 STOP — claim eligibility is evaluated against a different clock

**Every one of the four sites takes `now` from an injected clock** (`self._clock()`,
or a `now` parameter). The broker uses `pg_catalog.now()`.

```python
# BEFORE — gpu_jobs.py:875
now = self._clock()
...  GpuProviderInvocation.available_at <= now
```
```sql
-- AFTER — 0035_claim_broker
AND candidate.available_at <= pg_catalog.now()
```

Two consequences, and neither is cosmetic:

- **Test drivability.** The existing suites drive these workers with a fake clock
  to exercise backoff, lease expiry and retry ordering deterministically. Those
  tests cannot reach the broker path at all — the database will not honour the
  fake clock. The equivalence tests directive 1 asks for **cannot be written
  against a frozen clock** unless the broker accepts `now`.
- **Capability.** If the broker instead accepts `now` as an argument, a
  compromised worker can pass a future `now` and claim work before it is due,
  bypassing backoff and retry delay. That is not a cross-tenant escape, but it is
  a new capability the current design does not grant.

**Resolved as an implementer decision, after first writing it up as a founder
one.** The correction matters, so it is left visible: the injected clock is a
*test seam*, not a production behaviour. In production `self._clock()` is wall
time on the application host and `pg_catalog.now()` is wall time on the database,
so the only real difference is host-to-database clock skew — and the database
clock is the better of the two, because it is the one shared by every worker
racing for the same row.

The decision therefore is:

1. **Keep `pg_catalog.now()`.** A caller-supplied `now` would let a compromised
   worker claim work before it is due, bypassing backoff and retry delay. That is
   a real capability and it buys only test convenience.
2. **Equivalence tests control the data, not the clock** — seed `available_at`
   and `lease_expires_at` at chosen offsets and let both paths read real time.
   Eligibility, lease expiry and ordering are all reachable that way.
3. **Backoff arithmetic stays tested where it lives**, against the worker's own
   functions with a frozen clock. It is not part of the claim contract.

Residual, and recorded rather than dismissed: **host-to-database clock skew** now
sits inside claim eligibility. It was always inside lease *expiry* comparisons on
the database side, so the exposure does not change in kind.

### 5.2 The url fetcher's eligibility disjunct

Already recorded in `0035` and in the decision package §3: the broker drops
`status IN ('queued','retry') OR`, because the ORM relies on an advisory lock for
exclusion and the broker has none. This is a **deliberate, documented narrowing**,
found by the concurrency proof. It is explained, so it is not a stop — but it must
appear in the url fetcher's equivalence tests as an expected difference rather
than be discovered later as a regression.

### 5.3 `analysis_tasks` shape mismatch

§4. Not a wiring problem — a contract problem. It needs a decision about whether
the broker concept extends to a two-table claim at all.

---

## 5a. GPU equivalence evidence — three kinds, proved three ways

*Reshaped 2026-08-12 on the coordinator's direction. The earlier version of this
section listed nine proofs as one undifferentiated set. Writing nine independent
tests would have exercised the same code repeatedly to satisfy a count; what
follows classifies the evidence by what each dimension actually is, and proves
each in the way that fits it.*

### A. COMPARATIVE — BEFORE against the broker, one seeded population

Real runs, live catalog, in `infra/postgres/shadow_validate_dual_plane.py`
(`_equivalence_pass`). BEFORE is `GpuInvocationWorker._claim`'s ORM predicate
written as SQL; AFTER is `akc_claim_gpu_invocation` actually claiming. The
population seeds every reason a row is or is not claimable: four claimable, plus
terminal status, not-yet-due, and live-lease rows that neither side may take.

Draining the broker proves eligibility and ordering together — each claim removes
exactly one row from the claimable set, so the grant *sequence* equals the
BEFORE-ordered eligible list only if both agree on both.

| Proof | Result |
|---|---|
| `equivalence:claim-eligibility` | BEFORE finds 4 claimable of 8 seeded; the broker granted exactly that set | **GREEN** |
| `equivalence:ordering` | grant sequence is BEFORE's `(available_at, created_at, id)` order, row for row | **GREEN** |
| `equivalence:lease-expiry` | a live-leased row is claimable by neither; past its expiry it is claimable by both, and is the only such row | **GREEN** |
| `equivalence:concurrency` | 4 concurrent callers drained 8 contended rows into 8 grants, all distinct, none lost | **GREEN** |

These are the four that stay genuinely comparative, and they are where the last
real defect was found — the first concurrency run granted 16 claims over 12 rows.

### B. INVARIANT — the double lease stamp is MADE IMPOSSIBLE

**Recorded as made impossible, not as verified.** Nothing observed a double stamp
and concluded it cannot happen. `_claim_from_row` takes `token` as a keyword-only
parameter and assigns it; the body has nothing to mint a second token with, so
AFTER passing the broker's own value back is a no-op rather than a second write.

The distinction matters to whoever reads this later: a verified property can
regress silently, an impossible one cannot regress without the shape changing.
So the shape is pinned by negative regression tests in
`services/scheduler/tests/test_claim_equivalence.py`:

| Test | Holds |
|---|---|
| `test_the_shared_body_cannot_mint_a_lease_token` | no `uuid4` call anywhere in `_claim_from_row` | **GREEN** |
| `test_the_token_and_lease_arrive_as_parameters` | `token` and `lease_expires_at` are keyword-only parameters | **GREEN** |
| `test_the_before_path_mints_exactly_one_token_and_hands_it_over` | BEFORE mints once and passes it in | **GREEN** |

Reintroducing minting inside the shared body would let AFTER stamp a token
different from the one already on the row, and because the claim binding compares
`lease_token` against `app.lease_token`, the row would vanish from its own
transaction mid-flight. That failure is silent, which is why the defence is shape
rather than vigilance.

### C. SHARED BODY + REACHABILITY

Body equivalence comes from one implementation with two callers. **That is not
sufficient on its own** — a shared body proves both callers run the same code, not
that both *reach* it under the same conditions, and an extra condition on one side
would be an equivalence break no amount of sharing detects. Both halves are
proved separately.

**Body — one implementation:**

| Test | Holds |
|---|---|
| `test_the_claim_choreography_has_exactly_one_implementation` | `_terminal_local`, `append_gpu_event`, `commit` and `_fence_reason` appear in `_claim_from_row` and **not** in `_claim` (per-marker, so a failure names the duplicate) | **GREEN** |
| `test_every_state_transition_lives_in_the_shared_body` | `status`, `attempt_count`, `cancel_attempt_count`, `lease_token`, `lease_expires_at`, `started_at`, `last_error_code` are written only in the shared body; `_claim` writes nothing of its own | **GREEN** |
| `test_the_shared_body_reaches_both_terminal_states` | both `GPU_PROVIDER_CANCEL_UNCONFIRMED` and `GPU_PROVIDER_ATTEMPTS_EXHAUSTED` live there | **GREEN** |
| `test_the_commit_is_the_last_thing_the_shared_body_does` | exactly one `commit`, exactly one `return`, return after commit | **GREEN** |

Rollback and visibility follow from the commit boundary rather than needing their
own exercise: every write sits above one commit in one transaction, and the
broker's `UPDATE` runs inside that same transaction because a `SECURITY DEFINER`
function joins its caller's. An exception anywhere above takes the lease stamp
with it.

**Reachability — the half the refactor does not give for free:**

| Test | Holds |
|---|---|
| `test_entry_into_the_shared_body_is_gated_only_by_finding_a_row` | `_claim` has **exactly one** conditional before the handover, and it is `if invocation is None: return`. Every additional condition would be one the broker path must reproduce, and an unreproduced one is a silent break | **GREEN** |

The structural half says the entry gate is only "did a row turn up". The
behavioural half — that both sides find *the same* row over the same population —
is category A, `equivalence:claim-eligibility` and `equivalence:ordering`.

### What this set covers, and what the written-AFTER proof adds

**GPU equivalence is GREEN for all three categories.** What that establishes is
that the adaptation *would* be behaviour-preserving: same rows, same order, same
exactly-once property, same body, same entry gate, and a second stamp that cannot
be expressed.

It does **not** establish that a written AFTER path is correct — a distinction
worth keeping, because equivalence evidence and implementation evidence are
different things and only the second one ships. That gap is closed separately by
`infra/postgres/verify_claim_via_broker.py`, which runs the real worker against a
real PostgreSQL transaction with `use_claim_broker` on: 21 cases covering token
pass-through, no second stamp, context binding and clearing, scoped reread,
rollback, all five action branches, both terminal states, and Canary A telemetry.

`_claim_via_broker` is implemented. The GPU claim path is wired behind
`GpuWorkerPolicy.use_claim_broker`, **default `false`**, so reaching it is a
deliberate act rather than a deployment.

#### Superseded — this section before the AFTER path was written

> `_claim_via_broker` does not exist. […] It does not establish that a written
> AFTER path is correct, because there is no written AFTER path. **GPU
> equivalence is GREEN for the evidence set the coordinator defined.** Wiring has
> not started.


---

## 6. Status of the two gates

**Gate 1A — detector correctness and discrimination: GREEN** (2026-08-12).

The detector is wired into the real poll path — `GpuInvocationWorker.run_one` →
`_observe_poll` → `claim_backlog` → `ClaimStarvationDetector` →
`record_claim_poll` — publishing five series plus `akc_claim_poll_starved`.
Both halves of the discriminating pair are exercised against that path
(`services/scheduler/tests/test_claim_starvation_gate.py`):

- backlog 12 / claimable 12 / 3 consecutive zero polls → alert, and **not** on
  the first two;
- backlog 400 / claimable 0 / 50 consecutive zero polls → silent throughout.

That the two counts genuinely differ is measured on a live catalog:
`broker:backlog-exceeds-claimable-when-rows-are-leased`, total 16 against
claimable 3.

**Gate 1B — real workload observation: PENDING.** An operational-confidence gate,
not a code gate. Nothing has run this against real traffic. **Required before
production activation; not required before a staging canary.**

**Gate 2 — unmodified pgvector reproduction: GREEN** (2026-08-12). CI run
`31517256771`, job `postgres-rls-and-role-boundaries`, image
`pgvector/pgvector:pg17@sha256:d2ef61f4…`. The unmodified migration tree applied
to head, the privilege receipt was generated, the committed receipt matched a
catalog CI built independently, and the dual-plane shadow suite passed. `0035`
and `0036` apply unmodified on real pgvector.

*Other CI jobs are red for pre-existing reasons — the same failure set appears in
the pre-push run `31378252332`. That is separate debt and is not Gate 2.*

---

## 6a. What opens the first canary

| Gate | Status | Required for |
|---|---|---|
| **1A** detector correctness and discrimination | **GREEN** | staging canary |
| **2** unmodified pgvector reproduction | **GREEN** | staging canary |
| **GPU equivalence** (A comparative · B invariant · C shared-body + reachability) | **GREEN** — see §5a | staging canary |
| **Canary A** broker path with `BYPASSRLS` **ON** | **GREEN** | canary B |
| **Written-AFTER integration proof** | **GREEN** — 21 cases | canary B |
| **1B** real workload observation | **PENDING** | production rollout |

**The first staging `NOBYPASSRLS` canary opens on 1A + 2 + GPU equivalence.** All
three are green, and Canary A and the written-AFTER proof are green on top of
them. **That still disarms nothing by itself.** What remains before Canary B, in
order:

1. push the AFTER-path commit, and re-run on real `pgvector/pgvector:pg17` in
   GitHub Actions — the written-AFTER proof must be green there, not only
   locally;
2. write a **staging-only disarm migration for the GPU worker alone**, at a
   revision reconciled against the current head (`0036_claim_backlog_probe`)
   rather than against the numbering the older plan documents assumed;
3. run Canary B in staging with the broker path on and the GPU worker at
   `NOBYPASSRLS`. **The other six worker roles are untouched.**

Expanding beyond the GPU worker is forbidden until Canary B is green. Production
rollout additionally requires Gate 1B.

**`BYPASSRLS` remains 7/7. No disarm migration exists.**

#### Superseded — this section before the AFTER path was written

> **That does not disarm anything by itself** — opening the canary is a
> deliberate act, it needs the `_claim_via_broker` path that does not yet exist,
> and it needs a disarm migration that has not been written. What the evidence
> establishes is that the adaptation *would* preserve behaviour. What it does not
> establish is that a written AFTER path is correct, because there is none.

### Superseded — Gate 2 as it stood before CI ran

Kept because it records why the gate existed. From this workstation there was no
Docker and no pgvector in the local PostgreSQL 17, so every measurement came from
a cluster where `0024` had been rewritten outside the repository. CI was the only
path to the receipt, and "wired" was explicitly not "green".

`BYPASSRLS` remains 7/7. No disarm migration exists.
