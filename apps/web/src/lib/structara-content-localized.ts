import { PUBLIC_PAGES, type StructaraPage } from "@/lib/tavonel-content";
import { PUBLIC_PAGES_KO } from "@/lib/structara-content-ko";
import type { StructaraLocale } from "@/lib/locale";

export function getPublicPages(
  locale: StructaraLocale,
): Record<string, StructaraPage> {
  return locale === "ko" ? PUBLIC_PAGES_KO : PUBLIC_PAGES;
}

export function getPublicPage(
  path: string,
  locale: StructaraLocale,
): StructaraPage | undefined {
  return getPublicPages(locale)[path];
}
