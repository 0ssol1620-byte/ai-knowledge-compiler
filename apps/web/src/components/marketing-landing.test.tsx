import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/structara-hero", () => ({
  StructaraHeroScene: () => <div data-testid="hero-scene" />,
}));
vi.mock("@/components/structara-marketing-shell", () => ({
  StructaraMarketingShell: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@/components/marketing/transformation-story", () => ({
  TransformationStory: () => (
    <section className="folynta-scene" data-scene="04-transformation" />
  ),
}));

import { MarketingLanding } from "@/components/marketing-landing";

afterEach(cleanup);

describe("FOLYNTA landing authority", () => {
  it("renders exactly seven top-level narrative scenes", () => {
    const { container } = render(<MarketingLanding locale="en" />);
    const scenes = container.querySelectorAll("main > section");

    expect(scenes).toHaveLength(7);
    expect(
      Array.from(scenes, (scene) => scene.getAttribute("data-scene")),
    ).toEqual([
      "01-hero",
      "02-processing",
      "03-proof",
      "04-transformation",
      "05-knowledge",
      "06-trust-security",
      "07-final",
    ]);
  });

  it("uses the fixed Korean brand promise without a hero metric", () => {
    const { container } = render(<MarketingLanding locale="ko" />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /흩어진 문서를\s+하나의 지식 시스템으로\./,
      }),
    ).toBeVisible();
    expect(screen.getByText(/모든 중요한 결과를 원문으로/)).toBeVisible();
    expect(
      container.querySelector('[data-scene="01-hero"]'),
    ).not.toHaveTextContent(/%|latency|cost\/page/i);
  });
});
