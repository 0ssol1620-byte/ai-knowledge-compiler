"use client";

import {
  ArrowDown,
  ArrowRight,
  CheckSquare,
  ClipboardText,
  FolderOpen,
  GridFour,
  List,
  MagnifyingGlass,
  Plus,
  WarningCircle,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import type { WorkspaceDashboardSnapshot } from "@/components/workspace-dashboard";
import { apiRequest } from "@/lib/api-client";
import { demoProjects } from "@/lib/demo-data";
import type { StructaraLocale } from "@/lib/locale";
import { localeLanguageTag as localeTag } from "@/lib/locale";
import type { ProjectSummary } from "@/lib/types";

type StatusFilter = "all" | ProjectSummary["status"];
type SortKey = "updated" | "name" | "documents" | "reviews";
type ViewMode = "table" | "grid";

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

const COPY = {
  en: {
    loading: "Loading project operations…",
    errorTitle: "Projects could not be loaded",
    errorBody:
      "No project count or status is estimated when the workspace API is unavailable.",
    retry: "Retry",
    eyebrow: "Knowledge operations",
    title: "Projects",
    description:
      "Organize source files, integrity findings, knowledge outputs, and retention policy around a durable project boundary.",
    newProject: "New project",
    summaryLabel: "Project summary",
    total: "Total",
    ready: "Ready",
    processing: "Processing",
    attention: "Needs attention",
    toolbarLabel: "Project filters and view controls",
    searchPlaceholder: "Search projects, owners, or purpose",
    searchLabel: "Search projects",
    status: "Status",
    allStatuses: "All statuses",
    draft: "Draft",
    sort: "Sort",
    updated: "Recently updated",
    name: "Project name",
    documentCount: "Document count",
    reviewCount: "Integrity finding count",
    viewLabel: "Project view",
    table: "Table",
    grid: "Grid",
    selected: "selected",
    copied: "Copied",
    copyIds: "Copy project IDs",
    clearSelection: "Clear selection",
    emptyTitle: "No projects match this view",
    emptyBody:
      "Clear the search or status filter. No hidden project is inferred.",
    reset: "Reset filters",
    visible: "visible project(s)",
    selectVisible: "Select visible projects",
    deselectVisible: "Deselect visible projects",
    project: "Project",
    documents: "Documents",
    review: "Integrity",
    owner: "Owner",
    updatedColumn: "Updated",
    open: "Open",
    select: "Select",
    deselect: "Deselect",
    noDescription: "No project description",
    workspace: "Workspace",
    openReview: "Unresolved or quarantined",
    ledger:
      "Project status, owner, and counts are loaded from the workspace ledger; unavailable data is never estimated.",
    notRecorded: "Not recorded",
  },
  ko: {
    loading: "프로젝트 운영 정보를 불러오는 중…",
    errorTitle: "프로젝트를 불러올 수 없습니다",
    errorBody:
      "워크스페이스 API를 사용할 수 없을 때 프로젝트 수나 상태를 추정하지 않습니다.",
    retry: "다시 시도",
    eyebrow: "지식 운영",
    title: "프로젝트",
    description:
      "원본 파일, 무결성 상태, 지식 출력과 보존 정책을 지속 가능한 프로젝트 경계 안에서 관리합니다.",
    newProject: "새 프로젝트",
    summaryLabel: "프로젝트 요약",
    total: "전체",
    ready: "준비 완료",
    processing: "처리 중",
    attention: "확인 필요",
    toolbarLabel: "프로젝트 필터와 보기 설정",
    searchPlaceholder: "프로젝트, 소유자 또는 목적 검색",
    searchLabel: "프로젝트 검색",
    status: "상태",
    allStatuses: "모든 상태",
    draft: "초안",
    sort: "정렬",
    updated: "최근 업데이트",
    name: "프로젝트 이름",
    documentCount: "문서 수",
    reviewCount: "무결성 예외 수",
    viewLabel: "프로젝트 보기",
    table: "표",
    grid: "카드",
    selected: "개 선택됨",
    copied: "복사됨",
    copyIds: "프로젝트 ID 복사",
    clearSelection: "선택 해제",
    emptyTitle: "조건에 맞는 프로젝트가 없습니다",
    emptyBody:
      "검색어 또는 상태 필터를 초기화하세요. 숨겨진 프로젝트를 임의로 추정하지 않습니다.",
    reset: "필터 초기화",
    visible: "개 프로젝트 표시",
    selectVisible: "표시된 프로젝트 모두 선택",
    deselectVisible: "표시된 프로젝트 선택 해제",
    project: "프로젝트",
    documents: "문서",
    review: "무결성",
    owner: "소유자",
    updatedColumn: "업데이트",
    open: "열기",
    select: "선택",
    deselect: "선택 해제",
    noDescription: "프로젝트 설명 없음",
    workspace: "워크스페이스",
    openReview: "미해결 또는 격리",
    ledger:
      "프로젝트 상태, 소유자와 건수는 워크스페이스 원장에서 불러오며 사용할 수 없는 데이터는 추정하지 않습니다.",
    notRecorded: "기록 없음",
  },
} as const;

export function ProjectsWorkspace({
  locale = "en",
}: {
  locale?: StructaraLocale;
}) {
  const copy = COPY[locale];
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<SortKey>("updated");
  const [view, setView] = useState<ViewMode>("table");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [copied, setCopied] = useState(false);

  const dashboard = useQuery({
    queryKey: ["projects-dashboard"],
    queryFn: () => apiRequest<WorkspaceDashboardSnapshot>("/v1/dashboard"),
    enabled: !DEMO_MODE,
  });

  const projects = useMemo<ProjectSummary[]>(
    () =>
      DEMO_MODE
        ? demoProjects.map((project, index) => ({
            ...project,
            owner_name:
              index === 0
                ? locale === "ko"
                  ? "데모 김"
                  : "Demo Kim"
                : locale === "ko"
                  ? "샘플 팀"
                  : "Sample team",
          }))
        : (dashboard.data?.projects ?? []),
    [dashboard.data?.projects, locale],
  );

  const filtered = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    return projects
      .filter((project) => {
        const matchesSearch =
          normalized.length === 0 ||
          `${project.name} ${project.description ?? ""} ${project.owner_name ?? ""}`
            .toLowerCase()
            .includes(normalized);
        return matchesSearch && (status === "all" || project.status === status);
      })
      .sort((left, right) => {
        if (sort === "name")
          return left.name.localeCompare(right.name, localeTag(locale));
        if (sort === "documents")
          return right.document_count - left.document_count;
        if (sort === "reviews") return right.review_count - left.review_count;
        return Date.parse(right.updated_at) - Date.parse(left.updated_at);
      });
  }, [locale, projects, search, sort, status]);

  const allVisibleSelected =
    filtered.length > 0 &&
    filtered.every((project) => selected.has(project.id));

  function toggleProject(projectId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
    setCopied(false);
  }

  function toggleAllVisible() {
    setSelected((current) => {
      const next = new Set(current);
      if (allVisibleSelected)
        filtered.forEach((project) => next.delete(project.id));
      else filtered.forEach((project) => next.add(project.id));
      return next;
    });
    setCopied(false);
  }

  async function copySelectedIds() {
    const ids = [...selected];
    if (ids.length === 0) return;
    await navigator.clipboard.writeText(ids.join("\n"));
    setCopied(true);
  }

  if (dashboard.isPending && !DEMO_MODE) {
    return <div className="st-document-loading">{copy.loading}</div>;
  }

  if (dashboard.isError && !DEMO_MODE) {
    return (
      <div className="page-shell projects-page">
        <section className="dashboard-error" role="alert">
          <WarningCircle size={24} weight="fill" aria-hidden="true" />
          <div>
            <h1>{copy.errorTitle}</h1>
            <p>{copy.errorBody}</p>
            <small>{dashboard.error.message}</small>
          </div>
          <button
            type="button"
            className="secondary-button"
            onClick={() => void dashboard.refetch()}
          >
            {copy.retry}
          </button>
        </section>
      </div>
    );
  }

  return (
    <div
      className="page-shell projects-page"
      data-project-mode={DEMO_MODE ? "sample" : "live"}
    >
      <header className="projects-hero">
        <div>
          <p className="eyebrow">{copy.eyebrow}</p>
          <h1>{copy.title}</h1>
          <p>{copy.description}</p>
        </div>
        <Link className="primary-button" href="/intake" data-app-header-action>
          <Plus size={16} /> {copy.newProject}
        </Link>
      </header>

      <section className="projects-summary" aria-label={copy.summaryLabel}>
        <div>
          <span>{copy.total}</span>
          <strong>{projects.length}</strong>
        </div>
        <div>
          <span>{copy.ready}</span>
          <strong>
            {projects.filter((project) => project.status === "ready").length}
          </strong>
        </div>
        <div>
          <span>{copy.processing}</span>
          <strong>
            {
              projects.filter((project) => project.status === "processing")
                .length
            }
          </strong>
        </div>
        <div>
          <span>{copy.attention}</span>
          <strong>
            {
              projects.filter((project) => project.status === "attention")
                .length
            }
          </strong>
        </div>
      </section>

      <section className="projects-toolbar" aria-label={copy.toolbarLabel}>
        <label className="projects-search">
          <MagnifyingGlass size={16} aria-hidden="true" />
          <input
            value={search}
            onInput={(event) => setSearch(event.currentTarget.value)}
            placeholder={copy.searchPlaceholder}
            aria-label={copy.searchLabel}
          />
        </label>
        <label>
          <span>{copy.status}</span>
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.currentTarget.value as StatusFilter)
            }
          >
            <option value="all">{copy.allStatuses}</option>
            <option value="draft">{copy.draft}</option>
            <option value="processing">{copy.processing}</option>
            <option value="ready">{copy.ready}</option>
            <option value="attention">{copy.attention}</option>
          </select>
        </label>
        <label>
          <span>{copy.sort}</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.currentTarget.value as SortKey)}
          >
            <option value="updated">{copy.updated}</option>
            <option value="name">{copy.name}</option>
            <option value="documents">{copy.documentCount}</option>
            <option value="reviews">{copy.reviewCount}</option>
          </select>
        </label>
        <div
          className="projects-view-switch"
          role="group"
          aria-label={copy.viewLabel}
        >
          <button
            type="button"
            className={view === "table" ? "active" : undefined}
            aria-pressed={view === "table"}
            onClick={() => setView("table")}
          >
            <List size={16} />
            <span>{copy.table}</span>
          </button>
          <button
            type="button"
            className={view === "grid" ? "active" : undefined}
            aria-pressed={view === "grid"}
            onClick={() => setView("grid")}
          >
            <GridFour size={16} />
            <span>{copy.grid}</span>
          </button>
        </div>
      </section>

      {selected.size > 0 && (
        <section className="projects-bulk-bar" aria-live="polite">
          <span>
            <CheckSquare size={16} /> {selected.size} {copy.selected}
          </span>
          <button type="button" onClick={() => void copySelectedIds()}>
            <ClipboardText size={15} /> {copied ? copy.copied : copy.copyIds}
          </button>
          <button type="button" onClick={() => setSelected(new Set())}>
            {copy.clearSelection}
          </button>
        </section>
      )}

      {filtered.length === 0 ? (
        <section className="projects-empty-state">
          <FolderOpen size={34} aria-hidden="true" />
          <h2>{copy.emptyTitle}</h2>
          <p>{copy.emptyBody}</p>
          <button
            type="button"
            className="secondary-button compact"
            onClick={() => {
              setSearch("");
              setStatus("all");
            }}
          >
            {copy.reset}
          </button>
        </section>
      ) : view === "table" ? (
        <div className="projects-table-wrap">
          <table className="projects-table">
            <caption>
              {filtered.length} {copy.visible}
            </caption>
            <thead>
              <tr>
                <th>
                  <button
                    type="button"
                    aria-label={
                      allVisibleSelected
                        ? copy.deselectVisible
                        : copy.selectVisible
                    }
                    aria-pressed={allVisibleSelected}
                    onClick={toggleAllVisible}
                  >
                    <CheckSquare size={17} />
                  </button>
                </th>
                <th>{copy.project}</th>
                <th>{copy.status}</th>
                <th>{copy.documents}</th>
                <th>{copy.review}</th>
                <th>{copy.owner}</th>
                <th>{copy.updatedColumn}</th>
                <th>
                  <span className="sr-only">{copy.open}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((project) => (
                <tr key={project.id} data-selected={selected.has(project.id)}>
                  <td>
                    <button
                      type="button"
                      aria-label={`${selected.has(project.id) ? copy.deselect : copy.select} ${project.name}`}
                      aria-pressed={selected.has(project.id)}
                      onClick={() => toggleProject(project.id)}
                    >
                      <CheckSquare
                        size={17}
                        weight={selected.has(project.id) ? "fill" : "regular"}
                      />
                    </button>
                  </td>
                  <th scope="row">
                    <Link href={`/app/projects/${project.id}/overview`}>
                      <strong>{project.name}</strong>
                      <small>{project.description || copy.noDescription}</small>
                    </Link>
                  </th>
                  <td>
                    <span
                      className="project-status"
                      data-status={project.status}
                    >
                      {statusLabel(project.status, locale)}
                    </span>
                  </td>
                  <td>
                    {project.document_count.toLocaleString(localeTag(locale))}
                  </td>
                  <td>
                    {project.review_count.toLocaleString(localeTag(locale))}
                  </td>
                  <td>{project.owner_name || copy.workspace}</td>
                  <td>
                    <time dateTime={project.updated_at}>
                      {formatUpdated(
                        project.updated_at,
                        locale,
                        copy.notRecorded,
                      )}
                    </time>
                  </td>
                  <td>
                    <Link
                      className="icon-button compact"
                      href={`/app/projects/${project.id}/overview`}
                      aria-label={`${copy.open} ${project.name}`}
                    >
                      <ArrowRight size={16} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="projects-card-grid">
          {filtered.map((project) => (
            <article key={project.id} data-selected={selected.has(project.id)}>
              <header>
                <button
                  type="button"
                  aria-label={`${selected.has(project.id) ? copy.deselect : copy.select} ${project.name}`}
                  aria-pressed={selected.has(project.id)}
                  onClick={() => toggleProject(project.id)}
                >
                  <CheckSquare
                    size={17}
                    weight={selected.has(project.id) ? "fill" : "regular"}
                  />
                </button>
                <span className="project-status" data-status={project.status}>
                  {statusLabel(project.status, locale)}
                </span>
              </header>
              <Link href={`/app/projects/${project.id}/overview`}>
                <h2>{project.name}</h2>
                <p>{project.description || copy.noDescription}</p>
              </Link>
              <dl>
                <div>
                  <dt>{copy.documents}</dt>
                  <dd>
                    {project.document_count.toLocaleString(localeTag(locale))}
                  </dd>
                </div>
                <div>
                  <dt>{copy.openReview}</dt>
                  <dd>
                    {project.review_count.toLocaleString(localeTag(locale))}
                  </dd>
                </div>
              </dl>
              <footer>
                <span>{project.owner_name || copy.workspace}</span>
                <time dateTime={project.updated_at}>
                  {formatUpdated(project.updated_at, locale, copy.notRecorded)}
                </time>
              </footer>
            </article>
          ))}
        </div>
      )}

      <footer className="projects-ledger-note">
        <ArrowDown size={14} /> {copy.ledger}
      </footer>
    </div>
  );
}

function statusLabel(
  status: ProjectSummary["status"],
  locale: StructaraLocale,
): string {
  return locale === "ko"
    ? {
        draft: "초안",
        processing: "처리 중",
        ready: "준비 완료",
        attention: "확인 필요",
      }[status]
    : {
        draft: "Draft",
        processing: "Processing",
        ready: "Ready",
        attention: "Needs attention",
      }[status];
}

function formatUpdated(
  value: string,
  locale: StructaraLocale,
  fallback: string,
): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return fallback;
  return new Intl.DateTimeFormat(localeTag(locale), {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(timestamp);
}
