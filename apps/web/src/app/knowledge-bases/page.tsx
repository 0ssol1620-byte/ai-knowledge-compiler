import type { Metadata } from "next";

import { KnowledgeStudio } from "@/components/knowledge-studio";

export const metadata: Metadata = { title: "지식베이스" };

export default function KnowledgeBasesPage() {
  return <KnowledgeStudio />;
}
