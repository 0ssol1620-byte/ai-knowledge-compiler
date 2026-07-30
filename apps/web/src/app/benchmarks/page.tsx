import type { Metadata } from "next";

import { StructaraMarketingPage } from "@/components/structara-marketing-page";
import { PUBLIC_PAGES } from "@/lib/structara-content";

export const metadata: Metadata = {
  title: "Document benchmarks",
  description:
    "Versioned evaluation for text, numbers, tables, reading order, source coverage, latency, and cost.",
};

export default function BenchmarksPage() {
  return <StructaraMarketingPage definition={PUBLIC_PAGES["/benchmarks"]!} />;
}
