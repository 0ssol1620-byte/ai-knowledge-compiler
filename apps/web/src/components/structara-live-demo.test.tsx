import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StructaraLiveDemo } from "@/components/structara-live-demo";

class IntersectionObserverProbe {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", IntersectionObserverProbe);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StructaraLiveDemo", () => {
  it("exposes all five compilation phases as an accessible tab sequence", () => {
    render(<StructaraLiveDemo />);

    expect(screen.getAllByRole("tab")).toHaveLength(5);
    expect(screen.getByRole("tab", { name: /Collect/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(screen.getByRole("tab", { name: /Verify/ }));

    expect(screen.getByRole("tab", { name: /Verify/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText(/Numeric gate/)).toHaveTextContent(
      "Numeric gate · exact · source line 3669",
    );
    expect(screen.getByRole("tabpanel")).toHaveTextContent("4,902,490,901 JPY");
  });

  it("supports keyboard phase selection and explicit pause or resume", () => {
    render(<StructaraLiveDemo />);

    const collect = screen.getByRole("tab", { name: /Collect/ });
    fireEvent.keyDown(collect, { key: "End" });
    expect(screen.getByRole("tab", { name: /Package/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    const resume = screen.getByRole("button", { name: "Resume demo" });
    fireEvent.click(resume);
    expect(screen.getByRole("button", { name: "Pause demo" })).toBeVisible();
  });

  it("renders the localized phase and control contract", () => {
    render(<StructaraLiveDemo locale="ko" />);

    expect(screen.getByRole("tab", { name: /수집/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /검증/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "데모 일시정지" })).toBeVisible();
    expect(screen.getByText(/파서 품질 주장 아님/)).toBeVisible();
  });
});
