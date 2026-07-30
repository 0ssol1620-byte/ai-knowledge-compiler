import { createSHA256 } from "hash-wasm";

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

export class MultipartTransferError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MultipartTransferError";
  }
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
  const contentType = file.type || "application/octet-stream";
  const sha256 = await browserSha256(file);
  const cacheKey = resumeCacheKey(sha256, file.size, contentType, projectId);
  const initiated = await resumeOrInitiate({
    cacheKey,
    file,
    contentType,
    sha256,
    projectId,
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
        });
      } catch (error) {
        preserveForResume =
          error instanceof MultipartTransferError ||
          (error instanceof ApiError && error.retryable);
        throw error;
      }
    } else {
      await uploadSingleFile(file, initiated);
    }

    await apiRequest(`/v1/uploads/${initiated.upload_id}/complete`, {
      method: "POST",
      idempotencyKey: crypto.randomUUID(),
      body: JSON.stringify({ sha256, parts: completedParts }),
    });
    removeResumeRecord(cacheKey);
    try {
      const estimate = await analyzeDocument(initiated.document_id);
      return { documentId: initiated.document_id, estimate };
    } catch (error) {
      if (
        error instanceof ApiError &&
        ["PDF_PASSWORD_REQUIRED", "PDF_PASSWORD_EXPIRED"].includes(error.code)
      ) {
        throw new PdfPasswordRequiredError(initiated.document_id);
      }
      throw error;
    }
  } catch (error) {
    if (error instanceof PdfPasswordRequiredError) {
      removeResumeRecord(cacheKey);
      throw error;
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
}): Promise<CompletedUploadPart[]> {
  const fetchImpl = input.fetchImpl ?? fetch;
  const wait = input.wait ?? waitMilliseconds;
  validateMultipartPlan(input.file.size, input.plan);

  const uploaded = await apiRequest<{
    upload_id: string;
    parts: UploadedPart[];
    assembly_completed: boolean;
  }>(input.plan.list_parts_url);
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
    const results = await mapWithConcurrency(
      batch,
      input.plan.max_concurrency,
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
        });
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
}): Promise<CompletedUploadPart> {
  let target = input.initialTarget;
  for (let attempt = 0; attempt <= input.maxRetries; attempt += 1) {
    try {
      const response = await input.fetchImpl(target.upload_url, {
        method: "PUT",
        headers: target.headers,
        body: input.body,
        credentials: "omit",
        cache: "no-store",
        referrerPolicy: "no-referrer",
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

export async function browserSha256(
  file: Blob,
  chunkSize = 4 * 1024 * 1024,
): Promise<string> {
  const hasher = await createSHA256();
  hasher.init();
  for (let offset = 0; offset < file.size; offset += chunkSize) {
    const bytes = new Uint8Array(
      await file.slice(offset, offset + chunkSize).arrayBuffer(),
    );
    hasher.update(bytes);
  }
  return hasher.digest("hex");
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
}): Promise<UploadInitiation> {
  const record = loadResumeRecord(input.cacheKey);
  if (record) {
    try {
      const status = await apiRequest<UploadSessionStatus>(
        `/v1/uploads/${record.uploadId}`,
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
