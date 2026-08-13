import { describe, expect, it } from "vitest";

import {
  PRODUCT_EVENT_TYPES,
  PROPOSED_EVENT_TYPES,
  REUSED_EVENT_TYPES,
  parseProductEvent,
  productEventSchema,
} from "@/lib/product-event";

/**
 * The failure paths matter more than the happy path here.
 *
 * `ProductEvent` is the seam between a fixture the repository controls and an
 * SSE stream it does not. Whatever the live endpoint eventually sends, this
 * parser is what stands between it and the DOM, so the tests that matter are
 * the ones proving it rejects.
 */

const valid = {
  schema_version: "1.0",
  event_id: "evt_1",
  event_type: "recovery.completed.v1",
  sequence: 4,
  occurred_at: "2026-08-11T09:00:04.160Z",
  collection_id: "col_sample_0001",
  mode: "demo",
  document_id: "d_policy_2026",
  page_number: 147,
  payload: { attempt: 2, verified: true },
};

describe("productEventSchema", () => {
  it("accepts a well-formed event", () => {
    const parsed = parseProductEvent(valid);
    expect(parsed?.event_type).toBe("recovery.completed.v1");
  });

  it("rejects an unknown event type rather than passing it through", () => {
    expect(
      parseProductEvent({ ...valid, event_type: "page.vibed.v1" }),
    ).toBeUndefined();
  });

  it("rejects a payload that does not match its event type", () => {
    // Right envelope, wrong shape: `recovery.completed.v1` requires
    // `verified`, and requires it to be `true`.
    //
    // `attempt` is deliberately *not* the field under test any more. It became
    // optional when the live adapter landed: the backend reports an attempt id
    // rather than an index, and requiring one would have forced the adapter to
    // invent it. `verified` stayed a literal because §11.2 R3 depends on it —
    // a recovery that did not verify must never be counted as a repair.
    expect(
      parseProductEvent({ ...valid, payload: { attempt: 2 } }),
    ).toBeUndefined();
    expect(
      parseProductEvent({ ...valid, payload: { attempt: 2, verified: false } }),
    ).toBeUndefined();
  });

  /*
   * Optional does not mean "all of them at once".
   *
   * Five payloads were relaxed so the live adapter and the fixture could both
   * satisfy them. Relaxed too far, an empty payload parsed clean and the strip
   * rendered "a file", "0 resolved" and "0 created" — three statements about
   * the world that no event ever made. Each of those now needs an identity or
   * a count before it is an event at all.
   */
  it("refuses an event that carries neither an identity nor a count", () => {
    const empty = (event_type: string) =>
      parseProductEvent({ ...valid, event_type, payload: {} });

    expect(empty("file.discovered.v1")).toBeUndefined();
    expect(empty("entity.resolved.v1")).toBeUndefined();
    expect(empty("relation.created.v1")).toBeUndefined();

    // Either half on its own is a real event.
    expect(
      parseProductEvent({
        ...valid,
        event_type: "entity.resolved.v1",
        payload: { entity_count: 12 },
      }),
    ).toBeDefined();
    expect(
      parseProductEvent({
        ...valid,
        event_type: "entity.resolved.v1",
        payload: { entity_id: "e_1" },
      }),
    ).toBeDefined();
  });

  it("refuses half a relation, which would render undefined endpoints", () => {
    expect(
      parseProductEvent({
        ...valid,
        event_type: "relation.created.v1",
        payload: { relation_id: "r_1", predicate: "covers" },
      }),
    ).toBeUndefined();

    expect(
      parseProductEvent({
        ...valid,
        event_type: "relation.created.v1",
        payload: {
          relation_id: "r_1",
          from_entity_id: "e_1",
          to_entity_id: "e_2",
          predicate: "covers",
        },
      }),
    ).toBeDefined();
  });

  it("rejects sequence 0 — the wire contract is a positive monotonic counter", () => {
    expect(parseProductEvent({ ...valid, sequence: 0 })).toBeUndefined();
  });

  it("rejects a mode outside demo/live", () => {
    // A stream that could label itself anything defeats PART 17.4's whole
    // point: sample and real have to stay distinguishable.
    expect(parseProductEvent({ ...valid, mode: "preview" })).toBeUndefined();
  });

  it("rejects a recovery event claiming it was not verified", () => {
    // `verified` is a literal `true`. A recovery that did not verify is a
    // different event, not this one with a flag flipped.
    expect(
      parseProductEvent({ ...valid, payload: { attempt: 2, verified: false } }),
    ).toBeUndefined();
  });

  it("rejects a resolution with a single candidate", () => {
    // A conflict needs at least two candidates or it is not a conflict, and a
    // resolution that reports one outcome has hidden the losers.
    expect(
      parseProductEvent({
        ...valid,
        event_type: "authority.resolved.v1",
        payload: {
          conflict_id: "cfl_1",
          winner_unit_id: "u_1",
          basis: "applicability",
          outcomes: [{ unit_id: "u_1", status: "ACTIVE" }],
        },
      }),
    ).toBeUndefined();
  });

  it("rejects a non-object", () => {
    expect(parseProductEvent(null)).toBeUndefined();
    expect(parseProductEvent("recovery.completed.v1")).toBeUndefined();
  });
});

describe("vocabulary provenance", () => {
  it("keeps the reused and proposed lists disjoint", () => {
    // If a name drifted into both lists, the "which of these does the backend
    // already emit" question would have two answers.
    const overlap = REUSED_EVENT_TYPES.filter((type) =>
      (PROPOSED_EVENT_TYPES as readonly string[]).includes(type),
    );
    expect(overlap).toEqual([]);
  });

  it("declares every type the schema can parse", () => {
    const declared = new Set<string>(PRODUCT_EVENT_TYPES);
    const inSchema = productEventSchema.options.map(
      (option) => option.shape.event_type.value,
    );
    for (const type of inSchema) expect(declared.has(type)).toBe(true);
    expect(inSchema).toHaveLength(PRODUCT_EVENT_TYPES.length);
  });

  it("uses the repository's versioned naming convention throughout", () => {
    for (const type of PRODUCT_EVENT_TYPES) {
      expect(type).toMatch(/^[a-z_]+(\.[a-z_]+)+\.v1$/);
    }
  });
});
