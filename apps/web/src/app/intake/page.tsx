import type { Metadata } from "next";

import { CollectionIntake } from "@/components/collection-intake";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return {
    title: locale === "ko" ? "컬렉션 수집" : "Collection intake",
    description:
      locale === "ko"
        ? "폴더 구조를 보존하는 안전한 로컬 매니페스트와 사전견적 준비 화면"
        : "Build a safe local manifest that preserves folder structure before signed preflight.",
  };
}

export default async function IntakePage() {
  const locale = await getRequestLocale();
  return <CollectionIntake locale={locale} />;
}
