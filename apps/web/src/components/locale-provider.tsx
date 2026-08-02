"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

import { localeLanguageTag, type StructaraLocale } from "@/lib/locale";

type LocaleContextValue = {
  locale: StructaraLocale;
  languageTag: "en-US" | "ko-KR";
  setLocale: (locale: StructaraLocale) => void;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({
  locale,
  children,
}: {
  locale: StructaraLocale;
  children: ReactNode;
}) {
  const setLocale = useCallback((nextLocale: StructaraLocale) => {
    document.documentElement.lang = nextLocale;
    const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    window.location.assign(
      `/api/locale?value=${encodeURIComponent(nextLocale)}&returnTo=${encodeURIComponent(returnTo)}`,
    );
  }, []);
  const value = useMemo<LocaleContextValue>(
    () => ({ locale, languageTag: localeLanguageTag(locale), setLocale }),
    [locale, setLocale],
  );

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}

export function useStructaraLocale(): LocaleContextValue {
  const value = useContext(LocaleContext);
  if (!value) {
    throw new Error("useStructaraLocale must be used inside LocaleProvider");
  }
  return value;
}
