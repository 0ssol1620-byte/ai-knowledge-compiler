import "server-only";

import { cookies } from "next/headers";

import {
  AKC_LOCALE_COOKIE,
  LEGACY_LOCALE_COOKIE,
  normalizeStructaraLocale,
  type StructaraLocale,
} from "@/lib/locale";

export async function getRequestLocale(): Promise<StructaraLocale> {
  const store = await cookies();
  return normalizeStructaraLocale(
    store.get(AKC_LOCALE_COOKIE)?.value ??
      store.get(LEGACY_LOCALE_COOKIE)?.value,
  );
}

/**
 * Public pages render English until the visitor chooses a language. Main's
 * public pages were English-only; making Korean their cookieless default is
 * a public-copy and GTM decision held for the founder, so it is not taken
 * here. The app keeps DEFAULT_STRUCTARA_LOCALE.
 */
export async function getPublicRequestLocale(): Promise<StructaraLocale> {
  const store = await cookies();
  const value =
    store.get(AKC_LOCALE_COOKIE)?.value ??
    store.get(LEGACY_LOCALE_COOKIE)?.value;
  return value === "ko" ? "ko" : "en";
}
