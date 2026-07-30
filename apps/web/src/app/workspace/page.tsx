import type { Metadata } from "next";
import { Suspense } from "react";

import { ProcessingWorkspace } from "@/components/workspace/processing-workspace";

export const metadata: Metadata = {
  title: "처리 작업",
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
      aria-label="처리 작업 불러오는 중"
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
