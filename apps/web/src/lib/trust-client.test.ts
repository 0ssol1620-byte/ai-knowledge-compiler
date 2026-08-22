import { describe, expect, it } from "vitest";

import { qualitySummarySchema, sceneSchema } from "@/lib/trust-client";

const jobId = "123e4567-e89b-42d3-a456-426614174000";

describe("trust API wire contracts", () => {
  it("accepts a truthful terminal scene", () => {
    expect(
      sceneSchema.parse({
        schema_version: "1.0",
        job_id: jobId,
        status: "completed",
        terminal: true,
        pages_total: 2,
        page_state_counts: { COMPLETED: 2 },
        accepted_blocks: 4,
        unresolved_recoveries: 0,
        progress: {},
        generated_at: "2026-08-03T00:00:00+09:00",
      }).terminal,
    ).toBe(true);
  });

  it("does not allow coverage or precision above one", () => {
    expect(() =>
      qualitySummarySchema.parse({
        schema_version: "1.0",
        job_id: jobId,
        verified_count: 1,
        recovered_verified_count: 0,
        unresolved_count: 0,
        excluded_count: 0,
        critical_false_verified_count: 0,
        silent_omission_count: 0,
        verified_coverage: 1.01,
        accepted_precision: 1,
        publishable: true,
        reason_codes: [],
        limitations: [],
      }),
    ).toThrow();
  });
});
