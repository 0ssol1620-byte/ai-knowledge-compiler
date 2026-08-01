import type { Metadata, Route } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { StructaraAppPage } from "@/components/structara-app-page";
import { StructaraAppPageLocalized } from "@/components/structara-app-page-localized";
import { ProcessingWorkspace } from "@/components/workspace/processing-workspace";
import {
  type CompatibilityQuery,
  integrityCompatibilityTarget,
} from "@/lib/integrity-compatibility";
import { getRequestLocale } from "@/lib/locale-server";

type Props = {
  params: Promise<{ id: string; view: string }>;
  searchParams: Promise<CompatibilityQuery>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { view } = await params;
  const locale = await getRequestLocale();
  return {
    title:
      locale === "ko"
        ? view === "review"
          ? "무결성 콘솔"
          : `${view === "processing" ? "처리" : "문서"} Studio`
        : view === "review"
          ? "Integrity Console"
          : `${view[0]?.toUpperCase()}${view.slice(1)} Studio`,
    robots: { index: false, follow: false },
  };
}

export default async function DocumentRoute({ params, searchParams }: Props) {
  const { id, view } = await params;
  const query = await searchParams;
  const locale = await getRequestLocale();
  if (view === "processing") {
    return (
      <Suspense
        fallback={
          <div className="st-document-loading">Opening Processing Studio…</div>
        }
      >
        <ProcessingWorkspace />
      </Suspense>
    );
  }
  if (view === "review") {
    redirect(
      integrityCompatibilityTarget(query, { documentId: id }) as Route,
    );
  }
  const definition = {
    route: `document/${view}`,
    title:
      view === "markdown"
        ? "Markdown editor"
        : view === "sources"
          ? "Source provenance"
          : view === "versions"
            ? "Document versions"
            : "Document workspace",
    description:
      view === "sources"
        ? "Explore accepted blocks by page, block, note, and entity with coverage and origin."
        : view === "versions"
          ? "Compare source, Markdown, and knowledge impact without destructive overwrite."
          : "Edit structured content with outline, source gutter, origin labels, lint, and version history.",
    action: view === "versions" ? "Compare versions" : "Export",
  };
  return locale === "ko" ? (
    <StructaraAppPageLocalized {...definition} locale={locale} />
  ) : (
    <StructaraAppPage {...definition} />
  );
}
