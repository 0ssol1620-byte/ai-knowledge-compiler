import type { Metadata } from "next";

import { AnalyticsLive } from "@/components/analytics-live";

export const metadata: Metadata = {
  title: "제품 분석",
};

export default function AnalyticsPage() {
  return <AnalyticsLive />;
}
