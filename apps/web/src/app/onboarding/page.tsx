import type { Metadata } from "next";

import { LocaleProvider } from "@/components/locale-provider";
import { TavonelOnboarding } from "@/components/tavonel-onboarding";
import { getPublicRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getPublicRequestLocale();
  return {
    title: locale === "ko" ? "첫 지식 프로젝트" : "First knowledge project",
    robots: { index: false, follow: false },
  };
}

export default async function OnboardingPage() {
  return (
    <LocaleProvider locale={await getPublicRequestLocale()}>
      <TavonelOnboarding />
    </LocaleProvider>
  );
}
