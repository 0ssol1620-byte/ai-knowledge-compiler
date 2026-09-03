"use client";

import {
  ArrowRight,
  FileArrowUp,
  FolderOpen,
  PlugsConnected,
  Question,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import type { WorkspaceDashboardSnapshot } from "@/components/workspace-dashboard";
import { apiRequest } from "@/lib/api-client";

export function WorkspaceHomeLive({
  demoSnapshot,
}: {
  demoSnapshot?: WorkspaceDashboardSnapshot;
}) {
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiRequest<WorkspaceDashboardSnapshot>("/v1/dashboard"),
    enabled: !demoSnapshot,
  });

  if (demoSnapshot) return <WorkspaceHome snapshot={demoSnapshot} />;

  if (dashboard.isPending) {
    return <div className="workspace-home" aria-busy="true">Loading the next verified action…</div>;
  }
  if (dashboard.isError) {
    return (
      <div className="workspace-home">
        <section className="workspace-home-error" role="alert">
          <WarningCircle size={22} weight="fill" aria-hidden="true" />
          <div><h1>Home is unavailable.</h1><p>No workspace state is estimated while the ledger cannot be read.</p></div>
          <button type="button" className="secondary-button" onClick={() => void dashboard.refetch()}>Try again</button>
        </section>
      </div>
    );
  }

  return <WorkspaceHome snapshot={dashboard.data} />;
}

function WorkspaceHome({ snapshot }: { snapshot: WorkspaceDashboardSnapshot }) {
  const readyProject = [...snapshot.projects]
    .filter((project) => project.status === "ready")
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0];
  const attention = snapshot.review_required + snapshot.failed_jobs;
  const state = snapshot.active_jobs > 0
    ? "processing"
    : attention > 0
      ? "review"
      : readyProject
        ? "world"
        : "new";

  return (
    <div className="workspace-home">
      <p className="workspace-eyebrow">Home · next verified action</p>
      {state === "new" && (
        <HomeFocus icon={FolderOpen} eyebrow="Start here" title="Build your first World" body="Add files directly or inspect the source paths this build actually supports.">
          <Link className="primary-button" href="/intake"><FileArrowUp size={16} /> Upload files</Link>
          <Link className="secondary-button" href="/app/settings/integrations"><PlugsConnected size={16} /> Connect source</Link>
        </HomeFocus>
      )}
      {state === "processing" && (
        <HomeFocus icon={SpinnerGap} eyebrow="Compiling now" title={`${formatNumber(snapshot.active_jobs)} processing ${snapshot.active_jobs === 1 ? "job" : "jobs"}`} body="Watch persisted processing activity. Unknown work is never converted into a fake percentage.">
          <Link className="primary-button" href="/activity">Watch live <ArrowRight size={16} /></Link>
        </HomeFocus>
      )}
      {state === "review" && (
        <HomeFocus icon={WarningCircle} eyebrow="Decision required" title={`${formatNumber(attention)} ${attention === 1 ? "decision needs" : "decisions need"} you`} body="Review low-confidence or failed evidence before it can become active knowledge.">
          <Link className="primary-button" href="/review">Review decisions <ArrowRight size={16} /></Link>
        </HomeFocus>
      )}
      {state === "world" && readyProject && (
        <HomeFocus icon={Question} eyebrow="Active World" title={`${readyProject.name} is current`} body={`Last recorded project update ${formatRelativeTime(readyProject.updated_at)}. Open the World or ask with source-bound citations.`}>
          <Link className="primary-button" href="/ask">Ask <ArrowRight size={16} /></Link>
          <Link className="secondary-button" href="/knowledge-bases">Explore World</Link>
        </HomeFocus>
      )}

      <details className="workspace-home-details">
        <summary>Details <span>Projects, processing, review, pages, and provenance</span></summary>
        <dl>
          <Metric label="Projects" value={snapshot.active_project_count} />
          <Metric label="Active jobs" value={snapshot.active_jobs} />
          <Metric label="Review required" value={snapshot.review_required} />
          <Metric label="Failed jobs" value={snapshot.failed_jobs} />
          <Metric label="Pages this cycle" value={snapshot.processed_pages_this_cycle} />
          <Metric label="Provenance coverage" value={snapshot.provenance_coverage === null ? "Unavailable" : `${(snapshot.provenance_coverage * 100).toFixed(1)}%`} />
        </dl>
        <div className="workspace-home-projects">
          {snapshot.projects.map((project) => (
            <Link key={project.id} href={`/workspace?project=${project.id}`}>
              <span><strong>{project.name}</strong><small>{project.document_count} documents · {project.review_count} review</small></span>
              <em data-status={project.status}>{project.status}</em>
            </Link>
          ))}
        </div>
      </details>
    </div>
  );
}

function HomeFocus({ icon: Icon, eyebrow, title, body, children }: {
  icon: typeof FolderOpen;
  eyebrow: string;
  title: string;
  body: string;
  children: React.ReactNode;
}) {
  return (
    <section className="workspace-home-focus">
      <Icon size={28} weight="duotone" aria-hidden="true" />
      <div><p>{eyebrow}</p><h1>{title}</h1><span>{body}</span><div>{children}</div></div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{typeof value === "number" ? formatNumber(value) : value}</dd></div>;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatRelativeTime(value: string): string {
  const milliseconds = Date.now() - Date.parse(value);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "at an unavailable time";
  const minutes = Math.max(1, Math.round(milliseconds / 60_000));
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hours ago`;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(value));
}
