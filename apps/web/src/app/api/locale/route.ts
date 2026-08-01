import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  normalizeStructaraLocale,
  STRUCTARA_LOCALE_COOKIE,
} from "@/lib/locale";

export function GET(request: NextRequest) {
  const locale = normalizeStructaraLocale(
    request.nextUrl.searchParams.get("value"),
  );
  const requestedReturn = request.nextUrl.searchParams.get("returnTo") ?? "/";
  const returnTo =
    requestedReturn.startsWith("/") && !requestedReturn.startsWith("//")
      ? requestedReturn
      : "/";
  // A relative Location keeps the browser on the exact public origin that
  // initiated the request. Building an absolute URL from Next's internal
  // origin can otherwise switch localhost/127.0.0.1 in local verification or
  // leak an infrastructure hostname behind a reverse proxy.
  const response = new NextResponse(null, {
    status: 303,
    headers: { Location: returnTo },
  });
  response.cookies.set(STRUCTARA_LOCALE_COOKIE, locale, {
    path: "/",
    maxAge: 31_536_000,
    sameSite: "lax",
    httpOnly: false,
    secure:
      request.nextUrl.protocol === "https:" ||
      request.headers.get("x-forwarded-proto") === "https",
  });
  return response;
}
