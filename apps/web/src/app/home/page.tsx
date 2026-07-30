import {
  ArrowRight,
  Books,
  CheckCircle,
  Clock,
  FileText,
  FolderOpen,
  Plus,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";
import Link from "next/link";

import { CreateProjectButton } from "@/components/create-project-button";
import { DashboardLive } from "@/components/dashboard-live";
import { UploadPanel } from "@/components/upload-panel";
import { demoProjects } from "@/lib/demo-data";

export const metadata: Metadata = {
  title: "홈",
};

const statusConfig = {
  draft: { label: "초안", icon: FolderOpen, tone: "neutral" },
  processing: { label: "처리 중", icon: Clock, tone: "blue" },
  ready: { label: "검증 완료", icon: CheckCircle, tone: "green" },
  attention: { label: "검토 필요", icon: WarningCircle, tone: "amber" },
} as const;

export default function DashboardPage() {
  if (process.env.NEXT_PUBLIC_AKC_DEMO_MODE !== "true") {
    return <DashboardLive />;
  }

  return (
    <div className="page-shell dashboard-page">
      <section className="page-heading">
        <div>
          <h1>원문에서 검증 가능한 지식까지</h1>
          <p>
            자료를 업로드하면 원문 좌표와 근거를 보존한 Markdown, Obsidian
            Vault, RAG 패키지로 컴파일합니다.
          </p>
        </div>
        <CreateProjectButton />
      </section>

      <section className="overview-grid" aria-label="워크스페이스 요약">
        <article className="metric-card primary">
          <div className="metric-icon">
            <Books size={20} weight="fill" aria-hidden="true" />
          </div>
          <div>
            <span>활성 프로젝트</span>
            <strong>3</strong>
            <small>이번 주 1개 export 완료</small>
          </div>
        </article>
        <article className="metric-card">
          <div className="metric-icon">
            <FileText size={20} weight="fill" aria-hidden="true" />
          </div>
          <div>
            <span>처리된 페이지</span>
            <strong>1,284</strong>
            <small>Native 71% · Visual 29%</small>
          </div>
        </article>
        <article className="metric-card">
          <div className="metric-icon">
            <CheckCircle size={20} weight="fill" aria-hidden="true" />
          </div>
          <div>
            <span>근거 연결률</span>
            <strong>99.2%</strong>
            <small>검증된 source reference</small>
          </div>
        </article>
        <article className="metric-card">
          <div className="metric-icon">
            <ShieldCheck size={20} weight="fill" aria-hidden="true" />
          </div>
          <div>
            <span>외부 전송</span>
            <strong>0 pages</strong>
            <small>Private 기본 정책 적용 중</small>
          </div>
        </article>
      </section>

      <div className="dashboard-grid">
        <section className="panel projects-panel">
          <div className="panel-heading">
            <div>
              <h2>최근 프로젝트</h2>
              <p>검토와 export가 필요한 작업부터 표시합니다.</p>
            </div>
            <Link href="/workspace" className="text-link">
              모든 처리 작업
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
          <div className="project-list">
            {demoProjects.map((project) => {
              const status = statusConfig[project.status];
              const StatusIcon = status.icon;
              return (
                <Link
                  href={`/workspace?project=${project.id}`}
                  className="project-row"
                  key={project.id}
                >
                  <span className="project-file-icon" aria-hidden="true">
                    <FolderOpen size={20} weight="duotone" />
                  </span>
                  <span className="project-main">
                    <strong>{project.name}</strong>
                    <span>{project.description}</span>
                  </span>
                  <span className="project-meta">
                    <span>{project.document_count}개 문서</span>
                    {project.review_count > 0 && (
                      <span>{project.review_count}개 검토</span>
                    )}
                  </span>
                  <span className={`status-badge ${status.tone}`}>
                    <StatusIcon size={14} weight="fill" aria-hidden="true" />
                    {status.label}
                  </span>
                  <ArrowRight
                    className="row-arrow"
                    size={16}
                    aria-hidden="true"
                  />
                </Link>
              );
            })}
          </div>
          <CreateProjectButton
            variant="inline"
            label={
              <>
                <Plus size={16} aria-hidden="true" />새 프로젝트 만들기
              </>
            }
          />
        </section>

        <UploadPanel />
      </div>
    </div>
  );
}
