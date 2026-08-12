import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BenchmarkLab } from "@/components/benchmark-lab";
import { publicBenchmarkSnapshot } from "@/lib/benchmark-public";

afterEach(cleanup);

describe("BenchmarkLab", () => {
  it("separates measured candidates from pre-inference diagnostics", () => {
    render(<BenchmarkLab />);

    const measuredTable = screen.getByRole("table", {
      name: "Reproducible parser results on the same corpus",
    });
    for (const candidate of publicBenchmarkSnapshot.datasets) {
      expect(within(measuredTable).getByText(candidate.label)).toBeInTheDocument();
    }

    const diagnosticLane = screen.getByRole("region", {
      name: "Failures stay visible.",
    });
    expect(within(diagnosticLane).getByText("OvisOCR2 · vLLM 0.22.1")).toBeInTheDocument();
    expect(within(diagnosticLane).getByText("0 scored cases")).toBeInTheDocument();
    expect(
      within(measuredTable).getByText("OvisOCR2 0.9B · vLLM cu129"),
    ).toBeInTheDocument();
    expect(
      within(measuredTable).queryByText("OvisOCR2 · vLLM 0.22.1"),
    ).not.toBeInTheDocument();
  });
});
