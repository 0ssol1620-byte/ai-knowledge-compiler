import { describe, expect, it } from "vitest";

import { CANONICAL_PLANS } from "@/lib/billing-catalog";

describe("canonical billing catalog", () => {
  it("keeps launch names and included usage canonical", () => {
    expect(CANONICAL_PLANS.map((plan) => plan.name)).toEqual([
      "Evaluation",
      "Developer",
      "Team",
      "Scale",
      "Enterprise",
    ]);
    expect(CANONICAL_PLANS.find((plan) => plan.code === "developer")).toMatchObject({
      price: "$29",
      includedPages: 500,
      commerciallyQualified: true,
    });
    expect(CANONICAL_PLANS.find((plan) => plan.code === "team")).toMatchObject({
      price: "$99",
      includedPages: 2_500,
      commerciallyQualified: true,
    });
  });

  it("does not invent an allowance for unqualified tiers", () => {
    expect(CANONICAL_PLANS.find((plan) => plan.code === "scale")).toMatchObject({
      includedPages: null,
      commerciallyQualified: false,
    });
  });
});
