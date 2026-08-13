import { describe, expect, it } from "vitest";

import { continueSchedule } from "@/lib/demo-world-source";
import {
  DEMO_COMPILE_STREAM,
  DEMO_INITIAL_WORLD,
  buildAskStream,
  buildChangeStream,
  nextWorldState,
} from "@/lib/demo-workspace";
import {
  reduceProductEvent,
  reduceProductEvents,
  scopeKey,
} from "@/lib/world-projection";

// Every event in this file's fixtures is demo-scope, so they all share the
// one `"demo:*"` cursor (I2 §5) — see world-projection.ts.
const DEMO_KEY = scopeKey({ kind: "demo" });

/**
 * Pins the bug `continueSchedule` exists to prevent: `buildChangeStream` and
 * `buildAskStream` both number their own events from `sequence: 1`, written
 * on the assumption of a standalone replay. This app instead merges every
 * sub-stream into one running `WorldProjection` shared with WORLD, whose
 * demo-scope cursor (`lastSequenceByScope["demo:*"]`) is already past the
 * compile stream's ~26 events by the time a visitor reaches CHANGE or ASK.
 * `reduceProductEvent`'s at-least-once guard drops anything at or below that
 * cursor — so an un-renumbered follow-up stream would be silently discarded
 * in its entirety, not applied.
 */
describe("continueSchedule", () => {
  it("shifts every event's sequence by the given offset, preserving order and atMs", () => {
    const schedule = buildAskStream(DEMO_INITIAL_WORLD);
    const shifted = continueSchedule(schedule, 100);

    expect(shifted).toHaveLength(schedule.length);
    shifted.forEach((entry, index) => {
      expect(entry.event.sequence).toBe(schedule[index]!.event.sequence + 100);
      expect(entry.atMs).toBe(schedule[index]!.atMs);
      expect(entry.event.event_type).toBe(schedule[index]!.event.event_type);
    });
  });

  it("without renumbering, a follow-up stream is dropped entirely by a running projection", () => {
    const compiled = reduceProductEvents(
      DEMO_COMPILE_STREAM.map((entry) => entry.event),
    );
    const raw = buildAskStream(DEMO_INITIAL_WORLD);
    const afterRaw = raw.reduce(
      (state, entry) => reduceProductEvent(state, entry.event),
      compiled,
    );
    // The bug: every event in `raw` has sequence <=
    // compiled.lastSequenceByScope[DEMO_KEY], so none of them changed the
    // projection at all.
    expect(afterRaw).toBe(compiled);
    expect(afterRaw.ask).toBeUndefined();
  });

  it("renumbered, the same follow-up stream is applied and answers the question", () => {
    const compiled = reduceProductEvents(
      DEMO_COMPILE_STREAM.map((entry) => entry.event),
    );
    const renumbered = continueSchedule(
      buildAskStream(DEMO_INITIAL_WORLD),
      compiled.lastSequenceByScope[DEMO_KEY] ?? 0,
    );
    const answered = renumbered.reduce(
      (state, entry) => reduceProductEvent(state, entry.event),
      compiled,
    );

    expect(answered.ask?.answer).toBe(DEMO_INITIAL_WORLD.term);
    expect(answered.lastSequenceByScope[DEMO_KEY]).toBeGreaterThan(
      compiled.lastSequenceByScope[DEMO_KEY] ?? 0,
    );
  });

  it("a renumbered change stream, then a renumbered ask stream, both apply in order", () => {
    let state = reduceProductEvents(
      DEMO_COMPILE_STREAM.map((entry) => entry.event),
    );
    const target = nextWorldState(DEMO_INITIAL_WORLD, "5 years");
    const changeSchedule = continueSchedule(
      buildChangeStream(DEMO_INITIAL_WORLD, target),
      state.lastSequenceByScope[DEMO_KEY] ?? 0,
    );
    for (const entry of changeSchedule) {
      state = reduceProductEvent(state, entry.event);
    }
    expect(state.sourceRevision?.newValue).toBe("5 years");
    expect(state.worldState?.id).toBe(target.id);

    const askSchedule = continueSchedule(
      buildAskStream(target),
      state.lastSequenceByScope[DEMO_KEY] ?? 0,
    );
    for (const entry of askSchedule) {
      state = reduceProductEvent(state, entry.event);
    }
    expect(state.ask?.answer).toBe("5 years");
  });
});
