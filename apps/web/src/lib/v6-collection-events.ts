import type { CollectionEvent } from "@/lib/collection-runtime-client";
import {
  V6_PARALLEL_EVENT_TYPES,
  type V6VersionedEvent,
} from "@/components/v6";

const V6_PARALLEL_EVENT_TYPE_SET = new Set<string>(V6_PARALLEL_EVENT_TYPES);

function payloadString(
  event: CollectionEvent,
  key: string,
): string | undefined {
  const value = event.payload[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/**
 * Adapt only durable, job-correlated collection events. The adapter renames
 * the authoritative timestamp field but never manufactures job, page, pool,
 * attempt, or cost evidence that was not present in the event ledger.
 */
export function collectionEventsToV6(
  events: readonly CollectionEvent[],
  activeJobId?: string | null,
): V6VersionedEvent[] {
  return events.flatMap((event) => {
    if (event.job_id === null) return [];
    if (activeJobId && event.job_id !== activeJobId) return [];
    const projectId = payloadString(event, "project_id");
    const documentId = payloadString(event, "document_id");
    const documentVersionId = payloadString(event, "document_version_id");
    const pageId = payloadString(event, "page_id");
    return [
      {
        schema_version: event.schema_version,
        event_id: event.event_id,
        event_type: event.event_type,
        sequence: event.sequence,
        occurred_at: event.timestamp,
        job_id: event.job_id,
        payload: event.payload,
        ...(projectId ? { project_id: projectId } : {}),
        ...(documentId ? { document_id: documentId } : {}),
        ...(documentVersionId
          ? { document_version_id: documentVersionId }
          : {}),
        ...(pageId ? { page_id: pageId } : {}),
      },
    ];
  });
}

export function hasV6ParallelEvidence(
  events: readonly V6VersionedEvent[],
): boolean {
  return events.some((event) => V6_PARALLEL_EVENT_TYPE_SET.has(event.event_type));
}

/** Sequence immediately before the bounded durable replay window. */
export function v6ReplayBaseline(
  events: readonly V6VersionedEvent[],
): number | undefined {
  const first = events.at(0);
  return first === undefined ? undefined : Math.max(0, first.sequence - 1);
}
