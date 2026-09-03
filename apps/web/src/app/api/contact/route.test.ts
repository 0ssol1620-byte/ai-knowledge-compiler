import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/contact/route";

const validBody = {
  name: "김타보넬",
  email: "buyer@example.com",
  company: "Example Labs",
  topic: "sales",
  message: "문서 5만 페이지를 검증 가능한 지식으로 변환하고 싶습니다.",
  website: "",
  startedAt: Date.now() - 5000,
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("contact API", () => {
  it("fails closed when delivery is not configured", async () => {
    const result = await POST(contactRequest(validBody));
    expect(result.status).toBe(503);
  });

  it("accepts bot-shaped submissions without sending mail", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const result = await POST(
      contactRequest({ ...validBody, website: "spam.test" }),
    );
    expect(result.status).toBe(202);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends escaped content through Resend without exposing credentials", async () => {
    vi.stubEnv("AKC_RESEND_API_KEY", "secret-test-key");
    vi.stubEnv("AKC_CONTACT_FROM", "TAVONEL <no-reply@tavonel.com>");
    vi.stubEnv("AKC_CONTACT_TO", "hello@tavonel.com");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "email_test" }), { status: 200 }),
      );

    const result = await POST(
      contactRequest({
        ...validBody,
        message: "<script>alert(1)</script> 안전한 문의입니다.",
      }),
    );
    expect(result.status).toBe(202);

    const [, options] = fetchMock.mock.calls[0]!;
    const payload = JSON.parse(String(options?.body)) as Record<
      string,
      unknown
    >;
    expect(payload.reply_to).toBe(validBody.email);
    expect(payload.html).toContain("&lt;script&gt;");
    expect(payload.html).not.toContain("<script>");
    expect(JSON.stringify(payload)).not.toContain("secret-test-key");
  });

  it("rejects cross-origin submissions", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://tavonel.com");
    const result = await POST(
      contactRequest(validBody, "https://attacker.test"),
    );
    expect(result.status).toBe(403);
  });

  it("accepts localhost development origins on non-default ports", async () => {
    const result = await POST(
      contactRequest(validBody, "http://127.0.0.1:3101"),
    );
    expect(result.status).toBe(503);
  });

  it("rejects oversized request bodies before parsing", async () => {
    const request = contactRequest(validBody);
    request.headers.set("content-length", "16385");
    const result = await POST(request);
    expect(result.status).toBe(413);
  });
});

function contactRequest(body: unknown, origin = "http://localhost:3000") {
  return new Request("http://localhost:3000/api/contact", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin },
    body: JSON.stringify(body),
  });
}
