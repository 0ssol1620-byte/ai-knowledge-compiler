import type { Metadata } from "next";

import { AskStudio } from "@/components/ask-studio";

export const metadata: Metadata = {
  title: "Ask",
  description: "Ask an active TAVONEL World and inspect its source-bound citations.",
};

export default async function AskPage({
  searchParams,
}: {
  searchParams: Promise<{ collection?: string }>;
}) {
  const { collection } = await searchParams;
  return <AskStudio collectionId={collection ?? null} />;
}
