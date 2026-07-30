"use client";

import {
  ArrowRight,
  CaretRight,
  CheckCircle,
  Clock,
  FileArrowUp,
  FolderOpen,
  HardDrives,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import Link from "next/link";

import { CreateProjectButton } from "@/components/create-project-button";
import type { ProjectSummary } from "@/lib/types";

export interface WorkspaceDashboardSnapshot {
  active_project_count: number;
  active_jobs: number;
  review_required: number;
  failed_jobs: number;
  processed_pages_this_cycle: number;
  storage_used_bytes: number;
  credit_remaining: number | null;
  retention_days: number;
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

export function WorkspaceDashboard({
  snapshot,
  demo = false,
}: {
  snapshot: WorkspaceDashboardSnapshot;
  demo?: boolean;
}) {
  const attentionCount = snapshot.review_required + snapshot.failed_jobs;

  return (
    <div className="page-shell dashboard-page">
      <nav className="dashboard-breadcrumb" aria-label="현재 위치">
        <Link href="/">제품 사이트</Link>
        <CaretRight size={12} aria-hidden="true" />
        <span aria-current="page">대시보드</span>
      </nav>

      <header className="dashboard-header">
        <div>
          <div className="dashboard-title-row">
            <h1>워크스페이스</h1>
            <span className="dashboard-evidence-label">
              {demo ? "샘플 데이터" : "운영 원장 기준"}
            </span>
          </div>
          <p>
            {attentionCount > 0
              ? `지금 확인할 항목 ${attentionCount.toLocaleString("ko-KR")}건과 진행 중인 작업 ${snapshot.active_jobs.toLocaleString("ko-KR")}건이 있습니다.`
              : "지금 확인할 오류나 검토 항목이 없습니다. 새 문서를 바로 처리할 수 있습니다."}
          </p>
        </div>
        <div className="dashboard-actions">
          <CreateProjectButton variant="secondary" />
          <Link href="/quick-convert" className="primary-button">
            <FileArrowUp size={17} aria-hidden="true" />새 업로드
          </Link>
        </div>
      </header>

      <section className="dashboard-command-center" aria-label="다음 행동">
        <article className="dashboard-next-action">
          <div className="dashboard-action-heading">
            <span className="dashboard-action-icon" aria-hidden="true">
              <Clock size={19} />
            </span>
            <div>
              <h2>처리 중</h2>
              <p>큐와 실행 중인 작업</p>
            </div>
            <strong>{snapshot.active_jobs.toLocaleString("ko-KR")}</strong>
          </div>
          <p className="dashboard-action-copy">
            {snapshot.active_jobs > 0
              ? "페이지별 처리 경로와 실제 이벤트를 Processing Studio에서 확인하세요."
              : "현재 실행 중인 작업이 없습니다."}
          </p>
          <Link href="/activity" className="dashboard-action-link">
            처리 활동 보기
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </article>

        <article
          className={`dashboard-next-action ${attentionCount > 0 ? "attention" : ""}`}
        >
          <div className="dashboard-action-heading">
            <span className="dashboard-action-icon" aria-hidden="true">
              <WarningCircle size={19} />
            </span>
            <div>
              <h2>검토 필요</h2>
              <p>
                열린 검토 {snapshot.review_required.toLocaleString("ko-KR")} ·
                실패 {snapshot.failed_jobs.toLocaleString("ko-KR")}
              </p>
            </div>
            <strong>{attentionCount.toLocaleString("ko-KR")}</strong>
          </div>
          <p className="dashboard-action-copy">
            {attentionCount > 0
              ? "영향도가 높은 항목부터 원문과 후보 결과를 비교할 수 있습니다."
              : "검토 대기 또는 실패한 작업이 없습니다."}
          </p>
          <Link href="/review" className="dashboard-action-link">
            검토 큐 열기
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </article>

        <aside className="dashboard-usage" aria-label="사용 현황">
          <div className="dashboard-usage-heading">
            <div>
              <h2>사용 현황</h2>
              <p>현재 워크스페이스 정책 기준</p>
            </div>
            <Link href="/usage">자세히</Link>
          </div>
          <dl>
            <div>
              <dt>이번 주기 처리</dt>
              <dd>
                {snapshot.processed_pages_this_cycle.toLocaleString("ko-KR")}쪽
              </dd>
            </div>
            <div>
              <dt>저장공간</dt>
              <dd>{formatBytes(snapshot.storage_used_bytes)}</dd>
            </div>
            <div>
              <dt>사용 가능 크레딧</dt>
              <dd>
                {snapshot.credit_remaining === null
                  ? "—"
                  : snapshot.credit_remaining.toLocaleString("ko-KR", {
                      maximumFractionDigits: 2,
                    })}
              </dd>
            </div>
            <div>
              <dt>원본 보존</dt>
              <dd>
                {snapshot.retention_days === 0
                  ? "처리 후 삭제"
                  : `${snapshot.retention_days.toLocaleString("ko-KR")}일`}
              </dd>
            </div>
          </dl>
        </aside>
      </section>

      <section className="dashboard-evidence-strip" aria-label="운영 증거 요약">
        <div>
          <span>활성 프로젝트</span>
          <strong>
            {snapshot.active_project_count.toLocaleString("ko-KR")}
          </strong>
        </div>
        <div>
          <span>근거 연결률</span>
          <strong>
            {snapshot.provenance_coverage === null
              ? "측정 전"
              : `${(snapshot.provenance_coverage * 100).toFixed(1)}%`}
          </strong>
        </div>
        <div>
          <span>외부 전송 페이지</span>
          <strong>{snapshot.external_pages.toLocaleString("ko-KR")}</strong>
        </div>
        <div className="dashboard-policy-state">
          <ShieldCheck size={16} aria-hidden="true" />
          <span>수치는 저장된 처리·감사 증거에서만 집계됩니다.</span>
        </div>
      </section>

      <section className="dashboard-projects">
        <div className="dashboard-section-heading">
          <div>
            <h2>최근 프로젝트</h2>
            <p>검토가 필요한 프로젝트를 먼저 확인하고 결과로 이동합니다.</p>
          </div>
          <Link href="/projects">
            전체 프로젝트
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>

        {snapshot.projects.length === 0 ? (
          <div className="dashboard-empty">
            <FolderOpen size={22} aria-hidden="true" />
            <div>
              <strong>아직 프로젝트가 없습니다.</strong>
              <p>첫 프로젝트를 만들거나 빠른 변환으로 문서를 처리하세요.</p>
            </div>
          </div>
        ) : (
          <div className="dashboard-table-scroll">
            <table className="dashboard-project-table">
              <caption className="sr-only">
                최근 프로젝트의 문서 수, 상태, 최근 활동, 검토 항목, 출력과
                담당자
              </caption>
              <thead>
                <tr>
                  <th scope="col">프로젝트</th>
                  <th scope="col">문서</th>
                  <th scope="col">상태</th>
                  <th scope="col">최근 활동</th>
                  <th scope="col">검토</th>
                  <th scope="col">출력</th>
                  <th scope="col">담당자</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.projects.map((project) => {
                  const status = statusConfig[project.status];
                  const StatusIcon = status.icon;
                  return (
                    <tr key={project.id}>
                      <th scope="row">
                        <Link href={`/workspace?project=${project.id}`}>
                          <span
                            className="project-table-icon"
                            aria-hidden="true"
                          >
                            <FolderOpen size={17} />
                          </span>
                          <span>
                            <strong>{project.name}</strong>
                            <small>{project.description ?? "설명 없음"}</small>
                          </span>
                        </Link>
                      </th>
                      <td>{project.document_count.toLocaleString("ko-KR")}</td>
                      <td>
                        <span className={`status-badge ${status.tone}`}>
                          <StatusIcon
                            size={13}
                            weight="fill"
                            aria-hidden="true"
                          />
                          {status.label}
                        </span>
                      </td>
                      <td>
                        <time dateTime={project.updated_at}>
                          {formatRelativeDate(project.updated_at)}
                        </time>
                      </td>
                      <td>
                        {project.review_count > 0 ? (
                          <Link
                            href={`/review?project=${project.id}`}
                            className="dashboard-review-link"
                          >
                            {project.review_count.toLocaleString("ko-KR")}건
                          </Link>
                        ) : (
                          "없음"
                        )}
                      </td>
                      <td>
                        <Link
                          href={`/workspace?project=${project.id}`}
                          className="dashboard-output-link"
                        >
                          {project.status === "ready"
                            ? "결과 보기"
                            : "작업 보기"}
                        </Link>
                      </td>
                      <td>{project.owner_name ?? "워크스페이스"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="dashboard-security-note">
        <HardDrives size={17} aria-hidden="true" />
        <p>
          원본 보존, 외부 provider, 처리 리전 정책은 업로드 전에 다시 확인할 수
          있습니다.
        </p>
        <Link href="/settings">보안 정책 확인</Link>
      </section>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes.toLocaleString("ko-KR")} B`;
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toLocaleString("ko-KR", { maximumFractionDigits: 1 })} KB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toLocaleString("ko-KR", { maximumFractionDigits: 1 })} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toLocaleString("ko-KR", { maximumFractionDigits: 1 })} GB`;
}

function formatRelativeDate(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "기록 없음";
  const difference = Date.now() - timestamp;
  const day = 24 * 60 * 60 * 1000;
  if (difference >= 0 && difference < day) return "오늘";
  if (difference >= day && difference < day * 2) return "어제";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
  }).format(timestamp);
}
