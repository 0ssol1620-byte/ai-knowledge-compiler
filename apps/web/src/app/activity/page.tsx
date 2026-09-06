import type { Metadata } from "next";

import { ActivityLive } from "@/components/activity-live";

export const metadata: Metadata = { title: "Activity" };

export default function ActivityPage() {
  return <ActivityLive />;
}
