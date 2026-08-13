import type {
  ProductEvent,
  RouteLane,
  TemporalStatus,
} from "@/lib/product-event";

/**
 * The projection — the only place a `ProductEvent` becomes something a
 * component renders.
 *
 * There is exactly one of these because there is exactly one UI. The demo
 * fixture and the live SSE stream both hand events to `reduceProductEvent`,
 * so a divergence between "what the marketing page shows" and "what the
 * product shows" would have to be written deliberately rather than drift in.
 *
 * Deliberately a pure reducer over a plain object: it is unit-testable without
 * a DOM, it can run on the server for a static first frame, and it is cheap
 * enough to run per event without memoisation.
 *
 * Two invariants it enforces rather than trusts:
 *
 *   §11.2 R5   progress is counted. `recompiled` and `scheduled` both come
 *              from the event; nothing here divides them into a percentage
 *              or extrapolates an ETA.
 *   §11.2 R3   a recovered page keeps its scar. `recovered` is a separate
 *              counter from `verified` and is never folded into it.
 */

export interface DiscoveryProjection {
  filesDiscovered: number;
  revisionFamilies: number;
  duplicates: number;
  documentsProfiled: number;
  complexTables: number;
  /**
   * Files named by `file.discovered.v1`, in arrival order.
   *
   * The count and the identities arrive on different events, so they are kept
   * as separate fields: `filesDiscovered` is authoritative for how many, this
   * is authoritative for which, and neither is inferred from the other.
   */
  namedFiles: string[];
}

export interface LaneEvent {
  key: string;
  lane: RouteLane;
  /**
   * Which page this was. Absent on an adapted live frame: the backend's
   * job-summary events carry no `page_number`, and the envelope only admits a
   * positive one — so the `?? 0` this used to default to named a page that
   * cannot exist.
   */
  pageNumber: number | undefined;
  /**
   * Which try this was. Absent on an adapted live frame: the backend reports
   * an attempt *id*, not an index, and a page chip that invented "attempt 1"
   * would be asserting something nobody said.
   */
  attempt: number | undefined;
  /** Plain-language line for the milestone rail. */
  line: string;
  kind: "route" | "finding" | "reroute" | "recovered";
}

export interface WorldProjection {
  /**
   * I2 §5/§10 — highest `sequence` applied, per plane+identity, keyed by
   * `` `${scope.kind}:${identity}` `` (e.g. `"job:job-abc"`,
   * `"collection:coll-xyz"`, `"demo:*"`). Job-plane and collection-plane
   * `sequence` are different counter spaces (per-job vs. per-collection
   * monotonic) and are not comparable, so a single global counter would let
   * one plane's numbering mask the other's replays. Live sources resume each
   * scope from its own cursor.
   */
  lastSequenceByScope: Record<string, number>;
  mode: "demo" | "live" | "idle";
  discovery: DiscoveryProjection;
  lanes: LaneEvent[];
  /** §11.2 R3 — kept apart from any success count. */
  recoveredPages: number;
  entityIds: string[];
  relationIds: string[];
  unitIds: string[];
  worldActive: boolean;
  worldTotals: { entities: number; relations: number; knowledgeUnits: number };
  /**
   * Which world state is active, and which one it replaced.
   *
   * `previousId` is retained rather than overwritten: the CHANGE act activates
   * a second world state and the point of that act is the difference between
   * the two, which is not expressible if activation only ever means "now".
   */
  worldState:
    | { id: string; revision: number; previousId: string | undefined }
    | undefined;
  /** The source edit that started the current change, if one did. */
  sourceRevision:
    | {
        changeId: string;
        documentId: string;
        revision: number;
        previousRevision: number;
        locator: string;
        cell: string;
        previousValue: string;
        newValue: string;
      }
    | undefined;
  conflictSubject: string | undefined;
  resolution: {
    winnerUnitId: string;
    basis: string;
    outcomes: { unitId: string; status: TemporalStatus }[];
  } | undefined;
  impact: {
    changeId: string;
    sourcesChanged: number;
    knowledgeUnitsAffected: number;
    agentContextsStale: number;
    retrievalPackagesInvalidated: number;
  } | undefined;
  recompile: {
    recompiled: number;
    scheduled: number;
    worldUnitsTotal: number;
    done: boolean;
    unitIds: string[];
  } | undefined;
  ask: {
    question: string;
    resolved: { documentLabel: string; status: TemporalStatus }[];
    answer: string | undefined;
    guarantees: { label: string; held: boolean; because: string }[];
    trace: string[];
  } | undefined;
}

export const EMPTY_PROJECTION: WorldProjection = {
  lastSequenceByScope: {},
  mode: "idle",
  discovery: {
    filesDiscovered: 0,
    revisionFamilies: 0,
    duplicates: 0,
    documentsProfiled: 0,
    complexTables: 0,
    namedFiles: [],
  },
  lanes: [],
  recoveredPages: 0,
  entityIds: [],
  relationIds: [],
  unitIds: [],
  worldActive: false,
  worldTotals: { entities: 0, relations: 0, knowledgeUnits: 0 },
  worldState: undefined,
  sourceRevision: undefined,
  conflictSubject: undefined,
  resolution: undefined,
  impact: undefined,
  recompile: undefined,
  ask: undefined,
};

function laneKey(event: ProductEvent, kind: LaneEvent["kind"]): string {
  return `${kind}-${event.sequence}`;
}

/**
 * I2 §5 — the cursor key for an event's scope: `` `${kind}:${identity}` ``.
 * Every `"demo"` event shares one cursor (`"demo:*"`) rather than one per
 * `fixture_id` — I2 §5's own example, and fixture replay does not need
 * finer-grained idempotency than "this fixture stream" today.
 */
export function scopeKey(scope: ProductEvent["scope"]): string {
  switch (scope.kind) {
    case "job":
      return `job:${scope.job_id}`;
    case "collection":
      return `collection:${scope.collection_id}`;
    case "demo":
      return "demo:*";
  }
}

export function reduceProductEvent(
  state: WorldProjection,
  event: ProductEvent,
): WorldProjection {
  const key = scopeKey(event.scope);
  const cursor = state.lastSequenceByScope[key] ?? 0;

  // At-least-once delivery means a replayed event must be a no-op, not a
  // double count. Dropping anything at or below the cursor is the cheapest
  // correct rule and matches how event-reducer.ts guards the job stream —
  // scoped per plane+identity so a job-scope and a collection-scope event
  // that happen to share a numeric `sequence` are never mistaken for
  // duplicates of each other (I2 §5, the central design problem this file
  // implements).
  if (event.sequence <= cursor) return state;

  const next: WorldProjection = {
    ...state,
    lastSequenceByScope: { ...state.lastSequenceByScope, [key]: event.sequence },
    mode: event.mode,
  };

  switch (event.event_type) {
    case "collection.discovery.progress.v1":
      next.discovery = {
        ...state.discovery,
        filesDiscovered: event.payload.files_discovered,
      };
      return next;

    /*
     * Only a named file joins `namedFiles`. The adapted form of this event
     * carries a count instead, and a count is already `filesDiscovered` —
     * pushing a placeholder would make the list lie about what it holds.
     */
    case "file.discovered.v1":
      next.discovery = {
        ...state.discovery,
        namedFiles: event.payload.file_name
          ? [...state.discovery.namedFiles, event.payload.file_name]
          : state.discovery.namedFiles,
        filesDiscovered:
          event.payload.files_discovered ?? state.discovery.filesDiscovered,
      };
      return next;

    case "revision.family.detected.v1":
      next.discovery = {
        ...state.discovery,
        revisionFamilies: event.payload.families_total,
      };
      return next;

    case "file.duplicate.detected.v1":
      next.discovery = {
        ...state.discovery,
        duplicates: event.payload.duplicates_total,
      };
      return next;

    case "document.profiled.v1":
      next.discovery = {
        ...state.discovery,
        documentsProfiled: event.payload.documents_profiled,
        complexTables:
          event.payload.complex_tables_total ?? state.discovery.complexTables,
      };
      return next;

    case "page.route.selected.v1":
      next.lanes = [
        ...state.lanes,
        {
          key: laneKey(event, "route"),
          lane: event.payload.lane,
          pageNumber: event.page_number,
          attempt: event.payload.attempt,
          line:
            event.page_number === undefined
              ? `Routed to ${event.payload.lane}`
              : `Page ${event.page_number} routed to ${event.payload.lane}`,
          kind: "route",
        },
      ];
      return next;

    /*
     * A finding names a page only when the event carried one.
     *
     * `attempt: 1` used to be hardcoded here and the page defaulted to 0. On
     * the fixture path both were harmless — every frame has a page and a first
     * attempt. Once the live adapter existed, a collection-level
     * `verification.failed.v1` reached this line and rendered as "Page 0 ·
     * attempt 1", two facts the event never stated.
     */
    case "verification.failed.v1":
      next.lanes = [
        ...state.lanes,
        {
          key: laneKey(event, "finding"),
          lane: "PRECISION",
          pageNumber: event.page_number,
          attempt: undefined,
          line:
            event.page_number === undefined
              ? "Requires deeper inspection"
              : `Page ${event.page_number} requires deeper inspection`,
          kind: "finding",
        },
      ];
      return next;

    case "document.rerouted.v1":
      next.lanes = [
        ...state.lanes,
        {
          key: laneKey(event, "reroute"),
          lane: event.payload.to_lane,
          pageNumber: event.page_number,
          attempt: event.payload.attempt,
          line: "Rerouting...",
          kind: "reroute",
        },
      ];
      return next;

    case "recovery.completed.v1":
      next.lanes = [
        ...state.lanes,
        {
          key: laneKey(event, "recovered"),
          // The lane is derived, not sent: §11.3 keeps RECOVERY a display
          // concept so the backend's route_label enum stays as it is.
          lane: "RECOVERY",
          pageNumber: event.page_number,
          attempt: event.payload.attempt,
          line: "Recovered",
          kind: "recovered",
        },
      ];
      next.recoveredPages = state.recoveredPages + 1;
      return next;

    /*
     * An identity extends the list; a count sets the total. The WORLD act
     * draws one node per id, so a live stream that only knows *how many*
     * entities exist correctly draws none and reports the number instead.
     */
    case "entity.resolved.v1":
      if (event.payload.entity_id) {
        next.entityIds = [...state.entityIds, event.payload.entity_id];
      } else if (event.payload.entity_count !== undefined) {
        next.worldTotals = {
          ...state.worldTotals,
          entities: event.payload.entity_count,
        };
      }
      return next;

    case "relation.created.v1":
      if (event.payload.relation_id) {
        next.relationIds = [...state.relationIds, event.payload.relation_id];
      } else if (event.payload.relation_count !== undefined) {
        next.worldTotals = {
          ...state.worldTotals,
          relations: event.payload.relation_count,
        };
      }
      return next;

    case "knowledge.unit.created.v1":
      next.unitIds = [...state.unitIds, event.payload.unit_id];
      return next;

    case "world_state.activated.v1":
      next.worldActive = true;
      next.worldTotals = {
        entities: event.payload.entities,
        relations: event.payload.relations,
        knowledgeUnits: event.payload.knowledge_units,
      };
      next.worldState = {
        id: event.payload.world_state_id,
        revision: event.payload.revision,
        previousId: event.payload.previous_world_state_id,
      };
      return next;

    case "source.revision.created.v1":
      next.sourceRevision = {
        changeId: event.payload.change_id,
        documentId: event.payload.document_id,
        revision: event.payload.revision,
        previousRevision: event.payload.previous_revision,
        locator: event.payload.locator,
        cell: event.payload.cell,
        previousValue: event.payload.previous_value,
        newValue: event.payload.new_value,
      };
      return next;

    case "conflict.detected.v1":
      next.conflictSubject = event.payload.subject;
      return next;

    case "authority.resolved.v1":
      next.resolution = {
        winnerUnitId: event.payload.winner_unit_id,
        basis: event.payload.basis,
        outcomes: event.payload.outcomes.map((outcome) => ({
          unitId: outcome.unit_id,
          status: outcome.status,
        })),
      };
      return next;

    case "impact.detected.v1":
      next.impact = {
        changeId: event.payload.change_id,
        sourcesChanged: event.payload.sources_changed,
        knowledgeUnitsAffected: event.payload.knowledge_units_affected,
        agentContextsStale: event.payload.agent_contexts_stale,
        retrievalPackagesInvalidated:
          event.payload.retrieval_packages_invalidated,
      };
      next.recompile = undefined;
      return next;

    case "recompile.progress.v1":
      next.recompile = {
        recompiled: event.payload.recompiled,
        scheduled: event.payload.scheduled,
        worldUnitsTotal: event.payload.world_units_total,
        done: false,
        unitIds: event.payload.unit_id
          ? [...(state.recompile?.unitIds ?? []), event.payload.unit_id]
          : (state.recompile?.unitIds ?? []),
      };
      return next;

    case "recompile.completed.v1":
      next.recompile = {
        recompiled: event.payload.recompiled,
        scheduled: state.recompile?.scheduled ?? event.payload.recompiled,
        worldUnitsTotal: event.payload.world_units_total,
        done: true,
        unitIds: state.recompile?.unitIds ?? [],
      };
      return next;

    case "answer.resolution.started.v1":
      next.ask = {
        question: event.payload.question,
        resolved: [],
        answer: undefined,
        guarantees: [],
        trace: [],
      };
      return next;

    case "answer.source.resolved.v1": {
      const ask = state.ask;
      if (!ask) return next;
      next.ask = {
        ...ask,
        resolved: [
          ...ask.resolved,
          {
            documentLabel: event.payload.document_label,
            status: event.payload.status,
          },
        ],
      };
      return next;
    }

    case "answer.emitted.v1": {
      const ask = state.ask;
      if (!ask) return next;
      next.ask = {
        ...ask,
        answer: event.payload.answer,
        guarantees: event.payload.guarantees.map((guarantee) => ({ ...guarantee })),
        trace: [...event.payload.trace],
      };
      return next;
    }
  }
}

export function reduceProductEvents(
  events: readonly ProductEvent[],
  from: WorldProjection = EMPTY_PROJECTION,
): WorldProjection {
  return events.reduce(reduceProductEvent, from);
}
