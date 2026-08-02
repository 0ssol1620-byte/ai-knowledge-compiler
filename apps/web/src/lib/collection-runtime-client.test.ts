import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchEventSourceMock } = vi.hoisted(() => ({
  fetchEventSourceMock: vi.fn(),
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

import { apiRequest } from "@/lib/api-client";
import {
  CollectionEventContractError,
  controlCollectionProcessing,
  getCollectionEvents,
  getCollectionScene,
  getDocumentVersionPagePreviewUrl,
  getProofCropUrl,
  retryCollectionProcessing,
  startCollectionProcessing,
  streamCollectionEvents,
} from "@/lib/collection-runtime-client";
import {
  loadCollectionRuntimePointer,
  saveCollectionRuntimePointer,
} from "@/lib/collection-storage";

vi.mock("@/lib/api-client", async () => {
  const actual =
    await vi.importActual<Record<string, unknown>>("@/lib/api-client");
  return { ...actual, apiRequest: vi.fn() };
});

vi.mock("@/lib/collection-storage", () => ({
  loadCollectionRuntimePointer: vi.fn(),
  saveCollectionRuntimePointer: vi.fn(async (value) => ({
    ...value,
    updatedAt: "2026-08-01T00:00:00Z",
  })),
}));

const collectionId = "00000000-0000-4000-8000-000000000001";
const jobId = "00000000-0000-4000-8000-000000000002";
const planId = "00000000-0000-4000-8000-000000000003";
const sha = "a".repeat(64);
const prefixedSha = `sha256:${"b".repeat(64)}`;
const resumeToken = "r".repeat(40);

const startInput = {
  collectionId,
  preflightSha256: sha,
  estimateSha256: "c".repeat(64),
  hardCapCredits: "48",
  overagePolicy: "stop_at_cap" as const,
  knowledgeBlueprintId: "general_knowledge_base",
  knowledgeBlueprintRegistrySha256: prefixedSha,
  knowledgeBlueprintModuleSha256: `sha256:${"d".repeat(64)}`,
  outputModules: [
    "source_index",
    "document_catalog",
    "knowledge_notes",
    "entities",
    "relations",
    "integrity",
    "export_manifest",
  ] as const,
};

function startResponse(overrides: Record<string, unknown> = {}) {
  return {
    id: planId,
    collection_id: collectionId,
    plan_version: 1,
    status: "compiled",
    input_integrity_sha256: sha,
    plan: {},
    modules: [],
    processing_job_id: jobId,
    processing_status: "queued",
    processing_resume_token: resumeToken,
    credits_reserved: "42",
    credits_consumed: "0",
    credits_refunded: "0",
    credits_released: "0",
    execution_scope: "collection_processing_runtime",
    created_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function pointer() {
  return {
    collectionId,
    startIdempotencyKey: "00000000-0000-4000-8000-000000000010",
    processingResumeToken: resumeToken,
    jobId,
    architecturePlanId: planId,
    status: "running",
    hardCapCredits: "48",
    overagePolicy: "stop_at_cap",
    updatedAt: "2026-08-01T00:00:00Z",
  };
}

function eventResponse(event: Record<string, unknown>) {
  return {
    snapshot: {
      collection_id: collectionId,
      status: "PROCESSING",
      manifest_revision: 1,
      latest_sequence: 17,
      upload: null,
      processing_job_id: jobId,
      processing_status: "running",
      processing_stage: "analysis",
      total_tasks: 64,
      completed_tasks: 0,
      failed_tasks: 0,
      credits_reserved: "42",
      credits_consumed: "0",
      credit_hard_cap: "48",
      terminal_result_ids: [],
    },
    events: [event],
    next_sequence: 17,
  };
}

function canonicalEvent(
  eventType: string,
  payload: Record<string, unknown>,
  overrides: Record<string, unknown> = {},
) {
  return {
    event_id: "00000000-0000-4000-8000-000000000004",
    collection_id: collectionId,
    job_id: jobId,
    sequence: 17,
    event_type: eventType,
    timestamp: "2026-08-01T00:00:17Z",
    payload,
    schema_version: "1.0",
    ...overrides,
  };
}

describe("collection processing runtime contract", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockReset();
    vi.mocked(apiRequest).mockReset();
    vi.mocked(loadCollectionRuntimePointer).mockReset();
    vi.mocked(saveCollectionRuntimePointer).mockClear();
  });

  it("accepts only a resumable runtime start bound to the approved hard cap", async () => {
    vi.mocked(loadCollectionRuntimePointer).mockResolvedValue(undefined);
    vi.mocked(apiRequest).mockResolvedValue(startResponse());

    const run = await startCollectionProcessing(startInput);

    expect(run).toEqual(
      expect.objectContaining({ job_id: jobId, status: "queued" }),
    );
    expect(apiRequest).toHaveBeenCalledWith(
      `/v1/collections/${collectionId}/compile`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it.each([
    { execution_scope: "existing_verified_artifacts_only" },
    { processing_job_id: null },
    { processing_resume_token: null },
    { processing_status: "completed" },
    { credits_reserved: "49" },
    { unexpected: true },
  ])(
    "fails closed for a non-runtime or over-cap start response",
    async (override) => {
      vi.mocked(loadCollectionRuntimePointer).mockResolvedValue(undefined);
      vi.mocked(apiRequest).mockResolvedValue(startResponse(override));
      await expect(
        startCollectionProcessing(startInput),
      ).rejects.toBeInstanceOf(CollectionEventContractError);
    },
  );

  it("uses the separate processing capability and rotates only its resume token", async () => {
    vi.mocked(loadCollectionRuntimePointer).mockResolvedValue(pointer());
    vi.mocked(apiRequest).mockResolvedValue({
      collection_id: collectionId,
      architecture_plan_id: planId,
      processing_job_id: jobId,
      collection_status: "PROCESSING",
      processing_status: "running",
      immutable_plan_sha256: sha,
      approved_preflight_sha256: sha,
      approved_estimate_sha256: "c".repeat(64),
      credit_hard_cap: "48",
      overage_policy: "stop_at_cap",
      total_tasks: 64,
      completed_tasks: 41,
      failed_tasks: 1,
      billable_pages: 986,
      unbillable_pages: 14,
      credits_reserved: "42",
      credits_consumed: "25",
      credits_refunded: "0",
      credits_released: "0",
      processing_resume_token: "s".repeat(40),
    });

    const run = await controlCollectionProcessing(collectionId, "resume");
    const [, request] = vi.mocked(apiRequest).mock.calls[0]!;
    const body = JSON.parse(String(request?.body));

    expect(vi.mocked(apiRequest).mock.calls[0]?.[0]).toBe(
      `/v1/collections/${collectionId}/processing/control`,
    );
    expect(body).toEqual({
      action: "resume",
      processing_resume_token: resumeToken,
    });
    expect(body).not.toHaveProperty("browser_resume_token");
    expect(run.task_counts.total).toBe(64);
    expect(saveCollectionRuntimePointer).toHaveBeenCalledWith(
      expect.objectContaining({ processingResumeToken: "s".repeat(40) }),
    );
  });

  it("reuses a pending processing-control key after an ambiguous response", async () => {
    vi.mocked(loadCollectionRuntimePointer).mockResolvedValue({
      ...pointer(),
      controlAction: "resume",
      controlIdempotencyKey: "00000000-0000-4000-8000-000000000066",
    });
    vi.mocked(apiRequest).mockRejectedValue(new TypeError("connection reset"));

    await expect(
      controlCollectionProcessing(collectionId, "resume"),
    ).rejects.toThrow("connection reset");

    expect(apiRequest).toHaveBeenCalledWith(
      `/v1/collections/${collectionId}/processing/control`,
      expect.objectContaining({
        idempotencyKey: "00000000-0000-4000-8000-000000000066",
      }),
    );
    expect(saveCollectionRuntimePointer).not.toHaveBeenCalled();
  });

  it("redrives a retryable collection without requiring a stale browser capability", async () => {
    vi.mocked(loadCollectionRuntimePointer).mockResolvedValue(undefined);
    vi.mocked(apiRequest).mockResolvedValue({
      collection_id: collectionId,
      architecture_plan_id: planId,
      processing_job_id: jobId,
      collection_status: "PROCESSING",
      processing_status: "queued",
      immutable_plan_sha256: sha,
      approved_preflight_sha256: sha,
      approved_estimate_sha256: "c".repeat(64),
      credit_hard_cap: "48",
      overage_policy: "stop_at_cap",
      total_tasks: 64,
      completed_tasks: 41,
      failed_tasks: 1,
      billable_pages: 986,
      unbillable_pages: 14,
      credits_reserved: "17",
      credits_consumed: "25",
      credits_refunded: "0",
      credits_released: "0",
      processing_resume_token: "s".repeat(40),
    });

    const run = await retryCollectionProcessing(collectionId);

    expect(apiRequest).toHaveBeenCalledWith(
      `/v1/collections/${collectionId}/processing/retry`,
      expect.objectContaining({
        method: "POST",
        body: "{}",
        idempotencyKey: expect.any(String),
      }),
    );
    expect(run).toEqual(
      expect.objectContaining({ status: "queued", job_id: jobId }),
    );
    expect(saveCollectionRuntimePointer).toHaveBeenCalledWith(
      expect.objectContaining({
        collectionId,
        processingResumeToken: "s".repeat(40),
        hardCapCredits: "48",
        retryIdempotencyKey: null,
      }),
    );
  });

  it("fails closed when processing retry returns another collection", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      collection_id: "00000000-0000-4000-8000-000000000099",
      architecture_plan_id: planId,
      processing_job_id: jobId,
      collection_status: "PROCESSING",
      processing_status: "queued",
      immutable_plan_sha256: sha,
      approved_preflight_sha256: sha,
      approved_estimate_sha256: "c".repeat(64),
      credit_hard_cap: "48",
      overage_policy: "stop_at_cap",
      total_tasks: 0,
      completed_tasks: 0,
      failed_tasks: 0,
      billable_pages: 0,
      unbillable_pages: 0,
      credits_reserved: "0",
      credits_consumed: "0",
      credits_refunded: "0",
      credits_released: "0",
      processing_resume_token: "s".repeat(40),
    });

    await expect(
      retryCollectionProcessing(collectionId),
    ).rejects.toBeInstanceOf(CollectionEventContractError);
    expect(saveCollectionRuntimePointer).toHaveBeenCalledTimes(1);
    expect(saveCollectionRuntimePointer).toHaveBeenCalledWith(
      expect.objectContaining({ retryIdempotencyKey: expect.any(String) }),
    );
  });

  it("reuses a pending retry key after an ambiguous response", async () => {
    vi.mocked(loadCollectionRuntimePointer).mockResolvedValue({
      ...pointer(),
      retryIdempotencyKey: "00000000-0000-4000-8000-000000000077",
    });
    vi.mocked(apiRequest).mockRejectedValue(new TypeError("connection reset"));

    await expect(retryCollectionProcessing(collectionId)).rejects.toThrow(
      "connection reset",
    );

    expect(apiRequest).toHaveBeenCalledWith(
      `/v1/collections/${collectionId}/processing/retry`,
      expect.objectContaining({
        idempotencyKey: "00000000-0000-4000-8000-000000000077",
      }),
    );
    expect(saveCollectionRuntimePointer).not.toHaveBeenCalled();
  });

  it("rejects an authoritative v1 snapshot that omits required processing evidence", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      snapshot: {
        collection_id: collectionId,
        status: "PROCESSING",
        manifest_revision: 1,
        latest_sequence: 1,
        upload: null,
        total_tasks: 0,
        completed_tasks: 0,
        failed_tasks: 0,
      },
      events: [],
      next_sequence: 1,
    });

    await expect(getCollectionEvents(collectionId)).rejects.toBeInstanceOf(
      CollectionEventContractError,
    );
  });

  it("accepts authoritative task progress in the collection snapshot", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      snapshot: {
        collection_id: collectionId,
        status: "PROCESSING",
        manifest_revision: 1,
        latest_sequence: 17,
        upload: null,
        processing_job_id: jobId,
        processing_status: "running",
        processing_stage: "analysis",
        total_tasks: 64,
        completed_tasks: 41,
        failed_tasks: 1,
        credits_reserved: "42",
        credits_consumed: "25",
        credit_hard_cap: "48",
        terminal_result_ids: [],
      },
      events: [],
      next_sequence: 17,
    });

    const response = await getCollectionEvents(collectionId, 16);

    expect(response.snapshot).toEqual(
      expect.objectContaining({
        total_tasks: 64,
        completed_tasks: 41,
        failed_tasks: 1,
      }),
    );
  });

  it("rejects replay events that drift from their typed payload contract", async () => {
    vi.mocked(apiRequest).mockResolvedValue(
      eventResponse(
        canonicalEvent("processing.started.v1", {
          collection_id: collectionId,
        }),
      ),
    );

    await expect(getCollectionEvents(collectionId, 16)).rejects.toBeInstanceOf(
      CollectionEventContractError,
    );
  });

  it("accepts canonical integer, object, and boolean event payload fields", async () => {
    vi.mocked(apiRequest).mockResolvedValue(
      eventResponse(
        canonicalEvent("block.completed.v1", {
          collection_id: collectionId,
          processing_job_id: jobId,
          block_count: 12,
          block_type_counts: { paragraph: 10, table: 2 },
          evidence_bound: true,
          forward_compatible_evidence: { retained: true },
        }),
      ),
    );

    const response = await getCollectionEvents(collectionId, 16);

    expect(response.events[0]?.event_type).toBe("block.completed.v1");
  });

  it.each([
    ["block_count", 12.5],
    ["block_type_counts", []],
    ["evidence_bound", "true"],
  ])(
    "rejects a required %s field with the wrong canonical descriptor",
    async (field, value) => {
      vi.mocked(apiRequest).mockResolvedValue(
        eventResponse(
          canonicalEvent("block.completed.v1", {
            collection_id: collectionId,
            processing_job_id: jobId,
            block_count: 12,
            block_type_counts: { paragraph: 12 },
            evidence_bound: true,
            [field]: value,
          }),
        ),
      );

      await expect(
        getCollectionEvents(collectionId, 16),
      ).rejects.toBeInstanceOf(CollectionEventContractError);
    },
  );

  it("validates present optional fields but permits their absence", async () => {
    const basePayload = {
      collection_id: collectionId,
      verified_files: 8,
    };
    vi.mocked(apiRequest).mockResolvedValue(
      eventResponse(canonicalEvent("file.security.passed.v1", basePayload)),
    );
    await expect(getCollectionEvents(collectionId, 16)).resolves.toBeDefined();

    vi.mocked(apiRequest).mockResolvedValue(
      eventResponse(
        canonicalEvent("file.security.passed.v1", {
          ...basePayload,
          source_files: "8",
        }),
      ),
    );
    await expect(getCollectionEvents(collectionId, 16)).rejects.toBeInstanceOf(
      CollectionEventContractError,
    );
  });

  it("accepts nullable canonical strings and rejects other values", async () => {
    const payload = {
      collection_id: collectionId,
      processing_job_id: null,
      export_id: "00000000-0000-4000-8000-000000000005",
      package_manifest_id: "00000000-0000-4000-8000-000000000006",
      profile: "full",
      completion_scope: "verified",
      status: "started",
    };
    vi.mocked(apiRequest).mockResolvedValue(
      eventResponse(
        canonicalEvent("export.started.v1", payload, { job_id: null }),
      ),
    );
    await expect(getCollectionEvents(collectionId, 16)).resolves.toBeDefined();

    vi.mocked(apiRequest).mockResolvedValue(
      eventResponse(
        canonicalEvent(
          "export.started.v1",
          { ...payload, processing_job_id: 7 },
          { job_id: null },
        ),
      ),
    );
    await expect(getCollectionEvents(collectionId, 16)).rejects.toBeInstanceOf(
      CollectionEventContractError,
    );
  });

  it("uses the durable integer sequence as the SSE Last-Event-ID replay cursor", async () => {
    fetchEventSourceMock.mockResolvedValueOnce(undefined);

    await streamCollectionEvents(
      {
        collectionId,
        afterSequence: 17,
        signal: new AbortController().signal,
      },
      {
        onConnection: vi.fn(),
        onEvent: vi.fn(),
      },
    );

    expect(fetchEventSourceMock).toHaveBeenCalledWith(
      expect.stringContaining(`/v1/collections/${collectionId}/events/stream`),
      expect.objectContaining({
        headers: expect.objectContaining({ "Last-Event-ID": "17" }),
      }),
    );
  });

  it("accepts a bounded identifier-only deterministic scene snapshot", async () => {
    const pageId = "00000000-0000-4000-8000-000000000021";
    vi.mocked(apiRequest).mockResolvedValue({
      collection_id: collectionId,
      collection_status: "PROCESSING",
      manifest_revision: 2,
      sequence: 17,
      total_pages: 1,
      projected_page_count: 1,
      route_state_counts: { "native:COMPLETED": 1 },
      clusters: [],
      pages: [
        {
          page_id: pageId,
          document_id: "00000000-0000-4000-8000-000000000022",
          document_version_id: "00000000-0000-4000-8000-000000000023",
          page_number: 1,
          status: "COMPLETED",
          route: "native",
          preview_ref: `/v1/pages/${pageId}/preview`,
          finding_count: 1,
        },
      ],
      knowledge: {
        note_ids: [],
        entity_ids: [],
        relation_ids: [],
        package_ids: [],
        note_count: 0,
        entity_count: 0,
        relation_count: 0,
        package_count: 0,
      },
      integrity: {
        file_status_counts: {},
        verification_status_counts: {},
        authority_mapping_status_counts: {},
        package_status_counts: {},
        unresolved_count: 0,
        quarantined_count: 0,
        blocker_codes: [],
      },
      scene_hash: "f".repeat(64),
    });

    await expect(getCollectionScene(collectionId)).resolves.toEqual(
      expect.objectContaining({ scene_hash: "f".repeat(64) }),
    );
  });

  it("rejects inconsistent scene counts and validates proof URLs locally", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      collection_id: collectionId,
      collection_status: "PROCESSING",
      manifest_revision: 1,
      sequence: 1,
      total_pages: 0,
      projected_page_count: 1,
      route_state_counts: {},
      clusters: [],
      pages: [],
      knowledge: {
        note_ids: [],
        entity_ids: [],
        relation_ids: [],
        package_ids: [],
        note_count: 0,
        entity_count: 0,
        relation_count: 0,
        package_count: 0,
      },
      integrity: {
        file_status_counts: {},
        verification_status_counts: {},
        authority_mapping_status_counts: {},
        package_status_counts: {},
        unresolved_count: 0,
        quarantined_count: 0,
        blocker_codes: [],
      },
      scene_hash: "f".repeat(64),
    });

    await expect(getCollectionScene(collectionId)).rejects.toBeInstanceOf(
      CollectionEventContractError,
    );
    expect(getDocumentVersionPagePreviewUrl(planId, 1)).toContain(
      `/v1/document-versions/${planId}/pages/1/preview`,
    );
    expect(getProofCropUrl(jobId)).toContain(`/v1/proofs/${jobId}/crop`);
    expect(() => getProofCropUrl("not-a-proof")).toThrow(
      CollectionEventContractError,
    );
  });

  it("fails closed before opening SSE when the replay sequence is invalid", async () => {
    await expect(
      streamCollectionEvents(
        {
          collectionId,
          afterSequence: -1,
          signal: new AbortController().signal,
        },
        { onConnection: vi.fn(), onEvent: vi.fn() },
      ),
    ).rejects.toBeInstanceOf(CollectionEventContractError);
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
  });
});
