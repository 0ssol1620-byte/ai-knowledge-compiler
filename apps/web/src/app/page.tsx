import type { Metadata } from "next";

import { MarketingLanding } from "@/components/marketing-landing";

export const metadata: Metadata = {
  title: "The Knowledge Compiler for AI",
  description:
    "Turn documents into structured, verified, connected knowledge with every important result linked back to its source.",
  alternates: { canonical: "/" },
};

export default function MarketingPage() {
  return <MarketingLanding />;
}
