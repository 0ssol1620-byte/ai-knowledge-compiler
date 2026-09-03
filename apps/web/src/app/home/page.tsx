import type { Metadata } from "next";

import { DashboardLive } from "@/components/dashboard-live";
import {
  WorkspaceDashboard,
} from "@/components/workspace-dashboard";
import { demoWorkspaceSnapshot } from "@/lib/demo-workspace-snapshot";

export const metadata: Metadata = {
  title: "Workspace overview",
};

export default function DashboardPage() {
  if (process.env.NEXT_PUBLIC_AKC_DEMO_MODE !== "true") {
    return <DashboardLive />;
  }
  return <WorkspaceDashboard snapshot={demoWorkspaceSnapshot} demo />;
}
