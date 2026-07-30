import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "@/lib/api-client";
import {
  browserSha256,
  mapWithConcurrency,
  MultipartTransferError,
  normalizeEtag,
  uploadMultipartFile,
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
  });

  it("hashes a blob incrementally without loading it as one array buffer", async () => {
    const digest = await browserSha256(new Blob(["abc"]), 1);
    expect(digest).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
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
