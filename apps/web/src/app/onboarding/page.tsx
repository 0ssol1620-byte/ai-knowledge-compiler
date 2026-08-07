import type { Metadata } from "next";

import { TavonelOnboarding } from "@/components/tavonel-onboarding";

export const metadata: Metadata = {
  title: "First knowledge project",
  robots: { index: false, follow: false },
};

export default function OnboardingPage() {
  return <TavonelOnboarding />;
}
