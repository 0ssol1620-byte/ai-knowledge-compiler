import type { Metadata } from "next";

import { TavonelMarketingPage } from "@/components/tavonel-marketing-page";
import { JsonLd } from "@/components/json-ld";
import { PUBLIC_PAGES } from "@/lib/tavonel-content";
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
      <TavonelMarketingPage definition={definition} />
    </>
  );
}
