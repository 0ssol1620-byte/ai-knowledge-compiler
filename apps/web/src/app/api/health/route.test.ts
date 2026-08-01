import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/health/route";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("web deployment health", () => {
  it("exposes the immutable provider revision when available", async () => {
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "A".repeat(40));
    vi.stubEnv("VERCEL_DEPLOYMENT_ID", "dpl_test");
    vi.stubEnv("VERCEL_ENV", "preview");

    const response = GET();

    expect(response.headers.get("Cache-Control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual(
      expect.objectContaining({
        status: "ok",
        service: "akc-web",
        revision: "a".repeat(40),
        revision_source: "vercel",
        deployment_id: "dpl_test",
        environment: "preview",
      }),
    );
  });

  it("fails closed instead of inventing a revision", async () => {
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "main");
    vi.stubEnv("GITHUB_SHA", "");
    vi.stubEnv("AKC_DEPLOYMENT_REVISION", "");

    const response = GET();

    await expect(response.json()).resolves.toEqual(
      expect.objectContaining({
        revision: null,
        revision_source: null,
      }),
    );
  });
});
