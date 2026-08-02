import { beforeEach, describe, expect, it } from "vitest";

import {
  collectionRetryPointerKey,
  loadCollectionResumeRecord,
  saveCollectionResumeRecord,
  saveCollectionRuntimePointer,
} from "@/lib/collection-storage";

describe("collection recovery storage", () => {
  beforeEach(() => window.localStorage.clear());

  it("keeps only an opaque IndexedDB pointer in localStorage", async () => {
    const pointerKey = collectionRetryPointerKey("project-1", "a".repeat(64));
    await saveCollectionResumeRecord(pointerKey, {
      collectionId: "collection-storage-test",
      sourceRootId: "source-storage-test",
      projectId: "project-1",
      sourceFingerprint: "a".repeat(64),
      limitations: ["verified receipt pending"],
      pendingReceipts: [{ fileId: "file-1", sourceFileId: "source-file-1" }],
      browserResumeToken: "browser-secret-token",
    });

    const rawPointer = window.localStorage.getItem(pointerKey) ?? "";
    expect(JSON.parse(rawPointer)).toEqual({
      schemaVersion: 2,
      sessionId: "collection:collection-storage-test",
    });
    expect(rawPointer).not.toContain("browser-secret-token");
    expect(rawPointer).not.toContain("source-file-1");
    await expect(loadCollectionResumeRecord(pointerKey)).resolves.toEqual(
      expect.objectContaining({ browserResumeToken: "browser-secret-token" }),
    );
  });

  it("does not copy processing capability tokens into localStorage", async () => {
    await saveCollectionRuntimePointer({
      collectionId: "collection-runtime-storage-test",
      startIdempotencyKey: "start-key",
      processingResumeToken: "processing-secret-token",
    });
    const persisted = Array.from(
      { length: window.localStorage.length },
      (_, index) => {
        const key = window.localStorage.key(index) ?? "";
        return `${key}:${window.localStorage.getItem(key) ?? ""}`;
      },
    ).join("\n");
    expect(persisted).not.toContain("processing-secret-token");
  });
});
