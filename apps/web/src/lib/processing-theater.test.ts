import { describe, expect, it } from "vitest";

import {
  groupedProcessingStageFraction,
  PROCESSING_EVENT_BATCH_MS,
  PROCESSING_THEATER_STAGES,
} from "@/lib/processing-theater";

describe("processing theater contract", () => {
  it("exposes exactly six customer-facing event stages and a 100 ms batch", () => {
    expect(PROCESSING_EVENT_BATCH_MS).toBe(100);
    expect(
      PROCESSING_THEATER_STAGES.map(({ id, label }) => [id, label]),
    ).toEqual([
      ["collect", "COLLECT"],
      ["understand", "UNDERSTAND"],
      ["verify", "VERIFY"],
      ["compile", "COMPILE"],
      ["architect", "ARCHITECT"],
      ["package", "PACKAGE"],
    ]);
  });

  it("never marks a grouped stage complete until every real member reports", () => {
    const members = PROCESSING_THEATER_STAGES[0].members;
    expect(
      groupedProcessingStageFraction(
        { upload: { done: 1, total: 1 } },
        members,
      ),
    ).toBe(0.99);
    expect(
      groupedProcessingStageFraction(
        {
          upload: { done: 1, total: 1 },
          security_scan: { done: 1, total: 1 },
          preflight: { done: 1, total: 1 },
        },
        members,
      ),
    ).toBe(1);
  });
});
