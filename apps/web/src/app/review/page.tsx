import type { Metadata, Route } from "next";
import { redirect } from "next/navigation";

import {
  type CompatibilityQuery,
  integrityCompatibilityTarget,
} from "@/lib/integrity-compatibility";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return { title: locale === "ko" ? "무결성 콘솔" : "Integrity Console" };
}

export default async function ReviewCompatibilityPage({
  searchParams,
}: {
  searchParams: Promise<CompatibilityQuery>;
}) {
  redirect(integrityCompatibilityTarget(await searchParams) as Route);
}
