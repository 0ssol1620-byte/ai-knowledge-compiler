import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TavonelPricingPlanner } from "@/components/tavonel-pricing-planner";

afterEach(cleanup);

describe("TavonelPricingPlanner", () => {
  it("shows every page-based plan without hiding the estimator", () => {
    render(<TavonelPricingPlanner />);

    expect(screen.getByRole("heading", { name: "Team" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Scale" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Enterprise" })).toBeVisible();
    expect(screen.getByRole("slider", { name: /Detected pages/ })).toBeVisible();
  });

  it("updates the bounded dollar estimate from page volume", () => {
    render(<TavonelPricingPlanner />);

    fireEvent.change(screen.getByRole("slider", { name: /Detected pages/ }), {
      target: { value: "5000" },
    });

    expect(screen.getByText("5,000")).toBeVisible();
    expect(screen.getByText("$200.00")).toBeVisible();
    expect(screen.getByText("$211.00")).toBeVisible();
    expect(screen.getByText("$300.00")).toBeVisible();
  });
});
