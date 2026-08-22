import { describe, expect, it } from "vitest";

import type { CollectionEvent } from "@/lib/collection-runtime-client";
import {
  collectionEventsToV6,
  hasV6ParallelEvidence,
  v6ReplayBaseline,
} from "@/lib/v6-collection-events";

const JOB_ID = "00000000-0000-4000-8000-000000000001";

function event(
  eventType: CollectionEvent["event_type"],
  sequence: number,
  jobId: string | null = JOB_ID,
): CollectionEvent {
  return {
    schema_version: "1.0",
    event_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    collection_id: "00000000-0000-4000-8000-000000000010",
    job_id: jobId,
    sequence,
    event_type: eventType,
    timestamp: `2026-08-01T00:00:${String(sequence).padStart(2, "0")}Z`,
    payload: {
      collection_id: "00000000-0000-4000-8000-000000000010",
      document_id: "00000000-0000-4000-8000-000000000020",
      page_id: "00000000-0000-4000-8000-000000000030",
    },
  };
}

describe("v6 collection-event adapter", () => {
  it("renames only the timestamp and preserves authoritative identifiers", () => {
    const adapted = collectionEventsToV6([event("shard.planned.v1", 7)]);

    expect(adapted).toHaveLength(1);
    expect(adapted[0]).toMatchObject({
      event_type: "shard.planned.v1",
      sequence: 7,
      occurred_at: "2026-08-01T00:00:07Z",
      job_id: JOB_ID,
      document_id: "00000000-0000-4000-8000-000000000020",
      page_id: "00000000-0000-4000-8000-000000000030",
    });
  });

  it("excludes uncorrelated and collection-only events instead of inventing a job", () => {
    const adapted = collectionEventsToV6(
      [
        event("shard.planned.v1", 8, null),
        event("shard.dispatched.v1", 9, JOB_ID),
        event(
          "attempt.started.v1",
          10,
          "00000000-0000-4000-8000-000000000099",
        ),
      ],
      JOB_ID,
    );

    expect(adapted.map((item) => item.sequence)).toEqual([9]);
    expect(hasV6ParallelEvidence(adapted)).toBe(true);
    expect(v6ReplayBaseline(adapted)).toBe(8);
  });

  it("does not label legacy events as parallel evidence", () => {
    const adapted = collectionEventsToV6([
      event("processing.started.v1", 1),
    ]);

    expect(hasV6ParallelEvidence(adapted)).toBe(false);
    expect(v6ReplayBaseline([])).toBeUndefined();
  });
});
