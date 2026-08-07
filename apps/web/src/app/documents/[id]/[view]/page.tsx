import type { Metadata } from "next";
import { Suspense } from "react";

import { ReviewStudio } from "@/components/review-studio";
import { FolyntaAppPage } from "@/components/folynta-app-page";
import { ProcessingWorkspace } from "@/components/workspace/processing-workspace";

type Props = { params: Promise<{ id: string; view: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { view } = await params;
  return {
    title: `${view[0]?.toUpperCase()}${view.slice(1)} Studio`,
    robots: { index: false, follow: false },
  };
}

export default async function DocumentRoute({ params }: Props) {
  const { view } = await params;
  if (view === "processing") {
    return (
      <Suspense
        fallback={
          <div className="fl-document-loading">Opening Processing Studio…</div>
        }
      >
        <ProcessingWorkspace />
      </Suspense>
    );
  }
  if (view === "review") return <ReviewStudio />;
  return (
    <FolyntaAppPage
      route={`document/${view}`}
      title={
        view === "markdown"
          ? "Markdown editor"
          : view === "sources"
            ? "Source provenance"
            : view === "versions"
              ? "Document versions"
              : "Document workspace"
      }
      description={
        view === "sources"
          ? "Explore accepted blocks by page, block, note, and entity with coverage and origin."
          : view === "versions"
            ? "Compare source, Markdown, and knowledge impact without destructive overwrite."
            : "Edit structured content with outline, source gutter, origin labels, lint, and version history."
      }
      action={view === "versions" ? "Compare versions" : "Export"}
    />
  );
}
