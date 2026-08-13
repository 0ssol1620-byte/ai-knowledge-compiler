# INTEGRATION I0 — Shared World Contract Promotion

Status: **PARTIAL — semantic conflict found, founder decision needed.**

This document records what was promoted from the V5 cinematic lineage onto
this Integration branch (`agent/tavonel-surface-integration`, based on clean
`main` @ `7ac5098`), what was proven against real `main` state, and — the
part that must not be glossed over — what could **not** be honestly proven
because the backend module the promoted code was written against does not
exist on `main`.

## 1. Provenance

- `ProductEvent`, `LiveEventAdapter`, `WorldProjection` entered the codebase
  in V5 foundation commit `270875e` on worktree
  `D:\CodexProjects\ai-knowledge-compiler-v5-cinematic`
  (branch `agent/tavonel-v5-cinematic`), and received correctness/boundary
  fixes in `f042563` on the same branch. Current head there: `3d2cb8c`.
- Cinematic V2 (`D:\CodexProjects\ai-knowledge-compiler-cinematic-v2`,
  branch `agent/tavonel-cinematic-v2`) inherited these three files
  unchanged. Verified directly in this session:

  ```
  git diff 3d2cb8c HEAD -- apps/web/src/lib/product-event.ts \
                           apps/web/src/lib/live-event-adapter.ts \
                           apps/web/src/lib/world-projection.ts
  ```

  produced **zero lines of output** in the cinematic-v2 worktree — confirming
  the founder's zero-diff claim for the three contract files.
- `demo-event-source.ts` was also zero-diff between the two branches.
  `demo-workspace.ts` was **not** zero-diff: Cinematic V2 reassigned three
  `originIndex` fixture values (fixture-only bookkeeping, not wire data) to
  satisfy a Cinematic V2 Director-Bible acceptance clause
  (`graph-director.test.ts`, §16 test 2 / C02 acceptance #3). That edit is
  presentation-track-specific and was **not** brought across. This branch
  sources `demo-workspace.ts` from the V5 copy (`3d2cb8c`), which carries no
  cinematic-only references.

## 2. Promoted files

Contract layer (production code, zero presentation dependencies):

- `apps/web/src/lib/product-event.ts`
- `apps/web/src/lib/live-event-adapter.ts`
- `apps/web/src/lib/world-projection.ts`

Tests:

- `apps/web/src/lib/product-event.test.ts`
- `apps/web/src/lib/product-event.contract.test.ts`
- `apps/web/src/lib/live-event-adapter.test.ts`
- `apps/web/src/lib/world-projection.test.ts`

Fixture/synthetic (explicitly **not** contract semantics, per §5 of the
dispatch):

- `apps/web/src/lib/demo-event-source.ts` — `DemoFixtureEventSource`, a demo
  replay source implementing `ProductEventSource`. Self-contained; imports
  only `@/lib/demo-workspace` and `@/lib/product-event`.
- `apps/web/src/lib/demo-workspace.ts` — sample-world fixture data (entities,
  relations, a scripted `DEMO_COMPILE_STREAM`). Self-contained; imports only
  `@/lib/product-event`. Every figure in it is invented for the landing page,
  as its own header comment states — not a measurement, not backend truth.

New dependency: `apps/web/package.json` gained
`"@akc/contracts": "workspace:*"` under `dependencies` (matching V5's own
placement) — required because `product-event.contract.test.ts` and
`live-event-adapter.test.ts` import from it. This package already exists on
`main` (`packages/contracts`); only the dependency edge from `apps/web` is
new. No backend/API code, schema, or migration was touched to add it.

## 3. THE CONFLICT — backend event module mismatch

**This is the semantic conflict the dispatch's stop condition names, and it
blocks proof items 2, 3 (partially), 6 (partially) and 7 (partially) below
from being honestly claimed as passing.**

`LiveEventAdapter`'s own header comment says it mirrors
`CollectionEvent.Root` in `@akc/contracts`, and its correlation logic is a
transcription of `validate_collection_event_payload` in
`akc_cir.collection_events`. `product-event.contract.test.ts` and
`live-event-adapter.test.ts` both import
`COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` and `CollectionEventType` from
`@akc/contracts` to build backend-shaped fixtures and cross-check the
adapter's field requirements against the generated contract.

That module does not exist on `main`:

- `packages/cir-python/src/akc_cir/collection_events.py`
  (`class CollectionEventType(StrEnum)`, collection/source-root-keyed events
  such as `collection.discovery.progress.v1`, `file.discovered.v1`, etc.)
  was introduced in commit `d7a6b30` ("feat: complete Structara v4 and v6
  platform", 2026-08-01).
- **`d7a6b30` is not an ancestor of `main`.** Verified directly:

  ```
  git merge-base --is-ancestor d7a6b30 7ac5098 && echo yes || echo no
  → no
  ```

  It is only reachable from divergent branches: `agent/tavonel-v5-cinematic`,
  `agent/tavonel-cinematic-v2`, `agent/folynta-trust-integration-v1`,
  `agent/tavonel-absorption-research`, `agent/tavonel-ip-research`, and
  others — never `main`.
- `main`'s actual, real backend real-time event system is a different module:
  `packages/cir-python/src/akc_cir/events.py`, `class EventType(StrEnum)`
  inside `ProcessingEvent` — job/project-keyed
  (`project_id`, `job_id`, `tenant_id`, `document_id`, `page_id`), not
  collection/source-root-keyed. Its event vocabulary
  (`job.created.v1`, `job.stage.progress.v1`, `page.preflight.completed.v1`,
  `page.completed.v1`, `credit.reserved.v1`, …) overlaps with
  `ProductEvent`'s `REUSED_EVENT_TYPES` in exactly **one** name —
  `page.route.selected.v1` — appearing in both `EventType` and
  `CollectionEventType`, with no evidence the two share a payload shape (this
  was not further audited; doing so would be scoping in backend work this
  promotion is not authorized to touch).
- Correspondingly, `packages/contracts/src/generated-contracts.ts` on `main`
  is 111 lines with no `COLLECTION_EVENT_TYPES` /
  `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` export; the V5 branch's
  generated file (376 lines) has both, because it was generated from V5's
  own (unpromoted) `collection_events.py`.

**Consequence, stated plainly:** `LiveEventAdapter` as promoted is a
translation from a backend event shape (`akc_cir.collection_events`) that
does not exist on `main`. It has never been run against `main`'s actual
event producer (`akc_cir.events`), and nobody has checked whether its
mapping logic is even applicable to that module's payloads. The adapter's
*internal* logic (fail-closed behavior, refusal to fabricate, correlation
checks, the Page-0 regression fix) is sound and independently testable
against literal fixtures — but the claim "this bridges the real backend" is
unproven on this branch, and this promotion does not attempt to resolve
that by rewriting the adapter against `akc_cir.events.EventType` or by
inventing a shim. That decision — which backend module `LiveEventAdapter`
should actually target, and whether `akc_cir.collection_events` should be
promoted to `main` in its own right — is not this promotion's call.

## 4. Fixture-only vs. backend-supported `ProductEvent` audit

Per the dispatch, this audits `ProductEvent`'s union against what a real
backend actually emits. Given §3 above, "backend-supported" now has to be
read carefully: `REUSED_EVENT_TYPES` was checked against
`akc_cir.collection_events` (V5-only, not on `main`), not against `main`'s
real `akc_cir.events`. The table below preserves that original classification
(as measured by `product-event.contract.test.ts`'s intent) but the right-hand
column states what is actually true **on `main` today**.

| `ProductEvent` type | V5 classification (`REUSED_EVENT_TYPES`) | True status on `main` |
|---|---|---|
| `collection.discovery.progress.v1` | reused from `akc_cir.collection_events` | **no such backend module on `main`** |
| `file.discovered.v1` | reused | **no such backend module on `main`** |
| `file.duplicate.detected.v1` | reused | **no such backend module on `main`** |
| `page.route.selected.v1` | reused | name coincides with `akc_cir.events.EventType.PAGE_ROUTE_SELECTED` on `main`; payload shape unverified |
| `verification.failed.v1` | reused | **no such backend module on `main`** |
| `recovery.completed.v1` | reused | **no such backend module on `main`** |
| `entity.resolved.v1` | reused | **no such backend module on `main`** |
| `relation.created.v1` | reused | **no such backend module on `main`** |
| `revision.family.detected.v1`, `document.profiled.v1`, `document.rerouted.v1`, `knowledge.unit.created.v1`, `conflict.detected.v1`, `authority.resolved.v1`, `source.revision.created.v1`, `world_state.activated.v1`, `impact.detected.v1`, `recompile.progress.v1`, `recompile.completed.v1`, `answer.resolution.started.v1`, `answer.source.resolved.v1`, `answer.emitted.v1` | `PROPOSED_EVENT_TYPES` — fixture/proposed-only, no producer, by the code's own declaration | **still fixture/proposed-only; nothing on `main` changes this.** Do not treat any of these as backend-supported. |

Bottom line: **none of the 22 `ProductEvent` types in the union are
demonstrably backend-supported on `main` today.** The 8 "reused" types were
reused from a backend module that itself never reached `main`; the other 14
were fixture-only even on the branch that invented them. This promotion does
not remove or relabel any of them — the union is preserved exactly — but no
one should read `REUSED_EVENT_TYPES` as "these are safe to treat as live" on
this branch without first resolving §3.

## 5. Promotion-proof results

Command used (from `apps/web/`, after `pnpm install` and building
`packages/contracts` with `pnpm build`):

```
npx vitest run src/lib/product-event.test.ts \
                src/lib/product-event.contract.test.ts \
                src/lib/live-event-adapter.test.ts \
                src/lib/world-projection.test.ts
```

Result: **4 test files, 88 tests total — 77 passed, 11 failed.**
(`product-event.test.ts`: 13/13 pass. `world-projection.test.ts`: 29/29
pass. `live-event-adapter.test.ts`: 34/43 pass, 9 fail.
`product-event.contract.test.ts`: 1/3 pass, 2 fail.)

Mapped to the 9 required proof items:

1. **`ProductEvent` schema/contract tests pass** — **PARTIAL.**
   `product-event.test.ts` (schema validation, envelope, unions): 13/13
   PASS. `product-event.contract.test.ts` (cross-check against the backend's
   collection-event contract): 1/3 pass. The 2 failures
   (`reuses eight names the backend already defines`,
   `diverges from that contract in exactly the recorded places`) are both
   `TypeError: Cannot read properties of undefined`, because
   `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` does not exist in `main`'s
   `@akc/contracts` build — direct consequence of §3. **BLOCKED.**
2. **Adapter mapping tests pass** — **BLOCKED.** The 8
   `<type>: real payload → adapter → ProductEvent` tests in
   `live-event-adapter.test.ts` each fail at the same line
   (`COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS[type]` on `undefined`) before
   they can assert anything about the adapter's mapping behavior. These are
   the tests that were supposed to prove the mapping against real backend
   payload shapes; they cannot run.
3. **Unknown/unmappable backend events do not fabricate output** — **PASS.**
   `describe("the adapter refuses rather than invents")` — drops a frame
   missing a required field (with reason), refuses an unverified recovery,
   names a fixture-only type as having no producer, rejects a non-envelope
   frame. None of these four tests touch `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS`
   and all pass.
4. **Missing page locator never synthesized as "Page 0"** — **PASS.**
   `describe("third-audit finding 2: a page is named only when the event
   carried one")` — all pass, including the regression case (pageless
   `page.route.selected.v1` / `verification.failed.v1` /
   `recovery.completed.v1` frames produce `pageNumber: undefined` and a line
   that never contains "Page 0"). The fix this test pins is present and
   proven — it was already true against literal fixtures and did not depend
   on the missing generated contract.
5. **At-least-once replay is idempotent in `WorldProjection`** — **PASS.**
   `describe("at-least-once delivery")` in `world-projection.test.ts`: a
   redelivered event is a no-op (`reduceProductEvent` returns the identical
   object reference), and a redelivered `entity.resolved.v1` does not
   double-count. Both pass.
6. **Live adapter and demo source converge on the same downstream
   `ProductEvent` → projection path** — **PARTIAL / weak pass.** The test
   `"feeds the same projection the fixture path feeds"` passed — it drives
   `adaptCollectionEvent` with locally-built fixture frames and confirms the
   resulting `ProductEvent`s reduce correctly. But because that test builds
   its own frames rather than validating them against
   `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` first, it only proves internal
   consistency (adapter output → projection), not that those frames resemble
   anything a real backend emits. Given §3, no test in this suite can prove
   that today.
7. **Collection/job correlation checks remain intact** — **PARTIAL.**
   `describe("third-audit finding 1: identity fields the producer
   requires")` — 8 of 9 tests pass, including the actual security-relevant
   assertions (payload with no collection identity refused, wrong-typed
   collection identity refused, payload job under null/absent envelope job
   refused, job-correlated type with no job refused, untouched frames still
   adapt). The 1 failure —
   `"requires a job for exactly the types the generated contract requires
   one for"` — is the test that cross-checks `JOB_CORRELATED_TYPES` against
   `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` and fails for the same §3
   reason. The adapter's own refusal behavior is proven; the claim that its
   hardcoded `JOB_CORRELATED_TYPES` set exactly matches a real backend
   contract is not.
8. **No backend event/schema/migration changed** — **CONFIRMED.** This
   promotion touched only `apps/web/src/lib/*`, `apps/web/package.json` (one
   new dependency line), and this doc. `git status` on this branch shows no
   changes under `services/api/`, `packages/cir-python/`, or any migration
   directory.
9. **No presentation dependency in the shared contract layer** — **CONFIRMED.**
   `product-event.ts`, `live-event-adapter.ts`, and `world-projection.ts`
   import only `zod` and each other. Read directly, none references
   `three`, `@react-three/fiber`, `@react-three/drei`, GSAP, or any component
   module. `demo-event-source.ts` and `demo-workspace.ts` likewise import
   only `@/lib/product-event` (and each other).

## 6. What was and was not committed

Per the coordinator's correction, this promotion does **not** claim
`INTEGRATION I0 READY`, and does not commit `LiveEventAdapter` as though the
conflict in §3 were resolved. One commit was made on this branch,
`eb26ba7` ("feat(integration): promote ProductEvent and WorldProjection as
shared contract"), containing only the subset that is genuinely, honestly
proven independent of the conflict:

- `apps/web/src/lib/product-event.ts` + `product-event.test.ts` (13/13 pass,
  no `@akc/contracts` dependency)
- `apps/web/src/lib/world-projection.ts` + `world-projection.test.ts`
  (29/29 pass, including at-least-once idempotency; no `@akc/contracts`
  dependency)
- `apps/web/src/lib/demo-event-source.ts` + `demo-workspace.ts` (fixtures
  `world-projection.test.ts` exercises; self-contained, no `@akc/contracts`
  or presentation dependency)
- this document

**Left uncommitted, present in the worktree only, as untracked files:**

- `apps/web/src/lib/live-event-adapter.ts`
- `apps/web/src/lib/live-event-adapter.test.ts`
- `apps/web/src/lib/product-event.contract.test.ts`

These three are exactly the files whose tests require
`COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` / `CollectionEventType` from
`@akc/contracts`, i.e. exactly the files blocked by §3. The
`"@akc/contracts": "workspace:*"` dependency edit that was temporarily added
to `apps/web/package.json` to prove this (and the resulting `pnpm-lock.yaml`
change) was **reverted** before committing, since the committed subset does
not need it — re-add it only once §3 is resolved and `LiveEventAdapter` is
ready to be promoted for real.

## 7. Open question for the founder

Which of these should the Product App track (and this Integration branch)
actually build against:

- **(a)** Promote `akc_cir.collection_events` (currently only reachable via
  `d7a6b30` on non-`main` branches) to `main` as a real backend module, so
  `LiveEventAdapter` as written becomes provable, or
- **(b)** Rewrite `LiveEventAdapter` to target `main`'s actual
  `akc_cir.events.EventType` / `ProcessingEvent` contract, which is a
  different keying scheme (`project_id`/`job_id` vs.
  `collection_id`/`source_root_id`) and a different event vocabulary, or
- **(c)** Something narrower — e.g. promote only the `ProductEvent` /
  `WorldProjection` half now (they do not depend on this conflict) and leave
  `LiveEventAdapter` for a follow-up once (a) or (b) is decided.

No backend code was touched and no shim was invented while this was
unresolved.
