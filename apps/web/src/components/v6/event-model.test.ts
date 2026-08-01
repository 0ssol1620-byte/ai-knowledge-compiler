import { describe, expect, it } from "vitest";

import {
  creditImpactForEvent,
  deriveV6ProductView,
  type V6VersionedEvent,
} from "./event-model";

function event(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown> = {},
  options: Partial<V6VersionedEvent> = {},
): V6VersionedEvent {
  return {
    schema_version: "1.0",
    event_id: `event-${sequence}`,
    event_type: eventType,
    sequence,
    occurred_at: `2026-08-01T00:00:${String(sequence).padStart(2, "0")}Z`,
    job_id: "job-v6",
    payload,
    ...options,
  };
}

describe("deriveV6ProductView", () => {
  it("derives concurrent page states, recovery, verification, and immutable attempt lineage", () => {
    const view = deriveV6ProductView([
      event(1, "shard.planned.v1", {
        page_ids: ["page-1", "page-2"],
      }),
      event(2, "attempt.started.v1", {
        attempt_id: "attempt-1",
        attempt_number: 1,
        root_attempt_id: "attempt-1",
        shard_id: "shard-a",
        page_id: "page-1",
        page_number1: 1,
        worker_pool_id: "pool-mineru",
        worker_id: "worker-01",
        route: "mineru_precision",
      }),
      event(3, "attempt.started.v1", {
        attempt_id: "attempt-2",
        root_attempt_id: "attempt-2",
        shard_id: "shard-b",
        page_id: "page-2",
        page_number1: 2,
        worker_pool_id: "pool-paddle",
        worker_id: "worker-02",
        route: "paddle_vl",
      }),
      event(4, "recovery.region.requested.v1", {
        page_id: "page-1",
        region_id: "table-4",
        reason_code: "row_omission",
      }),
      event(5, "recovery.completed.v1", {
        page_id: "page-1",
        region_id: "table-4",
      }),
      event(6, "attempt.accepted.v1", {
        attempt_id: "attempt-1",
        page_id: "page-1",
        verification_state: "auto_repaired",
        gpu_seconds: 8.25,
        provider_cost_usd: 0.18,
        user_credits: 1.5,
        billable: true,
        validator_status: "pass",
      }),
      event(7, "page.unresolved.v1", {
        page_id: "page-2",
        reason_code: "authority_conflict",
      }),
    ]);

    expect(view.pages).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ pageId: "page-1", state: "auto_repaired" }),
        expect.objectContaining({ pageId: "page-2", state: "unresolved" }),
      ]),
    );
    expect(view.attempts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          attemptId: "attempt-1",
          attemptNumber: 1,
          rootAttemptId: "attempt-1",
          status: "accepted",
          gpuSeconds: 8.25,
        }),
      ]),
    );
    expect(view.workerPools.map((pool) => pool.poolId)).toEqual([
      "pool-mineru",
      "pool-paddle",
    ]);
    expect(view.cost).toMatchObject({
      gpuSeconds: 8.25,
      providerCostUsd: 0.18,
      attemptUserCredits: 1.5,
    });
    expect(
      view.integrityEntries.find((entry) => entry.kind === "unresolved")
        ?.creditImpact,
    ).toMatchObject({
      kind: "not_billable",
      source: "v6_fail_closed_policy",
    });
  });

  it("does not promote a page completion event to verified without verification evidence", () => {
    const view = deriveV6ProductView([
      event(1, "page.completed.v1", { page_id: "page-1" }),
    ]);

    expect(view.pages[0]?.state).toBe("completed_unverified");
  });

  it("projects the canonical backend shard range, pool key, final state, and GPU milliseconds", () => {
    const documentId = "00000000-0000-4000-8000-000000000020";
    const common = { document_id: documentId, shard_id: "shard-backend" };
    const view = deriveV6ProductView([
      event(1, "shard.planned.v1", {
        ...common,
        page_start: 3,
        page_end: 4,
        route_class: "cross_page_table",
      }),
      event(2, "attempt.started.v1", {
        ...common,
        attempt_id: "attempt-backend",
        attempt_number: 1,
        pool_key: "mineru-3-4-4",
      }),
      event(3, "attempt.output.received.v1", {
        ...common,
        attempt_id: "attempt-backend",
        gpu_milliseconds: 2_500,
      }),
      event(4, "attempt.accepted.v1", {
        ...common,
        attempt_id: "attempt-backend",
        final_state: "authority_verified",
        cost_usd: "0.0125",
        billable: true,
      }),
    ]);

    expect(view.pages.map((page) => [page.pageNumber1, page.state])).toEqual([
      [3, "authority_verified"],
      [4, "authority_verified"],
    ]);
    expect(view.attempts[0]).toMatchObject({
      attemptId: "attempt-backend",
      poolId: "mineru-3-4-4",
      gpuSeconds: 2.5,
      providerCostUsd: 0.0125,
    });
  });

  it("fails closed on unsupported schemas, conflicting sequences, and replay gaps", () => {
    const view = deriveV6ProductView(
      [
        event(11, "attempt.started.v1", {
          attempt_id: "attempt-1",
          page_id: "page-1",
        }),
        event(13, "attempt.output.received.v1", {
          attempt_id: "attempt-1",
          page_id: "page-1",
        }),
        event(
          13,
          "attempt.accepted.v1",
          { attempt_id: "attempt-conflict", page_id: "page-2" },
          { event_id: "event-conflict" },
        ),
        event(
          14,
          "attempt.accepted.v1",
          { attempt_id: "attempt-v2", page_id: "page-3" },
          { schema_version: "2.0" },
        ),
      ],
      10,
    );

    expect(view.ignoredEventCount).toBe(1);
    expect(view.conflictingSequenceCount).toBe(1);
    expect(view.gapCount).toBe(1);
    expect(view.pages.map((page) => page.pageId)).toEqual(["page-1"]);
  });

  it("reports missing cost as missing rather than synthetic zero", () => {
    const view = deriveV6ProductView([
      event(1, "attempt.started.v1", {
        attempt_id: "attempt-1",
        page_id: "page-1",
      }),
    ]);

    expect(view.cost.gpuSeconds).toBeNull();
    expect(view.cost.providerCostUsd).toBeNull();
    expect(view.cost.consumedCredits).toBeNull();
  });

  it("preserves a signed credit delta instead of coercing a refund to zero", () => {
    expect(
      creditImpactForEvent(
        event(1, "page.unresolved.v1", {
          page_id: "page-1",
          user_credit_delta: -2.5,
        }),
      ),
    ).toMatchObject({ kind: "measured", value: "-2.5" });
  });
});
