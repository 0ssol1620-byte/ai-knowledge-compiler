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
  draft: { label: "Draft", icon: FolderOpen, tone: "neutral" },
  processing: { label: "Processing", icon: Clock, tone: "blue" },
  ready: { label: "Verified", icon: CheckCircle, tone: "green" },
  attention: { label: "Review required", icon: WarningCircle, tone: "amber" },
} as const;

export function WorkspaceDashboard({
  snapshot,
  demo = false,
}: {
  snapshot: WorkspaceDashboardSnapshot;
  demo?: boolean;
}) {
  const attentionCount = snapshot.review_required + snapshot.failed_jobs;
  const coverage =
    snapshot.provenance_coverage === null
      ? "Not measured"
      : `${(snapshot.provenance_coverage * 100).toFixed(1)}%`;

  return (
    <div className="page-shell dashboard-page enterprise-dashboard">
      <nav className="dashboard-breadcrumb" aria-label="Breadcrumb">
        <Link href="/">Product site</Link>
        <CaretRight size={12} aria-hidden="true" />
        <span aria-current="page">Overview</span>
      </nav>

      <header className="dashboard-header">
        <div>
          <div className="dashboard-title-row">
            <h1>Workspace overview</h1>
            <span className="dashboard-evidence-label">
              {demo ? "Demo ledger" : "Live ledger"}
            </span>
          </div>
          <p>
            {attentionCount > 0
              ? `${formatNumber(attentionCount)} items need review. ${formatNumber(snapshot.active_jobs)} job is active.`
              : "No failed jobs or open reviews. The workspace is ready for a new document."}
          </p>
        </div>
        <div className="dashboard-actions">
          <CreateProjectButton variant="secondary" />
          <Link href="/quick-convert" className="primary-button">
            <FileArrowUp size={17} aria-hidden="true" />
            Upload document
          </Link>
        </div>
      </header>

      <section className="operations-board" aria-label="Operational priorities">
        <article className="operations-priority">
          <div className="operations-priority-heading">
            <div>
              <span>Priority queue</span>
              <h2>
                {attentionCount > 0
                  ? `${formatNumber(attentionCount)} findings need a decision`
                  : "The review queue is clear"}
              </h2>
            </div>
            <strong>{formatNumber(attentionCount)}</strong>
          </div>
          <p>
            {attentionCount > 0
              ? "Open the highest-impact finding, compare the source and candidate result, then approve or correct it without leaving Review Studio."
              : "New parser findings and failed files will appear here in impact order."}
          </p>
          <div className="operations-priority-meta">
            <span>
              <WarningCircle size={15} aria-hidden="true" />
              {formatNumber(snapshot.review_required)} open reviews
            </span>
            <span>{formatNumber(snapshot.failed_jobs)} failed files</span>
            <Link href="/review">
              Open review queue
              <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
        </article>

        <article className="operations-progress">
          <header>
            <div>
              <span>Processing now</span>
              <h2>
                {snapshot.active_jobs > 0
                  ? `${formatNumber(snapshot.active_jobs)} active job`
                  : "No active jobs"}
              </h2>
            </div>
            <Clock size={20} aria-hidden="true" />
          </header>
          <div className="operations-stage-line" aria-label="Current pipeline">
            <span data-state="done">Upload</span>
            <span data-state="done">Preflight</span>
            <span data-state={snapshot.active_jobs > 0 ? "active" : "idle"}>
              Parse
            </span>
            <span data-state="idle">Verify</span>
            <span data-state="idle">Compile</span>
          </div>
          <p>
            Page-level routes and parser events are available in Processing
            Studio.
          </p>
          <Link href="/activity">
            View processing activity
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </article>

        <aside className="operations-policy" aria-label="Workspace limits">
          <header>
            <div>
              <span>Workspace limits</span>
              <h2>Current policy</h2>
            </div>
            <Link href="/usage">Manage</Link>
          </header>
          <dl>
            <MetricRow
              label="Pages this cycle"
              value={formatNumber(snapshot.processed_pages_this_cycle)}
            />
            <MetricRow
              label="Storage"
              value={formatBytes(snapshot.storage_used_bytes)}
            />
            <MetricRow
              label="Credits available"
              value={
                snapshot.credit_remaining === null
                  ? "—"
                  : formatNumber(snapshot.credit_remaining, 2)
              }
            />
            <MetricRow
              label="Source retention"
              value={
                snapshot.retention_days === 0
                  ? "Delete after processing"
                  : `${formatNumber(snapshot.retention_days)} days`
              }
            />
          </dl>
        </aside>
      </section>

      <section className="evidence-ledger" aria-label="Evidence ledger">
        <div className="evidence-ledger-title">
          <ShieldCheck size={18} aria-hidden="true" />
          <span>
            <strong>Evidence ledger</strong>
            <small>Derived only from stored processing and audit records</small>
          </span>
        </div>
        <dl>
          <MetricRow
            label="Active projects"
            value={formatNumber(snapshot.active_project_count)}
          />
          <MetricRow label="Provenance coverage" value={coverage} />
          <MetricRow
            label="Pages sent externally"
            value={formatNumber(snapshot.external_pages)}
          />
        </dl>
      </section>

      <section className="dashboard-projects">
        <div className="dashboard-section-heading">
          <div>
            <h2>Recent projects</h2>
            <p>Projects with unresolved evidence appear first.</p>
          </div>
          <Link href="/projects">
            View all projects
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>

        {snapshot.projects.length === 0 ? (
          <div className="dashboard-empty-state">
            <FolderOpen size={24} aria-hidden="true" />
            <h3>No projects yet</h3>
            <p>
              Create a project to keep documents, reviews, and exports together.
            </p>
            <CreateProjectButton />
          </div>
        ) : (
          <div className="dashboard-table-scroll">
            <table className="dashboard-project-table">
              <caption className="sr-only">
                Recent projects with documents, status, activity, reviews,
                output, and owner
              </caption>
              <thead>
                <tr>
                  <th scope="col">Project</th>
                  <th scope="col">Docs</th>
                  <th scope="col">Status</th>
                  <th scope="col">Updated</th>
                  <th scope="col">Review</th>
                  <th scope="col">Output</th>
                  <th scope="col">Owner</th>
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
                            <small>
                              {project.description ?? "No description"}
                            </small>
                          </span>
                        </Link>
                      </th>
                      <td>{formatNumber(project.document_count)}</td>
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
                            {formatNumber(project.review_count)}
                          </Link>
                        ) : (
                          "None"
                        )}
                      </td>
                      <td>
                        <Link
                          href={`/workspace?project=${project.id}`}
                          className="dashboard-output-link"
                        >
                          {project.status === "ready"
                            ? "Open result"
                            : "Open job"}
                        </Link>
                      </td>
                      <td>{project.owner_name ?? "Workspace"}</td>
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
          Source retention, external providers, and processing region are
          checked again before upload.
        </p>
        <Link href="/settings">Review security policy</Link>
      </section>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function formatNumber(value: number, maximumFractionDigits = 0): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(
    value,
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${formatNumber(bytes)} B`;
  if (bytes < 1024 * 1024) {
    return `${formatNumber(bytes / 1024, 1)} KB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${formatNumber(bytes / (1024 * 1024), 1)} MB`;
  }
  return `${formatNumber(bytes / (1024 * 1024 * 1024), 1)} GB`;
}

function formatRelativeDate(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "No record";
  const difference = Date.now() - timestamp;
  const day = 24 * 60 * 60 * 1000;
  if (difference >= 0 && difference < day) return "Today";
  if (difference >= day && difference < day * 2) return "Yesterday";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(timestamp);
}
