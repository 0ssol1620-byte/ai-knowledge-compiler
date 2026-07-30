type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordAt(root: UnknownRecord, key: string): UnknownRecord {
  return isRecord(root[key]) ? root[key] : {};
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0
    ? value
    : undefined;
}

function optionalBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function firstDefined<T>(...values: Array<T | undefined>): T | undefined {
  return values.find((value) => value !== undefined);
}

export interface WorkspaceMember {
  id?: string;
  displayName?: string;
  email?: string;
  role?: string;
  status?: string;
}

export interface SettingsSnapshot {
  tenantId?: string;
  workspaceName?: string;
  updatedAt?: string;
  privateMode?: boolean;
  externalTransferAllowed?: boolean;
  trainingOptIn?: boolean;
  previewPiiMasking?: boolean;
  productAnalyticsEnabled?: boolean;
  dataRetentionDays?: number;
  canManagePolicy?: boolean;
  members: WorkspaceMember[];
}

export function normalizeSettingsResponse(payload: unknown): SettingsSnapshot {
  if (!isRecord(payload)) {
    throw new Error("The settings response has an invalid format.");
  }
  const tenant = recordAt(payload, "tenant");
  const privacy = recordAt(payload, "privacy");
  const retention = recordAt(payload, "retention");
  const capabilities = recordAt(payload, "capabilities");
  const rawMembers = Array.isArray(payload.members) ? payload.members : [];

  const members = rawMembers.flatMap((entry): WorkspaceMember[] => {
    if (!isRecord(entry)) return [];
    const member = {
      id: firstDefined(optionalString(entry.id), optionalString(entry.user_id)),
      displayName: firstDefined(
        optionalString(entry.display_name),
        optionalString(entry.name),
      ),
      email: optionalString(entry.email),
      role: optionalString(entry.role),
      status: optionalString(entry.status),
    };
    return member.id || member.displayName || member.email ? [member] : [];
  });

  return {
    tenantId: firstDefined(
      optionalString(payload.tenant_id),
      optionalString(tenant.id),
    ),
    workspaceName: firstDefined(
      optionalString(payload.workspace_name),
      optionalString(tenant.name),
    ),
    updatedAt: firstDefined(
      optionalString(payload.updated_at),
      optionalString(tenant.updated_at),
    ),
    privateMode: firstDefined(
      optionalBoolean(payload.private_mode),
      optionalBoolean(privacy.private_mode),
      optionalBoolean(tenant.private_mode),
    ),
    externalTransferAllowed: firstDefined(
      optionalBoolean(payload.external_transfer_allowed),
      optionalBoolean(privacy.external_transfer_allowed),
      optionalBoolean(tenant.external_transfer_allowed),
    ),
    trainingOptIn: firstDefined(
      optionalBoolean(payload.training_opt_in),
      optionalBoolean(privacy.training_opt_in),
      optionalBoolean(tenant.training_opt_in),
    ),
    previewPiiMasking: firstDefined(
      optionalBoolean(payload.preview_pii_masking),
      optionalBoolean(privacy.preview_pii_masking),
      optionalBoolean(privacy.mask_pii_in_previews),
    ),
    productAnalyticsEnabled: firstDefined(
      optionalBoolean(payload.product_analytics_enabled),
      optionalBoolean(privacy.product_analytics_enabled),
    ),
    dataRetentionDays: firstDefined(
      optionalNumber(payload.data_retention_days),
      optionalNumber(retention.data_retention_days),
      optionalNumber(tenant.data_retention_days),
    ),
    canManagePolicy: firstDefined(
      optionalBoolean(payload.can_manage_policy),
      optionalBoolean(capabilities.can_manage_policy),
    ),
    members,
  };
}

export interface AdminDependency {
  name: string;
  status?: string;
  detail?: string;
  latencyMs?: number;
}

export interface AdminIntervention {
  jobId: string;
  errorCode?: string;
  routeHistory?: string;
  attempts?: number;
  maxAttempts?: number;
  retryable: boolean;
  actionLabel?: string;
  actionUrl?: string;
}

export interface AdminHealthSnapshot {
  status?: string;
  generatedAt?: string;
  oldestQueueAgeSeconds?: number;
  queuedJobs?: number;
  runningJobs?: number;
  dlqCount?: number;
  terminalSuccessRate?: number;
  dependencies: AdminDependency[];
  interventions: AdminIntervention[];
}

function normalizeDependency(name: string, value: unknown): AdminDependency {
  if (isRecord(value)) {
    return {
      name,
      status: firstDefined(
        optionalString(value.status),
        optionalString(value.state),
      ),
      detail: firstDefined(
        optionalString(value.detail),
        optionalString(value.message),
        optionalString(value.version),
      ),
      latencyMs: firstDefined(
        optionalNumber(value.latency_ms),
        optionalNumber(value.latency),
      ),
    };
  }
  return { name, status: optionalString(value) };
}

export function normalizeAdminHealthResponse(
  payload: unknown,
): AdminHealthSnapshot {
  if (!isRecord(payload)) {
    throw new Error("The operations response has an invalid format.");
  }
  const metrics = recordAt(payload, "metrics");
  const queue = isRecord(payload.queue)
    ? payload.queue
    : isRecord(payload.queues)
      ? payload.queues
      : {};
  const dependencySource = isRecord(payload.dependencies)
    ? payload.dependencies
    : isRecord(payload.components)
      ? payload.components
      : {};
  const dependencies = Object.entries(dependencySource).map(([name, value]) =>
    normalizeDependency(name, value),
  );

  if (Array.isArray(payload.dependencies)) {
    for (const entry of payload.dependencies) {
      if (!isRecord(entry)) continue;
      const name = firstDefined(
        optionalString(entry.name),
        optionalString(entry.component),
      );
      if (name) dependencies.push(normalizeDependency(name, entry));
    }
  }

  const rawInterventions = [
    ...(Array.isArray(payload.interventions) ? payload.interventions : []),
    ...(Array.isArray(payload.jobs_requiring_intervention)
      ? payload.jobs_requiring_intervention
      : []),
    ...(Array.isArray(payload.failed_jobs) ? payload.failed_jobs : []),
  ];
  const seenJobs = new Set<string>();
  const interventions = rawInterventions.flatMap(
    (entry): AdminIntervention[] => {
      if (!isRecord(entry)) return [];
      const jobId = firstDefined(
        optionalString(entry.job_id),
        optionalString(entry.id),
      );
      if (!jobId || seenJobs.has(jobId)) return [];
      seenJobs.add(jobId);
      const route = entry.route_history;
      const routeHistory = Array.isArray(route)
        ? route
            .filter((value): value is string => typeof value === "string")
            .join(" → ")
        : optionalString(route);
      const retryable =
        optionalBoolean(entry.retryable) ??
        optionalString(entry.action)?.toLowerCase() === "retry";
      const suppliedActionUrl = optionalString(entry.action_url);
      const safeActionUrl = suppliedActionUrl?.startsWith("/v1/admin/")
        ? suppliedActionUrl
        : undefined;
      return [
        {
          jobId,
          errorCode: firstDefined(
            optionalString(entry.error_code),
            optionalString(entry.error),
          ),
          routeHistory,
          attempts: optionalNumber(entry.attempts),
          maxAttempts: optionalNumber(entry.max_attempts),
          retryable,
          actionLabel: optionalString(entry.action_label),
          actionUrl:
            safeActionUrl ??
            (retryable
              ? `/v1/admin/jobs/${encodeURIComponent(jobId)}/retry`
              : undefined),
        },
      ];
    },
  );

  return {
    status: firstDefined(
      optionalString(payload.status),
      optionalString(payload.overall_status),
    ),
    generatedAt: optionalString(payload.generated_at),
    oldestQueueAgeSeconds: firstDefined(
      optionalNumber(payload.oldest_queue_age_seconds),
      optionalNumber(queue.oldest_age_seconds),
      optionalNumber(metrics.oldest_queue_age_seconds),
    ),
    queuedJobs: firstDefined(
      optionalNumber(payload.queued_jobs),
      optionalNumber(queue.queued),
      optionalNumber(metrics.queued_jobs),
    ),
    runningJobs: firstDefined(
      optionalNumber(payload.running_jobs),
      optionalNumber(queue.running),
      optionalNumber(metrics.running_jobs),
    ),
    dlqCount: firstDefined(
      optionalNumber(payload.dlq_count),
      optionalNumber(queue.dlq_count),
      optionalNumber(queue.dead_letter_count),
      optionalNumber(metrics.dlq_count),
    ),
    terminalSuccessRate: firstDefined(
      optionalNumber(payload.terminal_success_rate),
      optionalNumber(metrics.terminal_success_rate),
    ),
    dependencies,
    interventions,
  };
}
