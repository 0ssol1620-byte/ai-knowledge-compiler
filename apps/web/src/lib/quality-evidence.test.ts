import { describe, expect, it } from "vitest";

import { measuredQualityBreakdown } from "@/lib/quality-evidence";

describe("measuredQualityBreakdown", () => {
  it("normalizes only finite measurements supplied by the backend", () => {
    expect(
      measuredQualityBreakdown({
        evaluation_payload: {
          overall_score: 0.925,
          vector: {
            text_fidelity: 0.91,
            numeric_fidelity: 97,
            table_fidelity: Number.NaN,
          },
        },
      }),
    ).toEqual({
      overall: 92.5,
      metrics: [
        {
          key: "text_fidelity",
          label: "Character agreement",
          score: 91,
        },
        { key: "numeric_fidelity", label: "Number agreement", score: 97 },
      ],
    });
  });

  it("does not invent an overall score or absent components", () => {
    expect(measuredQualityBreakdown({ status: "verified" })).toEqual({
      metrics: [],
    });
    expect(measuredQualityBreakdown(undefined)).toEqual({ metrics: [] });
  });
});
