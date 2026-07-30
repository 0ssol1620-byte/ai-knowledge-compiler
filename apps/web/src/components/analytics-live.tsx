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
        message="기간과 분모가 검증된 제품 지표를 계산하고 있습니다."
        busy
      />
    );
  }

  if (analytics.isError) {
    return (
      <AnalyticsState
        message={`제품 지표를 불러오지 못했습니다: ${analytics.error.message}`}
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
    <main className={`simple-page analytics-page ${styles.root}`}>
      <div className="analytics-title-row">
        <div>
          <p className="eyebrow">Measured product evidence</p>
          <h1>제품 분석</h1>
          <p>
            추정값이나 데모 숫자가 아니라 현재 워크스페이스의 운영 기록만
            집계합니다. 모든 비율에는 분자와 분모가 함께 표시됩니다.
          </p>
        </div>
        <div
          className="analytics-window-switcher"
          role="group"
          aria-label="분석 기간"
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

      <section className="analytics-metrics" aria-label="핵심 제품 지표">
        {overview.map(({ icon, metric }) => (
          <MetricCard key={metric.key} icon={icon} metric={metric} />
        ))}
      </section>

      {!data.privacy.enabled ? (
        <div className="panel honest-state analytics-disabled" role="status">
          <LockKey size={22} weight="duotone" aria-hidden="true" />
          <div>
            <strong>제품 분석이 꺼져 있습니다.</strong>
            <p>
              개인정보 설정에서 다시 켤 때까지 행동 이벤트를 저장하지 않고
              집계도 계산하지 않습니다.
            </p>
          </div>
        </div>
      ) : (
        <>
          <section className="panel analytics-panel analytics-wide-panel">
            <div className="panel-heading">
              <div>
                <h2>7일 활성화 퍼널</h2>
                <p>완전한 관찰 기간을 확보한 가입 코호트만 포함합니다.</p>
              </div>
            </div>
            <ActivationFunnel stages={data.activation} />
          </section>

          <div className="analytics-section-grid">
            <MetricPanel
              title="제품 사용"
              description="속도, 완료, 내보내기와 재사용"
              metrics={Object.values(data.product)}
            />
            <MetricPanel
              title="품질"
              description="검토, 근거 연결과 사용자 오류"
              metrics={Object.values(data.quality)}
            />
            <MetricPanel
              title="단위 경제성"
              description="크레딧과 통화 비용을 구분한 지표"
              metrics={Object.values(data.economics)}
            />
            <ExportEvidence snapshot={data} />
          </div>
        </>
      )}

      <details className="panel analytics-methodology">
        <summary>코호트와 측정 한계</summary>
        <div>
          <p>
            {formatDate(data.window.start_at)} 이상,{" "}
            {formatDate(data.window.end_at)} 미만 · UTC
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
                    {cohort.population.toLocaleString("ko-KR")}개 ·{" "}
                    {cohort.observation_days}일 관찰 — {cohort.definition}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </details>

      <p className="analytics-generated-at">
        계약 {data.schema_version} · 생성{" "}
        {new Date(data.generated_at).toLocaleString("ko-KR")}
      </p>
    </main>
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
            ? "분석 수집 안 함"
            : privateOnly
              ? "비공개 모드 · 운영 기록만"
              : "테넌트 내부 1차 데이터"}
        </strong>
        <span>{snapshot.privacy.payload_policy} 외부 분석 전송: 없음.</span>
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
        <p>분석이 꺼져 있어 퍼널을 계산하지 않았습니다.</p>
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
              : `${stage.users.toLocaleString("ko-KR")}명`}
          </span>
          <span className="activation-rate">
            코호트 {formatRatio(stage.cohort_rate)}
            <small>이전 단계 {formatRatio(stage.step_rate)}</small>
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
                <summary>정의</summary>
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
          <h2>내보내기·환불 근거</h2>
          <p>프로필과 통화를 섞지 않은 원자료 집계</p>
        </div>
      </div>
      {snapshot.export_profiles.length === 0 &&
      snapshot.refunds_by_currency.length === 0 ? (
        <div className="honest-state compact">
          <p>선택 기간에 표시할 내보내기 또는 결제 코호트가 없습니다.</p>
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
                      결제 {currency.paid_payments.toLocaleString("ko-KR")} ·
                      환불 {currency.refunded_payments.toLocaleString("ko-KR")}
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
    <main className={`simple-page analytics-page ${styles.root}`}>
      <p className="eyebrow">Measured product evidence</p>
      <h1>제품 분석</h1>
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
            다시 시도
          </button>
        )}
      </div>
    </main>
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
  if (metric.unit === "seconds") return `${formatNumber(metric.value)}초`;
  if (metric.unit === "minutes_per_job")
    return `${formatNumber(metric.value)}분/작업`;
  if (metric.unit === "credits_per_page")
    return `${formatNumber(metric.value)} cr/페이지`;
  if (metric.unit === "credits_per_project")
    return `${formatNumber(metric.value)} cr/프로젝트`;
  return formatNumber(metric.value);
}

function metricEvidence(metric: AnalyticsMetric): string {
  if (metric.denominator !== null) {
    return `분자 ${formatNumber(metric.numerator ?? 0)} / 분모 ${formatNumber(
      metric.denominator,
    )}`;
  }
  if (metric.numerator !== null) {
    return `관측 ${formatNumber(metric.numerator)}`;
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
    available: "측정됨",
    empty_denominator: "분모 없음",
    insufficient_evidence: "근거 부족",
    disabled: "분석 꺼짐",
    not_instrumented: "수집 안 함",
  };
  return labels[status];
}
