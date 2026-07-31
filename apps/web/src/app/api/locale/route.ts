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
  const response = NextResponse.redirect(
    new URL(returnTo, request.nextUrl.origin),
  );
  response.cookies.set(STRUCTARA_LOCALE_COOKIE, locale, {
    path: "/",
    maxAge: 31_536_000,
    sameSite: "lax",
    httpOnly: false,
    secure: request.nextUrl.protocol === "https:",
  });
  return response;
}
