import type { Metadata } from "next";

import { TavonelAppPage } from "@/components/tavonel-app-page";
import { APP_PAGE_COPY } from "@/lib/tavonel-content";

type Props = { params: Promise<{ slug?: string[] }> };

function resolve(slug: string[] | undefined) {
  const parts = slug?.length ? slug : ["home"];
  const route = parts.join("/");
  const top = parts[0] ?? "home";

  if (top === "projects" && parts.length >= 2) {
    const view = parts.at(-1) ?? "overview";
    return {
      route,
      title:
        view === "documents"
          ? "Project documents"
          : view === "graph"
            ? "Project knowledge graph"
            : view === "knowledge"
              ? "Project knowledge"
              : view === "exports"
                ? "Project exports"
                : "DART Annual Report",
      description:
        view === "documents"
          ? "Inspect versions, pages, processing, review, knowledge, retention, and output files."
          : "Source coverage, knowledge health, recent activity, documents, and notes.",
      action: view === "exports" ? "New export" : "Upload documents",
    };
  }

  if (top === "settings" || top === "admin") {
    const section = parts[1] ?? (top === "admin" ? "jobs" : "organization");
    return {
      route,
      title: `${top === "admin" ? "Admin · " : ""}${section[0]!.toUpperCase()}${section.slice(1)}`,
      description:
        "Organization policy with impact preview, re-authentication, audit, and durable confirmation.",
      action: top === "admin" ? "Open audit" : "Review changes",
    };
  }

  return { route, ...(APP_PAGE_COPY[top] ?? APP_PAGE_COPY.home!) };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const definition = resolve(slug);
  return {
    title: definition.title,
    description: definition.description,
    robots: { index: false, follow: false },
  };
}

export default async function AppRoute({ params }: Props) {
  const { slug } = await params;
  return <TavonelAppPage {...resolve(slug)} />;
}
