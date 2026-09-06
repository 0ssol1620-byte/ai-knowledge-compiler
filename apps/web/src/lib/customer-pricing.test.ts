import { describe, expect, it } from "vitest";

import { customerChargeQuote, formatUsd } from "@/lib/customer-pricing";

describe("customer page pricing", () => {
  it("separates standard and routed pages from internal usage units", () => {
    expect(customerChargeQuote(100, 75)).toEqual({
      minimum: 4,
      estimated: 4.5,
      maximum: 6,
    });
  });

  it("clamps impossible native counts to the billable page count", () => {
    expect(customerChargeQuote(10, 99).estimated).toBe(0.4);
  });

  it("formats customer currency independently", () => {
    expect(formatUsd(4.5)).toBe("$4.50");
  });
});
