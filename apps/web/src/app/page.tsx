import type { Metadata } from "next";

import { MarketingLanding } from "@/components/marketing-landing";

export const metadata: Metadata = {
  title: "Evidence-linked knowledge from every document",
  description:
    "Turn PDFs, reports, papers, and course material into source-linked Markdown, Obsidian vaults, RAG data, and knowledge graphs.",
};

export default function MarketingPage() {
  return <MarketingLanding />;
}
