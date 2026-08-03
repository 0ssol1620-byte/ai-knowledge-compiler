import { type NextRequest, NextResponse } from "next/server";

function configuredApiOrigin(): string {
  try {
    return new URL(
      process.env.NEXT_PUBLIC_AKC_API_URL ?? "http://localhost:8000",
    ).origin;
  } catch {
    return "http://localhost:8000";
  }
}

export function proxy(request: NextRequest) {
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const development = process.env.NODE_ENV !== "production";
  const apiOrigin = configuredApiOrigin();
  const policy = [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    `img-src 'self' data: blob: ${apiOrigin}`,
    "font-src 'self' data:",
    "style-src 'self' 'unsafe-inline'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    `connect-src 'self' ${apiOrigin}`,
    "worker-src 'self' blob:",
    "media-src 'self' blob:",
    "manifest-src 'self'",
    "form-action 'self'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("x-folynta-pathname", request.nextUrl.pathname);
  // Next reads the request CSP and applies this nonce to framework scripts.
  requestHeaders.set("Content-Security-Policy", policy);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
