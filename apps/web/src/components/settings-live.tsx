"use client";

import {
  Check,
  CreditCard,
  Database,
  LockKey,
  ShieldCheck,
  UsersThree,
  Warning,
  WebhooksLogo,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import {
  normalizeSettingsResponse,
  type SettingsSnapshot,
} from "@/lib/operations-contracts";
import { BillingManagement } from "@/components/billing-management";
import { TeamManagement } from "@/components/team-management";
import { WebhookManagement } from "@/components/webhook-management";

interface EditablePolicy {
  private_mode?: boolean;
  external_transfer_allowed?: boolean;
  training_opt_in?: boolean;
  preview_pii_masking?: boolean;
  product_analytics_enabled?: boolean;
  data_retention_days?: number;
}

function editablePolicy(settings: SettingsSnapshot): EditablePolicy {
  return {
    private_mode: settings.privateMode,
    external_transfer_allowed: settings.externalTransferAllowed,
    training_opt_in: settings.trainingOptIn,
    preview_pii_masking: settings.previewPiiMasking,
    product_analytics_enabled: settings.productAnalyticsEnabled,
    data_retention_days: settings.dataRetentionDays,
  };
}

function applyPolicy(
  settings: SettingsSnapshot,
  policy: EditablePolicy,
): SettingsSnapshot {
  return {
    ...settings,
    privateMode: policy.private_mode ?? settings.privateMode,
    externalTransferAllowed:
      policy.external_transfer_allowed ?? settings.externalTransferAllowed,
    trainingOptIn: policy.training_opt_in ?? settings.trainingOptIn,
    previewPiiMasking: policy.preview_pii_masking ?? settings.previewPiiMasking,
    productAnalyticsEnabled:
      policy.product_analytics_enabled ?? settings.productAnalyticsEnabled,
    dataRetentionDays: policy.data_retention_days ?? settings.dataRetentionDays,
  };
}

export function SettingsLive() {
  const queryClient = useQueryClient();
  const roles = useAuthStore((state) => state.roles);
  const [changes, setChanges] = useState<EditablePolicy>({});
  const [saved, setSaved] = useState(false);

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: async () =>
      normalizeSettingsResponse(await apiRequest<unknown>("/v1/settings")),
  });

  const canManageByRole = roles.some((role) =>
    ["owner", "admin"].includes(role.toLowerCase()),
  );
  const canManage =
    settings.data?.canManagePolicy === undefined
      ? canManageByRole
      : settings.data.canManagePolicy;
  const canManageBilling = roles.some((role) =>
    ["owner", "admin", "billing"].includes(role.toLowerCase()),
  );

  const isDirty = Object.keys(changes).length > 0;

  const updateSettings = useMutation({
    mutationFn: (payload: EditablePolicy) =>
      apiRequest<unknown>("/v1/settings", {
        method: "PATCH",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify(payload),
      }),
    onSuccess: (_response, submitted) => {
      queryClient.setQueryData<SettingsSnapshot>(
        ["settings"],
        (current) => current && applyPolicy(current, submitted),
      );
      setChanges({});
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  if (settings.isPending) {
    return (
      <SettingsState message="워크스페이스 정책을 불러오고 있습니다." busy />
    );
  }

  if (settings.isError) {
    return (
      <SettingsState
        message={`설정을 불러오지 못했습니다: ${settings.error.message}`}
        retry={() => {
          void settings.refetch();
        }}
      />
    );
  }

  const data = settings.data;
  const policy = { ...editablePolicy(data), ...changes };
  const policyEvidencePresent = [
    policy.private_mode,
    policy.external_transfer_allowed,
    policy.training_opt_in,
    policy.preview_pii_masking,
    policy.product_analytics_enabled,
  ].some((value) => value !== undefined);

  function update<K extends keyof EditablePolicy>(
    key: K,
    value: EditablePolicy[K],
  ) {
    updateSettings.reset();
    setSaved(false);
    const baseline = editablePolicy(data);
    setChanges((current) => {
      const next = { ...current, [key]: value };
      if (value === baseline[key]) delete next[key];
      return next;
    });
  }

  return (
    <div className="simple-page settings-page">
      <h1>설정</h1>
      <p>
        데이터 보존과 외부 처리 정책을 서버에 저장된 워크스페이스 단위로
        관리합니다.
        {data.updatedAt && (
          <small className="evidence-timestamp">
            마지막 갱신 · {new Date(data.updatedAt).toLocaleString("ko-KR")}
          </small>
        )}
      </p>

      <div className="settings-layout">
        <nav className="settings-nav" aria-label="설정 섹션">
          <a href="#privacy" className="active">
            <ShieldCheck size={16} weight="fill" aria-hidden="true" />
            개인정보·처리
          </a>
          <a href="#retention">
            <Database size={16} aria-hidden="true" />
            보존·삭제
          </a>
          <a href="#members">
            <UsersThree size={16} aria-hidden="true" />
            멤버·역할
          </a>
          {canManageBilling && (
            <a href="#billing">
              <CreditCard size={16} aria-hidden="true" />
              크레딧·결제
            </a>
          )}
          {canManage && (
            <a href="#webhooks">
              <WebhooksLogo size={16} aria-hidden="true" />
              Webhooks
            </a>
          )}
        </nav>

        <div className="settings-content">
          <section className="settings-section" id="privacy">
            <header>
              <div>
                <h2>처리 경계</h2>
                <p>응답에 존재하는 실제 정책만 표시하고 수정합니다.</p>
              </div>
              <span
                className={`policy-state ${policy.private_mode ? "safe" : ""}`}
              >
                <LockKey size={13} weight="fill" aria-hidden="true" />
                {policy.private_mode === true
                  ? "Private mode"
                  : policy.private_mode === false
                    ? "Managed mode"
                    : "정책 미확인"}
              </span>
            </header>

            {!policyEvidencePresent ? (
              <div className="honest-state compact">
                <Warning size={20} aria-hidden="true" />
                <p>서버 응답에 표시할 처리 정책이 없습니다.</p>
              </div>
            ) : (
              <>
                <PolicyToggle
                  label="프라이빗 모드"
                  description="활성화하면 외부 전송을 허용하지 않는 경계로 전환합니다."
                  value={policy.private_mode}
                  disabled={!canManage || updateSettings.isPending}
                  onChange={(value) => {
                    update("private_mode", value);
                    if (value && policy.external_transfer_allowed === true) {
                      update("external_transfer_allowed", false);
                    }
                  }}
                />
                <PolicyToggle
                  label="외부 모델 전송 허용"
                  description="프로젝트별 명시적 동의가 있어도 이 정책이 꺼져 있으면 외부 전송하지 않습니다."
                  value={policy.external_transfer_allowed}
                  disabled={
                    !canManage ||
                    updateSettings.isPending ||
                    policy.private_mode === true
                  }
                  onChange={(value) =>
                    update("external_transfer_allowed", value)
                  }
                />
                <PolicyToggle
                  label="제품 개선 데이터 제공"
                  description="명시적으로 켠 경우에만 학습·개선 목적의 사용을 허용합니다."
                  value={policy.training_opt_in}
                  disabled={!canManage || updateSettings.isPending}
                  onChange={(value) => update("training_opt_in", value)}
                />
                {policy.preview_pii_masking !== undefined && (
                  <PolicyToggle
                    label="미리보기 민감정보 마스킹"
                    description="원본은 변경하지 않고 사용자 미리보기에서만 감지된 민감정보를 가립니다."
                    value={policy.preview_pii_masking}
                    disabled={!canManage || updateSettings.isPending}
                    onChange={(value) => update("preview_pii_masking", value)}
                  />
                )}
                {policy.product_analytics_enabled !== undefined && (
                  <PolicyToggle
                    label="최소 제품 분석"
                    description="문서 본문이나 민감정보 없이 최소 사용 이벤트와 집계 지표만 기록합니다. 끄면 이후 이벤트 수집을 중단합니다."
                    value={policy.product_analytics_enabled}
                    disabled={!canManage || updateSettings.isPending}
                    onChange={(value) =>
                      update("product_analytics_enabled", value)
                    }
                  />
                )}
              </>
            )}
          </section>

          <section className="settings-section" id="retention">
            <header>
              <div>
                <h2>보존·삭제</h2>
                <p>서버가 제공한 워크스페이스 보존 기간을 변경합니다.</p>
              </div>
            </header>
            {policy.data_retention_days === undefined ? (
              <div className="honest-state compact">
                <p>보존 기간 정보가 API 응답에 없습니다.</p>
              </div>
            ) : (
              <div className="retention-grid retention-grid-live">
                <label>
                  <span>데이터 보존 기간</span>
                  <select
                    value={policy.data_retention_days}
                    disabled={!canManage || updateSettings.isPending}
                    onChange={(event) =>
                      update("data_retention_days", Number(event.target.value))
                    }
                  >
                    {[
                      ...new Set([
                        0,
                        1,
                        7,
                        30,
                        90,
                        365,
                        policy.data_retention_days,
                      ]),
                    ]
                      .sort((left, right) => left - right)
                      .map((days) => (
                        <option key={days} value={days}>
                          {days === 0 ? "처리 후 즉시 삭제" : `${days}일`}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
            )}
            <div className="deletion-assurance">
              <Check size={15} weight="bold" aria-hidden="true" />
              삭제 작업의 완료 여부는 서버가 발급한 deletion receipt로
              검증합니다.
            </div>
          </section>

          <section className="settings-section" id="members">
            <header>
              <div>
                <h2>{data.workspaceName ?? "워크스페이스"} 멤버</h2>
                <p>멤버 정보가 응답에 포함된 경우에만 표시합니다.</p>
              </div>
            </header>
            {canManage ? (
              <TeamManagement />
            ) : data.members.length === 0 ? (
              <div className="honest-state compact">
                <UsersThree size={20} aria-hidden="true" />
                <p>멤버 목록이 API 응답에 없습니다.</p>
              </div>
            ) : (
              <div className="member-list">
                {data.members.map((member, index) => (
                  <div
                    className="member-row"
                    key={
                      member.id ??
                      member.email ??
                      `${member.displayName}-${index}`
                    }
                  >
                    <span className="avatar" aria-hidden="true">
                      {(member.displayName ?? member.email ?? "—")
                        .slice(0, 2)
                        .toUpperCase()}
                    </span>
                    <span>
                      <strong>{member.displayName ?? "이름 미제공"}</strong>
                      <small>{member.email ?? "이메일 미제공"}</small>
                    </span>
                    <span className="status-badge neutral">
                      {member.role ?? member.status ?? "역할 미제공"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {canManage && (
            <section className="settings-section" id="webhooks">
              <header>
                <div>
                  <h2>Webhook delivery</h2>
                  <p>
                    HMAC 서명 endpoint와 재시도·dead-letter 전달 이력을
                    관리합니다.
                  </p>
                </div>
              </header>
              <WebhookManagement />
            </section>
          )}

          {canManageBilling && (
            <section className="settings-section" id="billing">
              <header>
                <div>
                  <h2>크레딧·결제</h2>
                  <p>
                    사업자 checkout과 서명된 webhook으로 확정된 결제 원장만
                    표시합니다.
                  </p>
                </div>
              </header>
              <BillingManagement />
            </section>
          )}

          <div className="settings-save" role="status" aria-live="polite">
            <span>
              {!canManage
                ? "Owner 또는 Admin 역할만 정책을 변경할 수 있습니다."
                : updateSettings.isError
                  ? settingsErrorMessage(updateSettings.error)
                  : saved
                    ? "변경 사항이 서버에 저장되었습니다."
                    : isDirty
                      ? "저장하지 않은 변경 사항이 있습니다."
                      : "현재 서버 설정과 일치합니다."}
            </span>
            <button
              className="primary-button"
              type="button"
              disabled={!canManage || !isDirty || updateSettings.isPending}
              onClick={() => updateSettings.mutate(changes)}
            >
              {updateSettings.isPending ? "저장 중…" : "설정 저장"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PolicyToggle({
  label,
  description,
  value,
  disabled,
  onChange,
}: {
  label: string;
  description: string;
  value?: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  if (value === undefined) return null;
  return (
    <label className="setting-row">
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <input
        type="checkbox"
        className="switch"
        checked={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

function SettingsState({
  message,
  busy = false,
  retry,
}: {
  message: string;
  busy?: boolean;
  retry?: () => void;
}) {
  return (
    <div className="simple-page settings-page">
      <h1>설정</h1>
      <div className="panel honest-state" aria-busy={busy}>
        {busy ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <Warning size={20} />
        )}
        <p>{message}</p>
        {retry && (
          <button type="button" className="secondary-button" onClick={retry}>
            다시 시도
          </button>
        )}
      </div>
    </div>
  );
}

function settingsErrorMessage(error: Error): string {
  if (error instanceof ApiError && error.status === 403) {
    return "이 정책을 변경할 권한이 없습니다.";
  }
  return `저장하지 못했습니다: ${error.message}`;
}
