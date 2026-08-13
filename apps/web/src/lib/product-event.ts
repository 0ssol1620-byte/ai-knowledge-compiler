import { z } from "zod";

/**
 * `ProductEvent` — the one vocabulary the cinematic landing and the real
 * product both render.
 *
 * v5 PART 17.4 says the app projects durable backend events into the UI and
 * that sample mode and real mode are distinguished explicitly. That is the
 * whole design constraint here: there is no "demo component" and no "live
 * component". There is one projection (`world-projection.ts`) fed by one
 * interface (`ProductEventSource`), and the two implementations are a frozen
 * fixture and an SSE stream.
 *
 *     ProductEvent  →  DemoFixtureEventSource  →  projection  →  UI
 *     ProductEvent  →  LiveEventSource (SSE)   →  projection  →  UI
 *
 * ── Vocabulary provenance ────────────────────────────────────────────────
 *
 * Names are not invented where the backend already has one. Eight of the
 * types below are the exact strings `akc_cir.collection_events` already
 * emits; the rest are named in the same `<domain>.<action>.v1` style and are
 * listed in `PROPOSED_EVENT_TYPES` so the gap is legible rather than implied.
 * Nothing in this file changes a backend contract — this is the client half of
 * a proposal, and every proposed type is fixture-only today.
 *
 * **Sharing a name is not sharing a contract, and here it is neither.** All
 * eight reused types declare payloads that do not satisfy the backend's
 * required fields, so the second arrow above does not yet work against the
 * real collection stream: those frames fail validation and are dropped.
 * `product-event.contract.test.ts` measures and pins that divergence rather
 * than leaving it to be discovered by whoever first wires up the endpoint.
 *
 * The envelope mirrors `akc_cir.events.ProcessingEvent`: snake_case on the
 * wire (chapter 17 defines the SSE envelope in snake_case even though CIR
 * artifacts are camelCase), a positive monotonic `sequence`, and a
 * `schema_version` literal.
 */

export const PRODUCT_EVENT_SCHEMA_VERSION = "1.0";

/**
 * Types `akc_cir.collection_events.CollectionEventType` already defines.
 *
 * The *names* are reused. The *payloads* are not compatible: every one of the
 * eight declares a different shape from the one
 * `COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS` requires, so a real collection
 * frame fails `parseProductEvent` and is dropped. An earlier version of this
 * comment said rendering these "needs no backend work — only a projection";
 * that was measured and is false. `product-event.contract.test.ts` pins the
 * exact divergence, and closing it is an open product decision.
 */
export const REUSED_EVENT_TYPES = [
  "collection.discovery.progress.v1",
  "file.discovered.v1",
  "file.duplicate.detected.v1",
  "page.route.selected.v1",
  "verification.failed.v1",
  "recovery.completed.v1",
  "entity.resolved.v1",
  "relation.created.v1",
] as const;

/**
 * Types v5 PART 17.4 names that have no producer yet.
 *
 * PART 17.4's shorthand is expanded to the repository's versioned convention:
 * `document.profiled` → `document.profiled.v1`, `impact.detected` →
 * `impact.detected.v1`, and so on. `knowledge.created` is split into
 * `knowledge.unit.created.v1` because `entity.resolved.v1` and
 * `relation.created.v1` already carry the other two thirds of it.
 *
 * `source.admitted` is deliberately absent: `file.security.passed.v1` is the
 * existing event for the same moment, and adding a second name for it would
 * be the drift this list exists to prevent.
 */
export const PROPOSED_EVENT_TYPES = [
  "revision.family.detected.v1",
  "document.profiled.v1",
  "document.rerouted.v1",
  "knowledge.unit.created.v1",
  "conflict.detected.v1",
  "authority.resolved.v1",
  "source.revision.created.v1",
  "world_state.activated.v1",
  "impact.detected.v1",
  "recompile.progress.v1",
  "recompile.completed.v1",
  "answer.resolution.started.v1",
  "answer.source.resolved.v1",
  "answer.emitted.v1",
] as const;

export const PRODUCT_EVENT_TYPES = [
  ...REUSED_EVENT_TYPES,
  ...PROPOSED_EVENT_TYPES,
] as const;

export type ProductEventType = (typeof PRODUCT_EVENT_TYPES)[number];

/**
 * Which lane a page was routed through.
 *
 * `RECOVERY` is a display concept derived from `attempt >= 2`, exactly as
 * DESIGN_MASTER_V3 §11.3 specifies — the API's `route_label` has no such
 * value and does not need one.
 */
export const ROUTE_LANES = [
  "NATIVE",
  "FAST",
  "PRECISION",
  "RECOVERY",
] as const;
export type RouteLane = (typeof ROUTE_LANES)[number];

/**
 * How a knowledge unit stands in time and authority.
 *
 * `EXCEPTION` is not a third temporal state — it means an applicability scope
 * narrower than the active default won, which is the distinction WOW #2 is
 * about. Keeping it in one enum is what lets the UI encode all three without
 * a second field.
 */
export const TEMPORAL_STATUS = [
  "ACTIVE",
  "SUPERSEDED",
  "EXCEPTION",
] as const;
export type TemporalStatus = (typeof TEMPORAL_STATUS)[number];

/** Why one candidate beat the others. Never "it was the newest file". */
export const RESOLUTION_BASIS = [
  "current",
  "authority",
  "applicability",
] as const;
export type ResolutionBasis = (typeof RESOLUTION_BASIS)[number];

/**
 * A pointer back into the source, narrowed from `@akc/contracts`' `SourceRef`.
 *
 * The full contract carries `documentVersionId`, `bbox1000`, rotation and
 * media offsets. The landing needs the path a visitor can read out loud —
 * document, page, table, cell — so this is the readable subset and not a
 * competing definition. Anything rendering a bbox uses the real `SourceRef`.
 */
export const sourceRefLiteSchema = z.object({
  document_id: z.string().min(1),
  document_label: z.string().min(1),
  page_number: z.number().int().positive(),
  locator: z.string().min(1),
  cell: z.string().min(1).optional(),
});
export type SourceRefLite = z.infer<typeof sourceRefLiteSchema>;

const envelope = {
  schema_version: z.literal(PRODUCT_EVENT_SCHEMA_VERSION),
  event_id: z.string().min(1),
  sequence: z.number().int().positive(),
  occurred_at: z.string().min(1),
  collection_id: z.string().min(1),
  /**
   * PART 17.4: "Sample mode와 real mode를 명시적으로 구분한다."
   *
   * On the envelope rather than on the source object so that a projection,
   * a screenshot or a log line carries the distinction with it. A live
   * backend emits `"live"` and cannot emit `"demo"`.
   */
  mode: z.enum(["demo", "live"]),
  document_id: z.string().min(1).optional(),
  /** 1-based, matching `SourceRef.pageNumber1`. */
  page_number: z.number().int().positive().optional(),
};

function event<T extends ProductEventType, P extends z.ZodTypeAny>(
  type: T,
  payload: P,
) {
  return z.object({ ...envelope, event_type: z.literal(type), payload });
}

/* ── DISCOVER ───────────────────────────────────────────────────────────── */

const discoveryProgress = event(
  "collection.discovery.progress.v1",
  z.object({
    files_discovered: z.number().int().nonnegative(),
    files_total: z.number().int().nonnegative().optional(),
  }),
);

/**
 * One named file, or a count of them.
 *
 * Both fields are optional because the two producers know different things.
 * The fixture names the file; the backend's `file.discovered.v1` is a running
 * count and has no name to give. Requiring `file_name` would mean the adapter
 * could only satisfy this schema by inventing one, and a fabricated filename
 * on an evidence surface is exactly the thing this repository refuses.
 *
 * `eventLines()` prints whichever arrived, and says so either way.
 */
const fileDiscovered = event(
  "file.discovered.v1",
  z
    .object({
      file_name: z.string().min(1).optional(),
      files_discovered: z.number().int().nonnegative().optional(),
      sha256_prefix: z.string().min(1).optional(),
    })
    // Optional does not mean "all of them at once". An empty payload would
    // render as "a file" — a discovery the stream never reported.
    .refine(
      (payload) =>
        payload.file_name !== undefined || payload.files_discovered !== undefined,
      { message: "file.discovered.v1 needs a file_name or a files_discovered" },
    ),
);

const duplicateDetected = event(
  "file.duplicate.detected.v1",
  z.object({
    duplicates_total: z.number().int().nonnegative(),
    sha256_prefix: z.string().min(1).optional(),
  }),
);

const revisionFamilyDetected = event(
  "revision.family.detected.v1",
  z.object({
    families_total: z.number().int().nonnegative(),
    /** "probable" is load-bearing: a revision family is a hypothesis. */
    confidence: z.enum(["probable", "confirmed"]),
  }),
);

const documentProfiled = event(
  "document.profiled.v1",
  z.object({
    documents_profiled: z.number().int().nonnegative(),
    complex_tables_total: z.number().int().nonnegative().optional(),
  }),
);

/* ── ROUTE / RECOVER ────────────────────────────────────────────────────── */

/**
 * `attempt` and `reason` are per-page facts the fixture has and the backend's
 * job-level summary does not; `page_count` is the reverse. `lane` is the one
 * thing both can state — the adapter reads it off `route_counts`.
 */
const routeSelected = event(
  "page.route.selected.v1",
  z.object({
    lane: z.enum(ROUTE_LANES),
    attempt: z.number().int().positive().optional(),
    reason: z.string().min(1).optional(),
    page_count: z.number().int().nonnegative().optional(),
  }),
);

const verificationFailed = event(
  "verification.failed.v1",
  z.object({
    finding_code: z.string().min(1),
    detail: z.string().min(1),
  }),
);

const documentRerouted = event(
  "document.rerouted.v1",
  z.object({
    from_lane: z.enum(ROUTE_LANES),
    to_lane: z.enum(ROUTE_LANES),
    attempt: z.number().int().positive(),
  }),
);

const recoveryCompleted = event(
  "recovery.completed.v1",
  z.object({
    /** Which try succeeded. The backend reports an attempt *id*, not an index. */
    attempt: z.number().int().positive().optional(),
    /** The backend's terminal state for the recovery, carried verbatim. */
    final_state: z.string().min(1).optional(),
    /**
     * §11.2 R3 — a recovered unit keeps its scar. The projection counts
     * these separately so a run never reads as clean when it was repaired.
     */
    verified: z.literal(true),
  }),
);

/* ── WORLD ──────────────────────────────────────────────────────────────── */

/**
 * An entity, or a count of them — and the difference is load-bearing.
 *
 * The WORLD act draws twelve named nodes because the fixture names twelve
 * entities. The backend's `entity.resolved.v1` is a per-job count with a
 * scope and no identities, so the adapter can honestly report *how many* and
 * nothing more. That is a real limit of the live path today, and the UI shows
 * the count rather than inventing nodes to fill the frame.
 */
const entityResolved = event(
  "entity.resolved.v1",
  z
    .object({
      entity_id: z.string().min(1).optional(),
      entity_type: z.string().min(1).optional(),
      label: z.string().min(1).optional(),
      entity_count: z.number().int().nonnegative().optional(),
      scope: z.string().min(1).optional(),
    })
    // An identity or a count. Neither would render as "0 resolved", which is
    // a statement about the world that no event made.
    .refine(
      (payload) =>
        payload.entity_id !== undefined || payload.entity_count !== undefined,
      { message: "entity.resolved.v1 needs an entity_id or an entity_count" },
    ),
);

const relationCreated = event(
  "relation.created.v1",
  z
    .object({
      relation_id: z.string().min(1).optional(),
      from_entity_id: z.string().min(1).optional(),
      to_entity_id: z.string().min(1).optional(),
      predicate: z.string().min(1).optional(),
      relation_count: z.number().int().nonnegative().optional(),
      evidence_bound: z.boolean().optional(),
    })
    .refine(
      (payload) =>
        payload.relation_id !== undefined || payload.relation_count !== undefined,
      { message: "relation.created.v1 needs a relation_id or a relation_count" },
    )
    // A named relation must name both ends. Half a relation renders as
    // "undefined —predicate→ undefined".
    .refine(
      (payload) =>
        payload.relation_id === undefined ||
        (payload.from_entity_id !== undefined &&
          payload.to_entity_id !== undefined &&
          payload.predicate !== undefined),
      { message: "a named relation needs both endpoints and a predicate" },
    ),
);

const knowledgeUnitCreated = event(
  "knowledge.unit.created.v1",
  z.object({
    unit_id: z.string().min(1),
    title: z.string().min(1),
    source_ref: sourceRefLiteSchema,
  }),
);

/**
 * A source document gained a revision, and with it a new value in one cell.
 *
 * The head of the CHANGE sequence. An edit is not a preview here: it revises a
 * source, and what follows —  impact, recompilation, activation — is the world
 * catching up to that revision. `previous_value` travels with it because a
 * revision that cannot say what it replaced cannot support a before/after
 * reading of the two world states.
 */
const sourceRevisionCreated = event(
  "source.revision.created.v1",
  z.object({
    change_id: z.string().min(1),
    document_id: z.string().min(1),
    revision: z.number().int().positive(),
    previous_revision: z.number().int().positive(),
    locator: z.string().min(1),
    cell: z.string().min(1),
    previous_value: z.string().min(1),
    new_value: z.string().min(1),
  }),
);

/**
 * `revision` and `previous_world_state_id` are what make activation a
 * transition rather than a fact. The first activation of a session has no
 * predecessor; every later one names the state it replaced, so the world it
 * replaced stays addressable instead of being overwritten.
 */
const worldStateActivated = event(
  "world_state.activated.v1",
  z.object({
    world_state_id: z.string().min(1),
    revision: z.number().int().positive(),
    previous_world_state_id: z.string().min(1).optional(),
    entities: z.number().int().nonnegative(),
    relations: z.number().int().nonnegative(),
    knowledge_units: z.number().int().nonnegative(),
  }),
);

/* ── TRUTH ──────────────────────────────────────────────────────────────── */

const conflictDetected = event(
  "conflict.detected.v1",
  z.object({
    conflict_id: z.string().min(1),
    subject: z.string().min(1),
    candidate_unit_ids: z.array(z.string().min(1)).min(2),
  }),
);

const authorityResolved = event(
  "authority.resolved.v1",
  z.object({
    conflict_id: z.string().min(1),
    winner_unit_id: z.string().min(1),
    basis: z.enum(RESOLUTION_BASIS),
    /**
     * The losers keep their status rather than disappearing. A superseded
     * unit that vanishes cannot be audited, and PART 17.2's point is that
     * resolution is visible, not that the newest file wins.
     */
    outcomes: z
      .array(
        z.object({
          unit_id: z.string().min(1),
          status: z.enum(TEMPORAL_STATUS),
        }),
      )
      .min(2),
  }),
);

/* ── CHANGE ─────────────────────────────────────────────────────────────── */

const impactDetected = event(
  "impact.detected.v1",
  z.object({
    change_id: z.string().min(1),
    changed_unit_id: z.string().min(1),
    sources_changed: z.number().int().positive(),
    knowledge_units_affected: z.number().int().nonnegative(),
    agent_contexts_stale: z.number().int().nonnegative(),
    retrieval_packages_invalidated: z.number().int().nonnegative(),
  }),
);

const recompileProgress = event(
  "recompile.progress.v1",
  z.object({
    change_id: z.string().min(1),
    /**
     * §11.2 R5 — progress is counted, never estimated. Both terms are
     * carried so the UI never has to compute a percentage to render.
     */
    recompiled: z.number().int().nonnegative(),
    scheduled: z.number().int().positive(),
    world_units_total: z.number().int().positive(),
    unit_id: z.string().min(1).optional(),
  }),
);

const recompileCompleted = event(
  "recompile.completed.v1",
  z.object({
    change_id: z.string().min(1),
    recompiled: z.number().int().nonnegative(),
    world_units_total: z.number().int().positive(),
  }),
);

/* ── ASK ────────────────────────────────────────────────────────────────── */

const answerResolutionStarted = event(
  "answer.resolution.started.v1",
  z.object({
    question_id: z.string().min(1),
    question: z.string().min(1),
  }),
);

const answerSourceResolved = event(
  "answer.source.resolved.v1",
  z.object({
    question_id: z.string().min(1),
    document_label: z.string().min(1),
    status: z.enum(TEMPORAL_STATUS),
  }),
);

const answerEmitted = event(
  "answer.emitted.v1",
  z.object({
    question_id: z.string().min(1),
    answer: z.string().min(1),
    /**
     * Four independent checks, not a score. A scalar confidence number is
     * exactly the shape this product refuses to publish.
     */
    guarantees: z
      .array(
        z.object({
          label: z.string().min(1),
          held: z.boolean(),
          because: z.string().min(1),
        }),
      )
      .min(1),
    trace: z.array(z.string().min(1)).min(2),
    source_ref: sourceRefLiteSchema,
  }),
);

export const productEventSchema = z.discriminatedUnion("event_type", [
  discoveryProgress,
  fileDiscovered,
  duplicateDetected,
  revisionFamilyDetected,
  documentProfiled,
  routeSelected,
  verificationFailed,
  documentRerouted,
  recoveryCompleted,
  entityResolved,
  relationCreated,
  knowledgeUnitCreated,
  sourceRevisionCreated,
  worldStateActivated,
  conflictDetected,
  authorityResolved,
  impactDetected,
  recompileProgress,
  recompileCompleted,
  answerResolutionStarted,
  answerSourceResolved,
  answerEmitted,
]);

export type ProductEvent = z.infer<typeof productEventSchema>;

export type ProductEventOf<T extends ProductEventType> = Extract<
  ProductEvent,
  { event_type: T }
>;

/**
 * The contract both sources satisfy.
 *
 * `subscribe` returns its unsubscribe function so a React effect can clean up
 * without the source keeping a registry keyed by identity. `seek` exists for
 * the demo replay control and is optional because a live stream cannot honour
 * it — a stream that silently ignored a seek would be the "silent fallback"
 * CLAUDE.md forbids, so the capability is absent rather than faked.
 */
export interface ProductEventSource {
  readonly mode: "demo" | "live";
  readonly label: string;
  subscribe(listener: (event: ProductEvent) => void): () => void;
  start(): void;
  stop(): void;
  seek?(sequence: number): void;
}

/**
 * Parse one wire event.
 *
 * Returns `undefined` for anything that fails, and the caller drops it. A
 * malformed event on a public landing page must not blank the screen, and it
 * must not be rendered half-parsed either.
 */
export function parseProductEvent(value: unknown): ProductEvent | undefined {
  const result = productEventSchema.safeParse(value);
  return result.success ? result.data : undefined;
}
