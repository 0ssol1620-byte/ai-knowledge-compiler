import { z } from "zod";

import { ApiError, apiRequest } from "@/lib/api-client";

export const INTEGRITY_DECISION_ACTIONS = [
  "keep_quarantined",
  "exclude",
  "retry_new_engine",
  "provide_password",
  "correct_source",
  "override",
] as const;

export type CollectionIntegrityDecisionAction =
  (typeof INTEGRITY_DECISION_ACTIONS)[number];
export type CollectionIntegrityTargetType =
  | "quarantine_item"
  | "review_item";

export const INTEGRITY_REASON_BY_ACTION = {
  keep_quarantined: "ACCEPTED_QUARANTINE",
  exclude: "EXCLUDED_FROM_OUTPUT",
  retry_new_engine: "RETRY_WITH_APPROVED_ENGINE",
  provide_password: "ENCRYPTED_PDF_SECRET_SUBMITTED",
  correct_source: "CORRECTED_SOURCE_SUBMITTED",
  override: "CUSTOMER_OVERRIDE_APPROVED",
} as const satisfies Record<CollectionIntegrityDecisionAction, string>;

const targetTypeSchema = z.enum(["quarantine_item", "review_item"]);
const decisionActionSchema = z.enum(INTEGRITY_DECISION_ACTIONS);
const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const boundedCodeSchema = z
  .string()
  .min(1)
  .max(160)
  .regex(/^[A-Za-z0-9_.:@/+\-]+$/);

const evidenceReferenceSchema = z
  .object({
    kind: z.enum([
      "artifact_sha256",
      "analysis_task",
      "source_file",
      "engine_revision",
      "support_case",
    ]),
    reference_id: z.uuid().optional(),
    sha256: sha256Schema.optional(),
    revision: boundedCodeSchema.optional(),
  })
  .strict()
  .superRefine((reference, context) => {
    const valid =
      (reference.kind === "artifact_sha256" &&
        reference.sha256 !== undefined &&
        reference.reference_id === undefined &&
        reference.revision === undefined) ||
      ((reference.kind === "analysis_task" ||
        reference.kind === "support_case") &&
        reference.reference_id !== undefined &&
        reference.sha256 === undefined &&
        reference.revision === undefined) ||
      (reference.kind === "source_file" &&
        reference.reference_id !== undefined &&
        reference.sha256 !== undefined &&
        reference.revision === undefined) ||
      (reference.kind === "engine_revision" &&
        reference.reference_id === undefined &&
        reference.sha256 !== undefined &&
        reference.revision !== undefined);
    if (!valid) {
      context.addIssue({
        code: "custom",
        message: "The structured evidence fields do not match their kind.",
      });
    }
  });

const integrityFindingSchema = z
  .object({
    target_type: targetTypeSchema,
    target_id: z.uuid(),
    status: boundedCodeSchema,
    category: boundedCodeSchema,
    severity: boundedCodeSchema,
    reason_code: boundedCodeSchema,
    allowed_actions: z.array(decisionActionSchema).max(INTEGRITY_DECISION_ACTIONS.length),
    created_at: z.iso.datetime({ offset: true }),
  })
  .strict()
  .superRefine((finding, context) => {
    if (new Set(finding.allowed_actions).size !== finding.allowed_actions.length) {
      context.addIssue({
        code: "custom",
        path: ["allowed_actions"],
        message: "Allowed actions must be unique.",
      });
    }
  });

const integrityDecisionSchema = z
  .object({
    id: z.uuid(),
    collection_id: z.uuid(),
    target_type: targetTypeSchema,
    target_id: z.uuid(),
    action: decisionActionSchema,
    reason_code: z.enum(Object.values(INTEGRITY_REASON_BY_ACTION)),
    evidence_reference: evidenceReferenceSchema.nullable(),
    previous_status: boundedCodeSchema,
    resulting_status: boundedCodeSchema,
    override_applied: z.boolean(),
    actor_id: z.uuid(),
    created_at: z.iso.datetime({ offset: true }),
  })
  .strict();

const integrityFindingsResponseSchema = z
  .object({
    collection_id: z.uuid(),
    items: z.array(integrityFindingSchema),
    next_cursor: z.string().min(1).max(512).nullable(),
  })
  .strict();

const integrityDecisionsResponseSchema = z
  .object({
    collection_id: z.uuid(),
    items: z.array(integrityDecisionSchema),
    next_cursor: z.uuid().nullable(),
  })
  .strict();

const decisionCreateSchema = z
  .object({
    target_type: targetTypeSchema,
    target_id: z.uuid(),
    action: decisionActionSchema,
    reason_code: z.enum(Object.values(INTEGRITY_REASON_BY_ACTION)),
    evidence_reference: evidenceReferenceSchema.nullable().optional(),
    acknowledge_override: z.boolean(),
  })
  .strict()
  .superRefine((decision, context) => {
    if (decision.reason_code !== INTEGRITY_REASON_BY_ACTION[decision.action]) {
      context.addIssue({
        code: "custom",
        path: ["reason_code"],
        message: "Reason code does not match the selected action.",
      });
    }
    const requiredEvidenceActions = new Set<CollectionIntegrityDecisionAction>([
      "retry_new_engine",
      "provide_password",
      "correct_source",
      "override",
    ]);
    if (requiredEvidenceActions.has(decision.action) && !decision.evidence_reference) {
      context.addIssue({
        code: "custom",
        path: ["evidence_reference"],
        message: "This action requires a structured evidence reference.",
      });
    }
    const allowedKinds: Record<CollectionIntegrityDecisionAction, readonly string[]> = {
      keep_quarantined: ["artifact_sha256", "support_case"],
      exclude: ["artifact_sha256", "support_case"],
      retry_new_engine: ["engine_revision"],
      provide_password: ["analysis_task"],
      correct_source: ["source_file"],
      override: ["artifact_sha256", "support_case"],
    };
    if (
      decision.evidence_reference &&
      !allowedKinds[decision.action].includes(decision.evidence_reference.kind)
    ) {
      context.addIssue({
        code: "custom",
        path: ["evidence_reference", "kind"],
        message: "Evidence kind is not allowed for the selected action.",
      });
    }
    if (decision.acknowledge_override !== (decision.action === "override")) {
      context.addIssue({
        code: "custom",
        path: ["acknowledge_override"],
        message: "Only an override can carry explicit override acknowledgement.",
      });
    }
  });

export type CollectionIntegrityFinding = z.infer<typeof integrityFindingSchema>;
export type CollectionIntegrityDecision = z.infer<typeof integrityDecisionSchema>;
export type CollectionIntegrityEvidenceReference = z.infer<
  typeof evidenceReferenceSchema
>;
export type CollectionIntegrityDecisionCreate = z.input<
  typeof decisionCreateSchema
>;
export type CollectionIntegrityFindingsResponse = z.infer<
  typeof integrityFindingsResponseSchema
>;
export type CollectionIntegrityDecisionsResponse = z.infer<
  typeof integrityDecisionsResponseSchema
>;

export class CollectionIntegrityContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CollectionIntegrityContractError";
  }
}

export async function getCollectionIntegrityFindings(
  collectionId: string,
  signal?: AbortSignal,
): Promise<CollectionIntegrityFindingsResponse> {
  const raw = await apiRequest<unknown>(
    `/v1/collections/${collectionId}/integrity/findings?limit=200`,
    { signal },
  );
  const parsed = integrityFindingsResponseSchema.safeParse(raw);
  if (!parsed.success || parsed.data.collection_id !== collectionId) {
    throw new CollectionIntegrityContractError(
      "The integrity findings response failed its strict collection contract.",
    );
  }
  return parsed.data;
}

export async function getCollectionIntegrityDecisions(
  collectionId: string,
  signal?: AbortSignal,
): Promise<CollectionIntegrityDecisionsResponse> {
  const raw = await apiRequest<unknown>(
    `/v1/collections/${collectionId}/integrity/decisions?limit=200`,
    { signal },
  );
  const parsed = integrityDecisionsResponseSchema.safeParse(raw);
  if (
    !parsed.success ||
    parsed.data.collection_id !== collectionId ||
    parsed.data.items.some((item) => item.collection_id !== collectionId)
  ) {
    throw new CollectionIntegrityContractError(
      "The integrity decision history failed its strict collection contract.",
    );
  }
  return parsed.data;
}

export async function createCollectionIntegrityDecision(
  collectionId: string,
  input: CollectionIntegrityDecisionCreate,
): Promise<CollectionIntegrityDecision> {
  const parsedInput = decisionCreateSchema.safeParse(input);
  if (!parsedInput.success) {
    throw new CollectionIntegrityContractError(
      parsedInput.error.issues[0]?.message ??
        "The integrity decision does not satisfy the audited contract.",
    );
  }
  const pending = pendingDecision(collectionId, parsedInput.data);
  try {
    const raw = await apiRequest<unknown>(
      `/v1/collections/${collectionId}/integrity/decisions`,
      {
        method: "POST",
        idempotencyKey: pending.idempotencyKey,
        body: JSON.stringify(parsedInput.data),
      },
    );
    const parsed = integrityDecisionSchema.safeParse(raw);
    if (
      !parsed.success ||
      parsed.data.collection_id !== collectionId ||
      parsed.data.target_type !== parsedInput.data.target_type ||
      parsed.data.target_id !== parsedInput.data.target_id ||
      parsed.data.action !== parsedInput.data.action ||
      parsed.data.reason_code !== parsedInput.data.reason_code ||
      parsed.data.override_applied !== (parsedInput.data.action === "override") ||
      JSON.stringify(parsed.data.evidence_reference ?? null) !==
        JSON.stringify(parsedInput.data.evidence_reference ?? null)
    ) {
      throw new CollectionIntegrityContractError(
        "The integrity decision acknowledgement failed correlation checks.",
      );
    }
    clearPendingDecision(pending.storageKey);
    return parsed.data;
  } catch (error) {
    if (!isAmbiguousMutationFailure(error)) {
      clearPendingDecision(pending.storageKey);
    }
    throw error;
  }
}

type PendingDecisionRecord = {
  schemaVersion: 1;
  requestShape: string;
  idempotencyKey: string;
};

function pendingDecision(
  collectionId: string,
  input: z.output<typeof decisionCreateSchema>,
): PendingDecisionRecord & { storageKey: string } {
  const storageKey = `akc:integrity-decision:v1:${collectionId}:${input.target_type}:${input.target_id}`;
  const requestShape = JSON.stringify(input);
  const stored = readPendingDecision(storageKey);
  if (stored?.requestShape === requestShape) {
    return { ...stored, storageKey };
  }
  const record: PendingDecisionRecord = {
    schemaVersion: 1,
    requestShape,
    idempotencyKey: crypto.randomUUID(),
  };
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(record));
  } catch {
    // The server idempotency boundary still applies for this in-flight request.
  }
  return { ...record, storageKey };
}

function readPendingDecision(storageKey: string): PendingDecisionRecord | undefined {
  try {
    const value = JSON.parse(window.localStorage.getItem(storageKey) ?? "") as unknown;
    if (
      typeof value === "object" &&
      value !== null &&
      "schemaVersion" in value &&
      value.schemaVersion === 1 &&
      "requestShape" in value &&
      typeof value.requestShape === "string" &&
      "idempotencyKey" in value &&
      typeof value.idempotencyKey === "string" &&
      z.uuid().safeParse(value.idempotencyKey).success
    ) {
      return value as PendingDecisionRecord;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function clearPendingDecision(storageKey: string): void {
  try {
    window.localStorage.removeItem(storageKey);
  } catch {
    // Storage can be unavailable in locked-down browser contexts.
  }
}

function isAmbiguousMutationFailure(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return (
    error.retryable ||
    error.status === 408 ||
    error.status === 409 ||
    error.status === 425 ||
    error.status === 429 ||
    error.status >= 500
  );
}
