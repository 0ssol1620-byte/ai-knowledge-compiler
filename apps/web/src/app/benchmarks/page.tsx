import type { Metadata } from "next";

import { TavonelMarketingPage } from "@/components/tavonel-marketing-page";
import { JsonLd } from "@/components/json-ld";
import { getRequestLocale } from "@/lib/locale-server";
import { PUBLIC_PAGES_KO } from "@/lib/structara-content-ko";
import { PUBLIC_PAGES } from "@/lib/tavonel-content";
import { pageGraph, SITE_BASE } from "@/lib/structured-data";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return {
    title: locale === "ko" ? "문서 벤치마크" : "Document benchmarks",
    description:
      locale === "ko"
        ? "텍스트, 숫자, 표, 읽기 순서, 원문 커버리지, 지연 시간과 비용을 버전별로 평가합니다."
        : "Versioned evaluation for text, numbers, tables, reading order, source coverage, latency, and cost.",
  };
}

export default async function BenchmarksPage() {
  const locale = await getRequestLocale();
  const definition = (locale === "ko" ? PUBLIC_PAGES_KO : PUBLIC_PAGES)[
    "/benchmarks"
  ]!;
  return (
    <>
      <JsonLd nodes={pageGraph(definition, SITE_BASE)} />
      <TavonelMarketingPage definition={definition} locale={locale} />
    </>
  );
}
