import type { Metadata } from "next";

import { AuthPage } from "@/components/auth-page";

export const metadata: Metadata = {
  title: "Build your knowledge",
  description: "Create a FOLYNTA account and begin with your first document.",
};

export default function SignupPage() {
  return <AuthPage mode="register" nextPath="/onboarding" />;
}
