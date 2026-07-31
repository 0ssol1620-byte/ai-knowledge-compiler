import "server-only";

import { cookies } from "next/headers";

import {
  normalizeStructaraLocale,
  STRUCTARA_LOCALE_COOKIE,
  type StructaraLocale,
} from "@/lib/locale";

export async function getRequestLocale(): Promise<StructaraLocale> {
  const store = await cookies();
  return normalizeStructaraLocale(store.get(STRUCTARA_LOCALE_COOKIE)?.value);
}
