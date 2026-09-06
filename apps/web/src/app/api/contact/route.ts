import { createHash } from "node:crypto";

import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";

const contactSchema = z.object({
  name: z.string().trim().min(2).max(80),
  email: z.string().trim().email().max(254),
  company: z.string().trim().max(120).optional().default(""),
  topic: z.enum(["sales", "support", "security", "privacy", "partnership"]),
  message: z.string().trim().min(20).max(5000),
  website: z.string().max(200).optional().default(""),
  startedAt: z.number().int().positive(),
});

const topicLabels = {
  sales: "도입 및 요금",
  support: "제품 지원",
  security: "보안 검토",
  privacy: "개인정보",
  partnership: "파트너십",
} as const;

const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_LIMIT = 5;
const buckets = new Map<string, number[]>();

export async function POST(request: Request) {
  if (!isAllowedOrigin(request)) {
    return response("This request origin is not allowed.", 403);
  }

  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return response("Only JSON requests are accepted.", 415);
  }

  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (Number.isFinite(contentLength) && contentLength > 16_384) {
    return response("The request is too large.", 413);
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return response("Check the request format and try again.", 400);
  }

  const parsed = contactSchema.safeParse(raw);
  if (!parsed.success) {
    return response("Check the required fields and input lengths.", 400);
  }

  // Bots commonly submit instantly or fill the hidden website field.
  if (parsed.data.website || Date.now() - parsed.data.startedAt < 1500) {
    return NextResponse.json({ ok: true }, { status: 202 });
  }

  const clientKey = clientFingerprint(request);
  if (isRateLimited(clientKey)) {
    return response("Too many requests. Please try again in 10 minutes.", 429);
  }

  const apiKey = process.env.AKC_RESEND_API_KEY;
  const from = process.env.AKC_CONTACT_FROM ?? process.env.AKC_RESEND_SENDER;
  const to = process.env.AKC_CONTACT_TO;
  if (!apiKey || !from || !to) {
    return response(
      "The inquiry channel is not available yet. Please try again shortly.",
      503,
    );
  }

  const data = parsed.data;
  const delivery = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "Idempotency-Key": contactId(data.email, data.message),
    },
    body: JSON.stringify({
      from,
      to: [to],
      reply_to: data.email,
      subject: `[TAVONEL 문의] ${topicLabels[data.topic]} · ${data.name}`,
      text: plainText(data),
      html: htmlBody(data),
    }),
    signal: AbortSignal.timeout(10_000),
  }).catch(() => null);

  if (!delivery?.ok) {
    return response("Delivery is delayed. Please try again shortly.", 502);
  }

  return NextResponse.json(
    { ok: true },
    { status: 202, headers: { "Cache-Control": "no-store" } },
  );
}

function isAllowedOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return process.env.NODE_ENV !== "production";

  if (process.env.NODE_ENV !== "production") {
    try {
      const hostname = new URL(origin).hostname;
      if (hostname === "localhost" || hostname === "127.0.0.1") return true;
    } catch {
      return false;
    }
  }

  const configured = [
    process.env.NEXT_PUBLIC_SITE_URL,
    ...(process.env.AKC_CONTACT_ALLOWED_ORIGINS ?? "").split(","),
  ]
    .filter(Boolean)
    .map((value) => {
      try {
        return new URL(value!.trim()).origin;
      } catch {
        return "";
      }
    });

  return configured.includes(origin);
}

function clientFingerprint(request: Request): string {
  const forwarded = request.headers
    .get("x-forwarded-for")
    ?.split(",")[0]
    ?.trim();
  const source = forwarded || request.headers.get("x-real-ip") || "unknown";
  return createHash("sha256").update(source).digest("hex");
}

function isRateLimited(key: string): boolean {
  const now = Date.now();
  const recent = (buckets.get(key) ?? []).filter(
    (time) => now - time < RATE_WINDOW_MS,
  );
  if (recent.length >= RATE_LIMIT) return true;
  recent.push(now);
  buckets.set(key, recent);
  if (buckets.size > 10_000) buckets.clear();
  return false;
}

function contactId(email: string, message: string): string {
  const digest = createHash("sha256")
    .update(`${email.toLowerCase()}\n${message}`)
    .digest("hex")
    .slice(0, 32);
  return `contact/${digest}`;
}

type Contact = z.infer<typeof contactSchema>;

function plainText(data: Contact): string {
  return [
    "TAVONEL 웹사이트 문의",
    "",
    `유형: ${topicLabels[data.topic]}`,
    `이름: ${data.name}`,
    `이메일: ${data.email}`,
    `회사/조직: ${data.company || "미입력"}`,
    "",
    data.message,
  ].join("\n");
}

function htmlBody(data: Contact): string {
  const message = escapeHtml(data.message).replaceAll("\n", "<br>");
  return `<main style="font-family:Georgia,serif;max-width:640px;margin:0 auto;color:#171a1f">
    <p style="font-size:12px;letter-spacing:.12em;color:#3159d9">TAVONEL WEBSITE INQUIRY</p>
    <h1 style="font-size:24px">${escapeHtml(topicLabels[data.topic])}</h1>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <tr><th style="text-align:left;padding:10px 0;border-bottom:1px solid #ddd">이름</th><td style="padding:10px 0;border-bottom:1px solid #ddd">${escapeHtml(data.name)}</td></tr>
      <tr><th style="text-align:left;padding:10px 0;border-bottom:1px solid #ddd">이메일</th><td style="padding:10px 0;border-bottom:1px solid #ddd">${escapeHtml(data.email)}</td></tr>
      <tr><th style="text-align:left;padding:10px 0;border-bottom:1px solid #ddd">회사/조직</th><td style="padding:10px 0;border-bottom:1px solid #ddd">${escapeHtml(data.company || "미입력")}</td></tr>
    </table>
    <p style="font-size:15px;line-height:1.7;margin-top:28px">${message}</p>
  </main>`;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[character]!;
  });
}

function response(error: string, status: number) {
  return NextResponse.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
