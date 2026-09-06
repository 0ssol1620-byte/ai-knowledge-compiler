"use client";

import { ArrowRight, Clock, Pulse, WarningCircle } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import type { WorkspaceDashboardSnapshot } from "@/components/workspace-dashboard";
import { apiRequest } from "@/lib/api-client";

export function ActivityLive() {
  const activity = useQuery({
    queryKey: ["activity-dashboard"],
    queryFn: () => apiRequest<WorkspaceDashboardSnapshot>("/v1/dashboard"),
  });

  if (activity.isPending) {
    return <div className="activity-live" aria-busy="true">Loading activity ledger…</div>;
  }
  if (activity.isError) {
    return (
      <div className="activity-live">
        <section className="activity-unavailable" role="alert">
          <WarningCircle size={20} />
          <h1>Activity unavailable</h1>
          <p>No activity is estimated while the tenant ledger is unavailable.</p>
        </section>
      </div>
    );
  }

  const snapshot = activity.data;
  const projects = [...snapshot.projects].sort((left, right) =>
    right.updated_at.localeCompare(left.updated_at),
  );
  return (
    <div className="activity-live">
      <header className="activity-header">
        <div>
          <p className="workspace-eyebrow">Activity · tenant ledger</p>
          <h1>Runs and changes, in one place.</h1>
          <p>
            Project status comes from the authenticated dashboard projection.
            Job event details remain in each processing workspace.
          </p>
        </div>
        <div>
          <span><Pulse size={16} /> {snapshot.active_jobs} active</span>
          <span>{snapshot.failed_jobs} failed</span>
        </div>
      </header>
      <section className="activity-register" aria-label="Recent project activity">
        <div className="activity-register-head">
          <span>Project</span><span>Status</span><span>Updated</span><span>Open</span>
        </div>
        {projects.length === 0 ? (
          <p className="activity-empty">No project activity is present yet.</p>
        ) : projects.map((project) => (
          <article key={project.id}>
            <div>
              <strong>{project.name}</strong>
              <small>{project.description || "No description"}</small>
            </div>
            <span data-status={project.status}>{project.status}</span>
            <time dateTime={project.updated_at}>
              <Clock size={14} /> {new Intl.DateTimeFormat("en", {
                dateStyle: "medium",
                timeStyle: "short",
              }).format(new Date(project.updated_at))}
            </time>
            <Link href={`/workspace?project=${project.id}`}>Workspace <ArrowRight size={14} /></Link>
          </article>
        ))}
      </section>
    </div>
  );
}
