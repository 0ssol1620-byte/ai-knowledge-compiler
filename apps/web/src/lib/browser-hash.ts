import { MultipartTransferError } from "@/lib/transfer-errors";

/**
 * Browser-side hashing, split out so the marketing page does not pay for it.
 *
 * The hero drop zone inspects a file the visitor chose, which means hashing it,
 * and it reached browserSha256 through upload-client. That module imports
 * api-client at module scope for the real upload path, so the homepage's
 * initial bundle carried zod and the SSE client -- 21 KB gzip of request
 * validation for a page that never calls the API.
 *
 * It is the same reasoning as the hash-wasm dynamic import below, one level up:
 * the dependency belongs to the moment a visitor acts, not to first paint.
 * Nothing here changed except its address.
 */

export async function browserSha256(
  file: Blob,
  chunkSize = 8 * 1024 * 1024,
  signal?: AbortSignal,
): Promise<string> {
  signal?.throwIfAborted();
  const safeChunkSize = Math.max(
    4 * 1024 * 1024,
    Math.min(16 * 1024 * 1024, Math.floor(chunkSize)),
  );
  if (typeof Worker !== "undefined") {
    return hashInWorker(file, safeChunkSize, signal);
  }
  return hashInline(file, safeChunkSize, signal);
}

export async function browserQuickFingerprint(
  file: Blob,
  signal?: AbortSignal,
  sampleBytes = 64 * 1024,
): Promise<string> {
  signal?.throwIfAborted();
  const boundedSample = Math.max(16 * 1024, Math.min(256 * 1024, sampleBytes));
  const firstEnd = Math.min(file.size, boundedSample);
  const lastStart = Math.max(firstEnd, file.size - boundedSample);
  const sampled = new Blob([
    new TextEncoder().encode(`qv1:${file.size}:`),
    file.slice(0, firstEnd),
    file.slice(lastStart),
  ]);
  const digest = await browserSha256(sampled, 4 * 1024 * 1024, signal);
  return `qv1:${file.size}:${digest}`;
}

async function hashInline(
  file: Blob,
  chunkSize: number,
  signal?: AbortSignal,
): Promise<string> {
  // Main-thread hashing is a compatibility path only. Keep each synchronous
  // hash update small and yield between every read/update so large sources do
  // not monopolize input, paint, or abort handling when Workers are unavailable.
  const inlineChunkSize = Math.min(chunkSize, 1024 * 1024);
  /*
   * hash-wasm is imported here rather than at module scope, and the reason is
   * a budget rather than a preference.
   *
   * This module is reached from the marketing hero: the drop zone inspects a
   * file the visitor chose, and inspecting means hashing. A top-level import
   * put the WASM hasher into the homepage's initial bundle, where it is dead
   * weight until someone actually drops something -- and it pushed
   * resource-summary:script.size past the §22 ratchet at 200 KB.
   *
   * Nothing about the hash changes. It is fetched on the first call and the
   * module cache keeps it for every call after.
   */
  const { createSHA256 } = await import("hash-wasm");
  const hasher = await createSHA256();
  hasher.init();
  for (let offset = 0; offset < file.size; offset += inlineChunkSize) {
    await yieldHashingTurn(signal);
    signal?.throwIfAborted();
    const bytes = new Uint8Array(
      await file.slice(offset, offset + inlineChunkSize).arrayBuffer(),
    );
    await yieldHashingTurn(signal);
    signal?.throwIfAborted();
    hasher.update(bytes);
  }
  signal?.throwIfAborted();
  return hasher.digest("hex");
}

function yieldHashingTurn(signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", abort);
      callback();
    };
    const abort = () => {
      globalThis.clearTimeout(timer);
      finish(() =>
        reject(
          signal?.reason instanceof Error
            ? signal.reason
            : new DOMException("Hashing was aborted.", "AbortError"),
        ),
      );
    };
    const timer = globalThis.setTimeout(() => finish(resolve), 0);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}

function hashInWorker(
  file: Blob,
  chunkSize: number,
  signal?: AbortSignal,
): Promise<string> {
  const worker = new Worker(new URL("../workers/sha256.worker.ts", import.meta.url), {
    type: "module",
    name: "akc-sha256",
  });
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      signal?.removeEventListener("abort", abort);
      worker.terminate();
    };
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback();
    };
    const abort = () =>
      finish(() =>
        reject(
          signal?.reason instanceof Error
            ? signal.reason
            : new DOMException("Hashing was aborted.", "AbortError"),
        ),
      );
    worker.onerror = () => {
      finish(() =>
        reject(
          new MultipartTransferError(
            "The local SHA-256 worker stopped unexpectedly.",
          ),
        ),
      );
    };
    worker.onmessage = (
      event: MessageEvent<
        | { id: string; kind: "progress"; bytes: number; total: number }
        | { id: string; kind: "complete"; sha256: string }
        | { id: string; kind: "error"; message: string }
      >,
    ) => {
      const message = event.data;
      if (message.id !== id) return;
      if (message.kind === "complete") {
        finish(() => resolve(message.sha256));
      } else if (message.kind === "error") {
        finish(() => reject(new MultipartTransferError(message.message)));
      }
    };
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) {
      abort();
      return;
    }
    worker.postMessage({ id, blob: file, chunkSize });
  });
}
