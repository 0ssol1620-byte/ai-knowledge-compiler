import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FolyntaPricingPlanner } from "@/components/folynta-pricing-planner";

afterEach(cleanup);

describe("FolyntaPricingPlanner", () => {
  it("switches audience without hiding the estimator", () => {
    render(<FolyntaPricingPlanner />);

    fireEvent.click(screen.getByRole("button", { name: "Teams" }));

    expect(screen.getByRole("heading", { name: "Team" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Business" })).toBeVisible();
    expect(screen.getByRole("slider", { name: /Monthly pages/ })).toBeVisible();
  });

  it("updates the bounded credit estimate from page volume", () => {
    render(<FolyntaPricingPlanner />);

    fireEvent.change(screen.getByRole("slider", { name: /Monthly pages/ }), {
      target: { value: "50000" },
    });

    expect(screen.getByText("50,000")).toBeVisible();
    expect(screen.getByText("Business")).toBeVisible();
    expect(screen.getByText("68,200–87,200")).toBeVisible();
    expect(screen.getByText("87,200 credits")).toBeVisible();
  });
});
