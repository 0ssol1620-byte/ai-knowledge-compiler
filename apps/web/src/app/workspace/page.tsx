import type { Metadata } from "next";
import { Suspense } from "react";

import { ProcessingWorkspace } from "@/components/workspace/processing-workspace";
import { getRequestLocale } from "@/lib/locale-server";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return {
    title: locale === "ko" ? "처리 워크스페이스" : "Processing workspace",
  };
}

export default async function WorkspacePage() {
  const locale = await getRequestLocale();
  return (
    <Suspense fallback={<WorkspaceSkeleton locale={locale} />}>
      <ProcessingWorkspace />
    </Suspense>
  );
}

function WorkspaceSkeleton({ locale }: { locale: "en" | "ko" }) {
  return (
    <div
      className="workspace-skeleton"
      aria-label={
        locale === "ko"
          ? "처리 워크스페이스 불러오는 중"
          : "Loading processing workspace"
      }
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
