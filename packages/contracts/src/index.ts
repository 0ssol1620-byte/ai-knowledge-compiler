/** Canonical JSON wire contracts. Runtime validation remains mandatory. */

export * from "./generated-contracts.js";

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  JsonPrimitive | JsonValue[] | { readonly [key: string]: JsonValue };

export const BLOCK_ORIGINS = [
  "native_extracted",
  "ocr_extracted",
  "rule_reconstructed",
  "ai_reconstructed",
  "ai_summarized",
  "ai_inferred",
  "user_edited",
] as const;
export type BlockOrigin = (typeof BLOCK_ORIGINS)[number];

export const CONTENT_LAYERS = [
  "source",
  "extracted",
  "structured",
  "knowledge",
  "index",
] as const;
export type ContentLayer = (typeof CONTENT_LAYERS)[number];

export const BLOCK_TYPES = [
  "title",
  "heading",
  "paragraph",
  "list",
  "table",
  "figure",
  "caption",
  "formula",
  "code",
  "quote",
  "footnote",
  "header",
  "footer",
  "page_number",
  "unknown",
] as const;
export type BlockType = (typeof BLOCK_TYPES)[number];

/** [x1,y1,x2,y2], integer normalized to 0..1000 with positive area. */
export type BBox1000 = readonly [number, number, number, number];

export interface SourceRef {
  readonly documentId: string;
  readonly documentVersionId: string;
  readonly pageIndex0: number;
  readonly pageNumber1: number;
  readonly bbox1000?: BBox1000;
  readonly nativeObjectId?: string;
  readonly imageAssetId?: string;
  readonly timeStartMs?: number;
  readonly timeEndMs?: number;
}

export interface CanonicalCell {
  readonly id: string;
  readonly rowIndex0: number;
  readonly columnIndex0: number;
  readonly rowSpan: number;
  readonly columnSpan: number;
  readonly rawText: string;
  readonly normalizedText: string;
  readonly origin: BlockOrigin;
  readonly sourceRefs: readonly SourceRef[];
  readonly confidence?: number;
  readonly qualityFlags: readonly string[];
}

export interface CanonicalTable {
  readonly id: string;
  readonly rowCount: number;
  readonly columnCount: number;
  readonly headerRowCount: number;
  readonly cells: readonly CanonicalCell[];
  readonly caption?: string;
  readonly sourceRefs: readonly SourceRef[];
  readonly qualityFlags: readonly string[];
}

export interface CanonicalBlock {
  readonly id: string;
  readonly parentId?: string;
  readonly order: number;
  readonly type: BlockType;
  readonly contentLayer: ContentLayer;
  readonly rawText?: string;
  readonly normalizedText?: string;
  readonly markdown?: string;
  readonly sanitizedHtml?: string;
  readonly table?: CanonicalTable;
  readonly formulaLatex?: string;
  readonly origin: BlockOrigin;
  readonly sourceRefs: readonly SourceRef[];
  readonly modelRunIds: readonly string[];
  readonly confidence?: number;
  readonly qualityFlags: readonly string[];
  readonly contentHash: `sha256:${string}`;
  readonly revision: number;
}

export interface ModelRunRecord {
  readonly id: string;
  readonly provider: string;
  readonly model: string;
  readonly revision: string;
  readonly runtime: string;
  readonly runtimeVersion: string;
  readonly promptSha256: `sha256:${string}`;
  readonly quantization?: string;
  readonly hardware: string;
  readonly containerDigest: string;
  readonly routeProfile: string;
  readonly startedAt: string;
  readonly completedAt?: string;
}

export interface CanonicalDocument {
  readonly schemaVersion: "cir-1.0.0";
  readonly tenantId: string;
  readonly documentId: string;
  readonly documentVersionId: string;
  readonly title: string;
  readonly sourceFilename: string;
  readonly sourceSha256: `sha256:${string}`;
  readonly contentLayer: ContentLayer;
  readonly blocks: readonly CanonicalBlock[];
  readonly modelRuns: readonly ModelRunRecord[];
  readonly metadata: Readonly<Record<string, JsonValue>>;
  readonly createdAt: string;
}

export const PAGE_STATES = [
  "UPLOADED",
  "SECURITY_SCANNING",
  "SECURITY_VERIFIED",
  "PREFLIGHTING",
  "PREFLIGHTED",
  "NATIVE_EXTRACTING",
  "OCR_QUEUED",
  "OCR_RUNNING",
  "NORMALIZING",
  "VALIDATING",
  "COMPLETED",
  "UNRESOLVED",
  "QUARANTINED",
  "NEEDS_REVIEW",
  "RETRY_SCHEDULED",
  "FAILED",
] as const;
export type PageState = (typeof PAGE_STATES)[number];

export type ProcessingStage =
  | "upload"
  | "security_scan"
  | "preflight"
  | "extract"
  | "normalize"
  | "knowledge"
  | "validate"
  | "package";

export type EventType =
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
  | "page.unresolved.v1"
  | "page.quarantined.v1"
  | "page.needs_review.v1"
  | "page.failed.v1"
  | "document.knowledge.note_created.v1"
  | "document.knowledge.link_created.v1"
  | "document.validation.completed.v1"
  | "export.started.v1"
  | "export.completed.v1"
  | "job.completed.v1"
  | "job.failed.v1"
  | "job.cancelled.v1"
  | "credit.reserved.v1"
  | "credit.consumed.v1"
  | "credit.released.v1";

export interface ProcessingEvent {
  readonly schema_version: "1.0";
  readonly event_id: string;
  readonly event_type: EventType;
  readonly sequence: number;
  readonly occurred_at: string;
  readonly project_id: string;
  readonly job_id: string;
  readonly tenant_id?: string;
  readonly document_id?: string;
  readonly document_version_id?: string;
  readonly page_id?: string;
  readonly payload: Readonly<Record<string, JsonValue>>;
}

export type Route =
  | "native"
  | "paddle_vl"
  | "paddle_fast"
  | "hpd_fast"
  | "unlimited_long"
  | "mistral_fallback"
  | "region_recovery"
  | "authority_reconstruction"
  | "unresolved"
  | "quarantine";

export type RouteProfile =
  | "parse_fast_v1"
  | "parse_balanced_v1"
  | "parse_precision_v1"
  | "parse_long_v1"
  | "parse_private_v1";

export type ProcessingMode =
  "speed" | "balanced" | "precision" | "private" | "long_form_beta";
export type RiskTier = "normal" | "high";

export interface FeatureFlags {
  readonly hpdEnabled: boolean;
  readonly paddleFastEnabled: boolean;
  readonly unlimitedLongEnabled: boolean;
  readonly externalFallbackEnabled: boolean;
  readonly regionRecoveryEnabled: boolean;
  readonly authorityVerificationEnabled: boolean;
  readonly differentialVerificationEnabled: boolean;
}

export interface DataPolicy {
  readonly externalApiAllowed: boolean;
  readonly retentionDays: number;
  readonly regionalRestriction?: string;
  readonly privateProcessing: boolean;
}

export interface PageMetrics {
  readonly pageIndex0: number;
  readonly width: number;
  readonly height: number;
  readonly nativeTextChars: number;
  readonly nativeWordCount: number;
  readonly nativeBlockCount: number;
  readonly nativeTextCoverage: number;
  readonly imageCoverage: number;
  readonly invalidUnicodeRatio: number;
  readonly replacementCharRatio: number;
  readonly whitespaceAnomalyScore: number;
  readonly nativeReadingOrderScore: number;
  readonly fontSizeP10?: number;
  readonly estimatedColumns: number;
  readonly tableDensity: number;
  readonly formulaDensity: number;
  readonly chartProbability: number;
  readonly handwritingProbability: number;
  readonly rotationDegrees: 0 | 90 | 180 | 270;
  readonly skewDegrees: number;
  readonly blurScore: number;
  readonly contrastScore: number;
  readonly smallTextScore: number;
  readonly scriptDistribution: Readonly<Record<string, number>>;
  readonly suspectedPromptInjection: boolean;
}

export interface RouteDecision {
  readonly route: Route;
  readonly routeProfile: RouteProfile;
  readonly reasonCodes: readonly string[];
  readonly expectedCredits: number;
  readonly requiresVisualParse: boolean;
  readonly requireCrossCheck: boolean;
  readonly maxAttempts: number;
  readonly policyVersion: string;
  readonly providerOptions: Readonly<Record<string, JsonValue>>;
}

export type EscalationAction =
  "accept" | "retry" | "escalate" | "review" | "fail" | "discard_challenger";

export interface EscalationDecision {
  readonly action: EscalationAction;
  readonly route?: Route;
  readonly reasonCodes: readonly string[];
  readonly attemptNumber: number;
  readonly policyVersion: string;
}

export type ErrorCode =
  | "INVALID_REQUEST"
  | "UNSUPPORTED_FILE_TYPE"
  | "FILE_SIGNATURE_MISMATCH"
  | "FILE_TOO_LARGE"
  | "FILE_MALICIOUS"
  | "ARCHIVE_UNSAFE"
  | "PASSWORD_REQUIRED"
  | "INVALID_PASSWORD"
  | "QUOTA_EXCEEDED"
  | "URL_BLOCKED"
  | "ROUTE_UNAVAILABLE"
  | "PROVIDER_TIMEOUT"
  | "PROVIDER_INVALID_OUTPUT"
  | "QUALITY_REVIEW_REQUIRED"
  | "INTERNAL_ERROR";

export interface ErrorEnvelope {
  readonly schemaVersion: "error-1.0.0";
  readonly code: ErrorCode;
  readonly message: string;
  readonly retryable: boolean;
  readonly traceId: string;
  readonly details: Readonly<Record<string, JsonValue>>;
}

export interface Claim {
  readonly text: string;
  readonly origin: BlockOrigin;
  readonly sourceBlockIds: readonly string[];
  readonly confidence: number;
}

export interface KnowledgeNote {
  readonly noteId: string;
  readonly title: string;
  readonly noteType:
    | "concept"
    | "document"
    | "person"
    | "organization"
    | "project"
    | "glossary"
    | "question"
    | "moc";
  readonly contentOrigin: BlockOrigin;
  readonly evidenceBlockIds: readonly string[];
  readonly summary?: string;
  readonly claims: readonly Claim[];
  readonly aliases: readonly string[];
  readonly tags: readonly string[];
  readonly relatedNoteCandidates: readonly {
    readonly targetId: string;
    readonly relation: string;
    readonly reason: string;
    readonly sourceBlockIds: readonly string[];
    readonly confidence: number;
  }[];
  readonly reviewStatus:
    "pending" | "auto_with_warnings" | "user_verified" | "rejected";
}

export interface RelationAssertion {
  readonly id: string;
  readonly subject: string;
  readonly predicate: string;
  readonly object: string;
  readonly assertionStatus:
    "extracted" | "ai_summarized" | "ai_inferred" | "user_verified";
  readonly confidence: number;
  readonly evidenceBlockIds: readonly string[];
  readonly reviewStatus:
    "pending" | "auto_with_warnings" | "user_verified" | "rejected";
}

export interface KnowledgeBundle {
  readonly schemaVersion: "knowledge-1.0.0";
  readonly documentId: string;
  readonly notes: readonly KnowledgeNote[];
  readonly relations: readonly RelationAssertion[];
  readonly conflicts: readonly JsonValue[];
}

export interface MarkdownRange {
  readonly startLine1: number;
  readonly endLine1: number;
  readonly startCodepoint0: number;
  readonly endCodepoint0: number;
  readonly offsetEncoding: "unicode_code_points";
}

export interface SourceMapEntry {
  readonly blockId: string;
  readonly revision: number;
  readonly contentHash: `sha256:${string}`;
  readonly markdownPath: string;
  readonly markdownRange: MarkdownRange;
  readonly sourceRefs: readonly SourceRef[];
  readonly origin: BlockOrigin;
  readonly confidence?: number;
}

export interface SourceMap {
  readonly schemaVersion: "source-map-1.0.0";
  readonly documentId: string;
  readonly documentVersionId: string;
  readonly sourceSha256: `sha256:${string}`;
  readonly entries: readonly SourceMapEntry[];
}

export interface RagChunk {
  readonly schemaVersion: "rag-chunk-1.0.0";
  readonly chunkId: string;
  readonly documentId: string;
  readonly documentVersion: string;
  readonly title: string;
  readonly headingPath: readonly string[];
  readonly content: string;
  readonly contentType: string;
  readonly language: string;
  readonly tokenCount: number;
  readonly tokenizer: string;
  readonly sourceRefs: readonly SourceRef[];
  readonly origin: BlockOrigin;
  readonly contentLayer: ContentLayer;
  readonly quality?: number;
  readonly previousChunkId?: string;
  readonly nextChunkId?: string;
  readonly contentHash: `sha256:${string}`;
}

export interface QualityVector {
  readonly textFidelity: number | null;
  readonly numericFidelity: number | null;
  readonly layoutFidelity: number | null;
  readonly tableFidelity: number | null;
  readonly hierarchyValidity: number | null;
  readonly provenanceCoverage: number | null;
  readonly repetitionSafety: number | null;
  readonly languageConsistency: number | null;
  readonly markdownValidity: number | null;
}

export type QualityStatus =
  "PASS" | "PASS_WITH_WARNINGS" | "ESCALATE" | "REVIEW_REQUIRED" | "FAIL";

export interface ExportManifest {
  readonly schemaVersion: "export-manifest-1.0.0";
  readonly exportId: string;
  readonly tenantId: string;
  readonly projectId: string;
  readonly documentId: string;
  readonly documentVersionId: string;
  readonly profile:
    | "bundle"
    | "portable_raw"
    | "portable_structured"
    | "obsidian"
    | "rag"
    | "json_ld";
  readonly sourceSha256: `sha256:${string}`;
  readonly generatedAt: string;
  readonly modelProvenance: Readonly<Record<string, JsonValue>>;
  readonly files: readonly {
    readonly path: string;
    readonly mediaType: string;
    readonly sha256: `sha256:${string}`;
    readonly sizeBytes: number;
  }[];
  readonly warnings: readonly string[];
}

export function assertBBox1000(
  value: readonly number[],
): asserts value is BBox1000 {
  if (
    value.length !== 4 ||
    value.some(
      (coordinate) =>
        !Number.isInteger(coordinate) || coordinate < 0 || coordinate > 1000,
    ) ||
    value[0] === undefined ||
    value[1] === undefined ||
    value[2] === undefined ||
    value[3] === undefined ||
    value[0] >= value[2] ||
    value[1] >= value[3]
  ) {
    throw new TypeError(
      "bbox1000 must be four ordered 0..1000 integers with positive area",
    );
  }
}

export function assertPagePair(pageIndex0: number, pageNumber1: number): void {
  if (
    !Number.isInteger(pageIndex0) ||
    pageIndex0 < 0 ||
    pageNumber1 !== pageIndex0 + 1
  ) {
    throw new TypeError("pageNumber1 must equal pageIndex0 + 1");
  }
}
