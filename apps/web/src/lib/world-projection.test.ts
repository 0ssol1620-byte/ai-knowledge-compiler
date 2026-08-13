import { describe, expect, it, vi } from "vitest";

import { DemoFixtureEventSource } from "@/lib/demo-event-source";
import {
  buildAskStream,
  buildChangeStream,
  DEMO_AFFECTED_UNITS,
  DEMO_ANSWER,
  DEMO_COMPILE_STREAM,
  DEMO_DISCOVERY,
  DEMO_ENTITIES,
  DEMO_IMPACT,
  DEMO_INITIAL_WORLD,
  DEMO_RELATIONS,
  DEMO_TRUTH_STREAM,
  DEMO_UNITS,
  nextWorldState,
} from "@/lib/demo-workspace";
import { parseProductEvent } from "@/lib/product-event";
import type { ProductEvent } from "@/lib/product-event";
import {
  EMPTY_PROJECTION,
  reduceProductEvent,
  reduceProductEvents,
} from "@/lib/world-projection";

const compileEvents = DEMO_COMPILE_STREAM.map((entry) => entry.event);

/** The world a five-year revision activates, used by the change/ask suites. */
const CHANGED_WORLD = nextWorldState(DEMO_INITIAL_WORLD, "5 years");

describe("the demo fixture is a valid ProductEvent stream", () => {
  it("parses every event against the schema", () => {
    // The fixture is typed, so this cannot fail at compile time — but the
    // fixture is also what the live contract is proposed from, and a fixture
    // that would not survive its own parser is not a proposal.
    for (const event of compileEvents) {
      expect(parseProductEvent(event)).toBeDefined();
    }
  });

  it("numbers sequences from 1 with no gaps", () => {
    expect(compileEvents.map((event) => event.sequence)).toEqual(
      compileEvents.map((_, index) => index + 1),
    );
  });

  it("labels every event as demo mode", () => {
    for (const event of compileEvents) expect(event.mode).toBe("demo");
  });

  /*
   * Regression. The entity and relation beats are written as two `.map()`s
   * whose `atMs` ranges overlap, so before `build()` sorted, a relation
   * scheduled at 4820ms carried a higher sequence than an entity scheduled at
   * 6130ms. The reducer drops anything at or below `lastSequence` — correctly,
   * because delivery is at-least-once — so eleven of twelve entities were
   * swallowed the moment the stream ran on a clock.
   *
   * Reducing the array in order cannot catch this; only the relationship
   * between the two orderings can.
   */
  for (const [name, stream] of [
    ["compile", DEMO_COMPILE_STREAM],
    ["truth", DEMO_TRUTH_STREAM],
    ["change", buildChangeStream(DEMO_INITIAL_WORLD, CHANGED_WORLD)],
    ["ask", buildAskStream()],
  ] as const) {
    it(`delivers the ${name} stream in sequence order`, () => {
      let previousAt = -1;
      let previousSequence = 0;
      for (const entry of stream) {
        expect(entry.event.sequence).toBe(previousSequence + 1);
        expect(entry.atMs).toBeGreaterThanOrEqual(previousAt);
        previousAt = entry.atMs;
        previousSequence = entry.event.sequence;
      }
    });
  }

  it("keeps every event when the schedule is played on a clock", async () => {
    // The end-to-end version of the same guarantee: play the real timers at
    // high speed and assert the projection is identical to the array reduce.
    const source = new DemoFixtureEventSource(DEMO_COMPILE_STREAM, {
      speed: 400,
    });
    const seen: ProductEvent[] = [];
    source.subscribe((event) => seen.push(event));
    source.start();
    await new Promise((resolve) => setTimeout(resolve, 120));
    source.stop();

    expect(seen).toHaveLength(compileEvents.length);
    const timed = reduceProductEvents(seen);
    expect(timed.entityIds).toHaveLength(DEMO_ENTITIES.length);
    expect(timed.relationIds).toHaveLength(DEMO_RELATIONS.length);
    expect(timed.worldActive).toBe(true);
  });
});

describe("reduceProductEvents — the compile stream", () => {
  const projection = reduceProductEvents(compileEvents);

  it("reaches the discovery figures the stream carries", () => {
    expect(projection.discovery.filesDiscovered).toBe(
      DEMO_DISCOVERY.filesDiscovered,
    );
    expect(projection.discovery.revisionFamilies).toBe(
      DEMO_DISCOVERY.revisionFamilies,
    );
    expect(projection.discovery.duplicates).toBe(DEMO_DISCOVERY.duplicates);
    expect(projection.discovery.complexTables).toBe(
      DEMO_DISCOVERY.complexTables,
    );
  });

  it("builds the whole world", () => {
    expect(projection.entityIds).toHaveLength(DEMO_ENTITIES.length);
    expect(projection.relationIds).toHaveLength(DEMO_RELATIONS.length);
    expect(projection.unitIds).toHaveLength(DEMO_UNITS.length);
    expect(projection.worldActive).toBe(true);
  });

  it("derives the RECOVERY lane rather than expecting the backend to send it", () => {
    // §11.3 — `route_label` has no RECOVERY value and does not need one.
    const lanes = projection.lanes.map((entry) => entry.lane);
    expect(lanes).toContain("RECOVERY");
    const routeEvents = compileEvents.filter(
      (event) => event.event_type === "page.route.selected.v1",
    );
    for (const event of routeEvents) {
      if (event.event_type !== "page.route.selected.v1") continue;
      expect(event.payload.lane).not.toBe("RECOVERY");
    }
  });

  it("keeps the recovery scar as its own counter", () => {
    // §11.2 R3 — a repaired page never reads as one that was clean.
    expect(projection.recoveredPages).toBe(1);
  });
});

describe("at-least-once delivery", () => {
  it("treats a redelivered event as a no-op", () => {
    const first = compileEvents[0];
    if (!first) throw new Error("fixture is empty");
    const once = reduceProductEvent(EMPTY_PROJECTION, first);
    const twice = reduceProductEvent(once, first);
    expect(twice).toBe(once);
  });

  it("does not double-count a redelivered entity", () => {
    const entityEvent = compileEvents.find(
      (event) => event.event_type === "entity.resolved.v1",
    );
    if (!entityEvent) throw new Error("no entity event in the fixture");
    const state = reduceProductEvents(compileEvents);
    const replayed = reduceProductEvent(state, entityEvent);
    expect(replayed.entityIds).toHaveLength(DEMO_ENTITIES.length);
  });
});

describe("truth resolution", () => {
  const projection = reduceProductEvents(
    DEMO_TRUTH_STREAM.map((entry) => entry.event),
  );

  it("records the losers as well as the winner", () => {
    expect(projection.resolution?.winnerUnitId).toBe("u_warranty_2026");
    expect(projection.resolution?.outcomes).toHaveLength(DEMO_UNITS.length);
  });

  it("resolves on applicability, not on recency", () => {
    // The 2026 policy is also the newest file, so a "latest wins" system would
    // produce the same winner by accident. The basis is what distinguishes it.
    expect(projection.resolution?.basis).toBe("applicability");
  });
});

describe("incremental recompilation", () => {
  const projection = reduceProductEvents(
    buildChangeStream(DEMO_INITIAL_WORLD, CHANGED_WORLD).map((entry) => entry.event),
  );

  it("recompiles only the affected units", () => {
    expect(projection.recompile?.recompiled).toBe(DEMO_AFFECTED_UNITS.length);
    expect(projection.recompile?.done).toBe(true);
  });

  it("keeps the denominator so the counter never becomes a percentage", () => {
    // §11.2 R5 — both terms travel on the event. `7 / 12,841` is the claim;
    // `0.05%` would not be.
    expect(projection.recompile?.worldUnitsTotal).toBe(
      DEMO_IMPACT.worldUnitsTotal,
    );
    expect(projection.impact?.knowledgeUnitsAffected).toBeLessThan(
      DEMO_IMPACT.worldUnitsTotal,
    );
  });
});

/**
 * The demo is one state machine: change → impact → activation → ask → evidence.
 *
 * An edit here is not a preview of an impact. It revises a source, and the
 * revision ends in a *new activated world state* that everything downstream
 * answers from. These tests hold the two halves that make that true — the
 * sequence actually reaches activation, and the state it replaced survives.
 */
describe("a change activates a new world state", () => {
  const events = buildChangeStream(DEMO_INITIAL_WORLD, CHANGED_WORLD).map(
    (entry) => entry.event,
  );
  const projection = reduceProductEvents(events);

  it("starts from a source revision that names what it replaced", () => {
    expect(projection.sourceRevision).toMatchObject({
      documentId: "d_policy_2026",
      cell: "Cell B4",
      previousValue: DEMO_INITIAL_WORLD.term,
      newValue: CHANGED_WORLD.term,
      revision: CHANGED_WORLD.revision,
      previousRevision: DEMO_INITIAL_WORLD.revision,
    });
  });

  it("ends on activation rather than on the last recompiled unit", () => {
    // Ordering matters: anything downstream that reads the world must not be
    // able to observe a finished counter before the state is active.
    const types = events.map((event) => event.event_type);
    expect(types[0]).toBe("source.revision.created.v1");
    expect(types.at(-1)).toBe("world_state.activated.v1");
    expect(types.indexOf("recompile.completed.v1")).toBeLessThan(
      types.indexOf("world_state.activated.v1"),
    );
  });

  it("keeps the world it replaced addressable", () => {
    expect(projection.worldState).toEqual({
      id: CHANGED_WORLD.id,
      revision: CHANGED_WORLD.revision,
      previousId: DEMO_INITIAL_WORLD.id,
    });
    // The previous state is not merely an id: its value is still readable, so
    // a before/after of the two worlds can be stated rather than inferred.
    expect(CHANGED_WORLD.previous).toEqual({
      id: DEMO_INITIAL_WORLD.id,
      revision: DEMO_INITIAL_WORLD.revision,
      term: DEMO_INITIAL_WORLD.term,
    });
  });

  it("answers the changed world with the changed value", () => {
    const asked = reduceProductEvents(
      buildAskStream(CHANGED_WORLD).map((entry) => entry.event),
    );
    expect(asked.ask?.answer).toBe("5 years");
    // And the evidence path names the revision it answered from.
    expect(asked.ask?.trace).toContain(
      `Document revision ${CHANGED_WORLD.revision}`,
    );
    expect(asked.ask?.trace.at(-1)).toBe("Cell B4");
  });

  it("still answers the untouched world with the original value", () => {
    const asked = reduceProductEvents(
      buildAskStream(DEMO_INITIAL_WORLD).map((entry) => entry.event),
    );
    expect(asked.ask?.answer).toBe(DEMO_ANSWER);
  });
});

describe("ask", () => {
  const projection = reduceProductEvents(
    buildAskStream().map((entry) => entry.event),
  );

  it("shows every document considered, including the rejected ones", () => {
    const statuses = projection.ask?.resolved.map((entry) => entry.status);
    expect(statuses).toEqual(["SUPERSEDED", "ACTIVE", "EXCEPTION"]);
  });

  it("emits four independent guarantees rather than one score", () => {
    expect(projection.ask?.answer).toBe(DEMO_ANSWER);
    expect(projection.ask?.guarantees).toHaveLength(4);
    expect(projection.ask?.trace.at(-1)).toBe("Cell B4");
  });

  it("drops a source resolution that arrives before its question", () => {
    const orphan = buildAskStream()[1]?.event;
    if (!orphan) throw new Error("fixture too short");
    const state = reduceProductEvent(EMPTY_PROJECTION, orphan);
    expect(state.ask).toBeUndefined();
  });
});

describe("DemoFixtureEventSource", () => {
  it("delivers the whole schedule in order when finished early", () => {
    // This is the reduced-motion path: same events, no waiting.
    const source = new DemoFixtureEventSource(DEMO_COMPILE_STREAM);
    const seen: ProductEvent[] = [];
    source.subscribe((event) => seen.push(event));
    source.finish();
    expect(seen.map((event) => event.sequence)).toEqual(
      compileEvents.map((event) => event.sequence),
    );
  });

  it("stops delivering after stop()", () => {
    vi.useFakeTimers();
    try {
      const source = new DemoFixtureEventSource(DEMO_COMPILE_STREAM);
      const seen: ProductEvent[] = [];
      source.subscribe((event) => seen.push(event));
      source.start();
      vi.advanceTimersByTime(500);
      const delivered = seen.length;
      expect(delivered).toBeGreaterThan(0);
      source.stop();
      vi.advanceTimersByTime(10_000);
      expect(seen).toHaveLength(delivered);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops delivering to an unsubscribed listener", () => {
    const source = new DemoFixtureEventSource(DEMO_COMPILE_STREAM);
    const seen: ProductEvent[] = [];
    const unsubscribe = source.subscribe((event) => seen.push(event));
    unsubscribe();
    source.finish();
    expect(seen).toHaveLength(0);
  });
});
