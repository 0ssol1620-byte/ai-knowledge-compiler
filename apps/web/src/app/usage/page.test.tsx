import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import { redirect } from "next/navigation";

import UsagePage from "@/app/usage/page";

const mockedRedirect = vi.mocked(redirect);

describe("UsagePage", () => {
  it("redirects to the canonical /billing route instead of rendering", () => {
    UsagePage();
    expect(mockedRedirect).toHaveBeenCalledWith("/billing");
    expect(mockedRedirect).toHaveBeenCalledTimes(1);
  });
});
