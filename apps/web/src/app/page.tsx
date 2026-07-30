import type { Metadata } from "next";

import { MarketingLanding } from "@/components/marketing-landing";

export const metadata: Metadata = {
  title: "모든 문서를, 검증 가능한 AI 지식으로",
  description:
    "PDF·보고서·논문·강의자료를 원문 근거가 연결된 Markdown, Obsidian Vault, RAG 데이터와 지식 그래프로 변환합니다.",
};

export default function MarketingPage() {
  return <MarketingLanding />;
}
