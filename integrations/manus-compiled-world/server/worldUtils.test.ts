import { describe, expect, it } from "vitest";
import { COMPILE_STAGES, contentHash, decodeUpload, MAX_PILOT_UPLOAD_BYTES, safeFileName, selectPrimarySource, stageProgress } from "./worldUtils";

describe("Compiled World upload safeguards", () => {
  it("decodes a valid browser data URL", () => {
    const bytes = decodeUpload("data:text/plain;base64,SGVsbG8=");
    expect(bytes.toString("utf8")).toBe("Hello");
  });

  it("rejects empty and oversized pilot uploads", () => {
    expect(() => decodeUpload("data:text/plain;base64,")).toThrow("between 1 byte and 5 MB");
    const oversized = Buffer.alloc(MAX_PILOT_UPLOAD_BYTES + 1).toString("base64");
    expect(() => decodeUpload(`data:application/pdf;base64,${oversized}`)).toThrow("between 1 byte and 5 MB");
  });

  it("keeps storage filenames safe and content hashes deterministic", () => {
    expect(safeFileName("Q4 / board: review?.pdf")).toBe("Q4 _ board_ review_.pdf");
    expect(safeFileName("../../Board pack 2026.pdf")).toContain("Board pack 2026.pdf");
    expect(safeFileName("../../Board pack 2026.pdf")).not.toContain("/");
    expect(contentHash(Buffer.from("same source"))).toBe(contentHash(Buffer.from("same source")));
    expect(contentHash(Buffer.from("same source"))).not.toBe(contentHash(Buffer.from("different source")));
  });

  it("exposes a monotonic server-side compile milestone contract", () => {
    expect(COMPILE_STAGES).toEqual(["intake", "scan", "dedupe", "graph"]);
    expect(COMPILE_STAGES.map(stageProgress)).toEqual([12, 38, 68, 100]);
  });

  it("prefers a review-selected non-duplicate source and falls back safely", () => {
    const sources = [
      { id: 3, duplicateOfId: 1 },
      { id: 2, duplicateOfId: null },
      { id: 1, duplicateOfId: null },
    ];
    expect(selectPrimarySource(sources, 1)).toEqual({ source: sources[2], selection: "review-selected" });
    expect(selectPrimarySource(sources, 3)).toEqual({ source: sources[1], selection: "automatic" });
    expect(selectPrimarySource(sources, null)).toEqual({ source: sources[1], selection: "automatic" });
  });
});
