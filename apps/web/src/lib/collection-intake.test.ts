import { describe, expect, it } from "vitest";

import {
  buildIntakeManifest,
  collectionManifestLimitState,
  COLLECTION_MAX_BYTES,
  COLLECTION_MAX_FILES,
  mergeIntakeFiles,
  safeRelativePath,
  type IntakeFileLike,
} from "@/lib/collection-intake";

function file(
  name: string,
  webkitRelativePath: string,
  overrides: Partial<IntakeFileLike> = {},
): IntakeFileLike {
  return {
    name,
    size: 120,
    type: "text/markdown",
    lastModified: 42,
    webkitRelativePath,
    ...overrides,
  };
}

describe("collection intake manifest", () => {
  it("normalizes safe folder paths and rejects traversal or absolute paths", () => {
    expect(safeRelativePath(file("note.md", "vault\\notes\\note.md"))).toBe(
      "vault/notes/note.md",
    );
    expect(safeRelativePath(file("secret.md", "../secret.md"))).toBeUndefined();
    expect(
      safeRelativePath(file("secret.md", "C:\\secret.md")),
    ).toBeUndefined();
    expect(
      safeRelativePath(file("secret.md", "/root/secret.md")),
    ).toBeUndefined();
  });

  it("reports duplicate candidates provisionally without dropping either path", () => {
    const manifest = buildIntakeManifest([
      file("note.md", "vault/a/note.md"),
      file("note.md", "vault/archive/note.md"),
      file("table.csv", "vault/table.csv", {
        size: 80,
        type: "text/csv",
      }),
    ]);

    expect(manifest.accepted).toHaveLength(3);
    expect(manifest.duplicateCandidates).toBe(1);
    expect(manifest.uniqueCandidates).toBe(2);
    expect(manifest.formats).toEqual([
      { extension: "md", count: 2 },
      { extension: "csv", count: 1 },
    ]);
    expect(manifest.accepted[1]?.duplicateOf).toBe("vault/a/note.md");
  });

  it("merges reselections without duplicating the same path and fingerprint", () => {
    const first = file("note.md", "vault/note.md");
    const second = file("table.csv", "vault/table.csv");
    expect(mergeIntakeFiles([first], [first, second])).toEqual([first, second]);
  });

  it("enforces the 5,000-file and 10 GiB collection manifest boundaries", () => {
    const atFileLimit = buildIntakeManifest(
      Array.from({ length: COLLECTION_MAX_FILES }, (_, index) =>
        file(`note-${index}.md`, `vault/note-${index}.md`, { size: 1 }),
      ),
    );
    expect(collectionManifestLimitState(atFileLimit)).toEqual({
      withinLimits: true,
      fileLimitExceeded: false,
      byteLimitExceeded: false,
    });

    const overFileLimit = buildIntakeManifest([
      ...atFileLimit.accepted.map((entry) => entry.file),
      file("extra.md", "vault/extra.md", { size: 1 }),
    ]);
    expect(collectionManifestLimitState(overFileLimit).fileLimitExceeded).toBe(
      true,
    );

    const overByteLimit = buildIntakeManifest([
      file("archive.pdf", "vault/archive.pdf", {
        size: COLLECTION_MAX_BYTES + 1,
        type: "application/pdf",
      }),
    ]);
    expect(collectionManifestLimitState(overByteLimit).byteLimitExceeded).toBe(
      true,
    );
  });
});
