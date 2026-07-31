import type { Metadata } from "next";

import { MarketingLanding } from "@/components/marketing-landing";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const korean = locale === "ko";
  return {
    title: korean ? "AI를 위한 지식 컴파일러" : "The Knowledge Compiler for AI",
    description: korean
      ? "문서를 구조화되고 검증되며 서로 연결된 지식으로 전환하고 중요한 모든 결과를 원본에 연결합니다."
      : "Turn documents into structured, verified, connected knowledge with every important result linked back to its source.",
    alternates: { canonical: "/" },
  };
}

export default async function MarketingPage() {
  const locale = await getRequestLocale();
  return <MarketingLanding locale={locale} />;
}
