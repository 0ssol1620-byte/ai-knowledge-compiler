import type {
  BlockOrigin,
  CanonicalBlock,
  CanonicalBlockPatch,
  JobEvent,
  LiveJobState,
  PageStatus,
  ReviewItem,
} from "@/lib/types";

const EVENT_WINDOW = 512;

export type LiveJobAction =
  | JobEvent
  | {
      kind: "snapshot.reset";
      lastSequence: number;
    };

type BlockEventPayload = {
  block_id: string;
  type?: CanonicalBlock["type"];
  block_type?: CanonicalBlock["type"];
  markdown?: string;
  source_text?: string;
  origin?: BlockOrigin | "native" | "ocr" | "layout_reconstructed";
  origin_type?: BlockOrigin | "native" | "ocr" | "layout_reconstructed";
  content_layer?: CanonicalBlock["content_layer"];
  confidence?: number;
  quality_flags?: string[];
  warnings?: string[];
  order?: number;
  revision?: number;
  source_refs?: CanonicalBlock["source_refs"];
};

function normalizeOrigin(value: BlockEventPayload["origin_type"]): BlockOrigin {
  if (value === "native") return "native_extracted";
  if (value === "ocr") return "ocr_extracted";
  if (value === "layout_reconstructed") return "rule_reconstructed";
  return value ?? "native_extracted";
}

function blockFromEvent(event: JobEvent): CanonicalBlockPatch | undefined {
  const payload = event.payload as Partial<BlockEventPayload>;
  if (!payload.block_id) return undefined;
  const blockType = payload.block_type ?? payload.type;
  const origin = payload.origin_type ?? payload.origin;
  const qualityFlags = payload.warnings ?? payload.quality_flags;
  return {
    id: payload.block_id,
    ...(payload.order !== undefined ? { order: payload.order } : {}),
    ...(blockType !== undefined ? { type: blockType } : {}),
    ...(payload.markdown !== undefined ? { markdown: payload.markdown } : {}),
    ...(payload.source_text !== undefined
      ? { source_text: payload.source_text }
      : {}),
    ...(origin !== undefined ? { origin: normalizeOrigin(origin) } : {}),
    ...(payload.content_layer !== undefined
      ? { content_layer: payload.content_layer }
      : {}),
    ...(payload.source_refs !== undefined
      ? { source_refs: payload.source_refs }
      : {}),
    ...(payload.confidence !== undefined
      ? { confidence: payload.confidence }
      : {}),
    ...(qualityFlags !== undefined ? { quality_flags: qualityFlags } : {}),
    ...(payload.revision !== undefined ? { revision: payload.revision } : {}),
  };
}

export const initialLiveJobState: LiveJobState = {
  lastSequence: 0,
  seenEventIds: [],
  pendingEvents: {},
  needsReplay: false,
  stageProgress: {},
  pageStatus: {},
  blockPatches: {},
  warnings: {},
  connection: "idle",
};

function rememberEvent(ids: string[], id: string): string[] {
  const next = [...ids, id];
  return next.length > EVENT_WINDOW
    ? next.slice(next.length - EVENT_WINDOW)
    : next;
}

function applyOrderedEvent(state: LiveJobState, event: JobEvent): LiveJobState {
  if (state.seenEventIds.includes(event.event_id)) return state;
  if (event.sequence <= state.lastSequence) return state;

  const next: LiveJobState = {
    ...state,
    lastSequence: event.sequence,
    seenEventIds: rememberEvent(state.seenEventIds, event.event_id),
  };

  switch (event.event_type) {
    case "job.stage.progress.v1": {
      const payload = event.payload as {
        stage: string;
        done: number;
        total: number;
      };
      next.stageProgress = {
        ...state.stageProgress,
        [payload.stage]: { done: payload.done, total: payload.total },
      };
      return next;
    }
    case "page.processing.started.v1":
    case "page.completed.v1":
    case "page.needs_review.v1":
    case "page.failed.v1":
    case "page.retry.scheduled.v1": {
      const payload = event.payload as {
        page_id?: string;
        status?: PageStatus;
      };
      const pageId = payload.page_id ?? event.page_id;
      const defaultStatus: Record<string, PageStatus> = {
        "page.processing.started.v1": "ocr_running",
        "page.completed.v1": "completed",
        "page.needs_review.v1": "needs_review",
        "page.failed.v1": "failed",
        "page.retry.scheduled.v1": "retry_scheduled",
      };
      if (pageId) {
        next.pageStatus = {
          ...state.pageStatus,
          [pageId]: payload.status ?? defaultStatus[event.event_type]!,
        };
      }
      if (event.event_type === "page.needs_review.v1") {
        const warning = event.payload as Partial<ReviewItem> & {
          review_item_id?: string;
        };
        const reviewId = warning.review_item_id ?? warning.id;
        if (reviewId && warning.category && warning.message) {
          next.warnings = {
            ...state.warnings,
            [reviewId]: {
              id: reviewId,
              severity: warning.severity ?? "medium",
              category: warning.category,
              message: warning.message,
              page_id: warning.page_id ?? pageId,
              block_id: warning.block_id,
              status: "open",
              candidates: warning.candidates,
            },
          };
        }
      }
      return next;
    }
    case "page.block.completed.v1":
    case "page.markdown.updated.v1": {
      const block = blockFromEvent(event);
      if (block) {
        next.blockPatches = {
          ...state.blockPatches,
          [block.id]: {
            ...state.blockPatches[block.id],
            ...block,
          },
        };
      }
      return next;
    }
    case "job.completed.v1":
      return { ...next, terminalStatus: "completed", connection: "closed" };
    case "job.failed.v1":
      return { ...next, terminalStatus: "failed", connection: "closed" };
    default:
      return next;
  }
}

export function reduceJobEvent(
  state: LiveJobState,
  action: LiveJobAction,
): LiveJobState {
  if ("kind" in action) {
    return {
      ...initialLiveJobState,
      lastSequence: action.lastSequence,
      connection: state.connection,
    };
  }
  const event = action;
  if (state.seenEventIds.includes(event.event_id)) return state;
  if (
    Object.values(state.pendingEvents).some(
      (pending) => pending.event_id === event.event_id,
    )
  ) {
    return state;
  }
  if (event.sequence <= state.lastSequence) return state;

  const expected = state.lastSequence + 1;
  if (event.sequence > expected) {
    return {
      ...state,
      pendingEvents: { ...state.pendingEvents, [event.sequence]: event },
      needsReplay: true,
      gapFrom: expected,
    };
  }

  let next = applyOrderedEvent(state, event);
  const pending = { ...next.pendingEvents };
  delete pending[event.sequence];

  let following = pending[next.lastSequence + 1];
  while (following) {
    delete pending[following.sequence];
    next = applyOrderedEvent({ ...next, pendingEvents: pending }, following);
    following = pending[next.lastSequence + 1];
  }

  return {
    ...next,
    pendingEvents: pending,
    needsReplay: Object.keys(pending).length > 0,
    gapFrom:
      Object.keys(pending).length > 0 ? next.lastSequence + 1 : undefined,
  };
}

export function stageFraction(
  progress: LiveJobState["stageProgress"],
  stage: string,
): number {
  const value = progress[stage];
  if (!value || value.total <= 0) return 0;
  return Math.min(1, Math.max(0, value.done / value.total));
}

const stageWeights: Record<string, number> = {
  upload: 0.04,
  security_scan: 0.04,
  preflight: 0.05,
  extract: 0.28,
  normalize: 0.14,
  knowledge: 0.24,
  validate: 0.15,
  package: 0.06,
};

export function weightedOverallProgress(
  progress: LiveJobState["stageProgress"],
): number {
  const ratio = Object.entries(stageWeights).reduce(
    (sum, [stage, weight]) => sum + stageFraction(progress, stage) * weight,
    0,
  );
  return Math.round(Math.min(1, ratio) * 100);
}
