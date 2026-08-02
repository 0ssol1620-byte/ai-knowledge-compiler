import type { Metadata } from "next";

import { StructaraMarketingPage } from "@/components/structara-marketing-page";
import { getRequestLocale } from "@/lib/locale-server";
import { getPublicPage } from "@/lib/structara-content-localized";

export const metadata: Metadata = {
  title: "Document benchmarks",
  description:
    "Versioned evaluation for text, numbers, tables, reading order, source coverage, latency, and cost.",
};

export default async function BenchmarksPage() {
  const locale = await getRequestLocale();
  const definition = getPublicPage("/benchmarks", locale);

  if (!definition) {
    throw new Error("Missing localized /benchmarks page definition");
  }

  return <StructaraMarketingPage definition={definition} />;
}
