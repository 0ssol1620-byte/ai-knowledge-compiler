import { describe, expect, it } from "vitest";

describe("Google Drive OAuth 운영 자격 증명", () => {
  it("Google 토큰 엔드포인트가 TAVONEL 클라이언트를 invalid_client로 거부하지 않는다", async () => {
    const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID;
    const clientSecret = process.env.GOOGLE_OAUTH_CLIENT_SECRET;

    expect(clientId).toMatch(/\.apps\.googleusercontent\.com$/);
    expect(clientSecret).toMatch(/^GOCSPX-/);

    const response = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: clientId!,
        client_secret: clientSecret!,
        grant_type: "authorization_code",
      }),
    });
    const payload = (await response.json()) as { error?: string };

    // A real authorization code is deliberately omitted. Google should report
    // that request defect, not reject our registered OAuth client credentials.
    expect(payload.error).not.toBe("invalid_client");
    expect(response.status).toBe(400);
  }, 15_000);
});
