import { describe, expect, it } from "vitest";

import {
  displayDocumentMetadata,
  normalizedDocumentVersion,
} from "@/lib/document-metadata";

describe("displayDocumentMetadata", () => {
  it("keeps source format separate from semantic classification", () => {
    expect(displayDocumentMetadata("pdf", "research_note")).toEqual({
      fileType: "PDF",
      semanticType: "research note",
      semanticClassificationAvailable: true,
    });
  });

  it("uses honest fallback labels when metadata is absent", () => {
    expect(displayDocumentMetadata(" ", null)).toEqual({
      fileType: "Unknown",
      semanticType: "Not classified",
      semanticClassificationAvailable: false,
    });
  });
});

describe("normalizedDocumentVersion", () => {
  it("prefers the top-level immutable job version", () => {
    expect(normalizedDocumentVersion(3, 2)).toBe(3);
  });

  it("falls back to the nested document version", () => {
    expect(normalizedDocumentVersion(undefined, 4)).toBe(4);
  });

  it("rejects absent and invalid version values", () => {
    expect(normalizedDocumentVersion(0, -1)).toBeUndefined();
    expect(normalizedDocumentVersion(Number.NaN, undefined)).toBeUndefined();
  });
});
