import type { Metadata } from "next";

import { AuthPage } from "@/components/auth-page";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return {
    title: locale === "ko" ? "지식 시스템 구축하기" : "Build your knowledge",
    description:
      locale === "ko"
        ? "FOLYNTA 계정을 만들고 첫 문서로 시작하세요."
        : "Create a FOLYNTA account and begin with your first document.",
  };
}

export default function SignupPage() {
  return <AuthPage mode="register" nextPath="/onboarding" />;
}
