export type ProcessingMode = "speed" | "balanced" | "precision" | "private";

export type BlockOrigin =
  | "native_extracted"
  | "ocr_extracted"
  | "rule_reconstructed"
  | "ai_reconstructed"
  | "ai_summarized"
  | "ai_inferred"
  | "user_edited";

export type PageStatus =
  | "uploaded"
  | "security_scanning"
  | "security_verified"
  | "preflighting"
  | "preflighted"
  | "native_extracting"
  | "ocr_queued"
  | "ocr_running"
  | "normalizing"
  | "validating"
  | "completed"
  | "needs_review"
  | "retry_scheduled"
  | "failed";

export interface SourceRef {
  document_id: string;
  document_version_id: string;
  page_index: number;
  page_number: number;
  bbox1000?: [number, number, number, number];
  source_sha256?: string;
}

export interface CanonicalBlock {
  id: string;
  order: number;
  type:
    | "title"
    | "heading"
    | "paragraph"
    | "list"
    | "table"
    | "figure"
    | "caption"
    | "formula"
    | "code"
    | "quote"
    | "footnote"
    | "unknown";
  markdown: string;
  source_text: string;
  origin: BlockOrigin;
  content_layer: "extracted" | "structured" | "knowledge";
  source_refs: SourceRef[];
  confidence?: number;
  quality_flags: string[];
  revision: number;
}

export interface BlockModelMergeRequest {
  base_revision: number;
  new_model_markdown: string;
  model_revision: string;
  apply_non_conflicting: boolean;
}

export interface BlockModelMergeResponse {
  block_id: string;
  status:
    "unchanged" | "model_replaced" | "kept_user" | "auto_merged" | "conflict";
  base_revision: number;
  current_revision: number;
  applied: boolean;
  user_locked: boolean;
  base: string;
  user: string;
  new_model: string;
  merged: string | null;
  conflict_count: number;
  etag: string;
}

export type CanonicalBlockPatch = Pick<CanonicalBlock, "id"> &
  Partial<Omit<CanonicalBlock, "id">>;

export interface PageSummary {
  id: string;
  page_number: number;
  status: PageStatus;
  route_profile: string;
  route_label: "Native" | "OCR" | "Fast" | "Precision" | "Fallback";
  quality_state: "verified" | "warning" | "review" | "failed";
  attempt?: {
    id: string;
    number: number;
    status: PageStatus;
    route: string;
    route_profile: string;
    quality: Record<string, unknown>;
    escalation: Record<string, unknown>;
  } | null;
  thumbnail_url?: string;
  blocks: CanonicalBlock[];
}

export type JobEventType =
  | "job.created.v1"
  | "job.stage.started.v1"
  | "job.stage.progress.v1"
  | "job.stage.completed.v1"
  | "page.preflight.completed.v1"
  | "page.route.selected.v1"
  | "page.processing.started.v1"
  | "page.layout.detected.v1"
  | "page.block.completed.v1"
  | "page.markdown.updated.v1"
  | "page.quality.updated.v1"
  | "page.retry.scheduled.v1"
  | "page.completed.v1"
  | "page.needs_review.v1"
  | "page.failed.v1"
  | "document.knowledge.note_created.v1"
  | "document.knowledge.link_created.v1"
  | "document.validation.completed.v1"
  | "export.started.v1"
  | "export.completed.v1"
  | "job.completed.v1"
  | "job.failed.v1"
  | "credit.reserved.v1"
  | "credit.consumed.v1"
  | "credit.released.v1";

export interface JobEvent<T = unknown> {
  event_id: string;
  event_type: JobEventType;
  occurred_at: string;
  project_id: string;
  document_id?: string;
  job_id: string;
  page_id?: string;
  sequence: number;
  schema_version: "1.0";
  payload: T;
}

export interface LiveJobState {
  lastSequence: number;
  seenEventIds: string[];
  pendingEvents: Record<number, JobEvent>;
  needsReplay: boolean;
  gapFrom?: number;
  stageProgress: Record<string, { done: number; total: number }>;
  pageStatus: Record<string, PageStatus>;
  blockPatches: Record<string, CanonicalBlockPatch>;
  warnings: Record<string, ReviewItem>;
  connection: "idle" | "connecting" | "live" | "reconnecting" | "closed";
  terminalStatus?: "completed" | "failed" | "cancelled";
}

export interface ReviewItem {
  id: string;
  severity: "low" | "medium" | "high" | "critical";
  category: string;
  message: string;
  page_id?: string;
  block_id?: string;
  status: "open" | "resolved";
  candidates?: Array<{ engine: string; value: string }>;
}

export interface ReviewResolution {
  action: "accept" | "adopt_source" | "replace" | "reject";
  value?: string;
  note?: string;
}

export interface ReviewScopePreview {
  document_id: string;
  category: string;
  item_count: number;
  review_ids: string[];
  preview_sha256: string;
  allowed_actions: Array<"accept" | "adopt_source" | "reject">;
}

export interface ProjectSummary {
  id: string;
  name: string;
  description?: string;
  document_count: number;
  review_count: number;
  status: "draft" | "processing" | "ready" | "attention";
  updated_at: string;
}

export interface PreflightEstimate {
  total_pages: number;
  native_pages: number;
  visual_pages: number;
  precision_candidate_pages: number;
  tables: number;
  formulas: number;
  figures: number;
  credit_min: number;
  credit_max: number;
  third_party_model_api: boolean;
  expected_duration_min: number;
  expected_duration_max: number;
}
