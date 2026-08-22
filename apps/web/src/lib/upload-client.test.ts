import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { analyzeDocument, ApiError, apiRequest } from "@/lib/api-client";
import {
  browserSha256,
  browserQuickFingerprint,
  adaptiveTransferConcurrency,
  mapWithAdaptiveConcurrency,
  mapWithConcurrency,
  MultipartTransferError,
  normalizeEtag,
  uploadAndAnalyze,
  uploadMultipartFile,
  uploadSourceFile,
} from "@/lib/upload-client";

vi.mock("@/lib/api-client", async () => {
  const actual =
    await vi.importActual<Record<string, unknown>>("@/lib/api-client");
  return {
    ...actual,
    apiRequest: vi.fn(),
    analyzeDocument: vi.fn(),
  };
});

const etagA = "a".repeat(32);
const etagB = "b".repeat(32);
const etagC = "c".repeat(32);

describe("browser-direct multipart uploads", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
    vi.mocked(analyzeDocument).mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hashes a blob incrementally without loading it as one array buffer", async () => {
    const digest = await browserSha256(new Blob(["abc"]), 1);
    expect(digest).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("yields and honors abort on the bounded main-thread compatibility path", async () => {
    vi.stubGlobal("Worker", undefined);
    const controller = new AbortController();
    const source = new Blob([new Uint8Array(3 * 1024 * 1024)]);
    const pending = browserSha256(source, 16 * 1024 * 1024, controller.signal);

    window.setTimeout(
      () => controller.abort(new DOMException("Paused", "AbortError")),
      0,
    );

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("treats a quick-fingerprint collision only as a candidate until full SHA-256 differs", async () => {
    const boundary = "a".repeat(64 * 1024);
    const tail = "z".repeat(64 * 1024);
    const first = new Blob([boundary, "x".repeat(32 * 1024), tail]);
    const second = new Blob([boundary, "y".repeat(32 * 1024), tail]);

    const [quickFirst, quickSecond, fullFirst, fullSecond] = await Promise.all([
      browserQuickFingerprint(first),
      browserQuickFingerprint(second),
      browserSha256(first),
      browserSha256(second),
    ]);

    expect(quickFirst).toBe(quickSecond);
    expect(fullFirst).not.toBe(fullSecond);
    expect(quickFirst).toMatch(/^qv1:\d+:[0-9a-f]{64}$/);
  });

  it("terminates the SHA worker and returns AbortError when hashing is paused", async () => {
    let terminated = false;
    class PendingWorker {
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      postMessage() {}
      terminate() {
        terminated = true;
      }
    }
    vi.stubGlobal("Worker", PendingWorker);
    const controller = new AbortController();
    const pending = browserSha256(new Blob(["source"]), undefined, controller.signal);
    controller.abort(new DOMException("Paused", "AbortError"));

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(terminated).toBe(true);
  });

  it("pauses new adaptive work while hidden and resumes on visibility", async () => {
    let visible = false;
    let started = 0;
    const pending = mapWithAdaptiveConcurrency(
      [1, 2, 3],
      async (value) => {
        started += 1;
        return value;
      },
      {
        kind: "file",
        capacity: () => ({ visible, deviceMemory: 8, downlink: 20 }),
      },
    );
    await Promise.resolve();
    expect(adaptiveTransferConcurrency("file", { visible: false })).toBe(0);
    expect(started).toBe(0);

    visible = true;
    document.dispatchEvent(new Event("visibilitychange"));
    await expect(pending).resolves.toEqual([1, 2, 3]);
    expect(started).toBe(3);
  });

  it("bounds concurrent work and preserves result ordering", async () => {
    let active = 0;
    let maximum = 0;
    const values = await mapWithConcurrency(
      [1, 2, 3, 4, 5],
      2,
      async (value) => {
        active += 1;
        maximum = Math.max(maximum, active);
        await new Promise((resolve) => window.setTimeout(resolve, 1));
        active -= 1;
        return value * 2;
      },
    );
    expect(maximum).toBe(2);
    expect(values).toEqual([2, 4, 6, 8, 10]);
  });

  it("normalizes only sanitized provider ETags", () => {
    expect(normalizeEtag(`"${etagA.toUpperCase()}"`)).toBe(etagA);
    expect(() => normalizeEtag("credential?signature=secret")).toThrow(
      MultipartTransferError,
    );
  });

  it("resumes completed parts and uploads only missing slices", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({
        upload_id: "upload-1",
        parts: [{ part_number: 1, etag: etagA, size: 4 }],
      } as never)
      .mockResolvedValueOnce({
        upload_id: "upload-1",
        parts: [
          {
            part_number: 2,
            upload_url: "https://objects.invalid/2",
            headers: {},
            expires_at: "2099-01-01T00:00:00Z",
          },
          {
            part_number: 3,
            upload_url: "https://objects.invalid/3",
            headers: {},
            expires_at: "2099-01-01T00:00:00Z",
          },
        ],
      } as never);
    const uploadedBodies: string[] = [];
    let active = 0;
    let maximum = 0;
    const directFetch = vi.fn(
      async (url: string | URL | Request, init?: RequestInit) => {
        active += 1;
        maximum = Math.max(maximum, active);
        const body = init?.body as Blob;
        uploadedBodies.push(await body.text());
        await new Promise((resolve) => window.setTimeout(resolve, 1));
        active -= 1;
        return new Response(null, {
          status: 200,
          headers: {
            ETag: String(url).endsWith("/2") ? `"${etagB}"` : `"${etagC}"`,
          },
        });
      },
    );

    const completed = await uploadMultipartFile({
      file: new File(["abcdefghijkl"], "source.txt", { type: "text/plain" }),
      uploadId: "upload-1",
      plan: {
        part_size: 4,
        part_count: 3,
        presign_batch_size: 2,
        max_concurrency: 2,
        max_retries: 1,
        sign_parts_url: "/v1/uploads/upload-1/parts/sign",
        list_parts_url: "/v1/uploads/upload-1/parts",
      },
      fetchImpl: directFetch as typeof fetch,
      wait: () => Promise.resolve(),
    });

    expect(maximum).toBe(2);
    expect(uploadedBodies.sort()).toEqual(["efgh", "ijkl"]);
    expect(completed).toEqual([
      { part_number: 1, etag: etagA },
      { part_number: 2, etag: etagB },
      { part_number: 3, etag: etagC },
    ]);
  });

  it("refreshes an expired part URL and retries without exposing it", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({
        upload_id: "upload-2",
        parts: [],
      } as never)
      .mockResolvedValueOnce({
        upload_id: "upload-2",
        parts: [
          {
            part_number: 1,
            upload_url: "https://objects.invalid/expired",
            headers: {},
            expires_at: "2099-01-01T00:00:00Z",
          },
        ],
      } as never)
      .mockResolvedValueOnce({
        upload_id: "upload-2",
        parts: [
          {
            part_number: 1,
            upload_url: "https://objects.invalid/refreshed",
            headers: {},
            expires_at: "2099-01-01T00:00:00Z",
          },
        ],
      } as never);
    const directFetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 403 }))
      .mockResolvedValueOnce(
        new Response(null, {
          status: 200,
          headers: { ETag: `"${etagA}"` },
        }),
      );

    const completed = await uploadMultipartFile({
      file: new File(["abcd"], "source.txt"),
      uploadId: "upload-2",
      plan: {
        part_size: 4,
        part_count: 1,
        presign_batch_size: 1,
        max_concurrency: 1,
        max_retries: 1,
        sign_parts_url: "/v1/uploads/upload-2/parts/sign",
        list_parts_url: "/v1/uploads/upload-2/parts",
      },
      fetchImpl: directFetch as typeof fetch,
      wait: () => Promise.resolve(),
    });

    expect(directFetch).toHaveBeenCalledTimes(2);
    expect(completed).toEqual([{ part_number: 1, etag: etagA }]);
  });

  it("continues finalization after a lost provider completion ACK", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      upload_id: "upload-assembled",
      parts: [],
      assembly_completed: true,
    } as never);
    const directFetch = vi.fn();

    const completed = await uploadMultipartFile({
      file: new File(["abcd"], "source.txt"),
      uploadId: "upload-assembled",
      plan: {
        part_size: 4,
        part_count: 1,
        presign_batch_size: 1,
        max_concurrency: 1,
        max_retries: 1,
        sign_parts_url: "/v1/uploads/upload-assembled/parts/sign",
        list_parts_url: "/v1/uploads/upload-assembled/parts",
      },
      fetchImpl: directFetch as typeof fetch,
      wait: () => Promise.resolve(),
    });

    expect(completed).toEqual([]);
    expect(directFetch).not.toHaveBeenCalled();
  });

  it("returns a server-verified source receipt without starting analysis", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({
        upload_id: "upload-source",
        document_id: "document-source",
        method: "PUT",
        upload_url: "/v1/uploads/upload-source/content",
        headers: { "Content-Type": "text/plain" },
        expires_at: "2099-01-01T00:00:00Z",
      } as never)
      .mockResolvedValueOnce({
        upload_id: "upload-source",
        source_file_id: "source-file-1",
        document_id: "document-source",
        document_version: 1,
        status: "SECURITY_VERIFIED",
      } as never);
    const directFetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const result = await uploadSourceFile(
      new File(["source"], "source.txt", { type: "text/plain" }),
      "project-1",
      "a".repeat(64),
    );

    expect(result).toEqual(
      expect.objectContaining({
        sourceFileId: "source-file-1",
        documentId: "document-source",
        sha256: "a".repeat(64),
      }),
    );
    expect(analyzeDocument).not.toHaveBeenCalled();
    directFetch.mockRestore();
  });

  it("preserves an encrypted document and exposes the password-resume boundary", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({
        upload_id: "upload-encrypted",
        document_id: "document-encrypted",
        method: "PUT",
        upload_url: "/v1/uploads/upload-encrypted/content",
        headers: { "Content-Type": "application/pdf" },
        expires_at: "2099-01-01T00:00:00Z",
      } as never)
      .mockResolvedValueOnce({
        upload_id: "upload-encrypted",
        source_file_id: "source-encrypted",
        document_id: "document-encrypted",
        document_version: 1,
        status: "SECURITY_VERIFIED",
      } as never);
    vi.mocked(analyzeDocument).mockRejectedValueOnce(
      new ApiError("Password required", 422, "PDF_PASSWORD_REQUIRED", false),
    );
    const directFetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(
      uploadAndAnalyze(
        new File(["encrypted"], "locked.pdf", {
          type: "application/pdf",
        }),
      ),
    ).rejects.toEqual(
      expect.objectContaining({
        name: "PdfPasswordRequiredError",
        code: "PDF_PASSWORD_REQUIRED",
        documentId: "document-encrypted",
      }),
    );
    expect(
      vi
        .mocked(apiRequest)
        .mock.calls.some(([path]) => String(path).endsWith("/abort")),
    ).toBe(false);
    directFetch.mockRestore();
  });

  it("returns a resumable error after transient retries are exhausted", async () => {
    vi.mocked(apiRequest)
      .mockResolvedValueOnce({
        upload_id: "upload-3",
        parts: [],
      } as never)
      .mockResolvedValueOnce({
        upload_id: "upload-3",
        parts: [
          {
            part_number: 1,
            upload_url: "https://objects.invalid/retry",
            headers: {},
            expires_at: "2099-01-01T00:00:00Z",
          },
        ],
      } as never);
    const directFetch = vi.fn().mockRejectedValue(new TypeError("network"));

    await expect(
      uploadMultipartFile({
        file: new File(["abcd"], "source.txt"),
        uploadId: "upload-3",
        plan: {
          part_size: 4,
          part_count: 1,
          presign_batch_size: 1,
          max_concurrency: 1,
          max_retries: 1,
          sign_parts_url: "/v1/uploads/upload-3/parts/sign",
          list_parts_url: "/v1/uploads/upload-3/parts",
        },
        fetchImpl: directFetch as typeof fetch,
        wait: () => Promise.resolve(),
      }),
    ).rejects.toThrow(MultipartTransferError);
    expect(directFetch).toHaveBeenCalledTimes(2);
  });
});
