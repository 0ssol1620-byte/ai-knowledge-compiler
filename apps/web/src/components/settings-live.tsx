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
    return <SettingsState message="Loading workspace policy." busy />;
  }

  if (settings.isError) {
    return (
      <SettingsState
        message={`Settings could not be loaded: ${settings.error.message}`}
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
      <h1>Settings</h1>
      <p>
        Manage server-backed retention and external processing policy for this
        workspace.
        {data.updatedAt && (
          <small className="evidence-timestamp">
            Last updated · {new Date(data.updatedAt).toLocaleString("en-US")}
          </small>
        )}
      </p>

      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          <a href="#privacy" className="active">
            <ShieldCheck size={16} weight="fill" aria-hidden="true" />
            Privacy & processing
          </a>
          <a href="#retention">
            <Database size={16} aria-hidden="true" />
            Retention & deletion
          </a>
          <a href="#members">
            <UsersThree size={16} aria-hidden="true" />
            Members & roles
          </a>
          {canManageBilling && (
            <a href="#billing">
              <CreditCard size={16} aria-hidden="true" />
              Credits & billing
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
                <h2>Processing boundary</h2>
                <p>
                  Only policies present in the server response can be changed.
                </p>
              </div>
              <span
                className={`policy-state ${policy.private_mode ? "safe" : ""}`}
              >
                <LockKey size={13} weight="fill" aria-hidden="true" />
                {policy.private_mode === true
                  ? "Private mode"
                  : policy.private_mode === false
                    ? "Managed mode"
                    : "Policy unknown"}
              </span>
            </header>

            {!policyEvidencePresent ? (
              <div className="honest-state compact">
                <Warning size={20} aria-hidden="true" />
                <p>No processing policy is present in the server response.</p>
              </div>
            ) : (
              <>
                <PolicyToggle
                  label="Private mode"
                  description="Prevents all external transfer when enabled."
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
                  label="Allow external model transfer"
                  description="No external transfer occurs while this is off, even with project-level consent."
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
                  label="Product improvement data"
                  description="Allows training or improvement use only when explicitly enabled."
                  value={policy.training_opt_in}
                  disabled={!canManage || updateSettings.isPending}
                  onChange={(value) => update("training_opt_in", value)}
                />
                {policy.preview_pii_masking !== undefined && (
                  <PolicyToggle
                    label="Mask sensitive data in previews"
                    description="Masks detected sensitive data in user previews without changing the source."
                    value={policy.preview_pii_masking}
                    disabled={!canManage || updateSettings.isPending}
                    onChange={(value) => update("preview_pii_masking", value)}
                  />
                )}
                {policy.product_analytics_enabled !== undefined && (
                  <PolicyToggle
                    label="Minimal product analytics"
                    description="Records only minimal usage events and aggregate metrics without document content or sensitive data. Turning this off stops future collection."
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
                <h2>Retention & deletion</h2>
                <p>
                  Change the workspace retention period provided by the server.
                </p>
              </div>
            </header>
            {policy.data_retention_days === undefined ? (
              <div className="honest-state compact">
                <p>No retention period is present in the API response.</p>
              </div>
            ) : (
              <div className="retention-grid retention-grid-live">
                <label>
                  <span>Data retention period</span>
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
                          {days === 0
                            ? "Delete after processing"
                            : `${days} days`}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
            )}
            <div className="deletion-assurance">
              <Check size={15} weight="bold" aria-hidden="true" />
              Completion of deletion is verified with a server-issued deletion
              receipt.
            </div>
          </section>

          <section className="settings-section" id="members">
            <header>
              <div>
                <h2>{data.workspaceName ?? "Workspace"} members</h2>
                <p>Members are shown only when included in the response.</p>
              </div>
            </header>
            {canManage ? (
              <TeamManagement />
            ) : data.members.length === 0 ? (
              <div className="honest-state compact">
                <UsersThree size={20} aria-hidden="true" />
                <p>No member list is present in the API response.</p>
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
                      <strong>
                        {member.displayName ?? "Name unavailable"}
                      </strong>
                      <small>{member.email ?? "Email unavailable"}</small>
                    </span>
                    <span className="status-badge neutral">
                      {member.role ?? member.status ?? "Role unavailable"}
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
                    Manage HMAC-signed endpoints and retry or dead-letter
                    delivery history.
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
                  <h2>Credits & billing</h2>
                  <p>
                    Only payment ledger entries confirmed by business checkout
                    and signed webhooks are shown.
                  </p>
                </div>
              </header>
              <BillingManagement />
            </section>
          )}

          <div className="settings-save" role="status" aria-live="polite">
            <span>
              {!canManage
                ? "Only Owner or Admin roles can change policy."
                : updateSettings.isError
                  ? settingsErrorMessage(updateSettings.error)
                  : saved
                    ? "Changes were saved to the server."
                    : isDirty
                      ? "There are unsaved changes."
                      : "Settings match the server."}
            </span>
            <button
              className="primary-button"
              type="button"
              disabled={!canManage || !isDirty || updateSettings.isPending}
              onClick={() => updateSettings.mutate(changes)}
            >
              {updateSettings.isPending ? "Saving…" : "Save settings"}
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
      <h1>Settings</h1>
      <div className="panel honest-state" aria-busy={busy}>
        {busy ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <Warning size={20} />
        )}
        <p>{message}</p>
        {retry && (
          <button type="button" className="secondary-button" onClick={retry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

function settingsErrorMessage(error: Error): string {
  if (error instanceof ApiError && error.status === 403) {
    return "You do not have permission to change this policy.";
  }
  return `Settings could not be saved: ${error.message}`;
}
