import type { Metadata } from "next";

import { ReviewStudio } from "@/components/review-studio";

export const metadata: Metadata = { title: "Review Studio" };

export default function ReviewPage() {
  return <ReviewStudio />;
}
