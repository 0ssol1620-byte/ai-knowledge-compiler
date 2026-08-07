import type { Metadata } from "next";

import { JsonLd } from "@/components/json-ld";
import { MarketingLanding } from "@/components/marketing-landing";
import { organizationGraph, SITE_BASE } from "@/lib/structured-data";

export const metadata: Metadata = {
  title: "The Knowledge Compiler for AI",
  description:
    "Turn documents into structured, verified, connected knowledge with every important result linked back to its source.",
  alternates: { canonical: "/" },
};

export default function MarketingPage() {
  return (
    <>
      <JsonLd nodes={organizationGraph(SITE_BASE)} />
      <MarketingLanding />
    </>
  );
}
