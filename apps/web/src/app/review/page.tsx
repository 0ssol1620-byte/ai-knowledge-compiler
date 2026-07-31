import type { Metadata } from "next";

import { ReviewStudio } from "@/components/review-studio";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return { title: locale === "ko" ? "검토 Studio" : "Review Studio" };
}

export default async function ReviewPage() {
  const locale = await getRequestLocale();
  return <ReviewStudio locale={locale} />;
}
