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
