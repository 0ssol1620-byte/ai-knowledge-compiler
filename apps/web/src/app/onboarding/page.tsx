import type { Metadata } from "next";

import { TavonelOnboarding } from "@/components/tavonel-onboarding";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return {
    title: locale === "ko" ? "첫 지식 프로젝트" : "First knowledge project",
    robots: { index: false, follow: false },
  };
}

export default async function OnboardingPage() {
  return <TavonelOnboarding />;
}
