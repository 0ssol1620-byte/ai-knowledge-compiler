import type { Metadata } from "next";

import { ProjectsWorkspace } from "@/components/projects-workspace";
import { getRequestLocale } from "@/lib/locale-server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return {
    title: locale === "ko" ? "프로젝트" : "Projects",
    description:
      locale === "ko"
        ? "원본 연결 문서 프로젝트, 검토 의무, 소유권과 지식 출력을 관리합니다."
        : "Manage source-bound document projects, review obligations, ownership, and knowledge outputs.",
    robots: { index: false, follow: false },
  };
}

export default async function ProjectsPage() {
  const locale = await getRequestLocale();
  return <ProjectsWorkspace locale={locale} />;
}
