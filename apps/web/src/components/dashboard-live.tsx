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
        <div
          className="dashboard-loading-grid"
          aria-label="대시보드 불러오는 중"
        >
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
            <h1>워크스페이스를 불러오지 못했습니다.</h1>
            <p>
              표시할 수 없는 수치를 추정하지 않습니다. 연결을 확인한 뒤 다시
              시도하세요.
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
            다시 시도
          </button>
        </section>
      </div>
    );
  }

  return <WorkspaceDashboard snapshot={dashboard.data} />;
}
