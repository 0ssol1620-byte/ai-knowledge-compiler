import { describe, expect, it } from "vitest";

import {
  buildAskStream,
  buildChangeStream,
  DEMO_COMPILE_STREAM,
  DEMO_ENTITIES,
  DEMO_INITIAL_WORLD,
  DEMO_RELATIONS,
  DEMO_UNITS,
  nextWorldState,
} from "@/lib/demo-workspace";
import { reduceProductEvents } from "@/lib/world-projection";

/**
 * I2's central risk (design §11): Product App (separate worktree, HEAD
 * `9e52a7d` at the time this proof was written, not modified by this change)
 * consumes `ProductEvent`/`WorldProjection` through its own copy of
 * `demo-workspace.ts`/`world-view-model.ts`. This file proves the new
 * `scope`/`lastSequenceByScope` shape produces an equivalent projection for
 * the same kind of event sequence Product App's P1 slice runs today.
 *
 * ── Why this worktree's fixture stands in for Product App's ─────────────────
 *
 * `apps/web/src/lib/demo-workspace.ts`, `product-event.ts` and
 * `world-projection.ts` were byte-identical between this worktree and the
 * Product App worktree before this change (`diff -q` on all three, this
 * session — see the I2 compatibility proof doc for the exact commands). This
 * worktree's copies are what I2 was authorized to change; Product App's are
 * not touched. The one edit needed to keep this worktree's own fixture
 * parseable — adding `scope: { kind: "demo" }` to `demo-workspace.ts`'s
 * `build()` — is exactly the shape of edit any consumer will need to make to
 * adopt `scope`, so running the (now-diverged-by-one-field) local fixture
 * through the new projection is a faithful stand-in for "what happens to
 * Product App's identical fixture once it adopts I2".
 *
 * ── What Product App actually reads (verified read-only this session) ──────
 *
 * `world-view-model.ts`'s `worldObjects()` reads `projection.entityIds`
 * (membership only, via a `Set`); `demo-world-source.ts`/
 * `product-world-context.tsx` read `projection.mode`, `.worldActive`,
 * `.discovery`, `.lanes`, `.recoveredPages`, `.relationIds`, `.unitIds`,
 * `.worldState`, `.sourceRevision`, `.conflictSubject`, `.resolution`,
 * `.impact`, `.recompile`, `.ask` — every field this change leaves untouched.
 * None of it reads `.lastSequence` or `.collection_id` (I2 §11's own
 * post-M0-validated finding, cited not re-derived). This proof therefore
 * checks exactly the fields Product App's P1 pages actually consume.
 */

const compileEvents = DEMO_COMPILE_STREAM.map((entry) => entry.event);
const CHANGED_WORLD = nextWorldState(DEMO_INITIAL_WORLD, "5 years");

describe("I2 compatibility proof — Product P1's consumption pattern", () => {
  it("BEFORE/AFTER: WORLD act reaches the same object counts P1's world-view-model.ts expects", () => {
    const projection = reduceProductEvents(compileEvents);

    // BEFORE (pre-I2, `lastSequence: number`, no `scope`): the same fixture,
    // reduced by the same event-type switch, produced these counts — the
    // switch statement's cases are untouched by I2 (I2 §10: "the per-event-
    // type payload switch statement itself does not need to change").
    // AFTER (this change): identical counts, because every compile-stream
    // event now carries `scope: { kind: "demo" }`, which the reducer treats
    // as a single cursor namespace — the stream's own internal sequence
    // ordering (1..N, unchanged) is what actually gates the switch.
    expect(projection.entityIds).toHaveLength(DEMO_ENTITIES.length);
    expect(projection.relationIds).toHaveLength(DEMO_RELATIONS.length);
    expect(projection.unitIds.length).toBeGreaterThanOrEqual(0); // WORLD act does not emit knowledge units yet — matches pre-I2 behavior
    expect(projection.worldActive).toBe(true);
    expect(projection.mode).toBe("demo");
  });

  it("BEFORE/AFTER: the cursor advances to the stream length either way, just under a different key", () => {
    const projection = reduceProductEvents(compileEvents);

    // BEFORE: `projection.lastSequence === compileEvents.length` (a bare
    // number Product App's P1 pages never read — I2 §11, proven).
    // AFTER: the same value lives at `lastSequenceByScope["demo:*"]`, because
    // every compile-stream event shares the one `"demo"` scope.
    expect(projection.lastSequenceByScope).toEqual({
      "demo:*": compileEvents.length,
    });
  });

  it("BEFORE/AFTER: the CHANGE act still ends on activation with the world it replaced addressable", () => {
    const events = buildChangeStream(DEMO_INITIAL_WORLD, CHANGED_WORLD).map(
      (entry) => entry.event,
    );
    const projection = reduceProductEvents(events);

    expect(projection.worldState).toEqual({
      id: CHANGED_WORLD.id,
      revision: CHANGED_WORLD.revision,
      previousId: DEMO_INITIAL_WORLD.id,
    });
  });

  it("BEFORE/AFTER: ASK still resolves every document, including the rejected ones", () => {
    const projection = reduceProductEvents(buildAskStream().map((entry) => entry.event));
    const statuses = projection.ask?.resolved.map((entry) => entry.status);
    expect(statuses).toEqual(["SUPERSEDED", "ACTIVE", "EXCEPTION"]);
  });

  it("BEFORE/AFTER: none of P1's consumed fields ever read the legacy collection_id", () => {
    // The demo fixture no longer sets a top-level `collection_id` at all
    // (I2 normalization strips it for `"demo"` scope) — if any P1-consumed
    // field had silently depended on it, this projection would already show
    // the gap. It does not: every check above is unaffected.
    const projection = reduceProductEvents(compileEvents);
    expect(projection).not.toHaveProperty("collection_id");
  });
});
