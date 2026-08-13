# I2 — Product Event Normalization Contract (design proposal)

Status: **design only, not implemented**. This document proposes a discriminated
scope contract for `ProductEvent` to replace the current unconditional
`collection_id` requirement, per the founder's decision that `ProductEvent`
remains the single normalization boundary above multiple coexisting backend
event planes (job plane and collection plane — see
[`I1_CANONICAL_BACKEND_EVENT_RECONCILIATION.md`](I1_CANONICAL_BACKEND_EVENT_RECONCILIATION.md)).

This document builds directly on I0 and I1 and does not re-derive or
contradict their findings — it cites them. Every claim below is tagged
`observed` / `proven` / `inferred` / `proposed`, same discipline as I0/I1.

Implementation of the new plane adapters is explicitly **not** authorized by
this document — the founder gated that on a parallel `M0` task (mainline and
migration ancestry reconciliation), which determines which backend lineage is
actually converging into `main`.

---

## Grounding

- `apps/web/src/lib/product-event.ts` (`observed`): the current envelope is
  `schema_version, event_id, sequence, occurred_at, collection_id (required),
  mode, document_id?, page_number?`. `collection_id` is non-optional.
- `apps/web/src/lib/world-projection.ts` (`observed`): `reduceProductEvent`
  drops any event where `event.sequence <= state.lastSequence` — a single
  global integer counter, no per-plane namespacing. `mode: "demo" | "live" |
  "idle"` already exists on the projection.
- Product App's `demo-world-source.ts` / `product-world-context.tsx`
  (`observed`, read-only from the Product App worktree): `createSampleWorldSource()`
  already wraps `DemoFixtureEventSource` behind a `ProductEventSource`
  interface intended for a future `LiveProductEventSource` swap.
  `continueSchedule()` already re-offsets `sequence` numbers when combining
  multiple scripted streams into one projection — an existing precedent for
  exactly the "two sources' sequence numbers aren't directly comparable"
  problem this document addresses in §5.
- I1's already-proven findings, cited not re-derived: job plane and
  collection plane coexist as different abstraction levels (`proven`, I1 §2);
  `main` has no `akc_cir.collection_events` at all (`proven`, I1 §1/§4);
  `@akc/contracts` is 111 lines on `main` (no event types) vs. 376 lines on
  the V5/cinematic-v2/Security lineage (`CollectionEventType` only —
  `EventType` is generated nowhere) (`observed`, I1 §5); none of
  `ProductEvent`'s 22 union members are currently produced by any real
  backend, and 8 "reused" names have proven payload mismatches
  (`proven`, I1 §7–8).

---

## 1. Plane discriminator (`proposed`)

Add a discriminator to the envelope, `scope`:

```ts
type EventScope =
  | { kind: "job"; job_id: string; document_id?: string; page_number?: number }
  | { kind: "collection"; collection_id: string; job_id?: string }
  | { kind: "demo"; fixture_id?: string };
```

The third `"demo"` kind is justified: `DemoFixtureEventSource` already
exists, and rather than forcing fixture-originated events to fabricate a
`job_id` or `collection_id` to satisfy validation, an honest third scope
keeps `CLAUDE.md`'s "no silent fallback / never invent data" rule intact at
the type level.

`scope.kind` and the existing `mode: "demo" | "live"` field are **orthogonal
axes**, not the same thing: `mode` says whether an event came from a live
backend or a replayed fixture; `scope.kind` says which backend-plane shape
the event's identities follow. A demo fixture can legitimately impersonate a
`"job"`-shaped or `"collection"`-shaped event, or be pure `"demo"`-shaped
invented data — the combination lets a consumer distinguish "this fixture
mimics a real job-plane event" from "this fixture is purely illustrative,"
without touching Product App's existing `mode`/`label` API (§4, §11).

## 2. Mandatory identities by plane (from I1 §6a/§6b, `observed`)

- **`scope.kind === "job"`**: `job_id` required — real field on
  `JobEvent`/`ProcessingEvent`. `document_id` / `page_number` optional (not
  reliably present per event type). `collection_id` is **structurally
  absent** — must never be required or fabricated for this scope.
- **`scope.kind === "collection"`**: `collection_id` required — real field on
  `CollectionEvent`. `job_id` optional (nullable column, real but not always
  populated).
- **`scope.kind === "demo"`**: no identity required — fixture data by
  definition.

## 3. Optional identities and why

- Job plane's `document_id`/`page_number`: I1 found these aren't reliably
  present per event type (`observed`) — mandatory would force adapters to
  fabricate them, which is prohibited.
- Collection plane's `job_id`: nullable in the real schema — present it
  gives a trustworthy correlation hint to the job plane; absent doesn't
  invalidate the event.
- `tenant_id` is **excluded from the envelope entirely** on both planes (I1:
  "unavailable — no tenant field at all," `observed`) — this preserves the
  existing design that `ProductEvent` sits outside the authorization
  boundary; the document explicitly states `ProductEvent` must never be used
  for authorization decisions (ties to §7).

## 4. Source provenance vs. `mode`

`mode` (`"demo" | "live"`) already flows from `ProductEventSource` through to
`ProductWorldContextValue.mode` (`observed`, Product App's
`product-world-context.tsx`) — this document proposes **no change** to that
API. `scope` is a new event-level field, not a context-level API, so
Product App's existing P1 consumption is unaffected by this axis alone
(interacts with `collection_id` migration concerns in §11).

## 5. Sequence / idempotency across planes (`proposed`, the central design problem)

`reduceProductEvent` currently keys idempotency off a single global
`lastSequence: number` (`observed`, `world-projection.ts`). Two backend
planes converging breaks this: job-plane `sequence` (per-job monotonic) and
collection-plane `sequence` (per-collection monotonic) are **different
counter spaces** and not comparable (`inferred` from I1 §2/§9).

Proposal: replace the single counter with a per-scope cursor map:

```ts
lastSequenceByScope: Record<`${EventScope["kind"]}:${string}`, number>;
// e.g. "job:job-abc" → 42, "collection:coll-xyz" → 7, "demo:*" → 190
```

Idempotency check becomes `event.sequence <= (lastSequenceByScope[scopeKey] ?? 0)`,
scoped per plane+identity. This generalizes what `demo-world-source.ts`'s
`continueSchedule()` already does by hand (manually re-offsetting `sequence`
to merge multiple scripted streams into one global counter) — with per-scope
cursors, that workaround becomes unnecessary. This is a breaking change to
`WorldProjection`'s shape (§10, §11).

## 6. Event timestamp semantics (`proposed`)

`occurred_at` maps as exact/ISO on both planes (I1 §6a/§6b), but which clock
produced it is unverified — job-plane and collection-plane events are
written by different processes (scheduler vs. collection API), so clock
skew is possible (`inferred`, not directly verified this session).

Proposal: `WorldProjection` must **never reorder by `occurred_at`**. Within
a scope, `sequence` is the sole ordering authority; across scopes, events
interleave in arrival order only (whenever each source's `attachSource` call
delivers them). `occurred_at` is display-only, never a sort key. This means
a job event can visibly "arrive after" the collection event that summarizes
it without breaking anything, because each axis only orders its own data.

## 7. Fields unsafe to infer (carried forward from I1, not re-derived)

- `tenant_id` — absent on both planes; never invented, never added to the
  envelope (I1 §6a/§6b).
- Attaching `collection_id` to a job-plane event — fabricating a
  structurally absent field; prohibited (I0 "never invent data," I1 §6a).
- World-state/authority identity (e.g. `world_state_id`) — absent from both
  backends; stays fixture-only in `PROPOSED_EVENT_TYPES` (I1 §7).
- `route_label`/`attempt` payload shape — I1 marked this "unproven" at the
  emit-site level for both planes; **this discriminated-union design does
  not solve that** — scope tagging fixes identity correctness, not payload
  verification. That remains open work (see the contract-generation-gap
  recommendation below).

## 8. Backend-supported vs. fixture/proposed event types

| Plane | Backend-claimed (name matches; payload unverified/mismatched) | Fixture/proposed only |
|---|---|---|
| job (`EventType`) | `page.route.selected.v1` (name matches across both planes; payload unverified) | remaining ~21 |
| collection (`CollectionEventType`, absent from `main`) | 8 "reused" types (name matches; payload proven mismatched, I1 §7–8) | remaining ~14 |
| demo | none by definition | all 22 — currently the only source that actually emits any of them |

## 9. Mapping loss

Both planes lose `tenant_id`, world-state/authority identity, and a typed
evidence locator (`SourceRef`) (I1 §6a/§6b/§11-D, cited not re-derived). Job
plane structurally loses `collection_id` — the discriminated-union design
makes this loss **visible at the type level** instead of hidden behind a
required-but-sometimes-empty field, which is the main correctness gain of
this proposal. Collection plane loses most fields of the 8 reused types
(I1 §6b table). Whether this loss is acceptable is a product decision for
the founder, not re-litigated here.

## 10. `WorldProjection` compatibility

**Change required** (`proposed`): `lastSequence: number` becomes
`lastSequenceByScope` (§5), and the line that currently reads only
`event.mode` must also branch on `event.scope`. The per-event-type payload
switch statement itself does **not** need to change — `scope` is an
envelope-level addition, so each existing `case` in `reduceProductEvent` is
reusable as-is. In short: payload shape can be absorbed at the adapter
layer, but the sequence-cursor structure cannot be hidden from
`WorldProjection` — it's a real, not cosmetic, change to that file.

## 11. Migration / backward-compatibility strategy (central risk)

Product App (separate worktree, commit `a4828b8`, P1 vertical slice) already
consumes the **current** shape (`collection_id` required, single
`lastSequence`) and is explicitly required to stay `READY` and undisturbed.
This document does not modify that worktree; the following is a proposed
path, not a completed migration.

- Changing `collection_id` from required to scope-conditional is a
  **breaking change** for any code that reads `event.collection_id` directly
  at the top level. ~~Whether Product App's current components do this was
  not verified this session~~ **UPDATE (post-M0 validation pass,
  2026-08-13): verified — `proven`, not `inferred`.** A full grep of the
  Product App worktree (schema/producer/consumer files and all four P1 view
  pages) found `collection_id` referenced only at its own schema definition
  (`product-event.ts:160`) and inside the demo fixture's own
  event-construction code (`demo-workspace.ts`, a **producer**, not a
  consumer). `reduceProductEvent` — the only place `ProductEvent` fields are
  actually consumed to build state — never reads `event.collection_id`, and
  none of the four view pages or their layouts reference it at all. This
  **confirms `no consumer`**, not merely "optional consumer" — no code in
  Product App today would break if `collection_id` moved into the
  discriminated `scope` field. The additive-rollout strategy below remains
  prudent for future consumers but is not load-bearing for Product App's
  current compatibility.
- Proposed strategy: **additive rollout**. Keep the existing top-level
  `collection_id` field, mark it deprecated, and introduce `scope`
  alongside it. Adapters mirror the value onto both `scope.collection_id`
  and the legacy top-level field when `scope.kind === "collection"`, so both
  shapes coexist for one release. For `scope.kind === "job"` frames, the
  adapter does **not** synthesize a top-level `collection_id` — this is the
  point where any existing code that reads `collection_id` as always-present
  would break, and that risk is stated here explicitly rather than hidden.
- The `lastSequence` → `lastSequenceByScope` change **is** a breaking change
  to `EMPTY_PROJECTION`'s shape and to `world-projection.test.ts`'s 29
  existing passing tests. Because `product-event.ts`/`world-projection.ts`
  are already-promoted I0-A files, this change must go through
  `CLAUDE.md`'s Protected Core ladder — compatibility contract → shadow →
  benchmark → canary — not a direct edit. That ladder is out of scope for
  this design document; it belongs to the implementation phase, gated on M0.

## Contract generation gap — recommendation

I1 §5 found `main`'s `akc_cir.events.EventType`/`JobEvent` has **no**
generated frontend contract on any branch, including the branches that do
generate `CollectionEventType`. The frontend's `JobEventType` is hand
maintained with no sync mechanism.

**Recommendation (`proposed`):** keep the Python side
(`akc_cir.events.EventType`/`ProcessingEvent`, and `collection_events.py` if
promoted) as the source of truth, and extend `packages/contracts`'s existing
codegen pipeline — the one already producing `CollectionEventType` at 376
lines — to also cover `akc_cir.events`, generating
`JOB_EVENT_TYPES`/`JOB_EVENT_REQUIRED_PAYLOAD_FIELDS` the same way. Then add
a `job-event.contract.test.ts` parallel to the existing
`product-event.contract.test.ts` so the job plane gets the same payload-shape
verification rigor the collection plane already has (this generalizes I1's
own closing recommendation). The exact generator script/mechanism was not
inspected this session (see Unresolved).

---

## Unresolved / not verified this session

- ~~Whether Product App's `demo-workspace.ts` or its components reference
  `ProductEvent.collection_id` at the top level anywhere~~ **RESOLVED by a
  post-M0 validation pass (2026-08-13): no consumer anywhere in Product App.
  See the updated §11 above.**
- The real emit-site payload for `EventType.PAGE_ROUTE_SELECTED` /
  `CollectionEventType.PAGE_ROUTE_SELECTED` — inherited as "unproven" from
  I1, not re-verified here.
- Whether `job.event_sequence` and `collection.event_sequence` are actually
  written from different clocks/transactions (the basis for the §6 skew
  caution) — not directly compared in code this session.
- The exact `packages/contracts` codegen script/mechanism (name, invocation)
  — neither I1 nor this document opened it directly.

## Post-M0 validation pass (2026-08-13)

`M0_MAINLINE_MIGRATION_RECONCILIATION.md` landed after this document was
first written. A short validation pass confirmed, by reading M0 in full,
that M0 is entirely about Alembic migration-ancestry reconciliation and does
not examine `CollectionEvent`'s column list, the job/collection event-plane
split, or `ProductEvent`'s envelope shape — that remains I1's territory,
which M0 explicitly does not re-derive or contradict. **M0 does not change
this document's `scope` field design or its producer/persistence picture.**

One stale-citation note surfaced by the same pass, not a correction to this
document's content: this document cites I1's `collection_events`/
`CollectionEventType` findings (§Grounding, §8), and I1 in turn originally
described the Security branch's migration ancestry as unresolved — a claim
M0 later proved stale (see I1's own "M0 CORRECTION" block). This document
does not repeat that specific stale claim, so no correction is needed here,
but future revisions citing I1 should cite its corrected state.

## Note on section labeling

The dispatch brief referred to "I1's field matrix §D." I1's document does
not have a section literally labeled §D — the closest matches are I1 §6
(payload field matrix, `observed`+`inferred`) and I1 §11 (lettered A–E
answers, where D covers information loss). This document treats I1 §6 as
the field matrix and I1 §11-D as the mapping-loss answer; both are cited
above (§2, §9) under those actual section numbers.
