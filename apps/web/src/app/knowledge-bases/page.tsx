import type { Metadata } from "next";

import { KnowledgeStudio } from "@/components/knowledge-studio";
import { getRequestLocale } from "@/lib/locale-server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return { title: locale === "ko" ? "지식 베이스" : "Knowledge bases" };
}

export default async function KnowledgeBasesPage() {
  const locale = await getRequestLocale();
  return <KnowledgeStudio locale={locale} />;
}
