import type { Metadata } from "next";

import { AnalyticsLive } from "@/components/analytics-live";

export const metadata: Metadata = { title: "벤치마크" };

export default function BenchmarksPage() {
  return <AnalyticsLive />;
}
