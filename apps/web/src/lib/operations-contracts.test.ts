import { describe, expect, it } from "vitest";

import {
  normalizeAdminHealthResponse,
  normalizeSettingsResponse,
} from "@/lib/operations-contracts";

describe("normalizeSettingsResponse", () => {
  it("accepts flat policy fields without inventing optional data", () => {
    expect(
      normalizeSettingsResponse({
        tenant_id: "tenant-1",
        private_mode: true,
        external_transfer_allowed: false,
        training_opt_in: false,
        product_analytics_enabled: true,
        data_retention_days: 30,
      }),
    ).toMatchObject({
      tenantId: "tenant-1",
      privateMode: true,
      externalTransferAllowed: false,
      trainingOptIn: false,
      productAnalyticsEnabled: true,
      dataRetentionDays: 30,
      previewPiiMasking: undefined,
      members: [],
    });
  });

  it("accepts nested hosted settings and filters malformed members", () => {
    const result = normalizeSettingsResponse({
      tenant: { id: "tenant-2", name: "Lab" },
      privacy: { private_mode: false, mask_pii_in_previews: true },
      retention: { data_retention_days: 7 },
      capabilities: { can_manage_policy: true },
      members: [
        { user_id: "user-1", display_name: "Owner", role: "owner" },
        null,
      ],
    });
    expect(result.workspaceName).toBe("Lab");
    expect(result.previewPiiMasking).toBe(true);
    expect(result.members).toHaveLength(1);
  });
});

describe("normalizeAdminHealthResponse", () => {
  it("normalizes dependencies, queue evidence, and safe retry actions", () => {
    const result = normalizeAdminHealthResponse({
      status: "degraded",
      components: {
        database: { status: "healthy", latency_ms: 4 },
      },
      queue: { oldest_age_seconds: 12, dlq_count: 1 },
      jobs_requiring_intervention: [
        {
          job_id: "job-1",
          error_code: "PROVIDER_TIMEOUT",
          route_history: ["native", "ocr"],
          attempts: 2,
          max_attempts: 3,
          retryable: true,
          action_url: "https://malicious.example/retry",
        },
      ],
    });
    expect(result.dependencies[0]).toEqual({
      name: "database",
      status: "healthy",
      detail: undefined,
      latencyMs: 4,
    });
    expect(result.oldestQueueAgeSeconds).toBe(12);
    expect(result.interventions[0]?.actionUrl).toBe(
      "/v1/admin/jobs/job-1/retry",
    );
  });
});
