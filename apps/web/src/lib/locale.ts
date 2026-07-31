export const STRUCTARA_LOCALES = ["en", "ko"] as const;

export type StructaraLocale = (typeof STRUCTARA_LOCALES)[number];

export const DEFAULT_STRUCTARA_LOCALE: StructaraLocale = "en";
export const STRUCTARA_LOCALE_COOKIE = "structara_locale";

export function normalizeStructaraLocale(
  value: string | null | undefined,
): StructaraLocale {
  return value === "ko" ? "ko" : DEFAULT_STRUCTARA_LOCALE;
}

export function localeLanguageTag(locale: StructaraLocale): "en-US" | "ko-KR" {
  return locale === "ko" ? "ko-KR" : "en-US";
}

export function localeCopy<T>(
  locale: StructaraLocale,
  copy: Readonly<{ en: T; ko: T }>,
): T {
  return locale === "ko" ? copy.ko : copy.en;
}

export function formatLocaleNumber(
  locale: StructaraLocale,
  value: number,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(localeLanguageTag(locale), options).format(
    value,
  );
}

export function formatLocaleDateTime(
  locale: StructaraLocale,
  value: string | number | Date,
  options?: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat(localeLanguageTag(locale), options).format(
    new Date(value),
  );
}

export function formatLocaleRelativeDate(
  locale: StructaraLocale,
  value: string | number | Date,
  now: string | number | Date = Date.now(),
): string {
  const delta = new Date(value).getTime() - new Date(now).getTime();
  const formatter = new Intl.RelativeTimeFormat(localeLanguageTag(locale), {
    numeric: "auto",
  });
  const abs = Math.abs(delta);
  if (abs < 60_000)
    return formatter.format(Math.round(delta / 1_000), "second");
  if (abs < 3_600_000)
    return formatter.format(Math.round(delta / 60_000), "minute");
  if (abs < 86_400_000)
    return formatter.format(Math.round(delta / 3_600_000), "hour");
  return formatter.format(Math.round(delta / 86_400_000), "day");
}
