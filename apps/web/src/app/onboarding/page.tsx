import type { Metadata } from "next";

import { StructaraOnboarding } from "@/components/structara-onboarding";

export const metadata: Metadata = {
  title: "First knowledge project",
  robots: { index: false, follow: false },
};

export default function OnboardingPage() {
  return <StructaraOnboarding />;
}
