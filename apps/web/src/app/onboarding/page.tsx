import type { Metadata } from "next";

import { FolyntaOnboarding } from "@/components/folynta-onboarding";

export const metadata: Metadata = {
  title: "First knowledge project",
  robots: { index: false, follow: false },
};

export default function OnboardingPage() {
  return <FolyntaOnboarding />;
}
