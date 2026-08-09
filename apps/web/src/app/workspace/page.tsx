import type { Metadata } from "next";
import { Suspense } from "react";

import { ProcessingWorkspace } from "@/components/workspace/processing-workspace";

export const metadata: Metadata = {
  title: "Processing workspace",
};

export default function WorkspacePage() {
  return (
    <Suspense fallback={<WorkspaceSkeleton />}>
      <ProcessingWorkspace />
    </Suspense>
  );
}

function WorkspaceSkeleton() {
  return (
    <div
      className="workspace-skeleton"
      aria-label="Loading processing workspace"
      aria-busy="true"
    >
      <div className="skeleton-bar" />
      <div className="skeleton-columns">
        <div />
        <div />
        <div />
      </div>
    </div>
  );
}
