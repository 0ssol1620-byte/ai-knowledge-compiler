import { browserQuickFingerprint, browserSha256 } from "@/lib/browser-hash";
import { MultipartTransferError } from "@/lib/transfer-errors";
import {
  analyzeDocument,
  apiAbsoluteUrl,
  ApiError,
  apiRequest,
} from "@/lib/api-client";
import type { PreflightEstimate } from "@/lib/types";

interface MultipartUploadPlan {
  part_size: number;
  part_count: number;
  presign_batch_size: number;
  max_concurrency: number;
  max_retries: number;
  sign_parts_url: string;
  list_parts_url: string;
}

interface UploadInitiation {
  upload_id: string;
  document_id: string;
  method: "PUT" | "MULTIPART";
  upload_url?: string | null;
  headers?: Record<string, string>;
  multipart?: MultipartUploadPlan | null;
  expires_at: string;
}

interface UploadSessionStatus {
  upload_id: string;
  document_id: string;
  project_id: string;
  method: "PUT" | "MULTIPART";
  status: string;
  expected_size: number;
  expected_content_type: string;
  expected_sha256: string;
  expires_at: string;
  multipart?: MultipartUploadPlan | null;
}

interface PartTarget {
  part_number: number;
  upload_url: string;
  headers?: Record<string, string>;
  expires_at: string;
}

export interface CompletedUploadPart {
  part_number: number;
  etag: string;
}

interface UploadedPart extends CompletedUploadPart {
  size: number;
}

interface ResumeRecord {
  uploadId: string;
  documentId: string;
}

interface UploadCompleted {
  upload_id: string;
  source_file_id: string;
  document_id: string;
  document_version: number;
  status: string;
}

export interface UploadedSourceFile {
  uploadId: string;
  sourceFileId: string;
  documentId: string;
  documentVersion: number;
  status: string;
  sha256: string;
}

export class PdfPasswordRequiredError extends ApiError {
  constructor(readonly documentId: string) {
    super(
      "This PDF is encrypted. Enter its password to continue isolated analysis.",
      422,
      "PDF_PASSWORD_REQUIRED",
      false,
    );
    this.name = "PdfPasswordRequiredError";
  }
}

export async function uploadAndAnalyze(
  file: File,
  projectId?: string,
): Promise<{ documentId: string; estimate: PreflightEstimate }> {
  const uploaded = await uploadSourceFile(file, projectId);
  try {
    const estimate = await analyzeDocument(uploaded.documentId);
    return { documentId: uploaded.documentId, estimate };
  } catch (error) {
    if (
      error instanceof ApiError &&
      ["PDF_PASSWORD_REQUIRED", "PDF_PASSWORD_EXPIRED"].includes(error.code)
    ) {
      throw new PdfPasswordRequiredError(uploaded.documentId);
    }
    throw error;
  }
}

export async function uploadSourceFile(
  file: File,
  projectId?: string,
  precomputedSha256?: string,
  options: { signal?: AbortSignal } = {},
): Promise<UploadedSourceFile> {
  options.signal?.throwIfAborted();
  const contentType = file.type || "application/octet-stream";
  const sha256 =
    precomputedSha256 ??
    (await browserSha256(file, 8 * 1024 * 1024, options.signal));
  if (!/^[0-9a-f]{64}$/i.test(sha256)) {
    throw new ApiError(
      "The source hash is invalid.",
      422,
      "INVALID_LOCAL_SHA256",
      false,
    );
  }
  const cacheKey = resumeCacheKey(sha256, file.size, contentType, projectId);
  const initiated = await resumeOrInitiate({
    cacheKey,
    file,
    contentType,
    sha256,
    projectId,
    signal: options.signal,
  });

  let preserveForResume = false;
  try {
    let completedParts: CompletedUploadPart[] = [];
    if (initiated.method === "MULTIPART") {
      const plan = initiated.multipart;
      if (!plan) {
        throw new ApiError(
          "The multipart upload plan is missing.",
          409,
          "UPLOAD_STATE_CORRUPT",
          false,
        );
      }
      try {
        completedParts = await uploadMultipartFile({
          file,
          uploadId: initiated.upload_id,
          plan,
          signal: options.signal,
        });
      } catch (error) {
        preserveForResume =
          error instanceof MultipartTransferError ||
          (error instanceof ApiError && error.retryable);
        throw error;
      }
    } else {
      await uploadSingleFile(file, initiated, options.signal);
    }

    const completed = await apiRequest<UploadCompleted>(
      `/v1/uploads/${initiated.upload_id}/complete`,
      {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({ sha256, parts: completedParts }),
        signal: options.signal,
      },
    );
    removeResumeRecord(cacheKey);
    return {
      uploadId: completed.upload_id,
      sourceFileId: completed.source_file_id,
      documentId: completed.document_id,
      documentVersion: completed.document_version,
      status: completed.status,
      sha256: sha256.toLowerCase(),
    };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      preserveForResume = true;
    }
    if (
      initiated.method === "MULTIPART" &&
      error instanceof ApiError &&
      error.retryable
    ) {
      preserveForResume = true;
    }
    if (!preserveForResume) {
      removeResumeRecord(cacheKey);
      await apiRequest(`/v1/uploads/${initiated.upload_id}/abort`, {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      }).catch(() => undefined);
    }
    throw error;
  }
}

async function uploadSingleFile(
  file: File,
  initiated: UploadInitiation,
  signal?: AbortSignal,
): Promise<void> {
  if (!initiated.upload_url) {
    throw new ApiError(
      "The single-upload target is missing.",
      409,
      "UPLOAD_STATE_CORRUPT",
      false,
    );
  }
  const uploadResponse = await fetch(apiAbsoluteUrl(initiated.upload_url), {
    method: "PUT",
    headers: initiated.headers,
    body: file,
    credentials: initiated.upload_url.startsWith("/") ? "include" : "omit",
    cache: "no-store",
    referrerPolicy: "no-referrer",
    signal,
  });
  if (!uploadResponse.ok) {
    throw new ApiError(
      `The source upload failed (${uploadResponse.status}).`,
      uploadResponse.status,
      "UPLOAD_TRANSFER_FAILED",
      uploadResponse.status >= 500,
    );
  }
}

export async function uploadMultipartFile(input: {
  file: File;
  uploadId: string;
  plan: MultipartUploadPlan;
  fetchImpl?: typeof fetch;
  wait?: (milliseconds: number) => Promise<void>;
  signal?: AbortSignal;
}): Promise<CompletedUploadPart[]> {
  const fetchImpl = input.fetchImpl ?? fetch;
  const wait = input.wait ?? waitMilliseconds;
  validateMultipartPlan(input.file.size, input.plan);

  input.signal?.throwIfAborted();
  const uploaded = await apiRequest<{
    upload_id: string;
    parts: UploadedPart[];
    assembly_completed: boolean;
  }>(input.plan.list_parts_url, { signal: input.signal });
  if (uploaded.assembly_completed) return [];
  const completed = new Map<number, CompletedUploadPart>();
  for (const part of uploaded.parts) {
    const expectedSize = expectedPartSize(
      input.file.size,
      input.plan.part_size,
      input.plan.part_count,
      part.part_number,
    );
    if (part.size === expectedSize) {
      completed.set(part.part_number, {
        part_number: part.part_number,
        etag: normalizeEtag(part.etag),
      });
    }
  }

  const pending = Array.from(
    { length: input.plan.part_count },
    (_, index) => index + 1,
  ).filter((partNumber) => !completed.has(partNumber));
  for (
    let offset = 0;
    offset < pending.length;
    offset += input.plan.presign_batch_size
  ) {
    const batch = pending.slice(offset, offset + input.plan.presign_batch_size);
    const targets = await signParts(input.plan.sign_parts_url, batch);
    const targetByPart = new Map(
      targets.map((target) => [target.part_number, target]),
    );
    const results = await mapWithAdaptiveConcurrency(
      batch,
      async (partNumber) => {
        const target = targetByPart.get(partNumber);
        if (!target) {
          throw new ApiError(
            "A signed part target is missing.",
            502,
            "PART_TARGET_MISSING",
            true,
          );
        }
        const start = (partNumber - 1) * input.plan.part_size;
        const body = input.file.slice(
          start,
          Math.min(start + input.plan.part_size, input.file.size),
        );
        return uploadPartWithRetry({
          body,
          initialTarget: target,
          maxRetries: input.plan.max_retries,
          signPartsUrl: input.plan.sign_parts_url,
          fetchImpl,
          wait,
          signal: input.signal,
        });
      },
      {
        kind: "part",
        maximum: input.plan.max_concurrency,
        signal: input.signal,
      },
    );
    for (const part of results) completed.set(part.part_number, part);
  }

  const ordered = [...completed.values()].sort(
    (left, right) => left.part_number - right.part_number,
  );
  if (
    ordered.length !== input.plan.part_count ||
    ordered.some((part, index) => part.part_number !== index + 1)
  ) {
    throw new MultipartTransferError(
      "The uploaded part list is incomplete. Retry to resume from the last completed part.",
    );
  }
  return ordered;
}

async function uploadPartWithRetry(input: {
  body: Blob;
  initialTarget: PartTarget;
  maxRetries: number;
  signPartsUrl: string;
  fetchImpl: typeof fetch;
  wait: (milliseconds: number) => Promise<void>;
  signal?: AbortSignal;
}): Promise<CompletedUploadPart> {
  let target = input.initialTarget;
  for (let attempt = 0; attempt <= input.maxRetries; attempt += 1) {
    input.signal?.throwIfAborted();
    try {
      const response = await input.fetchImpl(target.upload_url, {
        method: "PUT",
        headers: target.headers,
        body: input.body,
        credentials: "omit",
        cache: "no-store",
        referrerPolicy: "no-referrer",
        signal: input.signal,
      });
      if (response.ok) {
        const etag = response.headers.get("ETag");
        if (!etag) {
          throw new MultipartTransferError(
            "The storage response does not include a valid ETag. Check the bucket CORS configuration.",
          );
        }
        return {
          part_number: target.part_number,
          etag: normalizeEtag(etag),
        };
      }
      if (!isRetryableUploadStatus(response.status)) {
        throw new ApiError(
          `The upload part was rejected (${response.status}).`,
          response.status,
          "UPLOAD_PART_REJECTED",
          false,
        );
      }
      if (response.status === 401 || response.status === 403) {
        const [refreshedTarget] = await signParts(input.signPartsUrl, [
          target.part_number,
        ]);
        if (!refreshedTarget) {
          throw new MultipartTransferError(
            "The part re-signing response is empty. Retry to resume the upload.",
          );
        }
        target = refreshedTarget;
      }
    } catch (error) {
      if (error instanceof ApiError && !error.retryable) throw error;
      if (error instanceof MultipartTransferError) throw error;
      if (attempt >= input.maxRetries) {
        throw new MultipartTransferError(
          "A network error interrupted the part upload. Retry to resume after the last completed part.",
        );
      }
    }
    if (attempt < input.maxRetries) {
      await input.wait(Math.min(8_000, 500 * 2 ** attempt));
    }
  }
  throw new MultipartTransferError(
    "The part upload retry limit was exceeded. Retry to resume the upload.",
  );
}

async function signParts(
  signPartsUrl: string,
  partNumbers: number[],
): Promise<PartTarget[]> {
  const response = await apiRequest<{
    upload_id: string;
    parts: PartTarget[];
  }>(signPartsUrl, {
    method: "POST",
    body: JSON.stringify({ part_numbers: partNumbers }),
  });
  return response.parts;
}

export async function mapWithConcurrency<T, R>(
  values: readonly T[],
  concurrency: number,
  callback: (value: T) => Promise<R>,
): Promise<R[]> {
  const safeConcurrency = Math.max(1, Math.min(8, Math.floor(concurrency)));
  const results = new Array<R>(values.length);
  let nextIndex = 0;
  async function worker(): Promise<void> {
    while (nextIndex < values.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await callback(values[index]!);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(safeConcurrency, values.length) }, () =>
      worker(),
    ),
  );
  return results;
}

export type AdaptiveTransferKind = "file" | "part";

type BrowserCapacity = {
  visible: boolean;
  deviceMemory?: number;
  effectiveType?: string;
  downlink?: number;
  saveData?: boolean;
};

export function adaptiveTransferConcurrency(
  kind: AdaptiveTransferKind,
  capacity: BrowserCapacity = browserCapacity(),
): number {
  if (!capacity.visible) return 0;
  const minimum = kind === "file" ? 3 : 2;
  let concurrency = kind === "file" ? 6 : 5;
  if ((capacity.deviceMemory ?? 8) <= 2) concurrency = minimum;
  else if ((capacity.deviceMemory ?? 8) <= 4) concurrency = Math.min(4, concurrency);
  if (capacity.saveData || ["slow-2g", "2g"].includes(capacity.effectiveType ?? "")) {
    concurrency = minimum;
  } else if (capacity.effectiveType === "3g") {
    concurrency = Math.min(concurrency, minimum + 1);
  }
  if (
    capacity.visible &&
    (capacity.deviceMemory ?? 0) >= 8 &&
    (capacity.downlink ?? 0) >= 20
  ) {
    concurrency = 8;
  }
  return Math.max(minimum, Math.min(8, concurrency));
}

export async function mapWithAdaptiveConcurrency<T, R>(
  values: readonly T[],
  callback: (value: T) => Promise<R>,
  options: {
    kind: AdaptiveTransferKind;
    maximum?: number;
    capacity?: () => BrowserCapacity;
    signal?: AbortSignal;
  },
): Promise<R[]> {
  if (values.length === 0) return [];
  const results = new Array<R>(values.length);
  const capacity = options.capacity ?? browserCapacity;
  const maximum = Math.max(1, Math.min(8, options.maximum ?? 8));
  let cursor = 0;
  let running = 0;
  let completed = 0;
  let settled = false;

  return new Promise<R[]>((resolve, reject) => {
    const cleanup = () => {
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", schedule);
      }
      options.signal?.removeEventListener("abort", abort);
    };
    const finishFailure = (error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const runOne = (index: number) => {
      running += 1;
      void callback(values[index]!)
        .then((result) => {
          results[index] = result;
          completed += 1;
        })
        .catch(finishFailure)
        .finally(() => {
          running -= 1;
          if (settled) return;
          if (completed === values.length) {
            settled = true;
            cleanup();
            resolve(results);
            return;
          }
          schedule();
        });
    };
    function schedule() {
      if (settled) return;
      if (options.signal?.aborted) {
        finishFailure(options.signal.reason ?? new DOMException("Aborted", "AbortError"));
        return;
      }
      const target = Math.min(
        maximum,
        adaptiveTransferConcurrency(options.kind, capacity()),
      );
      while (running < target && cursor < values.length) {
        const index = cursor;
        cursor += 1;
        runOne(index);
      }
    }
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", schedule);
    }
    const abort = () =>
      finishFailure(options.signal?.reason ?? new DOMException("Aborted", "AbortError"));
    options.signal?.addEventListener("abort", abort, { once: true });
    schedule();
  });
}

export function weightedFairFileOrder<T extends { size: number }>(
  values: readonly T[],
): T[] {
  const buckets: T[][] = [[], [], []];
  for (const value of values) {
    const index = value.size <= 4 * 1024 * 1024 ? 0 : value.size <= 64 * 1024 * 1024 ? 1 : 2;
    buckets[index]!.push(value);
  }
  const order = [0, 1, 0, 2] as const;
  const result: T[] = [];
  while (buckets.some((bucket) => bucket.length > 0)) {
    let progressed = false;
    for (const bucketIndex of order) {
      const value = buckets[bucketIndex]!.shift();
      if (!value) continue;
      result.push(value);
      progressed = true;
    }
    if (!progressed) break;
  }
  return result;
}


function browserCapacity(): BrowserCapacity {
  const navigatorWithCapacity = globalThis.navigator as
    | (Navigator & {
        deviceMemory?: number;
        connection?: {
          effectiveType?: string;
          downlink?: number;
          saveData?: boolean;
        };
      })
    | undefined;
  return {
    visible: typeof document === "undefined" || document.visibilityState === "visible",
    deviceMemory: navigatorWithCapacity?.deviceMemory,
    effectiveType: navigatorWithCapacity?.connection?.effectiveType,
    downlink: navigatorWithCapacity?.connection?.downlink,
    saveData: navigatorWithCapacity?.connection?.saveData,
  };
}

export function normalizeEtag(value: string): string {
  const normalized = value.trim().replace(/^"|"$/g, "").toLowerCase();
  if (!/^[a-f0-9]{32,128}$/.test(normalized)) {
    throw new MultipartTransferError("Storage returned an invalid ETag.");
  }
  return normalized;
}

function validateMultipartPlan(
  fileSize: number,
  plan: MultipartUploadPlan,
): void {
  if (
    plan.part_size <= 0 ||
    plan.part_count <= 0 ||
    plan.part_count > 10_000 ||
    plan.presign_batch_size < 1 ||
    plan.presign_batch_size > 100 ||
    plan.max_concurrency < 1 ||
    plan.max_concurrency > 8 ||
    Math.ceil(fileSize / plan.part_size) !== plan.part_count
  ) {
    throw new ApiError(
      "The server returned an invalid multipart upload plan.",
      409,
      "UPLOAD_PLAN_INVALID",
      false,
    );
  }
}

function expectedPartSize(
  fileSize: number,
  partSize: number,
  partCount: number,
  partNumber: number,
): number {
  if (partNumber < 1 || partNumber > partCount) return -1;
  return partNumber < partCount
    ? partSize
    : fileSize - partSize * (partCount - 1);
}

async function resumeOrInitiate(input: {
  cacheKey: string;
  file: File;
  contentType: string;
  sha256: string;
  projectId?: string;
  signal?: AbortSignal;
}): Promise<UploadInitiation> {
  const record = loadResumeRecord(input.cacheKey);
  if (record) {
    try {
      const status = await apiRequest<UploadSessionStatus>(
        `/v1/uploads/${record.uploadId}`,
        { signal: input.signal },
      );
      if (
        status.method === "MULTIPART" &&
        ["initiated", "uploaded", "completed"].includes(status.status) &&
        status.expected_size === input.file.size &&
        status.expected_content_type === input.contentType &&
        status.expected_sha256 === input.sha256 &&
        status.multipart &&
        Date.parse(status.expires_at) > Date.now()
      ) {
        return {
          upload_id: status.upload_id,
          document_id: status.document_id,
          method: status.method,
          multipart: status.multipart,
          expires_at: status.expires_at,
        };
      }
      removeResumeRecord(input.cacheKey);
    } catch (error) {
      if (!(error instanceof ApiError) || error.retryable) throw error;
      removeResumeRecord(input.cacheKey);
    }
  }

  const initiated = await apiRequest<UploadInitiation>("/v1/uploads/initiate", {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: JSON.stringify({
      filename: input.file.name,
      content_type: input.contentType,
      size: input.file.size,
      sha256: input.sha256,
      project_id: input.projectId,
    }),
    signal: input.signal,
  });
  if (initiated.method === "MULTIPART") {
    saveResumeRecord(input.cacheKey, {
      uploadId: initiated.upload_id,
      documentId: initiated.document_id,
    });
  }
  return initiated;
}

function resumeCacheKey(
  sha256: string,
  size: number,
  contentType: string,
  projectId?: string,
): string {
  return `akc:multipart:v1:${sha256}:${size}:${contentType}:${projectId ?? "default"}`;
}

function loadResumeRecord(key: string): ResumeRecord | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "");
    if (
      typeof value === "object" &&
      value !== null &&
      typeof value.uploadId === "string" &&
      typeof value.documentId === "string"
    ) {
      return value as ResumeRecord;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function saveResumeRecord(key: string, value: ResumeRecord): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function removeResumeRecord(key: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(key);
}

function isRetryableUploadStatus(status: number): boolean {
  return (
    status === 401 ||
    status === 403 ||
    status === 408 ||
    status === 429 ||
    status >= 500
  );
}

function waitMilliseconds(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

// Re-exported so existing importers keep working. The definitions live in
// browser-hash.ts, which pulls in no API client.
export { browserQuickFingerprint, browserSha256 };
export { MultipartTransferError };
