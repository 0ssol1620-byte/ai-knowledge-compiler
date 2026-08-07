import type { Metadata } from "next";

import { FolyntaMarketingPage } from "@/components/folynta-marketing-page";
import { PUBLIC_PAGES } from "@/lib/folynta-content";

export const metadata: Metadata = {
  title: "Document benchmarks",
  description:
    "Versioned evaluation for text, numbers, tables, reading order, source coverage, latency, and cost.",
};

export default function BenchmarksPage() {
  return <FolyntaMarketingPage definition={PUBLIC_PAGES["/benchmarks"]!} />;
}
