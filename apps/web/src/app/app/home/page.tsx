import type { Metadata } from "next";

import { WorkspaceHomeLive } from "@/components/workspace-home-live";
import { demoWorkspaceSnapshot } from "@/lib/demo-workspace-snapshot";

export const metadata: Metadata = {
  title: "Home",
  description: "The next verified action for this TAVONEL workspace.",
  robots: { index: false, follow: false },
};

export default function HomePage() {
  return (
    <WorkspaceHomeLive
      demoSnapshot={
        process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true"
          ? demoWorkspaceSnapshot
          : undefined
      }
    />
  );
}
