import { describe, expect, it } from "vitest";

import { appActionHref } from "@/lib/app-action";

describe("Structara app header actions", () => {
  it.each([
    ["home", "/quick-convert"],
    ["projects", "/projects"],
    ["jobs", "/activity"],
    ["knowledge-bases", "/knowledge-bases"],
    ["benchmarks", "/analytics"],
    ["recipes", "/settings"],
    ["exports", "/workspace"],
    ["api", "/api-workflows"],
    ["usage", "/usage"],
    ["billing", "/settings"],
    ["projects/sample/overview", "/quick-convert"],
    ["projects/sample/exports", "/workspace"],
    ["settings/security", "/settings"],
    ["admin/audit", "/admin"],
    ["document/sample/review", "/workspace"],
  ])("maps %s to an operable destination", (route, expected) => {
    expect(appActionHref(route)).toBe(expected);
    expect(expected).not.toBe(`/app/${route}`);
  });
});
