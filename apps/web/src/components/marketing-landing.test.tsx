import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/locale-switcher", () => ({
  LocaleSwitcher: () => <div aria-label="Locale switcher" />,
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
      "01-product-film",
      "02-intake",
      "03-recovery",
      "04-actual-source",
      "05-knowledge",
      "06-trust",
      "07-final",
    ]);
  });

  it("uses the fixed Korean brand promise without a hero metric", () => {
    const { container } = render(<MarketingLanding locale="ko" />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /흩어진 문서를, 검증 가능한 지식으로\./,
      }),
    ).toBeVisible();
    expect(screen.getByText(/모든 결과를 원문까지 연결/)).toBeVisible();
    expect(
      container.querySelector('[data-scene="01-product-film"]'),
    ).not.toHaveTextContent(/%|latency|cost\/page/i);
  });

  it("labels the real DART PDF renderer and rejects fake progress", () => {
    render(<MarketingLanding locale="ko" />);

    expect(screen.getByText(/실제 공시 PDF를 PDF\.js로 렌더링/)).toBeVisible();
    expect(screen.getByText(/시간 기반 가짜 진행률은 없습니다/)).toBeVisible();
    expect(
      screen.getByText(/DOM 재구성을 원문으로 표시하지 않습니다/),
    ).toBeVisible();
  });
});
