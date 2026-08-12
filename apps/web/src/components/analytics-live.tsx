"use client";

import {
  ArrowClockwise,
  ChartLineUp,
  CheckCircle,
  Clock,
  Coins,
  LockKey,
  Warning,
} from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest } from "@/lib/api-client";
import styles from "@/components/analytics-live.module.css";

type WindowKey = "7d" | "30d" | "90d";
type MetricStatus =
  | "available"
  | "empty_denominator"
  | "insufficient_evidence"
  | "disabled"
  | "not_instrumented";
type MetricUnit =
  | "count"
  | "ratio"
  | "seconds"
  | "minutes_per_job"
  | "credits_per_page"
  | "credits_per_project";

export interface AnalyticsMetric {
  key: string;
  label: string;
  value: number | null;
  numerator: number | null;
  denominator: number | null;
  unit: MetricUnit;
  status: MetricStatus;
  definition: string;
  sources: string[];
}

interface ActivationStage {
  key: string;
  label: string;
  users: number | null;
  cohort_rate: number | null;
  step_rate: number | null;
  status: MetricStatus;
  definition: string;
  sources: string[];
}

interface AnalyticsSnapshot {
  schema_version: "2026-07-30";
  generated_at: string;
  window: {
    key: WindowKey;
    start_at: string;
    end_at: string;
    days: number;
    boundary: "start_inclusive_end_exclusive";
    timezone: "UTC";
  };
  privacy: {
    enabled: boolean;
    private_mode: boolean;
    collection_mode:
      "disabled" | "private_operational_only" | "tenant_local_first_party";
    external_export: false;
    optional_behavior_events_stored: boolean;
    payload_policy: string;
  };
  cohorts: Array<{
    key: string;
    start_at: string;
    end_at: string;
    observation_days: number;
    population: number;
    definition: string;
  }>;
  north_star: AnalyticsMetric;
  activation: ActivationStage[];
  product: Record<string, AnalyticsMetric>;
  export_profiles: Array<{
    profile: string;
    exports: number;
    share: number | null;
  }>;
  quality: Record<string, AnalyticsMetric>;
  economics: Record<string, AnalyticsMetric>;
  refunds_by_currency: Array<{
    currency: string;
    paid_payments: number;
    paid_amount_minor: number;
    refunded_payments: number;
    refunded_amount_minor: number;
  }>;
  limitations: string[];
}

const windows: WindowKey[] = ["7d", "30d", "90d"];

export function AnalyticsLive() {
  const [windowKey, setWindowKey] = useState<WindowKey>("30d");
  const analytics = useQuery({
    queryKey: ["analytics", windowKey],
    queryFn: () =>
      apiRequest<AnalyticsSnapshot>(`/v1/analytics?window=${windowKey}`),
  });

  if (analytics.isPending) {
    return (
      <AnalyticsState
        message="Calculating product metrics with verified windows and denominators."
        busy
      />
    );
  }

  if (analytics.isError) {
    return (
      <AnalyticsState
        message={`Product metrics could not be loaded: ${analytics.error.message}`}
        retry={() => {
          void analytics.refetch();
        }}
      />
    );
  }

  const data = analytics.data;
  const finalActivation = data.activation.at(-1);
  const overview = [
    {
      icon: ChartLineUp,
      metric: data.north_star,
    },
    {
      icon: CheckCircle,
      metric: activationMetric(finalActivation),
    },
    {
      icon: Clock,
      metric:
        data.product.job_completion_rate ??
        unavailableOverview("job_completion_rate", "Job completion rate"),
    },
    {
      icon: Coins,
      metric:
        data.economics.credit_cost_per_page ??
        unavailableOverview(
          "credit_cost_per_page",
          "Credit cost per processed page",
        ),
    },
  ];

  return (
    <div className={`simple-page analytics-page ${styles.root}`}>
      <div className="analytics-title-row">
        <div>
          <h1>Product analytics</h1>
          <p>
            Metrics come only from this workspace&apos;s operational
            records—never estimates or demo values. Every rate includes its
            numerator and denominator.
          </p>
        </div>
        <div
          className="analytics-window-switcher"
          role="group"
          aria-label="Analytics period"
        >
          {windows.map((candidate) => (
            <button
              key={candidate}
              type="button"
              className={candidate === windowKey ? "active" : undefined}
              aria-pressed={candidate === windowKey}
              onClick={() => setWindowKey(candidate)}
            >
              {candidate}
            </button>
          ))}
        </div>
      </div>

      <PrivacyNotice snapshot={data} />

      <section className="analytics-metrics" aria-label="Core product metrics">
        {overview.map(({ icon, metric }) => (
          <MetricCard key={metric.key} icon={icon} metric={metric} />
        ))}
      </section>

      {!data.privacy.enabled ? (
        <div className="panel honest-state analytics-disabled" role="status">
          <LockKey size={22} weight="duotone" aria-hidden="true" />
          <div>
            <strong>Product analytics is disabled.</strong>
            <p>
              Behavioral events are neither stored nor aggregated until you
              enable analytics in privacy settings.
            </p>
          </div>
        </div>
      ) : (
        <>
          <section className="panel analytics-panel analytics-wide-panel">
            <div className="panel-heading">
              <div>
                <h2>Seven-day activation funnel</h2>
                <p>
                  Includes only signup cohorts with a complete observation
                  window.
                </p>
              </div>
            </div>
            <ActivationFunnel stages={data.activation} />
          </section>

          <div className="analytics-section-grid">
            <MetricPanel
              title="Product usage"
              description="Speed, completion, export, and reuse"
              metrics={Object.values(data.product)}
            />
            <MetricPanel
              title="Quality"
              description="Integrity findings, evidence linking, and user-reported errors"
              metrics={Object.values(data.quality)}
            />
            <MetricPanel
              title="Unit economics"
              description="Metrics that separate credits from currency costs"
              metrics={Object.values(data.economics)}
            />
            <ExportEvidence snapshot={data} />
          </div>
        </>
      )}

      <details className="panel analytics-methodology">
        <summary>Cohorts and measurement limits</summary>
        <div>
          <p>
            From {formatDate(data.window.start_at)} through{" "}
            {formatDate(data.window.end_at)} · UTC
          </p>
          <ul>
            {data.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
          {data.cohorts.length > 0 && (
            <dl>
              {data.cohorts.map((cohort) => (
                <div key={cohort.key}>
                  <dt>{cohort.key}</dt>
                  <dd>
                    {cohort.population.toLocaleString("en-US")} users ·{" "}
                    {cohort.observation_days}-day observation —{" "}
                    {cohort.definition}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </details>

      <p className="analytics-generated-at">
        Contract {data.schema_version} · generated{" "}
        {new Date(data.generated_at).toLocaleString("ko-KR")}
      </p>
    </div>
  );
}

function PrivacyNotice({ snapshot }: { snapshot: AnalyticsSnapshot }) {
  const privateOnly =
    snapshot.privacy.collection_mode === "private_operational_only";
  const disabled = snapshot.privacy.collection_mode === "disabled";
  return (
    <div
      className={`analytics-privacy-notice ${disabled ? "disabled" : ""}`}
      role="status"
    >
      <LockKey size={17} weight="fill" aria-hidden="true" />
      <div>
        <strong>
          {disabled
            ? "Analytics not collected"
            : privateOnly
              ? "Private mode · operational records only"
              : "First-party tenant data"}
        </strong>
        <span>
          {snapshot.privacy.payload_policy} No external analytics transfer.
        </span>
      </div>
    </div>
  );
}

function MetricCard({
  icon: Icon,
  metric,
}: {
  icon: Icon;
  metric: AnalyticsMetric;
}) {
  return (
    <article className="analytics-metric">
      <div>
        <Icon size={17} weight="fill" aria-hidden="true" />
        <span>{metric.label}</span>
      </div>
      <strong>{formatMetric(metric)}</strong>
      <small className={metric.status === "available" ? "good" : "warn"}>
        {metric.status === "available" ? (
          <CheckCircle size={11} weight="fill" aria-hidden="true" />
        ) : (
          <Warning size={11} weight="fill" aria-hidden="true" />
        )}
        {metricEvidence(metric)}
      </small>
    </article>
  );
}

function ActivationFunnel({ stages }: { stages: ActivationStage[] }) {
  if (stages.length === 0) {
    return (
      <div className="honest-state compact">
        <p>The funnel was not calculated because analytics is disabled.</p>
      </div>
    );
  }
  return (
    <ol className="activation-funnel">
      {stages.map((stage, index) => (
        <li key={stage.key}>
          <span className="activation-step" aria-hidden="true">
            {index + 1}
          </span>
          <div>
            <strong>{stage.label}</strong>
            <small>{stage.definition}</small>
          </div>
          <span className="activation-users">
            {stage.users === null
              ? statusLabel(stage.status)
              : `${stage.users.toLocaleString("en-US")} users`}
          </span>
          <span className="activation-rate">
            Cohort {formatRatio(stage.cohort_rate)}
            <small>Previous stage {formatRatio(stage.step_rate)}</small>
          </span>
        </li>
      ))}
    </ol>
  );
}

function MetricPanel({
  title,
  description,
  metrics,
}: {
  title: string;
  description: string;
  metrics: AnalyticsMetric[];
}) {
  return (
    <section className="panel analytics-panel analytics-definition-panel">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      <dl className="analytics-definition-list">
        {metrics.map((metric) => (
          <div key={metric.key}>
            <dt>
              <span>{metric.label}</span>
              <small>{statusLabel(metric.status)}</small>
            </dt>
            <dd>
              <strong>{formatMetric(metric)}</strong>
              <span>{metricEvidence(metric)}</span>
              <details>
                <summary>Definition</summary>
                <p>{metric.definition}</p>
              </details>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ExportEvidence({ snapshot }: { snapshot: AnalyticsSnapshot }) {
  return (
    <section className="panel analytics-panel analytics-definition-panel">
      <div className="panel-heading">
        <div>
          <h2>Export and refund evidence</h2>
          <p>Raw aggregates that keep profiles and currencies separate</p>
        </div>
      </div>
      {snapshot.export_profiles.length === 0 &&
      snapshot.refunds_by_currency.length === 0 ? (
        <div className="honest-state compact">
          <p>No export or payment cohorts are available for this period.</p>
        </div>
      ) : (
        <div className="analytics-evidence-groups">
          {snapshot.export_profiles.length > 0 && (
            <div>
              <h3>Export profile</h3>
              <ul>
                {snapshot.export_profiles.map((profile) => (
                  <li key={profile.profile}>
                    <span>{profile.profile}</span>
                    <strong>
                      {profile.exports.toLocaleString("ko-KR")} ·{" "}
                      {formatRatio(profile.share)}
                    </strong>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {snapshot.refunds_by_currency.length > 0 && (
            <div>
              <h3>Payment cohort by currency</h3>
              <ul>
                {snapshot.refunds_by_currency.map((currency) => (
                  <li key={currency.currency}>
                    <span>{currency.currency}</span>
                    <strong>
                      Paid {currency.paid_payments.toLocaleString("en-US")} ·
                      refunded{" "}
                      {currency.refunded_payments.toLocaleString("en-US")}
                    </strong>
                    <small>
                      minor units{" "}
                      {currency.paid_amount_minor.toLocaleString("ko-KR")} /{" "}
                      {currency.refunded_amount_minor.toLocaleString("ko-KR")}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function AnalyticsState({
  message,
  busy = false,
  retry,
}: {
  message: string;
  busy?: boolean;
  retry?: () => void;
}) {
  return (
    <div className={`simple-page analytics-page ${styles.root}`}>
      <h1>Product analytics</h1>
      <div
        className="panel honest-state"
        aria-busy={busy}
        aria-live="polite"
        role={busy ? "status" : "alert"}
      >
        {busy ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <Warning size={20} aria-hidden="true" />
        )}
        <p>{message}</p>
        {retry && (
          <button type="button" className="secondary-button" onClick={retry}>
            <ArrowClockwise size={15} aria-hidden="true" />
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

function activationMetric(stage: ActivationStage | undefined): AnalyticsMetric {
  if (!stage) {
    return unavailableOverview(
      "activation_reuse_or_merge",
      "7-day activated and reused",
    );
  }
  return {
    key: "activation_reuse_or_merge",
    label: "7-day activated and reused",
    value: stage.cohort_rate,
    numerator: stage.users,
    denominator: null,
    unit: "ratio",
    status: stage.status,
    definition: stage.definition,
    sources: stage.sources,
  };
}

function unavailableOverview(key: string, label: string): AnalyticsMetric {
  return {
    key,
    label,
    value: null,
    numerator: null,
    denominator: null,
    unit: "count",
    status: "insufficient_evidence",
    definition: "No metric contract was returned.",
    sources: [],
  };
}

export function formatMetric(metric: AnalyticsMetric): string {
  if (metric.value === null) return statusLabel(metric.status);
  if (metric.unit === "ratio") return formatRatio(metric.value);
  if (metric.unit === "seconds") return `${formatNumber(metric.value)} sec`;
  if (metric.unit === "minutes_per_job")
    return `${formatNumber(metric.value)} min/job`;
  if (metric.unit === "credits_per_page")
    return `${formatNumber(metric.value)} cr/page`;
  if (metric.unit === "credits_per_project")
    return `${formatNumber(metric.value)} cr/project`;
  return formatNumber(metric.value);
}

function metricEvidence(metric: AnalyticsMetric): string {
  if (metric.denominator !== null) {
    return `Numerator ${formatNumber(metric.numerator ?? 0)} / denominator ${formatNumber(
      metric.denominator,
    )}`;
  }
  if (metric.numerator !== null) {
    return `Observed ${formatNumber(metric.numerator)}`;
  }
  return statusLabel(metric.status);
}

function formatRatio(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString("ko-KR", { timeZone: "UTC" });
}

function statusLabel(status: MetricStatus): string {
  const labels: Record<MetricStatus, string> = {
    available: "Measured",
    empty_denominator: "No denominator",
    insufficient_evidence: "Insufficient evidence",
    disabled: "Analytics disabled",
    not_instrumented: "Not collected",
  };
  return labels[status];
}
