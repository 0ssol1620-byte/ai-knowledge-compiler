import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { GET } from "@/app/api/locale/route";

describe("locale redirect contract", () => {
  it("uses a same-origin relative redirect and persists the selected locale", () => {
    const response = GET(
      new NextRequest(
        "http://127.0.0.1:3101/api/locale?value=ko&returnTo=%2Fintake%3Ftab%3Dfiles",
      ),
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("/intake?tab=files");
    expect(response.headers.get("Set-Cookie")).toContain(
      "structara_locale=ko",
    );
  });

  it("rejects protocol-relative return targets", () => {
    const response = GET(
      new NextRequest(
        "https://structara.example/api/locale?value=ko&returnTo=%2F%2Fevil.example",
      ),
    );

    expect(response.headers.get("Location")).toBe("/");
    expect(response.headers.get("Set-Cookie")).toContain("Secure");
  });
});
