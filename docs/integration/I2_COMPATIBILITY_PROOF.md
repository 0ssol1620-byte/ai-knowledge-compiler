# I2 — Compatibility Proof (implementation)

Status: **implemented in `apps/web/src/lib/product-event.ts` and
`world-projection.ts`**, this worktree only. This document is the
before/after evidence I2's design (`I2_PRODUCT_EVENT_NORMALIZATION_CONTRACT.md`)
called for in its §11 migration strategy, plus the negative proofs the
project's standing discipline requires: every acceptance test must be shown
capable of failing, not just shown passing.

---

## 1. What changed

`ProductEvent` gained a required discriminated `scope` field
(`{ kind: "job" | "collection" | "demo", ... }`, per the design's §1). The
legacy top-level `collection_id` became optional and is now normalized by
`parseProductEvent` rather than trusted from the raw frame: mirrored from
`scope.collection_id` for `"collection"`-scope events, deleted outright (not
set to `undefined`) for every other scope.

`WorldProjection.lastSequence: number` became
`lastSequenceByScope: Record<string, number>`, keyed by
`` `${scope.kind}:${identity}` ``. The idempotency check in
`reduceProductEvent` moved from one global counter to one cursor per scope
key, exactly as the design's §5 specified.

The per-event-type payload switch inside `reduceProductEvent` did not
change — the design's own prediction in §10 ("the per-event-type payload
switch statement itself does not need to change").

## 2. Files changed and why

| File | Change |
|---|---|
| `apps/web/src/lib/product-event.ts` | `EventScope`/`eventScopeSchema` added; `scope` added to the envelope (required); `collection_id` changed required→optional; `parseProductEvent` now normalizes scope (mirror/strip) as its last step. |
| `apps/web/src/lib/world-projection.ts` | `lastSequence: number` → `lastSequenceByScope: Record<string, number>`; `scopeKey()` helper added; `reduceProductEvent`'s idempotency check and cursor update are now scope-keyed. |
| `apps/web/src/lib/demo-workspace.ts` | Its `build()` helper (the only place this worktree constructs raw fixture events) now sets `scope: { kind: "demo" }` instead of the legacy `collection_id: DEMO_COLLECTION_ID` — required so the existing 29 `world-projection.test.ts` tests still parse against the new mandatory `scope` field. |
| `apps/web/src/lib/product-event.test.ts` | Its one shared `valid` fixture gained a `scope: { kind: "collection", collection_id: "col_sample_0001" }` field, for the same reason. |
| `apps/web/src/lib/product-event-scope.test.ts` | New. Cross-scope cursor independence + no-identity-fabrication tests. |
| `apps/web/src/lib/product-event-p1-compatibility.test.ts` | New. This document's test-form evidence. |

## 3. Test results

Baseline (this session, before any edit, `git stash` verified):

```
src/lib/product-event.test.ts        13 tests, 13 passed
src/lib/world-projection.test.ts     29 tests, 29 passed
                                      42 total, 42 passed
```

After implementation, same two files, unchanged:

```
src/lib/product-event.test.ts        13 tests, 13 passed
src/lib/world-projection.test.ts     29 tests, 29 passed
                                      42 total, 42 passed
```

Zero regressions and zero expectation rewrites in either file beyond the
`scope`/`collection_id` fixture edits named above — every assertion about
projection *behavior* (entity/relation/unit counts, lane derivation, recovery
scar counting, world-state activation, ask resolution) is byte-identical to
before.

New tests added, all passing:

```
src/lib/product-event-scope.test.ts             14 tests, 14 passed
src/lib/product-event-p1-compatibility.test.ts   5 tests,  5 passed
```

Combined targeted run:

```
$ npx vitest run src/lib/product-event.test.ts src/lib/world-projection.test.ts \
    src/lib/product-event-scope.test.ts src/lib/product-event-p1-compatibility.test.ts

 Test Files  4 passed (4)
      Tests  61 passed (61)
```

## 4. The negative proof: cross-scope contamination under the OLD design

`product-event-scope.test.ts`'s
`"would have been silently dropped by the pre-I2 single global cursor"` test
reconstructs the exact rule that lived in `world-projection.ts` before this
change — read directly from `git show HEAD` at the start of this session
(`HEAD` here being the commit this work started from, `838d9af`):

```ts
if (event.sequence <= state.lastSequence) return state;
// ...
lastSequence: event.sequence,
```

One counter, shared by every plane. The test feeds a job-scope event
(`sequence: 1`) and a collection-scope event (`sequence: 1`, unrelated
identity, unrelated plane) through that reconstructed rule and asserts the
second is dropped — `secondEventWasDropped === true`. It is: both events
share the numeric value 1, and the old rule only ever compared numbers, never
identities.

The very next test, `"applies both events under the new per-scope cursor"`,
feeds the identical two events through the real, current
`reduceProductEvent` and asserts the opposite: the collection event's
`files_discovered: 42` is actually applied
(`afterCollection.discovery.filesDiscovered === 42`), and both cursors are
recorded independently:

```ts
expect(afterCollection.lastSequenceByScope).toEqual({
  "job:job-abc": 1,
  "collection:coll-xyz": 1,
});
```

This is not a reasoning-only claim — the pre-change source line was read
directly (`git show HEAD:apps/web/src/lib/world-projection.ts`, confirmed
this session to read exactly `if (event.sequence <= state.lastSequence)
return state;`), and the reconstruction in the test uses that same rule
verbatim.

## 5. The negative proof: no identity fabrication

`product-event-scope.test.ts`'s `"no identity fabrication across scopes"`
suite (7 tests) proves, for a job-scope event:

- `event.collection_id === undefined` after parsing (not merely falsy —
  `Object.prototype.hasOwnProperty.call(event, "collection_id") === false`,
  so a caller's `"collection_id" in event` check cannot read `true`).
- The same holds even when a raw frame *tries* to attach a `collection_id` to
  a job-scope event (a simulated producer bug) — normalization strips it
  regardless of what the raw frame claimed.
- The same holds for `"demo"` scope.
- A `"collection"`-scope event, conversely, gets its legacy `collection_id`
  *mirrored* from `scope.collection_id` — including overriding a stale or
  mismatched top-level value the raw frame tried to carry, so the mirrored
  value is always derived from `scope`, never trusted from the wire directly.
- Both `"job"` and `"collection"` scope reject a frame missing their
  respective mandatory identity (`job_id` / `collection_id`) — the identity
  is enforced, not merely optional-and-usually-present.

## 6. Before/after compatibility proof for Product P1

Restated from `product-event-p1-compatibility.test.ts`'s own header comment:

**File identity, verified this session.** `diff -q` on
`apps/web/src/lib/{product-event.ts,world-projection.ts,demo-workspace.ts,demo-event-source.ts}`
between this worktree (`ai-knowledge-compiler-surface-integration`, this
change's target) and the Product App worktree
(`ai-knowledge-compiler-product-app`, HEAD `9e52a7d`, not modified by this
change) produced no output on all four files — they were byte-identical
before this implementation started.

**What Product App actually reads, verified read-only this session.**
`world-view-model.ts`'s `worldObjects()` reads `projection.entityIds` (`Set`
membership only). `demo-world-source.ts`/`product-world-context.tsx` and the
four P1 view pages read `.mode`, `.worldActive`, `.discovery`, `.lanes`,
`.recoveredPages`, `.relationIds`, `.unitIds`, `.worldState`,
`.sourceRevision`, `.conflictSubject`, `.resolution`, `.impact`, `.recompile`,
`.ask` — none of it reads `.lastSequence` or the top-level `.collection_id`
(this matches I2's own §11 post-M0-validated finding, cited not re-derived
here).

**BEFORE** (pre-I2 shape, same fixture, same event-type switch statement):
the compile stream produced `entityIds.length === DEMO_ENTITIES.length`
(12), `relationIds.length === DEMO_RELATIONS.length`, `worldActive === true`,
`mode === "demo"`, and a bare `lastSequence` equal to the stream length —
this is exactly what `world-projection.test.ts`'s pre-existing
`"reduceProductEvents — the compile stream"` suite already asserted, and
still asserts unchanged.

**AFTER** (this implementation): `product-event-p1-compatibility.test.ts`
runs the identical compile/change/ask streams — now carrying
`scope: { kind: "demo" }` on every event — through the new
`reduceProductEvents`, and asserts the same counts, the same `worldActive`,
the same `worldState` before/after shape on the CHANGE act, and the same
`ask.resolved` status ordering. All five assertions pass. The cursor
equivalent of the old `lastSequence` is confirmed present and correct at its
new address: `lastSequenceByScope["demo:*"] === compileEvents.length`.

**Conclusion:** for the specific fields Product App's P1 slice consumes, the
new `scope`/`lastSequenceByScope` shape is behaviorally equivalent to the
old shape. Product App's own worktree was not modified and was not run
against this change — this is a proof by fixture equivalence plus verified
file identity and verified read-set, not an integration test against the
live Product App code.

## 7. Known, deliberate exclusion: `live-event-adapter.ts` and its tests

Per this task's hard constraints, `apps/web/src/lib/live-event-adapter.ts`,
`live-event-adapter.test.ts` and `product-event.contract.test.ts` were not
touched. All three were already broken at the session's start — a `git
stash` baseline check (this session) showed
`live-event-adapter.test.ts` + `product-event.contract.test.ts` combined ran
46 tests with 11 already failing, entirely due to
`Module '"@akc/contracts"' has no exported member 'COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS'`
— a pre-existing, unrelated breakage (I0-B is still blocked on I1's
still-open canonical-model question).

**This implementation adds 14 more failures to that same pair of files**,
because `live-event-adapter.ts`'s `adaptCollectionEvent()` constructs a
`ProductEvent` candidate object with no `scope` field, and `scope` is now
required — so every event it builds fails `parseProductEvent` and the
adapter now reports `undefined` for cases it previously mapped successfully.
Verified: same `git stash` baseline check, before/after test-name diff,
35 passed → 21 passed within those two files (46 tests total either way).

This is a real, measured side effect of a shared-file change on files this
task explicitly forbade editing to fix. It is not silently absorbed: **I2's
own §11 already names this exact risk** — "any existing code that reads
`collection_id` as always-present would break" — and `live-event-adapter.ts`
is precisely that kind of not-yet-migrated consumer, now additionally
missing the newly-mandatory `scope` field it has no way to supply without
being edited. The task's explicit compatibility requirement is scoped to
`product-event.test.ts` (13) and `world-projection.test.ts` (29), not to
these three I0-B files, and those 42 are unaffected. Fixing
`live-event-adapter.ts` to emit `scope` is the natural next step once I1's
canonical-model question unblocks I0-B — it is out of this task's scope to
do it here.
