import { fetchEventSource } from "@microsoft/fetch-event-source";
import { z } from "zod";

import {
  asLive,
  asSample,
  type MarkedData,
} from "@/lib/data-boundary";

export {
  asLive,
  asSample,
  dataSourceOf,
  isLive,
  isSample,
  markedValue,
  SAMPLE_BADGE_LABEL,
} from "@/lib/data-boundary";
import {
  DEMO_ANSWER,
  DEMO_ENTITIES,
  DEMO_GUARANTEES,
  DEMO_IMPACT,
  DEMO_RELATIONS,
  DEMO_TRACE,
  DEMO_WORLD_STATE_ID,
  type DemoGuarantee,
} from "@/lib/demo-workspace";
import type { JobEvent, JobEventType, PreflightEstimate } from "@/lib/types";

// The application ships with a nonce-only CSP. Zod's optional JIT path probes
// `Function(...)`, which Firefox correctly reports as a blocked eval even
// though Zod catches the exception. The interpreter path is deterministic and
// keeps all supported browsers free of CSP violations.
z.config({ jitless: true });

const API_URL = process.env.NEXT_PUBLIC_AKC_API_URL ?? "http://localhost:8000";

export function apiAbsoluteUrl(path: string): string {
  if (!path.startsWith("/")) return path;
  return `${API_URL}${path}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly retryable: boolean,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions extends RequestInit {
  token?: string;
  idempotencyKey?: string;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
  if (options.idempotencyKey)
    headers.set("Idempotency-Key", options.idempotencyKey);

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
    credentials: "include",
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: {
        code?: string;
        message?: string;
        retryable?: boolean;
        request_id?: string;
      };
    };
    throw new ApiError(
      payload.error?.message ??
        `The request could not be completed (${response.status}).`,
      response.status,
      payload.error?.code ?? "HTTP_ERROR",
      payload.error?.retryable ?? response.status >= 500,
      payload.error?.request_id,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function listProjects(): Promise<
  Array<{ id: string; name: string; description?: string; updated_at: string }>
> {
  return apiRequest<
    Array<{
      id: string;
      name: string;
      description?: string;
      updated_at: string;
    }>
  >("/v1/projects");
}

export async function createProject(input: {
  name: string;
  description?: string;
  mode: string;
}): Promise<{ id: string; name: string; description?: string }> {
  return apiRequest<{ id: string; name: string; description?: string }>(
    "/v1/projects",
    {
      method: "POST",
      idempotencyKey: crypto.randomUUID(),
      body: JSON.stringify({
        name: input.name,
        description: input.description,
        classification: "general",
        output_profile: {
          processing_mode: input.mode,
        },
      }),
    },
  );
}

export async function analyzeDocument(
  documentId: string,
): Promise<PreflightEstimate> {
  const task = await apiRequest<AnalysisTaskStatus>(
    `/v1/documents/${documentId}/analyze`,
    {
      method: "POST",
      idempotencyKey: crypto.randomUUID(),
    },
  );
  await waitForAnalysis(documentId, { initial: task });
  return apiRequest<PreflightEstimate>(`/v1/documents/${documentId}/estimate`);
}

type ProductAnalyticsEvent =
  | {
      event_type:
        | "landing_demo_started"
        | "landing_demo_completed"
        | "explore_object_opened"
        | "explore_citation_opened"
        | "pricing_viewed"
        | "signup_started"
        | "source_added"
        | "connector_started"
        | "compile_started"
        | "compile_completed"
        | "review_opened"
        | "review_completed"
        | "world_opened"
        | "evidence_opened"
        | "ask_started"
        | "ask_cited_answer"
        | "package_downloaded";
    }
  | { event_type: "estimate_viewed"; document_id: string }
  | { event_type: "result_first_viewed"; job_id: string }
  | {
      event_type: "project_revisited" | "source_merged";
      project_id: string;
    }
  | {
      event_type: "support_session_closed";
      duration_seconds: number;
    }
  | {
      event_type: "user_reported_error";
      project_id: string;
      category:
        | "incorrect_text"
        | "numeric_mismatch"
        | "table_error"
        | "missing_source"
        | "other";
    };

export async function recordProductAnalyticsEvent(
  event: ProductAnalyticsEvent,
): Promise<void> {
  await apiRequest("/v1/analytics/events", {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: JSON.stringify(event),
  });
}

export interface AnalysisTaskStatus {
  task_id: string;
  document_id: string;
  status: "queued" | "running" | "completed" | "failed" | "dead_letter";
  attempt_count: number;
  max_attempts: number;
  page_count: number;
  block_count: number;
  preview_count: number;
  error_code?: string | null;
}

export async function waitForAnalysis(
  documentId: string,
  options: {
    initial?: AnalysisTaskStatus;
    maxElapsedMs?: number;
    wait?: (milliseconds: number) => Promise<void>;
  } = {},
): Promise<AnalysisTaskStatus> {
  const wait = options.wait ?? waitMilliseconds;
  const maxElapsedMs = options.maxElapsedMs ?? 5 * 60 * 1000;
  const startedAt = Date.now();
  let delayMs = 500;
  let task =
    options.initial ??
    (await apiRequest<AnalysisTaskStatus>(
      `/v1/documents/${documentId}/analysis`,
    ));
  while (task.status === "queued" || task.status === "running") {
    if (Date.now() - startedAt >= maxElapsedMs) {
      throw new ApiError(
        "Document preflight did not complete within the time limit.",
        504,
        "ANALYSIS_POLL_TIMEOUT",
        true,
      );
    }
    await wait(delayMs);
    task = await apiRequest<AnalysisTaskStatus>(
      `/v1/documents/${documentId}/analysis`,
    );
    delayMs = Math.min(5000, Math.ceil(delayMs * 1.6));
  }
  if (task.status !== "completed") {
    throw new ApiError(
      "Document preflight failed.",
      422,
      task.error_code ?? "ANALYSIS_FAILED",
      false,
    );
  }
  return task;
}

async function waitMilliseconds(milliseconds: number): Promise<void> {
  await new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));
}

const eventTypes = [
  "job.created.v1",
  "job.stage.started.v1",
  "job.stage.progress.v1",
  "job.stage.completed.v1",
  "page.preflight.completed.v1",
  "page.route.selected.v1",
  "page.processing.started.v1",
  "page.layout.detected.v1",
  "page.block.completed.v1",
  "page.markdown.updated.v1",
  "page.quality.updated.v1",
  "page.retry.scheduled.v1",
  "page.completed.v1",
  "page.needs_review.v1",
  "page.failed.v1",
  "document.knowledge.note_created.v1",
  "document.knowledge.link_created.v1",
  "document.validation.completed.v1",
  "export.started.v1",
  "export.completed.v1",
  "job.completed.v1",
  "job.failed.v1",
  "credit.reserved.v1",
  "credit.consumed.v1",
  "credit.released.v1",
] as const satisfies readonly JobEventType[];

const eventEnvelope = z.object({
  event_id: z.string(),
  event_type: z.enum(eventTypes),
  occurred_at: z.string(),
  project_id: z.string(),
  document_id: z.string().optional(),
  job_id: z.string(),
  page_id: z.string().optional(),
  sequence: z.number().int().positive(),
  schema_version: z.literal("1.0"),
  payload: z.unknown(),
});

export function parseJobEvent(payload: unknown): JobEvent | undefined {
  const parsed = eventEnvelope.safeParse(payload);
  return parsed.success ? parsed.data : undefined;
}

export async function streamJob(
  input: {
    jobId: string;
    lastEventId?: string;
    signal: AbortSignal;
  },
  handlers: {
    onEvent: (event: JobEvent) => void;
    onConnection: (state: "live" | "reconnecting") => void;
    onActivity?: () => void;
    onReset?: () => void;
  },
): Promise<void> {
  let retryAttempt = 0;
  await fetchEventSource(`${API_URL}/v1/jobs/${input.jobId}/events`, {
    method: "GET",
    credentials: "include",
    headers: {
      ...(input.lastEventId ? { "Last-Event-ID": input.lastEventId } : {}),
    },
    signal: input.signal,
    openWhenHidden: true,
    onopen(response) {
      if (!response.ok) {
        const retryable =
          response.status === 408 ||
          response.status === 429 ||
          response.status >= 500;
        throw new ApiError(
          "The real-time connection failed.",
          response.status,
          "SSE_OPEN",
          retryable,
        );
      }
      retryAttempt = 0;
      handlers.onConnection("live");
      handlers.onActivity?.();
      return Promise.resolve();
    },
    onmessage(message) {
      // fetch-event-source dispatches an empty message for the server's
      // `: heartbeat` comment, so transport liveness is observable without
      // inventing a persisted domain event.
      handlers.onActivity?.();
      if (!message.data) return;
      try {
        const payload = JSON.parse(message.data) as unknown;
        // Replay reset is an SSE transport control message, not a persisted
        // processing event. It deliberately stays outside JobEventType.
        if (message.event === "stream.replay.reset.v1") {
          handlers.onReset?.();
          return;
        }
        const event = parseJobEvent(payload);
        if (event) handlers.onEvent(event);
      } catch {
        // A malformed event is ignored; sequence replay will fill the gap.
      }
    },
    onerror(error) {
      handlers.onConnection("reconnecting");
      if (error instanceof ApiError && !error.retryable) throw error;
      retryAttempt += 1;
      const exponential = Math.min(
        30_000,
        1_000 * 2 ** Math.min(retryAttempt, 5),
      );
      return exponential + Math.floor(Math.random() * 500);
    },
  });
}

/* ── /v1/world client stubs ──────────────────────────────────────────────── */

/**
 * Client half of the `/v1/world` surface: `getWorld`, `listChanges`, and
 * `ask` are real fetch calls against the API base URL, but the backend world
 * module is still being built separately. Until it exists every call fails to
 * connect — which is not an error state for the UI — so each function falls
 * back through the SAMPLE/LIVE data boundary (`asSample`) to the registered
 * demo-workspace fixture.
 *
 * The boundary is what keeps this honest: a fallback is wrapped by
 * `asSample`, so whatever the UI renders from it is forced to carry the
 * SAMPLE badge. There is deliberately no code path here that produces
 * live-marked (`asLive`) content from anything other than an actual HTTP
 * response — no mock server, no invented "live" payload.
 *
 * Every function returns `MarkedData<T>` rather than `T`: the caller must
 * look at `source` (via `isLive`) before presenting the data, which is the
 * whole point of routing these stubs through lib/data-boundary.ts.
 */

/** A compiled world state, as `/v1/world/{id}` is expected to return it. */
export interface WorldStateDto {
  id: string;
  revision: number;
  entity_count: number;
  relation_count: number;
}

/** One recorded world change, as `/v1/world/changes` is expected to return. */
export interface WorldChangeDto {
  id: string;
  world_state_id: string;
  /** Human-readable summary of what moved; never a fabricated metric. */
  summary: string;
  /** ISO 8601 instant the change was activated at. */
  changed_at: string;
}

/** An answer with its guarantees and provenance trace, as ASK returns them. */
export interface WorldAnswerDto {
  question: string;
  answer: string;
  guarantees: readonly DemoGuarantee[];
  trace: readonly string[];
}

/**
 * The one instant the demo fixture's clock is pinned to (demo-workspace.ts
 * `EPOCH`). The sample change record below is stamped with it so
 * `listChanges(since)` filtering stays deterministic across replays.
 */
const FIXTURE_EPOCH_ISO = "2026-08-11T09:00:00.000Z";

const SAMPLE_WORLD_STATE: WorldStateDto = {
  id: DEMO_WORLD_STATE_ID,
  revision: 1,
  entity_count: DEMO_ENTITIES.length,
  relation_count: DEMO_RELATIONS.length,
};

const SAMPLE_CHANGE: WorldChangeDto = {
  id: DEMO_IMPACT.changeId,
  world_state_id: DEMO_WORLD_STATE_ID,
  summary: `Recompiled the warranty term source · ${DEMO_IMPACT.knowledgeUnitsAffected} knowledge units affected`,
  changed_at: FIXTURE_EPOCH_ISO,
};

/**
 * Fetch a compiled world state by id. Falls back to the sample workspace
 * fixture — badged SAMPLE — when the backend is unreachable or errors.
 */
export async function getWorld(
  worldId: string,
): Promise<MarkedData<WorldStateDto>> {
  try {
    const state = await apiRequest<WorldStateDto>(
      `/v1/world/${encodeURIComponent(worldId)}`,
    );
    return asLive(state);
  } catch {
    // The sample fallback only knows the fixture workspace; it reports the
    // fixture's own id rather than pretending the requested id resolved.
    return asSample(SAMPLE_WORLD_STATE);
  }
}

/**
 * List world changes activated after `since` (ISO 8601 cursor). Falls back to
 * the fixture's single recorded change when the backend is unavailable — and
 * to an empty list when the cursor is past it, exactly as the live endpoint
 * would behave for an up-to-date client.
 */
export async function listChanges(
  since: string,
): Promise<MarkedData<readonly WorldChangeDto[]>> {
  try {
    const changes = await apiRequest<readonly WorldChangeDto[]>(
      `/v1/world/changes?since=${encodeURIComponent(since)}`,
    );
    return asLive(changes);
  } catch {
    const cursor = Date.parse(since);
    const changes =
      Number.isNaN(cursor) || cursor < Date.parse(FIXTURE_EPOCH_ISO)
        ? [SAMPLE_CHANGE]
        : [];
    return asSample(changes);
  }
}

/**
 * Ask the world a question. The backend answering service is not wired yet,
 * so this falls back to the fixture exchange (the warranty question's answer,
 * guarantees, and provenance trace) under the SAMPLE badge.
 */
export async function ask(query: string): Promise<MarkedData<WorldAnswerDto>> {
  try {
    const answer = await apiRequest<WorldAnswerDto>("/v1/world/ask", {
      method: "POST",
      idempotencyKey: crypto.randomUUID(),
      body: JSON.stringify({ query }),
    });
    return asLive(answer);
  } catch {
    return asSample({
      question: query,
      answer: DEMO_ANSWER,
      guarantees: DEMO_GUARANTEES,
      trace: DEMO_TRACE,
    });
  }
}
