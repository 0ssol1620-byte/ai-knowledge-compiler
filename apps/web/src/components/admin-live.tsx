"use client";

import {
  ArrowClockwise,
  CheckCircle,
  Database,
  Queue,
  ShieldCheck,
  Warning,
} from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DispatchDlqPanel } from "@/components/dispatch-dlq-panel";
import { ModelOperationsPanel } from "@/components/model-operations-panel";
import { apiRequest, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import {
  normalizeAdminHealthResponse,
  type AdminDependency,
  type AdminHealthSnapshot,
  type AdminIntervention,
} from "@/lib/operations-contracts";

export function AdminLive() {
  const roles = useAuthStore((state) => state.roles);
  const [activeJobId, setActiveJobId] = useState<string>();
  const isAdmin = roles.some((role) =>
    ["owner", "admin"].includes(role.toLowerCase()),
  );
  const health = useQuery({
    queryKey: ["admin-health"],
    queryFn: async () =>
      normalizeAdminHealthResponse(
        await apiRequest<unknown>("/v1/admin/health"),
      ),
    enabled: isAdmin,
    refetchInterval: 30_000,
  });
  const retry = useMutation({
    mutationFn: (actionUrl: string) =>
      apiRequest<unknown>(actionUrl, {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      }),
    onSettled: async () => {
      setActiveJobId(undefined);
      await health.refetch();
    },
  });

  if (!isAdmin) {
    return (
      <AdminState
        title="운영 콘솔 접근 제한"
        message="Owner 또는 Admin 역할이 확인된 세션만 운영 상태를 조회할 수 있습니다."
        denied
      />
    );
  }

  if (health.isPending) {
    return (
      <AdminState
        title="운영 콘솔"
        message="실제 서비스 상태와 개입 대상을 불러오고 있습니다."
        busy
      />
    );
  }

  if (health.isError) {
    const denied =
      health.error instanceof ApiError && health.error.status === 403;
    return (
      <AdminState
        title={denied ? "운영 콘솔 접근 제한" : "운영 콘솔"}
        message={
          denied
            ? "현재 세션에는 운영 상태를 조회할 권한이 없습니다."
            : `운영 상태를 불러오지 못했습니다: ${health.error.message}`
        }
        denied={denied}
        retry={
          denied
            ? undefined
            : () => {
                void health.refetch();
              }
        }
      />
    );
  }

  const data = health.data;
  const cards = healthCards(data);
  return (
    <div className="simple-page admin-page">
      <div className="admin-title-row">
        <div>
          <h1>운영 콘솔</h1>
          <p>
            서버가 반환한 상태와 식별자만 표시하며 문서 내용이나 사용자
            개인정보는 노출하지 않습니다.
            {data.generatedAt && (
              <small className="evidence-timestamp">
                스냅샷 · {new Date(data.generatedAt).toLocaleString("ko-KR")}
              </small>
            )}
          </p>
        </div>
        <button
          className="secondary-button compact"
          type="button"
          disabled={health.isFetching}
          onClick={() => {
            void health.refetch();
          }}
        >
          <ArrowClockwise size={14} aria-hidden="true" />
          {health.isFetching ? "새로고침 중…" : "새로고침"}
        </button>
      </div>

      {cards.length === 0 ? (
        <section className="panel honest-state compact">
          <Warning size={21} aria-hidden="true" />
          <p>API 응답에 표시할 운영 지표가 없습니다.</p>
        </section>
      ) : (
        <section className="admin-health-grid" aria-label="운영 상태">
          {cards.map((card) => {
            const Icon = card.icon;
            return (
              <article key={card.label}>
                <Icon size={18} weight="fill" aria-hidden="true" />
                <span>{card.label}</span>
                <strong
                  className={card.tone ? `health-${card.tone}` : undefined}
                >
                  {card.value}
                </strong>
              </article>
            );
          })}
        </section>
      )}

      {data.dependencies.length > 0 && (
        <section className="panel admin-dependencies-panel">
          <div className="panel-heading">
            <div>
              <h2>서비스 의존성</h2>
              <p>상태 API가 보고한 구성요소만 표시합니다.</p>
            </div>
          </div>
          <div className="admin-dependency-list">
            {data.dependencies.map((dependency) => (
              <DependencyRow dependency={dependency} key={dependency.name} />
            ))}
          </div>
        </section>
      )}

      <ModelOperationsPanel />

      <DispatchDlqPanel />

      <section className="panel admin-table-panel">
        <div className="panel-heading">
          <div>
            <h2>작업 개입 필요</h2>
            <p>재시도 가능 상태와 서버가 허용한 작업만 실행할 수 있습니다.</p>
          </div>
        </div>
        {data.interventions.length === 0 ? (
          <div className="honest-state compact">
            <CheckCircle size={21} weight="fill" aria-hidden="true" />
            <p>현재 API가 보고한 개입 대상 작업이 없습니다.</p>
          </div>
        ) : (
          <div className="admin-table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Error</th>
                  <th>Route history</th>
                  <th>Attempts</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {data.interventions.map((job) => (
                  <InterventionRow
                    job={job}
                    key={job.jobId}
                    pending={retry.isPending && activeJobId === job.jobId}
                    disabled={retry.isPending}
                    onRetry={
                      job.actionUrl
                        ? () => {
                            setActiveJobId(job.jobId);
                            retry.mutate(job.actionUrl!);
                          }
                        : undefined
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {retry.isError && (
          <p className="admin-action-error" role="alert">
            작업을 실행하지 못했습니다: {retry.error.message}
          </p>
        )}
      </section>
    </div>
  );
}

function healthCards(data: AdminHealthSnapshot) {
  const cards: Array<{
    label: string;
    value: string;
    icon: typeof Database;
    tone?: "healthy" | "warning" | "danger" | "neutral";
  }> = [];
  if (data.status) {
    cards.push({
      label: "Overall",
      value: data.status,
      icon: ShieldCheck,
      tone: healthTone(data.status),
    });
  }
  if (data.oldestQueueAgeSeconds !== undefined) {
    cards.push({
      label: "Oldest queue age",
      value: `${formatNumber(data.oldestQueueAgeSeconds)}s`,
      icon: Queue,
    });
  }
  if (data.terminalSuccessRate !== undefined) {
    cards.push({
      label: "Terminal success",
      value: formatRate(data.terminalSuccessRate),
      icon: CheckCircle,
    });
  }
  if (data.dlqCount !== undefined) {
    cards.push({
      label: "DLQ",
      value: formatNumber(data.dlqCount),
      icon: Warning,
      tone: data.dlqCount > 0 ? "warning" : "healthy",
    });
  }
  if (data.queuedJobs !== undefined) {
    cards.push({
      label: "Queued jobs",
      value: formatNumber(data.queuedJobs),
      icon: Queue,
    });
  }
  if (data.runningJobs !== undefined) {
    cards.push({
      label: "Running jobs",
      value: formatNumber(data.runningJobs),
      icon: ArrowClockwise,
    });
  }
  return cards;
}

function DependencyRow({ dependency }: { dependency: AdminDependency }) {
  return (
    <div className="admin-dependency-row">
      <Database size={16} aria-hidden="true" />
      <strong>{dependency.name}</strong>
      <span
        className={`dependency-status health-${healthTone(dependency.status)}`}
      >
        {dependency.status ?? "상태 미제공"}
      </span>
      <small>
        {dependency.detail ??
          (dependency.latencyMs === undefined
            ? "세부 정보 미제공"
            : `${formatNumber(dependency.latencyMs)}ms`)}
      </small>
    </div>
  );
}

function InterventionRow({
  job,
  pending,
  disabled,
  onRetry,
}: {
  job: AdminIntervention;
  pending: boolean;
  disabled: boolean;
  onRetry?: () => void;
}) {
  return (
    <tr>
      <td>
        <code>{job.jobId}</code>
      </td>
      <td>{job.errorCode ?? "—"}</td>
      <td>{job.routeHistory ?? "—"}</td>
      <td>
        {job.attempts === undefined
          ? "—"
          : `${job.attempts}${job.maxAttempts === undefined ? "" : ` / ${job.maxAttempts}`}`}
      </td>
      <td>
        {onRetry ? (
          <button
            className="secondary-button compact"
            type="button"
            disabled={disabled}
            onClick={onRetry}
          >
            <ArrowClockwise size={13} aria-hidden="true" />
            {pending ? "실행 중…" : (job.actionLabel ?? "Retry job")}
          </button>
        ) : (
          <span className="muted-copy">
            {job.retryable ? "작업 URL 미제공" : "자동 재시도 불가"}
          </span>
        )}
      </td>
    </tr>
  );
}

function AdminState({
  title,
  message,
  busy = false,
  denied = false,
  retry,
}: {
  title: string;
  message: string;
  busy?: boolean;
  denied?: boolean;
  retry?: () => void;
}) {
  return (
    <div className="simple-page admin-page">
      <h1>{title}</h1>
      <div
        className="panel honest-state"
        aria-busy={busy}
        role={denied ? "alert" : undefined}
      >
        {busy ? (
          <span className="spinner" aria-hidden="true" />
        ) : denied ? (
          <ShieldCheck size={22} weight="fill" aria-hidden="true" />
        ) : (
          <Warning size={22} aria-hidden="true" />
        )}
        <p>{message}</p>
        {retry && (
          <button className="secondary-button" type="button" onClick={retry}>
            다시 시도
          </button>
        )}
      </div>
    </div>
  );
}

function healthTone(
  status?: string,
): "healthy" | "warning" | "danger" | "neutral" {
  const normalized = status?.toLowerCase();
  if (
    ["healthy", "ready", "ok", "pass", "passing", "up"].includes(
      normalized ?? "",
    )
  ) {
    return "healthy";
  }
  if (["degraded", "warning", "warn", "partial"].includes(normalized ?? "")) {
    return "warning";
  }
  if (
    ["unhealthy", "failed", "fail", "down", "error", "blocked"].includes(
      normalized ?? "",
    )
  ) {
    return "danger";
  }
  return "neutral";
}

function formatNumber(value: number): string {
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
}

function formatRate(value: number): string {
  const percent = value <= 1 ? value * 100 : value;
  return `${percent.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`;
}
