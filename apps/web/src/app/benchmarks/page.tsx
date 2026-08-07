import type { Metadata } from "next";

import { FolyntaMarketingPage } from "@/components/folynta-marketing-page";
import { JsonLd } from "@/components/json-ld";
import { PUBLIC_PAGES } from "@/lib/folynta-content";
import { pageGraph, SITE_BASE } from "@/lib/structured-data";

export const metadata: Metadata = {
  title: "Document benchmarks",
  description:
    "Versioned evaluation for text, numbers, tables, reading order, source coverage, latency, and cost.",
};

export default function BenchmarksPage() {
  const definition = PUBLIC_PAGES["/benchmarks"]!;
  return (
    <>
      <JsonLd nodes={pageGraph(definition, SITE_BASE)} />
      <FolyntaMarketingPage definition={definition} />
    </>
  );
}
