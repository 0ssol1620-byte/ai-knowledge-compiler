"use client";

import clsx from "clsx";

import { useStructaraLocale } from "@/components/locale-provider";

export function LocaleSwitcher({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  const { locale, setLocale } = useStructaraLocale();
  const label = locale === "ko" ? "언어 선택" : "Choose language";

  return (
    <div
      className={clsx("locale-switcher", compact && "compact", className)}
      role="group"
      aria-label={label}
    >
      <button
        type="button"
        aria-pressed={locale === "en"}
        onClick={() => setLocale("en")}
      >
        EN
      </button>
      <button
        type="button"
        aria-pressed={locale === "ko"}
        onClick={() => setLocale("ko")}
      >
        KO
      </button>
    </div>
  );
}
