import type { Metadata } from "next";

import { KnowledgeStudio } from "@/components/knowledge-studio";
import { ProjectsWorkspace } from "@/components/projects-workspace";
import { StructaraAppPage } from "@/components/structara-app-page";
import { StructaraAppPageLocalized } from "@/components/structara-app-page-localized";
import { getRequestLocale } from "@/lib/locale-server";
import { APP_PAGE_COPY } from "@/lib/structara-content";

type Props = { params: Promise<{ slug?: string[] }> };

// Locale-sensitive product pages must never reuse a prerendered child segment.
// Keeping this declaration next to the page prevents a mixed-language shell
// when the request cookie differs from a previous render.
export const dynamic = "force-dynamic";
export const revalidate = 0;

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
  const locale = await getRequestLocale();
  const definition = resolve(slug);
  return {
    title:
      locale === "ko"
        ? `${definition.title} · 운영 워크스페이스`
        : definition.title,
    description:
      locale === "ko"
        ? "실제 데이터와 데모 fixture의 경계를 명확히 구분하는 Structara 운영 워크스페이스입니다."
        : definition.description,
    robots: { index: false, follow: false },
  };
}

export default async function AppRoute({ params }: Props) {
  const { slug } = await params;
  const locale = await getRequestLocale();
  if ((slug?.[0] ?? "home") === "knowledge-bases") {
    return <KnowledgeStudio locale={locale} />;
  }
  if (slug?.[0] === "projects" && slug.length === 1) {
    return <ProjectsWorkspace locale={locale} />;
  }
  const definition = resolve(slug);
  return locale === "ko" ? (
    <StructaraAppPageLocalized {...definition} locale={locale} />
  ) : (
    <StructaraAppPage {...definition} />
  );
}
