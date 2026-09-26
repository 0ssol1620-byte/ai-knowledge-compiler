import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { IntegrityConsole } from "@/components/integrity-console";

afterEach(cleanup);

describe("IntegrityConsole", () => {
  it("shows every durable state and automatic attempt history before override", () => {
    const { container } = render(<IntegrityConsole locale="en" reference />);

    for (const [status, label] of [
      ["verified", "Verified"],
      ["authority_verified", "Authority verified"],
      ["auto_repaired", "Auto-repaired"],
      ["reprocessing", "Reprocessing"],
      ["warning", "Warning"],
      ["unresolved", "Unresolved"],
      ["quarantined", "Quarantined"],
    ] as const) {
      expect(container.querySelector(`[data-status="${status}"]`)).toHaveTextContent(label);
    }

    expect(screen.getByText("Automatic attempt history")).toBeVisible();
    expect(screen.getByText("Source-native structure")).toBeVisible();
    expect(screen.getByText(/remain immutable/)).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: /Continued table row/ }),
    );
    expect(screen.getByText("Overlap recovery")).toBeVisible();
    expect(screen.getByText("Repair accepted")).toBeVisible();

    fireEvent.click(screen.getByText("Optional customer decision"));
    expect(
      screen.getByRole("button", { name: "Record audited decision" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/live open finding and collection write permission/),
    ).toBeVisible();
  });
});
