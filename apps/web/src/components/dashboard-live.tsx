"use client";

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
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { CreateProjectButton } from "@/components/create-project-button";
import { UploadPanel } from "@/components/upload-panel";
import { apiRequest } from "@/lib/api-client";
import type { ProjectSummary } from "@/lib/types";

interface DashboardSummary {
  active_project_count: number;
  processed_pages: number;
  native_pages: number;
  visual_pages: number;
  provenance_coverage: number | null;
  external_pages: number;
  projects: ProjectSummary[];
}

const statusConfig = {
  draft: { label: "초안", icon: FolderOpen, tone: "neutral" },
  processing: { label: "처리 중", icon: Clock, tone: "blue" },
  ready: { label: "검증 완료", icon: CheckCircle, tone: "green" },
  attention: { label: "검토 필요", icon: WarningCircle, tone: "amber" },
} as const;

export function DashboardLive() {
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiRequest<DashboardSummary>("/v1/dashboard"),
  });

  if (dashboard.isPending) {
    return (
      <div className="page-shell dashboard-page" aria-busy="true">
        <section className="page-heading">
          <div>
            <h1>원문에서 검증 가능한 지식까지</h1>
            <p>워크스페이스의 검증된 상태를 불러오고 있습니다.</p>
          </div>
        </section>
        <div className="panel honest-state">
          <span className="spinner" aria-hidden="true" />
          <p>프로젝트와 처리 증거를 확인하는 중입니다.</p>
        </div>
      </div>
    );
  }

  if (dashboard.isError) {
    return (
      <div className="page-shell dashboard-page">
        <section className="page-heading">
          <div>
            <h1>워크스페이스를 불러오지 못했습니다.</h1>
            <p>
              표시할 수 없는 수치를 추정하지 않습니다. 연결을 확인한 뒤 다시
              시도하세요.
            </p>
          </div>
        </section>
        <div className="panel honest-state" role="alert">
          <WarningCircle size={20} weight="fill" aria-hidden="true" />
          <p>{dashboard.error.message}</p>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              void dashboard.refetch();
            }}
          >
            다시 시도
          </button>
        </div>
      </div>
    );
  }

  const summary = dashboard.data;
  const totalRouted = summary.native_pages + summary.visual_pages;
  const nativeShare =
    totalRouted > 0
      ? Math.round((summary.native_pages / totalRouted) * 100)
      : null;
  const visualShare = nativeShare === null ? null : 100 - nativeShare;

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
        <Metric
          icon={Books}
          label="활성 프로젝트"
          value={summary.active_project_count}
        />
        <Metric
          icon={FileText}
          label="처리된 페이지"
          value={summary.processed_pages.toLocaleString()}
          detail={
            nativeShare === null
              ? "아직 처리 경로 증거가 없습니다."
              : `Native ${nativeShare}% · Visual ${visualShare}%`
          }
        />
        <Metric
          icon={CheckCircle}
          label="근거 연결률"
          value={
            summary.provenance_coverage === null
              ? "—"
              : `${(summary.provenance_coverage * 100).toFixed(1)}%`
          }
          detail="검증된 source reference"
        />
        <Metric
          icon={ShieldCheck}
          label="외부 전송"
          value={`${summary.external_pages.toLocaleString()} pages`}
          detail="감사 원장 기준"
        />
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
          {summary.projects.length === 0 ? (
            <div className="honest-state compact">
              <FolderOpen size={22} aria-hidden="true" />
              <p>
                아직 프로젝트가 없습니다. 첫 프로젝트를 만들어 자료를
                추가하세요.
              </p>
            </div>
          ) : (
            <div className="project-list">
              {summary.projects.map((project) => {
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
                      <span>{project.description ?? "설명 없음"}</span>
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
          )}
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

function Metric({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Books;
  label: string;
  value: string | number;
  detail?: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-icon">
        <Icon size={20} weight="fill" aria-hidden="true" />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail ?? "현재 저장된 운영 증거 기준"}</small>
      </div>
    </article>
  );
}
