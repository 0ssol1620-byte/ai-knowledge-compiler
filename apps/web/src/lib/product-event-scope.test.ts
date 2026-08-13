import { describe, expect, it } from "vitest";

import { parseProductEvent } from "@/lib/product-event";
import type { ProductEvent } from "@/lib/product-event";
import {
  EMPTY_PROJECTION,
  reduceProductEvent,
  reduceProductEvents,
} from "@/lib/world-projection";

/**
 * I2 §5 / §11 — the two guarantees the discriminated `scope` contract exists
 * to make provable, not just asserted:
 *
 *   1. A job-plane event and a collection-plane event that happen to carry
 *      the same numeric `sequence` are never mistaken for redeliveries of
 *      each other. Job-plane and collection-plane `sequence` are different
 *      counter spaces (I1 §2/§9) — the single global `lastSequence` this
 *      file's design replaced could not tell them apart.
 *   2. A job-scope event never ends up with a truthy `collection_id`. The
 *      job plane structurally has none (I1 §6a) — a `collection_id` on a
 *      job-scope event would be exactly the "fabricated identity" CLAUDE.md
 *      forbids.
 */

const jobEventRaw = {
  schema_version: "1.0",
  event_id: "evt_job_0001",
  event_type: "page.route.selected.v1",
  sequence: 1,
  occurred_at: "2026-08-13T09:00:00.000Z",
  scope: { kind: "job", job_id: "job-abc" },
  mode: "live",
  payload: { lane: "FAST" },
};

const collectionEventRaw = {
  schema_version: "1.0",
  event_id: "evt_coll_0001",
  event_type: "collection.discovery.progress.v1",
  sequence: 1,
  occurred_at: "2026-08-13T09:00:01.000Z",
  scope: { kind: "collection", collection_id: "coll-xyz" },
  mode: "live",
  payload: { files_discovered: 42 },
};

describe("cross-scope cursor independence (I2 §5)", () => {
  const jobEvent = parseProductEvent(jobEventRaw);
  const collectionEvent = parseProductEvent(collectionEventRaw);

  it("parses both fixtures", () => {
    expect(jobEvent).toBeDefined();
    expect(collectionEvent).toBeDefined();
  });

  /*
   * Negative proof, run first: this reconstructs `world-projection.ts`'s
   * pre-I2 idempotency rule — a single `lastSequence: number` shared by every
   * plane, `event.sequence <= state.lastSequence` — to show the scenario
   * below is not a strawman. It is not a call into production code: that
   * rule does not exist in this file any more for a test to call, so the
   * only way to show what it would have done is to write it out here, next
   * to the citation of where it lived (`world-projection.ts`, pre-I2
   * `reduceProductEvent`, `git show` of this commit's parent has the exact
   * line).
   */
  it("would have been silently dropped by the pre-I2 single global cursor", () => {
    if (!jobEvent || !collectionEvent) throw new Error("fixtures failed to parse");

    let legacyLastSequence = 0;
    let secondEventWasDropped = false;
    for (const event of [jobEvent, collectionEvent]) {
      if (event.sequence <= legacyLastSequence) {
        secondEventWasDropped = true;
        continue;
      }
      legacyLastSequence = event.sequence;
    }

    // Both events carry `sequence: 1`. Under one global counter, the first
    // event (job-scope) raises the cursor to 1, and the second (collection-
    // scope, unrelated plane, unrelated identity) reads as an already-seen
    // redelivery purely because the numbers collide.
    expect(secondEventWasDropped).toBe(true);
  });

  it("applies both events under the new per-scope cursor — neither reads as a duplicate of the other", () => {
    if (!jobEvent || !collectionEvent) throw new Error("fixtures failed to parse");

    const afterJob = reduceProductEvent(EMPTY_PROJECTION, jobEvent);
    expect(afterJob.lanes).toHaveLength(1);

    const afterCollection = reduceProductEvent(afterJob, collectionEvent);

    // The collection event was actually applied, not dropped as a "replay"
    // of the job event that happened to share its sequence number.
    expect(afterCollection.discovery.filesDiscovered).toBe(42);

    // Each scope kept its own cursor.
    expect(afterCollection.lastSequenceByScope).toEqual({
      "job:job-abc": 1,
      "collection:coll-xyz": 1,
    });
  });

  it("order does not matter — feeding the collection event first is symmetric", () => {
    if (!jobEvent || !collectionEvent) throw new Error("fixtures failed to parse");

    const projection = reduceProductEvents([collectionEvent, jobEvent]);
    expect(projection.discovery.filesDiscovered).toBe(42);
    expect(projection.lanes).toHaveLength(1);
    expect(projection.lastSequenceByScope).toEqual({
      "job:job-abc": 1,
      "collection:coll-xyz": 1,
    });
  });

  it("still drops a genuine redelivery within the same scope", () => {
    if (!jobEvent) throw new Error("fixture failed to parse");
    const once = reduceProductEvent(EMPTY_PROJECTION, jobEvent);
    const twice = reduceProductEvent(once, jobEvent);
    expect(twice).toBe(once);
  });
});

describe("no identity fabrication across scopes (I2 §2/§7/§11)", () => {
  it("never lets a job-scope event carry a truthy top-level collection_id", () => {
    const event = parseProductEvent(jobEventRaw);
    expect(event).toBeDefined();
    expect(event?.collection_id).toBeUndefined();
    // Not merely `undefined` as a value — the key itself is absent, so a
    // `"collection_id" in event` check (as a real caller might write) cannot
    // read `true` for an identity the job plane never asserted.
    expect(Object.prototype.hasOwnProperty.call(event as object, "collection_id")).toBe(
      false,
    );
  });

  it("strips a collection_id even if a raw job-scope frame tries to carry one", () => {
    // A producer bug, not a legitimate frame — but normalization must scrub
    // it regardless of how it got there, because the guarantee is about the
    // parsed output, not about trusting every producer to behave.
    const event = parseProductEvent({
      ...jobEventRaw,
      collection_id: "col_should_not_survive",
    });
    expect(event).toBeDefined();
    expect(event?.collection_id).toBeUndefined();
  });

  it("strips a collection_id from a demo-scope event the same way", () => {
    const event = parseProductEvent({
      schema_version: "1.0",
      event_id: "evt_demo_0001",
      event_type: "collection.discovery.progress.v1",
      sequence: 1,
      occurred_at: "2026-08-13T09:00:00.000Z",
      scope: { kind: "demo" },
      collection_id: "col_should_not_survive",
      mode: "demo",
      payload: { files_discovered: 1 },
    });
    expect(event).toBeDefined();
    expect(event?.collection_id).toBeUndefined();
  });

  it("mirrors scope.collection_id onto the legacy top-level field for collection-scope events", () => {
    // The raw frame here carries no top-level `collection_id` at all — only
    // `scope`. Normalization derives the legacy field, rather than requiring
    // every producer to set both.
    const event = parseProductEvent(collectionEventRaw);
    expect(event).toBeDefined();
    expect(event?.collection_id).toBe("coll-xyz");
  });

  it("overrides a stale top-level collection_id with scope's value rather than trusting the raw frame", () => {
    const event = parseProductEvent({
      ...collectionEventRaw,
      collection_id: "col_stale_mismatch",
    });
    expect(event).toBeDefined();
    expect(event?.collection_id).toBe("coll-xyz");
  });

  it("rejects a collection-scope event with no collection_id at all — the identity is mandatory, not optional", () => {
    const event = parseProductEvent({
      ...collectionEventRaw,
      scope: { kind: "collection" },
    });
    expect(event).toBeUndefined();
  });

  it("rejects a job-scope event with no job_id — the identity is mandatory", () => {
    const event = parseProductEvent({ ...jobEventRaw, scope: { kind: "job" } });
    expect(event).toBeUndefined();
  });

  it("accepts a job-scope event carrying job_id, document_id and page_number on the scope itself", () => {
    const event = parseProductEvent({
      ...jobEventRaw,
      scope: {
        kind: "job",
        job_id: "job-abc",
        document_id: "d_policy_2026",
        page_number: 3,
      },
    });
    expect(event).toBeDefined();
    expect(event?.scope).toEqual({
      kind: "job",
      job_id: "job-abc",
      document_id: "d_policy_2026",
      page_number: 3,
    });
  });
});

describe("demo scope shares one cursor (I2 §5's own example: \"demo:*\")", () => {
  it("keys every demo-scope event under the same cursor regardless of fixture_id", () => {
    const first: ProductEvent | undefined = parseProductEvent({
      schema_version: "1.0",
      event_id: "evt_demo_a",
      event_type: "collection.discovery.progress.v1",
      sequence: 1,
      occurred_at: "2026-08-13T09:00:00.000Z",
      scope: { kind: "demo", fixture_id: "fixture-a" },
      mode: "demo",
      payload: { files_discovered: 1 },
    });
    const second: ProductEvent | undefined = parseProductEvent({
      schema_version: "1.0",
      event_id: "evt_demo_b",
      event_type: "collection.discovery.progress.v1",
      sequence: 2,
      occurred_at: "2026-08-13T09:00:01.000Z",
      scope: { kind: "demo", fixture_id: "fixture-b" },
      mode: "demo",
      payload: { files_discovered: 2 },
    });
    if (!first || !second) throw new Error("fixtures failed to parse");

    const projection = reduceProductEvents([first, second]);
    expect(projection.lastSequenceByScope).toEqual({ "demo:*": 2 });
    expect(projection.discovery.filesDiscovered).toBe(2);
  });
});
