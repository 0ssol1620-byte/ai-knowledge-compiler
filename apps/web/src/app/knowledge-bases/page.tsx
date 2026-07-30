import type { Metadata } from "next";

import { KnowledgeStudio } from "@/components/knowledge-studio";

export const metadata: Metadata = { title: "Knowledge bases" };

export default function KnowledgeBasesPage() {
  return <KnowledgeStudio />;
}
