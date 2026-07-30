import type { Metadata } from "next";

import { AnalyticsLive } from "@/components/analytics-live";

export const metadata: Metadata = {
  title: "Product analytics",
};

export default function AnalyticsPage() {
  return <AnalyticsLive />;
}
