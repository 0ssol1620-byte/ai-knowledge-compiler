import { describe, expect, it, vi } from "vitest";

import {
  abbreviateDigest,
  extensionOf,
  formatBytes,
  inspectDroppedFile,
} from "@/lib/facing/dropped-file";

// The digest itself is browser-hash's browserSha256, already covered in
// upload-client.test.ts. These tests are about what the hero is allowed to
// claim. The mock follows the function: it moved out of upload-client so the
// marketing page would stop shipping the API client with it.
vi.mock("@/lib/browser-hash", () => ({
  browserSha256: vi.fn(async () => "a".repeat(64)),
}));

function fileOf(name: string, size: number, type = "application/pdf"): File {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("inspectDroppedFile", () => {
  it("hashes a supported file and reports its own facts", async () => {
    const result = await inspectDroppedFile(fileOf("filing.pdf", 2_000_000));
    expect(result).toMatchObject({
      name: "filing.pdf",
      size: 2_000_000,
      extension: "pdf",
      supported: true,
      sha256: "a".repeat(64),
    });
    expect(result.rejection).toBeUndefined();
  });

  it("never returns a digest it did not compute", async () => {
    for (const file of [
      fileOf("empty.pdf", 0),
      fileOf("huge.pdf", 60 * 1024 * 1024),
      fileOf("clip.mov", 1000, "video/quicktime"),
    ]) {
      const result = await inspectDroppedFile(file);
      expect(result.rejection).toBeDefined();
      expect(result.sha256).toBe("");
    }
  });

  it("states the size limit rather than just refusing", async () => {
    const result = await inspectDroppedFile(fileOf("huge.pdf", 60 * 1024 * 1024));
    expect(result.rejection).toContain("50 MB");
  });

  it("names the unsupported extension so the message is actionable", async () => {
    const result = await inspectDroppedFile(fileOf("clip.mov", 1000));
    expect(result.rejection).toContain(".mov");
  });

  it("does not render an empty extension as a bare dot", async () => {
    const result = await inspectDroppedFile(fileOf("README", 1000));
    expect(result.extension).toBe("");
    // The message must not read ".  is not a format…" — it takes the other branch.
    expect(result.rejection).toBe(
      "That file has no extension the compiler recognises.",
    );
  });
});

describe("extensionOf", () => {
  it.each([
    ["report.PDF", "pdf"],
    ["a.b.docx", "docx"],
    ["README", ""],
    [".gitignore", ""], // a dotfile is not an extension
    ["trailing.", ""],
  ])("%s -> %s", (name, expected) => {
    expect(extensionOf(name)).toBe(expected);
  });
});

describe("formatBytes", () => {
  it.each([
    [512, "512 B"],
    [1024, "1.0 KB"],
    [1_500_000, "1.4 MB"],
    [52_428_800, "50 MB"],
  ])("%s -> %s", (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});

describe("abbreviateDigest", () => {
  it("marks the elision instead of silently truncating", () => {
    const hex = "0123456789abcdef".repeat(4);
    const short = abbreviateDigest(hex);
    expect(short).toContain("…");
    expect(short.startsWith("0123456789")).toBe(true);
    expect(short.endsWith("6789abcdef")).toBe(true);
  });

  it("leaves a short value alone", () => {
    expect(abbreviateDigest("abc123")).toBe("abc123");
  });
});
