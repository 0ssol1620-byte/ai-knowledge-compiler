/**
 * Generated TypeScript bindings for the canonical ProductEvent envelope.
 *
 * Source of truth: `packages/contracts/product-event.schema.json`
 * (TAVONEL Cinematic Compilation Replay Master Spec v2.0, §9.4). Regenerate
 * from the schema rather than hand-editing: the Python twin lives in
 * `packages/contracts/src/akc_contracts/product_event.py`, and the two must
 * stay byte-for-byte equivalent on the wire.
 *
 * The envelope deliberately validates framing only — identity, ordering,
 * mode and scope. Per-type payload contracts are a separate conformance layer
 * (spec Phase 1, steps 4-6), so `payload` stays `unknown` here.
 */

export const PRODUCT_EVENT_SCHEMA_VERSION = "1.0";

/**
 * §9.3 A — names already produced by `akc_cir.collection_events`. The names
 * are shared; the backend's required payload fields are not yet (see
 * docs/ux/CINEMATIC_EVENT_CONTRACT.md for the measured divergence).
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

/** §9.3 B — client proposal types; fixture-only until a producer exists. */
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

export interface JobScope {
  kind: "job";
  job_id: string;
  document_id?: string;
  page_number?: number;
}

export interface CollectionScope {
  kind: "collection";
  collection_id: string;
  job_id?: string;
}

export interface DemoScope {
  kind: "demo";
  fixture_id?: string;
}

export type EventScope = JobScope | CollectionScope | DemoScope;

/** §9.4 canonical envelope, verbatim. */
export interface ProductEventEnvelopeV1 {
  schema_version: typeof PRODUCT_EVENT_SCHEMA_VERSION;
  event_id: string;
  event_type: ProductEventType;
  /** Monotonic per scope (§9.6); never comparable across scopes. */
  sequence: number;
  occurred_at: string;
  monotonic_offset_ms?: number;
  mode: "demo" | "live";
  scope: EventScope;
  /** Opaque at the envelope level; typed by per-event payload contracts. */
  payload: unknown;
}

const REGISTERED_EVENT_TYPES: ReadonlySet<string> = new Set(PRODUCT_EVENT_TYPES);

const ENVELOPE_KEYS: ReadonlySet<string> = new Set([
  "schema_version",
  "event_id",
  "event_type",
  "sequence",
  "occurred_at",
  "monotonic_offset_ms",
  "mode",
  "scope",
  "payload",
]);

const SCOPE_ALLOWED_KEYS: Record<EventScope["kind"], ReadonlySet<string>> = {
  job: new Set(["kind", "job_id", "document_id", "page_number"]),
  collection: new Set(["kind", "collection_id", "job_id"]),
  demo: new Set(["kind", "fixture_id"]),
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function optionalNonEmptyString(value: Record<string, unknown>, key: string): boolean {
  return !(key in value) || value[key] === undefined || isNonEmptyString(value[key]);
}

function optionalPageNumber(value: Record<string, unknown>): boolean {
  return (
    !("page_number" in value) ||
    value["page_number"] === undefined ||
    isPositiveInteger(value["page_number"])
  );
}

export function isProductEventType(value: unknown): value is ProductEventType {
  return typeof value === "string" && REGISTERED_EVENT_TYPES.has(value);
}

export function isProductEventScope(value: unknown): value is EventScope {
  if (!isRecord(value)) return false;
  switch (value["kind"]) {
    case "job":
      return (
        hasOnlyKeys(value, SCOPE_ALLOWED_KEYS.job) &&
        isNonEmptyString(value["job_id"]) &&
        optionalNonEmptyString(value, "document_id") &&
        optionalPageNumber(value)
      );
    case "collection":
      return (
        hasOnlyKeys(value, SCOPE_ALLOWED_KEYS.collection) &&
        isNonEmptyString(value["collection_id"]) &&
        optionalNonEmptyString(value, "job_id")
      );
    case "demo":
      return hasOnlyKeys(value, SCOPE_ALLOWED_KEYS.demo) && optionalNonEmptyString(value, "fixture_id");
    default:
      return false;
  }
}

/**
 * Runtime guard mirroring `product-event.schema.json` one-to-one:
 * unknown keys are rejected at every level (`additionalProperties: false`),
 * so a drifted producer fails here instead of rendering half a frame.
 */
export function isProductEventEnvelopeV1(value: unknown): value is ProductEventEnvelopeV1 {
  if (!isRecord(value)) return false;
  if (!hasOnlyKeys(value, ENVELOPE_KEYS)) return false;
  if (!("payload" in value)) return false;
  if (value["schema_version"] !== PRODUCT_EVENT_SCHEMA_VERSION) return false;
  if (!isNonEmptyString(value["event_id"])) return false;
  if (!isProductEventType(value["event_type"])) return false;
  if (!isPositiveInteger(value["sequence"])) return false;
  if (!isNonEmptyString(value["occurred_at"])) return false;
  if (
    "monotonic_offset_ms" in value &&
    value["monotonic_offset_ms"] !== undefined &&
    (typeof value["monotonic_offset_ms"] !== "number" ||
      !Number.isFinite(value["monotonic_offset_ms"]))
  ) {
    return false;
  }
  if (value["mode"] !== "demo" && value["mode"] !== "live") return false;
  return isProductEventScope(value["scope"]);
}
