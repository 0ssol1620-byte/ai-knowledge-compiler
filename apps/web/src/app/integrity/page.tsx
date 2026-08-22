import type { Metadata } from "next";

import { IntegrityConsole } from "@/components/integrity-console";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return {
    title: locale === "ko" ? "무결성 콘솔" : "Integrity Console",
    description:
      locale === "ko"
        ? "자동 복구 이력과 근거 상태를 먼저 보여주는 무결성 검토 화면"
        : "Inspect automatic recovery history and evidence states before any optional human override.",
  };
}

export default async function IntegrityPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const locale = await getRequestLocale();
  const query = await searchParams;
  const collectionId = firstQueryValue(query.collection);
  const reference = firstQueryValue(query.reference) === "1";
  return (
    <IntegrityConsole
      locale={locale}
      collectionId={collectionId}
      reference={reference}
    />
  );
}

function firstQueryValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
