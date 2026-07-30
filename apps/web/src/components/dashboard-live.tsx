"use client";

import { WarningCircle } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";

import {
  WorkspaceDashboard,
  type WorkspaceDashboardSnapshot,
} from "@/components/workspace-dashboard";
import { apiRequest } from "@/lib/api-client";

export function DashboardLive() {
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiRequest<WorkspaceDashboardSnapshot>("/v1/dashboard"),
  });

  if (dashboard.isPending) {
    return (
      <div className="page-shell dashboard-page" aria-busy="true">
        <div className="dashboard-loading-heading">
          <span className="dashboard-loading-line wide" />
          <span className="dashboard-loading-line" />
        </div>
        <div className="dashboard-loading-grid" aria-label="Loading dashboard">
          <span />
          <span />
          <span />
        </div>
        <div className="dashboard-loading-table" />
      </div>
    );
  }

  if (dashboard.isError) {
    return (
      <div className="page-shell dashboard-page">
        <section className="dashboard-error" role="alert">
          <WarningCircle size={22} weight="fill" aria-hidden="true" />
          <div>
            <h1>The workspace could not be loaded.</h1>
            <p>
              We do not estimate unavailable metrics. Check the connection and
              try again.
            </p>
            <small>{dashboard.error.message}</small>
          </div>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              void dashboard.refetch();
            }}
          >
            Try again
          </button>
        </section>
      </div>
    );
  }

  return <WorkspaceDashboard snapshot={dashboard.data} />;
}
