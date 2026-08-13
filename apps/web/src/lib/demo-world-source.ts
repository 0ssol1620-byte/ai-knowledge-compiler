import { DemoFixtureEventSource } from "@/lib/demo-event-source";
import { DEMO_COMPILE_STREAM, type ScheduledEvent } from "@/lib/demo-workspace";
import type { ProductEventSource } from "@/lib/product-event";

/**
 * The only place the Product App's WORLD/SOURCE/CHANGE/ASK slice names a
 * concrete `ProductEventSource` implementation.
 *
 * `ProductWorldProvider` and every component downstream of it are written
 * against the `ProductEventSource` interface (see product-event.ts), not
 * against `DemoFixtureEventSource`. When a `LiveProductEventSource` exists —
 * blocked today on the backend event-module conflict recorded in
 * docs/integration/I0_SHARED_WORLD_CONTRACT_PROMOTION.md — swapping the
 * product into live mode means adding one function here (or a runtime
 * choice between this one and it), not rewriting the workspace.
 *
 * `speed` compresses the fixture's ~7.5s scripted compile into ~190ms. WORLD
 * is specified as a stable exploratory instrument, not the cinematic
 * landing's timed reveal — a visitor should not wait through a replay to
 * search a graph. This still runs the real `DemoFixtureEventSource` replay
 * and the real `reduceProductEvent` path; nothing here is faked or skipped,
 * only sped up, which is exactly the affordance the source's `speed` option
 * documents itself as existing for.
 */
export function createSampleWorldSource(): ProductEventSource {
  return new DemoFixtureEventSource(DEMO_COMPILE_STREAM, { speed: 40 });
}

/**
 * Renumber a fixture schedule to continue a running `WorldProjection`
 * instead of restarting it.
 *
 * Every `build()`-produced schedule in demo-workspace.ts (`buildChangeStream`,
 * `buildAskStream`) numbers its own events `sequence: 1, 2, 3, …` because it
 * is written to be replayed standalone. `reduceProductEvent`'s at-least-once
 * guard drops anything at or below the projection's current `lastSequence`
 * — which the WORLD compile stream has already pushed well past 1 by the
 * time a visitor reaches CHANGE or ASK. Feeding an un-renumbered
 * `buildChangeStream()`/`buildAskStream()` schedule into the same shared
 * projection this app uses would have every one of its events silently
 * dropped as a stale replay, not applied as new. This shifts `sequence`
 * (and only `sequence`; `atMs` stays relative to the sub-stream's own
 * replay clock) so the follow-up stream is honestly *new* to the shared
 * projection it is being merged into.
 */
export function continueSchedule(
  schedule: readonly ScheduledEvent[],
  afterSequence: number,
): ScheduledEvent[] {
  return schedule.map((entry) => ({
    atMs: entry.atMs,
    event: { ...entry.event, sequence: entry.event.sequence + afterSequence },
  }));
}
