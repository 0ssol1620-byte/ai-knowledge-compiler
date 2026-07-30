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
        title="Operations console access restricted"
        message="Only verified Owner or Admin sessions can view operational status."
        denied
      />
    );
  }

  if (health.isPending) {
    return (
      <AdminState
        title="Operations console"
        message="Loading live service status and intervention targets."
        busy
      />
    );
  }

  if (health.isError) {
    const denied =
      health.error instanceof ApiError && health.error.status === 403;
    return (
      <AdminState
        title={
          denied ? "Operations console access restricted" : "Operations console"
        }
        message={
          denied
            ? "This session is not authorized to view operational status."
            : `Operational status could not be loaded: ${health.error.message}`
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
          <h1>Operations console</h1>
          <p>
            This console displays only server-reported status and identifiers.
            Document content and personal data never appear here.
            {data.generatedAt && (
              <small className="evidence-timestamp">
                Snapshot · {new Date(data.generatedAt).toLocaleString("en-US")}
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
          {health.isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {cards.length === 0 ? (
        <section className="panel honest-state compact">
          <Warning size={21} aria-hidden="true" />
          <p>The API returned no operational metrics to display.</p>
        </section>
      ) : (
        <section className="admin-health-grid" aria-label="Operational status">
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
              <h2>Service dependencies</h2>
              <p>Only components reported by the status API are shown.</p>
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
            <h2>Jobs requiring intervention</h2>
            <p>Only retryable states and server-authorized actions can run.</p>
          </div>
        </div>
        {data.interventions.length === 0 ? (
          <div className="honest-state compact">
            <CheckCircle size={21} weight="fill" aria-hidden="true" />
            <p>The API reports no jobs requiring intervention.</p>
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
            The action could not be completed: {retry.error.message}
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
        {dependency.status ?? "Status unavailable"}
      </span>
      <small>
        {dependency.detail ??
          (dependency.latencyMs === undefined
            ? "Details unavailable"
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
            {pending ? "Running…" : (job.actionLabel ?? "Retry job")}
          </button>
        ) : (
          <span className="muted-copy">
            {job.retryable
              ? "Action URL unavailable"
              : "Automatic retry unavailable"}
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
            Try again
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
