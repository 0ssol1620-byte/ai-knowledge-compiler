import type { Metadata } from "next";

import { FolyntaCreativeReview } from "@/components/creative-review/folynta-creative-review";

export const metadata: Metadata = {
  title: "FOLYNTA creative direction review",
  robots: { index: false, follow: false },
};

type Direction = "folio" | "axis" | "plane" | "marks";

export default async function FolyntaCreativeReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ direction?: string }>;
}) {
  const requested = (await searchParams).direction;
  const direction: Direction =
    requested === "axis" || requested === "plane" || requested === "marks"
      ? requested
      : "folio";

  return <FolyntaCreativeReview direction={direction} />;
}
