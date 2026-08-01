import { apiRequest } from "@/lib/api-client";
import {
  buildIntakeManifest,
  COLLECTION_MAX_BYTES,
  COLLECTION_MAX_FILES,
} from "@/lib/collection-intake";
import {
  adaptiveTransferConcurrency,
  browserQuickFingerprint,
  browserSha256,
  mapWithAdaptiveConcurrency,
  uploadSourceFile,
  weightedFairFileOrder,
} from "@/lib/upload-client";
import {
  collectionRetryPointerKey,
  loadCollectionResumeRecord,
  saveCollectionFileHandles,
  saveCollectionResumeRecord,
  type CollectionFileHandleRecord,
  type CollectionResumeRecord,
} from "@/lib/collection-storage";

type CollectionControlRow = {
  id: string;
  status: string;
  manifest_revision: number;
};

type SourceRootRow = {
  id: string;
  collection_id: string;
  source_type: "local" | "google_drive" | "onedrive";
};

export type CollectionUploadSummary = {
  upload_session_id: string;
  manifest_revision: number;
  resume_version: number;
  status: "planned" | "uploading" | "completed" | "partial" | "expired" | "aborted";
  total_files: number;
  total_bytes: number;
  completed_files: number;
  active_files: number;
  failed_files: number;
  duplicate_files: number;
  source_manifest_hash: string;
  expires_at: string;
};

export type CollectionFilePlanResult = {
  id: string;
  source_root_id: string;
  source_file_id: string | null;
  relative_path: string;
  display_name: string;
  size_bytes: number;
  expected_mime: string;
  sha256: string;
  status: string;
  error_code: string | null;
  upload_required: boolean;
  upload_endpoint: string | null;
};

type CollectionFilesPlanResponse = {
  collection: CollectionControlRow;
  upload: CollectionUploadSummary;
  browser_resume_token: string;
  files: CollectionFilePlanResult[];
  limitations: string[];
};

type CollectionUploadStatusResponse = {
  collection: CollectionControlRow;
  upload: CollectionUploadSummary;
  files: CollectionFilePlanResult[];
  offset: number;
  limit: number;
  next_offset: number | null;
};

type CollectionUploadCompleteResponse = {
  collection: CollectionControlRow;
  upload: CollectionUploadSummary;
  accepted_receipts: number;
  duplicate_reuses: number;
  unresolved_files: number;
};

export type CollectionPreflightEstimate = {
  status: "fast_ready" | "sampled_ready" | "incomplete";
  basis: string;
  p50_credits: string | number | null;
  p95_credits: string | number | null;
  duration_p50_seconds: number | null;
  duration_p95_seconds: number | null;
  route_mix: Record<string, number>;
  reserve_ceiling: string | number | null;
  confidence: string | number;
  confidence_band: "low" | "medium" | "high";
  known_pages: number;
  sampled_pages: number;
  billable_pages: number;
  duplicate_pages: number;
  unbillable_pages: number;
  unestimated_files: number;
  predictor_revision: string;
  estimate_sha256: string;
  calibration_required: boolean;
  knowledge_blueprint_id: string;
  knowledge_blueprint_registry_sha256: string;
  knowledge_blueprint_module_sha256: string;
  knowledge_blueprint_candidates: Array<{
    id: string;
    module_sha256: string;
  }>;
  knowledge_blueprint_rationale_codes: string[];
  output_modules: Array<
    | "source_index"
    | "document_catalog"
    | "knowledge_notes"
    | "entities"
    | "relations"
    | "integrity"
    | "export_manifest"
  >;
  warnings: string[];
};

export type CollectionPreflightResult = {
  id: string;
  status: "complete" | "partial";
  input_manifest_hash: string;
  output_sha256: string;
  limitations: string[];
  estimate: CollectionPreflightEstimate;
};

export type ConnectedCollectionResult = {
  collectionId: string;
  sourceRootId: string;
  upload: CollectionUploadSummary;
  plannedFiles: CollectionFilePlanResult[];
  limitations: string[];
  browserResumeToken?: string | null;
  preflight?: CollectionPreflightResult;
  blocker?: {
    code:
      | "SOURCE_UPLOAD_INTERRUPTED"
      | "COLLECTION_RECEIPT_BINDING_INTERRUPTED"
      | "COLLECTION_UPLOAD_INCOMPLETE"
      | "NO_VERIFIED_FILES_FOR_PREFLIGHT"
      | "PREFLIGHT_NOT_READY";
    requiredFiles: number;
    message: string;
  };
};

export type CollectionPreparationProgress = {
  stage: "hashing" | "planning" | "uploading" | "verifying" | "preflight";
  completedFiles: number;
  totalFiles: number;
  currentFile?: string;
  resumed?: boolean;
};

export class CollectionPreparationError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
    this.name = "CollectionPreparationError";
  }
}

export async function prepareConnectedCollection(input: {
  projectId: string;
  name: string;
  files: readonly File[];
  hashBlob?: (blob: Blob, signal?: AbortSignal) => Promise<string>;
  fileHandles?: readonly CollectionFileHandleRecord[];
  signal?: AbortSignal;
  onSession?: (session: {
    collectionId: string;
    sourceRootId: string;
    browserResumeToken?: string | null;
  }) => void;
  resume?: Pick<CollectionResumeRecord, "collectionId" | "sourceRootId"> & {
    limitations?: string[];
    browserResumeToken?: string | null;
  };
  onProgress?: (progress: CollectionPreparationProgress) => void;
}): Promise<ConnectedCollectionResult> {
  input.signal?.throwIfAborted();
  const projectId = input.projectId.trim();
  const name = input.name.trim();
  if (!projectId) {
    throw new CollectionPreparationError(
      "Select a project before creating the collection.",
      "PROJECT_REQUIRED",
    );
  }
  if (!name) {
    throw new CollectionPreparationError(
      "Enter a collection name.",
      "COLLECTION_NAME_REQUIRED",
    );
  }

  const manifest = buildIntakeManifest(input.files);
  if (manifest.rejected.length > 0) {
    throw new CollectionPreparationError(
      "Remove files with unsafe relative paths before connecting the manifest.",
      "UNSAFE_RELATIVE_PATH",
    );
  }
  if (manifest.accepted.length === 0) {
    throw new CollectionPreparationError(
      "Add at least one safe file before creating the collection.",
      "COLLECTION_FILES_REQUIRED",
    );
  }
  if (manifest.accepted.length > COLLECTION_MAX_FILES) {
    throw new CollectionPreparationError(
      "The collection exceeds the 5,000-file control-plane limit.",
      "COLLECTION_FILE_LIMIT_EXCEEDED",
    );
  }
  if (manifest.totalBytes > COLLECTION_MAX_BYTES) {
    throw new CollectionPreparationError(
      "The collection exceeds the 10 GiB control-plane limit.",
      "COLLECTION_BYTE_LIMIT_EXCEEDED",
    );
  }
  const pathKeys = manifest.accepted.map((entry) =>
    entry.relativePath.toLowerCase(),
  );
  if (new Set(pathKeys).size !== pathKeys.length) {
    throw new CollectionPreparationError(
      "Two files resolve to the same case-insensitive relative path.",
      "COLLECTION_PATH_COLLISION",
    );
  }

  const hashBlob =
    input.hashBlob ??
    ((blob: Blob, signal?: AbortSignal) =>
      browserSha256(blob, 8 * 1024 * 1024, signal));
  input.onProgress?.({
    stage: "hashing",
    completedFiles: 0,
    totalFiles: manifest.accepted.length,
  });
  let hashedCount = 0;
  const hashedFiles = (
    await mapWithAdaptiveConcurrency(manifest.accepted, async (entry) => {
      const [sha256, quickFingerprint] = await Promise.all([
        hashBlob(entry.file, input.signal),
        browserQuickFingerprint(entry.file, input.signal),
      ]);
      input.signal?.throwIfAborted();
      hashedCount += 1;
      input.onProgress?.({
        stage: "hashing",
        completedFiles: hashedCount,
        totalFiles: manifest.accepted.length,
        currentFile: entry.relativePath,
      });
      return {
        entry,
        sha256,
        quickFingerprint,
      };
    }, { kind: "file", signal: input.signal })
  ).sort((left, right) =>
    left.entry.relativePath.localeCompare(right.entry.relativePath),
  );
  for (const item of hashedFiles) {
    assertSha256(item.sha256);
    assertQuickFingerprint(item.quickFingerprint);
  }
  const sourceFingerprint = await hashBlob(
    new Blob([
      JSON.stringify(
        hashedFiles.map(({ entry, sha256 }) => ({
          relative_path: entry.relativePath,
          sha256,
          size_bytes: entry.file.size,
        })),
      ),
    ]),
    input.signal,
  );
  assertSha256(sourceFingerprint);

  input.onProgress?.({
    stage: "planning",
    completedFiles: 0,
    totalFiles: hashedFiles.length,
  });
  const resumeKey = collectionRetryPointerKey(projectId, sourceFingerprint);
  const storedResume = await loadCollectionResumeRecord(resumeKey);
  const resume: CollectionResumeRecord | undefined = input.resume
    ? {
        collectionId: input.resume.collectionId,
        sourceRootId: input.resume.sourceRootId,
        projectId,
        sourceFingerprint,
        limitations:
          input.resume.limitations ?? storedResume?.limitations ?? [],
        pendingReceipts: storedResume?.pendingReceipts ?? [],
        browserResumeToken:
          input.resume.browserResumeToken ?? storedResume?.browserResumeToken,
        updatedAt: storedResume?.updatedAt ?? new Date().toISOString(),
      }
    : storedResume;
  let collectionId: string;
  let sourceRootId: string;
  let plannedFiles: CollectionFilePlanResult[];
  let limitations: string[];
  let resumeRecord: CollectionResumeRecord;
  let browserResumeToken: string | null | undefined;
  if (resume) {
    const status = await fetchCollectionUpload(resume.collectionId, input.signal);
    assertMatchingManifest(status.files, hashedFiles);
    collectionId = resume.collectionId;
    sourceRootId = resume.sourceRootId;
    plannedFiles = status.files;
    limitations =
      "limitations" in resume && Array.isArray(resume.limitations)
        ? resume.limitations
        : [];
    resumeRecord = resume;
    browserResumeToken = resume.browserResumeToken;
    input.onSession?.({ collectionId, sourceRootId, browserResumeToken });
    input.onProgress?.({
      stage: "planning",
      completedFiles: plannedFiles.length,
      totalFiles: plannedFiles.length,
      resumed: true,
    });
  } else {
    const collection = await apiRequest<CollectionControlRow>(
      "/v1/collections",
      {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({
          project_id: projectId,
          name,
          description:
            "Collection created from the Structara folder intake surface.",
          profile: { source: "web_collection_intake_v1" },
        }),
        signal: input.signal,
      },
    );
    const sourceRoot = await apiRequest<SourceRootRow>(
      `/v1/collections/${collection.id}/sources/local`,
      {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({
          display_name: name,
          source_fingerprint: sourceFingerprint,
        }),
        signal: input.signal,
      },
    );
    const planned = await apiRequest<CollectionFilesPlanResponse>(
      `/v1/collections/${collection.id}/files/plan`,
      {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({
          source_root_id: sourceRoot.id,
          files: hashedFiles.map(({ entry, sha256, quickFingerprint }) => ({
            relative_path: entry.relativePath,
            display_name: entry.file.name,
            size_bytes: entry.file.size,
            last_modified_ms: entry.file.lastModified || null,
            expected_mime: entry.file.type || "application/octet-stream",
            sha256,
            quick_fingerprint: quickFingerprint,
          })),
        }),
        signal: input.signal,
      },
    );
    collectionId = collection.id;
    sourceRootId = sourceRoot.id;
    plannedFiles = planned.files;
    limitations = planned.limitations;
    browserResumeToken = planned.browser_resume_token;
    resumeRecord = {
      collectionId,
      sourceRootId,
      projectId,
      sourceFingerprint,
      limitations,
      pendingReceipts: [],
      browserResumeToken,
      updatedAt: new Date().toISOString(),
    };
    await saveCollectionResumeRecord(resumeKey, resumeRecord);
    input.onSession?.({ collectionId, sourceRootId, browserResumeToken });
    input.onProgress?.({
      stage: "planning",
      completedFiles: plannedFiles.length,
      totalFiles: plannedFiles.length,
    });
  }

  const sessionId = await saveCollectionResumeRecord(resumeKey, resumeRecord);
  if (input.fileHandles?.length) {
    await saveCollectionFileHandles(sessionId, input.fileHandles);
  }

  const resumableReceipts = resumeRecord.pendingReceipts.filter((receipt) =>
    plannedFiles.some(
      (file) => file.id === receipt.fileId && file.upload_required,
    ),
  );
  if (resumableReceipts.length > 0) {
    try {
      await apiRequest<CollectionUploadCompleteResponse>(
        `/v1/collections/${collectionId}/upload/complete`,
        {
          method: "POST",
          idempotencyKey: crypto.randomUUID(),
          body: JSON.stringify({
            receipts: resumableReceipts.map((receipt) => ({
              file_id: receipt.fileId,
              outcome: "completed",
              source_file_id: receipt.sourceFileId,
            })),
          }),
          signal: input.signal,
        },
      );
      const reboundIds = new Set(
        resumableReceipts.map((receipt) => receipt.fileId),
      );
      resumeRecord.pendingReceipts = resumeRecord.pendingReceipts.filter(
        (receipt) => !reboundIds.has(receipt.fileId),
      );
      await saveCollectionResumeRecord(resumeKey, resumeRecord);
      const reboundStatus = await fetchCollectionUpload(collectionId, input.signal);
      assertMatchingManifest(reboundStatus.files, hashedFiles);
      plannedFiles = reboundStatus.files;
    } catch (error) {
      const status = await fetchCollectionUpload(collectionId, input.signal);
      return {
        collectionId,
        sourceRootId,
        upload: status.upload,
        plannedFiles: status.files,
        limitations,
        browserResumeToken,
        blocker: {
          code: "COLLECTION_RECEIPT_BINDING_INTERRUPTED",
          requiredFiles: status.upload.active_files,
          message: `A verified source receipt is saved for resume, but it could not be bound to the collection: ${errorMessage(error)} Retry with the same files; no preflight or processing job was requested.`,
        },
      };
    }
  } else if (resumeRecord.pendingReceipts.length > 0) {
    resumeRecord.pendingReceipts = [];
    await saveCollectionResumeRecord(resumeKey, resumeRecord);
  }

  const byPath = new Map(
    hashedFiles.map((item) => [item.entry.relativePath, item]),
  );
  const pending = weightedFairFileOrder(
    plannedFiles
      .filter((file) => file.upload_required)
      .map((value) => ({ value, size: value.size_bytes })),
  ).map(({ value }) => value);
  let uploadedFiles = 0;
  for (let offset = 0; offset < pending.length; ) {
    let concurrency = adaptiveTransferConcurrency("file");
    while (concurrency === 0) {
      await waitForDocumentVisibility(input.signal);
      concurrency = adaptiveTransferConcurrency("file");
    }
    const batch = pending.slice(offset, offset + concurrency);
    offset += batch.length;
    input.onProgress?.({
      stage: "uploading",
      completedFiles: uploadedFiles,
      totalFiles: pending.length,
      currentFile: batch[0]?.relative_path,
      resumed: Boolean(resume),
    });
    const transfers = await Promise.allSettled(
      batch.map(async (plannedFile) => {
        const local = byPath.get(plannedFile.relative_path);
        if (
          !local ||
          local.sha256.toLowerCase() !== plannedFile.sha256.toLowerCase() ||
          local.entry.file.size !== plannedFile.size_bytes
        ) {
          throw new CollectionPreparationError(
            "The local file no longer matches the immutable collection plan.",
            "COLLECTION_MANIFEST_MISMATCH",
          );
        }
        const source = await uploadSourceFile(local.entry.file, projectId, local.sha256, {
          signal: input.signal,
        });
        return {
          file_id: plannedFile.id,
          outcome: "completed" as const,
          source_file_id: source.sourceFileId,
        };
      }),
    );
    const receipts = transfers.flatMap((transfer) =>
      transfer.status === "fulfilled" ? [transfer.value] : [],
    );
    if (receipts.length > 0) {
      const receiptIds = new Set(receipts.map((receipt) => receipt.file_id));
      const persistedByFile = new Map(
        resumeRecord.pendingReceipts.map((receipt) => [
          receipt.fileId,
          receipt,
        ]),
      );
      for (const receipt of receipts) {
        persistedByFile.set(receipt.file_id, {
          fileId: receipt.file_id,
          sourceFileId: receipt.source_file_id,
        });
      }
      resumeRecord.pendingReceipts = [...persistedByFile.values()];
      await saveCollectionResumeRecord(resumeKey, resumeRecord);
      try {
        await apiRequest<CollectionUploadCompleteResponse>(
          `/v1/collections/${collectionId}/upload/complete`,
          {
            method: "POST",
            idempotencyKey: crypto.randomUUID(),
            body: JSON.stringify({ receipts }),
            signal: input.signal,
          },
        );
        uploadedFiles += receipts.length;
        resumeRecord.pendingReceipts = resumeRecord.pendingReceipts.filter(
          (receipt) => !receiptIds.has(receipt.fileId),
        );
        await saveCollectionResumeRecord(resumeKey, resumeRecord);
      } catch (error) {
        const status = await fetchCollectionUpload(collectionId, input.signal);
        return {
          collectionId,
          sourceRootId,
          upload: status.upload,
          plannedFiles: status.files,
          limitations,
          browserResumeToken,
          blocker: {
            code: "COLLECTION_RECEIPT_BINDING_INTERRUPTED",
            requiredFiles: status.upload.active_files,
            message: `The source transfer completed, but the verified receipt could not be bound to the collection: ${errorMessage(error)} Retry with the same files; no preflight or processing job was requested.`,
          },
        };
      }
    }
    const failed = transfers.find(
      (transfer): transfer is PromiseRejectedResult =>
        transfer.status === "rejected",
    );
    if (failed) {
      const status = await fetchCollectionUpload(collectionId, input.signal);
      return {
        collectionId,
        sourceRootId,
        upload: status.upload,
        plannedFiles: status.files,
        limitations,
        browserResumeToken,
        blocker: {
          code: "SOURCE_UPLOAD_INTERRUPTED",
          requiredFiles: status.upload.active_files,
          message: `${errorMessage(failed.reason)} Retry with the same files to resume this collection; no preflight or processing job was requested.`,
        },
      };
    }
    input.onProgress?.({
      stage: "uploading",
      completedFiles: uploadedFiles,
      totalFiles: pending.length,
      currentFile: batch.at(-1)?.relative_path,
      resumed: Boolean(resume),
    });
  }

  input.onProgress?.({
    stage: "verifying",
    completedFiles: uploadedFiles,
    totalFiles: pending.length,
    resumed: Boolean(resume),
  });
  const status = await fetchCollectionUpload(collectionId, input.signal);
  const base = {
    collectionId,
    sourceRootId,
    upload: status.upload,
    plannedFiles: status.files,
    limitations,
    browserResumeToken,
  };
  if (status.upload.active_files > 0) {
    return {
      ...base,
      blocker: {
        code: "COLLECTION_UPLOAD_INCOMPLETE",
        requiredFiles: status.upload.active_files,
        message:
          "The server still reports source files awaiting a verified receipt. Retry with the same files to resume this collection; no preflight or processing job was requested.",
      },
    };
  }
  if (status.upload.completed_files === 0) {
    return {
      ...base,
      blocker: {
        code: "NO_VERIFIED_FILES_FOR_PREFLIGHT",
        requiredFiles: 0,
        message:
          "The server accepted the manifest metadata but no verified source file is available for preflight. No processing job was requested.",
      },
    };
  }

  input.onProgress?.({
    stage: "preflight",
    completedFiles: status.upload.completed_files,
    totalFiles: status.upload.total_files,
    resumed: Boolean(resume),
  });
  let preflight: CollectionPreflightResult;
  try {
    preflight = await apiRequest<CollectionPreflightResult>(
      `/v1/collections/${collectionId}/preflight`,
      {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        signal: input.signal,
      },
    );
  } catch (error) {
    return {
      ...base,
      blocker: {
        code: "PREFLIGHT_NOT_READY",
        requiredFiles: 0,
        message: `Verified sources are bound, but repository preflight did not complete: ${errorMessage(error)} No processing job or credit reservation was requested.`,
      },
    };
  }
  resumeRecord.pendingReceipts = [];
  await saveCollectionResumeRecord(resumeKey, resumeRecord);
  return { ...base, preflight };
}

async function fetchCollectionUpload(
  collectionId: string,
  signal?: AbortSignal,
): Promise<CollectionUploadStatusResponse> {
  let offset = 0;
  const files: CollectionFilePlanResult[] = [];
  let first: CollectionUploadStatusResponse | undefined;
  do {
    const page = await apiRequest<CollectionUploadStatusResponse>(
      `/v1/collections/${collectionId}/upload?offset=${offset}&limit=500`,
      { signal },
    );
    first ??= page;
    files.push(...page.files);
    if (page.next_offset === null || page.next_offset === undefined) break;
    if (page.next_offset <= offset) {
      throw new CollectionPreparationError(
        "The collection upload cursor did not advance.",
        "COLLECTION_UPLOAD_CURSOR_INVALID",
      );
    }
    offset = page.next_offset;
  } while (files.length <= COLLECTION_MAX_FILES);
  if (!first || files.length > COLLECTION_MAX_FILES) {
    throw new CollectionPreparationError(
      "The collection upload status exceeded the supported manifest boundary.",
      "COLLECTION_UPLOAD_STATUS_INVALID",
    );
  }
  return { ...first, files, next_offset: null };
}

export async function controlCollectionUpload(
  collectionId: string,
  action: "pause" | "resume",
  browserResumeToken?: string | null,
): Promise<{
  collection: CollectionControlRow;
  upload: CollectionUploadSummary;
  browser_resume_token?: string | null;
}> {
  return apiRequest(`/v1/collections/${collectionId}/upload/control`, {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: JSON.stringify({
      action,
      ...(action === "resume" && browserResumeToken
        ? { browser_resume_token: browserResumeToken }
        : {}),
    }),
  });
}

function assertMatchingManifest(
  plannedFiles: readonly CollectionFilePlanResult[],
  hashedFiles: ReadonlyArray<{
    entry: { relativePath: string; file: File };
    sha256: string;
  }>,
): void {
  if (plannedFiles.length !== hashedFiles.length) {
    throw new CollectionPreparationError(
      "The selected files do not match the resumable collection manifest.",
      "COLLECTION_MANIFEST_MISMATCH",
    );
  }
  const byPath = new Map(
    hashedFiles.map((item) => [item.entry.relativePath, item]),
  );
  const mismatch = plannedFiles.some((planned) => {
    const local = byPath.get(planned.relative_path);
    return (
      !local ||
      local.entry.file.size !== planned.size_bytes ||
      local.sha256.toLowerCase() !== planned.sha256.toLowerCase()
    );
  });
  if (mismatch) {
    throw new CollectionPreparationError(
      "The selected files do not match the resumable collection manifest.",
      "COLLECTION_MANIFEST_MISMATCH",
    );
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "A source upload stopped before verification completed.";
}

function assertSha256(value: string): void {
  if (!/^[0-9a-f]{64}$/i.test(value)) {
    throw new CollectionPreparationError(
      "The local content hash is invalid.",
      "INVALID_LOCAL_SHA256",
    );
  }
}

function assertQuickFingerprint(value: string): void {
  if (!/^[0-9a-zA-Z:_-]{16,128}$/.test(value)) {
    throw new CollectionPreparationError(
      "The local quick-fingerprint candidate is invalid.",
      "INVALID_LOCAL_QUICK_FINGERPRINT",
    );
  }
}

function waitForDocumentVisibility(signal?: AbortSignal): Promise<void> {
  if (typeof document === "undefined" || document.visibilityState === "visible") {
    return Promise.resolve();
  }
  signal?.throwIfAborted();
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      document.removeEventListener("visibilitychange", onVisibility);
      signal?.removeEventListener("abort", onAbort);
    };
    const onVisibility = () => {
      if (document.visibilityState !== "visible") return;
      cleanup();
      resolve();
    };
    const onAbort = () => {
      cleanup();
      reject(
        signal?.reason instanceof Error
          ? signal.reason
          : new DOMException("Collection transfer was aborted.", "AbortError"),
      );
    };
    document.addEventListener("visibilitychange", onVisibility);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
