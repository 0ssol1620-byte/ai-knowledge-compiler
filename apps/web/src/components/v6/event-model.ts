export const V6_EVENT_SCHEMA_VERSION = "1.0" as const;

export const V6_PARALLEL_EVENT_TYPES = [
  "shard.planned.v1",
  "shard.dispatched.v1",
  "attempt.started.v1",
  "attempt.output.received.v1",
  "attempt.validation.failed.v1",
  "attempt.accepted.v1",
  "attempt.rejected.v1",
  "attempt.hedged.v1",
  "worker.semantic.degraded.v1",
  "worker.draining.v1",
  "worker.quarantined.v1",
  "recovery.region.requested.v1",
  "recovery.completed.v1",
  "continuity.merge.started.v1",
  "continuity.merge.completed.v1",
  "document.finalized.v1",
] as const;

export type V6ParallelEventType = (typeof V6_PARALLEL_EVENT_TYPES)[number];

/**
 * The product surface intentionally accepts the common versioned-event shape
 * rather than a transport-specific SSE wrapper. Callers must pass events only
 * after transport parsing. This module still validates the display contract and
 * fails closed on unsupported schema versions or conflicting sequences.
 */
export type V6VersionedEvent = {
  readonly schema_version: string;
  readonly event_id: string;
  readonly event_type: string;
  readonly sequence: number;
  readonly occurred_at: string;
  readonly project_id?: string;
  readonly job_id: string;
  readonly tenant_id?: string;
  readonly document_id?: string;
  readonly document_version_id?: string;
  readonly page_id?: string;
  readonly payload: Readonly<Record<string, unknown>>;
};

export type PagePresentationState =
  | "planned"
  | "dispatched"
  | "processing"
  | "validating"
  | "recovering"
  | "recovered_pending_validation"
  | "verified"
  | "authority_verified"
  | "cross_model_verified"
  | "auto_repaired"
  | "completed_unverified"
  | "validation_failed"
  | "unresolved"
  | "quarantined"
  | "failed";

export type PagePresentation = {
  readonly pageId: string;
  readonly pageNumber1?: number;
  readonly documentId?: string;
  readonly state: PagePresentationState;
  readonly lastEventType: string;
  readonly lastSequence: number;
  readonly lastOccurredAt: string;
  readonly eventCount: number;
  readonly route?: string;
  readonly regionId?: string;
  readonly attemptIds: readonly string[];
};

export type AttemptPresentation = {
  readonly attemptId: string;
  readonly attemptNumber?: number;
  readonly rootAttemptId?: string;
  readonly parentAttemptId?: string;
  readonly shardId?: string;
  readonly pageIds: readonly string[];
  readonly poolId?: string;
  readonly workerId?: string;
  readonly modelRevision?: string;
  readonly route?: string;
  readonly status: string;
  readonly validatorStatus?: string;
  readonly gpuSeconds?: number;
  readonly providerCostUsd?: number;
  readonly userCredits?: number;
  readonly costSource?: string;
  readonly billable?: boolean;
  readonly lastSequence: number;
  readonly lastOccurredAt: string;
};

export type WorkerPoolPresentation = {
  readonly poolId: string;
  readonly status: "healthy" | "degraded" | "draining" | "quarantined";
  readonly workerIds: readonly string[];
  readonly attemptIds: readonly string[];
  readonly lastSequence: number;
};

export type CreditImpact = {
  readonly kind:
    "measured" | "not_billable" | "no_duplicate_charge_policy" | "not_reported";
  readonly value?: string;
  readonly source?: string;
};

export type IntegrityLedgerEntry = {
  readonly eventId: string;
  readonly eventType: string;
  readonly sequence: number;
  readonly occurredAt: string;
  readonly kind:
    | "automatic_recovery"
    | "verification_failure"
    | "unresolved"
    | "quarantined"
    | "worker_health";
  readonly status: "active" | "resolved" | "isolated";
  readonly pageId?: string;
  readonly regionId?: string;
  readonly reason?: string;
  readonly evidenceRef: string;
  readonly creditImpact: CreditImpact;
};

export type ProductCostSummary = {
  readonly measuredAttemptCount: number;
  readonly gpuSeconds: number | null;
  readonly providerCostUsd: number | null;
  readonly attemptUserCredits: number | null;
  readonly consumedCredits: number | null;
  readonly releasedCredits: number | null;
};

export type V6ProductView = {
  readonly events: readonly V6VersionedEvent[];
  readonly pages: readonly PagePresentation[];
  readonly attempts: readonly AttemptPresentation[];
  readonly workerPools: readonly WorkerPoolPresentation[];
  readonly integrityEntries: readonly IntegrityLedgerEntry[];
  readonly cost: ProductCostSummary;
  readonly ignoredEventCount: number;
  readonly conflictingSequenceCount: number;
  readonly gapCount: number;
};

type MutablePage = {
  pageId: string;
  pageNumber1?: number;
  documentId?: string;
  state: PagePresentationState;
  lastEventType: string;
  lastSequence: number;
  lastOccurredAt: string;
  eventCount: number;
  route?: string;
  regionId?: string;
  attemptIds: Set<string>;
};

type MutableAttempt = {
  attemptId: string;
  attemptNumber?: number;
  rootAttemptId?: string;
  parentAttemptId?: string;
  shardId?: string;
  pageIds: Set<string>;
  poolId?: string;
  workerId?: string;
  modelRevision?: string;
  route?: string;
  status: string;
  validatorStatus?: string;
  gpuSeconds?: number;
  providerCostUsd?: number;
  userCredits?: number;
  costSource?: string;
  billable?: boolean;
  lastSequence: number;
  lastOccurredAt: string;
};

type MutableWorkerPool = {
  poolId: string;
  status: WorkerPoolPresentation["status"];
  workerIds: Set<string>;
  attemptIds: Set<string>;
  lastSequence: number;
};

const finalVerificationStates = new Set<PagePresentationState>([
  "verified",
  "authority_verified",
  "cross_model_verified",
  "auto_repaired",
  "unresolved",
  "quarantined",
  "failed",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(
  payload: Readonly<Record<string, unknown>>,
  ...keys: readonly string[]
): string | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim().length > 0) return value;
  }
  return undefined;
}

function booleanValue(
  payload: Readonly<Record<string, unknown>>,
  ...keys: readonly string[]
): boolean | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "boolean") return value;
  }
  return undefined;
}

function finiteNumber(value: unknown): number | undefined {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function signedNumberValue(value: unknown): number | undefined {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function numberValue(
  payload: Readonly<Record<string, unknown>>,
  ...keys: readonly string[]
): number | undefined {
  for (const key of keys) {
    const parsed = finiteNumber(payload[key]);
    if (parsed !== undefined) return parsed;
  }
  return undefined;
}

function nestedCostValue(
  payload: Readonly<Record<string, unknown>>,
  ...keys: readonly string[]
): number | undefined {
  const direct = numberValue(payload, ...keys);
  if (direct !== undefined) return direct;
  const cost = payload.cost;
  if (!isRecord(cost)) return undefined;
  return numberValue(cost, ...keys);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is string => typeof item === "string" && item.length > 0,
  );
}

function eventPageIds(event: V6VersionedEvent): string[] {
  const ids = new Set<string>();
  if (event.page_id) ids.add(event.page_id);
  const payloadId = stringValue(event.payload, "page_id");
  if (payloadId) ids.add(payloadId);
  for (const id of stringList(event.payload.page_ids)) ids.add(id);
  return [...ids];
}

function pageNumber(event: V6VersionedEvent): number | undefined {
  const explicit = numberValue(event.payload, "page_number1");
  if (explicit !== undefined && Number.isInteger(explicit) && explicit >= 1) {
    return explicit;
  }
  const index = numberValue(event.payload, "page_index0");
  return index !== undefined && Number.isInteger(index) ? index + 1 : undefined;
}

function verificationState(value: unknown): PagePresentationState | undefined {
  if (typeof value !== "string") return undefined;
  return finalVerificationStates.has(value as PagePresentationState)
    ? (value as PagePresentationState)
    : undefined;
}

function stateForEvent(
  event: V6VersionedEvent,
): PagePresentationState | undefined {
  const explicit =
    verificationState(event.payload.verification_state) ??
    verificationState(event.payload.final_state);
  if (explicit) return explicit;
  switch (event.event_type) {
    case "shard.planned.v1":
    case "page.preflight.completed.v1":
      return "planned";
    case "shard.dispatched.v1":
    case "page.route.selected.v1":
      return "dispatched";
    case "attempt.started.v1":
    case "page.processing.started.v1":
    case "page.layout.detected.v1":
    case "page.block.completed.v1":
      return "processing";
    case "attempt.output.received.v1":
      return "validating";
    case "recovery.region.requested.v1":
    case "page.retry.scheduled.v1":
      return "recovering";
    case "recovery.completed.v1":
      return "recovered_pending_validation";
    case "attempt.accepted.v1":
      return "verified";
    case "page.completed.v1":
      return "completed_unverified";
    case "attempt.validation.failed.v1":
    case "attempt.rejected.v1":
      return "validation_failed";
    case "page.unresolved.v1":
      return "unresolved";
    case "page.quarantined.v1":
      return "quarantined";
    case "page.failed.v1":
      return "failed";
    default:
      return undefined;
  }
}

function attemptStatus(eventType: string): string | undefined {
  switch (eventType) {
    case "attempt.started.v1":
      return "running";
    case "attempt.output.received.v1":
      return "validating";
    case "attempt.validation.failed.v1":
      return "validation_failed";
    case "attempt.accepted.v1":
      return "accepted";
    case "attempt.rejected.v1":
      return "rejected";
    case "attempt.hedged.v1":
      return "hedged";
    default:
      return undefined;
  }
}

function poolStatus(
  eventType: string,
): WorkerPoolPresentation["status"] | undefined {
  switch (eventType) {
    case "worker.semantic.degraded.v1":
      return "degraded";
    case "worker.draining.v1":
      return "draining";
    case "worker.quarantined.v1":
      return "quarantined";
    default:
      return undefined;
  }
}

function eventIsDisplayContractValid(event: V6VersionedEvent): boolean {
  return (
    event.schema_version === V6_EVENT_SCHEMA_VERSION &&
    typeof event.event_id === "string" &&
    event.event_id.length >= 3 &&
    typeof event.event_type === "string" &&
    /^[a-z0-9]+(?:[._][a-z0-9]+)*\.v1$/.test(event.event_type) &&
    Number.isInteger(event.sequence) &&
    event.sequence >= 1 &&
    typeof event.occurred_at === "string" &&
    !Number.isNaN(Date.parse(event.occurred_at)) &&
    typeof event.job_id === "string" &&
    event.job_id.length >= 3 &&
    isRecord(event.payload)
  );
}

function normalizeEvents(
  input: readonly V6VersionedEvent[],
  baselineSequence?: number,
): {
  events: V6VersionedEvent[];
  ignoredEventCount: number;
  conflictingSequenceCount: number;
  gapCount: number;
} {
  const byId = new Map<string, V6VersionedEvent>();
  let ignoredEventCount = 0;
  for (const event of input) {
    if (!eventIsDisplayContractValid(event)) {
      ignoredEventCount += 1;
      continue;
    }
    if (!byId.has(event.event_id)) byId.set(event.event_id, event);
  }
  const ordered = [...byId.values()].sort(
    (left, right) => left.sequence - right.sequence,
  );
  const events: V6VersionedEvent[] = [];
  const seenSequences = new Set<number>();
  let conflictingSequenceCount = 0;
  for (const event of ordered) {
    if (seenSequences.has(event.sequence)) {
      conflictingSequenceCount += 1;
      continue;
    }
    seenSequences.add(event.sequence);
    events.push(event);
  }
  let gapCount = 0;
  let previous = baselineSequence;
  for (const event of events) {
    if (previous !== undefined && event.sequence > previous + 1) {
      gapCount += event.sequence - previous - 1;
    }
    previous = event.sequence;
  }
  return {
    events,
    ignoredEventCount,
    conflictingSequenceCount,
    gapCount,
  };
}

function reasonForEvent(event: V6VersionedEvent): string | undefined {
  const direct = stringValue(
    event.payload,
    "reason",
    "reason_code",
    "error_code",
    "failure_code",
    "validator_status",
  );
  if (direct) return direct;
  const codes = stringList(event.payload.reason_codes);
  if (codes.length > 0) return codes.join(", ");
  const validation = event.payload.validation;
  if (isRecord(validation)) {
    return stringValue(validation, "reason", "reason_code", "status");
  }
  return undefined;
}

export function creditImpactForEvent(event: V6VersionedEvent): CreditImpact {
  const explicitText = stringValue(event.payload, "credit_impact", "billing");
  if (explicitText) {
    if (
      /^(?:not[_ -]?billable|not[_ -]?charged|no[_ -]?charge)$/i.test(
        explicitText,
      )
    ) {
      return { kind: "not_billable", source: "event_payload" };
    }
    return { kind: "measured", value: explicitText, source: "event_payload" };
  }
  const explicitAmount =
    signedNumberValue(event.payload.credit_impact_credits) ??
    signedNumberValue(event.payload.user_credit_delta);
  if (explicitAmount !== undefined) {
    return {
      kind: "measured",
      value: String(explicitAmount),
      source: "event_payload",
    };
  }
  if (booleanValue(event.payload, "billable") === false) {
    return { kind: "not_billable", source: "event_payload" };
  }
  if (
    [
      "page.unresolved.v1",
      "page.quarantined.v1",
      "output.quarantined.v1",
      "worker.quarantined.v1",
    ].includes(event.event_type)
  ) {
    return { kind: "not_billable", source: "v6_fail_closed_policy" };
  }
  if (
    [
      "recovery.region.requested.v1",
      "recovery.completed.v1",
      "attempt.hedged.v1",
      "attempt.rejected.v1",
      "attempt.validation.failed.v1",
    ].includes(event.event_type)
  ) {
    return {
      kind: "no_duplicate_charge_policy",
      source: "v6_retry_and_replica_policy",
    };
  }
  return { kind: "not_reported" };
}

function integrityEntry(
  event: V6VersionedEvent,
): IntegrityLedgerEntry | undefined {
  let kind: IntegrityLedgerEntry["kind"] | undefined;
  let status: IntegrityLedgerEntry["status"] = "active";
  switch (event.event_type) {
    case "recovery.region.requested.v1":
      kind = "automatic_recovery";
      break;
    case "recovery.completed.v1":
      kind = "automatic_recovery";
      status = "resolved";
      break;
    case "attempt.validation.failed.v1":
    case "attempt.rejected.v1":
    case "verification.failed.v1":
      kind = "verification_failure";
      break;
    case "page.unresolved.v1":
      kind = "unresolved";
      status = "isolated";
      break;
    case "page.quarantined.v1":
    case "output.quarantined.v1":
      kind = "quarantined";
      status = "isolated";
      break;
    case "worker.semantic.degraded.v1":
    case "worker.draining.v1":
    case "worker.quarantined.v1":
      kind = "worker_health";
      status =
        event.event_type === "worker.quarantined.v1" ? "isolated" : "active";
      break;
    default:
      return undefined;
  }
  const pageId = eventPageIds(event)[0];
  const regionId = stringValue(event.payload, "region_id");
  return {
    eventId: event.event_id,
    eventType: event.event_type,
    sequence: event.sequence,
    occurredAt: event.occurred_at,
    kind,
    status,
    ...(pageId ? { pageId } : {}),
    ...(regionId ? { regionId } : {}),
    ...(reasonForEvent(event) ? { reason: reasonForEvent(event) } : {}),
    evidenceRef: `event:${event.event_id}#${event.sequence}`,
    creditImpact: creditImpactForEvent(event),
  };
}

function sumOrNull(values: readonly (number | undefined)[]): number | null {
  const measured = values.filter(
    (value): value is number => value !== undefined,
  );
  return measured.length > 0
    ? measured.reduce((total, value) => total + value, 0)
    : null;
}

export function deriveV6ProductView(
  input: readonly V6VersionedEvent[],
  baselineSequence?: number,
): V6ProductView {
  const normalized = normalizeEvents(input, baselineSequence);
  const pages = new Map<string, MutablePage>();
  const attempts = new Map<string, MutableAttempt>();
  const pools = new Map<string, MutableWorkerPool>();
  const shardPageIds = new Map<string, string[]>();
  const pageNumbers = new Map<string, number>();
  const integrityEntries: IntegrityLedgerEntry[] = [];
  const consumedCredits: number[] = [];
  const releasedCredits: number[] = [];

  for (const event of normalized.events) {
    const shardId = stringValue(event.payload, "shard_id");
    let ids = eventPageIds(event);
    const explicitPageNumber = pageNumber(event);
    if (explicitPageNumber !== undefined) {
      for (const pageId of ids) pageNumbers.set(pageId, explicitPageNumber);
    }
    const rangeStart = numberValue(event.payload, "page_start");
    const rangeEnd = numberValue(event.payload, "page_end");
    if (
      ids.length === 0 &&
      rangeStart !== undefined &&
      rangeEnd !== undefined &&
      Number.isInteger(rangeStart) &&
      Number.isInteger(rangeEnd) &&
      rangeStart >= 1 &&
      rangeEnd >= rangeStart &&
      rangeEnd - rangeStart <= 10_000
    ) {
      const documentId =
        event.document_id ??
        stringValue(event.payload, "document_id") ??
        "unscoped-document";
      ids = Array.from({ length: rangeEnd - rangeStart + 1 }, (_, index) => {
        const number = rangeStart + index;
        const pageId = `${documentId}#page-${number}`;
        pageNumbers.set(pageId, number);
        return pageId;
      });
    }
    if (shardId && ids.length > 0) shardPageIds.set(shardId, ids);
    if (ids.length === 0 && shardId) ids = shardPageIds.get(shardId) ?? [];
    const nextState = stateForEvent(event);
    const attemptId = stringValue(event.payload, "attempt_id");
    const route = stringValue(
      event.payload,
      "route",
      "parser_recipe",
      "route_profile",
      "route_class",
    );
    const regionId = stringValue(event.payload, "region_id");
    if (nextState) {
      for (const pageId of ids) {
        const current = pages.get(pageId);
        const next: MutablePage = current ?? {
          pageId,
          state: nextState,
          lastEventType: event.event_type,
          lastSequence: event.sequence,
          lastOccurredAt: event.occurred_at,
          eventCount: 0,
          attemptIds: new Set<string>(),
        };
        next.state = nextState;
        next.lastEventType = event.event_type;
        next.lastSequence = event.sequence;
        next.lastOccurredAt = event.occurred_at;
        next.eventCount += 1;
        next.pageNumber1 = pageNumbers.get(pageId) ?? next.pageNumber1;
        next.documentId = event.document_id ?? next.documentId;
        next.route = route ?? next.route;
        next.regionId = regionId ?? next.regionId;
        if (attemptId) next.attemptIds.add(attemptId);
        pages.set(pageId, next);
      }
    }

    const mappedAttemptStatus = attemptStatus(event.event_type);
    if (attemptId && mappedAttemptStatus) {
      const current = attempts.get(attemptId);
      const next: MutableAttempt = current ?? {
        attemptId,
        pageIds: new Set<string>(),
        status: mappedAttemptStatus,
        lastSequence: event.sequence,
        lastOccurredAt: event.occurred_at,
      };
      next.rootAttemptId =
        stringValue(event.payload, "root_attempt_id") ?? next.rootAttemptId;
      const reportedAttemptNumber = numberValue(
        event.payload,
        "attempt_number",
      );
      if (
        reportedAttemptNumber !== undefined &&
        Number.isInteger(reportedAttemptNumber) &&
        reportedAttemptNumber >= 1
      ) {
        next.attemptNumber = reportedAttemptNumber;
      }
      next.parentAttemptId =
        stringValue(event.payload, "parent_attempt_id") ?? next.parentAttemptId;
      next.shardId = shardId ?? next.shardId;
      next.poolId =
        stringValue(
          event.payload,
          "worker_pool_id",
          "pool_id",
          "model_pool_id",
          "pool_key",
        ) ?? next.poolId;
      next.workerId = stringValue(event.payload, "worker_id") ?? next.workerId;
      next.modelRevision =
        stringValue(event.payload, "model_revision", "registry_model_id") ??
        next.modelRevision;
      next.route = route ?? next.route;
      next.status = mappedAttemptStatus;
      next.validatorStatus =
        stringValue(event.payload, "validator_status", "validation_status") ??
        next.validatorStatus;
      const gpuMilliseconds = nestedCostValue(
        event.payload,
        "gpu_milliseconds",
      );
      next.gpuSeconds =
        nestedCostValue(event.payload, "gpu_seconds") ??
        (gpuMilliseconds === undefined
          ? next.gpuSeconds
          : gpuMilliseconds / 1_000);
      next.providerCostUsd =
        nestedCostValue(
          event.payload,
          "provider_cost_usd",
          "actual_cost_usd",
          "cost_usd",
        ) ?? next.providerCostUsd;
      next.userCredits =
        nestedCostValue(event.payload, "user_credits", "credits") ??
        next.userCredits;
      next.costSource =
        stringValue(event.payload, "cost_source", "metering_source") ??
        next.costSource;
      next.billable = booleanValue(event.payload, "billable") ?? next.billable;
      next.lastSequence = event.sequence;
      next.lastOccurredAt = event.occurred_at;
      for (const pageId of ids) next.pageIds.add(pageId);
      attempts.set(attemptId, next);
    }

    const poolId = stringValue(
      event.payload,
      "worker_pool_id",
      "pool_id",
      "model_pool_id",
      "pool_key",
    );
    const workerId = stringValue(event.payload, "worker_id");
    const mappedPoolStatus = poolStatus(event.event_type);
    if (poolId) {
      const current = pools.get(poolId);
      const next: MutableWorkerPool = current ?? {
        poolId,
        status: "healthy",
        workerIds: new Set<string>(),
        attemptIds: new Set<string>(),
        lastSequence: event.sequence,
      };
      if (mappedPoolStatus) next.status = mappedPoolStatus;
      if (workerId) next.workerIds.add(workerId);
      if (attemptId) next.attemptIds.add(attemptId);
      next.lastSequence = event.sequence;
      pools.set(poolId, next);
    }

    const integrity = integrityEntry(event);
    if (integrity) integrityEntries.push(integrity);

    if (
      ["credit.consumed.v1", "credits.consumed.v1"].includes(event.event_type)
    ) {
      const credits = numberValue(event.payload, "credits");
      if (credits !== undefined) consumedCredits.push(credits);
    }
    if (
      [
        "credit.released.v1",
        "credits.released.v1",
        "credit.refunded.v1",
        "credits.refunded.v1",
      ].includes(event.event_type)
    ) {
      const credits = numberValue(event.payload, "credits");
      if (credits !== undefined) releasedCredits.push(credits);
    }
  }

  const pageList: PagePresentation[] = [...pages.values()]
    .map((page) => ({
      ...page,
      attemptIds: [...page.attemptIds],
    }))
    .sort((left, right) => {
      if (left.pageNumber1 !== undefined && right.pageNumber1 !== undefined) {
        return left.pageNumber1 - right.pageNumber1;
      }
      if (left.pageNumber1 !== undefined) return -1;
      if (right.pageNumber1 !== undefined) return 1;
      return left.pageId.localeCompare(right.pageId);
    });
  const attemptList: AttemptPresentation[] = [...attempts.values()]
    .map((attempt) => ({
      ...attempt,
      pageIds: [...attempt.pageIds],
    }))
    .sort((left, right) => right.lastSequence - left.lastSequence);
  const poolList: WorkerPoolPresentation[] = [...pools.values()]
    .map((pool) => ({
      ...pool,
      workerIds: [...pool.workerIds],
      attemptIds: [...pool.attemptIds],
    }))
    .sort((left, right) => left.poolId.localeCompare(right.poolId));

  return {
    events: normalized.events,
    pages: pageList,
    attempts: attemptList,
    workerPools: poolList,
    integrityEntries: integrityEntries.sort(
      (left, right) => right.sequence - left.sequence,
    ),
    cost: {
      measuredAttemptCount: attemptList.filter(
        (attempt) =>
          attempt.gpuSeconds !== undefined ||
          attempt.providerCostUsd !== undefined ||
          attempt.userCredits !== undefined,
      ).length,
      gpuSeconds: sumOrNull(attemptList.map((attempt) => attempt.gpuSeconds)),
      providerCostUsd: sumOrNull(
        attemptList.map((attempt) => attempt.providerCostUsd),
      ),
      attemptUserCredits: sumOrNull(
        attemptList.map((attempt) => attempt.userCredits),
      ),
      consumedCredits: sumOrNull(consumedCredits),
      releasedCredits: sumOrNull(releasedCredits),
    },
    ignoredEventCount: normalized.ignoredEventCount,
    conflictingSequenceCount: normalized.conflictingSequenceCount,
    gapCount: normalized.gapCount,
  };
}

export function eventCountForTypes(
  events: readonly V6VersionedEvent[],
  types: readonly string[],
): number {
  const accepted = new Set(types);
  return events.filter((event) => accepted.has(event.event_type)).length;
}
