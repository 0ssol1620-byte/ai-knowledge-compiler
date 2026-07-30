import { describe, expect, it } from "vitest";

import {
  formatMetric,
  type AnalyticsMetric,
} from "@/components/analytics-live";

function metric(overrides: Partial<AnalyticsMetric> = {}): AnalyticsMetric {
  return {
    key: "test",
    label: "Test",
    value: null,
    numerator: 0,
    denominator: 0,
    unit: "ratio",
    status: "empty_denominator",
    definition: "Synthetic formatter contract.",
    sources: [],
    ...overrides,
  };
}

describe("analytics metric formatting", () => {
  it("renders a measured ratio without inventing a comparison", () => {
    expect(
      formatMetric(
        metric({
          value: 0.5,
          numerator: 1,
          denominator: 2,
          status: "available",
        }),
      ),
    ).toBe("50.0%");
  });

  it("distinguishes an empty denominator from a measured zero", () => {
    expect(formatMetric(metric())).toBe("No denominator");
    expect(
      formatMetric(
        metric({
          value: 0,
          numerator: 0,
          denominator: 2,
          status: "available",
        }),
      ),
    ).toBe("0.0%");
  });

  it("labels credits as credits rather than currency", () => {
    const rendered = formatMetric(
      metric({
        value: 1.25,
        numerator: 2.5,
        denominator: 2,
        unit: "credits_per_page",
        status: "available",
      }),
    );
    expect(rendered).toBe("1.25 cr/page");
    expect(rendered).not.toContain("₩");
  });
});
