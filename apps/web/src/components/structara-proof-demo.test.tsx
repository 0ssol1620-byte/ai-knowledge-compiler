import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StructaraProofDemo } from "@/components/tavonel-proof-demo";

afterEach(cleanup);

describe("FOLYNTA source proof interaction", () => {
  it("supports keyboard, pin, hover, and compare states on the real fixture", () => {
    const { container } = render(<StructaraProofDemo locale="en" />);
    const sourceCell = screen.getByRole("button", {
      name: /selected source evidence/i,
    });

    fireEvent.focus(sourceCell);
    expect(container.firstChild).toHaveAttribute("data-evidence-state", "keyboard");

    fireEvent.click(sourceCell);
    expect(container.firstChild).toHaveAttribute("data-evidence-state", "pinned");

    fireEvent.mouseEnter(sourceCell);
    expect(container.firstChild).toHaveAttribute("data-evidence-state", "hover");

    fireEvent.click(screen.getByRole("tab", { name: "Original" }));
    expect(container.firstChild).toHaveAttribute("data-evidence-state", "compare");
  });
});
