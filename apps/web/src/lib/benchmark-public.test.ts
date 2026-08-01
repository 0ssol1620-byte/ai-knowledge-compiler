import { describe, expect, it } from "vitest";

import {
  formatBenchmarkCost,
  formatBenchmarkLatency,
  publicBenchmarkSnapshot,
} from "@/lib/benchmark-public";

describe("public benchmark evidence", () => {
  it("publishes only formal three-repeat candidates", () => {
    expect(publicBenchmarkSnapshot.status).toBe("available");
    expect(publicBenchmarkSnapshot.datasets.length).toBeGreaterThanOrEqual(3);
    expect(publicBenchmarkSnapshot.datasets.every((row) => row.evidence?.case_count === 54)).toBe(true);
    expect(publicBenchmarkSnapshot.datasets.every((row) => row.evidence?.hard_failure_count === 0)).toBe(true);
  });

  it("labels mean runtime in seconds and preserves micro-cost precision", () => {
    expect(formatBenchmarkLatency(6958.9195)).toBe("6.959 s");
    expect(formatBenchmarkCost(0.0006756086)).toBe("$0.000676");
  });
});
