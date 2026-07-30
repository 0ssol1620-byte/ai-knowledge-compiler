import type { Metadata } from "next";

import { ReviewStudio } from "@/components/review-studio";

export const metadata: Metadata = { title: "검토 스튜디오" };

export default function ReviewPage() {
  return <ReviewStudio />;
}
