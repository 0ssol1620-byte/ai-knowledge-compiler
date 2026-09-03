import type { Metadata } from "next";

import { ReviewStudio } from "@/components/review-studio";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return { title: locale === "ko" ? "검토" : "Review" };
}

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ job?: string; document?: string }>;
}) {
  const [query, locale] = await Promise.all([searchParams, getRequestLocale()]);
  return (
    <ReviewStudio
      jobId={query.job ?? null}
      documentId={query.document ?? "unselected"}
      locale={locale}
    />
  );
}
