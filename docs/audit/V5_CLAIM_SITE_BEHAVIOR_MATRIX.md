# Claim-site behaviour matrix — BEFORE / AFTER

*Written 2026-08-12, before any wiring. Directive 1 requires a 1:1 behaviour
matrix per claim site and a hard stop if any protected behaviour is left
unexplained.*

**Outcome: wiring is not started.** Two findings gate it, and only one is a true
stop:

- **§5.1, resolved by me** — the clock divergence, which I first wrote up as a
  founder decision and then corrected. It is a test seam, not a production
  behaviour, and the resolution is recorded there.
- **§5.3, a real stop** — `analysis_tasks` claims an `(outbox_event,
  analysis_task)` pair and locks the *event*. The broker contract describes one
  row from one table, so that site cannot be adapted without changing the
  contract. It is the last site in the disarm order, so it blocks nothing yet.

No site has been wired. The canary is chosen and its matrix is complete; the
equivalence tests §5.1 describes are not written.

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

### AFTER (proposed, not written)

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

## 5a. The nine 1:1 proofs the canary needs — required, and NOT written

Directive addendum, 2026-08-12. Wiring does not start until each of these is an
executable test that passes. The matrix above is the specification for them; it
is not a substitute for them.

| # | Proof | What it must show | Status |
|---|---|---|---|
| 1 | which rows are claimable | broker predicate and ORM predicate select the same row from the same seeded population | **not written** |
| 2 | ordering / prioritization | `available_at, created_at, id` yields the same first row under both | **not written** |
| 3 | concurrency | N concurrent callers over M rows grant M distinct claims — proven for the broker (`broker:claims-one-row-atomically`), **not yet compared against BEFORE** | partial |
| 4 | lease token generation | exactly one token per claim, and the site does not stamp a second (§2 risk 1) | **not written** |
| 5 | lease expiration | a row whose lease has run out is claimable again at the same instant under both | **not written** |
| 6 | attempt / state transition | `attempt_count`, `cancel_attempt_count`, `status`, `started_at`, `last_error_code`, `updated_at` end identical across all five action branches | **not written** |
| 7 | commit point | one commit, at the same place, with `GpuProviderAttempt` and the event append inside it | **not written** |
| 8 | both terminal states | `GPU_PROVIDER_CANCEL_UNCONFIRMED` and `GPU_PROVIDER_ATTEMPTS_EXHAUSTED` reached under the same conditions | **not written** |
| 9 | rollback and visibility on failure | a raised exception rolls back the lease stamp too — the broker's `UPDATE` runs inside the caller's transaction, so this should hold by construction and must be shown, not assumed | **not written** |

**No branch has yet been found that an equivalence test cannot account for.**
That is a statement about the matrix, not about the tests: the five action
branches, two terminal paths and the fence are all reachable and all have
observable end states. If writing them surfaces one, the rule is to stop and
report the branch.

---

## 6. Status of the two gates

**Gate 1 — zero-row starvation detection: instrumented, discriminating pair
proven; still RED pending a production observation.**

The detector is wired into the real poll path — `GpuInvocationWorker.run_one` →
`_observe_poll` → `claim_backlog` → `ClaimStarvationDetector` → `record_claim_poll`
— and publishes five series: poll attempts, grants, total backlog, claimable
backlog and the consecutive-zero run, plus `akc_claim_poll_starved`.

Both halves of the discriminating pair are exercised against that path
(`services/scheduler/tests/test_claim_starvation_gate.py`, 7 tests):

- **positive** — backlog 12, claimable 12, three consecutive empty polls →
  `akc_claim_poll_starved == 1`, and **not** on the first two;
- **negative** — backlog 400, claimable 0, fifty consecutive empty polls →
  silent throughout. This is the case one counter cannot see, and a detector that
  paged here would be turned off.

The two counts come from separate privileged probes, and that they genuinely
differ is measured on a live catalog:
`broker:backlog-exceeds-claimable-when-rows-are-leased` reports backlog 16
against claimable 3.

**Still RED**, because the directive requires the detector verified on a
production-equivalent path and nothing has run it against real traffic. What
remains is an observation, not code.

**Gate 2 — unmodified pgvector reproduction: RED, and not runnable here.**

```
docker: command not found
pgvector NOT installed in local PG17
no vector.dll
```

There is no Docker on this machine and pgvector is not installed in the local
PostgreSQL 17. **Gate 2 cannot be produced from this workstation by any means I
have** — the CI job is the only path, and I cannot run CI. The workflow is wired
and labelled; a wired workflow is explicitly not a receipt, and I am not claiming
one.

`BYPASSRLS` remains 7/7. No disarm migration exists.
