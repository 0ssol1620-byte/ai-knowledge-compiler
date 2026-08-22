import { fetchEventSource } from "@microsoft/fetch-event-source";
import {
  COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS,
  COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS,
  COLLECTION_EVENT_TYPES,
  type CollectionEventGenerated,
  type CollectionEventType,
} from "@akc/contracts";
import { z } from "zod";

import { apiAbsoluteUrl, ApiError, apiRequest } from "@/lib/api-client";
import type { CollectionUploadSummary } from "@/lib/collection-client";
import {
  loadCollectionRuntimePointer,
  saveCollectionRuntimePointer,
} from "@/lib/collection-storage";

export type CollectionState =
  | "CREATED"
  | "DISCOVERING"
  | "HASHING"
  | "UPLOADING"
  | "VERIFYING"
  | "SECURITY_SCAN"
  | "DEDUPLICATING"
  | "INGESTED"
  | "PREFLIGHTING"
  | "ESTIMATED"
  | "AWAITING_APPROVAL"
  | "PROCESSING"
  | "VERIFYING_OUTPUT"
  | "KNOWLEDGE_COMPILING"
  | "PACKAGING"
  | "COMPLETED"
  | "PAUSED"
  | "PARTIAL"
  | "FAILED_RETRYABLE"
  | "UNRESOLVED"
  | "QUARANTINED"
  | "CANCEL_REQUESTED"
  | "CANCELED"
  | "PURGED";

const COLLECTION_STATES = [
  "CREATED",
  "DISCOVERING",
  "HASHING",
  "UPLOADING",
  "VERIFYING",
  "SECURITY_SCAN",
  "DEDUPLICATING",
  "INGESTED",
  "PREFLIGHTING",
  "ESTIMATED",
  "AWAITING_APPROVAL",
  "PROCESSING",
  "VERIFYING_OUTPUT",
  "KNOWLEDGE_COMPILING",
  "PACKAGING",
  "COMPLETED",
  "PAUSED",
  "PARTIAL",
  "FAILED_RETRYABLE",
  "UNRESOLVED",
  "QUARANTINED",
  "CANCEL_REQUESTED",
  "CANCELED",
  "PURGED",
] as const satisfies readonly CollectionState[];

export type CollectionEvent = CollectionEventGenerated;
export type { CollectionEventType };

export type CollectionEventSnapshot = {
  collection_id: string;
  status: CollectionState;
  manifest_revision: number;
  latest_sequence: number;
  upload: CollectionUploadSummary | null;
  processing_job_id: string | null;
  processing_status:
    | "queued"
    | "running"
    | "paused"
    | "completed"
    | "failed"
    | "cancelled"
    | null;
  processing_stage: string | null;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  credits_reserved: string | number;
  credits_consumed: string | number;
  credit_hard_cap: string | number;
  terminal_result_ids: string[];
};

export type CollectionEventsResponse = {
  snapshot: CollectionEventSnapshot;
  events: CollectionEvent[];
  next_sequence: number;
};

export type CollectionIntegritySummary = {
  collection_id: string;
  collection_status: CollectionState;
  manifest_hash: string | null;
  integrity_sha256: string;
  file_status_counts: Record<string, number>;
  verification_status_counts: Record<string, number>;
  authority_mapping_status_counts: Record<string, number>;
  package_status_counts: Record<string, number>;
  ready_for_compile: boolean;
  ready_for_full_package: boolean;
  blockers: string[];
};

export type CollectionScene = {
  collection_id: string;
  collection_status: CollectionState;
  manifest_revision: number;
  sequence: number;
  total_pages: number;
  projected_page_count: number;
  route_state_counts: Record<string, number>;
  clusters: Array<{
    cluster_id: string;
    strategy: string;
    member_count: number;
    representative_file_ids: string[];
    outlier_count: number;
  }>;
  pages: Array<{
    page_id: string;
    document_id: string;
    document_version_id: string | null;
    page_number: number;
    status: string;
    route: string | null;
    preview_ref: string | null;
    finding_count: number;
  }>;
  knowledge: {
    note_ids: string[];
    entity_ids: string[];
    relation_ids: string[];
    package_ids: string[];
    note_count: number;
    entity_count: number;
    relation_count: number;
    package_count: number;
  };
  integrity: {
    file_status_counts: Record<string, number>;
    verification_status_counts: Record<string, number>;
    authority_mapping_status_counts: Record<string, number>;
    package_status_counts: Record<string, number>;
    unresolved_count: number;
    quarantined_count: number;
    blocker_codes: string[];
  };
  scene_hash: string;
};

export type CollectionOveragePolicy =
  "stop_at_cap" | "allow_10_percent" | "continue_within_balance";

export type CollectionProcessingRun = {
  run_id: string;
  job_id: string | null;
  architecture_plan_id: string | null;
  status: string;
  task_counts: Record<string, number>;
  credits_reserved: string | number;
  credits_consumed: string | number;
  credits_refunded: string | number;
  credits_released: string | number;
  hard_cap_credits: string | number;
  overage_policy: CollectionOveragePolicy;
  resume_token?: string | null;
};

export type CollectionProcessingControlResult = {
  collection_id: string;
  architecture_plan_id: string;
  processing_job_id: string;
  collection_status: CollectionState;
  processing_status:
    "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";
  immutable_plan_sha256: string;
  approved_preflight_sha256: string;
  approved_estimate_sha256: string;
  credit_hard_cap: string | number;
  overage_policy: CollectionOveragePolicy;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  billable_pages: number;
  unbillable_pages: number;
  credits_reserved: string | number;
  credits_consumed: string | number;
  credits_refunded: string | number;
  credits_released: string | number;
  processing_resume_token: string | null;
};

const decimalSchema = z.union([
  z.number().nonnegative().finite(),
  z.string().regex(/^\d+(?:\.\d+)?$/),
]);
const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const prefixedSha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const collectionStateSchema = z.enum(COLLECTION_STATES);
const overagePolicySchema = z.enum([
  "stop_at_cap",
  "allow_10_percent",
  "continue_within_balance",
]);

const architecturePlanStartSchema = z
  .object({
    id: z.uuid(),
    collection_id: z.uuid(),
    plan_version: z.number().int().positive(),
    status: z.enum(["planned", "compiled", "stale", "failed"]),
    input_integrity_sha256: sha256Schema,
    plan: z.record(z.string(), z.unknown()),
    modules: z.array(
      z
        .object({
          id: z.uuid(),
          module_key: z.enum([
            "source_index",
            "document_catalog",
            "knowledge_notes",
            "entities",
            "relations",
            "integrity",
            "export_manifest",
          ]),
          module_version: z.string().min(1),
          status: z.enum(["planned", "compiled", "skipped", "failed"]),
          config: z.record(z.string(), z.unknown()),
          output_summary: z.record(z.string(), z.unknown()),
        })
        .strict(),
    ),
    processing_job_id: z.uuid().nullable(),
    processing_status: z
      .enum(["queued", "running", "paused", "completed", "failed", "cancelled"])
      .nullable(),
    processing_resume_token: z.string().min(32).max(256).nullable(),
    credits_reserved: decimalSchema,
    credits_consumed: decimalSchema,
    credits_refunded: decimalSchema,
    credits_released: decimalSchema,
    execution_scope: z.enum([
      "existing_verified_artifacts_only",
      "collection_processing_runtime",
    ]),
    created_at: z.iso.datetime({ offset: true }),
  })
  .strict();

const processingControlSchema = z
  .object({
    collection_id: z.uuid(),
    architecture_plan_id: z.uuid(),
    processing_job_id: z.uuid(),
    collection_status: collectionStateSchema,
    processing_status: z.enum([
      "queued",
      "running",
      "paused",
      "completed",
      "failed",
      "cancelled",
    ]),
    immutable_plan_sha256: sha256Schema,
    approved_preflight_sha256: sha256Schema,
    approved_estimate_sha256: sha256Schema,
    credit_hard_cap: decimalSchema,
    overage_policy: overagePolicySchema,
    total_tasks: z.number().int().nonnegative(),
    completed_tasks: z.number().int().nonnegative(),
    failed_tasks: z.number().int().nonnegative(),
    billable_pages: z.number().int().nonnegative(),
    unbillable_pages: z.number().int().nonnegative(),
    credits_reserved: decimalSchema,
    credits_consumed: decimalSchema,
    credits_refunded: decimalSchema,
    credits_released: decimalSchema,
    processing_resume_token: z.string().min(32).max(256).nullable(),
  })
  .strict();

type CollectionPayloadFieldDescriptor =
  "string" | "integer" | "boolean" | "object" | "array" | "string|null";

function matchesPayloadFieldDescriptor(
  value: unknown,
  descriptor: CollectionPayloadFieldDescriptor,
): boolean {
  switch (descriptor) {
    case "string":
      return typeof value === "string";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "boolean":
      return typeof value === "boolean";
    case "object":
      return (
        typeof value === "object" && value !== null && !Array.isArray(value)
      );
    case "array":
      return Array.isArray(value);
    case "string|null":
      return typeof value === "string" || value === null;
  }
}

function hasOwnPayloadField(
  payload: Record<string, unknown>,
  key: string,
): boolean {
  return Object.prototype.hasOwnProperty.call(payload, key);
}

const collectionEventSchema = z
  .object({
    event_id: z.uuid(),
    collection_id: z.uuid(),
    job_id: z.uuid().nullable(),
    sequence: z.number().int().positive(),
    event_type: z.enum(COLLECTION_EVENT_TYPES),
    timestamp: z.iso.datetime({ offset: true }),
    payload: z.record(z.string(), z.unknown()),
    schema_version: z.literal("1.0"),
  })
  .strict()
  .superRefine((event, context) => {
    const required = COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS[event.event_type];
    for (const [key, expected] of Object.entries(required)) {
      const value = event.payload[key];
      const valid =
        hasOwnPayloadField(event.payload, key) &&
        matchesPayloadFieldDescriptor(
          value,
          expected as CollectionPayloadFieldDescriptor,
        );
      if (!valid) {
        context.addIssue({
          code: "custom",
          path: ["payload", key],
          message: `Expected the canonical ${expected} payload field.`,
        });
      }
    }
    const optional = COLLECTION_EVENT_OPTIONAL_PAYLOAD_FIELDS[event.event_type];
    for (const [key, expected] of Object.entries(optional)) {
      if (
        hasOwnPayloadField(event.payload, key) &&
        !matchesPayloadFieldDescriptor(
          event.payload[key],
          expected as CollectionPayloadFieldDescriptor,
        )
      ) {
        context.addIssue({
          code: "custom",
          path: ["payload", key],
          message: `Expected the canonical optional ${expected} payload field.`,
        });
      }
    }
    if (event.payload.collection_id !== event.collection_id) {
      context.addIssue({
        code: "custom",
        path: ["payload", "collection_id"],
        message: "Collection event payload identity mismatch.",
      });
    }
    if (
      typeof event.payload.processing_job_id === "string" &&
      event.payload.processing_job_id !== event.job_id
    ) {
      context.addIssue({
        code: "custom",
        path: ["payload", "processing_job_id"],
        message: "Collection event job correlation mismatch.",
      });
    }
  });

const collectionSnapshotSchema = z
  .object({
    collection_id: z.uuid(),
    status: collectionStateSchema,
    manifest_revision: z.number().int().nonnegative(),
    latest_sequence: z.number().int().nonnegative(),
    upload: z
      .object({
        upload_session_id: z.uuid(),
        manifest_revision: z.number().int().positive(),
        resume_version: z.number().int().positive(),
        status: z.enum([
          "planned",
          "uploading",
          "completed",
          "partial",
          "expired",
          "aborted",
        ]),
        total_files: z.number().int().nonnegative(),
        total_bytes: z.number().int().nonnegative(),
        completed_files: z.number().int().nonnegative(),
        active_files: z.number().int().nonnegative(),
        failed_files: z.number().int().nonnegative(),
        duplicate_files: z.number().int().nonnegative(),
        source_manifest_hash: sha256Schema,
        expires_at: z.iso.datetime({ offset: true }),
      })
      .strict()
      .nullable(),
    processing_job_id: z.uuid().nullable(),
    processing_status: z
      .enum(["queued", "running", "paused", "completed", "failed", "cancelled"])
      .nullable(),
    processing_stage: z.string().min(1).nullable(),
    total_tasks: z.number().int().nonnegative(),
    completed_tasks: z.number().int().nonnegative(),
    failed_tasks: z.number().int().nonnegative(),
    credits_reserved: decimalSchema,
    credits_consumed: decimalSchema,
    credit_hard_cap: decimalSchema,
    terminal_result_ids: z.array(z.uuid()),
  })
  .strict();

const collectionEventsSchema = z
  .object({
    snapshot: collectionSnapshotSchema,
    events: z.array(collectionEventSchema),
    next_sequence: z.number().int().nonnegative(),
  })
  .strict();

const nonnegativeCountRecordSchema = z.record(
  z.string().min(1),
  z.number().int().nonnegative(),
);
const collectionIntegritySchema = z
  .object({
    collection_id: z.uuid(),
    collection_status: collectionStateSchema,
    manifest_hash: sha256Schema.nullable(),
    integrity_sha256: sha256Schema,
    file_status_counts: nonnegativeCountRecordSchema,
    verification_status_counts: nonnegativeCountRecordSchema,
    authority_mapping_status_counts: nonnegativeCountRecordSchema,
    package_status_counts: nonnegativeCountRecordSchema,
    ready_for_compile: z.boolean(),
    ready_for_full_package: z.boolean(),
    blockers: z.array(z.string().min(1)),
  })
  .strict();

const collectionSceneSchema = z
  .object({
    collection_id: z.uuid(),
    collection_status: collectionStateSchema,
    manifest_revision: z.number().int().nonnegative(),
    sequence: z.number().int().nonnegative(),
    total_pages: z.number().int().nonnegative(),
    projected_page_count: z.number().int().nonnegative().max(200),
    route_state_counts: nonnegativeCountRecordSchema,
    clusters: z.array(
      z
        .object({
          cluster_id: z.uuid(),
          strategy: z.string().min(1),
          member_count: z.number().int().positive(),
          representative_file_ids: z.array(z.uuid()),
          outlier_count: z.number().int().nonnegative(),
        })
        .strict(),
    ),
    pages: z.array(
      z
        .object({
          page_id: z.uuid(),
          document_id: z.uuid(),
          document_version_id: z.uuid().nullable(),
          page_number: z.number().int().positive(),
          status: z.string().min(1),
          route: z.string().min(1).nullable(),
          preview_ref: z
            .string()
            .regex(/^\/v1\/pages\/[0-9a-f-]{36}\/preview$/)
            .nullable(),
          finding_count: z.number().int().nonnegative(),
        })
        .strict(),
    ),
    knowledge: z
      .object({
        note_ids: z.array(z.uuid()),
        entity_ids: z.array(z.uuid()),
        relation_ids: z.array(z.uuid()),
        package_ids: z.array(z.uuid()),
        note_count: z.number().int().nonnegative(),
        entity_count: z.number().int().nonnegative(),
        relation_count: z.number().int().nonnegative(),
        package_count: z.number().int().nonnegative(),
      })
      .strict(),
    integrity: z
      .object({
        file_status_counts: nonnegativeCountRecordSchema,
        verification_status_counts: nonnegativeCountRecordSchema,
        authority_mapping_status_counts: nonnegativeCountRecordSchema,
        package_status_counts: nonnegativeCountRecordSchema,
        unresolved_count: z.number().int().nonnegative(),
        quarantined_count: z.number().int().nonnegative(),
        blocker_codes: z.array(z.string().min(1)),
      })
      .strict(),
    scene_hash: sha256Schema,
  })
  .strict()
  .superRefine((scene, context) => {
    if (scene.projected_page_count !== scene.pages.length) {
      context.addIssue({
        code: "custom",
        path: ["projected_page_count"],
        message: "Projected page count must match the bounded page projection.",
      });
    }
    if (scene.projected_page_count > scene.total_pages) {
      context.addIssue({
        code: "custom",
        path: ["total_pages"],
        message: "The page projection cannot exceed the collection page total.",
      });
    }
  });

export class CollectionEventContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CollectionEventContractError";
  }
}

export class CollectionSseUnavailableError extends Error {
  constructor() {
    super("Collection SSE is unavailable; use the durable cursor snapshot.");
    this.name = "CollectionSseUnavailableError";
  }
}

export async function startCollectionProcessing(input: {
  collectionId: string;
  preflightSha256: string;
  estimateSha256: string;
  hardCapCredits: string | number;
  overagePolicy: CollectionOveragePolicy;
  knowledgeBlueprintId: string;
  knowledgeBlueprintRegistrySha256: string;
  knowledgeBlueprintModuleSha256: string;
  outputModules: readonly string[];
}): Promise<CollectionProcessingRun> {
  assertStartContract(input);
  const existing = await loadCollectionRuntimePointer(input.collectionId);
  const pointer =
    existing ??
    (await saveCollectionRuntimePointer({
      collectionId: input.collectionId,
      startIdempotencyKey: crypto.randomUUID(),
      hardCapCredits: input.hardCapCredits,
      overagePolicy: input.overagePolicy,
    }));
  const raw = await apiRequest<unknown>(
    `/v1/collections/${input.collectionId}/compile`,
    {
      method: "POST",
      idempotencyKey: pointer.startIdempotencyKey,
      body: JSON.stringify({
        approve_estimate: true,
        approved_preflight_sha256: input.preflightSha256,
        approved_estimate_sha256: input.estimateSha256,
        credit_hard_cap: input.hardCapCredits,
        overage_policy: input.overagePolicy,
        knowledge_blueprint_id: input.knowledgeBlueprintId,
        knowledge_blueprint_registry_sha256:
          input.knowledgeBlueprintRegistrySha256,
        knowledge_blueprint_module_sha256: input.knowledgeBlueprintModuleSha256,
        output_modules: input.outputModules,
      }),
    },
  );
  const parsed = architecturePlanStartSchema.safeParse(raw);
  if (!parsed.success) {
    throw new CollectionEventContractError(
      "The processing start response does not match the strict architecture-plan contract.",
    );
  }
  const response = parsed.data;
  if (response.collection_id !== input.collectionId) {
    throw new CollectionEventContractError(
      "The processing start response belongs to another collection.",
    );
  }
  if (
    response.execution_scope !== "collection_processing_runtime" ||
    response.processing_job_id === null ||
    response.processing_resume_token === null ||
    !["queued", "running"].includes(response.processing_status ?? "")
  ) {
    throw new CollectionEventContractError(
      "The server did not start a resumable collection-processing runtime.",
    );
  }
  if (
    Number(response.credits_reserved) > Number(input.hardCapCredits) ||
    !Number.isFinite(Number(response.credits_reserved))
  ) {
    throw new CollectionEventContractError(
      "The reserved credits exceed the customer-approved hard cap.",
    );
  }
  const stored = await saveCollectionRuntimePointer({
    ...pointer,
    collectionId: input.collectionId,
    processingResumeToken:
      response.processing_resume_token ?? pointer.processingResumeToken ?? null,
    jobId: response.processing_job_id ?? pointer.jobId ?? null,
    architecturePlanId: response.id,
    status: response.processing_status ?? response.status,
    creditsReserved: response.credits_reserved ?? pointer.creditsReserved ?? 0,
    creditsConsumed: response.credits_consumed ?? pointer.creditsConsumed ?? 0,
    creditsRefunded: response.credits_refunded ?? pointer.creditsRefunded ?? 0,
    creditsReleased: response.credits_released ?? pointer.creditsReleased ?? 0,
    hardCapCredits: input.hardCapCredits,
    overagePolicy: input.overagePolicy,
  });
  return runtimeFromPointer(stored);
}

export async function controlCollectionProcessing(
  collectionId: string,
  action: "pause" | "resume",
): Promise<CollectionProcessingRun> {
  let pointer = await loadCollectionRuntimePointer(collectionId);
  if (!pointer) {
    throw new CollectionEventContractError(
      "The local processing pointer is unavailable. Re-open processing from its approved collection.",
    );
  }
  if (action === "resume" && !pointer.processingResumeToken) {
    throw new CollectionEventContractError(
      "The one-time processing resume token is unavailable. Re-open this collection from the original browser session.",
    );
  }
  const controlIdempotencyKey =
    pointer.controlAction === action && pointer.controlIdempotencyKey
      ? pointer.controlIdempotencyKey
      : crypto.randomUUID();
  if (
    pointer.controlAction !== action ||
    pointer.controlIdempotencyKey !== controlIdempotencyKey
  ) {
    pointer = await saveCollectionRuntimePointer({
      ...pointer,
      controlAction: action,
      controlIdempotencyKey,
    });
  }
  let raw: unknown;
  try {
    raw = await apiRequest<unknown>(
      `/v1/collections/${collectionId}/processing/control`,
      {
        method: "POST",
        idempotencyKey: controlIdempotencyKey,
        body: JSON.stringify({
          action,
          ...(action === "resume"
            ? { processing_resume_token: pointer.processingResumeToken }
            : {}),
        }),
      },
    );
  } catch (error) {
    if (error instanceof ApiError && !error.retryable) {
      await saveCollectionRuntimePointer({
        ...pointer,
        controlAction: null,
        controlIdempotencyKey: null,
      });
    }
    throw error;
  }
  const parsed = processingControlSchema.safeParse(raw);
  if (!parsed.success) {
    throw new CollectionEventContractError(
      "The processing control response does not match the strict runtime contract.",
    );
  }
  const response = parsed.data;
  if (response.collection_id !== collectionId) {
    throw new CollectionEventContractError(
      "The processing control response belongs to another collection.",
    );
  }
  const stored = await saveCollectionRuntimePointer({
    ...pointer,
    collectionId,
    controlAction: null,
    controlIdempotencyKey: null,
    architecturePlanId: response.architecture_plan_id,
    jobId: response.processing_job_id,
    status:
      response.collection_status === "PAUSED"
        ? "paused"
        : response.processing_status,
    processingResumeToken:
      response.processing_resume_token ?? pointer.processingResumeToken ?? null,
    creditsReserved: response.credits_reserved,
    creditsConsumed: response.credits_consumed,
    creditsRefunded: response.credits_refunded,
    creditsReleased: response.credits_released,
    hardCapCredits: response.credit_hard_cap,
    overagePolicy: response.overage_policy,
  });
  return runtimeFromPointer(stored, {
    total: response.total_tasks,
    completed: response.completed_tasks,
    failed: response.failed_tasks,
    billable_pages: response.billable_pages,
    unbillable_pages: response.unbillable_pages,
  });
}

export async function retryCollectionProcessing(
  collectionId: string,
  creditHardCap?: string | number,
): Promise<CollectionProcessingRun> {
  let pointer = await loadCollectionRuntimePointer(collectionId);
  const retryIdempotencyKey =
    pointer?.retryIdempotencyKey ?? crypto.randomUUID();
  if (!pointer?.retryIdempotencyKey) {
    pointer = await saveCollectionRuntimePointer({
      ...(pointer ?? {
        collectionId,
        startIdempotencyKey: crypto.randomUUID(),
      }),
      collectionId,
      retryIdempotencyKey,
    });
  }
  let raw: unknown;
  try {
    raw = await apiRequest<unknown>(
      `/v1/collections/${collectionId}/processing/retry`,
      {
        method: "POST",
        idempotencyKey: retryIdempotencyKey,
        body: JSON.stringify(
          creditHardCap === undefined ? {} : { credit_hard_cap: creditHardCap },
        ),
      },
    );
  } catch (error) {
    if (error instanceof ApiError && !error.retryable) {
      await saveCollectionRuntimePointer({
        ...pointer,
        retryIdempotencyKey: null,
      });
    }
    throw error;
  }
  const parsed = processingControlSchema.safeParse(raw);
  if (!parsed.success) {
    throw new CollectionEventContractError(
      "The processing retry response does not match the strict runtime contract.",
    );
  }
  const response = parsed.data;
  if (response.collection_id !== collectionId) {
    throw new CollectionEventContractError(
      "The processing retry response belongs to another collection.",
    );
  }
  const stored = await saveCollectionRuntimePointer({
    ...pointer,
    collectionId,
    retryIdempotencyKey: null,
    architecturePlanId: response.architecture_plan_id,
    jobId: response.processing_job_id,
    status: response.processing_status,
    processingResumeToken:
      response.processing_resume_token ?? pointer.processingResumeToken ?? null,
    creditsReserved: response.credits_reserved,
    creditsConsumed: response.credits_consumed,
    creditsRefunded: response.credits_refunded,
    creditsReleased: response.credits_released,
    hardCapCredits: response.credit_hard_cap,
    overagePolicy: response.overage_policy,
  });
  return runtimeFromPointer(stored, {
    total: response.total_tasks,
    completed: response.completed_tasks,
    failed: response.failed_tasks,
    billable_pages: response.billable_pages,
    unbillable_pages: response.unbillable_pages,
  });
}

export async function restoreCollectionProcessing(
  collectionId: string,
): Promise<CollectionProcessingRun | undefined> {
  const pointer = await loadCollectionRuntimePointer(collectionId);
  return pointer ? runtimeFromPointer(pointer) : undefined;
}

function runtimeFromPointer(
  pointer: Awaited<ReturnType<typeof saveCollectionRuntimePointer>>,
  taskCounts: Record<string, number> = {},
): CollectionProcessingRun {
  return {
    run_id: pointer.architecturePlanId ?? pointer.jobId ?? pointer.collectionId,
    job_id: pointer.jobId ?? null,
    architecture_plan_id: pointer.architecturePlanId ?? null,
    status: pointer.status ?? "unknown",
    task_counts: taskCounts,
    credits_reserved: pointer.creditsReserved ?? 0,
    credits_consumed: pointer.creditsConsumed ?? 0,
    credits_refunded: pointer.creditsRefunded ?? 0,
    credits_released: pointer.creditsReleased ?? 0,
    hard_cap_credits: pointer.hardCapCredits ?? 0,
    overage_policy: (pointer.overagePolicy ??
      "stop_at_cap") as CollectionOveragePolicy,
    resume_token: pointer.processingResumeToken,
  };
}

function assertStartContract(input: {
  collectionId: string;
  preflightSha256: string;
  estimateSha256: string;
  hardCapCredits: string | number;
  overagePolicy: CollectionOveragePolicy;
  knowledgeBlueprintId: string;
  knowledgeBlueprintRegistrySha256: string;
  knowledgeBlueprintModuleSha256: string;
  outputModules: readonly string[];
}): void {
  const startInputSchema = z
    .object({
      collectionId: z.uuid(),
      preflightSha256: sha256Schema,
      estimateSha256: sha256Schema,
      hardCapCredits: decimalSchema,
      overagePolicy: overagePolicySchema,
      knowledgeBlueprintId: z.string().min(1),
      knowledgeBlueprintRegistrySha256: prefixedSha256Schema,
      knowledgeBlueprintModuleSha256: prefixedSha256Schema,
      outputModules: z
        .array(
          z.enum([
            "source_index",
            "document_catalog",
            "knowledge_notes",
            "entities",
            "relations",
            "integrity",
            "export_manifest",
          ]),
        )
        .min(1),
    })
    .strict();
  const parsed = startInputSchema.safeParse({
    ...input,
    outputModules: [...input.outputModules],
  });
  if (!parsed.success) {
    throw new CollectionEventContractError(
      "The approved processing request is incomplete or contains invalid evidence hashes.",
    );
  }
}

export async function getCollectionEvents(
  collectionId: string,
  afterSequence = 0,
  signal?: AbortSignal,
): Promise<CollectionEventsResponse> {
  const raw = await apiRequest<unknown>(
    `/v1/collections/${collectionId}/events?after_sequence=${afterSequence}&limit=500`,
    { signal },
  );
  const parsed = collectionEventsSchema.safeParse(raw);
  if (!parsed.success) {
    throw new CollectionEventContractError(
      "The collection event snapshot does not match schema version 1.0.",
    );
  }
  return parsed.data as CollectionEventsResponse;
}

export async function getCollectionIntegrity(
  collectionId: string,
  signal?: AbortSignal,
): Promise<CollectionIntegritySummary> {
  const raw = await apiRequest<unknown>(
    `/v1/collections/${collectionId}/integrity`,
    { signal },
  );
  const parsed = collectionIntegritySchema.safeParse(raw);
  if (!parsed.success) {
    throw new CollectionEventContractError(
      "The collection integrity response does not match its strict evidence contract.",
    );
  }
  if (parsed.data.collection_id !== collectionId) {
    throw new CollectionEventContractError(
      "The integrity response belongs to another collection.",
    );
  }
  return parsed.data;
}

export async function getCollectionScene(
  collectionId: string,
  signal?: AbortSignal,
): Promise<CollectionScene> {
  const raw = await apiRequest<unknown>(
    `/v1/collections/${collectionId}/scene`,
    {
      signal,
    },
  );
  const parsed = collectionSceneSchema.safeParse(raw);
  if (!parsed.success || parsed.data.collection_id !== collectionId) {
    throw new CollectionEventContractError(
      "The collection scene does not match its deterministic identifier-only contract.",
    );
  }
  return parsed.data;
}

export function getDocumentVersionPagePreviewUrl(
  documentVersionId: string,
  pageNumber: number,
): string {
  if (
    !z.uuid().safeParse(documentVersionId).success ||
    !Number.isSafeInteger(pageNumber) ||
    pageNumber < 1
  ) {
    throw new CollectionEventContractError(
      "A valid document version and page number are required.",
    );
  }
  return apiAbsoluteUrl(
    `/v1/document-versions/${documentVersionId}/pages/${pageNumber}/preview`,
  );
}

export function getProofCropUrl(proofId: string): string {
  if (!z.uuid().safeParse(proofId).success) {
    throw new CollectionEventContractError(
      "A valid proof identifier is required.",
    );
  }
  return apiAbsoluteUrl(`/v1/proofs/${proofId}/crop`);
}

export async function streamCollectionEvents(
  input: {
    collectionId: string;
    afterSequence?: number;
    signal: AbortSignal;
  },
  handlers: {
    onEvent: (event: CollectionEvent) => void;
    onSnapshot?: (snapshot: CollectionEventSnapshot) => void;
    onConnection: (state: "live" | "reconnecting") => void;
  },
): Promise<void> {
  if (
    input.afterSequence !== undefined &&
    (!Number.isSafeInteger(input.afterSequence) || input.afterSequence < 0)
  ) {
    throw new CollectionEventContractError(
      "The collection SSE replay cursor must be a non-negative integer sequence.",
    );
  }
  let retryAttempt = 0;
  await fetchEventSource(
    apiAbsoluteUrl(`/v1/collections/${input.collectionId}/events/stream`),
    {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "text/event-stream",
        ...(input.afterSequence
          ? { "Last-Event-ID": String(input.afterSequence) }
          : {}),
      },
      signal: input.signal,
      openWhenHidden: false,
      onopen(response) {
        if (response.status === 404 || response.status === 406) {
          throw new CollectionSseUnavailableError();
        }
        if (!response.ok) {
          throw new ApiError(
            "The collection event stream could not be opened.",
            response.status,
            "COLLECTION_SSE_OPEN",
            response.status === 408 ||
              response.status === 429 ||
              response.status >= 500,
          );
        }
        handlers.onConnection("live");
        retryAttempt = 0;
        return Promise.resolve();
      },
      onmessage(message) {
        if (!message.data) return;
        try {
          const raw = JSON.parse(message.data) as unknown;
          if (message.event === "collection.snapshot.v1") {
            const snapshot = collectionSnapshotSchema.safeParse(raw);
            if (snapshot.success) {
              handlers.onSnapshot?.(snapshot.data as CollectionEventSnapshot);
            }
            return;
          }
          const event = collectionEventSchema.safeParse(raw);
          if (event.success) handlers.onEvent(event.data as CollectionEvent);
        } catch {
          // The durable cursor endpoint will recover malformed or missing SSE frames.
        }
      },
      onerror(error) {
        if (error instanceof CollectionSseUnavailableError) throw error;
        if (error instanceof ApiError && !error.retryable) throw error;
        handlers.onConnection("reconnecting");
        retryAttempt += 1;
        return Math.min(30_000, 1_000 * 2 ** Math.min(5, retryAttempt));
      },
    },
  );
}
