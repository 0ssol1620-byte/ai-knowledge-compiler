# INTEGRATION I1 — Canonical Backend Event Model Reconciliation

Status: **RECONCILED — migration-ancestry finding corrected by M0
(2026-08-13, see the "M0 CORRECTION" block after section 1 and the note in
section 9); the canonical backend event model question (job plane vs.
collection plane vs. both) remains open and is unaffected by that
correction — that's a separate architectural question I1 still stands on.**
Originally: research only, no code changed. Written in the Surface Integration
worktree per the I1 dispatch that followed I0
(`docs/integration/I0_SHARED_WORLD_CONTRACT_PROMOTION.md`). Every claim below
is tagged `observed` / `proven` / `inferred` / `proposed`.

Worktrees used (all read-only except the Surface Integration worktree itself,
where only this file was written):

- `D:\CodexProjects\ai-knowledge-compiler-surface-integration` (this branch,
  `agent/tavonel-surface-integration`)
- `D:\CodexProjects\ai-knowledge-compiler-product-app`
  (`agent/tavonel-product-app`, HEAD `0c7a94b`, based on `main` @ `7ac5098`)
- `D:\CodexProjects\ai-knowledge-compiler-v5-cinematic`
  (`agent/tavonel-v5-cinematic`, HEAD `3d2cb8c`)
- `D:\CodexProjects\ai-knowledge-compiler-cinematic-v2`
  (`agent/tavonel-cinematic-v2`)
- `D:\CodexProjects\ai-knowledge-compiler`
  (`agent/folynta-trust-integration-v1`, the Security track)
- `origin/main` (fetched ref in the product-app remote), tip `185d04b`
  ("Merge pull request #34 ... agent/tavonel-trial-ingest") — **newer** than
  the `7ac5098` this and prior Integration work is based on. `observed`.

---

## 1. Lineage graph

`observed` (from `git log`, `git show`, file contents, in each worktree):

```
main line (job/document pipeline):
  0001_full_domain (job_events table, EventType/JobEvent) ... 
  0022_cdr_derivative_lineage @ 7ac5098 (Integration branches' base)
      |
      +-- 0023_trial_ingest -- origin/main tip 185d04b
              (anonymous-trial feature; unrelated to events; NOT reachable
               from the Integration branches' 7ac5098 base)

d7a6b30 "feat: complete Structara v4 and v6 platform" (2026-08-01)
  introduces akc_cir.collection_events.CollectionEventType,
  services/api/src/akc_api/collection_api.py, the `collections`/
  `collection_events`/... table family, and the collection SSE stream.
  d7a6b30 branches off before 0023_v4_collections; NOT an ancestor of main
  (git merge-base --is-ancestor d7a6b30 7ac5098 -> no, reconfirmed this
  session).
      |
      +-- agent/tavonel-v5-cinematic (migrations 0023_v4_collections ...
      |     0033_backfill_checkpoint_tenant_rls; head 3d2cb8c)
      |       +-- agent/tavonel-cinematic-v2 (inherits the same chain
      |             unchanged for the contract layer; presentation-only
      |             fixture edits on top, per I0 section 1)
      |
      +-- agent/folynta-trust-integration-v1 (Security track): inherits the
            FULL collection_events migration chain 0023_v4_collections ...
            0033_backfill_checkpoint_tenant_rls, then adds its OWN chain on
            top: 0034_dual_plane_authorization, 0035_claim_broker,
            0036_claim_backlog_probe, 0037_gpu_post_claim_authorization.

ProductEvent / LiveEventAdapter / WorldProjection:
  introduced V5 foundation commit 270875e (agent/tavonel-v5-cinematic),
  fixed in f042563, unchanged through cinematic-v2, promoted (contract-only
  half) onto this Integration branch in eb26ba7/14a05bf. Per I0 section 3,
  LiveEventAdapter was written against collection_events, which main does
  not have.
```

Key fact worth flagging on its own: **the Security track's migration chain is
built on top of the `collection_events`/V4-collections lineage, not on top of
`main`'s current chain.** `0034_dual_plane_authorization`'s `down_revision`
is `0033_backfill_checkpoint_tenant_rls`, which in turn chains back through
`0023_v4_collections` to `d7a6b30`. This means the Security track's claim
broker / `GpuInvocationWorker` work has never been proven to apply cleanly on
top of `main`'s real migration head (`0023_trial_ingest` on `origin/main`,
which the Security branch also does not have) -- that is a fact about
migration ancestry, not a statement about whether Security's work is correct;
flagged for the Security track and the founder, not resolved here (see
section 11).

> ## M0 CORRECTION (2026-08-13) — SUPERSEDES THE MIGRATION-ANCESTRY FINDING ABOVE
>
> **What I1 originally observed (quoted above, unmodified):** that the
> Security track's migration chain descends from `collection_events`/V4, not
> from `main`'s real head, and that this ancestry was therefore unresolved.
>
> **Why that observation was wrong:** it was read from a stale checkout of
> the Security worktree, taken before the Security branch's own reconciling
> merge had been accounted for in this document.
>
> **M0's proven current state** (`docs/integration/M0_MAINLINE_MIGRATION_RECONCILIATION.md`,
> independently re-verified by the orchestrator against the live Security
> worktree on 2026-08-13 — `0023_v4_collections`'s `down_revision` confirmed
> to read `0023_trial_ingest`, not `0022_cdr_derivative_lineage`; `185d04b`
> confirmed a real ancestor of the Security branch's current HEAD;
> `test_migration_graph.py` confirmed passing 6/6 on that branch right now):
> - `origin/main` merged PR #34 (`185d04b`, "trial-ingest") on 2026-08-09 09:42.
> - Three hours later, the Security branch merged that into itself at commit
>   `709a15f` ("merge: reconcile with main after #33 and #34 landed") and
>   explicitly re-pointed `0023_v4_collections`'s `down_revision` from
>   `0022_cdr_derivative_lineage` onto `0023_trial_ingest` — producing one
>   linear, single-head, single-base migration chain.
> - `tests/unit/test_migration_graph.py` was added in that same merge and
>   passes cleanly against the reconciled chain (6/6).
> - `v5-cinematic`/`cinematic-v2` fork from *inside* Security's post-reconcile
>   line (2026-08-11, `5d59bf6`), not the other way around.
> - The tracks actually behind the reconciled mainline are **Product App,
>   Commercial Shell, and Surface Integration** — all three still pinned to
>   `7ac5098` with migrations ending at `0022`, none carrying the guard test.
>
> **Conclusion:** the unresolved-ancestry claim quoted above is
> **SUPERSEDED / FACTUALLY CORRECTED**. Security's migration lineage is
> already reconciled and verified single-head. This does not change I1's
> separate, still-open finding about which backend *event model* is
> canonical (§B/§E below) — migration-lineage reconciliation and
> event-model canonicality are two different questions; only the former is
> resolved by this correction. It also does not change Security's own gate
> state: `BYPASSRLS 7/7` / `Gate 1B PENDING` / `Canary B BLOCKED` are
> unaffected by this correction in either direction.

---

## 2. Producer inventory -- `observed`

| Model | Producer | File | Branch(es) |
|---|---|---|---|
| `akc_cir.events.EventType` / `ProcessingEvent` | `emit_event()` (validates `event_type` against `EventType`, writes a `JobEvent` row inside the same transaction as the job mutation, tenant-scoped, monotonic `job.event_sequence`) | `services/api/src/akc_api/services.py:176` | `main`, product-app, and (still present, unremoved) v5-cinematic, cinematic-v2, Security |
| `akc_cir.events.EventType` (dispatch-terminal paths) | Direct `emit_event` calls, e.g. `job.failed.v1` at `scheduler.py:604` | `services/scheduler/src/akc_scheduler/scheduler.py` | product-app-equivalent chain, Security |
| `akc_cir.collection_events.CollectionEventType` | `_emit_collection_event()` (`collection_api.py`) and direct `CollectionEvent(...)` inserts (e.g. `scheduler.py:557`, on collection-linked job failure) | `services/api/src/akc_api/collection_api.py`, `collection_integrity_runtime.py`, `collection_integrity_decisions.py`, `parallel_runtime_store.py`; `services/scheduler/src/akc_scheduler/scheduler.py` | v5-cinematic, cinematic-v2, Security -- **absent on `main`/product-app** (grep for `collection_events`/`CollectionEventType` across product-app's `.py` tree returns zero matches; no `collection_events.py` file exists there) |
| `ProductEvent` | None. No backend anywhere emits `ProductEvent`-shaped frames; it is fed by either `DemoFixtureEventSource` (scripted fixture) or the not-yet-connected `LiveEventAdapter`. | `apps/web/src/lib/*` | Integration branch only |

**Direct evidence of the relationship between the two backend models**
(`observed`, Security branch, `services/api/src/akc_api/collection_api.py:6516-6531`):

```python
if source_job_events:
    await _emit_collection_event(
        session, collection=collection,
        event_type="processing.source_events.bridged.v1",
        job_id=parent_job.id,
        payload={
            "collection_id": str(collection.id),
            "processing_job_id": str(parent_job.id),
            "processing_jobs": len(processing_jobs),
            "source_event_count": len(source_job_events),
            "source_event_type_counts": dict(
                sorted(Counter(row.event_type for row in source_job_events).items())
            ),
        },
    )
```

`source_job_events` here are rows read from the **`JobEvent`/`EventType`
table** (`job_events`, keyed by the per-document `ProcessingJob`), and this
code summarizes/bridges them into a single `CollectionEvent`
(`processing.source_events.bridged.v1`) scoped to the batch. `proven`:
`services/api/tests/test_collection_api.py:951` asserts
`event_types.count("processing.source_events.bridged.v1") == 1` against a
real test run of this code path.

This is also directly observable in the failure path at
`scheduler.py:547-613`: on a collection-linked job's terminal dispatch
failure, the scheduler writes **both** a `CollectionEvent`
(`processing.failed.v1`, `collection_id`-keyed, collection status updated)
**and**, for the non-collection dispatch-exhaustion case a few lines later,
an `emit_event(job.failed.v1)` (`job_id`-keyed). They are not alternatives
chosen by branch -- a single collection-scoped job failure produces rows in
both tables in the same commit.

---

## 3. Transport inventory -- `observed`

| Endpoint | Model served | File | Branch(es) |
|---|---|---|---|
| `GET /v1/jobs/{job_id}/events` (SSE, `text/event-stream`, replay/reset via `sequence`, tenant RLS-scoped query, heartbeat every 15s) | `JobEvent`/`EventType`, wire-shaped by `_event_wire()` | `services/api/src/akc_api/main.py:4869-5148` | `main`/product-app (and still present unremoved on the other branches) |
| `GET /v1/collections/{id}/events?after_sequence=...` (poll) and `/v1/collections/{id}/events/stream` (SSE) | `CollectionEvent`/`CollectionEventType` | `services/api/src/akc_api/collection_api.py` (~line 5020-5100) | v5-cinematic, cinematic-v2, Security -- **no equivalent route exists on `main`** (`collection_api.py` itself does not exist on `main`) |

Frontend consumers, `observed`:

- `apps/web/src/lib/api-client.ts` (product-app / `main` lineage):
  `streamJob()` calls `fetchEventSource` against
  `${API_URL}/v1/jobs/${jobId}/events`, parses frames with `parseJobEvent()`
  into the hand-written `JobEvent`/`JobEventType` TS types declared in
  `apps/web/src/lib/types.ts` (**not** generated from `@akc/contracts` --
  see section 5). Consumed by `admin-live.tsx`, `analytics-live.tsx`,
  `dashboard-live.tsx`, `app-shell.tsx`, and others (10+ component matches).
  `proven`: `api-client.test.ts` asserts on real `event_type:
  "job.completed.v1"` payload shapes and drives `streamJob` end to end
  against a mocked SSE source.
- `apps/web/src/lib/collection-runtime-client.ts` (Security/cinematic
  lineage): imports `COLLECTION_EVENT_TYPES`,
  `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS`, `CollectionEventGenerated`
  **directly from `@akc/contracts`** (not hand-duplicated), calls
  `fetchEventSource` against `/v1/collections/{id}/events/stream`, and
  separately polls `/v1/collections/{id}/events`. **This file does not
  exist on `main`** (only on the Security/cinematic branches).

---

## 4. Persistence inventory -- `observed`

| Table | Model | Migration that created it | Present on `main`? |
|---|---|---|---|
| `job_events` | `akc_cir.events.EventType` / `JobEvent` | `0001_full_domain` (baseline); index/permission hardening in `0007_job_event_retention` | **Yes.** Verified via `git ls-tree -r origin/main` and the product-app worktree: both show `0001`...`0022` (product-app) / `...0023_trial_ingest` (origin/main); `models.py` on product-app defines `class JobEvent(Base): __tablename__ = "job_events"` at line 1294. |
| `collections`, `collection_source_roots`, `collection_files`, `collection_events`, `collection_preflights`, `collection_regions`, `collection_integrity_decisions`, `collection_integrity_action_executions`, ... (11+ tables) | `akc_cir.collection_events.CollectionEventType` / `CollectionEvent` + surrounding collection-domain aggregate | `0023_v4_collections`, `0025_collection_processing_runtime`, `0026`-`0030` | **No.** `git ls-tree -r origin/main -- migrations/versions` stops at `0023_trial_ingest`; grep for `collection_events` across product-app's `.py` tree returns zero files; grep for `"collection"` across product-app `migrations/versions/*.py` returns zero files. |

`job_events` has been in the schema since the very first migration
(`0001_full_domain`, `down_revision = None`) -- it is not a late addition;
it is baseline domain. `collection_events` and its surrounding table family
enter at `0023_v4_collections`, a migration `main` has never had.

---

## 5. Generated-contract comparison (`@akc/contracts`) -- `observed`

```
packages/contracts/src/generated-contracts.ts:
  product-app (= main)         111 lines
  v5-cinematic                 376 lines
  cinematic-v2                 376 lines  (byte-identical to v5-cinematic;
                                            diff produced zero output)
  Security (folynta-trust-...) 376 lines  (same content)
```

`main`'s 111-line file has **no event-stream type at all** -- it is entirely
`CanonicalDocumentContract`, `CanonicalTableContract`,
`DocumentClassificationContract`, `ErrorEnvelopeContract`,
`ExportManifestContract`, `KnowledgeBundleContract`. No `EventType`, no
`ProcessingEvent`, no `JobEvent`. This means **`main`'s real, deployed event
model (`akc_cir.events.EventType`/`JobEvent`) is not exposed through the
generated contract package at all** -- the frontend's `JobEventType`/
`JobEvent` TS types in `apps/web/src/lib/types.ts` are hand-maintained and
not generated or cross-checked against the Python `EventType` enum by any
tooling found in this repo. This is a real, unrelated-to-`collection_events`
gap.

The 376-line file (v5-cinematic/cinematic-v2/Security, identical across all
three) exports `COLLECTION_EVENT_TYPES`, `CollectionEventType`,
`COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS`,
`COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS`, and
`CollectionEventContract.Root` -- generated from `akc_cir.collection_events`,
consumed directly by `collection-runtime-client.ts`. It still has **no
generated type for `akc_cir.events.EventType`/`ProcessingEvent` either** --
that gap exists on every branch checked, not just `main`.

---

## 6. Payload field matrix -- `observed` (schema/model fields) + `inferred` (mapping quality where no test proves it)

### 6a. `akc_cir.events.EventType` / `JobEvent` -> `ProductEvent`

| Backend field (`ProcessingEvent`/`JobEvent`) | `ProductEvent` field | Mapping |
|---|---|---|
| `tenant_id` | *(none)* | **unavailable** -- `ProductEvent` envelope has no tenant field at all (`observed`, `product-event.ts` envelope: `schema_version, event_id, sequence, occurred_at, collection_id, mode, document_id?, page_number?`) |
| `project_id` | *(none)* | **unavailable** |
| `job_id` | *(none)* | **unavailable**; `ProductEvent` is keyed on `collection_id`, which `JobEvent` does not have at all |
| `document_id` | `document_id` | **exact**, when present -- but `JobEvent` payload doesn't reliably carry it per event type |
| `page_id` | `page_number` | **transformed** -- `page_id` is a `StableId`, `ProductEvent.page_number` is a 1-based int; no direct derivation shown anywhere in the code read |
| `sequence` | `sequence` | **exact**, name and semantics match (positive monotonic int) |
| `occurred_at` | `occurred_at` | **exact**, both ISO datetime strings |
| `event_type` (from `EventType`, e.g. `page.route.selected.v1`) | `event_type` (from `ProductEventType`) | **name-coincidental only** for the one shared string, `page.route.selected.v1`; payload shapes were never cross-checked (I0 section 3, reconfirmed here -- no test in this repo compares `EventType`'s payload for `page.route.selected.v1` against `ProductEvent`'s) |
| *(no `collection_id` field exists in `EventType`/`JobEvent` at all)* | `collection_id` (**required**, non-optional, in the envelope) | **unsafe to infer** -- there is no backend field to source this from for a `JobEvent`-shaped frame; a `LiveEventAdapter` targeting `EventType` would have to fabricate a `collection_id`, which `CLAUDE.md`'s "never invent data" rule forbids |
| -- route/recovery identity (`route_label`, `attempt` count) | `payload.lane`, `payload.attempt` in `page.route.selected.v1` | **transformed at best, unproven** -- `events.py`'s `payload: dict[str, Any]` is untyped at the Python level; could not confirm at any emit site whether it carries `lane`/`attempt` the way `ProductEvent` expects |
| -- world-state identity (`world_state_id`, `previous_world_state_id`) | `world_state.activated.v1` payload | **unavailable** -- no `world_state` concept found anywhere in `akc_cir/events.py`; this is a `PROPOSED_EVENT_TYPES` member with zero backend producer on any branch checked |
| -- evidence locator (`SourceRef`-shaped) | `sourceRefLiteSchema` (`document_id`, `document_label`, `page_number`, `locator`, optional `cell`) | **unavailable from `JobEvent`** -- `EventType` payloads are untyped dicts; no evidence in this session that any emit site populates a `SourceRef`-shaped structure |

### 6b. `akc_cir.collection_events.CollectionEventType` / `CollectionEvent` -> `ProductEvent`

| Backend field | `ProductEvent` field | Mapping |
|---|---|---|
| `tenant_id` | *(none)* | **unavailable**, same gap as 6a |
| `collection_id` | `collection_id` | **exact** -- both are `collection_id`-keyed, the one structural match `EventType` cannot offer |
| `job_id` (nullable) | *(none)* | **unavailable** in `ProductEvent`, though present in `CollectionEvent` |
| `sequence` | `sequence` | **exact** |
| `event_type` (from `CollectionEventType`) | `event_type` (from `ProductEventType`) | **name match for the 8 `REUSED_EVENT_TYPES`, payload divergent for all 8** -- `product-event.ts`'s own header comment states this explicitly (`observed`, lines 26-30): *"Sharing a name is not sharing a contract, and here it is neither. All eight reused types declare payloads that do not satisfy the backend's required fields, so the second arrow above does not yet work against the real collection stream: those frames fail validation and are dropped."* This is the strongest single piece of evidence in this whole investigation that even the branch that invented `LiveEventAdapter` never achieved a working mapping. |
| `timestamp`/`occurred_at` | `occurred_at` | **exact**, both ISO strings (note: the wire field is named `timestamp` in the generated `CollectionEventContract.Root` but `occurred_at` in the DB row -- a rename happens somewhere in serialization not audited line-by-line here) |
| -- route/recovery payloads exist in the vocabulary (`page.route.selected.v1`, `region.route.selected.v1`) | `payload.lane`, `payload.attempt` | **transformed at best, unproven** -- same caveat as 6a; per-type `_contract(...)` payload shape for these two types was not read line-by-line this session |
| *(no world-state concept in `CollectionEventType` either -- its vocabulary is discovery/upload/preflight/processing/integrity/export, not authority/temporal)* | `world_state.activated.v1`, `authority.resolved.v1`, `revision.family.detected.v1` | **unavailable** -- none of `ProductEvent`'s temporal/authority-identity types have a `CollectionEventType` counterpart by name or evident payload; these are `PROPOSED_EVENT_TYPES` with zero producer on any branch |
| `integrity.decision.recorded.v1`, `integrity.action.state_changed.v1` (real, tested -- `CollectionIntegrityDecision`/`CollectionIntegrityActionExecution` tables exist and are written by `collection_integrity_decisions.py`/`collection_integrity_runtime.py`) | *(no `ProductEvent` member for this)* | **`ProductEvent` is missing coverage the backend already has** -- the inverse gap: real backend event types with no `ProductEvent` representation at all |
| -- evidence locator | `sourceRefLiteSchema` | **unavailable from a typed field**, same untyped-payload caveat -- though `collection_events.py`'s `_contract(...)` dict (seen partially, e.g. line 334) suggests payload shapes ARE declared per-type here (unlike `EventType`), which is `inferred` to make `CollectionEventType` payloads more likely to be typed/contract-checked than `EventType`'s, based on `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` existing as a generated, enforced structure with no `EventType` equivalent on any branch |

**Bottom line on section 6:** neither candidate maps cleanly to
`ProductEvent` today. `EventType`/`JobEvent` fails structurally -- it has no
`collection_id` at all, which `ProductEvent`'s envelope requires
non-optionally. `CollectionEventType`/`CollectionEvent` matches structurally
(`collection_id`-keyed, same as `ProductEvent`) but the one place this was
actually tested (`product-event.contract.test.ts`) proved the 8 "reused"
payload shapes do not match -- which is the header comment's own admission
on the branch that invented the mapping.

---

## 7. `ProductEvent` coverage matrix -- `observed` + `inferred`

Of the 22 `ProductEvent` union members (8 `REUSED_EVENT_TYPES` + 14
`PROPOSED_EVENT_TYPES`):

| Group | Count | Backend candidate | Status |
|---|---|---|---|
| `REUSED_EVENT_TYPES` | 8 | `CollectionEventType` name match | Name exists on Security/cinematic branches only (not `main`); payload divergence `proven` for all 8 by `product-event.ts`'s own comment and the (currently non-runnable-on-`main`) contract test |
| `PROPOSED_EVENT_TYPES` | 14 | none | `observed`: zero producer on any branch checked -- `world_state.activated.v1`, `authority.resolved.v1`, `conflict.detected.v1`, `recompile.*`, `answer.*`, etc. have no match in either `EventType` or `CollectionEventType`'s vocabulary |

One name, `page.route.selected.v1`, is shared verbatim between `EventType`
and `CollectionEventType` (`observed`, I0 section 4 table, reconfirmed by
direct enum listing this session) -- but appears **twice** in the ecosystem
(`EventType.PAGE_ROUTE_SELECTED` and
`CollectionEventType.PAGE_ROUTE_SELECTED`), and neither payload shape was
cross-checked against `ProductEvent`'s `routeSelected` schema (`lane`,
`attempt?`, `reason?`, `page_count?`) in this session or, as far as the
tests show, in any prior one.

---

## 8. Fixture-only vs. backend-supported event matrix -- `observed`

**All 22 `ProductEvent` union members are currently produced only by
`DemoFixtureEventSource`.** Grep-confirmed: no backend code path anywhere in
the four backend-bearing worktrees (`main`, v5-cinematic, cinematic-v2,
Security) emits a `ProductEvent`-shaped frame; `ProductEvent`'s Zod schemas
are a client-side vocabulary that at best shares *names* (not payloads) with
8 `CollectionEventType` members and shares nothing with `EventType`. This
reconfirms and extends I0 section 4's conclusion with the additional finding
that the "reused" label was optimistic even on its home branch.

---

## 9. Security/tenant-correlation implications -- `observed`, reported without judgment per the dispatch's hard constraint

- `JobEvent`/`EventType`'s SSE route (`main.py:4869+`) does real tenant-RLS
  enforcement: `set_rls_context(event_session, tenant_id=principal.tenant_id, ...)`
  before every poll, and the underlying `JobEvent` query filters on
  `JobEvent.tenant_id == principal.tenant_id` explicitly, in addition to RLS.
- `CollectionEvent`'s emission path is transactional with the collection
  aggregate (`collection.event_sequence += 1` in the same session as the
  `CollectionEvent` insert), matching the same pattern `emit_event` uses for
  `JobEvent`/`job.event_sequence`.
- The Security track's own migrations (`0034_dual_plane_authorization`,
  `0035_claim_broker`, `0036_claim_backlog_probe`,
  `0037_gpu_post_claim_authorization`) sit **on top of** the
  `collection_events` lineage (down_revision chain confirmed:
  `0034 -> 0033_backfill_checkpoint_tenant_rls -> ... -> 0023_v4_collections
  -> d7a6b30`). **`⚠` SUPERSEDED — see the "M0 CORRECTION" block after
  section 1.** At the time this paragraph was written, `0023_v4_collections`
  still chained back to `d7a6b30`; M0 established that the Security branch
  had already re-pointed that same revision's `down_revision` onto
  `0023_trial_ingest` (commit `709a15f`, 2026-08-09, three hours before this
  research session began) and added a passing `test_migration_graph.py`
  guard. The "never been exercised against `main`'s actual migration head"
  claim in this paragraph is factually incorrect as of that merge; do not
  treat it as current. `BYPASSRLS 7/7` / `Gate 1B PENDING` / `Canary B
  BLOCKED` remain unaffected either way — that part of this paragraph still
  holds.
- Per the same evidence, promoting `collection_events` to `main` would not
  be a small, isolated change: it drags in the entire `0023`-`0033`
  migration chain (11 migrations, 11+ tables), not just
  `collection_events.py` in isolation. `inferred` from the migration
  dependency graph -- not verified by actually attempting the promotion,
  which this task is not authorized to do.

---

## 10. Migration/coexistence implications -- `observed`

- `main`'s migration chain is single-head and currently ends at
  `0023_trial_ingest` (`origin/main`) / `0022_cdr_derivative_lineage`
  (the `7ac5098` base the Integration branches use).
- The `collection_events`/V4-collections chain (`0023_v4_collections`
  through `0033_backfill_checkpoint_tenant_rls`) and `main`'s own chain
  (`...0022_cdr_derivative_lineage -> 0023_trial_ingest`) **both descend
  from `0022_cdr_derivative_lineage` but diverge into two different
  `0023_*` revisions** (`0023_trial_ingest` vs `0023_v4_collections`) that
  were never reconciled into one head on any branch checked. On
  v5-cinematic, `0023_v4_collections`'s own `down_revision` is
  `0023_trial_ingest` -- meaning that branch *has* linearized the two, by
  placing `v4_collections` after `trial_ingest` -- while
  `main`/`origin/main` has `trial_ingest` with no `v4_collections` after it
  at all. This is exactly the kind of multi-branch migration divergence
  `tests/unit/test_migration_graph.py` is designed to catch **within a
  single branch**; it does not and cannot catch divergence **across**
  branches that have not yet been merged. Promoting `collection_events` to
  `main` would require deciding whether `main`'s real `0023_trial_ingest`
  becomes the down-revision for a renumbered `collection_events` migration
  set, which is itself real migration-authorship work, not a research
  question this document answers.
- No migration on any branch checked deletes or supersedes `job_events`.
  Every branch that has `collection_events` still has `job_events` too, and
  both are actively written to by the same scheduler code (`scheduler.py`)
  in the same failure branch, as shown in section 2. This is direct
  evidence against "supersede" and for "coexist at different planes."

---

## 11. Answers to the five questions

**A. Which event model is actually produced by the intended production
pipeline today?**
Both are actually produced with real, traceable, tested producer paths --
but on different branches. On `main` (the only branch that is actually the
current deployed lineage per this repo's own precedence rules), only
`akc_cir.events.EventType`/`JobEvent` has a producer, persistence, transport,
and consumer path -- `observed` end to end (sections 2-4). `collection_events`
has an equally real, equally tested producer/persistence/transport/consumer
path, but only on the v5-cinematic/cinematic-v2/Security lineage, which is
not `main`. Neither is "more real" in the abstract; they are real on
different branches, and `main` is the one this repo's constitution treats
as authoritative absent a promotion decision.

**B. Is `collection_events` intended to supersede `events.EventType`,
coexist with it, or serve a different plane?**
Coexist at a different, higher abstraction level -- `proven`, not inferred.
Direct code evidence (sections 2, 9, 10): the same scheduler failure path
writes both a `CollectionEvent` and (in the non-collection case) a
`JobEvent`/`emit_event` in the same commit; `collection_api.py` has an
explicit bridge event, `processing.source_events.bridged.v1`, that reads
`JobEvent` rows and summarizes them into a `CollectionEvent` -- i.e.
`collection_events` is a batch/source-root-scoped aggregation layer sitting
above the per-document `job_events` stream, not a competing replacement for
it. No branch checked ever removes or deprecates `job_events` while adding
`collection_events`.

**C. Which one has the stronger end-to-end evidence?**
On `main`: only `EventType`/`JobEvent` has any evidence at all -- it is the
only one that exists there. On the branches where both exist
(v5-cinematic/cinematic-v2/Security): both have real
producer->persist->transport->consumer paths with passing tests
(`api-client.test.ts` for `JobEvent`; `test_collection_api.py` +
`collection-runtime-client.ts`'s own contract-error handling for
`CollectionEvent`). Neither is evidentially weak where it exists; the
weakness is entirely in the third thing, `ProductEvent`, which has zero
backend producer anywhere and whose own contract test (where it can run)
proves its "reused" payloads do not match the backend it claims to reuse
from.

**D. What information is lost when mapping either model to `ProductEvent`?**
See section 6 in full. Structurally: `EventType`/`JobEvent` cannot supply
`collection_id` at all (unavailable, not just lossy) since it has no such
field; `CollectionEventType`/`CollectionEvent` can supply `collection_id`
exactly but its 8 name-matching payloads are `proven` non-conformant to
what `ProductEvent` actually validates. Both candidates are missing tenant
identity, world-state identity, and a typed evidence locator entirely --
none of that exists as a structured field in either backend model's
untyped/loosely-typed payload dict as far as this session could verify.

**E. What should the final boundary be?**
See section 12 -- `proposed`, not `observed`. This document does not force
a single answer; the evidence supports different conclusions for different
halves of the union.

---

## 12. Recommended final architecture -- `proposed`

**Neither pure option 1 nor pure option 2 fits the evidence.** The two
backend models are not substitutes (section 10, `proven`), so promoting one
and rewriting `LiveEventAdapter` against it alone would silently drop the
other plane's events, and `main` does not have the collection plane at all
today.

**Recommended: a variant of option 3 (two upstream adapters converging into
one `ProductEvent`), but explicitly gated on option 1's precondition being
done first, and with `ProductEvent`'s union split to match:**

1. `ProductEvent` should be split (or at minimum internally partitioned)
   into two families that mirror the two real backend planes: a
   **job/document plane** (per-document processing -- routing, pages,
   blocks, quality; no `collection_id`) and a **collection/batch plane**
   (discovery, upload, preflight, integrity -- genuinely
   `collection_id`-scoped). Forcing every `ProductEvent` frame through one
   envelope that hard-requires `collection_id` is itself part of why
   `EventType` can never satisfy it structurally (section 6a) -- that is a
   `ProductEvent` design constraint fighting the shape of the plane it is
   supposed to represent, not a backend problem.
2. **`collection_events` promotion to `main` is a precondition for the
   collection-plane half of `ProductEvent` to ever be real**, and per
   sections 9/10 it is not small: it is 11 migrations, a table family, and
   a decision about how `main`'s real `0023_trial_ingest` head reconciles
   with `0023_v4_collections`. This document does not recommend doing that
   promotion as part of this task -- it recommends that the founder treat
   "do we want the collection/batch ingestion architecture (v4/v6
   Structara) on `main` at all" as the actual question, since
   `collection_events` is inseparable from that larger architecture, not a
   standalone event enum.
3. For the job/document plane, `LiveEventAdapter` should target `main`'s
   real `akc_cir.events.EventType`/`JobEvent` -- it is the only backend
   model that exists on `main` today -- but only after `ProductEvent`'s
   job-plane members are redesigned to not require `collection_id`, and
   only after someone writes and passes a contract test analogous to
   `product-event.contract.test.ts` that actually cross-checks payload
   shapes (section 6a shows this has never been done for `EventType`,
   unlike `CollectionEventType`, which at least has a test proving its
   divergence).
4. Until (2) is decided, the collection-plane half of `ProductEvent`
   (`REUSED_EVENT_TYPES`, all 8) should be treated as
   **backend-unsupported on `main`**, exactly as I0 concluded, and should
   stay fixture-only rather than being wired to a `LiveEventAdapter` that
   would either fabricate `collection_id` values (forbidden by this
   repo's "never invent data" rule) or throw on every real `main` job
   event (since `main` never emits collection-shaped frames at all).

This is closest to **option 3, modified**, not a clean pick of 1/2/3/4 as
listed in the dispatch -- flagged explicitly since the dispatch asked not to
force the answer toward one of the four if the evidence doesn't support it.

---

## 13. What this document does not resolve

- Whether "Structara v4/v6" (the collection/batch ingestion architecture) is
  wanted on `main` at all is a scope/roadmap decision for the founder, not
  an engineering fact this research can determine.
- Whether the Security track's claim-broker migrations (`0034`-`0037`) can
  be cleanly rebased onto `main`'s actual head (`origin/main`'s
  `0023_trial_ingest`) instead of the `collection_events` chain was not
  attempted -- that is implementation work, explicitly out of scope here,
  and belongs to the Security track's own process.
- The exact payload shape `akc_cir.events.EventType.PAGE_ROUTE_SELECTED`
  (or any other `EventType` member) actually emits at runtime was not
  fully traced field-by-field in this session; `events.py` declares
  `payload: dict[str, Any]` with no per-type schema, unlike
  `collection_events.py`'s `_contract(...)` dict. A follow-up that greps
  every `emit_event(..., payload={...})` call site in `main`'s
  `services/api` and `services/scheduler` to build a real per-type payload
  catalogue would materially strengthen section 6a and is recommended
  before anyone writes a `LiveEventAdapter` against `EventType`.

---

## 14. 2026-08-13 addendum — strengthened payload/transport/producer evidence, and a question neither this document nor I2 has answered

This section follows this document's own precedent (see the "M0 CORRECTION"
block after section 1) for appending dated findings without deleting or
rewriting prior text. Everything below is new investigation done after
section 13 was written; it does not revisit or contradict I1's core
job-plane/collection-plane coexistence finding (§B, `proven`) or the
M0 migration-ancestry correction. It follows directly the item §13 already
flagged as a recommended follow-up (per-type payload catalogue before
writing a `LiveEventAdapter`).

### 14.1 Real emit-site payloads, both planes, same event-type name — `observed`

`page.route.selected.v1` is emitted by both planes with genuinely different
shapes (not merely field-name drift — a structural mismatch with what
`ProductEvent` requires):

- Job plane, `services/api/src/akc_api/services.py:3898-3919`:
  ```python
  event_type="page.route.selected.v1",
  payload={
      "page_id": ..., "route": route.value, "policy_version": route_policy_version,
      "route_profile": route_profile, "processing_mode": ...,
      "sensitive_data_detected": ..., "reasons": list(route_reasons),
      "estimated_credits": ...,
      **({"attempt_id": ..., "attempt_number": ...} if page_attempt else {}),
  }
  ```
- Collection plane, `services/api/src/akc_api/collection_api.py:6595-6609`
  (batch-level summary, not per-page):
  ```python
  event_type="page.route.selected.v1",
  payload={
      "collection_id": ..., "processing_job_id": ..., "page_count": len(pages),
      "route_counts": dict(sorted(route_counts.items())),
      "route_policy_versions": sorted({...}),
  }
  ```

`ProductEvent`'s schema (`apps/web/src/lib/product-event.ts:251-258`)
requires a `lane` field (required enum) for this event type, plus optional
`attempt`/`reason`/`page_count`. **`lane` does not exist in either real
backend payload** — the job plane calls the same concept `route` (a
different field name, and the enum's actual member set was not
cross-checked against `ROUTE_LANES` this session); the collection plane has
no per-event `route`/`lane` at all, only an aggregated `route_counts` dict
across the whole batch. I1 §6a/§6b previously marked this mapping
"unproven" in both directions; it is now `proven` non-conformant in both
directions, strengthening (not weakening) I1's existing "payload divergence"
finding — this closes the specific gap §13's last bullet asked for, for
this one event type. The other 7 "reused" `CollectionEventType` members were
**not** traced line-by-line this round (3 of 8 checked total across this
document's history: `page.route.selected.v1`, `region.route.selected.v1`,
`numeric.authority.verified.v1`) — still open.

### 14.2 Transport reachability — `observed`

Both SSE/poll routes are unconditionally mounted, not feature-flagged or
dead code: `services/api/src/akc_api/main.py:9066-9083` mounts both
`collection_router` (from `collection_api.py`) and the job-plane router with
plain `app.include_router(...)` calls, no `settings.enable_*` gate found
(grepped `collection_api.py` in full for feature-flag conditionals — none).
`/jobs/{job_id}/events` (`main.py:4862`) and
`/collections/{id}/events/stream` (`collection_api.py:5012`) are both real,
registered, reachable routes.

### 14.3 New finding, not covered by I1 §1-§13 or by I2: both planes already have production consumers that bypass `ProductEvent` entirely — `observed`

- **Job plane**: `apps/web/src/lib/event-reducer.ts` in the Product App
  worktree (`D:\CodexProjects\ai-knowledge-compiler-product-app`) is a
  self-contained `LiveJobState` reducer that consumes `JobEvent` directly —
  unrelated to `WorldProjection`/`ProductEvent`. It has its own test file
  (`event-reducer.test.ts`, 208 lines) and is actually mounted:
  `processing-workspace-live.tsx` uses it, and `ProcessingWorkspace` is
  rendered at two real Next.js routes, `app/workspace/page.tsx` and
  `app/documents/[id]/[view]/page.tsx` (both confirmed to exist on disk).
- **Collection plane**: on the Security/v5-cinematic lineage,
  `apps/web/src/components/v6/event-model.ts` (`V6VersionedEvent`, own test
  file `event-model.test.ts`, 220 lines) adapts `collection-runtime-client.ts`'s
  `CollectionEvent` via `v6-collection-events.ts`
  (`collectionEventsToV6`), consumed by the same
  `processing-workspace-live.tsx` / `collection-processing-theater.tsx`
  pairing, mounted at the same two routes.

**This means both backend planes already have a working, tested,
production-routed consumer path that does not go through `ProductEvent` at
all.** `ProductEvent`/`WorldProjection` is a *third*, newer integration
layer being built alongside two that already work. Neither this document
(through section 13) nor `I2_PRODUCT_EVENT_NORMALIZATION_CONTRACT.md`
identifies what real product surface actually *requires* `ProductEvent` —
i.e., why `event-reducer.ts` and `v6/event-model.ts` are insufficient and a
converging third layer is needed. This is `observed` as a gap in the
existing research, not `proven` as evidence that `ProductEvent` is
unnecessary — it may be needed for the cinematic renderer specifically, or
for a future unified product surface neither existing reducer serves, but
that consumer has not been identified in code by any research pass so far.

### 14.4 Additional producers not enumerated in §2 — `observed`

- Job plane: `services/api/src/akc_api/batch_api.py` also calls
  `emit_event()` (2 sites: `job.created.v1`, `credit.reserved.v1`);
  `main.py` itself calls `emit_event()` directly at 5 sites (not only via
  service-layer functions).
- Collection plane: `services/api/src/akc_api/collection_processing.py`
  also calls `_emit_collection_event()` (1 site).
- Re-confirmed, consistent with §2: the Product App worktree (`main`
  lineage) has no `collection_api.py` at all — its job-plane producers are
  `batch_api.py`, `services.py`, `main.py`, `scheduler.py` only.

### 14.5 Effect on the recommended architecture (§12) — `inferred`

This new evidence does not weaken or strengthen §B's coexistence finding.
It does add a precondition to §12's option-3 recommendation (two
plane-specific adapters converging into one `ProductEvent`) that neither
this document nor I2 currently satisfies: **before implementing that
convergence, identify the actual consumer that needs it.** If no such
consumer exists yet beyond a hypothetical future one, that's a legitimate
reason to build it — but it should be stated as "for future consumer X," not
left implicit. This is flagged for the founder/orchestrator to resolve, not
decided here.

### 14.6 What this addendum still does not resolve

- Which real product surface (existing or planned) actually needs
  `ProductEvent`/`WorldProjection`, given two working bypasses already
  exist.
- The remaining 5 of 8 "reused" `CollectionEventType` members' real
  emit-site payloads.
- Whether `event-reducer.test.ts` / `v6/event-model.test.ts` actually pass
  (file/assertion contents were read, not executed, this round).
- Whether anything changed on `origin/main` past `185d04b` relevant to the
  job-plane consumer path — only the local Product App worktree (`9e52a7d`)
  was checked.
- `job.event_sequence` vs. `collection.event_sequence` clock/transaction
  independence (carried forward from I2 §6, still unverified).

**Status: I1's core coexistence finding stands (`READY`/`RECONCILED` per the
M0 correction above). The canonical-boundary implementation question is
`STILL OPEN` — strengthened evidence, but a new precondition (identify
`ProductEvent`'s actual required consumer) surfaced that neither I1 nor I2
previously named.**
