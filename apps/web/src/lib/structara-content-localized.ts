import { PUBLIC_PAGES, type TavonelPage } from "@/lib/tavonel-content";
import { PUBLIC_PAGES_KO } from "@/lib/structara-content-ko";
import type { StructaraLocale } from "@/lib/locale";

export function getPublicPages(
  locale: StructaraLocale,
): Record<string, TavonelPage> {
  return locale === "ko" ? PUBLIC_PAGES_KO : PUBLIC_PAGES;
}

export function getPublicPage(
  path: string,
  locale: StructaraLocale,
): TavonelPage | undefined {
  return getPublicPages(locale)[path];
}
